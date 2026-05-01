// -*- c++ -*-
//
// KeyedCounterStatsModule:
// - 通用的“从 core->getStatistics(map) 拉取 counters，并在 PE 侧做 delta 聚合”的实现基类
// - 约定：core_stats 中对应 key 的值为“累计总数”，本模块负责做 (cur-prev) 的增量统计
//

#pragma once

#include "IWorkloadStatsModule.h"

#include <sst/core/statapi/statbase.h>

#include <vector>

namespace SST { namespace SnnDL {

class KeyedCounterStatsModule : public IWorkloadStatsModule {
public:
    explicit KeyedCounterStatsModule(bool active_workload) : active_workload_(active_workload) {}

    void initialize(IWorkloadStatRegistrar& registrar, size_t num_cores) override {
        num_cores_ = num_cores;
        for (auto& c : counters_) {
            c.stat = registrar.registerU64(c.stat_name);
            c.last.assign(num_cores_, 0);
            c.current.assign(num_cores_, 0);
        }
    }

    void refreshCore(size_t core_id, const std::map<std::string, uint64_t>& core_stats) override {
        if (core_id >= num_cores_) return;
        for (auto& c : counters_) {
            const auto it = core_stats.find(c.key);
            c.current[core_id] = (it != core_stats.end()) ? it->second : 0;
        }
    }

    void emitDeltas() override {
        bool activity = false;
        for (auto& c : counters_) {
            uint64_t delta_sum = 0;
            for (size_t i = 0; i < num_cores_; ++i) {
                const uint64_t cur = c.current[i];
                const uint64_t prev = c.last[i];
                const uint64_t d = (cur >= prev) ? (cur - prev) : cur;
                delta_sum += d;
                c.last[i] = cur;
            }
            activity = activity || (delta_sum != 0);
            // 为保持 CSV key 稳定：即使 delta=0 也写入一次 addData。
            if (c.stat) c.stat->addData(delta_sum);
        }

        if (activity && !active_workload_ && unexpected_activity_stat_) {
            unexpected_activity_stat_->addData(1);
        }
    }

    void bindUnexpectedActivityStat(SST::Statistics::Statistic<uint64_t>* stat) override {
        unexpected_activity_stat_ = stat;
    }

protected:
    void addCounter(const char* key_and_stat) {
        addCounter(key_and_stat, key_and_stat);
    }

    void addCounter(const char* key, const char* stat_name) {
        Counter c;
        c.key = std::string(key ? key : "");
        c.stat_name = std::string(stat_name ? stat_name : "");
        counters_.push_back(std::move(c));
    }

private:
    struct Counter {
        std::string key;
        std::string stat_name;
        SST::Statistics::Statistic<uint64_t>* stat = nullptr;
        std::vector<uint64_t> last;
        std::vector<uint64_t> current;
    };

    bool active_workload_ = false;
    size_t num_cores_ = 0;
    SST::Statistics::Statistic<uint64_t>* unexpected_activity_stat_ = nullptr;
    std::vector<Counter> counters_;
};

}} // namespace SST::SnnDL
