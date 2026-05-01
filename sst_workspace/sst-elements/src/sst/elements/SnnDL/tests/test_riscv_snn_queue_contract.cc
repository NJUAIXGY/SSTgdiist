// -*- c++ -*-

#include "workload/common/SnnAccelBackend.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnQueueContract.h"

#include <cassert>
#include <cstdint>

int main() {
    using namespace SST::SnnDL;
    using namespace SST::SnnDL::riscv_snn;

    RiscvSnnQueueContract queues;
    assert(queues.configure(/*cmd_entries=*/8, /*cmp_entries=*/8, /*rx_entries=*/4));

    CommandDescriptorV1 desc;
    desc.hdr0 = encodeDescriptorHeader(
        /*version=*/1,
        CommandOpcode::FusedStep,
        /*flags=*/0,
        /*completion_policy=*/0,
        /*error_policy=*/0,
        /*desc_bytes=*/kCommandDescriptorBytes);
    desc.token = 0x1234;

    uint64_t ticket = 0;
    assert(queues.enqueueCommand(desc, ticket));
    assert(ticket == 0);
    assert(queues.cmdHead() == 0);
    assert(queues.cmdTail() == 1);

    SnnAccelCommand command;
    assert(queues.peekCommand(command));
    assert(command.ticket == 0);
    assert(command.token == 0x1234);
    assert(command.opcode == static_cast<uint8_t>(CommandOpcode::FusedStep));
    assert(queues.acceptCommand(command.ticket));
    assert(queues.cmdHead() == 1);
    assert(descriptorReservedFlagBits(command.raw_header) == 0u);
    assert(descriptorReservedHeaderBits(command.raw_header) == 0u);
    assert(opcodeHasStrongCommitBoundary(CommandOpcode::FusedStep));
    assert(!opcodeIsRxDebugOnly(CommandOpcode::FusedStep));
    assert(opcodeIsRxDebugOnly(CommandOpcode::RxDebugPop));

    SnnAccelCompletion completion;
    completion.token = command.token;
    completion.status_code = encodeStatusCode(
        CompletionPrimaryStatus::Success,
        CompletionSeverity::Success);
    completion.event_mask =
        eventMask(EventBit::CmdComplete) | eventMask(EventBit::BarrierRelease);

    uint32_t raised_events = 0;
    assert(queues.publishCompletion(completion, raised_events));
    assert(raised_events ==
           (eventMask(EventBit::CmdComplete) | eventMask(EventBit::BarrierRelease)));
    assert(queues.cmpTail() == 1);

    CompletionEntryV1 visible{};
    assert(queues.peekCompletion(visible));
    assert(visible.token == 0x1234u);
    assert(visible.status_code == completion.status_code);

    CompletionEntryV1 consumed{};
    assert(queues.consumeCompletion(consumed));
    assert(consumed.token == 0x1234u);
    assert(queues.cmpHead() == 1);

    CommandDescriptorV1 bad_policy_desc{};
    bad_policy_desc.hdr0 = encodeDescriptorHeader(
        /*version=*/1,
        CommandOpcode::FusedStep,
        /*flags=*/0x4,
        /*completion_policy=*/1,
        /*error_policy=*/0,
        /*desc_bytes=*/kCommandDescriptorBytes);
    assert(descriptorReservedFlagBits(bad_policy_desc.hdr0) == 0x4u);
    const uint64_t expected_fault = makeFaultCsrFromStatus(
        encodeStatusCode(
            CompletionPrimaryStatus::BadPolicy,
            CompletionSeverity::FaultAfterAccept),
        /*slot=*/2,
        /*aux=*/bad_policy_desc.hdr0 >> 32);
    assert(faultCode(expected_fault) == FaultCode::BadPolicy);
    assert(faultSource(expected_fault) == FaultSource::Descriptor);
    assert(faultSlot(expected_fault) == 2u);

    SnnAccelCompletion first_fault_completion;
    first_fault_completion.token = 0x44;
    first_fault_completion.status_code = encodeStatusCode(
        CompletionPrimaryStatus::BadFlags,
        CompletionSeverity::FaultAfterAccept);
    const uint64_t expected_first_fault = makeFaultCsrFromStatus(
        first_fault_completion.status_code,
        /*slot=*/0,
        /*aux=*/0x4u);
    first_fault_completion.aux0 = static_cast<uint32_t>(expected_first_fault & 0xFFFFFFFFu);
    first_fault_completion.aux1 = static_cast<uint32_t>(expected_first_fault >> 32);
    first_fault_completion.event_mask = eventMask(EventBit::CmdComplete) | eventMask(EventBit::Fault);

    SnnAccelCompletion second_fault_completion;
    second_fault_completion.token = 0x45;
    second_fault_completion.status_code = encodeStatusCode(
        CompletionPrimaryStatus::BadPolicy,
        CompletionSeverity::FaultAfterAccept);
    const uint64_t expected_second_fault = makeFaultCsrFromStatus(
        second_fault_completion.status_code,
        /*slot=*/1,
        /*aux=*/0x00004000u);
    second_fault_completion.aux0 = static_cast<uint32_t>(expected_second_fault & 0xFFFFFFFFu);
    second_fault_completion.aux1 = static_cast<uint32_t>(expected_second_fault >> 32);
    second_fault_completion.event_mask = eventMask(EventBit::CmdComplete) | eventMask(EventBit::Fault);

    assert(queues.publishCompletion(first_fault_completion, raised_events));
    assert(queues.publishCompletion(second_fault_completion, raised_events));

    CompletionEntryV1 first_fault_entry{};
    assert(queues.consumeCompletion(first_fault_entry));
    uint64_t visible_fault_csr = 0;
    visible_fault_csr = completionFaultSnapshot(first_fault_entry);
    assert(visible_fault_csr == expected_first_fault);
    visible_fault_csr = 0;
    assert(visible_fault_csr == 0);
    assert(completionFaultSnapshot(first_fault_entry) == expected_first_fault);

    CompletionEntryV1 second_fault_entry{};
    assert(queues.consumeCompletion(second_fault_entry));
    visible_fault_csr = completionFaultSnapshot(second_fault_entry);
    assert(visible_fault_csr == expected_second_fault);
    assert(completionFaultSnapshot(second_fault_entry) == expected_second_fault);

    return 0;
}
