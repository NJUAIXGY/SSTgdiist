// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "CoreWorkloadFactory.h"

#include "ICoreWorkload.h"
#include "WorkloadConfig.h"
#include "workload/riscv_snn/RiscvSnnWorkload.h"
#include "workload/snn/SnnWorkload.h"
#include "workload/stream/StreamWorkload.h"
#include "workload/tensor/TensorWorkload.h"
#include "workload/traffic/TrafficWorkload.h"
#include "workload/traffic_mem/TrafficMemWorkload.h"

namespace SST { namespace SnnDL {

namespace {

using WorkloadFactoryFn = std::unique_ptr<ICoreWorkload>(*)();

std::unique_ptr<ICoreWorkload> makeRiscvSnn_() { return std::make_unique<RiscvSnnWorkload>(); }
std::unique_ptr<ICoreWorkload> makeSnn_() { return std::make_unique<SnnWorkload>(); }
std::unique_ptr<ICoreWorkload> makeStream_() { return std::make_unique<StreamWorkload>(); }
std::unique_ptr<ICoreWorkload> makeTensor_() { return std::make_unique<TensorWorkload>(); }
std::unique_ptr<ICoreWorkload> makeTraffic_() { return std::make_unique<TrafficWorkload>(); }
std::unique_ptr<ICoreWorkload> makeTrafficMem_() { return makeTrafficMemWorkload(); }

struct WorkloadFactoryEntry {
    const char* name = nullptr;
    WorkloadFactoryFn create = nullptr;
};

const WorkloadFactoryEntry kWorkloadFactories[] = {
    {"riscv_snn", &makeRiscvSnn_},
    {"snn", &makeSnn_},
    {"stream", &makeStream_},
    {"tensor", &makeTensor_},
    {"traffic", &makeTraffic_},
    {"traffic_mem", &makeTrafficMem_},
};

} // namespace

std::unique_ptr<ICoreWorkload> createWorkloadByName(const std::string& name) {
    const std::string n = toLowerCopy(std::string(name));
    for (const auto& e : kWorkloadFactories) {
        if (!e.name || !e.create) continue;
        if (n == e.name) return e.create();
    }
    return nullptr;
}

}} // namespace SST::SnnDL
