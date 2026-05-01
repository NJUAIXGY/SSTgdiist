// -*- c++ -*-
//
// StepBcsrReachability implementation
//

#include "synapse/route/StepBcsrReachability.h"

#include <algorithm>
#include <cmath>
#include <cinttypes>
#include <limits>

#include <sst/core/output.h>

#include "synapse/route/BcsrRouteBuilder.h"

namespace SST { namespace SnnDL {

bool buildStepBcsrReachabilityRoutes(const StepBcsrReachabilityConfig& cfg,
                                     const StepBcsrReachabilityRuntime& rt,
                                     ISynapseRoute::RouteMap& routes_out,
                                     std::vector<uint32_t>& pre_with_routes_out) {
    routes_out.clear();
    pre_with_routes_out.clear();

    if (cfg.bcsr_template.empty()) return false;
    if (rt.total_nodes == 0 || rt.num_cores == 0 || rt.neurons_per_core == 0) return false;

    const uint64_t local_total = static_cast<uint64_t>(rt.num_cores) * static_cast<uint64_t>(rt.neurons_per_core);
    const uint64_t pre_begin_64 = rt.global_neuron_base;
    const uint64_t pre_end_64 = pre_begin_64 + local_total;
    if (pre_end_64 > (static_cast<uint64_t>(std::numeric_limits<uint32_t>::max()) + 1ULL)) return false;
    const uint32_t pre_begin = static_cast<uint32_t>(pre_begin_64);
    const uint32_t pre_end = static_cast<uint32_t>(pre_end_64);

    const uint32_t rows_hint = (cfg.bcsr_rows_per_core > 0) ? cfg.bcsr_rows_per_core : rt.neurons_per_core;

    SynapseRouteBuildConfig bcfg{};
    bcfg.routing_weight_driven = false;
    bcfg.use_bcsr = true;
    bcfg.total_nodes = rt.total_nodes;
    bcfg.cores_per_pe = rt.num_cores;
    bcfg.neurons_per_pe = rt.neurons_per_pe_cfg;
    // 重要：rows 语义为“每核行数”，用于 core_offset_global 计算；post_global 一律按 (pe,core,post_local) 计算。
    bcfg.rows = rows_hint;
    bcfg.cols = 0; // allow meta override
    bcfg.weights_template = cfg.bcsr_template;
    bcfg.routing_epsilon = static_cast<float>(cfg.bcsr_weight_epsilon);
    bcfg.bcsr_br = cfg.bcsr_br;
    bcfg.bcsr_bc = cfg.bcsr_bc;
    bcfg.bcsr_idx_bytes = cfg.bcsr_idx_bytes;
    bcfg.bcsr_val_bytes = cfg.bcsr_val_bytes;
    bcfg.base_addr = 0;
    bcfg.bcsr_rowptr_addr = cfg.bcsr_rowptr_offset;
    bcfg.bcsr_colidx_addr = cfg.bcsr_colidx_offset;
    bcfg.bcsr_blockdata_addr = cfg.bcsr_blockdata_offset;
    bcfg.bcsr_blockids_addr = cfg.bcsr_blockids_offset;

    BcsrAppendOptions opt{};
    opt.pre_begin = pre_begin;
    opt.pre_end = pre_end;

    bool ok = true;
    uint32_t pe_begin = 0;
    uint32_t pe_end = rt.total_nodes;
    if (cfg.build_local_only) {
        if (rt.node_id >= rt.total_nodes) return false;
        pe_begin = rt.node_id;
        pe_end = rt.node_id + 1;
    }

    for (uint32_t pe = pe_begin; pe < pe_end && ok; ++pe) {
        for (uint32_t core = 0; core < rt.num_cores; ++core) {
            std::string path = resolveBcsrTemplate(cfg.bcsr_template, pe, static_cast<int>(core));
            if (path.empty()) { ok = false; break; }
            if (!appendRoutesFromBcsrFile(bcfg, rt.log, path, pe, static_cast<int>(core), rows_hint, routes_out, opt)) {
                ok = false;
                break;
            }
        }
    }

    if (!ok || routes_out.empty()) {
        routes_out.clear();
        pre_with_routes_out.clear();
        return false;
    }

    pre_with_routes_out.reserve(routes_out.size());
    for (const auto& kv : routes_out) {
        if (!kv.second.empty()) pre_with_routes_out.push_back(kv.first);
    }
    std::sort(pre_with_routes_out.begin(), pre_with_routes_out.end());

    if (rt.log && cfg.log_enable) {
        uint64_t edges = 0;
        size_t max_routes = 0;
        for (const auto& kv : routes_out) {
            edges += static_cast<uint64_t>(kv.second.size());
            if (kv.second.size() > max_routes) max_routes = kv.second.size();
        }
        rt.log->verbose(CALL_INFO, 1, 0,
                        "[step-activation] BCSR reachability built: node=%u pre_range=[%u,%u) pre_with_routes=%zu edges=%" PRIu64 " max_routes=%zu\n",
                        rt.node_id, pre_begin, pre_end, pre_with_routes_out.size(), edges, max_routes);
    }

    return true;
}

}} // namespace SST::SnnDL
