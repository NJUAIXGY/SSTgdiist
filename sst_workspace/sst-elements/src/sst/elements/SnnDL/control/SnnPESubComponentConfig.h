// -*- c++ -*-
//
// SnnPESubComponentConfig:
// - 将 SnnPESubComponent 构造期的大量 params.find(...) 收敛到一处，降低主构造函数噪音。
// - 仅做参数解析/默认值/轻量规整，不引入新的运行期组件或装配点。
//

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/params.h>

#include "WorkloadConfig.h"

namespace SST { namespace SnnDL {

struct SnnPESubComponentConfig {
    // Diagnostics/sentinel
    bool sentinel_enable = false;

    // Basic identity
    int core_id = 0;
    int total_cores = 8;
    uint64_t global_neuron_base = 0;
    uint32_t num_neurons = 64;
    uint64_t base_addr = 0;
    uint32_t node_id = 0;
    uint32_t total_nodes = 1;
    int verbose = 0;
    bool enable_extended_diagnostics = false;

    // Optional profiling (compiled out unless SNNDL_ENABLE_PROFILING)
    bool profiler_enable = false;
    std::string profiler_csv_prefix;

    // Workload selector (normalized lowercase; env override preserved for compatibility)
    std::string workload_impl = "snn";

    // CoreShell knobs
    bool enable_weight_fetch = false;
    bool workload_spike_input_enable = false;
    bool write_weights_on_init = true;
    uint64_t memory_warmup_cycles = 1000;
    float init_default_weight = 0.5f;
    bool readresp_zero_fallback = false;
    uint32_t max_outstanding_requests = 16;
    std::string synapse_weight_mode = "bcsr_gas"; // bcsr_gas | gcss_valueonly_dstcore | gcss_valueonly_dstcore_idx2 | gcss_idx2_rowmphf | gcss_valueonly_dstcore_vlf_premphf | gcss_valueonly_dstcore_vlf_premphf_plp

    // Weight cache
    uint32_t max_cache_entries = 65536;
    bool use_clock_weight_cache = false;
    bool disable_weight_cache = false;

    // Legacy fallback (should remain default-off)
    bool use_event_weight_fallback = false;

    // Summary printing (default off)
    bool route_summary_enable = false;

    // Read merge knobs
    bool merge_read_cacheline = true;
    bool merge_read_row = false;
    bool merge_read_auto = false;
    uint32_t line_size_bytes = 64;
    // Dense weights physical layout (experiment; default row_major)
    std::string dense_layout_mode = "row_major"; // row_major|phys_v1
    uint32_t dense_phys_dram_row_bytes = 0;      // required when dense_layout_mode=phys_v1

    // GAS orchestration knobs (CoreShell-level)
    bool gas_enable = false;
    bool gas_window_mode = false;
    bool gas_manual_window_drive_requested = false; // deprecated; kept for diagnostics
    uint64_t gas_window_cycles_gather = 200;

    // Scheme-1 (slice baseline)
    bool scheme1_enable = false;
    uint32_t scheme1_slices = 8;
    uint64_t scheme1_gather_cycles = 100;
    uint64_t scheme1_slice_gap_cycles = 0;
    uint64_t scheme1_scatter_cycles = 1;
    bool scheme1_partition_mod = false;

    // Byte-exact verification (dense/raw_bcsr) – off by default
    bool byte_exact_verify_enable = false;
    std::string byte_exact_verify_mode;
    uint32_t byte_exact_verify_row_scale = 1024;
    uint32_t byte_exact_verify_max_mismatch = 8;

    // Loader barrier / shared done flag
    std::string loader_done_key;

    // Window-read (strict GAS) knobs
    bool window_read_enable = false;
    bool window_read_debug = false;
    uint32_t scatter_diag_limit = 0;
    uint32_t window_read_budget = 1024;
    bool read_force_single = false;
    uint64_t edge_collector_max_capacity = 1000000;

    // Weight indexing / routing knobs
    uint32_t weights_cols = 0;
    std::string index_mode = "pre_row_post_col";
    bool verify_routing_weights = false;
    bool enable_detailed_map_log = false;
    bool log_weight_details = false;

    uint64_t loader_barrier_cycles = 0;

    // BCSR meta (control-side wiring only; semantics live in synapse/weights)
    uint32_t bcsr_cols = 0;
    uint32_t bcsr_block_rows = 16;
    uint32_t bcsr_block_cols = 16;
    uint32_t bcsr_idx_bytes = 2;
    uint32_t bcsr_val_bytes = 4;
    uint64_t bcsr_rowptr_offset = 0;
    uint64_t bcsr_colidx_offset = 0;
    uint64_t bcsr_blockdata_offset = 0;
    uint64_t bcsr_blockids_offset = 0;
    std::string bcsr_layout_mode = "flat"; // flat|rowpack_v1
    uint32_t bcsr_colidx_row_stride_bytes = 0;
    uint32_t bcsr_blockdata_row_stride_bytes = 0;
    uint32_t bcsr_blockids_row_stride_bytes = 0;
    std::string bcsr_block_fetch_mode = "full_block"; // full_block|row_cacheline
    uint64_t per_core_stride = 0;
    uint32_t bcsr_row_index_cache_cap = 64;
    uint32_t bcsr_block_cache_cap = 256;
    bool bcsr_prefetch_all = false;
    bool verify_weights = false;
    bool bcsr_force_file_read = false;
    bool bcsr_rowptr_file_fallback_enable = false;

    // Apply/Scatter accumulator
    bool apply_acc_enable = false;
    uint64_t acc_high_watermark_bytes = 16ull * 1024ull * 1024ull;
    bool acc_spill_enable = true;
    bool apply_dense_acc_enable = true;
    bool acc_shadow_verify_enable = false;

    // Stage CSV / finish behavior
    std::string stage_events_csv;
    bool quiet_finish_logs = false;

    // Edge recording (diagnostic / window-read)
    bool record_edge_apply_enable = false;
    bool record_edge_idle_enable = false;
    bool record_edge_scatter_enable = false;

    // Misc cached paths
    std::string weights_template;
    std::string gcss_index_template;
    uint32_t neurons_per_pe = 0;
    std::string weights_file;

    // Semantic verify knobs (read by WeightMemorySubsystem orchestrator)
    bool bcsr_semantic_verify_enable = false;
    uint32_t bcsr_semantic_verify_max_edges = 64;
    uint32_t bcsr_semantic_verify_max_mismatch = 8;
    float bcsr_semantic_verify_abs_tol = 1e-6f;
    float bcsr_semantic_verify_rel_tol = 1e-6f;
};

inline SnnPESubComponentConfig parseSnnPESubComponentConfig(const SST::Params& params) {
    SnnPESubComponentConfig c{};

    c.sentinel_enable = params.find<int>("sentinel_enable", 0) != 0;

    c.core_id = params.find<int>("core_id", 0);
    c.total_cores = params.find<int>("total_cores", 8);
    c.global_neuron_base = params.find<uint64_t>("global_neuron_base", 0);
    c.num_neurons = params.find<uint32_t>("num_neurons", 64);
    c.base_addr = params.find<uint64_t>("base_addr", 0);
    c.node_id = params.find<uint32_t>("node_id", 0);
    c.total_nodes = params.find<uint32_t>("total_nodes", 1);
    c.verbose = params.find<int>("verbose", 0);
    c.enable_extended_diagnostics = params.find<int>("enable_extended_diagnostics", 0) != 0;

    c.profiler_enable = params.find<int>("enable_profiler", 0) != 0;
    c.profiler_csv_prefix = params.find<std::string>("profiler_csv_prefix", "");

    // Phase6: workload selection (Params first, env override for compatibility)
    c.workload_impl = workloadImplFromParamsOrEnvOverride(params, "snn");

    c.enable_weight_fetch = params.find<int>("enable_weight_fetch", 0) != 0;
    c.workload_spike_input_enable = params.find<int>("workload_spike_input_enable", 0) != 0;
    c.write_weights_on_init = params.find<int>("write_weights_on_init", 1) != 0;
    c.memory_warmup_cycles = params.find<uint64_t>("memory_warmup_cycles", 1000);
    c.init_default_weight = params.find<float>("init_default_weight", 0.5f);
    c.readresp_zero_fallback = params.find<int>("readresp_zero_fallback", 0) != 0;
    c.max_outstanding_requests = params.find<uint32_t>("max_outstanding_requests", 16);
    {
        std::string mode = params.find<std::string>("synapse_weight_mode", "bcsr_gas");
        for (char& ch : mode) {
            if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
        }
        if (mode == "gscc_valueonly_dstcore") mode = "gcss_valueonly_dstcore";
        if (mode == "gscc_valueonly_dstcore_vlf_premphf") mode = "gcss_valueonly_dstcore_vlf_premphf";
        if (mode == "gscc_valueonly_dstcore_vlf_premphf_plp") mode = "gcss_valueonly_dstcore_vlf_premphf_plp";
        if (mode != "bcsr_gas" &&
            mode != "gcss_valueonly_dstcore" &&
            mode != "gcss_valueonly_dstcore_idx2" &&
            mode != "gcss_idx2_rowmphf" &&
            mode != "gcss_valueonly_dstcore_vlf_premphf" &&
            mode != "gcss_valueonly_dstcore_vlf_premphf_plp") {
            mode = "bcsr_gas";
        }
        c.synapse_weight_mode = mode;
    }

    c.max_cache_entries = params.find<uint32_t>("max_cache_entries", 65536);
    c.use_clock_weight_cache = params.find<int>("use_clock_weight_cache", 0) != 0;
    c.disable_weight_cache = params.find<int>("disable_weight_cache", 0) != 0;

    c.use_event_weight_fallback = params.find<int>("use_event_weight_fallback", 0) != 0;
    c.route_summary_enable = params.find<int>("route_summary_enable", 0) != 0;

    c.merge_read_cacheline = params.find<int>("merge_read_cacheline", 1) != 0;
    c.merge_read_row = params.find<int>("merge_read_row", 0) != 0;
    c.merge_read_auto = params.find<int>("merge_read_auto", 0) != 0;
    c.line_size_bytes = params.find<uint32_t>("line_size_bytes", 64);
    c.dense_layout_mode = params.find<std::string>("dense_layout_mode", "row_major");
    c.dense_phys_dram_row_bytes = params.find<uint32_t>("dense_phys_dram_row_bytes", 0);

    c.gas_enable = params.find<int>("gas_enable", 0) != 0;
    c.gas_window_mode = params.find<int>("gas_window_mode", 0) != 0;
    c.gas_manual_window_drive_requested = params.find<int>("gas_manual_window_drive", 0) != 0; // deprecated
    c.gas_window_cycles_gather = clampNonZeroU64(params.find<uint64_t>("gas_window_cycles_gather", 200));

    c.scheme1_enable = params.find<int>("scheme1_enable", 0) != 0;
    c.scheme1_slices = params.find<uint32_t>("scheme1_slices", 8);
    c.scheme1_gather_cycles = clampNonZeroU64(params.find<uint64_t>("scheme1_gather_cycles", 100));
    c.scheme1_slice_gap_cycles = params.find<uint64_t>("scheme1_slice_gap_cycles", 0);
    c.scheme1_scatter_cycles = clampNonZeroU64(params.find<uint64_t>("scheme1_scatter_cycles", 1));
    c.scheme1_partition_mod = params.find<int>("scheme1_partition_mod", 0) != 0;

    c.byte_exact_verify_enable = params.find<int>("byte_exact_verify_enable", 0) != 0;
    c.byte_exact_verify_mode = params.find<std::string>("byte_exact_verify_mode", "");
    c.byte_exact_verify_row_scale = params.find<uint32_t>("byte_exact_verify_row_scale", 1024);
    c.byte_exact_verify_max_mismatch = params.find<uint32_t>("byte_exact_verify_max_mismatch", 8);

    c.loader_done_key = params.find<std::string>("loader_done_key", "");

    c.window_read_enable = params.find<int>("window_read_enable", 0) != 0;
    c.window_read_debug = params.find<int>("window_read_debug", 0) != 0;
    c.scatter_diag_limit = params.find<uint32_t>("scatter_diag_limit", 0);
    c.window_read_budget = params.find<uint32_t>("window_read_budget", 1024);
    c.read_force_single = params.find<int>("read_force_single", 0) != 0;
    c.edge_collector_max_capacity = params.find<uint64_t>("edge_collector_max_capacity", 1000000);

    c.weights_cols = params.find<uint32_t>("weights_cols", 0);
    c.index_mode = params.find<std::string>("index_mode", "pre_row_post_col");
    c.verify_routing_weights = params.find<int>("verify_routing_weights", 0) != 0;
    c.enable_detailed_map_log = params.find<int>("enable_detailed_map_log", 0) != 0;
    c.log_weight_details = params.find<int>("log_weight_details", 0) != 0;
    c.loader_barrier_cycles = params.find<uint64_t>("loader_barrier_cycles", 0);

    c.bcsr_cols = params.find<uint32_t>("weights_cols", c.num_neurons);
    c.bcsr_block_rows = params.find<uint32_t>("bcsr_block_rows", 16);
    c.bcsr_block_cols = params.find<uint32_t>("bcsr_block_cols", 16);
    c.bcsr_idx_bytes = params.find<uint32_t>("bcsr_idx_bytes", 2);
    c.bcsr_val_bytes = params.find<uint32_t>("bcsr_val_bytes", 4);
    c.bcsr_rowptr_offset = params.find<uint64_t>("bcsr_rowptr_offset", 0);
    c.bcsr_colidx_offset = params.find<uint64_t>("bcsr_colidx_offset", 0);
    c.bcsr_blockdata_offset = params.find<uint64_t>("bcsr_blockdata_offset", 0);
    c.bcsr_blockids_offset = params.find<uint64_t>("bcsr_blockids_offset", 0);
    c.bcsr_layout_mode = params.find<std::string>("bcsr_layout_mode", "flat");
    c.bcsr_colidx_row_stride_bytes = params.find<uint32_t>("bcsr_colidx_row_stride_bytes", 0);
    c.bcsr_blockdata_row_stride_bytes = params.find<uint32_t>("bcsr_blockdata_row_stride_bytes", 0);
    c.bcsr_blockids_row_stride_bytes = params.find<uint32_t>("bcsr_blockids_row_stride_bytes", 0);
    c.bcsr_block_fetch_mode = params.find<std::string>("bcsr_block_fetch_mode", "full_block");
    c.per_core_stride = params.find<uint64_t>("per_core_stride", 0);

    c.bcsr_row_index_cache_cap = params.find<uint32_t>("bcsr_row_index_cache_cap", 64);
    c.bcsr_block_cache_cap = params.find<uint32_t>("bcsr_block_cache_cap", 256);

    c.apply_acc_enable = params.find<int>("apply_acc_enable", 0) != 0;
    c.acc_high_watermark_bytes = params.find<uint64_t>("acc_high_watermark_bytes", 16ull * 1024ull * 1024ull);
    c.acc_spill_enable = params.find<int>("acc_spill_enable", 1) != 0;
    c.stage_events_csv = params.find<std::string>("stage_events_csv", "");

    c.bcsr_prefetch_all = params.find<int>("bcsr_prefetch_all", 0) != 0;
    c.verify_weights = params.find<int>("verify_weights", 0) != 0;
    c.bcsr_force_file_read = params.find<int>("bcsr_force_file_read", 0) != 0;
    c.bcsr_rowptr_file_fallback_enable = params.find<int>("bcsr_rowptr_file_fallback_enable", 0) != 0;
    c.quiet_finish_logs = params.find<int>("quiet_finish_logs", 0) != 0;

    // Edge recording defaults depend on GAS/window pipeline state.
    {
        const int record_apply_default = (c.gas_window_mode && c.apply_acc_enable) ? 1 : 0;
        c.record_edge_apply_enable = params.find<int>("record_edge_apply_enable", record_apply_default) != 0;
        c.record_edge_idle_enable = params.find<int>("record_edge_idle_enable", 0) != 0;
        c.record_edge_scatter_enable = params.find<int>("record_edge_scatter_enable", 0) != 0;
    }

    // Dense accumulator
    c.apply_dense_acc_enable = params.find<int>("apply_dense_acc_enable", 1) != 0;
    c.acc_shadow_verify_enable =
        c.apply_dense_acc_enable && (params.find<int>("acc_shadow_verify_enable", 0) != 0);

    c.weights_template = params.find<std::string>("weights_template", "");
    c.gcss_index_template = params.find<std::string>("gcss_index_template", "");
    c.neurons_per_pe = params.find<uint32_t>("neurons_per_pe", 0);
    c.weights_file = params.find<std::string>("weights_file", "");

    // Semantic verify knobs (passed to WeightMemorySubsystem orchestrator).
    c.bcsr_semantic_verify_enable = params.find<int>("bcsr_semantic_verify_enable", 0) != 0;
    c.bcsr_semantic_verify_max_edges = params.find<uint32_t>("bcsr_semantic_verify_max_edges", 64);
    c.bcsr_semantic_verify_max_mismatch = params.find<uint32_t>("bcsr_semantic_verify_max_mismatch", 8);
    c.bcsr_semantic_verify_abs_tol = params.find<float>("bcsr_semantic_verify_abs_tol", 1e-6f);
    c.bcsr_semantic_verify_rel_tol = params.find<float>("bcsr_semantic_verify_rel_tol", 1e-6f);

    return c;
}

}} // namespace SST::SnnDL
