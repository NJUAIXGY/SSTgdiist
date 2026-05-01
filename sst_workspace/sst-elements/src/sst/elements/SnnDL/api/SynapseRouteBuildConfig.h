// -*- c++ -*-
//
// SynapseRouteBuildConfig:
// - 权重驱动路由构建（dense/BCSR/edges_csv）所需的参数集合。
//
// 注意：该配置不包含传输/封包语义；未来将作为 Synapse/Route 子系统的配置输入。
// 为保持兼容，Phase2 期间保留旧别名 `SpikeCommRoutingConfig`（原本定义于 SpikeCommSubsystem.h）。

#pragma once

#include <cstdint>
#include <string>

#include "MulticastLimits.h"

namespace SST { namespace SnnDL {

struct SynapseRouteBuildConfig {
    bool routing_weight_driven = false;
    bool log_weight_details = false;
    bool verify_routing_weights = false;
    bool route_summary_enable = false;

    // Native multicast (blocked multicast; block size configurable; ingress selectable)
    bool multicast_enable = false;
    uint32_t multicast_block_w = 2;
    uint32_t multicast_block_h = 2;
    uint32_t multicast_block_d = 1;
    bool multicast_die_local_only = false;
    bool route3d_native_targets = false;
    std::string multicast_ingress_policy = "top_left";
    // Orthogonal policy points (string-based for backward compatibility & easy extension):
    // - inter: how INTER-stage unicast is routed across mesh (router-level)
    // - intra: how INTRA-stage blocked multicast expands within a block (router-level)
    std::string multicast_inter_policy = "xy";
    std::string multicast_intra_policy = "manhattan_x_first";

    // Route inputs (keep consistent with legacy cache key semantics).
    // NOTE: "rows" is interpreted as per-PE rows (neurons_per_pe). For per-core BCSR files,
    // SpikeCommSubsystem will derive per-core rows via rows_hint = ceil(rows / cores_per_pe).
    uint32_t rows = 0;
    uint32_t cols = 0;            // global cols (weights_cols)
    uint32_t total_nodes = 16;    // total PEs
    std::string mesh_shape;       // optional 'WxH' or 'WxHxZ'; native_3d route uses it directly
    uint32_t cores_per_pe = 1;    // total_cores
    uint32_t neurons_per_pe = 0;  // derived; used for denom & cache-key
    bool use_post_row_pre_col = false;
    bool real_synapse_inputs_available = false;

    std::string weights_template;
    float routing_epsilon = 1e-8f;
    uint32_t routing_topk = 0;
    uint32_t routing_topk_per_pe = 0;
    bool route_exclude_self_pe = false;
    std::string route_layers_mask;
    bool route_filter_warn = true;

    // Mapping integration
    std::string mapping_mode;
    std::string mapping_edges_file;
    bool mapping_csv_has_header = true;
    std::string mapping_csv_separator = ",";
    bool mapping_assume_block_ids = true;

    // Optional: BCSR route parsing parameters (used when weights_template points to BCSR bin).
    bool use_bcsr = false;
    uint32_t bcsr_br = 0;
    uint32_t bcsr_bc = 0;
    uint32_t bcsr_idx_bytes = 0;
    uint32_t bcsr_val_bytes = 0;
    uint64_t base_addr = 0;
    uint64_t bcsr_rowptr_addr = 0;
    uint64_t bcsr_colidx_addr = 0;
    uint64_t bcsr_blockdata_addr = 0;
    uint64_t bcsr_blockids_addr = 0;
};

// 兼容：旧名仍可用（Phase2 以后可逐步替换为 SynapseRouteBuildConfig）。
using SpikeCommRoutingConfig = SynapseRouteBuildConfig;

}} // namespace SST::SnnDL
