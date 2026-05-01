// -*- c++ -*-
//
// SpikeCommSubsystem: 通信子系统，封装 fanout + 事件构造 + 传输调用。
//

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include <sst/core/output.h>

#include "ISpikeTransport.h"
#include "ISynapseRoute.h"

namespace SST { namespace SnnDL {

class SpikeEvent;
class INocTransport;

struct SpikeCommRuntimeConfig {
    Output* log = nullptr;
    ISpikeTransport* transport = nullptr;
    INocTransport* noc = nullptr;  // optional (native multicast path uses packet injection)
    int src_core = 0;
    uint32_t node_id = 0;
    const uint32_t* active_step_seq = nullptr;
    ISynapseRoute* synapse_route = nullptr;
    uint64_t global_neuron_base = 0;
    bool experimental_spiketile_enable = false;
    uint32_t experimental_spiketile_max_pre_bits = 64;
    uint32_t experimental_spiketile_block_cols = 0;
    bool experimental_compact_mask_enable = false;
    bool experimental_inter_bundle_enable = false;
    uint32_t experimental_inter_bundle_max_entries = 64;
    bool experimental_inter_bundle_v2_enable = false;
};

class SpikeCommSubsystem {
public:
    void configure();

    void bindRuntime(const SpikeCommRuntimeConfig& rt);

    // Ensure Synapse/Route routing+fanout provider is initialized (idempotent).
    void initRouting();

    // 常规入口：compute core 报告本地 neuron_idx
    void emitNeuronFire(uint32_t neuron_idx, uint64_t now_cycle);
    // 批量入口：控制层已收敛好 fired 集合，仅需统一下发（不引入 compute::FireEvent 依赖）
    uint64_t emitNeuronFireBatch(const std::vector<uint32_t>& neuron_indices, uint64_t now_cycle);
    // 已知 source_global 的入口（保留扩展用途）
    void emitSource(uint32_t source_global, uint32_t source_local, uint64_t now_cycle);

    // Apply gating decision (from parent/PE). Delegated to Synapse/Route.
    void applyGatingDecision(uint32_t src_global,
                             const std::vector<uint32_t>& dest_pes,
                             uint64_t current_cycle,
                             uint64_t ttl_cycles);

    bool ready() const { return transport_ && route_provider_ready_; }
    uint64_t txSpikePacketsTotal() const { return tx_spike_packets_total_; }
    uint64_t txSpikeKeyPacketsTotal() const { return tx_spikekey_packets_total_; }
    uint64_t txSpikeTileKeyPacketsTotal() const { return tx_spiketilekey_packets_total_; }
    uint64_t txSpikeKeyV4PacketsTotal() const { return tx_spikekey_v4_packets_total_; }
    uint64_t txSpikeTileKeyV4PacketsTotal() const { return tx_spiketilekey_v4_packets_total_; }
    uint64_t txBundleV1PacketsTotal() const { return tx_bundle_v1_packets_total_; }
    uint64_t txBundleV2PacketsTotal() const { return tx_bundle_v2_packets_total_; }
    uint64_t txBundleV3PacketsTotal() const { return tx_bundle_v3_packets_total_; }
    uint64_t txCohortPacketsTotal() const { return tx_cohort_packets_total_; }
    uint64_t txCohortPresTotal() const { return tx_cohort_pres_total_; }
    uint64_t txCohortBandcolorSwitchTotal() const { return tx_cohort_bandcolor_switch_total_; }
    uint64_t stormCohortPacketsTotal() const { return tx_cohort_packets_total_; }
    uint64_t stormCohortPresTotal() const { return tx_cohort_pres_total_; }
    uint64_t stormCohortBandcolorSwitchTotal() const { return tx_cohort_bandcolor_switch_total_; }

private:
    void emitCommon_(uint32_t source_global, uint32_t source_local, uint64_t now_cycle);
    bool emitSpikeTileBatchExperimental_(const std::vector<uint32_t>& neuron_indices, uint64_t now_cycle);

    Output* log_ = nullptr;
    ISpikeTransport* transport_ = nullptr;     // 非拥有；由外部管理生命周期
    INocTransport* noc_ = nullptr;            // 非拥有；由外部管理生命周期
    int src_core_ = 0;
    uint32_t node_id_ = 0;
    const uint32_t* active_step_seq_ = nullptr;
    uint64_t global_neuron_base_ = 0;
    uint64_t emit_seq_ = 0; // monotonic per run; used to ensure group_id uniqueness under high-rate injection

    bool route_provider_ready_ = false;
    ISynapseRoute* synapse_route_ = nullptr;  // 非拥有；由控制层装配并保证生命周期
    bool experimental_spiketile_enable_ = false;
    uint32_t experimental_spiketile_max_pre_bits_ = 64;
    uint32_t experimental_spiketile_block_cols_ = 0;
    bool experimental_compact_mask_enable_ = false;
    bool experimental_inter_bundle_enable_ = false;
    uint32_t experimental_inter_bundle_max_entries_ = 64;
    bool experimental_inter_bundle_v2_enable_ = false;
    uint64_t tx_spike_packets_total_ = 0;
    uint64_t tx_spikekey_packets_total_ = 0;
    uint64_t tx_spiketilekey_packets_total_ = 0;
    uint64_t tx_spikekey_v4_packets_total_ = 0;
    uint64_t tx_spiketilekey_v4_packets_total_ = 0;
    uint64_t tx_bundle_v1_packets_total_ = 0;
    uint64_t tx_bundle_v2_packets_total_ = 0;
    uint64_t tx_bundle_v3_packets_total_ = 0;
    uint64_t tx_cohort_packets_total_ = 0;
    uint64_t tx_cohort_pres_total_ = 0;
    uint64_t tx_cohort_bandcolor_switch_total_ = 0;
    uint64_t bundle_v3_diag_attempt_total_ = 0;
    uint64_t bundle_v3_diag_success_total_ = 0;
    uint64_t bundle_v3_diag_fallback_total_ = 0;
    uint64_t bundle_v3_diag_emitted_packets_total_ = 0;
    uint32_t bundle_v3_diag_logs_emitted_ = 0;
    uint32_t bundle_v3_diag_log_cap_ = 64;

};

}} // namespace SST::SnnDL
