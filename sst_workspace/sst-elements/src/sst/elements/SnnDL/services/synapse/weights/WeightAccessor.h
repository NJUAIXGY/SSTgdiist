// -*- c++ -*-
//
// WeightAccessor: mapping helpers extracted from SnnPESubComponent.
// Keep behavior identical; only structural decoupling for readability/maintenance.

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

struct WeightAccessorConfig {
    uint32_t core_id = 0;
    uint64_t global_neuron_base = 0;
    uint32_t num_neurons = 0;
    uint32_t weights_cols = 0;
    bool use_post_row_pre_col = false;
};

struct WeightAccessor {
    WeightAccessor() = default;
    explicit WeightAccessor(WeightAccessorConfig cfg) : cfg_(cfg) {}

    void configure(WeightAccessorConfig cfg) { cfg_ = cfg; }

    // Resolve a (pre_global, post_local) pair into request indices and cache key.
    // allow_remap keeps legacy modulo remap behavior when pre is non-local.
    bool resolve(uint32_t pre_global, uint32_t post_local,
                 uint32_t& req_pre, uint32_t& req_post,
                 uint64_t& cache_key, bool allow_remap = false) const;

private:
    WeightAccessorConfig cfg_{};
};

}} // namespace SST::SnnDL
