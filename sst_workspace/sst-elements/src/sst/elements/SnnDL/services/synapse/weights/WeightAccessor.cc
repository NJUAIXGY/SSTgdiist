// -*- c++ -*-
//
// WeightAccessor: mapping helpers extracted from SnnPESubComponent.

#include "WeightAccessor.h"

namespace SST { namespace SnnDL {

bool WeightAccessor::resolve(uint32_t pre_global, uint32_t post_local,
                             uint32_t& req_pre, uint32_t& req_post,
                             uint64_t& cache_key, bool allow_remap) const {
    if (post_local >= cfg_.num_neurons) return false;
    req_post = post_local;
    if (cfg_.use_post_row_pre_col) {
        if (cfg_.weights_cols == 0) return false;
        if (pre_global >= cfg_.weights_cols) return false;
        cache_key = static_cast<uint64_t>(post_local) *
                        static_cast<uint64_t>(cfg_.weights_cols) +
                    static_cast<uint64_t>(pre_global);
        req_pre = pre_global;
        return true;
    }
    uint32_t pre_local = 0;
    const uint64_t base_global = static_cast<uint64_t>(cfg_.global_neuron_base);
    const uint64_t width = static_cast<uint64_t>(cfg_.num_neurons);
    const bool is_local = (static_cast<uint64_t>(pre_global) >= base_global) &&
                          (static_cast<uint64_t>(pre_global) < (base_global + width));
    if (is_local) {
        pre_local = static_cast<uint32_t>(static_cast<uint64_t>(pre_global) - base_global);
    } else {
        if (!allow_remap) return false;
        if (cfg_.num_neurons == 0) return false;
        const uint64_t core_span = static_cast<uint64_t>(cfg_.core_id) * width;
        const uint64_t base = (base_global >= core_span) ? (base_global - core_span) : 0ULL;
        const uint64_t pre_u64 = static_cast<uint64_t>(pre_global);
        const uint64_t diff = (pre_u64 >= base) ? (pre_u64 - base) : (pre_u64 + width - (base % width));
        pre_local = static_cast<uint32_t>(diff % width);
    }
    cache_key = static_cast<uint64_t>(pre_local) *
                    static_cast<uint64_t>(cfg_.num_neurons) +
                static_cast<uint64_t>(post_local);
    req_pre = pre_local;
    return true;
}

}} // namespace SST::SnnDL
