// -*- c++ -*-

#pragma once

#include <map>

#include "api/ICoreWorkload.h"
#include "workload/stream/StreamWorkload.h"
#include "workload/traffic/TrafficWorkload.h"

namespace SST { namespace SnnDL {

class TrafficMemWorkload final : public ICoreWorkload {
public:
    TrafficMemWorkload();
    ~TrafficMemWorkload() override;

    void configureFromParams(const SST::Params& params) override;
    void bindRuntime(const Runtime& rt) override;

    void onInitPhase(unsigned phase) override;
    void onSetup() override;
    void onFinish() override;
    void onGlobalStepStart(uint32_t seq) override;
    void resetMembraneState(float v_rest) override;

    bool onClockTick(uint64_t now_cycle) override;
    bool deliverPacket(NocPacketEvent* packet) override;

    bool hasWork() const override;
    double getUtilization() const override;
    void getStatistics(std::map<std::string, uint64_t>& stats) const override;

private:
    StreamWorkload stream_;
    TrafficWorkload traffic_;
};

std::unique_ptr<ICoreWorkload> makeTrafficMemWorkload();

}} // namespace SST::SnnDL
