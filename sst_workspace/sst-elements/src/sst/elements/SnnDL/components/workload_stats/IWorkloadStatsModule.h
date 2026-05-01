// -*- c++ -*-
//
// IWorkloadStatsModule:
// - MultiCorePE 侧的 workload 统计聚合模块接口
// - 目标：新增 workload 时不再堆叠 MultiCorePE.cc 的 if/else 与字段/last/delta 逻辑
//

#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>

namespace SST {
namespace Statistics {
template <class T>
class Statistic;
} // namespace Statistics
} // namespace SST

namespace SST { namespace SnnDL {

class IWorkloadStatRegistrar {
public:
    virtual ~IWorkloadStatRegistrar() = default;
    virtual SST::Statistics::Statistic<uint64_t>* registerU64(const std::string& stat_name) = 0;
};

class IWorkloadStatsModule {
public:
    virtual ~IWorkloadStatsModule() = default;

    // Stable module id (e.g. "stream", "tensor").
    virtual const char* name() const = 0;

    // Called once from MultiCorePE::initializeStatistics().
    virtual void initialize(IWorkloadStatRegistrar& registrar, size_t num_cores) = 0;

    // Called every cycle from MultiCorePE::refreshProcessingUnitStates_().
    // Expects monotonically increasing counters (total since start).
    virtual void refreshCore(size_t core_id, const std::map<std::string, uint64_t>& core_stats) = 0;

    // Called periodically (default: every 1000 cycles) and at finish().
    // Computes deltas since last emit and adds them into SST statistics.
    virtual void emitDeltas() = 0;

    // Optional: bind an observability stat for "activity seen while module inactive".
    virtual void bindUnexpectedActivityStat(SST::Statistics::Statistic<uint64_t>* /*stat*/) {}
};

}} // namespace SST::SnnDL
