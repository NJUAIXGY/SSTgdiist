// -*- c++ -*-
//
// AccumulatorOps: window accumulator implementation extracted from SnnPESubComponent.
// Owns all accumulator state (dense/sparse + spill + optional shadow verify).
// Control layer provides a lightweight config with optional counters/stats hooks.

#pragma once

#include <cstdint>
#include <unordered_map>
#include <utility>
#include <vector>

#include <sst/core/statapi/statbase.h>

namespace SST {
class Output;
} // namespace SST

namespace SST { namespace SnnDL {

struct AccumulatorOpsConfig {
    uint32_t num_neurons = 0;
    bool dense_enable = false;
    bool spill_enable = true;
    uint64_t high_watermark_bytes = 16 * 1024 * 1024;
    bool shadow_verify_enable = false;

    // Diagnostics / logging context (optional)
    bool window_read_debug = false;
    int core_id = 0;
    int verbose = 0;
    SST::Output* out = nullptr;

    // Optional per-window counters (owned by control layer)
    uint64_t* updates_count = nullptr;
    uint64_t* posts_touched_count = nullptr;
    uint64_t* spill_records_count = nullptr;
    uint64_t* spilled_bytes_sum = nullptr;
    uint64_t* hwm_bytes_max = nullptr;

    // Optional statistic hooks (owned by control layer)
    SST::Statistics::Statistic<uint64_t>* stat_apply_updates_total = nullptr;
    SST::Statistics::Statistic<uint64_t>* stat_posts_touched_total = nullptr;
    SST::Statistics::Statistic<uint64_t>* stat_spill_records_total = nullptr;
    SST::Statistics::Statistic<uint64_t>* stat_spilled_bytes_total = nullptr;
    SST::Statistics::Statistic<uint64_t>* stat_hwm_bytes_total = nullptr;
};

class AccumulatorOps {
public:
    explicit AccumulatorOps(const AccumulatorOpsConfig& cfg);

    // Reconfigure hooks/flags (safe before first use; resets internal state).
    void configure(const AccumulatorOpsConfig& cfg);

    void reset();
    void update(uint32_t post, float dv);

    bool denseEnabled() const { return dense_enable_; }

    // Collect current accumulated deltas in deterministic (sorted) order.
    // Caller decides how/when to apply and then calls reset().
    void collectSortedPairs(std::vector<std::pair<uint32_t, float>>& out);

    // Optional dense-shadow verification (no-op unless enabled).
    void verifyDense(uint32_t seq);

private:
    void mergeSpill_();

    AccumulatorOpsConfig cfg_{};

    bool dense_enable_ = false;
    bool spill_enable_ = true;
    uint64_t hwm_bytes_ = 16 * 1024 * 1024;
    bool shadow_verify_enable_ = false;
    bool shadow_mismatch_logged_ = false;

    uint64_t bytes_estimate_ = 0;

    // Sparse accumulator
    std::unordered_map<uint32_t, float> acc_delta_;
    // Dense accumulator
    std::vector<float> acc_dense_;
    std::vector<uint8_t> acc_touched_bitmap_;
    std::vector<uint32_t> acc_touched_list_;

    // Spill + shadow verify
    std::vector<std::pair<uint32_t, float>> acc_spill_log_;
    std::unordered_map<uint32_t, float> acc_shadow_map_;
};

}} // namespace SST::SnnDL
