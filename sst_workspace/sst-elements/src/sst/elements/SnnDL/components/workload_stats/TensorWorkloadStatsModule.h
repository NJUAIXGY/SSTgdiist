// -*- c++ -*-
//
// TensorWorkloadStatsModule: PE-level aggregation for tensor workload counters.
//

#pragma once

#include "KeyedCounterStatsModule.h"

namespace SST { namespace SnnDL {

class TensorWorkloadStatsModule final : public KeyedCounterStatsModule {
public:
    explicit TensorWorkloadStatsModule(bool active_workload) : KeyedCounterStatsModule(active_workload) {
        addCounter("tensor_mem_reads_issued_total");
        addCounter("tensor_mem_writes_issued_total");
        addCounter("tensor_mem_bytes_read_total");
        addCounter("tensor_mem_bytes_write_total");
        addCounter("tensor_mem_read_latency_cycles_total");
        addCounter("tensor_mem_read_latency_cycles_max");
        addCounter("tensor_mem_read_latency_samples_total");
        addCounter("tensor_mem_write_latency_cycles_total");
        addCounter("tensor_mem_write_latency_cycles_max");
        addCounter("tensor_mem_write_latency_samples_total");
        addCounter("tensor_mem_row_hit_total");
        addCounter("tensor_mem_row_miss_total");
        addCounter("tensor_mem_row_conflict_total");
        addCounter("tensor_mem_bank_queue_full_total");
        addCounter("tensor_mem_bank_queue_wait_cycles_total");
        addCounter("tensor_mem_sched_fifo_pick_total");
        addCounter("tensor_mem_sched_frfcfs_pick_total");
        addCounter("tensor_mem_cmd_act_total");
        addCounter("tensor_mem_cmd_pre_total");
        addCounter("tensor_mem_cmd_rdwr_total");
        addCounter("tensor_mem_row_service_cycles_total");
        addCounter("tensor_mem_refresh_block_cycles_total");
        addCounter("tensor_mem_proxy_delay_cycles_total");
        addCounter("tensor_mem_proxy_delay_cycles_max");
        addCounter("tensor_mem_bank_active_cycles_total");
        addCounter("tensor_mem_cmd_queue_slots_total");
        addCounter("tensor_mem_cmd_queue_depth_max");
        addCounter("tensor_mem_cmd_bus_wait_cycles_total");
        addCounter("tensor_mem_cmd_bus_bg_switch_total");
        addCounter("tensor_mem_cmd_issue_total");
        addCounter("tensor_compute_cycles_total");
        addCounter("tensor_compute_math_cycles_total");
        addCounter("tensor_compute_pipeline_cycles_total");
        addCounter("tensor_mxu_wavefront_cycles_total");
        addCounter("tensor_mxu_io_busy_cycles_total");
        addCounter("tensor_compute_precision_profile_id");
        addCounter("tensor_mac_ops_total");
        addCounter("tensor_dma_stall_cycles_total");
        addCounter("tensor_iter_cycles_total");
        addCounter("tensor_stall_dma_budget_cycles_total");
        addCounter("tensor_stall_dma_hbm_channel_budget_cycles_total");
        addCounter("tensor_stall_mem_outstanding_cycles_total");
        addCounter("tensor_stall_wait_read_cycles_total");
        addCounter("tensor_stall_wait_write_cycles_total");
        addCounter("tensor_stall_collective_cycles_total");
        addCounter("tensor_stall_onchip_capacity_cycles_total");
        addCounter("tensor_stall_onchip_port_cycles_total");
        addCounter("tensor_stall_onchip_bank_conflict_cycles_total");
        addCounter("tensor_stall_spill_budget_cycles_total");
        addCounter("tensor_dma_cycles_total");
        addCounter("tensor_dram_bytes_total");
        addCounter("tensor_onchip_bytes_total");
        addCounter("tensor_cfg_ub_bytes");
        addCounter("tensor_cfg_weight_bytes");
        addCounter("tensor_onchip_weight_occupancy_bytes_max");
        addCounter("tensor_onchip_weight_bank_occupancy_bytes_max");
        addCounter("tensor_onchip_a_resident_tiles_max");
        addCounter("tensor_onchip_b_resident_tiles_max");
        addCounter("tensor_tile_count_total");
        addCounter("tensor_spill_bytes_total");
        addCounter("tensor_spill_pkts_total");
        addCounter("tensor_collective_bytes_sent_total");
        addCounter("tensor_collective_bytes_recv_total");
        addCounter("tensor_collective_pkts_sent_total");
        addCounter("tensor_collective_pkts_recv_total");
        addCounter("tensor_collective_cycles_total");
        addCounter("tensor_collective_pending_cycles_total");
        addCounter("tensor_collective_issue_cycles_total");
        addCounter("tensor_collective_chunk_groups_total");
        addCounter("tensor_collective_ring_steps_total");
        addCounter("tensor_collective_2d_row_rs_steps_total");
        addCounter("tensor_collective_2d_col_rs_steps_total");
        addCounter("tensor_collective_2d_col_ag_steps_total");
        addCounter("tensor_collective_2d_row_ag_steps_total");
        addCounter("tensor_collective_2d_row_rs_bytes_sent_total");
        addCounter("tensor_collective_2d_col_rs_bytes_sent_total");
        addCounter("tensor_collective_2d_col_ag_bytes_sent_total");
        addCounter("tensor_collective_2d_row_ag_bytes_sent_total");
        addCounter("tensor_collective_reduce_wait_cycles_total");
        addCounter("tensor_collective_2d_reduce_wait_cycles_total");
        addCounter("tensor_collective_epoch_done_total");
        addCounter("tensor_collective_epoch_latency_cycles_total");
        addCounter("tensor_collective_epoch_latency_cycles_max");
        addCounter("tensor_collective_algo_id");
        addCounter("tensor_collective_credit_stall_cycles_total");
        addCounter("tensor_collective_backpressure_stall_cycles_total");
        addCounter("tensor_collective_inflight_chunks_max");
        addCounter("tensor_collective_credit_return_pkts_sent_total");
        addCounter("tensor_collective_credit_return_pkts_recv_total");
        addCounter("tensor_collective_credit_return_orphan_total");
        addCounter("tensor_collective_credit_return_dup_total");
        addCounter("tensor_collective_credit_return_latency_cycles_total");
        addCounter("tensor_collective_credit_return_latency_cycles_max");
        addCounter("tensor_bank_queue_occupancy_max");
        addCounter("tensor_stall_noc_budget_cycles_total");
        addCounter("tensor_overlap_compute_collective_cycles_total");
        addCounter("tensor_overlap_compute_mem_cycles_total");
        addCounter("tensor_pkt_sent_total");
        addCounter("tensor_pkt_recv_total");
        addCounter("tensor_pkt_bytes_sent_total");
        addCounter("tensor_pkt_bytes_recv_total");
        addCounter("tensor_vector_cycles_total");
        addCounter("tensor_program_any_busy_cycles_total");
        addCounter("tensor_program_dma_busy_cycles_total");
        addCounter("tensor_program_mxu_busy_cycles_total");
        addCounter("tensor_program_vec_busy_cycles_total");
        addCounter("tensor_program_coll_busy_cycles_total");
        addCounter("tensor_program_ops_total");
        addCounter("tensor_program_iters_total");
        addCounter("tensor_program_fence_count_total");
        addCounter("tensor_program_fence_wait_cycles_total");
        addCounter("tensor_program_ub_stall_cycles_total");
        addCounter("tensor_program_mem_stall_cycles_total");
        addCounter("tensor_program_ub_occupancy_bytes_max");
    }

    const char* name() const override { return "tensor"; }
};

}} // namespace SST::SnnDL
