// -*- c++ -*-

#include "workload/common/SnnAccelBackend.h"
#include "workload/common/SnnAccelBackendContract.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnMemoryImage.h"
#include "workload/riscv_snn/RiscvSnnQueueContract.h"
#include "WorkloadConfig.h"

#include <cstddef>
#include <cstdint>

static_assert(SST::SnnDL::riscv_snn::kCommandDescriptorBytes == 64, "descriptor ABI changed");
static_assert(SST::SnnDL::riscv_snn::kCompletionEntryBytes == 16, "completion ABI changed");
static_assert(SST::SnnDL::riscv_snn::kRxDebugEntryBytes == 16, "rx debug ABI changed");
static_assert(sizeof(SST::SnnDL::riscv_snn::CommandDescriptorV1) == 64, "descriptor size must stay 64B");
static_assert(sizeof(SST::SnnDL::riscv_snn::CompletionEntryV1) == 16, "completion size must stay 16B");
static_assert(sizeof(SST::SnnDL::riscv_snn::RxDebugEntryV1) == 16, "rx debug size must stay 16B");
static_assert(offsetof(SST::SnnDL::riscv_snn::CommandDescriptorV1, token) == 0x08, "token ABI drift");
static_assert(static_cast<uint32_t>(SST::SnnDL::riscv_snn::CommandOpcode::FusedStep) == 0x20, "opcode drift");
static_assert(
    static_cast<uint32_t>(SST::SnnDL::riscv_snn::CommandOpcode::StatSnapshot) == 0x50,
    "STAT_SNAPSHOT opcode drift");
static_assert(
    static_cast<uint32_t>(
        SST::SnnDL::riscv_snn::StatSnapshotSelector::AcceptedCommands) == 0u,
    "stat snapshot accepted_commands selector drift");
static_assert(
    static_cast<uint32_t>(
        SST::SnnDL::riscv_snn::StatSnapshotSelector::CompletedCommands) == 1u,
    "stat snapshot completed_commands selector drift");
static_assert(
    static_cast<uint32_t>(
        SST::SnnDL::riscv_snn::StatSnapshotSelector::ProviderBound) == 2u,
    "stat snapshot provider_bound selector drift");
static_assert(
    static_cast<uint32_t>(SST::SnnDL::riscv_snn::ArchitecturalEvent::CmdComplete) == 0u,
    "architectural event drift");
static_assert(
    static_cast<uint32_t>(SST::SnnDL::riscv_snn::RecommendedDeliveryCause::Fault) == 28u,
    "recommended delivery cause drift");
static_assert(SST::SnnDL::riscv_snn::ticketToSlot(9, 8) == 1, "ticket-to-slot drift");
static_assert(
    SST::SnnDL::riscv_snn::architecturalEventMask(
        SST::SnnDL::riscv_snn::ArchitecturalEvent::Fault) == (1u << 2),
    "architectural event mask drift");
static_assert(
    SST::SnnDL::riscv_snn::architecturalEventW1cMask() == 0x3Fu,
    "architectural event W1C mask drift");
static_assert(
    SST::SnnDL::riscv_snn::faultAckWriteClearsVisibleRecord(0x12340000ull),
    "fault clear predicate drift");
static_assert(
    !SST::SnnDL::riscv_snn::faultAckWriteClearsVisibleRecord(0x12340001ull),
    "fault clear predicate must reject non-zero low16");
static_assert(
    SST::SnnDL::riscv_snn::descriptorReservedFlagBits(
        SST::SnnDL::riscv_snn::encodeDescriptorHeader(
            /*version=*/1,
            SST::SnnDL::riscv_snn::CommandOpcode::FusedStep,
            /*flags=*/0xFC,
            /*completion_policy=*/0,
            /*error_policy=*/0,
            static_cast<uint8_t>(SST::SnnDL::riscv_snn::kCommandDescriptorBytes))) == 0xFCu,
    "reserved flag bits must stay observable");
static_assert(
    SST::SnnDL::riscv_snn::descriptorReservedHeaderBits(0xABCD000000000000ull) == 0xABCDu,
    "reserved header bits must stay observable");
static_assert(
    SST::SnnDL::riscv_snn::faultSlot(
        SST::SnnDL::riscv_snn::encodeFaultCsr(
            SST::SnnDL::riscv_snn::FaultCode::BadPolicy,
            SST::SnnDL::riscv_snn::FaultSource::Descriptor,
            /*slot=*/7,
            /*aux=*/0x12345678u)) == 7u,
    "fault slot packing drift");
static_assert(
    SST::SnnDL::riscv_snn::faultAux(
        SST::SnnDL::riscv_snn::encodeFaultCsr(
            SST::SnnDL::riscv_snn::FaultCode::BadFlags,
            SST::SnnDL::riscv_snn::FaultSource::Descriptor,
            /*slot=*/3,
            /*aux=*/0x89ABCDEFu)) == 0x89ABCDEFu,
    "fault aux packing drift");
static_assert(
    SST::SnnDL::riscv_snn::completionFaultSnapshot(0x89ABCDEFu, 0x01234567u) ==
        0x0123456789ABCDEFull,
    "completion fault snapshot packing drift");
static_assert(
    SST::SnnDL::riscv_snn::opcodeHasStrongCommitBoundary(
        SST::SnnDL::riscv_snn::CommandOpcode::FusedStep),
    "FUSED_STEP must stay the strong completion opcode");
static_assert(
    SST::SnnDL::riscv_snn::opcodeIsRxDebugOnly(
        SST::SnnDL::riscv_snn::CommandOpcode::RxDebugPop),
    "RX_DEBUG_POP must stay debug-only");
static_assert(
    !SST::SnnDL::riscv_snn::opcodeHasStrongCommitBoundary(
        SST::SnnDL::riscv_snn::CommandOpcode::RxDebugPop),
    "RX debug opcodes must not join the strong completion path");
static_assert(
    SST::SnnDL::riscv_snn::statSnapshotSelectorRaw(
        SST::SnnDL::riscv_snn::makeStatSnapshotSelectorArg0(
            SST::SnnDL::riscv_snn::StatSnapshotSelector::ProviderBound)) == 2u,
    "stat snapshot selector arg0 packing drift");
static_assert(
    SST::SnnDL::riscv_snn::decodeStatSnapshotResult(
        SST::SnnDL::riscv_snn::statSnapshotResultAux0(0x0123456789ABCDEFull),
        SST::SnnDL::riscv_snn::statSnapshotResultAux1(0x0123456789ABCDEFull)) ==
        0x0123456789ABCDEFull,
    "stat snapshot aux surface drift");
static_assert(
    SST::SnnDL::riscv_snn::statSnapshotSelectorIsKnown(0u) &&
        SST::SnnDL::riscv_snn::statSnapshotSelectorIsKnown(1u) &&
        SST::SnnDL::riscv_snn::statSnapshotSelectorIsKnown(2u),
    "known stat snapshot selectors must remain stable");
static_assert(
    !SST::SnnDL::riscv_snn::statSnapshotSelectorIsKnown(3u),
    "unknown stat snapshot selectors must stay invalid");
static_assert(
    SST::SnnDL::riscv_snn::statSnapshotCompletedCommandsVisibleValue(7u) == 7u,
    "completed_commands stat snapshot must expose the published completion count");
static_assert(
    SST::SnnDL::riscv_snn::statSnapshotProviderBoundVisibleValue(false) == 0u &&
        SST::SnnDL::riscv_snn::statSnapshotProviderBoundVisibleValue(true) == 1u,
    "provider_bound stat snapshot must stay a runtime-bridge visibility bit");
static_assert(
    SST::SnnDL::riscv_snn::statSnapshotSuccessExtraEventMask() == 0u,
    "stat snapshot success must not request extra architectural events");
int main(int argc, char** argv) {
    (void)argc;
    (void)argv;
    if (SST::SnnDL::workloadKindFromString("riscv_snn") != SST::SnnDL::WorkloadKind::RiscvSnn) {
        return 1;
    }
    SST::SnnDL::riscv_snn::RiscvSnnMemoryImage memory_image;
    SST::SnnDL::riscv_snn::RiscvSnnQueueContract queues;
    SST::SnnDL::SnnAccelCommand stat_command;
    stat_command.ticket = 7;
    stat_command.version = 1;
    stat_command.opcode =
        static_cast<uint8_t>(SST::SnnDL::riscv_snn::CommandOpcode::StatSnapshot);
    stat_command.desc_bytes = SST::SnnDL::riscv_snn::kCommandDescriptorBytes;
    stat_command.token = 0x42;
    stat_command.arg0 = SST::SnnDL::riscv_snn::makeStatSnapshotSelectorArg0(
        SST::SnnDL::riscv_snn::StatSnapshotSelector::CompletedCommands);
    uint64_t stat_value = 0;
    (void)queues.configure(8, 8, 4);
    if (!SST::SnnDL::tryResolveSnnAccelStatSnapshotValue(
            stat_command,
            /*accepted_commands=*/5,
            /*completed_commands=*/9,
            /*provider_bound=*/1,
            stat_value) ||
        stat_value != SST::SnnDL::riscv_snn::statSnapshotCompletedCommandsVisibleValue(9u)) {
        return 2;
    }
    stat_command.arg0 = SST::SnnDL::riscv_snn::makeStatSnapshotSelectorArg0(
        SST::SnnDL::riscv_snn::StatSnapshotSelector::ProviderBound);
    if (!SST::SnnDL::tryResolveSnnAccelStatSnapshotValue(
            stat_command,
            /*accepted_commands=*/5,
            /*completed_commands=*/9,
            /*provider_bound=*/SST::SnnDL::riscv_snn::statSnapshotProviderBoundVisibleValue(true),
            stat_value) ||
        stat_value != 1u) {
        return 3;
    }
    stat_command.arg0 = 0xDEADu;
    if (SST::SnnDL::tryResolveSnnAccelStatSnapshotValue(
            stat_command,
            /*accepted_commands=*/5,
            /*completed_commands=*/9,
            /*provider_bound=*/1,
            stat_value) ||
        stat_value != 0u) {
        return 4;
    }
    stat_command.arg0 = SST::SnnDL::riscv_snn::makeStatSnapshotSelectorArg0(
        SST::SnnDL::riscv_snn::StatSnapshotSelector::AcceptedCommands);
    const SST::SnnDL::SnnAccelCompletion stat_completion =
        SST::SnnDL::makeSnnAccelStatSnapshotCompletion(stat_command, 0x0123456789ABCDEFull);
    if ((stat_completion.event_mask &
         SST::SnnDL::riscv_snn::eventMask(
             SST::SnnDL::riscv_snn::EventBit::BarrierRelease)) != 0u) {
        return 5;
    }
    if (SST::SnnDL::riscv_snn::decodeStatSnapshotResult(
            stat_completion.aux0,
            stat_completion.aux1) != 0x0123456789ABCDEFull) {
        return 6;
    }
    (void)memory_image;
    (void)queues;
    return 0;
}
