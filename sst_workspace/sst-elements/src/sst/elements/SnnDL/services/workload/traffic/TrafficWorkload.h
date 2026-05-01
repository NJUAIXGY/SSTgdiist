// -*- c++ -*-
//
// TrafficWorkload：
// - 原生 SpikeKey 多播实验用的最小 traffic-only workload。
// - 生成可复现（伪随机但确定性）的本地 pre neuron 集合，并通过 SpikeCommSubsystem 发射。
// - 不建模神经动力学，不依赖 GAS/memHierarchy/WeightLoader。
//

#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "api/ICoreWorkload.h"
#include "services/synapse/route3d/Route3DNodeMapper.h"

namespace SST { namespace SnnDL {

class NocSpikeTransport;
class SpikeCommSubsystem;
class ISynapseRoute;

class TrafficWorkload final : public ICoreWorkload {
public:
    struct SemanticMemoryDemand {
        uint64_t metadata_lookup_demands = 0;
        uint64_t synapse_gather_demands = 0;
        uint64_t stream_region_demands = 0;
        uint64_t writeback_region_demands = 0;
        uint64_t tier_local_home_gather_demands = 0;
        uint64_t same_xy_cross_tier_gather_demands = 0;
        uint64_t remote_home_gather_demands = 0;
        uint64_t tier_local_home_stream_region_demands = 0;
        uint64_t same_xy_cross_tier_stream_region_demands = 0;
        uint64_t remote_home_stream_region_demands = 0;
        uint64_t emitted_pres = 0;
        uint64_t multicast_packets = 0;

        bool empty() const {
            return metadata_lookup_demands == 0 &&
                   synapse_gather_demands == 0 &&
                   stream_region_demands == 0 &&
                   writeback_region_demands == 0 &&
                   tier_local_home_gather_demands == 0 &&
                   same_xy_cross_tier_gather_demands == 0 &&
                   remote_home_gather_demands == 0 &&
                   tier_local_home_stream_region_demands == 0 &&
                   same_xy_cross_tier_stream_region_demands == 0 &&
                   remote_home_stream_region_demands == 0 &&
                   emitted_pres == 0 &&
                   multicast_packets == 0;
        }
    };

    TrafficWorkload();
    ~TrafficWorkload() override;

    void configureFromParams(const SST::Params& params) override;
    void bindRuntime(const Runtime& rt) override;

    void onInitPhase(unsigned phase) override;
    void onSetup() override;
    void onFinish() override;

    bool onClockTick(uint64_t now_cycle) override;
    bool deliverPacket(NocPacketEvent* packet) override;

    bool hasWork() const override;
    double getUtilization() const override;
    void getStatistics(std::map<std::string, uint64_t>& stats) const override;
    SemanticMemoryDemand takeSemanticDemand();

private:
    void ensureCommReady_();
    std::vector<uint32_t> sampleNeuronIndices_(uint64_t now_cycle);

    // Keep an owned copy to avoid lifetime ambiguity across different SST param plumbing paths.
    std::unique_ptr<SST::Params> params_{};
    Runtime rt_{};

    bool configured_ = false;
    bool comm_ready_ = false;

    bool traffic_enable_ = false;
    uint64_t traffic_period_cycles_ = 0;
    uint32_t traffic_batch_size_ = 0;
    uint64_t traffic_seed_ = 0;
    uint32_t traffic_pre_begin_ = 0;
    uint32_t traffic_pre_end_ = 0;
    uint64_t traffic_stop_cycle_ = 0; // 0=never stop (until sim ends)

    // Experimental: sender-side SpikeTileKey aggregation knobs (forwarded to SpikeCommSubsystem).
    bool experimental_spiketile_enable_ = false;
    uint32_t experimental_spiketile_max_pre_bits_ = 64;
    uint32_t experimental_spiketile_block_cols_ = 0;
    bool experimental_compact_mask_enable_ = false;
    bool experimental_inter_bundle_enable_ = false;
    uint32_t experimental_inter_bundle_max_entries_ = 64;
    bool experimental_inter_bundle_v2_enable_ = false;

    bool spikekey_check_enable_ = true;
    bool spikekey_check_fatal_ = false;
    uint32_t spikekey_check_log_cap_ = 8;
    uint32_t spikekey_group_log_cap_ = 8;
    uint32_t spikekey_check_logged_ = 0;
    MeshShape3D traffic_mesh_shape_{};
    bool traffic_mesh_shape_valid_ = false;
    std::string traffic_memory_kind_ = "hbm_like";
    uint64_t source_global_neuron_base_ = 0;
    uint64_t metadata_base_addr_ = 0;
    uint64_t gather_base_addr_ = 0;
    uint64_t stream_base_addr_ = 0;
    uint64_t writeback_base_addr_ = 0;

    uint64_t next_cycle_ = 0;
    uint32_t seq_ = 1;

    uint64_t tx_batches_ = 0;
    uint64_t tx_pres_total_ = 0;
    SemanticMemoryDemand pending_semantic_demand_{};
    uint64_t total_semantic_metadata_lookup_demands_ = 0;
    uint64_t total_semantic_synapse_gather_demands_ = 0;
    uint64_t total_semantic_stream_region_demands_ = 0;
    uint64_t total_semantic_writeback_region_demands_ = 0;
    uint64_t total_semantic_tier_local_home_gather_demands_ = 0;
    uint64_t total_semantic_same_xy_cross_tier_gather_demands_ = 0;
    uint64_t total_semantic_remote_home_gather_demands_ = 0;
    uint64_t total_semantic_tier_local_home_stream_region_demands_ = 0;
    uint64_t total_semantic_same_xy_cross_tier_stream_region_demands_ = 0;
    uint64_t total_semantic_remote_home_stream_region_demands_ = 0;
    uint64_t rx_spike_total_ = 0;
    // Key-like packets delivered to this core (SpikeKey + SpikeTileKey).
    uint64_t rx_spikekey_total_ = 0;
    // Subset counter for SpikeTileKey.
    uint64_t rx_spiketilekey_total_ = 0;
    uint64_t rx_spikekey_v4_total_ = 0;
    uint64_t rx_spiketilekey_v4_total_ = 0;
    uint64_t rx_spiketilekey_bad_decode_ = 0;
    uint64_t rx_spike_hops_sum_ = 0;
    uint64_t rx_spike_hops_max_ = 0;
    uint64_t rx_spikekey_hops_sum_ = 0;
    uint64_t rx_spikekey_hops_max_ = 0;

    uint64_t rx_spikekey_checked_total_ = 0;
    uint64_t rx_spikekey_ok_total_ = 0;
    uint64_t rx_spikekey_bad_total_ = 0;
    uint64_t rx_spikekey_bad_decode_ = 0;
    uint64_t rx_spikekey_bad_stage_ = 0;
    uint64_t rx_spikekey_bad_dst_ = 0;
    uint64_t rx_spikekey_bad_blockpos_ = 0;
    uint64_t rx_spikekey_bad_mask_ = 0;

    std::unique_ptr<ISynapseRoute> synapse_route_;
    std::unique_ptr<SpikeCommSubsystem> spike_comm_;
    std::unique_ptr<NocSpikeTransport> noc_spike_transport_;
};

}} // namespace SST::SnnDL
