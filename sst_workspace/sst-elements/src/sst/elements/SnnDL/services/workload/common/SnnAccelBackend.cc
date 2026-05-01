// -*- c++ -*-

#include <sst/core/sst_config.h>

#include <deque>
#include <optional>

#include "workload/common/SnnAccelBackend.h"
#include "workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.h"

namespace SST { namespace SnnDL {

namespace {

uint32_t invalidStatSnapshotSelectorStatus() {
    return riscv_snn::encodeStatusCode(
        riscv_snn::CompletionPrimaryStatus::BadPolicy,
        riscv_snn::CompletionSeverity::FaultAfterAccept);
}

class NullSnnAccelBackend final : public SnnAccelBackend {
public:
    void configure(const Config& cfg) override {
        cfg_ = cfg;
        step_state_ = SnnAccelStepState{};
        inflight_.reset();
        completions_.clear();
        last_tick_cycle_ = 0;
        last_ticket_ = 0;
        accepted_commands_ = 0;
        completed_commands_ = 0;
        faulted_commands_ = 0;
        injected_packets_ = 0;
    }

    bool tick(uint64_t now_cycle) override {
        last_tick_cycle_ = now_cycle;
        if (!inflight_) return false;

        bool did_work = true;
        auto& inflight = *inflight_;
        switch (inflight.phase) {
        case SnnAccelRuntimePhase::Accepted:
            if (inflight.fault_status != 0) {
                retireInflight_(/*success=*/false);
                return true;
            }
            if (snnAccelCommandIsFusedStep(inflight.command)) {
                inflight.phase = SnnAccelRuntimePhase::Executing;
                step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::Executing);
            } else {
                retireInflight_(/*success=*/true);
            }
            return did_work;
        case SnnAccelRuntimePhase::Executing:
            inflight.phase = SnnAccelRuntimePhase::OutboundDraining;
            step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::OutboundDraining);
            step_state_.outbound_draining = true;
            return did_work;
        case SnnAccelRuntimePhase::OutboundDraining:
            inflight.phase = SnnAccelRuntimePhase::BarrierWaiting;
            step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::BarrierWaiting);
            step_state_.outbound_draining = false;
            step_state_.barrier_waiting = true;
            return did_work;
        case SnnAccelRuntimePhase::BarrierWaiting:
            retireInflight_(/*success=*/true);
            return did_work;
        case SnnAccelRuntimePhase::Completed:
        case SnnAccelRuntimePhase::Faulted:
        case SnnAccelRuntimePhase::Idle:
        default:
            inflight_.reset();
            step_state_.busy = false;
            return true;
        }
    }

    bool submitCommand(const SnnAccelCommand& command) override {
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
        }
        inflight_ = inflight;
        ++accepted_commands_;
        return true;
    }

    bool pollCompletion(SnnAccelCompletion& completion) override {
        if (completions_.empty()) return false;
        completion = completions_.front();
        completions_.pop_front();
        return true;
    }

    bool injectPacket(NocPacketEvent* packet) override {
        (void)packet;
        ++injected_packets_;
        return true;
    }

    SnnAccelStepState readArchitecturalStepState() const override {
        return step_state_;
    }

    void snapshotStats(std::map<std::string, uint64_t>& stats) const override {
        stats["riscv_snn_backend_last_tick_cycle"] = last_tick_cycle_;
        stats["riscv_snn_backend_last_ticket"] = last_ticket_;
        stats["riscv_snn_backend_accepted_commands"] = accepted_commands_;
        stats["riscv_snn_backend_completed_commands"] = completed_commands_;
        stats["riscv_snn_backend_faulted_commands"] = faulted_commands_;
        stats["riscv_snn_backend_injected_packets"] = injected_packets_;
    }

private:
    struct InflightCommand {
        SnnAccelCommand command{};
        SnnAccelRuntimePhase phase = SnnAccelRuntimePhase::Idle;
        uint32_t step_seq = 0;
        uint32_t fault_status = 0;
        uint32_t fault_aux = 0;
    };

    void retireInflight_(bool success) {
        if (!inflight_) return;
        const InflightCommand inflight = *inflight_;
        inflight_.reset();

        if (!success || inflight.fault_status != 0) {
            SnnAccelCompletion completion = makeSnnAccelFaultCompletion(
                inflight.command,
                inflight.fault_status,
                inflight.fault_aux);
            step_state_.fault_valid = true;
            step_state_.busy = false;
            step_state_.barrier_waiting = false;
            step_state_.outbound_draining = false;
            step_state_.phase = accelRuntimePhaseValue(SnnAccelRuntimePhase::Faulted);
            completions_.push_back(completion);
            ++faulted_commands_;
            return;
        }

        if (snnAccelCommandIsStatSnapshot(inflight.command)) {
            uint64_t stat_value = 0;
            if (!tryResolveSnnAccelStatSnapshotValue(
                    inflight.command,
                    accepted_commands_,
                    completed_commands_,
                    /*provider_bound_visible=*/
                    riscv_snn::statSnapshotProviderBoundVisibleValue(false),
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

    Config cfg_{};
    uint64_t last_tick_cycle_ = 0;
    uint64_t last_ticket_ = 0;
    uint64_t accepted_commands_ = 0;
    uint64_t completed_commands_ = 0;
    uint64_t faulted_commands_ = 0;
    uint64_t injected_packets_ = 0;
    SnnAccelStepState step_state_{};
    std::optional<InflightCommand> inflight_{};
    std::deque<SnnAccelCompletion> completions_{};
};

} // namespace

std::unique_ptr<SnnAccelBackend> makeNullSnnAccelBackend() {
    return std::make_unique<NullSnnAccelBackend>();
}

std::unique_ptr<SnnAccelBackend> makeSnnAccelBackendByName(const std::string& name) {
    if (name == "runtime_bridge") return makeRiscvSnnRuntimeBridgeBackend();
    return makeNullSnnAccelBackend();
}

}} // namespace SST::SnnDL
