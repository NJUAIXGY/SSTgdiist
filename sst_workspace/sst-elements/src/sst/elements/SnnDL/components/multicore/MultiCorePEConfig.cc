// -*- c++ -*-
//
// MultiCorePEConfig.cc
//

#include "multicore/MultiCorePEConfig.h"

#include <algorithm>

#include <sst/core/params.h>

#include "WorkloadConfig.h"
#include "services/memory/PeDmaScheduler.h"

namespace SST { namespace SnnDL {

MultiCorePEConfig parseMultiCorePEConfig(const SST::Params& params) {
    MultiCorePEConfig c{};

    c.verbose_level = params.find<int>("verbose", 0);
    c.clock_freq = params.find<std::string>("clock", "1GHz");

    c.num_cores = params.find<int>("num_cores", 4);
    c.neurons_per_core = params.find<int>("neurons_per_core", 64);
    c.neurons_per_pe = params.find<uint32_t>("neurons_per_pe", 0);
    c.node_id = params.find<int>("node_id", 0);
    c.total_nodes = params.find<int>("total_nodes", 1);
    c.global_neuron_base = params.find<uint64_t>("global_neuron_base", 0);
    c.base_addr = params.find<uint64_t>("base_addr", 0);
    c.sim_stop_ns = params.find<uint64_t>("sim_stop_ns", 0);

    c.noc_lat_hist_max = params.find<uint32_t>("noc_lat_hist_max", 131072);
    if (c.noc_lat_hist_max < 64) c.noc_lat_hist_max = 64;
    if (c.noc_lat_hist_max > 2000000u) c.noc_lat_hist_max = 2000000u;

    // P2 Step3: no runtime getenv fallbacks here; only Params (+ optional cached env for workload selection).
    c.sentinel_enabled = params.find<int>("sentinel_enable", 0) != 0;
    c.progress_log_interval_ns = params.find<uint64_t>("progress_log_interval_ns", 0);
    c.progress_log_node = params.find<int>("progress_log_node", -1);
    c.step_diag_cap = params.find<long>("step_diag_cap", 0);
    c.step_diag_enable = params.find<int>("step_diag_enable", 0);

    c.weights_file = params.find<std::string>("weights_file", "");
    c.enable_numa = params.find<bool>("enable_numa", true);

    // Workload selector (used to disable step activation for non-SNN workloads).
    c.workload_impl = workloadImplFromParamsOrEnv(params, "snn");
    c.workload_kind = workloadKindFromString(c.workload_impl);
    c.workload_stats_modules = toLowerCopy(params.find<std::string>("workload_stats_modules", ""));

    // Exec mode hint (experiment observability; does not change behavior).
    c.exec_mode = execModeFromParams(params, "gas");

    {
        PeDmaScheduler::Config dma_defaults{};
        c.dma_enable = params.find<bool>("dma_enable", false);
        c.dma_bytes_per_cycle = params.find<uint64_t>("dma_bytes_per_cycle", 0);
        c.dma_read_engines = params.find<uint32_t>("dma_read_engines", 0);
        c.dma_max_inflight = params.find<uint32_t>("dma_max_inflight", 0);
        c.dma_queue_depth = params.find<uint32_t>("dma_queue_depth", 0);
        c.dma_overflow_policy = toLowerCopy(params.find<std::string>("dma_overflow_policy", "block"));
        c.dma_burst_bytes = params.find<uint64_t>("dma_burst_bytes", 0);
        c.dma_setup_cycles = params.find<uint32_t>("dma_setup_cycles", 0);
        c.dma_channels = params.find<uint32_t>("dma_channels", 1);
        c.dma_channel_bytes_per_cycle = params.find<uint64_t>("dma_channel_bytes_per_cycle", 0);
        c.dma_channel_interleave_bytes = params.find<uint64_t>("dma_channel_interleave_bytes", 256);
        c.dma_stage_budget_permille = dma_defaults.stage_budget_permille;

        for (size_t stage = 0; stage < c.dma_stage_budget_permille.size(); ++stage) {
            const char* stage_name = "gather";
            switch (stage) {
                case 0: stage_name = "gather"; break;
                case 1: stage_name = "apply"; break;
                case 2: stage_name = "scatter"; break;
                default: stage_name = "idle"; break;
            }
            for (size_t prio = 0; prio < c.dma_stage_budget_permille[stage].size(); ++prio) {
                const std::string key =
                    "dma_stage_budget_scale_" + std::string(stage_name) + "_p" + std::to_string(prio);
                const int curr = static_cast<int>(c.dma_stage_budget_permille[stage][prio]);
                int v = params.find<int>(key, curr);
                if (v < 0) v = 0;
                if (v > 1000) v = 1000;
                c.dma_stage_budget_permille[stage][prio] = static_cast<uint16_t>(v);
            }
        }
    }

    c.local_storage_enable = params.find<bool>("local_storage_enable", false);
    c.pe_internal_cpe_enable = params.find<bool>("pe_internal_cpe_enable", false);
    c.pe_internal_pod_enable = params.find<bool>("pe_internal_pod_enable", false);
    c.pe_internal_pod_count = params.find<uint32_t>("pe_internal_pod_count", 0);
    c.pe_internal_pod_size = params.find<uint32_t>("pe_internal_pod_size", 0);
    c.pe_internal_pod_metadata_capacity_bytes =
        params.find<uint64_t>("pe_internal_pod_metadata_capacity_bytes", 0);
    c.pe_internal_pod_metadata_banks =
        params.find<uint32_t>("pe_internal_pod_metadata_banks", 1);
    {
        const int explicit_enable = params.find<int>("pe_internal_pod_metadata_enable", -1);
        if (explicit_enable >= 0) {
            c.pe_internal_pod_metadata_enable = explicit_enable != 0;
        } else {
            c.pe_internal_pod_metadata_enable = c.pe_internal_pod_metadata_capacity_bytes > 0;
        }
    }
    c.pe_internal_pod_owner_entries =
        params.find<uint32_t>("pe_internal_pod_owner_entries", 0);
    c.pe_internal_pod_owner_entry_bytes =
        params.find<uint32_t>("pe_internal_pod_owner_entry_bytes", 16);
    {
        const int explicit_enable = params.find<int>("pe_internal_pod_owner_enable", -1);
        if (explicit_enable >= 0) {
            c.pe_internal_pod_owner_enable = explicit_enable != 0;
        } else {
            c.pe_internal_pod_owner_enable = c.pe_internal_pod_owner_entries > 0;
        }
    }
    c.pe_internal_pod_join_entries =
        params.find<uint32_t>("pe_internal_pod_join_entries", 0);
    c.pe_internal_pod_join_entry_bytes =
        params.find<uint32_t>("pe_internal_pod_join_entry_bytes", 16);
    {
        const int explicit_enable = params.find<int>("pe_internal_pod_join_enable", -1);
        if (explicit_enable >= 0) {
            c.pe_internal_pod_join_enable = explicit_enable != 0;
        } else {
            c.pe_internal_pod_join_enable = c.pe_internal_pod_join_entries > 0;
        }
    }
    c.pe_internal_pod_ready_entries =
        params.find<uint32_t>("pe_internal_pod_ready_entries", 0);
    {
        const int explicit_enable = params.find<int>("pe_internal_pod_ready_enable", -1);
        if (explicit_enable >= 0) {
            c.pe_internal_pod_ready_enable = explicit_enable != 0;
        } else {
            c.pe_internal_pod_ready_enable = c.pe_internal_pod_ready_entries > 0;
        }
    }
    c.pulse_enable = params.find<bool>("pulse_enable", false);
    c.pulse_osa_enable = params.find<bool>("pulse_osa_enable", false);
    c.pulse_osa_shared_weight_owner_enable =
        params.find<bool>("pulse_osa_shared_weight_owner_enable", false);
    c.pulse_osa_shared_weight_owner_actual_enable =
        params.find<bool>("pulse_osa_shared_weight_owner_actual_enable", false);
    c.pulse_osa_metadata_txn_enable =
        params.find<bool>("pulse_osa_metadata_txn_enable", false);
    c.pulse_osa_metadata_ready_lease_enable =
        params.find<bool>("pulse_osa_metadata_ready_lease_enable", false);
    c.pulse_osa_metadata_ready_lease_ttl =
        params.find<uint32_t>("pulse_osa_metadata_ready_lease_ttl", 0);
    c.pulse_osa_metadata_object_mask =
        toLowerCopy(params.find<std::string>(
            "pulse_osa_metadata_object_mask", "rowdescriptor"));
    c.pulse_observe_only = params.find<int>("pulse_observe_only", 1) != 0;
    c.pulse_ingress_enable = params.find<int>("pulse_ingress_enable", 1) != 0;
    c.pulse_agenda_observe_only = params.find<int>("pulse_agenda_observe_only", 1) != 0;
    c.pulse_harbor_enable = params.find<int>("pulse_harbor_enable", 0) != 0;
    c.pulse_descriptor_enable = params.find<int>("pulse_descriptor_enable", 0) != 0;
    c.pulse_descriptor_actual_enable = params.find<int>("pulse_descriptor_actual_enable", 0) != 0;
    c.experimental_rowdescriptor_ready_join_dedup_enable =
        params.find<int>("experimental_rowdescriptor_ready_join_dedup_enable", 0) != 0;
    c.pulse_domain_retire_enable = params.find<int>("pulse_domain_retire_enable", 0) != 0;
    c.pulse_domain_retire_observe_only = params.find<int>("pulse_domain_retire_observe_only", 1) != 0;
    c.pulse_domain_retire_mode =
        toLowerCopy(params.find<std::string>("pulse_domain_retire_mode", "per_post"));
    if (c.pulse_domain_retire_mode != "descriptor_domain") c.pulse_domain_retire_mode = "per_post";
    c.pulse_domain_retire_release_budget =
        params.find<uint32_t>("pulse_domain_retire_release_budget", 0);
    c.pulse_ingress_entries = params.find<uint32_t>("pulse_ingress_entries", 0);
    c.pulse_core_queue_entries = params.find<uint32_t>("pulse_core_queue_entries", 0);
    c.pulse_descriptor_packet_min = params.find<uint32_t>("pulse_descriptor_packet_min", 2);
    if (c.pulse_descriptor_packet_min == 0) c.pulse_descriptor_packet_min = 2;
    c.pulse_bypass_high_watermark_pct =
        params.find<uint32_t>("pulse_bypass_high_watermark_pct", 100);
    if (c.pulse_bypass_high_watermark_pct == 0) c.pulse_bypass_high_watermark_pct = 100;
    if (c.pulse_bypass_high_watermark_pct > 100) c.pulse_bypass_high_watermark_pct = 100;
    c.pulse_bypass_mode = toLowerCopy(params.find<std::string>("pulse_bypass_mode", "disabled"));
    if (c.pulse_bypass_mode != "high_watermark") c.pulse_bypass_mode = "disabled";

    c.ls_state_capacity_bytes =
        params.find<uint64_t>("ls_state_capacity_bytes",
                              params.find<uint64_t>("state_sram_capacity_bytes", 0));
    c.ls_state_banks =
        params.find<uint32_t>("ls_state_banks",
                              params.find<uint32_t>("state_sram_banks", 16));
    c.ls_state_read_ports =
        params.find<uint32_t>("ls_state_read_ports",
                              params.find<uint32_t>("state_sram_ports_per_bank", 1));
    c.ls_state_write_ports =
        params.find<uint32_t>("ls_state_write_ports",
                              params.find<uint32_t>("state_sram_ports_per_bank", 1));
    c.ls_state_update_ports =
        params.find<uint32_t>("ls_state_update_ports", c.ls_state_write_ports);
    c.ls_state_queue_depth = params.find<uint32_t>("ls_state_queue_depth", 0);
    {
        const int explicit_enable = params.find<int>("ls_state_enable", -1);
        if (explicit_enable >= 0) {
            c.ls_state_enable = explicit_enable != 0;
        } else {
            c.ls_state_enable =
                params.find<int>("state_sram_enable", 0) != 0 || c.ls_state_capacity_bytes > 0;
        }
    }

    const bool legacy_weight_master = params.find<int>("weight_sram_model_enable", 0) != 0;
    c.ls_weight_idx_capacity_bytes =
        params.find<uint64_t>("ls_weight_idx_capacity_bytes",
                              params.find<uint64_t>("weight_idx_sram_capacity_bytes", 0));
    c.ls_weight_idx_banks =
        params.find<uint32_t>("ls_weight_idx_banks",
                              params.find<uint32_t>("weight_idx_sram_banks", 16));
    c.ls_weight_idx_read_ports =
        params.find<uint32_t>("ls_weight_idx_read_ports",
                              params.find<uint32_t>("weight_sram_ports_per_bank", 1));
    c.ls_weight_idx_write_ports =
        params.find<uint32_t>("ls_weight_idx_write_ports",
                              params.find<uint32_t>("weight_sram_ports_per_bank", 1));
    c.ls_weight_idx_queue_depth = params.find<uint32_t>("ls_weight_idx_queue_depth", 0);
    {
        const int explicit_enable = params.find<int>("ls_weight_idx_enable", -1);
        if (explicit_enable >= 0) {
            c.ls_weight_idx_enable = explicit_enable != 0;
        } else {
            c.ls_weight_idx_enable =
                (legacy_weight_master && params.find<int>("weight_idx_sram_enable", 0) != 0) ||
                c.ls_weight_idx_capacity_bytes > 0;
        }
    }

    c.ls_weight_value_capacity_bytes =
        params.find<uint64_t>("ls_weight_value_capacity_bytes",
                              params.find<uint64_t>("weight_l0_sram_capacity_bytes", 0));
    c.ls_weight_value_banks =
        params.find<uint32_t>("ls_weight_value_banks",
                              params.find<uint32_t>("weight_l0_sram_banks", 8));
    c.ls_weight_value_read_ports =
        params.find<uint32_t>("ls_weight_value_read_ports",
                              params.find<uint32_t>("weight_sram_ports_per_bank", 1));
    c.ls_weight_value_write_ports =
        params.find<uint32_t>("ls_weight_value_write_ports",
                              params.find<uint32_t>("weight_sram_ports_per_bank", 1));
    c.ls_weight_value_queue_depth = params.find<uint32_t>("ls_weight_value_queue_depth", 0);
    {
        const int explicit_enable = params.find<int>("ls_weight_value_enable", -1);
        if (explicit_enable >= 0) {
            c.ls_weight_value_enable = explicit_enable != 0;
        } else {
            c.ls_weight_value_enable =
                (legacy_weight_master && params.find<int>("weight_l0_sram_enable", 0) != 0) ||
                c.ls_weight_value_capacity_bytes > 0;
        }
    }

    c.ls_activation_ingress_entries = params.find<uint32_t>("ls_activation_ingress_entries", 0);
    {
        const int explicit_enable = params.find<int>("ls_activation_ingress_enable", -1);
        if (explicit_enable >= 0) {
            c.ls_activation_ingress_enable = explicit_enable != 0;
        } else {
            c.ls_activation_ingress_enable = c.ls_activation_ingress_entries > 0;
        }
    }
    c.ls_activation_core_entries = params.find<uint32_t>("ls_activation_core_entries", 0);
    {
        const int explicit_enable = params.find<int>("ls_activation_core_enable", -1);
        if (explicit_enable >= 0) {
            c.ls_activation_core_enable = explicit_enable != 0;
        } else {
            c.ls_activation_core_enable = c.ls_activation_core_entries > 0;
        }
    }

    c.ls_acc_capacity_bytes =
        params.find<uint64_t>("ls_acc_capacity_bytes",
                              params.find<uint64_t>("acc_high_watermark_bytes", 0));
    c.ls_acc_banks = params.find<uint32_t>("ls_acc_banks", 1);
    c.ls_acc_read_ports = params.find<uint32_t>("ls_acc_read_ports", 1);
    c.ls_acc_write_ports = params.find<uint32_t>("ls_acc_write_ports", 1);
    c.ls_acc_update_ports = params.find<uint32_t>("ls_acc_update_ports", 1);
    c.ls_acc_queue_depth = params.find<uint32_t>("ls_acc_queue_depth", 0);
    {
        const int explicit_enable = params.find<int>("ls_acc_enable", -1);
        if (explicit_enable >= 0) {
            c.ls_acc_enable = explicit_enable != 0;
        } else {
            c.ls_acc_enable =
                params.find<int>("apply_acc_enable", 0) != 0 ||
                params.find<int>("apply_dense_acc_enable", 1) != 0 ||
                c.ls_acc_capacity_bytes > 0;
        }
    }

    c.ls_rf_entries = params.find<uint32_t>("ls_rf_entries", 0);
    c.ls_rf_entry_bytes = params.find<uint32_t>("ls_rf_entry_bytes", 4);
    c.ls_rf_read_ports = params.find<uint32_t>("ls_rf_read_ports", 1);
    c.ls_rf_write_ports = params.find<uint32_t>("ls_rf_write_ports", 1);
    {
        const int explicit_enable = params.find<int>("ls_rf_enable", -1);
        if (explicit_enable >= 0) {
            c.ls_rf_enable = explicit_enable != 0;
        } else {
            c.ls_rf_enable = c.ls_rf_entries > 0;
        }
    }

    c.v_thresh = params.find<float>("v_thresh", 1.0f);
    c.v_reset = params.find<float>("v_reset", 0.0f);
    c.v_rest = params.find<float>("v_rest", 0.0f);
    c.tau_mem = params.find<float>("tau_mem", 20.0f);
    c.t_ref = params.find<int>("t_ref", 2);

    c.enable_test_traffic = params.find<bool>("enable_test_traffic", false);
    c.test_traffic_packet_kind =
        toLowerCopy(params.find<std::string>("test_traffic_packet_kind", "spike"));
    if (c.test_traffic_packet_kind != "spike" &&
        c.test_traffic_packet_kind != "spikekey" &&
        c.test_traffic_packet_kind != "spikekey_direct_v4" &&
        c.test_traffic_packet_kind != "spiketile_bundle_v3") {
        c.test_traffic_packet_kind = "spike";
    }
    c.test_target_node = params.find<int>("test_target_node", 0);
    c.test_period = params.find<int>("test_period", 100);
    c.test_spikes_per_burst = params.find<int>("test_spikes_per_burst", 4);
    c.test_weight = params.find<float>("test_weight", 0.2f);
    c.test_max_spikes = params.find<int>("test_max_spikes", 10);

    c.use_optimized_ring = params.find<bool>("use_optimized_ring", true);
    c.print_node_summary = params.find<bool>("print_node_summary", true);
    c.primary_keepalive = params.find<bool>("primary_keepalive", false);
    c.manual_core_drive_enable = params.find<bool>("manual_core_drive_enable", false);
    c.manual_gas_gather_cycles = params.find<uint64_t>("manual_gas_gather_cycles", 200);

    c.verify_weights = params.find<bool>("verify_weights", false);
    c.weight_verify_samples = params.find<uint32_t>("weight_verify_samples", 16);
    c.expected_weight_value = params.find<float>("expected_weight_value", 0.5f);
    c.verify_log_each_sample = params.find<bool>("verify_log_each_sample", false);

    c.use_event_weight_fallback = params.find<bool>("use_event_weight_fallback", false);
    c.enable_memory_weights = params.find<bool>("enable_memory_weights", true);
    c.write_weights_on_init = params.find<bool>("write_weights_on_init", true);

    c.window_stats_enable = params.find<bool>("window_stats_enable", false);
    c.window_us = params.find<uint64_t>("window_us", 20);
    c.window_csv = params.find<std::string>("window_csv", "");
    c.window_metrics_csv = params.find<std::string>("window_metrics_csv", "");
    c.diag_fire_log = params.find<bool>("diag_fire_log", false);

    c.global_step_sync_enable = params.find<bool>("global_step_sync_enable", false);
    c.global_step_done_policy = toLowerCopy(params.find<std::string>("global_step_done_policy", "endscatter"));
    c.global_step_quiescent_min_cycles = clampNonZeroU64(params.find<uint64_t>("global_step_quiescent_min_cycles", 1));
    c.global_step_drain_min_cycles = clampNonZeroU64(params.find<uint64_t>("global_step_drain_min_cycles", 200));
    c.global_step_fixed_cycles = clampNonZeroU64(params.find<uint64_t>("global_step_fixed_cycles", 100000));
    c.loader_done_key = params.find<std::string>("loader_done_key", "");
    c.global_step_ready_delay_cycles = params.find<uint64_t>("global_step_ready_delay_cycles", 0);

    c.step_activation_enable = params.find<bool>("step_activation_enable", false);
    c.step_activation_fraction = params.find<double>("step_activation_fraction", 0.0);
    c.step_activation_fanout = params.find<uint32_t>("step_activation_fanout", 0);
    c.step_activation_seed = params.find<uint64_t>("step_activation_seed", 0xdecafbadULL);
    c.step_activation_period_cycles = params.find<uint64_t>("step_activation_period_cycles", 0);
    c.step_activation_trigger_core = params.find<int>("step_activation_trigger_core", 0);
    c.step_reset_mem_each_step = params.find<bool>("step_reset_mem_each_step", false);
    c.step_activation_event_weight = params.find<double>("step_activation_event_weight", 0.0);
    c.step_activation_pre_pattern = toLowerCopy(params.find<std::string>("step_activation_pre_pattern", "bernoulli"));
    c.step_activation_pre_cluster_len = params.find<uint32_t>("step_activation_pre_cluster_len", 0);
    c.step_activation_use_bcsr_routes = params.find<bool>("step_activation_use_bcsr_routes", false);
    c.step_activation_bcsr_template = params.find<std::string>("step_activation_bcsr_template", "");
    c.step_activation_bcsr_rows_per_core = params.find<uint32_t>("step_activation_bcsr_rows_per_core", 0);
    c.step_activation_bcsr_br = params.find<uint32_t>("step_activation_bcsr_br", 16);
    c.step_activation_bcsr_bc = params.find<uint32_t>("step_activation_bcsr_bc", 16);
    c.step_activation_bcsr_idx_bytes = params.find<uint32_t>("step_activation_bcsr_idx_bytes", 2);
    c.step_activation_bcsr_val_bytes = params.find<uint32_t>("step_activation_bcsr_val_bytes", 4);
    c.step_activation_bcsr_rowptr_offset = params.find<uint64_t>("step_activation_bcsr_rowptr_offset", 0);
    c.step_activation_bcsr_colidx_offset = params.find<uint64_t>("step_activation_bcsr_colidx_offset", 0);
    c.step_activation_bcsr_blockdata_offset = params.find<uint64_t>("step_activation_bcsr_blockdata_offset", 0);
    c.step_activation_bcsr_blockids_offset = params.find<uint64_t>("step_activation_bcsr_blockids_offset", 0);
    c.step_activation_bcsr_weight_epsilon = params.find<double>("step_activation_bcsr_weight_epsilon", 0.0);
    c.step_activation_log_enable = params.find<bool>("step_activation_log_enable", false);
    c.step_activation_build_local_only = params.find<bool>("step_activation_build_local_only", true);
    c.step_activation_bcsr_align = params.find<uint64_t>("step_activation_bcsr_align", 64);

    c.stage_events_csv_path = params.find<std::string>("stage_events_csv", "");
    c.stats_csv_path = params.find<std::string>("stats_csv", "");

    return c;
}

}} // namespace SST::SnnDL
