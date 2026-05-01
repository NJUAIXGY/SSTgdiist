// -*- c++ -*-

#pragma once

#include <map>
#include <memory>

#include <sst/core/params.h>

#include "api/ICoreWorkload.h"
#include "api/ISnnAccelRuntimeServices.h"
#include "workload/snn/SnnWorkload.h"

namespace SST { namespace SnnDL {

class RiscvSnnShadowRuntimeServices final : public ISnnAccelRuntimeServices {
public:
    ~RiscvSnnShadowRuntimeServices() override;

    void configureFromParams(const SST::Params& params);
    void bindRuntime(const ICoreWorkload::Runtime& rt);

    bool runtimeBridgeReady() const override;
    bool tickRuntime(uint64_t now_cycle) override;
    bool deliverIngressPacket(NocPacketEvent* packet) override;
    bool hasRuntimeWork() const override;
    double runtimeUtilization() const override;
    void snapshotRuntimeStats(std::map<std::string, uint64_t>& stats) const override;

    void onGlobalStepStart(uint32_t seq) override;
    void onGasStageEvent(const GasStageEvent& ev) override;
    void onGasStatEvent(const GasStatEvent& st) override;
    void onInitPhase(unsigned phase) override;
    void onSetup() override;
    void onFinish() override;
    void resetMembraneState(float v_rest) override;

private:
    void ensureShadow_();

    SST::Params params_{};
    ICoreWorkload::Runtime rt_{};
    std::unique_ptr<SnnWorkload> shadow_{};
    uint64_t tick_count_ = 0;
    uint64_t packet_count_ = 0;
    uint64_t gas_stage_event_count_ = 0;
    uint64_t gas_stat_event_count_ = 0;
    uint64_t init_phase_count_ = 0;
    uint64_t setup_count_ = 0;
    uint64_t finish_count_ = 0;
    uint64_t global_step_count_ = 0;
    uint64_t last_cycle_ = 0;
    uint64_t last_global_step_seq_ = 0;
};

}} // namespace SST::SnnDL
