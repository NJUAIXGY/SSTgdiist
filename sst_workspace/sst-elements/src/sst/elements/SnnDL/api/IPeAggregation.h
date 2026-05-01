// -*- c++ -*-
//
// IPeAggregation: PE 级汇聚接口（统计/阶段事件）。
//
// 目的：
// - 让 control 层（SnnPESubComponent 等）仅依赖窄接口上报统计与阶段事件；
// - 消除对 components/MultiCorePE.h 的硬依赖，降低耦合与编译依赖面。
//

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include <sst/core/serialization/serialize.h>

namespace SST { namespace SnnDL {


class IPeAggregation {
public:
    virtual ~IPeAggregation() = default;

    // === 阶段事件（用于 PE 级落盘/聚合） ===
    virtual void notifyStageEvent(uint32_t seq,
                                  const std::string& event,
                                  uint64_t ts_ns,
                                  uint64_t spikes_emitted,
                                  int core_id) = 0;

    // === Batch-A: memory access aggregation ===
    virtual void accumulateMemReadLatency(uint64_t latency_cycles, bool is_weight) = 0;
    virtual void accumulateIssueStats(uint64_t req_size_bytes, uint64_t inflight) = 0;

    // === GAS window stats aggregation ===
    virtual void accumulateGasStatsExt(uint64_t unique_bytes, uint64_t unique_reads,
                                       uint64_t rowwin_triggers, uint64_t rowwin_bytes,
                                       uint64_t bursts, uint64_t payload_bytes,
                                       uint64_t window_inflight_peak,
                                       uint64_t window_buffer_max_bytes,
                                       uint64_t frontend_staged_reads,
                                       uint64_t frontend_staged_line_touches,
                                       uint64_t frontend_granules_built,
                                       uint64_t unique_line_count,
                                       uint64_t covered_line_count,
                                       uint64_t overfetch_bytes,
                                       uint64_t apply_bank_credit_effective,
                                       uint64_t cmd_cost_veto,
                                       uint64_t cmd_cost_veto_fine_gap,
                                       uint64_t cmd_cost_veto_row_window,
                                       uint64_t stall_on_step_gate_cycles = 0) = 0;

    virtual void accumulateActivityF(double f) = 0;
    virtual void accumulateApplyScatterStats(uint64_t acc_updates, uint64_t posts_touched,
                                             uint64_t spikes_emitted, uint64_t hwm_bytes,
                                             uint64_t spill_records, uint64_t spilled_bytes) = 0;
    virtual void accumulateSynapseReadStats(uint64_t gcss_lookup_hit_total,
                                            uint64_t gcss_lookup_miss_total,
                                            uint64_t dense_reqs_total,
                                            uint64_t dense_bytes_total,
                                            uint64_t rowptr_reqs_total,
                                            uint64_t rowptr_bytes_total,
                                            uint64_t colidx_reqs_total,
                                            uint64_t colidx_bytes_total,
                                            uint64_t blockdata_reqs_total,
                                            uint64_t blockdata_bytes_total,
                                            uint64_t gcss_reqs_total,
                                            uint64_t gcss_bytes_total,
                                            uint64_t weight_idx_sram_reads_total,
                                            uint64_t weight_idx_sram_writes_total,
                                            uint64_t weight_idx_sram_bytes_read_total,
                                            uint64_t weight_idx_sram_bytes_write_total,
                                            uint64_t weight_idx_sram_bank_conflict_ticks_total,
                                            uint64_t weight_idx_sram_predicted_extra_cycles_total,
                                            uint64_t weight_idx_sram_resident_bytes_peak,
                                            uint64_t weight_idx_sram_bank_peak_accesses_per_tick,
                                            uint64_t weight_idx_sram_energy_read_pj_total,
                                            uint64_t weight_idx_sram_energy_write_pj_total,
                                            uint64_t weight_idx_lookup_total,
                                            uint64_t weight_idx_lookup_idx2_total,
                                            uint64_t weight_l0_sram_reads_total,
                                            uint64_t weight_l0_sram_writes_total,
                                            uint64_t weight_l0_sram_bytes_read_total,
                                            uint64_t weight_l0_sram_bytes_write_total,
                                            uint64_t weight_l0_sram_bank_conflict_ticks_total,
                                            uint64_t weight_l0_sram_predicted_extra_cycles_total,
                                            uint64_t weight_l0_sram_resident_bytes_peak,
                                            uint64_t weight_l0_sram_bank_peak_accesses_per_tick,
                                            uint64_t weight_l0_sram_energy_read_pj_total,
                                            uint64_t weight_l0_sram_energy_write_pj_total,
                                            uint64_t weight_sram_enforced_stall_cycles_total,
                                            uint64_t weight_l0_lookup_total,
                                            uint64_t weight_l0_hit_total,
                                            uint64_t weight_l0_fill_total,
                                            uint64_t weight_l0_evict_total,
                                            uint64_t core_state_sram_reads_total,
                                            uint64_t core_state_sram_writes_total,
                                            uint64_t core_state_sram_bytes_read_total,
                                            uint64_t core_state_sram_bytes_write_total,
                                            uint64_t core_state_sram_bank_conflict_ticks_total,
                                            uint64_t core_state_sram_predicted_extra_cycles_total,
                                            uint64_t core_state_sram_resident_bytes_peak,
                                            uint64_t core_state_sram_bank_peak_accesses_per_tick,
                                            uint64_t core_state_sram_energy_read_pj_total,
                                            uint64_t core_state_sram_energy_write_pj_total,
                                            uint64_t core_state_sram_stall_cycles_total,
                                            uint64_t gas_retire_global_hol_cycles_total,
                                            uint64_t gas_retire_ready_but_blocked_edges_total,
                                            uint64_t gas_retire_per_post_progress_total,
                                            uint64_t gas_retire_samepost_blocked_edges_total,
                                            uint64_t gas_retire_crosspost_blocked_edges_total,
                                            uint64_t gas_retire_policy_loss_cycles_total,
                                            uint64_t gas_retire_policy_loss_edges_total,
                                            uint64_t gas_retire_shadow_per_post_recoverable_cycles_total,
                                            uint64_t gas_retire_shadow_per_post_recoverable_edges_total,
                                            uint64_t gas_retire_shadow_per_post_ready_posts_peak,
                                            uint64_t gas_retire_shadow_per_post_committable_edges_peak) = 0;

    virtual void accumulateUniqueNeuronFired(uint64_t cnt) = 0;
    virtual void accumulateWindowSpikes(uint32_t seq, uint64_t count) = 0;
};

}} // namespace SST::SnnDL
