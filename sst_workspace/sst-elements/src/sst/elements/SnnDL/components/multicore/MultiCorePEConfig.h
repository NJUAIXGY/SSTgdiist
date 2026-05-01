// -*- c++ -*-
//
// MultiCorePEConfig:
// - 将 MultiCorePE 构造期的大量 params.find(...) 收敛到一处，降低主构造函数噪音。
// - 仅做参数解析/默认值/轻量规整，不引入新的运行期组件或装配点。
//

#pragma once

#include <array>
#include <cstdint>
#include <string>

#include "WorkloadConfig.h"

namespace SST {
class Params;
}

namespace SST { namespace SnnDL {

struct MultiCorePEConfig {
    // Common
    int verbose_level = 0;
    std::string clock_freq = "1GHz";

    // Layout
    int num_cores = 4;
    int neurons_per_core = 64;
    uint32_t neurons_per_pe = 0;
    int node_id = 0;
    int total_nodes = 1;
    uint64_t global_neuron_base = 0;
    uint64_t base_addr = 0;
    uint64_t sim_stop_ns = 0;

    // Native multicast lab
    uint32_t noc_lat_hist_max = 131072;

    // Diagnostics/sentinel
    bool sentinel_enabled = false;
    uint64_t progress_log_interval_ns = 0;
    int progress_log_node = -1;
    long step_diag_cap = 0;
    int step_diag_enable = 0;

    // Workload selector (for disabling StepActivation under non-SNN workloads)
    std::string workload_impl;  // normalized lowercase; empty means "snn"
    WorkloadKind workload_kind = WorkloadKind::Snn;
    // Optional workload stats modules (comma-separated). Empty -> auto from workload_impl.
    std::string workload_stats_modules;
    // Execution mode hint (experiment observability only)
    // - gas: default SNN GAS/window pipeline
    // - naive_raw: immediate per-spike reads (no GAS/window); still may use global step sync controller
    std::string exec_mode;  // normalized lowercase; empty means "gas"

    // PE-shared DMA (Phase 1: SNN workload runtime reads only)
    bool dma_enable = false;
    uint64_t dma_bytes_per_cycle = 0;
    uint32_t dma_read_engines = 0;
    uint32_t dma_max_inflight = 0;
    uint32_t dma_queue_depth = 0;
    std::string dma_overflow_policy = "block";
    uint64_t dma_burst_bytes = 0;
    uint32_t dma_setup_cycles = 0;
    uint32_t dma_channels = 1;
    uint64_t dma_channel_bytes_per_cycle = 0;
    uint64_t dma_channel_interleave_bytes = 256;
    std::array<std::array<uint16_t, 4>, 4> dma_stage_budget_permille{};

    // Local storage hierarchy (Phase A: object registry / stats / compatibility aliases)
    bool local_storage_enable = false;
    bool pe_internal_cpe_enable = false;
    bool pe_internal_pod_enable = false;
    uint32_t pe_internal_pod_count = 0;
    uint32_t pe_internal_pod_size = 0;
    bool pe_internal_pod_metadata_enable = false;
    uint64_t pe_internal_pod_metadata_capacity_bytes = 0;
    uint32_t pe_internal_pod_metadata_banks = 1;
    bool pe_internal_pod_owner_enable = false;
    uint32_t pe_internal_pod_owner_entries = 0;
    uint32_t pe_internal_pod_owner_entry_bytes = 16;
    bool pe_internal_pod_join_enable = false;
    uint32_t pe_internal_pod_join_entries = 0;
    uint32_t pe_internal_pod_join_entry_bytes = 16;
    bool pe_internal_pod_ready_enable = false;
    uint32_t pe_internal_pod_ready_entries = 0;
    bool pulse_enable = false;
    bool pulse_osa_enable = false;
    bool pulse_osa_shared_weight_owner_enable = false;
    bool pulse_osa_shared_weight_owner_actual_enable = false;
    bool pulse_osa_metadata_txn_enable = false;
    bool pulse_osa_metadata_ready_lease_enable = false;
    uint32_t pulse_osa_metadata_ready_lease_ttl = 0;
    std::string pulse_osa_metadata_object_mask = "rowdescriptor";
    bool pulse_observe_only = true;
    bool pulse_ingress_enable = true;
    bool pulse_agenda_observe_only = true;
    bool pulse_harbor_enable = false;
    bool pulse_descriptor_enable = false;
    bool pulse_descriptor_actual_enable = false;
    bool experimental_rowdescriptor_ready_join_dedup_enable = false;
    bool pulse_domain_retire_enable = false;
    bool pulse_domain_retire_observe_only = true;
    std::string pulse_domain_retire_mode = "per_post";
    uint32_t pulse_domain_retire_release_budget = 0;
    uint32_t pulse_ingress_entries = 0;
    uint32_t pulse_core_queue_entries = 0;
    uint32_t pulse_descriptor_packet_min = 2;
    uint32_t pulse_bypass_high_watermark_pct = 100;
    std::string pulse_bypass_mode = "disabled";

    bool ls_state_enable = false;
    uint64_t ls_state_capacity_bytes = 0;
    uint32_t ls_state_banks = 16;
    uint32_t ls_state_read_ports = 1;
    uint32_t ls_state_write_ports = 1;
    uint32_t ls_state_update_ports = 1;
    uint32_t ls_state_queue_depth = 0;

    bool ls_weight_idx_enable = false;
    uint64_t ls_weight_idx_capacity_bytes = 0;
    uint32_t ls_weight_idx_banks = 16;
    uint32_t ls_weight_idx_read_ports = 1;
    uint32_t ls_weight_idx_write_ports = 1;
    uint32_t ls_weight_idx_queue_depth = 0;

    bool ls_weight_value_enable = false;
    uint64_t ls_weight_value_capacity_bytes = 0;
    uint32_t ls_weight_value_banks = 8;
    uint32_t ls_weight_value_read_ports = 1;
    uint32_t ls_weight_value_write_ports = 1;
    uint32_t ls_weight_value_queue_depth = 0;

    bool ls_activation_ingress_enable = false;
    uint32_t ls_activation_ingress_entries = 0;
    bool ls_activation_core_enable = false;
    uint32_t ls_activation_core_entries = 0;

    bool ls_acc_enable = false;
    uint64_t ls_acc_capacity_bytes = 0;
    uint32_t ls_acc_banks = 1;
    uint32_t ls_acc_read_ports = 1;
    uint32_t ls_acc_write_ports = 1;
    uint32_t ls_acc_update_ports = 1;
    uint32_t ls_acc_queue_depth = 0;

    bool ls_rf_enable = false;
    uint32_t ls_rf_entries = 0;
    uint32_t ls_rf_entry_bytes = 4;
    uint32_t ls_rf_read_ports = 1;
    uint32_t ls_rf_write_ports = 1;

    // Files / toggles
    std::string weights_file;
    bool enable_numa = true;

    // Neuron params
    float v_thresh = 1.0f;
    float v_reset = 0.0f;
    float v_rest = 0.0f;
    float tau_mem = 20.0f;
    int t_ref = 2;

    // Test traffic
    bool enable_test_traffic = false;
    std::string test_traffic_packet_kind = "spike";
    int test_target_node = 0;
    int test_period = 100;
    int test_spikes_per_burst = 4;
    float test_weight = 0.2f;
    int test_max_spikes = 10;

    // Internal ring
    bool use_optimized_ring = true;

    // Output / misc
    bool print_node_summary = true;
    bool primary_keepalive = false;
    bool manual_core_drive_enable = false;
    uint64_t manual_gas_gather_cycles = 200;

    // Weight diagnostics
    bool verify_weights = false;
    uint32_t weight_verify_samples = 16;
    float expected_weight_value = 0.5f;
    bool verify_log_each_sample = false;

    bool use_event_weight_fallback = false;
    bool enable_memory_weights = true;
    bool write_weights_on_init = true;

    // Window stats (PE-level)
    bool window_stats_enable = false;
    uint64_t window_us = 20;
    std::string window_csv;
    std::string window_metrics_csv;
    bool diag_fire_log = false;

    // Global Step sync
    bool global_step_sync_enable = false;
    std::string global_step_done_policy = "endscatter";
    uint64_t global_step_quiescent_min_cycles = 1;
    uint64_t global_step_drain_min_cycles = 200;
    uint64_t global_step_fixed_cycles = 100000;
    // Step-limited fairness: delay PE_READY until WeightLoader publishes done (prevents naive_* from exploding pending queues).
    std::string loader_done_key;
    uint64_t global_step_ready_delay_cycles = 0; // wait N cycles after loader_done before PE_READY (lets rowptr prefetch settle)

    // StepActivationSubsystem params
    bool step_activation_enable = false;
    double step_activation_fraction = 0.0;
    uint32_t step_activation_fanout = 0;
    uint64_t step_activation_seed = 0xdecafbadULL;
    uint64_t step_activation_period_cycles = 0;
    int step_activation_trigger_core = 0;
    bool step_reset_mem_each_step = false;
    double step_activation_event_weight = 0.0;
    // StepActivation pre selection pattern (bernoulli/clustered)
    std::string step_activation_pre_pattern; // normalized lowercase; empty => bernoulli
    uint32_t step_activation_pre_cluster_len = 0; // clustered: contiguous pre length (neurons); 0 => auto (64)
    bool step_activation_use_bcsr_routes = false;
    std::string step_activation_bcsr_template;
    uint32_t step_activation_bcsr_rows_per_core = 0; // 0 => default to neurons_per_core
    uint32_t step_activation_bcsr_br = 16;
    uint32_t step_activation_bcsr_bc = 16;
    uint32_t step_activation_bcsr_idx_bytes = 2;
    uint32_t step_activation_bcsr_val_bytes = 4;
    uint64_t step_activation_bcsr_rowptr_offset = 0;
    uint64_t step_activation_bcsr_colidx_offset = 0;
    uint64_t step_activation_bcsr_blockdata_offset = 0;
    uint64_t step_activation_bcsr_blockids_offset = 0;
    double step_activation_bcsr_weight_epsilon = 0.0;
    bool step_activation_log_enable = false;
    bool step_activation_build_local_only = true;
    uint64_t step_activation_bcsr_align = 64;

    // Output paths (used for per-node dir derivation)
    std::string stage_events_csv_path;
    std::string stats_csv_path;
};

MultiCorePEConfig parseMultiCorePEConfig(const SST::Params& params);

}} // namespace SST::SnnDL
