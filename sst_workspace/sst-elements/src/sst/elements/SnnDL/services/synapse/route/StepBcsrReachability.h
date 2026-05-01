// -*- c++ -*-
//
// StepBcsrReachability:
// - 为 StepActivationSubsystem 提供 “基于 BCSR reachability 的 post 采样路由” 构建逻辑；
// - 放入 synapse/route 域，避免 stimulus 域重复实现 BCSR 解析与口径漂移。
//

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "ISynapseRoute.h"

namespace SST { class Output; }

namespace SST { namespace SnnDL {

struct StepBcsrReachabilityConfig {
    std::string bcsr_template;
    bool build_local_only = true;
    bool log_enable = false;

    uint32_t bcsr_rows_per_core = 0;
    uint32_t bcsr_br = 0;
    uint32_t bcsr_bc = 0;
    uint32_t bcsr_idx_bytes = 0;
    uint32_t bcsr_val_bytes = 0;
    uint64_t bcsr_rowptr_offset = 0;
    uint64_t bcsr_colidx_offset = 0;
    uint64_t bcsr_blockdata_offset = 0;
    uint64_t bcsr_blockids_offset = 0;
    double bcsr_weight_epsilon = 0.0;
};

struct StepBcsrReachabilityRuntime {
    SST::Output* log = nullptr;
    uint32_t node_id = 0;
    uint32_t total_nodes = 1;
    uint32_t num_cores = 1;
    uint32_t neurons_per_core = 1;
    uint32_t neurons_per_pe_cfg = 0;
    uint64_t global_neuron_base = 0;
};

// 输出 routes 仅覆盖本 PE 的 pre_global 范围（[global_neuron_base, global_neuron_base+num_cores*neurons_per_core)）。
// 返回 true 表示成功构建且 routes_out 非空；失败时 routes_out/pre_with_routes_out 会被清空。
bool buildStepBcsrReachabilityRoutes(const StepBcsrReachabilityConfig& cfg,
                                     const StepBcsrReachabilityRuntime& rt,
                                     ISynapseRoute::RouteMap& routes_out,
                                     std::vector<uint32_t>& pre_with_routes_out);

}} // namespace SST::SnnDL

