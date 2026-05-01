// -*- c++ -*-
//
// StreamWorkloadStatsModule: PE-level aggregation for stream workload counters.
//

#pragma once

#include "KeyedCounterStatsModule.h"

namespace SST { namespace SnnDL {

class StreamWorkloadStatsModule final : public KeyedCounterStatsModule {
public:
    explicit StreamWorkloadStatsModule(bool active_workload) : KeyedCounterStatsModule(active_workload) {
        addCounter("stream_mem_writes_issued_total");
        addCounter("stream_mem_reads_issued_total");
        addCounter("stream_mem_bytes_written_total");
        addCounter("stream_mem_bytes_read_total");
        addCounter("metadata_lookup_writes_issued_total");
        addCounter("metadata_lookup_reads_issued_total");
        addCounter("metadata_lookup_bytes_written_total");
        addCounter("metadata_lookup_bytes_read_total");
        addCounter("synapse_gather_writes_issued_total");
        addCounter("synapse_gather_reads_issued_total");
        addCounter("synapse_gather_bytes_written_total");
        addCounter("synapse_gather_bytes_read_total");
        addCounter("stream_region_writes_issued_total");
        addCounter("stream_region_reads_issued_total");
        addCounter("stream_region_bytes_written_total");
        addCounter("stream_region_bytes_read_total");
        addCounter("writeback_region_writes_issued_total");
        addCounter("writeback_region_reads_issued_total");
        addCounter("writeback_region_bytes_written_total");
        addCounter("writeback_region_bytes_read_total");
        addCounter("traffic_tx_batches");
        addCounter("traffic_tx_pre_total");
        addCounter("traffic_tx_spike_pkts");
        addCounter("traffic_tx_spikekey_pkts");
        addCounter("traffic_tx_spiketilekey_pkts");
        addCounter("traffic_tx_spikekey_v4_pkts");
        addCounter("traffic_tx_spiketilekey_v4_pkts");
        addCounter("traffic_tx_bundle_v1_pkts");
        addCounter("traffic_tx_bundle_v2_pkts");
        addCounter("traffic_tx_bundle_v3_pkts");
        addCounter("traffic_rx_spikekey_v4_total");
        addCounter("traffic_rx_spiketilekey_v4_total");
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
        addCounter("stream_mem_verify_pass_total");
        addCounter("stream_mem_verify_fail_total");
        addCounter("stream_pkt_sent_total");
        addCounter("stream_pkt_recv_total");
        addCounter("stream_pkt_bad_crc_total");
        addCounter("stream_pkt_bad_magic_total");
    }

    const char* name() const override { return "stream"; }
};

}} // namespace SST::SnnDL
