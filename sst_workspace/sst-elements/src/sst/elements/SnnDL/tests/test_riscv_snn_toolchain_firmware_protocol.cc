// -*- c++ -*-

#include "api/ICoreWorkload.h"
#include "api/ISnnAccelRuntimeServices.h"
#include "workload/common/SnnAccelBackend.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnFirmwareLoader.h"
#include "workload/riscv_snn/RiscvSnnHart.h"
#include "workload/riscv_snn/RiscvSnnIss.h"
#include "workload/riscv_snn/RiscvSnnMemoryImage.h"
#include "workload/riscv_snn/RiscvSnnQueueContract.h"
#include "workload/riscv_snn/RiscvSnnSampleFirmware.h"

#include <cassert>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <map>
#include <string>
#include <vector>

namespace {

using namespace SST::SnnDL;
using namespace SST::SnnDL::riscv_snn;

constexpr uint64_t kCmdqBase = 0x0;
constexpr uint64_t kCmpqBase = 0x1000;
constexpr uint64_t kStatSnapshotRefExpectedAux = 1;
constexpr uint64_t kStatSnapshotRefSuccessCode = 0xA1;

class FakeRuntimeServices final : public ISnnAccelRuntimeServices {
public:
    bool runtimeBridgeReady() const override { return ready; }

    bool tickRuntime(uint64_t now_cycle) override {
        last_cycle = now_cycle;
        ++tick_count;
        if (remaining_runtime_ticks > 0) {
            --remaining_runtime_ticks;
            return true;
        }
        return false;
    }

    bool deliverIngressPacket(NocPacketEvent* packet) override {
        (void)packet;
        ++packet_count;
        return packet_accept;
    }

    bool hasRuntimeWork() const override { return remaining_runtime_ticks > 0; }

    double runtimeUtilization() const override { return tick_count == 0 ? 0.0 : 1.0; }

    void snapshotRuntimeStats(std::map<std::string, uint64_t>& stats) const override {
        stats["fake_tick_count"] = tick_count;
        stats["fake_packet_count"] = packet_count;
        stats["fake_last_cycle"] = last_cycle;
    }

    bool ready = true;
    bool packet_accept = true;
    uint32_t remaining_runtime_ticks = 0;
    uint64_t tick_count = 0;
    uint64_t packet_count = 0;
    uint64_t last_cycle = 0;
};

bool runFirmwareSlice(RiscvSnnHart& hart, RiscvSnnIss& iss, uint64_t& retired) {
    bool did_work = false;
    for (uint32_t i = 0; i < 8; ++i) {
        const RiscvSnnIss::StepResult step = iss.step(hart);
        if (!step.retired) break;
        ++retired;
        did_work = true;
        if (step.stop_reason != RiscvSnnIss::StopReason::None) break;
    }
    return did_work;
}

bool publishCompletionToHart(RiscvSnnHart& hart,
                             RiscvSnnQueueContract& queues,
                             uint64_t cmpq_base,
                             const SnnAccelCompletion& completion,
                             uint64_t& out_fault_csr) {
    uint32_t raised_events = 0;
    if (!queues.publishCompletion(completion, raised_events)) return false;

    CompletionEntryV1 entry{};
    entry.token = static_cast<uint32_t>(completion.token & 0xFFFFFFFFu);
    entry.status_code = completion.status_code;
    entry.aux0 = completion.aux0;
    entry.aux1 = completion.aux1;
    const uint64_t slot = ticketToSlot(queues.cmpTail() - 1, queues.cmpEntries());
    if (!hart.storeBytes(
            cmpq_base + slot * static_cast<uint64_t>(kCompletionEntryBytes),
            &entry,
            sizeof(entry))) {
        return false;
    }

    out_fault_csr = 0;
    if (completion.status_code !=
        encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success)) {
        out_fault_csr =
            (static_cast<uint64_t>(completion.aux1) << 32) |
            static_cast<uint64_t>(completion.aux0);
        hart.writeCsr(kCsrMsnnFault, out_fault_csr);
    }
    hart.writeCsr(kCsrMsnnCmpqTail, queues.cmpTail());
    hart.raiseArchitecturalEvents(raised_events);
    return true;
}

struct FirmwareRunResult {
    CompletionEntryV1 final_completion{};
    std::vector<CompletionEntryV1> completion_trace{};
    uint64_t submitted_commands = 0;
    uint64_t visible_completions = 0;
    uint64_t consumed_completions = 0;
    uint64_t retired_instructions = 0;
    uint64_t visible_fault_csr = 0;
    uint64_t pending_events = 0;
    uint64_t cmd_head = 0;
    uint64_t cmd_tail = 0;
    uint64_t cmp_head = 0;
    uint64_t cmp_tail = 0;
    uint64_t gpr7 = 0;
    bool halted = false;
    uint32_t committed_seq = 0;
};

bool runFirmwareImage(const RiscvSnnMemoryImage& image,
                      FirmwareRunResult& out,
                      std::string& error,
                      bool use_runtime_bridge_backend = false) {
    out = FirmwareRunResult{};
    error.clear();

    RiscvSnnHart hart;
    hart.reset(image.entry_pc);
    if (!hart.loadMemoryImage(image, /*capacity_bytes=*/64 * 1024, error)) {
        return false;
    }

    RiscvSnnQueueContract queues;
    if (!queues.configure(/*cmd_entries=*/64, /*cmp_entries=*/64, /*rx_entries=*/16)) {
        error = "failed to configure queues";
        return false;
    }

    hart.writeCsr(kCsrMsnnCmdqBase, kCmdqBase);
    hart.writeCsr(kCsrMsnnCmdqSize, queues.cmdEntries());
    hart.writeCsr(kCsrMsnnCmdqHead, queues.cmdHead());
    hart.writeCsr(kCsrMsnnCmdqTail, queues.cmdTail());
    hart.writeCsr(kCsrMsnnCmpqBase, kCmpqBase);
    hart.writeCsr(kCsrMsnnCmpqSize, queues.cmpEntries());
    hart.writeCsr(kCsrMsnnCmpqHead, queues.cmpHead());
    hart.writeCsr(kCsrMsnnCmpqTail, queues.cmpTail());

    std::unique_ptr<SnnAccelBackend> backend;
    FakeRuntimeServices runtime_services;
    ICoreWorkload::Runtime runtime{};
    SnnAccelBackend::Config backend_cfg;
    if (use_runtime_bridge_backend) {
        backend = makeSnnAccelBackendByName("runtime_bridge");
        runtime.accel_runtime = &runtime_services;
        backend_cfg.runtime = runtime;
        backend_cfg.backend_name = "runtime_bridge";
    } else {
        backend = makeNullSnnAccelBackend();
        backend_cfg.backend_name = "null";
    }
    backend->configure(backend_cfg);
    std::deque<SnnAccelCommand> pending_completion_commands;

    RiscvSnnIss iss;
    for (uint64_t cycle = 0; cycle < 64; ++cycle) {
        (void)runFirmwareSlice(hart, iss, out.retired_instructions);

        while (queues.cmdTail() < hart.readCsr(kCsrMsnnCmdqTail)) {
            CommandDescriptorV1 desc{};
            const uint64_t slot = ticketToSlot(queues.cmdTail(), queues.cmdEntries());
            if (!hart.loadBytes(
                    kCmdqBase + slot * static_cast<uint64_t>(kCommandDescriptorBytes),
                    &desc,
                    sizeof(desc))) {
                error = "failed to load command descriptor from hart memory";
                return false;
            }
            uint64_t ticket = 0;
            if (!queues.enqueueCommand(desc, ticket)) {
                error = "failed to enqueue command";
                return false;
            }
            ++out.submitted_commands;
            hart.writeCsr(kCsrMsnnCmdqTail, queues.cmdTail());
        }

        while (true) {
            SnnAccelCommand command;
            if (!queues.peekCommand(command)) break;
            if (!backend->submitCommand(command)) break;
            if (!queues.acceptCommand(command.ticket)) {
                error = "failed to accept command";
                return false;
            }
            pending_completion_commands.push_back(command);
            hart.writeCsr(kCsrMsnnCmdqHead, queues.cmdHead());
        }

        (void)backend->tick(cycle);

        while (true) {
            SnnAccelCompletion completion;
            if (!backend->pollCompletion(completion)) break;
            if (pending_completion_commands.empty()) {
                error = "completion returned without tracked accepted command";
                return false;
            }
            pending_completion_commands.pop_front();
            if (!publishCompletionToHart(
                    hart,
                    queues,
                    kCmpqBase,
                    completion,
                    out.visible_fault_csr)) {
                error = "failed to publish completion to hart";
                return false;
            }
            ++out.visible_completions;
            out.completion_trace.push_back(
                CompletionEntryV1{
                    static_cast<uint32_t>(completion.token & 0xFFFFFFFFu),
                    completion.status_code,
                    completion.aux0,
                    completion.aux1,
                });
        }

        (void)runFirmwareSlice(hart, iss, out.retired_instructions);

        while (queues.cmpHead() < hart.readCsr(kCsrMsnnCmpqHead)) {
            CompletionEntryV1 completion{};
            if (!queues.consumeCompletion(completion)) {
                error = "failed to consume completion";
                return false;
            }
            ++out.consumed_completions;
            hart.writeCsr(kCsrMsnnCmpqHead, queues.cmpHead());
        }

        if (hart.isHalted()) break;
    }

    out.pending_events = hart.pendingEvents();
    out.cmd_head = queues.cmdHead();
    out.cmd_tail = queues.cmdTail();
    out.cmp_head = queues.cmpHead();
    out.cmp_tail = queues.cmpTail();

    const uint64_t final_cmp_slot =
        (out.cmp_tail == 0) ? 0 : ticketToSlot(out.cmp_tail - 1, queues.cmpEntries());
    if (!hart.loadBytes(
            kCmpqBase + final_cmp_slot * static_cast<uint64_t>(kCompletionEntryBytes),
            &out.final_completion,
            sizeof(out.final_completion))) {
        error = "failed to load final completion entry";
        return false;
    }

    out.gpr7 = hart.gpr(7);
    out.halted = hart.isHalted();
    out.committed_seq = backend->readArchitecturalStepState().committed_seq;
    return true;
}

std::filesystem::path findRepoRoot(std::string& error) {
    namespace fs = std::filesystem;

    fs::path cursor = fs::current_path();
    while (true) {
        if (fs::exists(cursor / "riscv_snn_isa_lab" / "firmware")) {
            return cursor;
        }
        const fs::path parent = cursor.parent_path();
        if (parent == cursor) break;
        cursor = parent;
    }

    error = "failed to locate repo root containing riscv_snn_isa_lab/firmware";
    return {};
}

bool runToolchainFirmwareProgram(const std::string& program,
                                 FirmwareRunResult& out,
                                 std::string& error) {
    namespace fs = std::filesystem;

    const fs::path repo_root = findRepoRoot(error);
    if (!error.empty()) return false;

    const fs::path elf_path = repo_root / "riscv_snn_isa_lab" / "firmware" / (program + ".elf");
    if (!fs::exists(elf_path)) {
        error = "missing toolchain firmware ELF: " + elf_path.string();
        return false;
    }

    RiscvSnnMemoryImage image;
    if (!RiscvSnnFirmwareLoader::loadElf64(elf_path.string(), image, error)) {
        return false;
    }

    const bool use_runtime_bridge_backend =
        program == "stat_snapshot_provider_bound_ref_toolchain";
    return runFirmwareImage(
        image,
        out,
        error,
        use_runtime_bridge_backend);
}

} // namespace

int main() {
    std::string error;

    FirmwareRunResult toolchain_success_result;
    assert(runToolchainFirmwareProgram(
        "external_dyn_desc_ref_toolchain",
        toolchain_success_result,
        error));
    assert(error.empty());
    assert(toolchain_success_result.submitted_commands == 1);
    assert(toolchain_success_result.visible_completions == 1);
    assert(toolchain_success_result.consumed_completions == 1);
    assert(toolchain_success_result.final_completion.token == 1u);
    assert(
        toolchain_success_result.final_completion.status_code ==
        encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success));
    assert(toolchain_success_result.visible_fault_csr == 0u);
    assert(toolchain_success_result.pending_events == 0);
    assert(toolchain_success_result.halted);
    assert(toolchain_success_result.gpr7 == 0x33u);
    assert(toolchain_success_result.committed_seq == 1);

    FirmwareRunResult toolchain_fault_ref_result;
    assert(runToolchainFirmwareProgram(
        "external_dyn_desc_fault_ref_toolchain",
        toolchain_fault_ref_result,
        error));
    assert(error.empty());
    assert(toolchain_fault_ref_result.submitted_commands == 1);
    assert(toolchain_fault_ref_result.visible_completions == 1);
    assert(toolchain_fault_ref_result.consumed_completions == 1);
    assert(toolchain_fault_ref_result.final_completion.token == 1u);
    assert(
        toolchain_fault_ref_result.final_completion.status_code ==
        samplefwv1::kExternalDynDescFaultRefExpectedStatus);
    assert(
        toolchain_fault_ref_result.visible_fault_csr ==
        samplefwv1::kExternalDynDescFaultRefExpectedFaultCsr);
    assert(toolchain_fault_ref_result.completion_trace.size() == 1);
    assert(
        completionFaultSnapshot(toolchain_fault_ref_result.completion_trace[0]) ==
        samplefwv1::kExternalDynDescFaultRefExpectedFaultCsr);
    assert(toolchain_fault_ref_result.pending_events == 0);
    assert(toolchain_fault_ref_result.halted);
    assert(
        toolchain_fault_ref_result.gpr7 ==
        static_cast<uint64_t>(samplefwv1::kExternalDynDescFaultRefSuccessCode));
    assert(toolchain_fault_ref_result.committed_seq == 0);

    FirmwareRunResult toolchain_bad_policy_result;
    assert(runToolchainFirmwareProgram(
        "external_dyn_desc_bad_policy_ref_toolchain",
        toolchain_bad_policy_result,
        error));
    assert(error.empty());
    assert(toolchain_bad_policy_result.submitted_commands == 1);
    assert(toolchain_bad_policy_result.visible_completions == 1);
    assert(toolchain_bad_policy_result.consumed_completions == 1);
    assert(toolchain_bad_policy_result.final_completion.token == 1u);
    assert(
        toolchain_bad_policy_result.final_completion.status_code ==
        samplefwv1::kExternalDynDescBadPolicyRefExpectedStatus);
    assert(
        toolchain_bad_policy_result.visible_fault_csr ==
        samplefwv1::kExternalDynDescBadPolicyRefExpectedFaultCsr);
    assert(toolchain_bad_policy_result.completion_trace.size() == 1);
    assert(
        completionFaultSnapshot(toolchain_bad_policy_result.completion_trace[0]) ==
        samplefwv1::kExternalDynDescBadPolicyRefExpectedFaultCsr);
    assert(toolchain_bad_policy_result.pending_events == 0);
    assert(toolchain_bad_policy_result.halted);
    assert(
        toolchain_bad_policy_result.gpr7 ==
        static_cast<uint64_t>(samplefwv1::kExternalDynDescBadPolicyRefSuccessCode));
    assert(toolchain_bad_policy_result.committed_seq == 0);

    FirmwareRunResult toolchain_fault_rearm_result;
    assert(runToolchainFirmwareProgram(
        "external_dyn_desc_fault_rearm_ref_toolchain",
        toolchain_fault_rearm_result,
        error));
    assert(error.empty());
    assert(toolchain_fault_rearm_result.submitted_commands == 2);
    assert(toolchain_fault_rearm_result.visible_completions == 2);
    assert(toolchain_fault_rearm_result.consumed_completions == 2);
    assert(toolchain_fault_rearm_result.final_completion.token == 2u);
    assert(
        toolchain_fault_rearm_result.final_completion.status_code ==
        samplefwv1::kExternalDynDescBadPolicyRefExpectedStatus);
    assert(
        toolchain_fault_rearm_result.visible_fault_csr ==
        samplefwv1::kExternalDynDescFaultRearmRefSecondExpectedFaultCsr);
    assert(toolchain_fault_rearm_result.completion_trace.size() == 2);
    assert(
        completionFaultSnapshot(toolchain_fault_rearm_result.completion_trace[0]) ==
        samplefwv1::kExternalDynDescFaultRefExpectedFaultCsr);
    assert(
        completionFaultSnapshot(toolchain_fault_rearm_result.completion_trace[1]) ==
        samplefwv1::kExternalDynDescFaultRearmRefSecondExpectedFaultCsr);
    assert(toolchain_fault_rearm_result.pending_events == 0);
    assert(toolchain_fault_rearm_result.halted);
    assert(
        toolchain_fault_rearm_result.gpr7 ==
        static_cast<uint64_t>(samplefwv1::kExternalDynDescFaultRearmRefSuccessCode));
    assert(toolchain_fault_rearm_result.committed_seq == 0);

    FirmwareRunResult toolchain_fault_overwrite_chain_result;
    assert(runToolchainFirmwareProgram(
        "external_dyn_desc_fault_overwrite_chain_ref_toolchain",
        toolchain_fault_overwrite_chain_result,
        error));
    assert(error.empty());
    assert(toolchain_fault_overwrite_chain_result.submitted_commands == 3);
    assert(toolchain_fault_overwrite_chain_result.visible_completions == 3);
    assert(toolchain_fault_overwrite_chain_result.consumed_completions == 3);
    assert(toolchain_fault_overwrite_chain_result.final_completion.token == 3u);
    assert(
        toolchain_fault_overwrite_chain_result.final_completion.status_code ==
        samplefwv1::kExternalDynDescFaultRefExpectedStatus);
    assert(
        toolchain_fault_overwrite_chain_result.visible_fault_csr ==
        samplefwv1::kExternalDynDescFaultOverwriteChainRefThirdExpectedFaultCsr);
    assert(toolchain_fault_overwrite_chain_result.completion_trace.size() == 3);
    assert(
        completionFaultSnapshot(toolchain_fault_overwrite_chain_result.completion_trace[0]) ==
        samplefwv1::kExternalDynDescFaultRefExpectedFaultCsr);
    assert(
        completionFaultSnapshot(toolchain_fault_overwrite_chain_result.completion_trace[1]) ==
        samplefwv1::kExternalDynDescFaultOverwriteChainRefSecondExpectedFaultCsr);
    assert(
        completionFaultSnapshot(toolchain_fault_overwrite_chain_result.completion_trace[2]) ==
        samplefwv1::kExternalDynDescFaultOverwriteChainRefThirdExpectedFaultCsr);
    assert(toolchain_fault_overwrite_chain_result.pending_events == 0);
    assert(toolchain_fault_overwrite_chain_result.halted);
    assert(
        toolchain_fault_overwrite_chain_result.gpr7 ==
        static_cast<uint64_t>(samplefwv1::kExternalDynDescFaultOverwriteChainRefSuccessCode));
    assert(toolchain_fault_overwrite_chain_result.committed_seq == 0);

    FirmwareRunResult toolchain_stat_snapshot_result;
    assert(runToolchainFirmwareProgram(
        "stat_snapshot_ref_toolchain",
        toolchain_stat_snapshot_result,
        error));
    assert(error.empty());
    assert(toolchain_stat_snapshot_result.submitted_commands == 1);
    assert(toolchain_stat_snapshot_result.visible_completions == 1);
    assert(toolchain_stat_snapshot_result.consumed_completions == 1);
    assert(toolchain_stat_snapshot_result.final_completion.token == 1u);
    assert(
        toolchain_stat_snapshot_result.final_completion.status_code ==
        encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success));
    assert(toolchain_stat_snapshot_result.final_completion.aux0 == kStatSnapshotRefExpectedAux);
    assert(toolchain_stat_snapshot_result.final_completion.aux1 == 0u);
    assert(toolchain_stat_snapshot_result.completion_trace.size() == 1);
    assert(toolchain_stat_snapshot_result.completion_trace[0].aux0 == kStatSnapshotRefExpectedAux);
    assert(toolchain_stat_snapshot_result.completion_trace[0].aux1 == 0u);
    assert(toolchain_stat_snapshot_result.visible_fault_csr == 0u);
    assert(toolchain_stat_snapshot_result.pending_events == 0);
    assert(toolchain_stat_snapshot_result.halted);
    assert(toolchain_stat_snapshot_result.gpr7 == kStatSnapshotRefSuccessCode);
    assert(toolchain_stat_snapshot_result.committed_seq == 0);

    FirmwareRunResult toolchain_stat_snapshot_completed_result;
    assert(runToolchainFirmwareProgram(
        "stat_snapshot_completed_ref_toolchain",
        toolchain_stat_snapshot_completed_result,
        error));
    assert(error.empty());
    assert(toolchain_stat_snapshot_completed_result.submitted_commands == 2);
    assert(toolchain_stat_snapshot_completed_result.visible_completions == 2);
    assert(toolchain_stat_snapshot_completed_result.consumed_completions == 2);
    assert(toolchain_stat_snapshot_completed_result.final_completion.token == 2u);
    assert(
        toolchain_stat_snapshot_completed_result.final_completion.status_code ==
        encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success));
    assert(toolchain_stat_snapshot_completed_result.final_completion.aux0 == 1u);
    assert(toolchain_stat_snapshot_completed_result.final_completion.aux1 == 0u);
    assert(toolchain_stat_snapshot_completed_result.completion_trace.size() == 2);
    assert(toolchain_stat_snapshot_completed_result.completion_trace[0].aux0 == 0u);
    assert(toolchain_stat_snapshot_completed_result.completion_trace[0].aux1 == 0u);
    assert(toolchain_stat_snapshot_completed_result.completion_trace[1].aux0 == 1u);
    assert(toolchain_stat_snapshot_completed_result.completion_trace[1].aux1 == 0u);
    assert(toolchain_stat_snapshot_completed_result.visible_fault_csr == 0u);
    assert(toolchain_stat_snapshot_completed_result.pending_events == 0);
    assert(toolchain_stat_snapshot_completed_result.halted);
    assert(toolchain_stat_snapshot_completed_result.gpr7 == 0xB1u);
    assert(toolchain_stat_snapshot_completed_result.committed_seq == 1u);

    FirmwareRunResult toolchain_stat_snapshot_provider_bound_result;
    assert(runToolchainFirmwareProgram(
        "stat_snapshot_provider_bound_ref_toolchain",
        toolchain_stat_snapshot_provider_bound_result,
        error));
    assert(error.empty());
    assert(toolchain_stat_snapshot_provider_bound_result.submitted_commands == 1);
    assert(toolchain_stat_snapshot_provider_bound_result.visible_completions == 1);
    assert(toolchain_stat_snapshot_provider_bound_result.consumed_completions == 1);
    assert(toolchain_stat_snapshot_provider_bound_result.final_completion.token == 1u);
    assert(
        toolchain_stat_snapshot_provider_bound_result.final_completion.status_code ==
        encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success));
    assert(toolchain_stat_snapshot_provider_bound_result.final_completion.aux0 == 1u);
    assert(toolchain_stat_snapshot_provider_bound_result.final_completion.aux1 == 0u);
    assert(toolchain_stat_snapshot_provider_bound_result.completion_trace.size() == 1);
    assert(toolchain_stat_snapshot_provider_bound_result.completion_trace[0].aux0 == 1u);
    assert(toolchain_stat_snapshot_provider_bound_result.completion_trace[0].aux1 == 0u);
    assert(toolchain_stat_snapshot_provider_bound_result.visible_fault_csr == 0u);
    assert(toolchain_stat_snapshot_provider_bound_result.pending_events == 0);
    assert(toolchain_stat_snapshot_provider_bound_result.halted);
    assert(toolchain_stat_snapshot_provider_bound_result.gpr7 == 0xC1u);
    assert(toolchain_stat_snapshot_provider_bound_result.committed_seq == 0);

    return 0;
}
