// -*- c++ -*-

#include "workload/common/SnnAccelBackend.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnHart.h"
#include "workload/riscv_snn/RiscvSnnIss.h"
#include "workload/riscv_snn/RiscvSnnMemoryImage.h"
#include "workload/riscv_snn/RiscvSnnQueueContract.h"
#include "workload/riscv_snn/RiscvSnnSampleFirmware.h"

#include <cassert>
#include <cstdint>
#include <string>
#include <vector>

namespace {

using namespace SST::SnnDL;
using namespace SST::SnnDL::riscv_snn;
constexpr uint64_t kCmdqBase = 0x0;
constexpr uint64_t kCmpqBase = 0x1000;

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
                      std::string& error) {
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

    auto backend = makeNullSnnAccelBackend();
    backend->configure(SnnAccelBackend::Config{});

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
            hart.writeCsr(kCsrMsnnCmdqHead, queues.cmdHead());
        }

        (void)backend->tick(cycle);

        while (true) {
            SnnAccelCompletion completion;
            if (!backend->pollCompletion(completion)) break;
            if (!publishCompletionToHart(hart, queues, kCmpqBase, completion, out.visible_fault_csr)) {
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

bool runFirmwareProgram(const std::string& program,
                        FirmwareRunResult& out,
                        std::string& error) {
    RiscvSnnSampleProgram sample_program;
    if (!buildSampleFirmwareProgram(program, sample_program, error)) {
        return false;
    }

    RiscvSnnMemoryImage image;
    image.entry_pc = sample_program.entry_pc;
    for (const auto& seg : sample_program.segments) {
        image.segments.push_back({seg.vaddr, seg.flags, seg.file_data});
    }

    return runFirmwareImage(image, out, error);
}

} // namespace

int main() {
    std::string error;
    FirmwareRunResult success_result;
    assert(runFirmwareProgram("external_dyn_desc_ref", success_result, error));
    assert(error.empty());
    assert(success_result.submitted_commands == 1);
    assert(success_result.visible_completions == 1);
    assert(success_result.consumed_completions == 1);
    assert(success_result.final_completion.token == 1u);
    assert(success_result.final_completion.status_code ==
           encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success));
    assert(success_result.cmd_head == 1);
    assert(success_result.cmd_tail == 1);
    assert(success_result.cmp_head == 1);
    assert(success_result.cmp_tail == 1);
    assert(success_result.pending_events == 0);
    assert(success_result.halted);
    assert(success_result.gpr7 == 0x33u);
    assert(success_result.retired_instructions >= 7);
    assert(success_result.committed_seq == 1);

    FirmwareRunResult fault_ref_result;
    assert(runFirmwareProgram("external_dyn_desc_fault_ref", fault_ref_result, error));
    assert(error.empty());
    assert(fault_ref_result.submitted_commands == 1);
    assert(fault_ref_result.visible_completions == 1);
    assert(fault_ref_result.consumed_completions == 1);
    assert(fault_ref_result.final_completion.token == 1u);
    assert(
        fault_ref_result.final_completion.status_code ==
        samplefwv1::kExternalDynDescFaultRefExpectedStatus);
    assert(
        fault_ref_result.visible_fault_csr ==
        samplefwv1::kExternalDynDescFaultRefExpectedFaultCsr);
    assert(fault_ref_result.completion_trace.size() == 1);
    assert(
        completionFaultSnapshot(fault_ref_result.completion_trace[0]) ==
        samplefwv1::kExternalDynDescFaultRefExpectedFaultCsr);
    assert(fault_ref_result.pending_events == 0);
    assert(fault_ref_result.halted);
    assert(
        fault_ref_result.gpr7 ==
        static_cast<uint64_t>(samplefwv1::kExternalDynDescFaultRefSuccessCode));
    assert(fault_ref_result.committed_seq == 0);

    FirmwareRunResult bad_policy_ref_result;
    assert(runFirmwareProgram("external_dyn_desc_bad_policy_ref", bad_policy_ref_result, error));
    assert(error.empty());
    assert(bad_policy_ref_result.submitted_commands == 1);
    assert(bad_policy_ref_result.visible_completions == 1);
    assert(bad_policy_ref_result.consumed_completions == 1);
    assert(bad_policy_ref_result.final_completion.token == 1u);
    assert(
        bad_policy_ref_result.final_completion.status_code ==
        samplefwv1::kExternalDynDescBadPolicyRefExpectedStatus);
    assert(
        bad_policy_ref_result.visible_fault_csr ==
        samplefwv1::kExternalDynDescBadPolicyRefExpectedFaultCsr);
    assert(bad_policy_ref_result.completion_trace.size() == 1);
    assert(
        completionFaultSnapshot(bad_policy_ref_result.completion_trace[0]) ==
        samplefwv1::kExternalDynDescBadPolicyRefExpectedFaultCsr);
    assert(bad_policy_ref_result.pending_events == 0);
    assert(bad_policy_ref_result.halted);
    assert(
        bad_policy_ref_result.gpr7 ==
        static_cast<uint64_t>(samplefwv1::kExternalDynDescBadPolicyRefSuccessCode));
    assert(bad_policy_ref_result.committed_seq == 0);

    FirmwareRunResult fault_rearm_ref_result;
    assert(runFirmwareProgram("external_dyn_desc_fault_rearm_ref", fault_rearm_ref_result, error));
    assert(error.empty());
    assert(fault_rearm_ref_result.submitted_commands == 2);
    assert(fault_rearm_ref_result.visible_completions == 2);
    assert(fault_rearm_ref_result.consumed_completions == 2);
    assert(fault_rearm_ref_result.final_completion.token == 2u);
    assert(
        fault_rearm_ref_result.final_completion.status_code ==
        samplefwv1::kExternalDynDescBadPolicyRefExpectedStatus);
    assert(
        fault_rearm_ref_result.visible_fault_csr ==
        samplefwv1::kExternalDynDescFaultRearmRefSecondExpectedFaultCsr);
    assert(fault_rearm_ref_result.completion_trace.size() == 2);
    assert(
        completionFaultSnapshot(fault_rearm_ref_result.completion_trace[0]) ==
        samplefwv1::kExternalDynDescFaultRefExpectedFaultCsr);
    assert(
        completionFaultSnapshot(fault_rearm_ref_result.completion_trace[1]) ==
        samplefwv1::kExternalDynDescFaultRearmRefSecondExpectedFaultCsr);
    assert(fault_rearm_ref_result.pending_events == 0);
    assert(fault_rearm_ref_result.halted);
    assert(
        fault_rearm_ref_result.gpr7 ==
        static_cast<uint64_t>(samplefwv1::kExternalDynDescFaultRearmRefSuccessCode));
    assert(fault_rearm_ref_result.committed_seq == 0);

    FirmwareRunResult fault_overwrite_chain_ref_result;
    assert(runFirmwareProgram("external_dyn_desc_fault_overwrite_chain_ref", fault_overwrite_chain_ref_result, error));
    assert(error.empty());
    assert(fault_overwrite_chain_ref_result.submitted_commands == 3);
    assert(fault_overwrite_chain_ref_result.visible_completions == 3);
    assert(fault_overwrite_chain_ref_result.consumed_completions == 3);
    assert(fault_overwrite_chain_ref_result.final_completion.token == 3u);
    assert(
        fault_overwrite_chain_ref_result.final_completion.status_code ==
        samplefwv1::kExternalDynDescFaultRefExpectedStatus);
    assert(
        fault_overwrite_chain_ref_result.visible_fault_csr ==
        samplefwv1::kExternalDynDescFaultOverwriteChainRefThirdExpectedFaultCsr);
    assert(fault_overwrite_chain_ref_result.completion_trace.size() == 3);
    assert(
        completionFaultSnapshot(fault_overwrite_chain_ref_result.completion_trace[0]) ==
        samplefwv1::kExternalDynDescFaultRefExpectedFaultCsr);
    assert(
        completionFaultSnapshot(fault_overwrite_chain_ref_result.completion_trace[1]) ==
        samplefwv1::kExternalDynDescFaultOverwriteChainRefSecondExpectedFaultCsr);
    assert(
        completionFaultSnapshot(fault_overwrite_chain_ref_result.completion_trace[2]) ==
        samplefwv1::kExternalDynDescFaultOverwriteChainRefThirdExpectedFaultCsr);
    assert(fault_overwrite_chain_ref_result.pending_events == 0);
    assert(fault_overwrite_chain_ref_result.halted);
    assert(
        fault_overwrite_chain_ref_result.gpr7 ==
        static_cast<uint64_t>(samplefwv1::kExternalDynDescFaultOverwriteChainRefSuccessCode));
    assert(fault_overwrite_chain_ref_result.committed_seq == 0);

    RiscvSnnHart fault_hart;
    fault_hart.reset(/*boot_pc=*/0);
    RiscvSnnMemoryImage fault_image;
    std::string fault_error;
    assert(fault_hart.loadMemoryImage(fault_image, /*capacity_bytes=*/8 * 1024, fault_error));
    assert(fault_error.empty());
    fault_hart.writeCsr(kCsrMsnnEventEnable, eventMask(EventBit::CmdComplete) | eventMask(EventBit::Fault));

    RiscvSnnQueueContract fault_queues;
    assert(fault_queues.configure(/*cmd_entries=*/8, /*cmp_entries=*/8, /*rx_entries=*/4));

    auto fault_backend = makeNullSnnAccelBackend();
    fault_backend->configure(SnnAccelBackend::Config{});

    SnnAccelCommand bad_policy{};
    bad_policy.ticket = 0;
    bad_policy.raw_header = encodeDescriptorHeader(
        /*version=*/1,
        CommandOpcode::FusedStep,
        /*flags=*/0x4,
        /*completion_policy=*/1,
        /*error_policy=*/0,
        static_cast<uint8_t>(kCommandDescriptorBytes));
    bad_policy.version = descriptorVersion(bad_policy.raw_header);
    bad_policy.opcode = descriptorOpcodeRaw(bad_policy.raw_header);
    bad_policy.flags = descriptorFlags(bad_policy.raw_header);
    bad_policy.completion_policy = descriptorCompletionPolicy(bad_policy.raw_header);
    bad_policy.error_policy = descriptorErrorPolicy(bad_policy.raw_header);
    bad_policy.desc_bytes = descriptorBytes(bad_policy.raw_header);
    bad_policy.token = 0x44;

    assert(fault_backend->submitCommand(bad_policy));
    assert(fault_backend->tick(/*now_cycle=*/0));

    SnnAccelCompletion fault_completion{};
    assert(fault_backend->pollCompletion(fault_completion));
    assert(fault_completion.status_code ==
           encodeStatusCode(
               CompletionPrimaryStatus::BadPolicy,
               CompletionSeverity::FaultAfterAccept));
    const uint64_t expected_fault_csr = makeFaultCsrFromStatus(
        fault_completion.status_code,
        /*slot=*/0,
        /*aux=*/static_cast<uint32_t>(bad_policy.raw_header >> 32));
    assert(fault_completion.aux0 == static_cast<uint32_t>(expected_fault_csr & 0xFFFFFFFFu));
    assert(fault_completion.aux1 == static_cast<uint32_t>(expected_fault_csr >> 32));

    uint64_t visible_fault_csr = 0;
    assert(fault_hart.enterWfi());
    assert(fault_hart.isWaitingForInterrupt());
    assert(publishCompletionToHart(
        fault_hart,
        fault_queues,
        kCmpqBase,
        fault_completion,
        visible_fault_csr));
    assert(visible_fault_csr == expected_fault_csr);
    assert(fault_hart.readCsr(kCsrMsnnFault) == expected_fault_csr);
    assert(!fault_hart.isWaitingForInterrupt());
    assert((fault_hart.pendingEvents() & eventMask(EventBit::Fault)) != 0);
    assert((fault_hart.pendingEvents() & eventMask(EventBit::CmdComplete)) != 0);
    assert(!fault_hart.consumeFaultAckRequest());

    fault_hart.writeCsr(kCsrMsnnEventPending, eventMask(EventBit::CmdComplete));
    assert((fault_hart.pendingEvents() & eventMask(EventBit::CmdComplete)) == 0);
    assert((fault_hart.pendingEvents() & eventMask(EventBit::Fault)) != 0);
    assert(fault_hart.readCsr(kCsrMsnnFault) == expected_fault_csr);
    assert(!fault_hart.enterWfi());

    fault_hart.writeCsr(kCsrMsnnFault, 0x12340000ull);
    assert(fault_hart.readCsr(kCsrMsnnFault) == 0);
    assert(fault_hart.consumeFaultAckRequest());
    assert(!fault_hart.consumeFaultAckRequest());
    assert((fault_hart.pendingEvents() & eventMask(EventBit::Fault)) != 0);
    assert((fault_hart.pendingEvents() & eventMask(EventBit::CmdComplete)) == 0);
    assert(!fault_hart.enterWfi());

    fault_hart.writeCsr(kCsrMsnnEventPending, eventMask(EventBit::Fault));
    assert(fault_hart.pendingEvents() == 0);
    assert(fault_hart.enterWfi());

    fault_hart.writeCsr(kCsrMsnnEventEnable, 0);
    assert(fault_hart.wakeEligibleEvents() == 0);

    const uint32_t second_fault_status = encodeStatusCode(
        CompletionPrimaryStatus::BadPolicy,
        CompletionSeverity::FaultAfterAccept);
    const uint64_t expected_second_fault_csr = makeFaultCsrFromStatus(
        second_fault_status,
        /*slot=*/1,
        /*aux=*/0x00000004u);
    SnnAccelCompletion second_fault_completion{};
    second_fault_completion.ticket = 1;
    second_fault_completion.token = 0x55;
    second_fault_completion.status_code = second_fault_status;
    second_fault_completion.aux0 = static_cast<uint32_t>(expected_second_fault_csr & 0xFFFFFFFFu);
    second_fault_completion.aux1 = static_cast<uint32_t>(expected_second_fault_csr >> 32);
    second_fault_completion.event_mask =
        eventMask(EventBit::CmdComplete) | eventMask(EventBit::Fault);

    assert(publishCompletionToHart(
        fault_hart,
        fault_queues,
        kCmpqBase,
        second_fault_completion,
        visible_fault_csr));
    assert(visible_fault_csr == expected_second_fault_csr);
    assert(fault_hart.readCsr(kCsrMsnnFault) == expected_second_fault_csr);
    assert((fault_hart.pendingEvents() & eventMask(EventBit::CmdComplete)) != 0);
    assert((fault_hart.pendingEvents() & eventMask(EventBit::Fault)) != 0);
    assert(fault_hart.wakeEligibleEvents() == 0);
    assert(fault_hart.isWaitingForInterrupt());

    fault_hart.writeCsr(kCsrMsnnEventEnable, eventMask(EventBit::Fault));
    assert((fault_hart.wakeEligibleEvents() & eventMask(EventBit::Fault)) != 0);
    assert(!fault_hart.isWaitingForInterrupt());

    fault_hart.writeCsr(kCsrMsnnEventPending, eventMask(EventBit::CmdComplete));
    assert((fault_hart.pendingEvents() & eventMask(EventBit::CmdComplete)) == 0);
    assert((fault_hart.pendingEvents() & eventMask(EventBit::Fault)) != 0);
    assert(fault_hart.readCsr(kCsrMsnnFault) == expected_second_fault_csr);

    fault_hart.writeCsr(kCsrMsnnFault, 0);
    assert(fault_hart.readCsr(kCsrMsnnFault) == 0);
    assert(fault_hart.consumeFaultAckRequest());
    fault_hart.writeCsr(kCsrMsnnEventPending, eventMask(EventBit::Fault));
    assert(fault_hart.pendingEvents() == 0);

    return 0;
}
