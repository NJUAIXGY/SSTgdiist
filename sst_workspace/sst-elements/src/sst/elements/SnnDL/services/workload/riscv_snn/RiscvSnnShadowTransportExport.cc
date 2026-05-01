// -*- c++ -*-

#include <sst/core/sst_config.h>

#include "workload/riscv_snn/RiscvSnnShadowTransportExport.h"

namespace SST { namespace SnnDL {

namespace {

constexpr const char* kRuntimeBridgeShadowPrefix = "riscv_snn_backend_runtime_bridge_shadow_";

constexpr const char* kCanonicalTransportKeys[] = {
    "snn_tx_spike_packets_total",
    "snn_tx_spikekey_packets_total",
    "snn_tx_spiketilekey_packets_total",
    "snn_tx_spikekey_v4_packets_total",
    "snn_tx_spiketilekey_v4_packets_total",
    "snn_tx_bundle_v1_packets_total",
    "snn_tx_bundle_v2_packets_total",
    "snn_tx_bundle_v3_packets_total",
    "snn_tx_cohort_packets_total",
    "snn_tx_cohort_pres_total",
    "snn_tx_cohort_bandcolor_switch_total",
    "storm_cohort_packets_total",
    "storm_cohort_pres_total",
    "storm_cohort_bandcolor_switch_total",
    "snn_rx_spike_packets_total",
    "snn_rx_spikekey_total",
    "snn_rx_spiketilekey_total",
    "snn_rx_spikekey_v4_total",
    "snn_rx_spiketilekey_v4_total",
    "snn_rx_fastpath_packets_total",
    "snn_rx_fallback_packets_total",
    "snn_rx_decode_fail_total",
    "snn_rx_fastpath_posts_total",
    "snn_rx_fastpath_accept_total",
    "snn_rx_fastpath_reject_total",
    "snn_rx_fastpath_edges_recorded_total",
};

} // namespace

void exportRiscvSnnRuntimeBridgeShadowTransportStats(std::map<std::string, uint64_t>& stats) {
    for (const char* key : kCanonicalTransportKeys) {
        if (!key) continue;
        if (stats.find(key) != stats.end()) continue;
        const std::string shadow_key = std::string(kRuntimeBridgeShadowPrefix) + key;
        const auto shadow_it = stats.find(shadow_key);
        if (shadow_it == stats.end()) continue;
        stats[key] = shadow_it->second;
    }
}

}} // namespace SST::SnnDL
