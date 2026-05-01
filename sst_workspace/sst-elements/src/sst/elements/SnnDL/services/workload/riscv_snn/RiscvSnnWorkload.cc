// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/riscv_snn/RiscvSnnWorkload.h"

#include <inttypes.h>

#include <sst/core/output.h>
#include <sst/core/params.h>

#include "events/NocPacketEvent.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnFirmwareLoader.h"
#include "workload/riscv_snn/RiscvSnnShadowTransportExport.h"

namespace SST { namespace SnnDL {

namespace {

uint64_t alignUp(uint64_t value, uint64_t alignment) {
    if (alignment == 0) return value;
    const uint64_t rem = value % alignment;
    return (rem == 0) ? value : (value + alignment - rem);
}

uint64_t makeFaultCsrForLocalStatus(riscv_snn::CompletionPrimaryStatus primary,
                                    uint16_t slot,
                                    uint32_t aux) {
    return riscv_snn::makeFaultCsrFromStatus(
        riscv_snn::encodeStatusCode(
            primary,
            riscv_snn::CompletionSeverity::FaultAfterAccept),
        slot,
        aux);
}

uint64_t packFaultCsrFromCompletion(const SnnAccelCompletion& completion) {
    return riscv_snn::completionFaultSnapshot(completion.aux0, completion.aux1);
}

} // namespace

RiscvSnnWorkload::RiscvSnnWorkload()
    : backend_(makeSnnAccelBackendByName("null")) {}

void RiscvSnnWorkload::configureFromParams(const SST::Params& params) {
    firmware_elf_ = params.find<std::string>("riscv_snn_firmware_elf", firmware_elf_);
    hart_isa_ = params.find<std::string>("riscv_snn_hart_isa", hart_isa_);
    backend_name_ = params.find<std::string>("riscv_snn_backend_name", backend_name_);
    boot_addr_ = params.find<uint64_t>("riscv_snn_boot_addr", boot_addr_);
    local_mem_bytes_ = params.find<uint64_t>("riscv_snn_local_mem_bytes", local_mem_bytes_);
    cmd_queue_entries_ = params.find<uint32_t>("riscv_snn_cmd_queue_entries", cmd_queue_entries_);
    cmp_queue_entries_ = params.find<uint32_t>("riscv_snn_cmp_queue_entries", cmp_queue_entries_);
    rx_debug_queue_entries_ =
        params.find<uint32_t>("riscv_snn_rx_debug_queue_entries", rx_debug_queue_entries_);
}

void RiscvSnnWorkload::bindRuntime(const Runtime& rt) {
    rt_ = rt;
    submitted_commands_ = 0;
    accepted_commands_ = 0;
    completion_visible_count_ = 0;
    completion_consumed_count_ = 0;
    fused_step_completion_count_ = 0;
    fault_count_ = 0;
    last_fault_csr_ = 0;
    last_completion_status_ = 0;
    firmware_loaded_ = false;
    firmware_loaded_bytes_ = 0;
    firmware_retired_instructions_ = 0;
    firmware_started_count_ = 0;
    next_bootstrap_token_ = 1;
    boot_driver_.reset();
    cmd_queue_base_ = 0;
    cmp_queue_base_ = 0;
    rx_debug_queue_base_ = 0;

    hart_.reset(boot_addr_);
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnHartId, rt.core_id);
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnCfg, 0);
    hart_.writeCsrRaw(
        riscv_snn::kCsrMsnnEventEnable,
        riscv_snn::eventMask(riscv_snn::EventBit::CmdComplete) |
            riscv_snn::eventMask(riscv_snn::EventBit::BarrierRelease) |
            riscv_snn::eventMask(riscv_snn::EventBit::Fault));

    if (!queues_.configure(cmd_queue_entries_, cmp_queue_entries_, rx_debug_queue_entries_)) {
        if (rt_.log) {
            rt_.log->fatal(CALL_INFO,
                           -1,
                           "RiscvSnnWorkload fatal: queue entries must be non-zero powers of two "
                           "(cmd=%u cmp=%u rx=%u)\n",
                           cmd_queue_entries_,
                           cmp_queue_entries_,
                           rx_debug_queue_entries_);
        }
        return;
    }
    syncQueueCsrs_();
    syncStatusCsr_();

    if (!firmware_elf_.empty()) {
        riscv_snn::RiscvSnnMemoryImage image;
        std::string error;
        if (!riscv_snn::RiscvSnnFirmwareLoader::loadElf64(firmware_elf_, image, error) ||
            !hart_.loadMemoryImage(image, local_mem_bytes_, error)) {
            if (rt_.log) {
                rt_.log->fatal(CALL_INFO,
                               -1,
                               "RiscvSnnWorkload fatal: failed to load firmware ELF '%s': %s\n",
                               firmware_elf_.c_str(),
                               error.c_str());
            }
            return;
        }
        firmware_loaded_ = true;
        firmware_loaded_bytes_ = image.footprintBytes();
        boot_driver_.configureExternalFirmware();
        if (!configureFirmwareControlPlane_()) {
            return;
        }
    } else {
        boot_driver_.configureInternalSmoke();
    }

    SnnAccelBackend::Config cfg;
    cfg.runtime = rt_;
    cfg.backend_name = backend_name_;
    cfg.compute_core_impl = "default";
    backend_ = makeSnnAccelBackendByName(backend_name_);
    if (!backend_) backend_ = makeNullSnnAccelBackend();
    backend_->configure(cfg);
}

bool RiscvSnnWorkload::onClockTick(uint64_t now_cycle) {
    last_tick_cycle_ = now_cycle;
    bool did_work = false;

    if (firmware_loaded_) {
        if (tickFirmware_()) did_work = true;
        if (drainFirmwareFaultAcks_()) did_work = true;
        if (drainFirmwareSubmittedCommands_()) did_work = true;
    } else if (tickBootDriver_()) {
        did_work = true;
    }
    if (submitVisibleCommands_()) did_work = true;

    if (backend_ && backend_->tick(now_cycle)) did_work = true;
    if (drainBackendCompletions_()) did_work = true;
    if (firmware_loaded_) {
        if (tickFirmware_()) did_work = true;
        if (drainFirmwareFaultAcks_()) did_work = true;
        if (drainFirmwareSubmittedCommands_()) did_work = true;
        if (drainFirmwareCompletionAcks_()) did_work = true;
    } else if (tickBootDriver_()) {
        did_work = true;
    }

    syncStatusCsr_();
    if (did_work) ++active_cycles_;
    return did_work;
}

bool RiscvSnnWorkload::deliverPacket(NocPacketEvent* packet) {
    if (!backend_) return false;
    return backend_->injectPacket(packet);
}

bool RiscvSnnWorkload::hasWork() const {
    if (!backend_) return false;
    const SnnAccelStepState state = backend_->readArchitecturalStepState();
    return state.busy ||
        hart_.pendingEvents() != 0 ||
        (firmware_loaded_ && !hart_.isHalted() && !hart_.isWaitingForInterrupt()) ||
        !queues_.commandQueueEmpty() ||
        queues_.completionQueueNonEmpty() ||
        boot_driver_.active();
}

double RiscvSnnWorkload::getUtilization() const {
    if (last_tick_cycle_ == 0) return 0.0;
    return static_cast<double>(active_cycles_) / static_cast<double>(last_tick_cycle_);
}

void RiscvSnnWorkload::getStatistics(std::map<std::string, uint64_t>& stats) const {
    stats["riscv_snn_last_tick_cycle"] = last_tick_cycle_;
    stats["riscv_snn_active_cycles"] = active_cycles_;
    stats["riscv_snn_pending_events"] = hart_.pendingEvents();
    stats["riscv_snn_enabled_events"] = hart_.enabledEvents();
    stats["riscv_snn_waiting_for_interrupt"] = hart_.isWaitingForInterrupt() ? 1 : 0;
    stats["riscv_snn_boot_addr"] = boot_addr_;
    stats["riscv_snn_local_mem_bytes"] = local_mem_bytes_;
    stats["riscv_snn_cmd_queue_entries"] = cmd_queue_entries_;
    stats["riscv_snn_cmp_queue_entries"] = cmp_queue_entries_;
    stats["riscv_snn_rx_debug_queue_entries"] = rx_debug_queue_entries_;
    stats["riscv_snn_cmdq_base"] = cmd_queue_base_;
    stats["riscv_snn_cmpq_base"] = cmp_queue_base_;
    stats["riscv_snn_rxq_base"] = rx_debug_queue_base_;
    stats["riscv_snn_firmware_elf_present"] = firmware_elf_.empty() ? 0 : 1;
    stats["riscv_snn_firmware_loaded"] = firmware_loaded_ ? 1 : 0;
    stats["riscv_snn_firmware_loaded_bytes"] = firmware_loaded_bytes_;
    stats["riscv_snn_firmware_started_count"] = firmware_started_count_;
    stats["riscv_snn_firmware_retired_instructions"] = firmware_retired_instructions_;
    stats["riscv_snn_firmware_halted"] = hart_.isHalted() ? 1 : 0;
    stats["riscv_snn_cmdq_head"] = queues_.cmdHead();
    stats["riscv_snn_cmdq_tail"] = queues_.cmdTail();
    stats["riscv_snn_cmpq_head"] = queues_.cmpHead();
    stats["riscv_snn_cmpq_tail"] = queues_.cmpTail();
    stats["riscv_snn_submitted_commands"] = submitted_commands_;
    stats["riscv_snn_accepted_commands"] = accepted_commands_;
    stats["riscv_snn_completion_visible_count"] = completion_visible_count_;
    stats["riscv_snn_completion_consumed_count"] = completion_consumed_count_;
    stats["riscv_snn_fused_step_completion_count"] = fused_step_completion_count_;
    stats["riscv_snn_fault_count"] = fault_count_;
    stats["riscv_snn_last_fault_code"] = static_cast<uint64_t>(last_fault_csr_ & 0xFFFFFFFFu);
    stats["riscv_snn_last_fault_csr"] = last_fault_csr_;
    stats["riscv_snn_last_completion_status"] = last_completion_status_;
    stats["riscv_snn_boot_mode"] = static_cast<uint64_t>(boot_driver_.mode());
    stats["riscv_snn_boot_driver_state"] = static_cast<uint64_t>(boot_driver_.state());
    stats["riscv_snn_backend_runtime_bridge"] = backend_name_ == "runtime_bridge" ? 1u : 0u;
    if (backend_) backend_->snapshotStats(stats);
    exportRiscvSnnRuntimeBridgeShadowTransportStats(stats);
}

void RiscvSnnWorkload::syncQueueCsrs_() {
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnCmdqBase, cmd_queue_base_);
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnCmdqSize, queues_.cmdEntries());
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnCmdqHead, queues_.cmdHead());
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnCmdqTail, queues_.cmdTail());

    hart_.writeCsrRaw(riscv_snn::kCsrMsnnCmpqBase, cmp_queue_base_);
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnCmpqSize, queues_.cmpEntries());
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnCmpqHead, queues_.cmpHead());
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnCmpqTail, queues_.cmpTail());

    hart_.writeCsrRaw(riscv_snn::kCsrMsnnRxqBase, rx_debug_queue_base_);
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnRxqSize, queues_.rxEntries());
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnRxqHead, queues_.rxHead());
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnRxqTail, queues_.rxTail());
}

void RiscvSnnWorkload::syncStatusCsr_() {
    uint64_t status = 0;
    const SnnAccelStepState step = backend_ ? backend_->readArchitecturalStepState() : SnnAccelStepState{};
    if (step.busy) status |= (1ull << 0);
    if (queues_.commandQueueFull()) status |= (1ull << 1);
    if (queues_.completionQueueNonEmpty()) status |= (1ull << 2);
    if (queues_.rxTail() != queues_.rxHead()) status |= (1ull << 3);
    if (step.barrier_waiting) status |= (1ull << 4);
    if (last_fault_csr_ != 0) status |= (1ull << 5);
    if (step.busy || step.inflight_seq != step.committed_seq) status |= (1ull << 6);
    if (step.outbound_draining) status |= (1ull << 7);
    status |= (static_cast<uint64_t>(queues_.lastAcceptedOpcode()) << 16);
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnStatus, status);
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnFault, last_fault_csr_);
    hart_.writeCsrRaw(riscv_snn::kCsrMsnnStep, step.committed_seq);
}

bool RiscvSnnWorkload::configureFirmwareControlPlane_() {
    cmd_queue_base_ = 0;
    cmp_queue_base_ = alignUp(
        static_cast<uint64_t>(cmd_queue_entries_) * riscv_snn::kCommandDescriptorBytes,
        4096);
    rx_debug_queue_base_ = alignUp(
        cmp_queue_base_ +
            static_cast<uint64_t>(cmp_queue_entries_) * riscv_snn::kCompletionEntryBytes,
        4096);
    const uint64_t required_bytes =
        rx_debug_queue_base_ +
        static_cast<uint64_t>(rx_debug_queue_entries_) * riscv_snn::kRxDebugEntryBytes;
    if (required_bytes > local_mem_bytes_) {
        if (rt_.log) {
            rt_.log->fatal(CALL_INFO,
                           -1,
                           "RiscvSnnWorkload fatal: local memory too small for firmware "
                           "control-plane layout (need=%" PRIu64 " have=%" PRIu64 ")\n",
                           required_bytes,
                           local_mem_bytes_);
        }
        return false;
    }
    syncQueueCsrs_();
    syncStatusCsr_();
    return true;
}

bool RiscvSnnWorkload::tickFirmware_() {
    if (!firmware_loaded_ || hart_.isHalted()) return false;

    bool did_work = false;
    for (uint32_t i = 0; i < firmware_issue_budget_per_tick_; ++i) {
        const RiscvSnnIss::StepResult result = iss_.step(hart_);
        if (!result.retired) {
            if (result.stop_reason == RiscvSnnIss::StopReason::Fault) {
                last_fault_csr_ = makeFaultCsrForLocalStatus(
                    riscv_snn::CompletionPrimaryStatus::BackendInternalError,
                    /*slot=*/0,
                    static_cast<uint32_t>(hart_.pc()));
                hart_.raiseArchitecturalEvents(riscv_snn::eventMask(riscv_snn::EventBit::Fault));
                hart_.halt();
                ++fault_count_;
            }
            break;
        }

        ++firmware_retired_instructions_;
        if (firmware_started_count_ == 0) {
            firmware_started_count_ = 1;
        }
        did_work = true;
        if (result.stop_reason != RiscvSnnIss::StopReason::None) break;
    }
    return did_work;
}

bool RiscvSnnWorkload::drainFirmwareFaultAcks_() {
    if (!hart_.consumeFaultAckRequest()) return false;
    last_fault_csr_ = 0;
    return true;
}

bool RiscvSnnWorkload::drainFirmwareSubmittedCommands_() {
    if (!firmware_loaded_) return false;

    const uint64_t sw_tail = hart_.readCsr(riscv_snn::kCsrMsnnCmdqTail);
    bool did_work = false;
    while (queues_.cmdTail() < sw_tail) {
        riscv_snn::CommandDescriptorV1 desc{};
        const uint64_t slot = riscv_snn::ticketToSlot(queues_.cmdTail(), queues_.cmdEntries());
        const uint64_t addr =
            cmd_queue_base_ + slot * static_cast<uint64_t>(riscv_snn::kCommandDescriptorBytes);
        if (!hart_.loadBytes(addr, &desc, sizeof(desc))) {
            last_fault_csr_ = makeFaultCsrForLocalStatus(
                riscv_snn::CompletionPrimaryStatus::MemorySemanticFault,
                static_cast<uint16_t>(slot),
                static_cast<uint32_t>(addr));
            hart_.raiseArchitecturalEvents(riscv_snn::eventMask(riscv_snn::EventBit::Fault));
            ++fault_count_;
            break;
        }

        uint64_t ticket = 0;
        if (!queues_.enqueueCommand(desc, ticket)) {
            last_fault_csr_ = makeFaultCsrForLocalStatus(
                riscv_snn::CompletionPrimaryStatus::CommandQueueOverflow,
                static_cast<uint16_t>(slot),
                queues_.cmdEntries());
            hart_.raiseArchitecturalEvents(riscv_snn::eventMask(riscv_snn::EventBit::Fault));
            ++fault_count_;
            break;
        }
        ++submitted_commands_;
        did_work = true;
    }

    if (did_work) syncQueueCsrs_();
    return did_work;
}

bool RiscvSnnWorkload::drainFirmwareCompletionAcks_() {
    if (!firmware_loaded_) return false;

    const uint64_t sw_head = hart_.readCsr(riscv_snn::kCsrMsnnCmpqHead);
    bool did_work = false;
    while (queues_.cmpHead() < sw_head) {
        riscv_snn::CompletionEntryV1 completion{};
        if (!queues_.consumeCompletion(completion)) break;
        ++completion_consumed_count_;
        did_work = true;
    }

    if (did_work) syncQueueCsrs_();
    return did_work;
}

bool RiscvSnnWorkload::submitVisibleCommands_() {
    if (!backend_) return false;
    bool did_work = false;
    while (true) {
        SnnAccelCommand command;
        if (!queues_.peekCommand(command)) break;
        if (!backend_->submitCommand(command)) break;
        if (!queues_.acceptCommand(command.ticket)) break;
        ++accepted_commands_;
        did_work = true;
        syncQueueCsrs_();
        syncStatusCsr_();
    }
    return did_work;
}

bool RiscvSnnWorkload::drainBackendCompletions_() {
    if (!backend_) return false;
    bool did_work = false;
    while (true) {
        SnnAccelCompletion completion;
        if (!backend_->pollCompletion(completion)) break;
        const uint64_t completion_slot = riscv_snn::ticketToSlot(queues_.cmpTail(), queues_.cmpEntries());

        uint32_t raised_events = 0;
        if (!queues_.publishCompletion(completion, raised_events)) {
            last_fault_csr_ = makeFaultCsrForLocalStatus(
                riscv_snn::CompletionPrimaryStatus::CompletionQueueOverflow,
                static_cast<uint16_t>(completion_slot),
                queues_.cmpEntries());
            hart_.raiseArchitecturalEvents(riscv_snn::eventMask(riscv_snn::EventBit::Fault));
            ++fault_count_;
            break;
        }

        if (firmware_loaded_) {
            riscv_snn::CompletionEntryV1 entry;
            entry.token = static_cast<uint32_t>(completion.token & 0xFFFFFFFFu);
            entry.status_code = completion.status_code;
            entry.aux0 = completion.aux0;
            entry.aux1 = completion.aux1;
            const uint64_t visible_slot =
                riscv_snn::ticketToSlot(queues_.cmpTail() - 1, queues_.cmpEntries());
            const uint64_t addr = cmp_queue_base_ +
                visible_slot * static_cast<uint64_t>(riscv_snn::kCompletionEntryBytes);
            if (!hart_.storeBytes(addr, &entry, sizeof(entry))) {
                last_fault_csr_ = makeFaultCsrForLocalStatus(
                    riscv_snn::CompletionPrimaryStatus::MemorySemanticFault,
                    static_cast<uint16_t>(visible_slot),
                    static_cast<uint32_t>(addr));
                hart_.raiseArchitecturalEvents(riscv_snn::eventMask(riscv_snn::EventBit::Fault));
                ++fault_count_;
                break;
            }
        }

        last_completion_status_ = completion.status_code;
        ++completion_visible_count_;
        if (completion.status_code !=
            riscv_snn::encodeStatusCode(
                riscv_snn::CompletionPrimaryStatus::Success,
                riscv_snn::CompletionSeverity::Success)) {
            last_fault_csr_ = packFaultCsrFromCompletion(completion);
            ++fault_count_;
        }
        if ((raised_events & riscv_snn::eventMask(riscv_snn::EventBit::BarrierRelease)) != 0) {
            ++fused_step_completion_count_;
        }
        if (raised_events != 0) {
            hart_.raiseArchitecturalEvents(raised_events);
        }

        did_work = true;
        syncQueueCsrs_();
        syncStatusCsr_();
    }
    return did_work;
}

bool RiscvSnnWorkload::tickBootDriver_() {
    RiscvSnnBootDriver::TickResult result;
    const bool did_work = boot_driver_.onTick(hart_, queues_, next_bootstrap_token_, result);
    if (!did_work) return false;

    if (result.enqueued_internal_command) {
        ++submitted_commands_;
    }
    if (result.consumed_completion) {
        ++completion_consumed_count_;
        last_completion_status_ = result.last_completion_status;
    }
    syncQueueCsrs_();
    syncStatusCsr_();
    return true;
}

}} // namespace SST::SnnDL
