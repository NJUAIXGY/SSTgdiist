// -*- c++ -*-
//
// NormalizedNeuronLayout.cc
//

#include "workload/layout/NormalizedNeuronLayout.h"

#include <algorithm>

namespace SST { namespace SnnDL {

namespace {

inline uint32_t clampNonZero_(uint32_t v) { return v ? v : 1u; }

inline int baseMatchScore_(uint64_t base_param, uint64_t node_base, uint64_t core_base) {
    if (base_param == core_base) return 2;
    if (base_param == node_base) return 1;
    return 0;
}

struct Hypothesis {
    bool valid = false;
    uint32_t neurons_per_core = 0;
    uint32_t neurons_per_pe = 0;
    bool num_neurons_was_per_pe = false;
    int match = 0;
};

inline uint64_t safeMul64_(uint32_t a, uint32_t b) {
    return static_cast<uint64_t>(a) * static_cast<uint64_t>(b);
}

inline bool equalsU32_(uint64_t v, uint32_t expect) {
    return v == static_cast<uint64_t>(expect);
}

} // namespace

NormalizedNeuronLayout normalizeNeuronLayout(
    uint32_t node_id,
    uint32_t core_id,
    uint32_t total_nodes_param,
    uint32_t cores_per_pe_param,
    uint32_t num_neurons_param,
    uint32_t neurons_per_pe_param,
    uint64_t global_neuron_base_param,
    uint32_t weights_cols_param)
{
    NormalizedNeuronLayout out{};
    out.total_nodes = clampNonZero_(total_nodes_param);
    out.cores_per_pe = clampNonZero_(cores_per_pe_param);

    const uint32_t raw = clampNonZero_(num_neurons_param);
    const uint64_t base_param = global_neuron_base_param;

    Hypothesis h_core{}; // interpret num_neurons as per-core
    Hypothesis h_pe{};   // interpret num_neurons as per-PE

    // Hypothesis 1: explicit neurons_per_pe wins; treat num_neurons as per-core.
    if (neurons_per_pe_param > 0) {
        h_core.valid = true;
        h_core.neurons_per_core = raw;
        h_core.neurons_per_pe = neurons_per_pe_param;
        h_core.num_neurons_was_per_pe = false;
        const uint64_t node_base = safeMul64_(node_id, h_core.neurons_per_pe);
        const uint64_t core_base = node_base + safeMul64_(core_id, h_core.neurons_per_core);
        h_core.match = baseMatchScore_(base_param, node_base, core_base);
    } else {
        // num_neurons as per-core: neurons_per_pe derived by cores_per_pe
        {
            const uint64_t npp64 = safeMul64_(raw, out.cores_per_pe);
            const uint32_t npp = (npp64 > 0xffffffffull) ? 0u : static_cast<uint32_t>(npp64);
            if (npp > 0) {
                h_core.valid = true;
                h_core.neurons_per_core = raw;
                h_core.neurons_per_pe = npp;
                h_core.num_neurons_was_per_pe = false;
                const uint64_t node_base = safeMul64_(node_id, npp);
                const uint64_t core_base = node_base + safeMul64_(core_id, raw);
                h_core.match = baseMatchScore_(base_param, node_base, core_base);
            }
        }
        // num_neurons as per-PE: requires divisible by cores_per_pe
        if ((raw % out.cores_per_pe) == 0) {
            h_pe.valid = true;
            h_pe.neurons_per_pe = raw;
            h_pe.neurons_per_core = raw / out.cores_per_pe;
            h_pe.num_neurons_was_per_pe = true;
            const uint64_t node_base = safeMul64_(node_id, raw);
            const uint64_t core_base = node_base + safeMul64_(core_id, h_pe.neurons_per_core);
            h_pe.match = baseMatchScore_(base_param, node_base, core_base);
        }
    }

    auto choose = [&](const Hypothesis& a, const Hypothesis& b) -> Hypothesis {
        if (a.valid && !b.valid) return a;
        if (!a.valid && b.valid) return b;
        if (!a.valid && !b.valid) return a;
        if (a.match != b.match) return (a.match > b.match) ? a : b;

        // Tie-breaker: if weights_cols matches total global neurons (total_nodes * neurons_per_pe), prefer it.
        if (weights_cols_param > 0 && out.total_nodes > 0) {
            const uint64_t expect_a = safeMul64_(out.total_nodes, a.neurons_per_pe);
            const uint64_t expect_b = safeMul64_(out.total_nodes, b.neurons_per_pe);
            const bool a_ok = equalsU32_(expect_a, weights_cols_param);
            const bool b_ok = equalsU32_(expect_b, weights_cols_param);
            if (a_ok != b_ok) return a_ok ? a : b;
        }

        // Backward-compat default: keep "per-core" interpretation.
        return a;
    };

    Hypothesis picked = choose(h_core, h_pe);
    if (!picked.valid) {
        // Defensive fallback: keep deterministic.
        picked.valid = true;
        picked.neurons_per_core = raw;
        picked.neurons_per_pe = clampNonZero_(neurons_per_pe_param);
        if (picked.neurons_per_pe == 1u) {
            const uint64_t npp64 = safeMul64_(raw, out.cores_per_pe);
            picked.neurons_per_pe = (npp64 > 0xffffffffull) ? 1u : static_cast<uint32_t>(npp64);
        }
        picked.num_neurons_was_per_pe = false;
        const uint64_t node_base = safeMul64_(node_id, picked.neurons_per_pe);
        const uint64_t core_base = node_base + safeMul64_(core_id, picked.neurons_per_core);
        picked.match = baseMatchScore_(base_param, node_base, core_base);
    }

    out.neurons_per_core = clampNonZero_(picked.neurons_per_core);
    out.neurons_per_pe = clampNonZero_(picked.neurons_per_pe);
    out.num_neurons_was_per_pe = picked.num_neurons_was_per_pe;
    out.base_match_score = picked.match;

    out.node_neuron_base = safeMul64_(node_id, out.neurons_per_pe);
    const uint64_t expected_core_base =
        out.node_neuron_base + safeMul64_(core_id, out.neurons_per_core);

    // Normalize global_neuron_base to core-base (node_base + core offset).
    if (base_param == expected_core_base) {
        out.core_neuron_base = base_param;
    } else if (base_param == out.node_neuron_base) {
        out.core_neuron_base = base_param + safeMul64_(core_id, out.neurons_per_core);
    } else {
        // Best-effort: derive from node/core ids (keeps deterministic even if base mismatched).
        out.core_neuron_base = expected_core_base;
    }

    return out;
}

}} // namespace SST::SnnDL

