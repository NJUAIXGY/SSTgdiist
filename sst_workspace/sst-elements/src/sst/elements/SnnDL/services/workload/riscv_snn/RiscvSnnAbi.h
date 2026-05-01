// -*- c++ -*-
//
// RiscvSnnAbi:
// - `riscv_snn` v1.1 草案的最小代码内 ABI 定义。
// - 这里只先冻结结构布局与常量，不在 v0 skeleton 中承诺完整行为。
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL { namespace riscv_snn {

inline constexpr uint32_t kCommandDescriptorBytes = 64;
inline constexpr uint32_t kCompletionEntryBytes = 16;
inline constexpr uint32_t kRxDebugEntryBytes = 16;

inline constexpr uint32_t kCsrMsnnCfg = 0xBC0;
inline constexpr uint32_t kCsrMsnnStatus = 0xBC1;
inline constexpr uint32_t kCsrMsnnFeat = 0xBC2;
inline constexpr uint32_t kCsrMsnnHartId = 0xBC3;
inline constexpr uint32_t kCsrMsnnCmdqBase = 0xBC8;
inline constexpr uint32_t kCsrMsnnCmdqSize = 0xBC9;
inline constexpr uint32_t kCsrMsnnCmdqHead = 0xBCA;
inline constexpr uint32_t kCsrMsnnCmdqTail = 0xBCB;
inline constexpr uint32_t kCsrMsnnCmpqBase = 0xBCC;
inline constexpr uint32_t kCsrMsnnCmpqSize = 0xBCD;
inline constexpr uint32_t kCsrMsnnCmpqHead = 0xBCE;
inline constexpr uint32_t kCsrMsnnCmpqTail = 0xBCF;
inline constexpr uint32_t kCsrMsnnRxqBase = 0xBD0;
inline constexpr uint32_t kCsrMsnnRxqSize = 0xBD1;
inline constexpr uint32_t kCsrMsnnRxqHead = 0xBD2;
inline constexpr uint32_t kCsrMsnnRxqTail = 0xBD3;
inline constexpr uint32_t kCsrMsnnEventEnable = 0xBD8;
inline constexpr uint32_t kCsrMsnnEventPending = 0xBD9;
inline constexpr uint32_t kCsrMsnnStep = 0xBDA;
inline constexpr uint32_t kCsrMsnnFault = 0xBDB;

enum class ArchitecturalEvent : uint8_t {
    CmdComplete = 0,
    BarrierRelease = 1,
    Fault = 2,
    RxDebug = 3,
    PrefetchDone = 4,
    Debug = 5,
};

using EventBit = ArchitecturalEvent;

enum class RecommendedDeliveryCause : uint8_t {
    CmdComplete = 24,
    RxDebug = 25,
    PrefetchDone = 26,
    BarrierRelease = 27,
    Fault = 28,
    Debug = 29,
    Reserved = 31,
};

enum class CommandOpcode : uint8_t {
    Nop = 0x00,
    PrefetchW = 0x01,
    StateLoad = 0x02,
    StateStore = 0x03,
    PhaseGather = 0x10,
    PhaseApply = 0x11,
    PhaseScatter = 0x12,
    FusedStep = 0x20,
    EgressCtrl = 0x30,
    RxDebugPop = 0x31,
    BarrierArrive = 0x40,
    StatSnapshot = 0x50,
};

enum class StatSnapshotSelector : uint32_t {
    AcceptedCommands = 0,
    CompletedCommands = 1,
    ProviderBound = 2,
};

inline constexpr uint32_t kStatSnapshotSelectorAcceptedCommands =
    static_cast<uint32_t>(StatSnapshotSelector::AcceptedCommands);
inline constexpr uint32_t kStatSnapshotSelectorBackendAcceptedCommands =
    kStatSnapshotSelectorAcceptedCommands;
inline constexpr uint32_t kStatSnapshotSelectorCompletedCommands =
    static_cast<uint32_t>(StatSnapshotSelector::CompletedCommands);
inline constexpr uint32_t kStatSnapshotSelectorBackendCompletedCommands =
    kStatSnapshotSelectorCompletedCommands;
inline constexpr uint32_t kStatSnapshotSelectorProviderBound =
    static_cast<uint32_t>(StatSnapshotSelector::ProviderBound);
inline constexpr uint32_t kStatSnapshotSelectorRuntimeBridgeProviderBound =
    kStatSnapshotSelectorProviderBound;

enum class DescriptorFlagBit : uint8_t {
    IrqHint = 0,
    TraceHint = 1,
};

enum class CompletionSeverity : uint8_t {
    Success = 0,
    RejectedBeforeAccept = 1,
    FaultAfterAccept = 2,
};

enum class CompletionPrimaryStatus : uint8_t {
    Success = 0x00,
    BadVersion = 0x01,
    BadDescBytes = 0x02,
    BadOpcode = 0x03,
    BadFlags = 0x04,
    BadAlignment = 0x05,
    BadPolicy = 0x06,
    CommandQueueOverflow = 0x10,
    CompletionQueueOverflow = 0x11,
    IllegalPhaseTransition = 0x20,
    BarrierProtocolViolation = 0x21,
    MemorySemanticFault = 0x30,
    BackendInternalError = 0x31,
};

enum class FaultCode : uint8_t {
    None = static_cast<uint8_t>(CompletionPrimaryStatus::Success),
    BadVersion = static_cast<uint8_t>(CompletionPrimaryStatus::BadVersion),
    BadDescBytes = static_cast<uint8_t>(CompletionPrimaryStatus::BadDescBytes),
    BadOpcode = static_cast<uint8_t>(CompletionPrimaryStatus::BadOpcode),
    BadFlags = static_cast<uint8_t>(CompletionPrimaryStatus::BadFlags),
    BadAlignment = static_cast<uint8_t>(CompletionPrimaryStatus::BadAlignment),
    BadPolicy = static_cast<uint8_t>(CompletionPrimaryStatus::BadPolicy),
    CommandQueueOverflow = static_cast<uint8_t>(CompletionPrimaryStatus::CommandQueueOverflow),
    CompletionQueueOverflow = static_cast<uint8_t>(CompletionPrimaryStatus::CompletionQueueOverflow),
    IllegalPhaseTransition = static_cast<uint8_t>(CompletionPrimaryStatus::IllegalPhaseTransition),
    BarrierProtocolViolation =
        static_cast<uint8_t>(CompletionPrimaryStatus::BarrierProtocolViolation),
    MemorySemanticFault = static_cast<uint8_t>(CompletionPrimaryStatus::MemorySemanticFault),
    BackendInternalError = static_cast<uint8_t>(CompletionPrimaryStatus::BackendInternalError),
};

enum class FaultSource : uint8_t {
    None = 0,
    Descriptor = 1,
    Queue = 2,
    Phase = 3,
    Barrier = 4,
    Memory = 5,
    BackendInternal = 6,
};

struct CommandDescriptorV1 {
    uint64_t hdr0 = 0;
    uint64_t token = 0;
    uint64_t arg0 = 0;
    uint64_t arg1 = 0;
    uint64_t src_addr = 0;
    uint64_t dst_addr = 0;
    uint64_t len_or_count = 0;
    uint64_t dep_user = 0;
};

struct CompletionEntryV1 {
    uint32_t token = 0;
    uint32_t status_code = 0;
    uint32_t aux0 = 0;
    uint32_t aux1 = 0;
};

struct RxDebugEntryV1 {
    uint32_t rx_type = 0;
    uint32_t seq = 0;
    uint32_t count_or_bytes = 0;
    uint32_t ptr_or_aux = 0;
};

inline constexpr uint32_t architecturalEventMask(ArchitecturalEvent bit) {
    return 1u << static_cast<uint32_t>(bit);
}

inline constexpr uint32_t eventMask(EventBit bit) {
    return architecturalEventMask(bit);
}

inline constexpr uint32_t architecturalEventW1cMask() {
    return 0x3Fu;
}

inline constexpr RecommendedDeliveryCause recommendedDeliveryCause(ArchitecturalEvent bit) {
    switch (bit) {
    case ArchitecturalEvent::CmdComplete:
        return RecommendedDeliveryCause::CmdComplete;
    case ArchitecturalEvent::RxDebug:
        return RecommendedDeliveryCause::RxDebug;
    case ArchitecturalEvent::PrefetchDone:
        return RecommendedDeliveryCause::PrefetchDone;
    case ArchitecturalEvent::BarrierRelease:
        return RecommendedDeliveryCause::BarrierRelease;
    case ArchitecturalEvent::Fault:
        return RecommendedDeliveryCause::Fault;
    case ArchitecturalEvent::Debug:
        return RecommendedDeliveryCause::Debug;
    default:
        return RecommendedDeliveryCause::Reserved;
    }
}

inline constexpr uint8_t descriptorVersion(uint64_t hdr0) {
    return static_cast<uint8_t>(hdr0 & 0xFFu);
}

inline constexpr uint8_t descriptorOpcodeRaw(uint64_t hdr0) {
    return static_cast<uint8_t>((hdr0 >> 8) & 0xFFu);
}

inline constexpr uint8_t descriptorFlags(uint64_t hdr0) {
    return static_cast<uint8_t>((hdr0 >> 16) & 0xFFu);
}

inline constexpr uint64_t makeStatSnapshotSelectorArg0(StatSnapshotSelector selector) {
    return static_cast<uint64_t>(static_cast<uint32_t>(selector));
}

inline constexpr uint32_t statSnapshotSelectorRaw(uint64_t arg0) {
    return static_cast<uint32_t>(arg0 & 0xFFFFFFFFu);
}

inline constexpr bool statSnapshotSelectorIsKnown(uint32_t selector) {
    return selector == kStatSnapshotSelectorAcceptedCommands ||
        selector == kStatSnapshotSelectorCompletedCommands ||
        selector == kStatSnapshotSelectorProviderBound;
}

// `CompletedCommands` exposes the number of successful completions that were already
// architecturally visible before publishing the current STAT_SNAPSHOT completion.
inline constexpr uint64_t statSnapshotCompletedCommandsVisibleValue(
    uint64_t published_successful_completions) {
    return published_successful_completions;
}

// `ProviderBound` is a runtime-bridge visibility bit, not a generic backend liveness metric.
inline constexpr uint64_t statSnapshotProviderBoundVisibleValue(bool runtime_bridge_ready) {
    return runtime_bridge_ready ? 1ull : 0ull;
}

// Successful STAT_SNAPSHOT completions wake software via CmdComplete only.
inline constexpr uint32_t statSnapshotSuccessExtraEventMask() {
    return 0u;
}

inline constexpr uint32_t statSnapshotResultAux0(uint64_t value) {
    return static_cast<uint32_t>(value & 0xFFFFFFFFu);
}

inline constexpr uint32_t statSnapshotResultAux1(uint64_t value) {
    return static_cast<uint32_t>((value >> 32) & 0xFFFFFFFFu);
}

inline constexpr uint64_t decodeStatSnapshotResult(uint32_t aux0, uint32_t aux1) {
    return static_cast<uint64_t>(aux0) | (static_cast<uint64_t>(aux1) << 32);
}

inline constexpr uint8_t descriptorCompletionPolicy(uint64_t hdr0) {
    return static_cast<uint8_t>((hdr0 >> 24) & 0xFFu);
}

inline constexpr uint8_t descriptorErrorPolicy(uint64_t hdr0) {
    return static_cast<uint8_t>((hdr0 >> 32) & 0xFFu);
}

inline constexpr uint8_t descriptorBytes(uint64_t hdr0) {
    return static_cast<uint8_t>((hdr0 >> 40) & 0xFFu);
}

inline constexpr uint8_t descriptorReservedFlagBits(uint64_t hdr0) {
    return static_cast<uint8_t>(descriptorFlags(hdr0) & 0xFCu);
}

inline constexpr uint16_t descriptorReservedHeaderBits(uint64_t hdr0) {
    return static_cast<uint16_t>((hdr0 >> 48) & 0xFFFFu);
}

inline constexpr uint64_t encodeDescriptorHeader(uint8_t version,
                                                 CommandOpcode opcode,
                                                 uint8_t flags,
                                                 uint8_t completion_policy,
                                                 uint8_t error_policy,
                                                 uint8_t desc_bytes) {
    return static_cast<uint64_t>(version)
        | (static_cast<uint64_t>(static_cast<uint8_t>(opcode)) << 8)
        | (static_cast<uint64_t>(flags) << 16)
        | (static_cast<uint64_t>(completion_policy) << 24)
        | (static_cast<uint64_t>(error_policy) << 32)
        | (static_cast<uint64_t>(desc_bytes) << 40);
}

inline constexpr uint32_t encodeStatusCode(CompletionPrimaryStatus primary,
                                           CompletionSeverity severity) {
    return static_cast<uint32_t>(static_cast<uint8_t>(primary))
        | (static_cast<uint32_t>(static_cast<uint8_t>(severity)) << 8);
}

inline constexpr CompletionPrimaryStatus completionPrimaryStatus(uint32_t status_code) {
    return static_cast<CompletionPrimaryStatus>(status_code & 0xFFu);
}

inline constexpr CompletionSeverity completionSeverity(uint32_t status_code) {
    return static_cast<CompletionSeverity>((status_code >> 8) & 0xFFu);
}

inline constexpr FaultCode faultCodeFromStatus(uint32_t status_code) {
    return static_cast<FaultCode>(static_cast<uint8_t>(completionPrimaryStatus(status_code)));
}

inline constexpr FaultSource faultSourceFromStatus(uint32_t status_code) {
    switch (completionPrimaryStatus(status_code)) {
    case CompletionPrimaryStatus::BadVersion:
    case CompletionPrimaryStatus::BadDescBytes:
    case CompletionPrimaryStatus::BadOpcode:
    case CompletionPrimaryStatus::BadFlags:
    case CompletionPrimaryStatus::BadAlignment:
    case CompletionPrimaryStatus::BadPolicy:
        return FaultSource::Descriptor;
    case CompletionPrimaryStatus::CommandQueueOverflow:
    case CompletionPrimaryStatus::CompletionQueueOverflow:
        return FaultSource::Queue;
    case CompletionPrimaryStatus::IllegalPhaseTransition:
        return FaultSource::Phase;
    case CompletionPrimaryStatus::BarrierProtocolViolation:
        return FaultSource::Barrier;
    case CompletionPrimaryStatus::MemorySemanticFault:
        return FaultSource::Memory;
    case CompletionPrimaryStatus::BackendInternalError:
        return FaultSource::BackendInternal;
    case CompletionPrimaryStatus::Success:
    default:
        return FaultSource::None;
    }
}

inline constexpr uint64_t encodeFaultCsr(FaultCode code,
                                         FaultSource source,
                                         uint16_t slot,
                                         uint32_t aux) {
    return static_cast<uint64_t>(static_cast<uint8_t>(code))
        | (static_cast<uint64_t>(static_cast<uint8_t>(source)) << 8)
        | (static_cast<uint64_t>(slot) << 16)
        | (static_cast<uint64_t>(aux) << 32);
}

inline constexpr FaultCode faultCode(uint64_t fault_csr) {
    return static_cast<FaultCode>(fault_csr & 0xFFu);
}

inline constexpr FaultSource faultSource(uint64_t fault_csr) {
    return static_cast<FaultSource>((fault_csr >> 8) & 0xFFu);
}

inline constexpr uint16_t faultSlot(uint64_t fault_csr) {
    return static_cast<uint16_t>((fault_csr >> 16) & 0xFFFFu);
}

inline constexpr uint32_t faultAux(uint64_t fault_csr) {
    return static_cast<uint32_t>(fault_csr >> 32);
}

inline constexpr bool faultAckWriteClearsVisibleRecord(uint64_t value) {
    return (value & 0xFFFFu) == 0;
}

inline constexpr uint64_t completionFaultSnapshot(uint32_t aux0, uint32_t aux1) {
    return (static_cast<uint64_t>(aux1) << 32) | static_cast<uint64_t>(aux0);
}

inline constexpr uint64_t completionFaultSnapshot(const CompletionEntryV1& entry) {
    return completionFaultSnapshot(entry.aux0, entry.aux1);
}

inline constexpr uint64_t makeFaultCsrFromStatus(uint32_t status_code,
                                                 uint16_t slot,
                                                 uint32_t aux) {
    if (completionSeverity(status_code) == CompletionSeverity::Success &&
        completionPrimaryStatus(status_code) == CompletionPrimaryStatus::Success) {
        return 0;
    }
    return encodeFaultCsr(
        faultCodeFromStatus(status_code),
        faultSourceFromStatus(status_code),
        slot,
        aux);
}

inline constexpr bool opcodeHasStrongCommitBoundary(CommandOpcode opcode) {
    return opcode == CommandOpcode::FusedStep;
}

inline constexpr bool opcodeIsRxDebugOnly(CommandOpcode opcode) {
    return opcode == CommandOpcode::RxDebugPop;
}

static_assert(sizeof(CommandDescriptorV1) == kCommandDescriptorBytes, "descriptor ABI drift");
static_assert(sizeof(CompletionEntryV1) == kCompletionEntryBytes, "completion ABI drift");
static_assert(sizeof(RxDebugEntryV1) == kRxDebugEntryBytes, "rx debug ABI drift");

}}} // namespace SST::SnnDL::riscv_snn
