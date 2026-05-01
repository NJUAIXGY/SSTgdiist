// -*- c++ -*-
//
// ISnnAccelRuntimeServices:
// - `riscv_snn` Phase C runtime bridge 的可选实验 provider。
// - 目标：只暴露驱动 shadow/runtime datapath 所需的最小能力，避免 `riscv_snn`
//   直接耦合 `SnnPESubComponent` 或默认 `snn` 内部实现。
//

#pragma once

#include <cstdint>
#include <map>

#include "IGasStageSink.h"
#include "IGlobalStepHooks.h"

namespace SST { namespace SnnDL {

class NocPacketEvent;

class ISnnAccelRuntimeServices : public IGlobalStepHooks, public IGasStageSink {
public:
    ~ISnnAccelRuntimeServices() override = default;

    virtual bool runtimeBridgeReady() const = 0;
    virtual bool tickRuntime(uint64_t now_cycle) = 0;
    virtual bool deliverIngressPacket(NocPacketEvent* packet) = 0;
    virtual bool hasRuntimeWork() const = 0;
    virtual double runtimeUtilization() const = 0;
    virtual void snapshotRuntimeStats(std::map<std::string, uint64_t>& stats) const = 0;

    void onGlobalStepStart(uint32_t /*seq*/) override {}
    void onGasStageEvent(const GasStageEvent& /*ev*/) override {}
    void onGasStatEvent(const GasStatEvent& /*st*/) override {}

    virtual void onInitPhase(unsigned /*phase*/) {}
    virtual void onSetup() {}
    virtual void onFinish() {}
    virtual void resetMembraneState(float /*v_rest*/) {}
};

}} // namespace SST::SnnDL
