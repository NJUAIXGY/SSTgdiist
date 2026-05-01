// -*- c++ -*-
//
// SnnAccelBackend:
// - workload=snn 与 workload=riscv_snn 共享的数据面/backend 合同。
// - v1 先提供最小可编译接口，后续再把真正的 SNN datapath 从 SnnWorkload 内部下沉到这里。
//

#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <string>

#include "api/ICoreWorkload.h"
#include "workload/common/SnnAccelBackendContract.h"

namespace SST { namespace SnnDL {

class NocPacketEvent;

class SnnAccelBackend {
public:
    struct Config {
        ICoreWorkload::Runtime runtime{};
        std::string backend_name = "null";
        std::string compute_core_impl = "default";
    };

    virtual ~SnnAccelBackend() = default;

    virtual void configure(const Config& cfg) = 0;
    virtual bool tick(uint64_t now_cycle) = 0;
    virtual bool submitCommand(const SnnAccelCommand& command) = 0;
    virtual bool pollCompletion(SnnAccelCompletion& completion) = 0;
    virtual bool injectPacket(NocPacketEvent* packet) = 0;
    virtual SnnAccelStepState readArchitecturalStepState() const = 0;
    virtual void snapshotStats(std::map<std::string, uint64_t>& stats) const = 0;
};

std::unique_ptr<SnnAccelBackend> makeNullSnnAccelBackend();
std::unique_ptr<SnnAccelBackend> makeSnnAccelBackendByName(const std::string& name);

}} // namespace SST::SnnDL
