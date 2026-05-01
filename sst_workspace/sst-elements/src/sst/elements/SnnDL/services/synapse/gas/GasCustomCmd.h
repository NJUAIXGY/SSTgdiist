// -*- c++ -*-
// GasCustomCmd.h: Custom control-plane commands for GAS phases

#pragma once

#include <sst/core/interfaces/stdMem.h>
#include <string>

#include "GasOps.h"
#include "IGasStageSink.h"

namespace SST { namespace SnnDL {

// CustomData payload carried inside StandardMem::CustomReq/Resp
struct GasOpData : public SST::Interfaces::StandardMem::CustomData {
    GasOp op = GasOp::BeginGather;
    uint32_t superstep = 0;
    uint32_t slice = 0;
    uint32_t total_slices = 1;
    bool flag = false; // generic flag (e.g., flush)

    GasOpData() = default;
    GasOpData(GasOp _op, uint32_t ss=0, uint32_t sl=0, uint32_t tot=1, bool fl=false)
        : op(_op), superstep(ss), slice(sl), total_slices(tot), flag(fl) {}

    // CustomData API
    SST::Interfaces::StandardMem::CustomData* makeResponse() override {
        // One-way by default
        return new GasOpData(GasOp::EndScatter, superstep, slice, total_slices, flag);
    }
    bool needsResponse() override { return false; }
    SST::Interfaces::StandardMem::Addr getRoutingAddress() override { return 0; }
    uint64_t getSize() override { return 0; }
    std::string getString() override {
        return std::string("GasOp:") + std::to_string((int)op) +
               ",ss=" + std::to_string(superstep) +
               ",sl=" + std::to_string(slice) +
               ",tot=" + std::to_string(total_slices) +
               ",fl=" + (flag?"1":"0");
    }
    void serialize_order(SST::Core::Serialization::serializer& ser) override {
        SST_SER(op);
        SST_SER(superstep);
        SST_SER(slice);
        SST_SER(total_slices);
        SST_SER(flag);
    }
    ImplementSerializable(SST::SnnDL::GasOpData);
};

// Upstream statistic update payload from GatherBufferIF to PE
struct GasStatData : public SST::Interfaces::StandardMem::CustomData {
    uint32_t superstep = 0;
    // Downstream unique reads/bytes (granule returns)
    uint64_t unique_reads = 0;
    uint64_t unique_bytes = 0;
    // Row-window coarse-merge counters per segment (issued at Apply build time)
    uint64_t rowwin_triggers = 0;
    uint64_t rowwin_bytes = 0;
    // Segment/burst counters regardless of row-window (issued at Apply build time)
    uint64_t bursts = 0;            // number of granules (segments) built
    uint64_t payload_bytes = 0;     // sum of sub-read sizes within the segment (useful bytes)
    uint64_t window_inflight_peak = 0;     // per-window inflight peak (two-buffer sum)
    uint64_t window_buffer_max_bytes = 0;  // per-window SRAM occupancy peak
    uint64_t gap_absorbed_bytes = 0;       // fine merge: absorbed gap bytes (window-level or segment-level additive)
    // Front-end line-clustering diagnostics (per build/window summary)
    uint64_t frontend_staged_reads = 0;
    uint64_t frontend_staged_line_touches = 0;
    uint64_t frontend_granules_built = 0;
    // DRAM-aware Apply diagnostics (optional; emitted only when enabled)
    uint64_t unique_line_count = 0;        // approx unique cachelines touched by staged reads (per window)
    uint64_t covered_line_count = 0;       // approx covered cachelines by issued segments (per window)
    uint64_t overfetch_bytes = 0;          // issued_bytes - payload_bytes (per window)
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

    GasStatData() = default;
    GasStatData(uint32_t superstep_,
                uint64_t r, uint64_t b,
                uint64_t rwt=0, uint64_t rwb=0,
                uint64_t bursts_=0, uint64_t payload_=0,
                uint64_t inflight_peak_=0, uint64_t buffer_peak_=0,
                uint64_t gap_abs_=0,
                uint64_t frontend_staged_reads_=0,
                uint64_t frontend_staged_line_touches_=0,
                uint64_t frontend_granules_built_=0,
                uint64_t unique_lines_=0,
                uint64_t covered_lines_=0,
                uint64_t overfetch_bytes_=0,
                uint64_t apply_bank_credit_effective_=0,
                uint64_t cmd_cost_veto_=0,
                uint64_t cmd_cost_veto_fine_gap_=0,
                uint64_t cmd_cost_veto_row_window_=0,
                uint64_t apply_issue_attempt_total_=0,
                uint64_t apply_issue_success_total_=0,
                uint64_t apply_issue_block_no_ready_total_=0,
                uint64_t apply_issue_block_inflight_cap_total_=0,
                uint64_t apply_issue_block_bank_credit_total_=0,
                uint64_t apply_issue_block_downstream_busy_total_=0,
                uint64_t apply_issue_block_retire_guard_total_=0,
                uint64_t apply_ready_queue_peak_=0,
                uint64_t apply_ready_queue_nonempty_cycles_total_=0,
                uint64_t apply_first_issue_delay_ns_=0,
                uint64_t apply_first_down_resp_delay_ns_=0,
                uint64_t apply_first_granule_done_delay_ns_=0,
                uint64_t apply_first_up_resp_delay_ns_=0,
                uint64_t apply_down_resp_total_=0,
                uint64_t apply_completed_granules_total_=0,
                uint64_t apply_emitted_subreads_total_=0,
                uint64_t apply_backlog_granules_residual_=0,
                uint64_t apply_backlog_pending_up_reads_residual_=0,
                uint64_t apply_backlog_inflight_residual_=0,
                uint64_t apply_backlog_granules_peak_after_due_=0,
                uint64_t apply_backlog_pending_up_reads_peak_after_due_=0,
                uint64_t apply_backlog_inflight_peak_after_due_=0,
                uint64_t stall_on_step_gate_cycles_=0)
        : superstep(superstep_),
          unique_reads(r), unique_bytes(b),
          rowwin_triggers(rwt), rowwin_bytes(rwb),
          bursts(bursts_), payload_bytes(payload_),
          window_inflight_peak(inflight_peak_),
          window_buffer_max_bytes(buffer_peak_),
          gap_absorbed_bytes(gap_abs_),
          frontend_staged_reads(frontend_staged_reads_),
          frontend_staged_line_touches(frontend_staged_line_touches_),
          frontend_granules_built(frontend_granules_built_),
          unique_line_count(unique_lines_),
          covered_line_count(covered_lines_),
          overfetch_bytes(overfetch_bytes_),
          apply_bank_credit_effective(apply_bank_credit_effective_),
          cmd_cost_veto(cmd_cost_veto_),
          cmd_cost_veto_fine_gap(cmd_cost_veto_fine_gap_),
          cmd_cost_veto_row_window(cmd_cost_veto_row_window_),
          apply_issue_attempt_total(apply_issue_attempt_total_),
          apply_issue_success_total(apply_issue_success_total_),
          apply_issue_block_no_ready_total(apply_issue_block_no_ready_total_),
          apply_issue_block_inflight_cap_total(apply_issue_block_inflight_cap_total_),
          apply_issue_block_bank_credit_total(apply_issue_block_bank_credit_total_),
          apply_issue_block_downstream_busy_total(apply_issue_block_downstream_busy_total_),
          apply_issue_block_retire_guard_total(apply_issue_block_retire_guard_total_),
          apply_ready_queue_peak(apply_ready_queue_peak_),
          apply_ready_queue_nonempty_cycles_total(apply_ready_queue_nonempty_cycles_total_),
          apply_first_issue_delay_ns(apply_first_issue_delay_ns_),
          apply_first_down_resp_delay_ns(apply_first_down_resp_delay_ns_),
          apply_first_granule_done_delay_ns(apply_first_granule_done_delay_ns_),
          apply_first_up_resp_delay_ns(apply_first_up_resp_delay_ns_),
          apply_down_resp_total(apply_down_resp_total_),
          apply_completed_granules_total(apply_completed_granules_total_),
          apply_emitted_subreads_total(apply_emitted_subreads_total_),
          apply_backlog_granules_residual(apply_backlog_granules_residual_),
          apply_backlog_pending_up_reads_residual(apply_backlog_pending_up_reads_residual_),
          apply_backlog_inflight_residual(apply_backlog_inflight_residual_),
          apply_backlog_granules_peak_after_due(apply_backlog_granules_peak_after_due_),
          apply_backlog_pending_up_reads_peak_after_due(apply_backlog_pending_up_reads_peak_after_due_),
          apply_backlog_inflight_peak_after_due(apply_backlog_inflight_peak_after_due_),
          stall_on_step_gate_cycles(stall_on_step_gate_cycles_) {}

    // CustomData API
    SST::Interfaces::StandardMem::CustomData* makeResponse() override { return new GasStatData(0, 0, 0); }
    bool needsResponse() override { return false; }
    SST::Interfaces::StandardMem::Addr getRoutingAddress() override { return 0; }
    uint64_t getSize() override { return sizeof(GasStatData); }
    std::string getString() override {
        return std::string("GasStatData:step=") + std::to_string(superstep) +
               ",reads=" + std::to_string(unique_reads) +
               ",bytes=" + std::to_string(unique_bytes) +
               ",rowwin_trig=" + std::to_string(rowwin_triggers) +
               ",rowwin_bytes=" + std::to_string(rowwin_bytes) +
               ",bursts=" + std::to_string(bursts) +
               ",payload=" + std::to_string(payload_bytes) +
               ",inflight_peak=" + std::to_string(window_inflight_peak) +
               ",buffer_peak=" + std::to_string(window_buffer_max_bytes) +
               ",gap_abs=" + std::to_string(gap_absorbed_bytes) +
               ",fe_reads=" + std::to_string(frontend_staged_reads) +
               ",fe_line_touches=" + std::to_string(frontend_staged_line_touches) +
               ",fe_granules=" + std::to_string(frontend_granules_built) +
               ",uniq_lines=" + std::to_string(unique_line_count) +
               ",cov_lines=" + std::to_string(covered_line_count) +
               ",overfetch=" + std::to_string(overfetch_bytes) +
               ",credit=" + std::to_string(apply_bank_credit_effective) +
               ",cmd_veto=" + std::to_string(cmd_cost_veto) +
               ",cmd_veto_fine=" + std::to_string(cmd_cost_veto_fine_gap) +
               ",cmd_veto_rowwin=" + std::to_string(cmd_cost_veto_row_window) +
               ",apply_issue_attempt=" + std::to_string(apply_issue_attempt_total) +
               ",apply_issue_success=" + std::to_string(apply_issue_success_total) +
               ",apply_issue_block_no_ready=" + std::to_string(apply_issue_block_no_ready_total) +
               ",apply_issue_block_inflight=" + std::to_string(apply_issue_block_inflight_cap_total) +
               ",apply_issue_block_retire_guard=" + std::to_string(apply_issue_block_retire_guard_total) +
               ",apply_ready_q_peak=" + std::to_string(apply_ready_queue_peak) +
               ",apply_ready_q_nonempty_cycles=" + std::to_string(apply_ready_queue_nonempty_cycles_total) +
               ",apply_first_issue_delay_ns=" + std::to_string(apply_first_issue_delay_ns) +
               ",apply_first_down_resp_delay_ns=" + std::to_string(apply_first_down_resp_delay_ns) +
               ",apply_first_granule_done_delay_ns=" + std::to_string(apply_first_granule_done_delay_ns) +
               ",apply_first_up_resp_delay_ns=" + std::to_string(apply_first_up_resp_delay_ns) +
               ",apply_down_resp_total=" + std::to_string(apply_down_resp_total) +
               ",apply_completed_granules_total=" + std::to_string(apply_completed_granules_total) +
               ",apply_emitted_subreads_total=" + std::to_string(apply_emitted_subreads_total) +
               ",apply_backlog_granules_residual=" + std::to_string(apply_backlog_granules_residual) +
               ",apply_backlog_pending_up_reads_residual=" + std::to_string(apply_backlog_pending_up_reads_residual) +
               ",apply_backlog_inflight_residual=" + std::to_string(apply_backlog_inflight_residual) +
               ",apply_backlog_granules_peak_after_due=" + std::to_string(apply_backlog_granules_peak_after_due) +
               ",apply_backlog_pending_up_reads_peak_after_due=" + std::to_string(apply_backlog_pending_up_reads_peak_after_due) +
               ",apply_backlog_inflight_peak_after_due=" + std::to_string(apply_backlog_inflight_peak_after_due) +
               ",stall_on_step_gate_cycles=" + std::to_string(stall_on_step_gate_cycles);
    }
    void serialize_order(SST::Core::Serialization::serializer& ser) override {
        SST_SER(superstep);
        SST_SER(unique_reads);
        SST_SER(unique_bytes);
        SST_SER(rowwin_triggers);
        SST_SER(rowwin_bytes);
        SST_SER(bursts);
        SST_SER(payload_bytes);
        SST_SER(window_inflight_peak);
        SST_SER(window_buffer_max_bytes);
        SST_SER(gap_absorbed_bytes);
        SST_SER(frontend_staged_reads);
        SST_SER(frontend_staged_line_touches);
        SST_SER(frontend_granules_built);
        SST_SER(unique_line_count);
        SST_SER(covered_line_count);
        SST_SER(overfetch_bytes);
        SST_SER(apply_bank_credit_effective);
        SST_SER(cmd_cost_veto);
        SST_SER(cmd_cost_veto_fine_gap);
        SST_SER(cmd_cost_veto_row_window);
        SST_SER(apply_issue_attempt_total);
        SST_SER(apply_issue_success_total);
        SST_SER(apply_issue_block_no_ready_total);
        SST_SER(apply_issue_block_inflight_cap_total);
        SST_SER(apply_issue_block_bank_credit_total);
        SST_SER(apply_issue_block_downstream_busy_total);
        SST_SER(apply_issue_block_retire_guard_total);
        SST_SER(apply_ready_queue_peak);
        SST_SER(apply_ready_queue_nonempty_cycles_total);
        SST_SER(apply_first_issue_delay_ns);
        SST_SER(apply_first_down_resp_delay_ns);
        SST_SER(apply_first_granule_done_delay_ns);
        SST_SER(apply_first_up_resp_delay_ns);
        SST_SER(apply_down_resp_total);
        SST_SER(apply_completed_granules_total);
        SST_SER(apply_emitted_subreads_total);
        SST_SER(apply_backlog_granules_residual);
        SST_SER(apply_backlog_pending_up_reads_residual);
        SST_SER(apply_backlog_inflight_residual);
        SST_SER(apply_backlog_granules_peak_after_due);
        SST_SER(apply_backlog_pending_up_reads_peak_after_due);
        SST_SER(apply_backlog_inflight_peak_after_due);
        SST_SER(stall_on_step_gate_cycles);
    }
    ImplementSerializable(SST::SnnDL::GasStatData);
};

inline GasStatEvent toGasStatEvent(const GasStatData& st) {
    GasStatEvent sev{};
    sev.superstep = st.superstep;
    sev.unique_reads = st.unique_reads;
    sev.unique_bytes = st.unique_bytes;
    sev.rowwin_triggers = st.rowwin_triggers;
    sev.rowwin_bytes = st.rowwin_bytes;
    sev.bursts = st.bursts;
    sev.payload_bytes = st.payload_bytes;
    sev.window_inflight_peak = st.window_inflight_peak;
    sev.window_buffer_max_bytes = st.window_buffer_max_bytes;
    sev.gap_absorbed_bytes = st.gap_absorbed_bytes;
    sev.frontend_staged_reads = st.frontend_staged_reads;
    sev.frontend_staged_line_touches = st.frontend_staged_line_touches;
    sev.frontend_granules_built = st.frontend_granules_built;
    sev.unique_line_count = st.unique_line_count;
    sev.covered_line_count = st.covered_line_count;
    sev.overfetch_bytes = st.overfetch_bytes;
    sev.apply_bank_credit_effective = st.apply_bank_credit_effective;
    sev.cmd_cost_veto = st.cmd_cost_veto;
    sev.cmd_cost_veto_fine_gap = st.cmd_cost_veto_fine_gap;
    sev.cmd_cost_veto_row_window = st.cmd_cost_veto_row_window;
    sev.apply_issue_attempt_total = st.apply_issue_attempt_total;
    sev.apply_issue_success_total = st.apply_issue_success_total;
    sev.apply_issue_block_no_ready_total = st.apply_issue_block_no_ready_total;
    sev.apply_issue_block_inflight_cap_total = st.apply_issue_block_inflight_cap_total;
    sev.apply_issue_block_bank_credit_total = st.apply_issue_block_bank_credit_total;
    sev.apply_issue_block_downstream_busy_total = st.apply_issue_block_downstream_busy_total;
    sev.apply_issue_block_retire_guard_total = st.apply_issue_block_retire_guard_total;
    sev.apply_ready_queue_peak = st.apply_ready_queue_peak;
    sev.apply_ready_queue_nonempty_cycles_total = st.apply_ready_queue_nonempty_cycles_total;
    sev.apply_first_issue_delay_ns = st.apply_first_issue_delay_ns;
    sev.apply_first_down_resp_delay_ns = st.apply_first_down_resp_delay_ns;
    sev.apply_first_granule_done_delay_ns = st.apply_first_granule_done_delay_ns;
    sev.apply_first_up_resp_delay_ns = st.apply_first_up_resp_delay_ns;
    sev.apply_down_resp_total = st.apply_down_resp_total;
    sev.apply_completed_granules_total = st.apply_completed_granules_total;
    sev.apply_emitted_subreads_total = st.apply_emitted_subreads_total;
    sev.apply_backlog_granules_residual = st.apply_backlog_granules_residual;
    sev.apply_backlog_pending_up_reads_residual = st.apply_backlog_pending_up_reads_residual;
    sev.apply_backlog_inflight_residual = st.apply_backlog_inflight_residual;
    sev.apply_backlog_granules_peak_after_due = st.apply_backlog_granules_peak_after_due;
    sev.apply_backlog_pending_up_reads_peak_after_due = st.apply_backlog_pending_up_reads_peak_after_due;
    sev.apply_backlog_inflight_peak_after_due = st.apply_backlog_inflight_peak_after_due;
    sev.stall_on_step_gate_cycles = st.stall_on_step_gate_cycles;
    return sev;
}

}} // namespace
