// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/riscv_snn/RiscvSnnShadowRuntimeServices.h"

#include "workload/snn/SnnWorkload.h"

namespace SST { namespace SnnDL {

RiscvSnnShadowRuntimeServices::~RiscvSnnShadowRuntimeServices() = default;

void RiscvSnnShadowRuntimeServices::configureFromParams(const SST::Params& params) {
    params_ = params;
}

void RiscvSnnShadowRuntimeServices::bindRuntime(const ICoreWorkload::Runtime& rt) {
    rt_ = rt;
    rt_.accel_runtime = nullptr;
    ensureShadow_();
    if (shadow_) shadow_->bindRuntime(rt_);
}

bool RiscvSnnShadowRuntimeServices::runtimeBridgeReady() const {
    return shadow_ != nullptr;
}

bool RiscvSnnShadowRuntimeServices::tickRuntime(uint64_t now_cycle) {
    ensureShadow_();
    if (!shadow_) return false;
    last_cycle_ = now_cycle;
    ++tick_count_;
    return shadow_->onClockTick(now_cycle);
}

bool RiscvSnnShadowRuntimeServices::deliverIngressPacket(NocPacketEvent* packet) {
    ensureShadow_();
    if (!shadow_) return false;
    ++packet_count_;
    return shadow_->deliverPacket(packet);
}

bool RiscvSnnShadowRuntimeServices::hasRuntimeWork() const {
    return shadow_ && shadow_->hasWork();
}

double RiscvSnnShadowRuntimeServices::runtimeUtilization() const {
    return shadow_ ? shadow_->getUtilization() : 0.0;
}

void RiscvSnnShadowRuntimeServices::snapshotRuntimeStats(std::map<std::string, uint64_t>& stats) const {
    stats["shadow_tick_count"] = tick_count_;
    stats["shadow_packet_count"] = packet_count_;
    stats["shadow_gas_stage_event_count"] = gas_stage_event_count_;
    stats["shadow_gas_stat_event_count"] = gas_stat_event_count_;
    stats["shadow_init_phase_count"] = init_phase_count_;
    stats["shadow_setup_count"] = setup_count_;
    stats["shadow_finish_count"] = finish_count_;
    stats["shadow_global_step_count"] = global_step_count_;
    stats["shadow_last_cycle"] = last_cycle_;
    stats["shadow_last_global_step_seq"] = last_global_step_seq_;
    if (!shadow_) return;

    std::map<std::string, uint64_t> shadow_stats;
    shadow_->getStatistics(shadow_stats);
    for (const auto& [key, value] : shadow_stats) {
        stats["shadow_" + key] = value;
    }
}

void RiscvSnnShadowRuntimeServices::onGlobalStepStart(uint32_t seq) {
    ensureShadow_();
    if (!shadow_) return;
    ++global_step_count_;
    last_global_step_seq_ = seq;
    shadow_->onGlobalStepStart(seq);
}

void RiscvSnnShadowRuntimeServices::onGasStageEvent(const GasStageEvent& ev) {
    ensureShadow_();
    if (!shadow_) return;
    ++gas_stage_event_count_;
    shadow_->onGasStageEvent(ev);
}

void RiscvSnnShadowRuntimeServices::onGasStatEvent(const GasStatEvent& st) {
    ensureShadow_();
    if (!shadow_) return;
    ++gas_stat_event_count_;
    shadow_->onGasStatEvent(st);
}

void RiscvSnnShadowRuntimeServices::onInitPhase(unsigned phase) {
    ensureShadow_();
    if (!shadow_) return;
    ++init_phase_count_;
    shadow_->onInitPhase(phase);
}

void RiscvSnnShadowRuntimeServices::onSetup() {
    ensureShadow_();
    if (!shadow_) return;
    ++setup_count_;
    shadow_->onSetup();
}

void RiscvSnnShadowRuntimeServices::onFinish() {
    ensureShadow_();
    if (!shadow_) return;
    ++finish_count_;
    shadow_->onFinish();
}

void RiscvSnnShadowRuntimeServices::resetMembraneState(float v_rest) {
    ensureShadow_();
    if (!shadow_) return;
    shadow_->resetMembraneState(v_rest);
}

void RiscvSnnShadowRuntimeServices::ensureShadow_() {
    if (shadow_) return;
    shadow_ = std::make_unique<SnnWorkload>();
    shadow_->configureFromParams(params_);
}

}} // namespace SST::SnnDL
