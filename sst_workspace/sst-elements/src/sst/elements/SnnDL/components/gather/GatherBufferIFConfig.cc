// -*- c++ -*-
//
// GatherBufferIFConfig.cc
//

#include "gather/GatherBufferIFConfig.h"

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

GatherBufferIFConfig parseGatherBufferIFConfig(const SST::Params& params) {
    GatherBufferIFConfig c{};

    c.verbose = params.find<int>("verbose", 0);

    c.diag_enable = (params.find<int>("diag_enable", 0) != 0);
    c.debug_enable = (params.find<int>("snndl_debug", 0) != 0);
    c.sentinel_enable = (params.find<int>("sentinel_enable", 0) != 0);
    c.experimental_stepgate_progress_enable = (params.find<int>("experimental_stepgate_progress_enable", 0) != 0);
    c.experimental_stepgate_progress_period_cycles =
        params.find<uint64_t>("experimental_stepgate_progress_period_cycles", 0);
    c.experimental_stepgate_progress_max_reports =
        params.find<uint32_t>("experimental_stepgate_progress_max_reports", 0);
    c.experimental_stepgate_progress_dump_level =
        params.find<uint32_t>("experimental_stepgate_progress_dump_level", 0);
    c.experimental_stepgate_progress_owner_node =
        params.find<int>("experimental_stepgate_progress_owner_node", -1);
    c.experimental_stepgate_progress_owner_core =
        params.find<int>("experimental_stepgate_progress_owner_core", -1);
    c.experimental_stepgate_apply_finish_poll_period_cycles =
        params.find<uint64_t>("experimental_stepgate_apply_finish_poll_period_cycles", 1);

    c.merge_policy = params.find<std::string>("merge_policy", "cacheline");
    c.sort_policy = params.find<std::string>("sort_policy", "row");

    c.row_bytes_guess = params.find<uint32_t>("row_bytes_guess", 8192);
    c.sram_bytes = params.find<uint64_t>("sram_bytes", 256 * 1024);
    c.gap_merge_enable = params.find<int>("gap_merge_enable", 1) != 0;
    c.gap_merge_k_bytes = params.find<uint64_t>("gap_merge_k_bytes", 0);
    c.burst_bytes_max = params.find<uint64_t>("burst_bytes_max", 64 * 1024);

    c.vlf_enable = params.find<int>("vlf_enable", 0) != 0;
    c.vlf_run_enable = params.find<int>("vlf_run_enable", 0) != 0;

    c.bank_bits = params.find<uint32_t>("bank_bits", 0);
    c.bank_shift = params.find<uint32_t>("bank_shift", 0);
    c.bank_auto_enable = params.find<int>("bank_auto_enable", 1) != 0;
    c.bank_auto_min_banks = params.find<uint32_t>("bank_auto_min_banks", 4);
    c.bank_auto_max_banks = params.find<uint32_t>("bank_auto_max_banks", 32);

    c.apply_issue_policy = params.find<std::string>("apply_issue_policy", "order");
    c.apply_frags_per_issue = params.find<uint32_t>("apply_frags_per_issue", 1);
    c.apply_bank_credit = params.find<uint32_t>("apply_bank_credit", 1);
    c.apply_age_fair_ns = params.find<uint64_t>("apply_age_fair_ns", 2000);

    c.row_window_enable = params.find<int>("row_window_enable", 0) != 0;
    c.row_window_bytes = params.find<uint64_t>("row_window_bytes", 0);
    c.row_window_timeout_ns = params.find<uint64_t>("row_window_timeout_ns", 0);

    c.sram_access_ns = params.find<uint32_t>("sram_access_ns", 0);
    c.max_inflight_reads = params.find<uint32_t>("max_inflight_reads", 128);
    c.tail_wait_timeout_ns = params.find<uint64_t>("tail_wait_timeout_ns", 0);
    c.allow_apply_miss_read = params.find<int>("allow_apply_miss_read", 0) != 0;
    c.flush_after_scatter = params.find<int>("flush_after_scatter", 1) != 0;
    c.strict_mode = params.find<int>("strict_mode", 1) != 0;
    c.double_buffer_enable = params.find<int>("double_buffer_enable", 1) != 0;
    c.window_auto = params.find<int>("window_auto", 0) != 0;
    c.step_gate_enable = params.find<int>("step_gate_enable", 0) != 0;

    // Deprecated, kept for compatibility (GatherBufferIF always clock-driven in auto mode).
    c.manual_window_drive_ignored = params.find<int>("manual_window_drive", 0);

    c.window_cycles_gather = params.find<uint64_t>("window_cycles_gather", 0);
    c.window_cycles_apply = params.find<uint64_t>("window_cycles_apply", 0);
    c.window_cycles_scatter = params.find<uint64_t>("window_cycles_scatter", 0);
    c.apply_auto_end_enable = params.find<int>("apply_auto_end_enable", 1) != 0;
    c.scatter_immediate_complete = params.find<int>("scatter_immediate_complete", 0) != 0;
    c.clock = params.find<std::string>("clock", "1GHz");

    // step_gate_enable=1 时阶段事件是全局 step 同步/收尾判定的关键输入，默认自动开启以避免隐式卡死。
    c.emit_stage_events = params.find<int>("emit_stage_events", c.step_gate_enable ? 1 : 0) != 0;
    c.emit_stage_events_lenient = params.find<int>("emit_stage_events_lenient", 0) != 0;
    c.stage_cycles_csv = params.find<std::string>("stage_cycles_csv", "");
    c.probe_gas_csv = params.find<std::string>("probe_gas_csv", "");
    c.defer_issue_until_apply = params.find<int>("defer_issue_until_apply", 0) != 0;
    c.gather_auto_end_bytes = params.find<uint64_t>("gather_auto_end_bytes", 0);
    c.gather_auto_end_reads = params.find<uint64_t>("gather_auto_end_reads", 0);

    c.byte_exact_verify_enable = params.find<int>("byte_exact_verify_enable", 0) != 0;
    c.byte_exact_verify_mode = params.find<std::string>("byte_exact_verify_mode", "");
    c.byte_exact_verify_row_scale = params.find<uint32_t>("byte_exact_verify_row_scale", 1024);
    c.byte_exact_verify_max_mismatch = params.find<uint32_t>("byte_exact_verify_max_mismatch", 8);
    c.byte_exact_verify_base_addr = params.find<uint64_t>("byte_exact_verify_base_addr", 0);
    c.byte_exact_verify_rows = params.find<uint32_t>("byte_exact_verify_rows", 0);
    c.byte_exact_verify_cols = params.find<uint32_t>("byte_exact_verify_cols", 0);
    c.byte_exact_dense_layout_mode = params.find<std::string>("byte_exact_dense_layout_mode", "row_major");
    c.byte_exact_dense_phys_dram_row_bytes = params.find<uint32_t>("byte_exact_dense_phys_dram_row_bytes", 0);
    c.byte_exact_verify_file_path = params.find<std::string>("byte_exact_verify_file_path", "");
    c.byte_exact_verify_sample_bytes = params.find<uint32_t>("byte_exact_verify_sample_bytes", 64);
    c.byte_exact_verify_max_resps = params.find<uint32_t>("byte_exact_verify_max_resps", 8);
    c.byte_exact_verify_owner_node = params.find<int>("byte_exact_verify_owner_node", -1);
    c.byte_exact_verify_owner_core = params.find<int>("byte_exact_verify_owner_core", -1);
    c.byte_exact_verify_rowptr_offset = params.find<uint64_t>("byte_exact_verify_rowptr_offset", 0);
    c.byte_exact_verify_colidx_offset = params.find<uint64_t>("byte_exact_verify_colidx_offset", 0);
    c.byte_exact_verify_blockdata_offset = params.find<uint64_t>("byte_exact_verify_blockdata_offset", 0);

    c.k_adapt_enable = params.find<int>("k_adapt_enable", 0) != 0;
    c.k_adapt_window_N = params.find<uint32_t>("k_adapt_window_N", 8);
    c.k_alpha_bw = params.find<double>("k_alpha_bw", 0.2);
    c.k_alpha_k = params.find<double>("k_alpha_k", 0.2);
    c.k_min_bytes = params.find<uint64_t>("k_min_bytes", 512);
    c.k_max_bytes = params.find<uint64_t>("k_max_bytes", 64 * 1024);
    c.k_delta_bytes = params.find<uint64_t>("k_delta_bytes", 512);

    c.ctrl_enable = params.find<int>("ctrl_enable", 0) != 0;
    c.ctrl_probe_every_N = params.find<uint32_t>("ctrl_probe_every_N", 4);
    c.ctrl_cooldown_N = params.find<uint32_t>("ctrl_cooldown_N", 4);
    c.ctrl_eps_reqs = params.find<double>("ctrl_eps_reqs", 0.02);
    c.ctrl_eps_burst = params.find<double>("ctrl_eps_burst", 0.05);
    c.ctrl_lat_tol_ns = params.find<uint64_t>("ctrl_lat_tol_ns", 1);
    c.ctrl_k_list = params.find<std::string>("ctrl_k_list", "512,1024,2048,4096,8192");
    c.ctrl_rowwin_list = params.find<std::string>("ctrl_rowwin_list", "0,16384,32768,65536");
    c.ctrl_timeout_list = params.find<std::string>("ctrl_timeout_list", "0,300,600");

    c.dram_cmd_cost_merge_enable = params.find<int>("dram_cmd_cost_merge_enable", 0) != 0;
    c.dram_cmd_t_row_hit_ns = params.find<uint32_t>("dram_cmd_t_row_hit_ns", 30);
    c.dram_cmd_t_row_miss_ns = params.find<uint32_t>("dram_cmd_t_row_miss_ns", 120);

    c.export_granules_csv = params.find<std::string>("export_granules_csv", "");
    c.node_id = params.find<uint32_t>("node_id", 0);
    c.core_id = params.find<uint32_t>("core_id", static_cast<uint32_t>(-1));
    c.export_window_metrics_csv = params.find<std::string>("export_window_metrics_csv", "");

    return c;
}

}} // namespace SST::SnnDL
