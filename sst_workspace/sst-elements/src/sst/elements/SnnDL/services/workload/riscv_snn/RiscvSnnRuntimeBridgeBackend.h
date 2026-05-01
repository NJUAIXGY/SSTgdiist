// -*- c++ -*-

#pragma once

#include <deque>
#include <optional>

#include "workload/common/SnnAccelBackend.h"

namespace SST { namespace SnnDL {

class ISnnAccelRuntimeServices;

class RiscvSnnRuntimeBridgeBackend final : public SnnAccelBackend {
public:
    void configure(const Config& cfg) override;
    bool tick(uint64_t now_cycle) override;
    bool submitCommand(const SnnAccelCommand& command) override;
    bool pollCompletion(SnnAccelCompletion& completion) override;
    bool injectPacket(NocPacketEvent* packet) override;
    SnnAccelStepState readArchitecturalStepState() const override;
    void snapshotStats(std::map<std::string, uint64_t>& stats) const override;

private:
    struct InflightCommand {
        SnnAccelCommand command{};
        SnnAccelRuntimePhase phase = SnnAccelRuntimePhase::Idle;
        uint32_t step_seq = 0;
        uint32_t fault_status = 0;
        uint32_t fault_aux = 0;
    };

    void retireInflightSuccess_();
    void retireInflightFault_(uint32_t status_code, uint32_t aux);

    Config cfg_{};
    ISnnAccelRuntimeServices* provider_ = nullptr;
    uint64_t last_tick_cycle_ = 0;
    uint64_t last_ticket_ = 0;
    uint64_t accepted_commands_ = 0;
    uint64_t completed_commands_ = 0;
    uint64_t faulted_commands_ = 0;
    uint64_t injected_packets_ = 0;
    uint64_t provider_ticks_ = 0;
    SnnAccelStepState step_state_{};
    std::optional<InflightCommand> inflight_{};
    std::deque<SnnAccelCompletion> completions_{};
};

std::unique_ptr<SnnAccelBackend> makeRiscvSnnRuntimeBridgeBackend();

}} // namespace SST::SnnDL
