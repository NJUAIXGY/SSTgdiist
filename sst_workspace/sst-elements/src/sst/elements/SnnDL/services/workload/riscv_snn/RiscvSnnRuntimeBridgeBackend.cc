// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.h"

#include "api/ISnnAccelRuntimeServices.h"

namespace SST { namespace SnnDL {

namespace {

uint32_t backendInternalStatus() {
    return riscv_snn::encodeStatusCode(
        riscv_snn::CompletionPrimaryStatus::BackendInternalError,
        riscv_snn::CompletionSeverity::FaultAfterAccept);
}

uint32_t invalidStatSnapshotSelectorStatus() {
    return riscv_snn::encodeStatusCode(
        riscv_snn::CompletionPrimaryStatus::BadPolicy,
        riscv_snn::CompletionSeverity::FaultAfterAccept);
}

} // namespace

void RiscvSnnRuntimeBridgeBackend::configure(const Config& cfg) {
    cfg_ = cfg;
    provider_ = cfg_.runtime.accel_runtime;
    step_state_ = SnnAccelStepState{};
    inflight_.reset();
    completions_.clear();
    last_tick_cycle_ = 0;
    last_ticket_ = 0;
    accepted_commands_ = 0;
    completed_commands_ = 0;
    faulted_commands_ = 0;
    injected_packets_ = 0;
    provider_ticks_ = 0;
}

bool RiscvSnnRuntimeBridgeBackend::tick(uint64_t now_cycle) {
    last_tick_cycle_ = now_cycle;
    bool did_work = false;

    if (provider_) {
        if (provider_->tickRuntime(now_cycle)) did_work = true;
        ++provider_ticks_;
    }

    if (!inflight_) return did_work;

    did_work = true;
    auto& inflight = *inflight_;
    switch (inflight.phase) {
    case SnnAccelRuntimePhase::Accepted:
        if (inflight.fault_status != 0) {
            retireInflightFault_(inflight.fault_status, inflight.fault_aux);
            return true;
        }
        if (!snnAccelCommandIsFusedStep(inflight.command)) {
            retireInflightSuccess_();
            return true;
        }
        inflight.phase = SnnAccelRuntimePhase::Executing;
        step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::Executing);
        return did_work;
    case SnnAccelRuntimePhase::Executing:
        inflight.phase = SnnAccelRuntimePhase::OutboundDraining;
        step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::OutboundDraining);
        step_state_.outbound_draining = true;
        return did_work;
    case SnnAccelRuntimePhase::OutboundDraining:
        if (provider_ && provider_->hasRuntimeWork()) return did_work;
        inflight.phase = SnnAccelRuntimePhase::BarrierWaiting;
        step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::BarrierWaiting);
        step_state_.outbound_draining = false;
        step_state_.barrier_waiting = true;
        return did_work;
    case SnnAccelRuntimePhase::BarrierWaiting:
        if (provider_ && provider_->hasRuntimeWork()) return did_work;
        retireInflightSuccess_();
        return did_work;
    case SnnAccelRuntimePhase::Completed:
    case SnnAccelRuntimePhase::Faulted:
    case SnnAccelRuntimePhase::Idle:
    default:
        inflight_.reset();
        step_state_.busy = false;
        return did_work;
    }
}

bool RiscvSnnRuntimeBridgeBackend::submitCommand(const SnnAccelCommand& command) {
    if (inflight_) return false;

    last_ticket_ = command.ticket;
    step_state_.busy = true;
    step_state_.fault_valid = false;
    step_state_.barrier_waiting = false;
    step_state_.outbound_draining = false;
    step_state_.last_accept_opcode = command.opcode;
    step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::Accepted);

    InflightCommand inflight;
    inflight.command = command;
    inflight.phase = SnnAccelRuntimePhase::Accepted;
    const SnnAccelValidationResult validation = validateSnnAccelCommand(command);
    inflight.fault_status = validation.status;
    inflight.fault_aux = validation.aux;

    if (snnAccelCommandIsFusedStep(command)) {
        inflight.step_seq = step_state_.committed_seq + 1;
        step_state_.inflight_seq = inflight.step_seq;
        if (!provider_ || !provider_->runtimeBridgeReady()) {
            inflight.fault_status = backendInternalStatus();
            inflight.fault_aux = 0x52544252u;
        }
    }

    inflight_ = inflight;
    ++accepted_commands_;
    return true;
}

bool RiscvSnnRuntimeBridgeBackend::pollCompletion(SnnAccelCompletion& completion) {
    if (completions_.empty()) return false;
    completion = completions_.front();
    completions_.pop_front();
    return true;
}

bool RiscvSnnRuntimeBridgeBackend::injectPacket(NocPacketEvent* packet) {
    ++injected_packets_;
    if (!provider_) return packet == nullptr;
    return provider_->deliverIngressPacket(packet);
}

SnnAccelStepState RiscvSnnRuntimeBridgeBackend::readArchitecturalStepState() const {
    return step_state_;
}

void RiscvSnnRuntimeBridgeBackend::snapshotStats(std::map<std::string, uint64_t>& stats) const {
    stats["riscv_snn_backend_last_tick_cycle"] = last_tick_cycle_;
    stats["riscv_snn_backend_last_ticket"] = last_ticket_;
    stats["riscv_snn_backend_accepted_commands"] = accepted_commands_;
    stats["riscv_snn_backend_completed_commands"] = completed_commands_;
    stats["riscv_snn_backend_faulted_commands"] = faulted_commands_;
    stats["riscv_snn_backend_injected_packets"] = injected_packets_;
    stats["riscv_snn_backend_runtime_bridge_ticks"] = provider_ticks_;
    stats["riscv_snn_backend_runtime_bridge_packets"] = injected_packets_;
    stats["riscv_snn_backend_runtime_bridge_provider_bound"] =
        riscv_snn::statSnapshotProviderBoundVisibleValue(
            provider_ && provider_->runtimeBridgeReady());
    if (!provider_) return;

    std::map<std::string, uint64_t> provider_stats;
    provider_->snapshotRuntimeStats(provider_stats);
    for (const auto& [key, value] : provider_stats) {
        stats["riscv_snn_backend_runtime_bridge_" + key] = value;
    }
}

void RiscvSnnRuntimeBridgeBackend::retireInflightSuccess_() {
    if (!inflight_) return;
    const InflightCommand inflight = *inflight_;
    inflight_.reset();

    if (snnAccelCommandIsStatSnapshot(inflight.command)) {
        uint64_t stat_value = 0;
        if (!tryResolveSnnAccelStatSnapshotValue(
                inflight.command,
                accepted_commands_,
                completed_commands_,
                riscv_snn::statSnapshotProviderBoundVisibleValue(
                    provider_ && provider_->runtimeBridgeReady()),
                stat_value)) {
            SnnAccelCompletion completion = makeSnnAccelFaultCompletion(
                inflight.command,
                invalidStatSnapshotSelectorStatus(),
                riscv_snn::statSnapshotSelectorRaw(inflight.command.arg0));
            step_state_.fault_valid = true;
            step_state_.busy = false;
            step_state_.barrier_waiting = false;
            step_state_.outbound_draining = false;
            step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::Faulted);
            completions_.push_back(completion);
            ++faulted_commands_;
            return;
        }

        SnnAccelCompletion completion =
            makeSnnAccelStatSnapshotCompletion(inflight.command, stat_value);
        step_state_.fault_valid = false;
        step_state_.busy = false;
        step_state_.barrier_waiting = false;
        step_state_.outbound_draining = false;
        step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::Completed);
        completions_.push_back(completion);
        ++completed_commands_;
        return;
    }

    SnnAccelCompletion completion = makeSnnAccelSuccessCompletion(
        inflight.command,
        snnAccelCommandIsFusedStep(inflight.command)
            ? riscv_snn::eventMask(riscv_snn::EventBit::BarrierRelease)
            : 0u);
    if (snnAccelCommandIsFusedStep(inflight.command)) {
        step_state_.committed_seq = inflight.step_seq;
        step_state_.inflight_seq = inflight.step_seq;
    }
    step_state_.fault_valid = false;
    step_state_.busy = false;
    step_state_.barrier_waiting = false;
    step_state_.outbound_draining = false;
    step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::Completed);
    completions_.push_back(completion);
    ++completed_commands_;
}

void RiscvSnnRuntimeBridgeBackend::retireInflightFault_(uint32_t status_code, uint32_t aux) {
    if (!inflight_) return;
    const InflightCommand inflight = *inflight_;
    inflight_.reset();

    SnnAccelCompletion completion =
        makeSnnAccelFaultCompletion(inflight.command, status_code, aux);
    step_state_.fault_valid = true;
    step_state_.busy = false;
    step_state_.barrier_waiting = false;
    step_state_.outbound_draining = false;
    step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::Faulted);
    completions_.push_back(completion);
    ++faulted_commands_;
}

std::unique_ptr<SnnAccelBackend> makeRiscvSnnRuntimeBridgeBackend() {
    return std::make_unique<RiscvSnnRuntimeBridgeBackend>();
}

}} // namespace SST::SnnDL
