// -*- c++ -*-
//
// SnnWorkloadStatsModule: PE-level aggregation for snn workload receive-path counters.
//

#pragma once

#include "KeyedCounterStatsModule.h"

namespace SST { namespace SnnDL {

class SnnWorkloadStatsModule final : public KeyedCounterStatsModule {
public:
    explicit SnnWorkloadStatsModule(bool active_workload) : KeyedCounterStatsModule(active_workload) {
        addCounter("snn_tx_spike_packets_total");
        addCounter("snn_tx_spikekey_packets_total");
        addCounter("snn_tx_spiketilekey_packets_total");
        addCounter("snn_tx_spikekey_v4_packets_total");
        addCounter("snn_tx_spiketilekey_v4_packets_total");
        addCounter("snn_tx_bundle_v1_packets_total");
        addCounter("snn_tx_bundle_v2_packets_total");
        addCounter("snn_tx_bundle_v3_packets_total");
        addCounter("snn_tx_cohort_packets_total");
        addCounter("snn_tx_cohort_pres_total");
        addCounter("snn_tx_cohort_bandcolor_switch_total");
        addCounter("snn_rx_spike_packets_total");
        addCounter("snn_rx_spikekey_total");
        addCounter("snn_rx_spiketilekey_total");
        addCounter("snn_rx_spikekey_v4_total");
        addCounter("snn_rx_spiketilekey_v4_total");
        addCounter("snn_rx_fastpath_packets_total");
        addCounter("snn_rx_fallback_packets_total");
        addCounter("snn_rx_decode_fail_total");
        addCounter("snn_rx_fastpath_posts_total");
        addCounter("snn_rx_fastpath_accept_total");
        addCounter("snn_rx_fastpath_reject_total");
        addCounter("snn_rx_fastpath_edges_recorded_total");
        addCounter("snn_edge_record_attempt_total");
        addCounter("snn_edge_record_commit_total");
        addCounter("snn_edge_record_skip_gate_total");
        addCounter("snn_edge_record_skip_stage_total");
        addCounter("snn_edge_record_skip_capacity_total");
        addCounter("snn_edge_record_skip_reject_total");
        addCounter("snn_edge_record_fastpath_handler_entry_total");
        addCounter("snn_edge_record_fastpath_wms_missing_total");
        addCounter("snn_edge_record_fastpath_backend_not_ready_total");
        addCounter("snn_edge_record_fastpath_stage_block_total");
        addCounter("snn_edge_record_process_local_handler_entry_total");
        addCounter("snn_edge_record_process_local_wms_missing_total");
        addCounter("snn_edge_record_process_local_backend_not_ready_total");
        addCounter("snn_edge_record_process_local_stage_block_total");
        addCounter("snn_edge_record_deliver_window_handler_entry_total");
        addCounter("snn_edge_record_deliver_window_wms_missing_total");
        addCounter("snn_edge_record_deliver_window_backend_not_ready_total");
        addCounter("snn_edge_record_deliver_window_stage_block_total");
        addCounter("metadata_lookup_reads_issued_total");
        addCounter("synapse_gather_reads_issued_total");
        addCounter("stream_region_writes_issued_total");
        addCounter("stream_region_reads_issued_total");
        addCounter("stream_region_bytes_written_total");
        addCounter("stream_region_bytes_read_total");
        addCounter("writeback_region_writes_issued_total");
        addCounter("writeback_region_reads_issued_total");
        addCounter("writeback_region_bytes_written_total");
        addCounter("writeback_region_bytes_read_total");
        addCounter("traffic_semantic_metadata_lookup_demands_total");
        addCounter("traffic_semantic_synapse_gather_demands_total");
        addCounter("traffic_semantic_stream_region_demands_total");
        addCounter("traffic_semantic_writeback_region_demands_total");
        addCounter("traffic_semantic_tier_local_home_gather_demands_total");
        addCounter("traffic_semantic_same_xy_cross_tier_gather_demands_total");
        addCounter("traffic_semantic_remote_home_gather_demands_total");
        addCounter("traffic_semantic_tier_local_home_stream_region_demands_total");
        addCounter("traffic_semantic_same_xy_cross_tier_stream_region_demands_total");
        addCounter("traffic_semantic_remote_home_stream_region_demands_total");
        addCounter("route3d_native_activation_total");
        addCounter("route3d_native_gating_activation_total");
        addCounter("route3d_native_direct_activation_total");
        addCounter("route3d_native_unique_sources_total");
        addCounter("route_native_source_fanout_active");
        addCounter("route_native_target_synthesis_active");
        addCounter("route_bootstrap_dependency_active");
        addCounter("route_real_synapse_inputs_available");
        addCounter("route_native_synapse_source_candidate");
        addCounter("route_source_semantics_authority_legacy_provider");
        addCounter("route_source_semantics_authority_legacy_built_routes_3d");
        addCounter("route_source_semantics_authority_native_3d_route_table");
        addCounter("route_source_primary_kind_legacy_only");
        addCounter("route_source_primary_kind_edges_csv_bootstrap");
        addCounter("route_source_primary_kind_legacy_route_tables_bootstrap");
        addCounter("route_source_primary_kind_legacy_route_tables_with_real_synapse_inputs");
        addCounter("route_source_primary_kind_native_3d_route_table_with_real_synapse_inputs");
        addCounter("route_source_primary_kind_real_synapse_inputs_only");
        addCounter("route_native_bootstrap_source_edges_csv");
        addCounter("route_native_bootstrap_source_legacy_route_tables");
        addCounter("route_topology_mesh_2d");
        addCounter("route_topology_mesh_3d");
        addCounter("route_target_semantics_authority_legacy_multicast_fallback");
        addCounter("route_target_semantics_authority_compat_3d_target_synthesis");
        addCounter("route_target_semantics_authority_native_3d_target_synthesis");
    }

    const char* name() const override { return "snn"; }
};

}} // namespace SST::SnnDL
