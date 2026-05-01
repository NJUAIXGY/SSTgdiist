// -*- c++ -*-
//
// NormalizedNeuronLayout:
// - 统一处理 "num_neurons / neurons_per_pe / global_neuron_base" 的历史多义口径。
// - 目标：让路由 denom、Spike 编解码 layout、以及 core-local global base 一致。
//
// 注意：这是“代码组织/口径收敛”的内部工具，不改变对外组件/装配点。
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

struct NormalizedNeuronLayout {
    // Derived, normalized layout
    uint32_t total_nodes = 1;
    uint32_t cores_per_pe = 1;
    uint32_t neurons_per_core = 1;
    uint32_t neurons_per_pe = 1;

    // Derived bases
    uint64_t node_neuron_base = 0;  // node_id * neurons_per_pe
    uint64_t core_neuron_base = 0;  // node_base + core_id * neurons_per_core

    // Diagnostics (best-effort)
    bool num_neurons_was_per_pe = false;
    int base_match_score = 0; // 2=core-base match, 1=node-base match, 0=no match
};

// Normalize layout semantics:
// - num_neurons_param can be "per-core" or "per-PE" depending on historical scripts.
// - neurons_per_pe_param, when provided (>0), wins and num_neurons_param is treated as per-core.
// - global_neuron_base_param can be either core-base or node-base; we normalize to core-base.
NormalizedNeuronLayout normalizeNeuronLayout(
    uint32_t node_id,
    uint32_t core_id,
    uint32_t total_nodes_param,
    uint32_t cores_per_pe_param,
    uint32_t num_neurons_param,
    uint32_t neurons_per_pe_param,
    uint64_t global_neuron_base_param,
    uint32_t weights_cols_param /*optional hint; 0 if unknown*/);

}} // namespace SST::SnnDL

