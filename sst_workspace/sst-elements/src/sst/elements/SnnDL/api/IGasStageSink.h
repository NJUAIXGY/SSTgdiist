// -*- c++ -*-
//
// IGasStageSink: GAS 控制面阶段事件/统计汇聚入口（StdMem glue → Control）
// - 目的：让 control/ 不解析 StandardMem::CustomResp，也不依赖 GasOpData/StandardMem 类型
//

#pragma once

#include <cstdint>

#include "GasOps.h"

namespace SST { namespace SnnDL {

struct GasStageEvent {
    GasOp op = GasOp::BeginGather;
    uint32_t superstep = 0;
    uint32_t slice = 0;
    uint32_t total_slices = 1;
    bool flag = false;
};

struct GasStatEvent {
    uint32_t superstep = 0;
    uint64_t unique_reads = 0;
    uint64_t unique_bytes = 0;
    uint64_t rowwin_triggers = 0;
    uint64_t rowwin_bytes = 0;
    uint64_t bursts = 0;
    uint64_t payload_bytes = 0;
    uint64_t window_inflight_peak = 0;
    uint64_t window_buffer_max_bytes = 0;
    uint64_t gap_absorbed_bytes = 0;
    // Front-end line-clustering diagnostics (per build/window summary)
    uint64_t frontend_staged_reads = 0;
    uint64_t frontend_staged_line_touches = 0;
    uint64_t frontend_granules_built = 0;
    // DRAM-aware Apply diagnostics (optional; only meaningful when enabled)
    uint64_t unique_line_count = 0;
    uint64_t covered_line_count = 0;
    uint64_t overfetch_bytes = 0;
    // Apply scheduler diagnostics (optional; per-window summary)
    uint64_t apply_bank_credit_effective = 0;
    // Cmd-cost guardrail diagnostics (optional; per-window summary)
    uint64_t cmd_cost_veto = 0;
    uint64_t cmd_cost_veto_fine_gap = 0;
    uint64_t cmd_cost_veto_row_window = 0;
    // Apply-stage runtime observability (per-window summary)
    uint64_t apply_issue_attempt_total = 0;
    uint64_t apply_issue_success_total = 0;
    uint64_t apply_issue_block_no_ready_total = 0;
    uint64_t apply_issue_block_inflight_cap_total = 0;
    uint64_t apply_issue_block_bank_credit_total = 0;
    uint64_t apply_issue_block_downstream_busy_total = 0;
    uint64_t apply_issue_block_retire_guard_total = 0;
    uint64_t apply_ready_queue_peak = 0;
    uint64_t apply_ready_queue_nonempty_cycles_total = 0;
    uint64_t apply_first_issue_delay_ns = 0;
    uint64_t apply_first_down_resp_delay_ns = 0;
    uint64_t apply_first_granule_done_delay_ns = 0;
    uint64_t apply_first_up_resp_delay_ns = 0;
    uint64_t apply_down_resp_total = 0;
    uint64_t apply_completed_granules_total = 0;
    uint64_t apply_emitted_subreads_total = 0;
    uint64_t apply_backlog_granules_residual = 0;
    uint64_t apply_backlog_pending_up_reads_residual = 0;
    uint64_t apply_backlog_inflight_residual = 0;
    uint64_t apply_backlog_granules_peak_after_due = 0;
    uint64_t apply_backlog_pending_up_reads_peak_after_due = 0;
    uint64_t apply_backlog_inflight_peak_after_due = 0;
    uint64_t stall_on_step_gate_cycles = 0;
};

class IGasStageSink {
public:
    virtual ~IGasStageSink() = default;

    virtual void onGasStageEvent(const GasStageEvent& ev) = 0;
    virtual void onGasStatEvent(const GasStatEvent& st) = 0;
};

}} // namespace SST::SnnDL
