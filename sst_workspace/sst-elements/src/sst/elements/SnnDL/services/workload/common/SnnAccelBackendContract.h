// -*- c++ -*-
//
// SnnAccelBackendContract:
// - `riscv_snn` control-plane 与实验 runtime/backend 共享的最小协议面。
// - Phase C 先冻结 command/completion/step-state 结构、阶段枚举与 validate helper，
//   让 null backend / runtime_bridge backend / provider 共用同一份 bit-level contract。
//

#pragma once

#include <cstdint>

#include "workload/riscv_snn/RiscvSnnAbi.h"

namespace SST { namespace SnnDL {

enum class SnnAccelRuntimePhase : uint32_t {
    Idle = 0,
    Accepted = 1,
    Executing = 2,
    OutboundDraining = 3,
    BarrierWaiting = 4,
    Completed = 5,
    Faulted = 6,
};

enum class SnnAccelCompletionVisibility : uint8_t {
    PayloadWritten = 0,
    CmpqTailPublished = 1,
    StatusVisible = 2,
    EventPendingRaised = 3,
    WakeEligible = 4,
};

struct SnnAccelCommand {
    uint64_t ticket = 0;
    uint64_t raw_header = 0;
    uint8_t version = 0;
    uint8_t opcode = 0;
    uint8_t flags = 0;
    uint8_t completion_policy = 0;
    uint8_t error_policy = 0;
    uint8_t desc_bytes = 0;
    uint64_t token = 0;
    uint64_t arg0 = 0;
    uint64_t arg1 = 0;
    uint64_t src_addr = 0;
    uint64_t dst_addr = 0;
    uint64_t len_or_count = 0;
    uint64_t dep_user = 0;
};

struct SnnAccelCompletion {
    uint64_t ticket = 0;
    uint64_t token = 0;
    uint32_t status_code = 0;
    uint32_t aux0 = 0;
    uint32_t aux1 = 0;
    uint32_t event_mask = 0;
};

struct SnnAccelStepState {
    uint32_t committed_seq = 0;
    uint32_t inflight_seq = 0;
    uint32_t phase = static_cast<uint32_t>(SnnAccelRuntimePhase::Idle);
    uint32_t last_accept_opcode = 0;
    bool busy = false;
    bool fault_valid = false;
    bool barrier_waiting = false;
    bool outbound_draining = false;
};

struct SnnAccelValidationResult {
    uint32_t status = 0;
    uint32_t aux = 0;

    bool ok() const { return status == 0; }
};

inline constexpr uint32_t accelRuntimePhaseValue(SnnAccelRuntimePhase phase) {
    return static_cast<uint32_t>(phase);
}

inline constexpr bool accelRuntimePhaseIsTerminal(SnnAccelRuntimePhase phase) {
    return phase == SnnAccelRuntimePhase::Completed || phase == SnnAccelRuntimePhase::Faulted;
}

inline constexpr bool completionVisibilityOrderIsMonotonic(SnnAccelCompletionVisibility lhs,
                                                           SnnAccelCompletionVisibility rhs) {
    return static_cast<uint8_t>(lhs) <= static_cast<uint8_t>(rhs);
}

inline constexpr bool fusedStepCompletionBoundaryReached(const SnnAccelStepState& state) {
    return accelRuntimePhaseIsTerminal(static_cast<SnnAccelRuntimePhase>(state.phase));
}

inline constexpr bool snnAccelCommandIsFusedStep(const SnnAccelCommand& command) {
    return command.opcode ==
        static_cast<uint8_t>(riscv_snn::CommandOpcode::FusedStep);
}

inline constexpr bool snnAccelCommandIsStatSnapshot(const SnnAccelCommand& command) {
    return command.opcode ==
        static_cast<uint8_t>(riscv_snn::CommandOpcode::StatSnapshot);
}

inline bool tryResolveSnnAccelStatSnapshotValue(const SnnAccelCommand& command,
                                                uint64_t accepted_commands,
                                                uint64_t completed_commands_visible,
                                                uint64_t provider_bound_visible,
                                                uint64_t& value) {
    const uint32_t selector = riscv_snn::statSnapshotSelectorRaw(command.arg0);
    if (!riscv_snn::statSnapshotSelectorIsKnown(selector)) {
        value = 0;
        return false;
    }
    switch (selector) {
    case riscv_snn::kStatSnapshotSelectorAcceptedCommands:
        value = accepted_commands;
        return true;
    case riscv_snn::kStatSnapshotSelectorCompletedCommands:
        value = riscv_snn::statSnapshotCompletedCommandsVisibleValue(
            completed_commands_visible);
        return true;
    case riscv_snn::kStatSnapshotSelectorProviderBound:
        value = provider_bound_visible;
        return true;
    default:
        value = 0;
        return false;
    }
}

inline SnnAccelValidationResult validateSnnAccelCommand(const SnnAccelCommand& command) {
    using namespace riscv_snn;

    if (command.version != 1) {
        return {
            encodeStatusCode(
                CompletionPrimaryStatus::BadVersion,
                CompletionSeverity::FaultAfterAccept),
            command.version,
        };
    }
    if (command.desc_bytes != kCommandDescriptorBytes) {
        return {
            encodeStatusCode(
                CompletionPrimaryStatus::BadDescBytes,
                CompletionSeverity::FaultAfterAccept),
            command.desc_bytes,
        };
    }
    if (command.completion_policy != 0 || command.error_policy != 0) {
        return {
            encodeStatusCode(
                CompletionPrimaryStatus::BadPolicy,
                CompletionSeverity::FaultAfterAccept),
            static_cast<uint32_t>(command.raw_header >> 32),
        };
    }
    if (descriptorReservedHeaderBits(command.raw_header) != 0) {
        return {
            encodeStatusCode(
                CompletionPrimaryStatus::BadPolicy,
                CompletionSeverity::FaultAfterAccept),
            static_cast<uint32_t>(command.raw_header >> 32),
        };
    }
    if (descriptorReservedFlagBits(command.raw_header) != 0) {
        return {
            encodeStatusCode(
                CompletionPrimaryStatus::BadFlags,
                CompletionSeverity::FaultAfterAccept),
            descriptorReservedFlagBits(command.raw_header),
        };
    }
    switch (static_cast<CommandOpcode>(command.opcode)) {
    case CommandOpcode::Nop:
    case CommandOpcode::PrefetchW:
    case CommandOpcode::FusedStep:
    case CommandOpcode::StatSnapshot:
        return {};
    default:
        return {
            encodeStatusCode(
                CompletionPrimaryStatus::BadOpcode,
                CompletionSeverity::FaultAfterAccept),
            command.opcode,
        };
    }
}

inline uint64_t makeSnnAccelFaultCsr(const SnnAccelCommand& command,
                                     uint32_t status_code,
                                     uint32_t aux) {
    return riscv_snn::makeFaultCsrFromStatus(
        status_code,
        static_cast<uint16_t>(command.ticket & 0xFFFFu),
        aux);
}

inline SnnAccelCompletion makeSnnAccelFaultCompletion(const SnnAccelCommand& command,
                                                      uint32_t status_code,
                                                      uint32_t aux,
                                                      uint32_t extra_event_mask = 0) {
    SnnAccelCompletion completion;
    completion.ticket = command.ticket;
    completion.token = command.token;
    completion.status_code = status_code;
    const uint64_t fault_csr = makeSnnAccelFaultCsr(command, status_code, aux);
    completion.aux0 = static_cast<uint32_t>(fault_csr & 0xFFFFFFFFu);
    completion.aux1 = static_cast<uint32_t>(fault_csr >> 32);
    completion.event_mask =
        riscv_snn::eventMask(riscv_snn::EventBit::CmdComplete) |
        riscv_snn::eventMask(riscv_snn::EventBit::Fault) |
        extra_event_mask;
    return completion;
}

inline SnnAccelCompletion makeSnnAccelSuccessCompletion(const SnnAccelCommand& command,
                                                        uint32_t extra_event_mask = 0,
                                                        uint32_t aux0 = 0,
                                                        uint32_t aux1 = 0) {
    SnnAccelCompletion completion;
    completion.ticket = command.ticket;
    completion.token = command.token;
    completion.status_code = riscv_snn::encodeStatusCode(
        riscv_snn::CompletionPrimaryStatus::Success,
        riscv_snn::CompletionSeverity::Success);
    completion.aux0 = aux0;
    completion.aux1 = aux1;
    completion.event_mask =
        riscv_snn::eventMask(riscv_snn::EventBit::CmdComplete) |
        extra_event_mask;
    return completion;
}

inline SnnAccelCompletion makeSnnAccelStatSnapshotCompletion(const SnnAccelCommand& command,
                                                             uint64_t value) {
    return makeSnnAccelSuccessCompletion(
        command,
        /*extra_event_mask=*/riscv_snn::statSnapshotSuccessExtraEventMask(),
        riscv_snn::statSnapshotResultAux0(value),
        riscv_snn::statSnapshotResultAux1(value));
}

}} // namespace SST::SnnDL
