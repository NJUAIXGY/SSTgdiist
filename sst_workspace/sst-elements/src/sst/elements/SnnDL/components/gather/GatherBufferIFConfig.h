// -*- c++ -*-
//
// GatherBufferIFConfig:
// - 将 GatherBufferIF 构造期的大量 params.find(...) 收敛到一处，降低主构造函数噪音。
// - 仅做参数解析/默认值，不引入新的运行期组件或装配点。
//

#pragma once

#include <cstdint>
#include <string>

namespace SST {
class Params;
}

namespace SST { namespace SnnDL {

struct GatherBufferIFConfig {
    int verbose = 0;

    // Diagnostics (P2)
    bool diag_enable = false;
    bool debug_enable = false;
    bool sentinel_enable = false;
    // Experimental: step-gate progress watchdog (debugging only; disabled by default).
    bool experimental_stepgate_progress_enable = false;
    uint64_t experimental_stepgate_progress_period_cycles = 0;
    uint32_t experimental_stepgate_progress_max_reports = 0;
    uint32_t experimental_stepgate_progress_dump_level = 0;
    int experimental_stepgate_progress_owner_node = -1;
    int experimental_stepgate_progress_owner_core = -1;
    // Experimental: avoid per-cycle EndApply spin in step-gate fallback mode (default preserves legacy behavior).
    uint64_t experimental_stepgate_apply_finish_poll_period_cycles = 1;

    // Policies
    // 默认使用 cacheline 语义（更贴近 memHierarchy/通用 cacheline 事务建模）。
    // row-streaming/DMA 属于显式架构假设，必须显式 opt-in，避免默认 over-fetch 污染结论。
    std::string merge_policy = "cacheline";
    std::string sort_policy = "row";

    // Core knobs
    uint32_t row_bytes_guess = 8192;
    uint64_t sram_bytes = 256 * 1024;
    bool gap_merge_enable = true;
    uint64_t gap_merge_k_bytes = 0;
    uint64_t burst_bytes_max = 64 * 1024;

    // Experimental: GCSS value-line fusion (VLF).
    // When enabled, staged reads are fused at cacheline granularity without absorbing "holes"
    // (i.e., no byte-gap fill / no row-window coarse merge). This targets pathological
    // read amplification observed in GCSS value-only paths.
    bool vlf_enable = false;
    // Optional: merge adjacent cachelines into contiguous runs (still no holes).
    bool vlf_run_enable = false;

    // Bank/row ordering
    uint32_t bank_bits = 0;
    uint32_t bank_shift = 0;
    bool bank_auto_enable = true;
    uint32_t bank_auto_min_banks = 4;
    uint32_t bank_auto_max_banks = 32;

    // Apply-stage issue scheduling.
    std::string apply_issue_policy = "order"; // order
    uint32_t apply_frags_per_issue = 1;       // max frags per scheduling step (0=unlimited)
    uint32_t apply_bank_credit = 1;           // max active granules per bank (0=unlimited)
    uint64_t apply_age_fair_ns = 2000;        // age-based fairness threshold (ns), 0=disable

    // Coarse row-window
    bool row_window_enable = false;
    uint64_t row_window_bytes = 0;
    uint64_t row_window_timeout_ns = 0;

    // Pipeline / timing
    uint32_t sram_access_ns = 0;
    uint32_t max_inflight_reads = 128;
    uint64_t tail_wait_timeout_ns = 0;
    bool allow_apply_miss_read = false;
    bool flush_after_scatter = true;
    bool strict_mode = true;
    bool double_buffer_enable = true;
    bool window_auto = false;
    bool step_gate_enable = false;
    int manual_window_drive_ignored = 0; // deprecated
    uint64_t window_cycles_gather = 0;
    uint64_t window_cycles_apply = 0;
    uint64_t window_cycles_scatter = 0;
    bool apply_auto_end_enable = true;
    bool scatter_immediate_complete = false;
    std::string clock = "1GHz";

    // Optional exports / probes
    bool emit_stage_events = false;
    bool emit_stage_events_lenient = false;
    std::string stage_cycles_csv;
    std::string probe_gas_csv;
    bool defer_issue_until_apply = false;
    uint64_t gather_auto_end_bytes = 0;
    uint64_t gather_auto_end_reads = 0;

    // Dense microbench correctness: byte-exact verification (optional; diagnostics only).
    bool byte_exact_verify_enable = false;
    std::string byte_exact_verify_mode;
    uint32_t byte_exact_verify_row_scale = 1024;
    uint32_t byte_exact_verify_max_mismatch = 8;
    uint64_t byte_exact_verify_base_addr = 0;
    uint32_t byte_exact_verify_rows = 0;
    uint32_t byte_exact_verify_cols = 0;
    // Dense layout interpretation for dense_rowcol_v1 (default preserves legacy row-major decoding).
    std::string byte_exact_dense_layout_mode = "row_major"; // row_major|phys_v1
    uint32_t byte_exact_dense_phys_dram_row_bytes = 0;      // phys_v1: DRAM row bytes (e.g., 8192)
    std::string byte_exact_verify_file_path;
    uint32_t byte_exact_verify_sample_bytes = 64;
    uint32_t byte_exact_verify_max_resps = 8;
    int byte_exact_verify_owner_node = -1;
    int byte_exact_verify_owner_core = -1;
    uint64_t byte_exact_verify_rowptr_offset = 0;
    uint64_t byte_exact_verify_colidx_offset = 0;
    uint64_t byte_exact_verify_blockdata_offset = 0;

    // Adaptive k
    bool k_adapt_enable = false;
    uint32_t k_adapt_window_N = 8;
    double k_alpha_bw = 0.2;
    double k_alpha_k = 0.2;
    uint64_t k_min_bytes = 512;
    uint64_t k_max_bytes = 64 * 1024;
    uint64_t k_delta_bytes = 512;

    // Adaptive control
    bool ctrl_enable = false;
    uint32_t ctrl_probe_every_N = 4;
    uint32_t ctrl_cooldown_N = 4;
    double ctrl_eps_reqs = 0.02;
    double ctrl_eps_burst = 0.05;
    uint64_t ctrl_lat_tol_ns = 1;
    std::string ctrl_k_list = "512,1024,2048,4096,8192";
    std::string ctrl_rowwin_list = "0,16384,32768,65536";
    std::string ctrl_timeout_list = "0,300,600";

    // Experimental: DRAM command-cost guided gap-merge/row-pack decisions during segment build.
    // This is intentionally isolated from baseline GAS semantics and must be explicitly enabled.
    bool dram_cmd_cost_merge_enable = false;
    uint32_t dram_cmd_t_row_hit_ns = 30;
    uint32_t dram_cmd_t_row_miss_ns = 120;

    // Granule/window metrics export
    std::string export_granules_csv;
    uint32_t node_id = 0;
    uint32_t core_id = static_cast<uint32_t>(-1);
    std::string export_window_metrics_csv;
};

GatherBufferIFConfig parseGatherBufferIFConfig(const SST::Params& params);

}} // namespace SST::SnnDL
