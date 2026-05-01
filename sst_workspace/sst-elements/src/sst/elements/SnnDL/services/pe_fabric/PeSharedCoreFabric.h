// -*- c++ -*-
//
// Minimal per-PE shared core fabric for PULSE Phase 0/1.

#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <unordered_map>
#include <vector>

#include "services/pe_fabric/PulseDescriptor.h"

namespace SST { namespace SnnDL {

class PeSharedCoreFabric {
public:
    enum class PacketKind : uint8_t {
        Other = 0,
        Spike = 1,
        SpikeKey = 2,
        SpikeTileKey = 3,
    };

    enum class BypassMode : uint8_t {
        Disabled = 0,
        HighWatermark = 1,
    };

    enum class IngressDecision : uint8_t {
        ForwardToCore = 0,
        Bypass = 1,
    };

    enum class ControlMessageKind : uint8_t {
        FrontierExport = 0,
        OwnerAnnounce = 1,
        JoinRequest = 2,
        ReadyFanout = 3,
        JoinReject = 4,
    };

    struct Config {
        bool enable = false;
        bool observe_only = true;
        bool ingress_enable = true;
        bool agenda_observe_only = true;
        bool harbor_enable = false;
        bool descriptor_enable = false;
        bool descriptor_actual_enable = false;
        size_t num_cores = 1;
        uint32_t ingress_entries = 0;
        uint32_t core_queue_entries = 0;
        uint32_t descriptor_packet_min = 2;
        uint32_t bypass_high_watermark_pct = 100;
        BypassMode bypass_mode = BypassMode::Disabled;
    };

    struct IngressObservation {
        PacketKind kind = PacketKind::Other;
        int endpoint_id = -1;
        uint32_t bytes = 0;
        uint32_t step_seq = 0;
        bool descriptor_surrogate_valid = false;
        uint32_t descriptor_post_block_id = 0;
        uint32_t descriptor_weight_region_id = 0;
        uint32_t descriptor_retire_domain_id = 0;
        bool descriptor_region_safe = true;
    };

    struct ControlMessage {
        ControlMessageKind kind = ControlMessageKind::FrontierExport;
        uint32_t scope_id = 0;
        uint32_t producer_core_id = 0;
        uint32_t owner_core_id = 0;
        uint32_t consumer_core_id = 0;
        uint32_t step_seq = 0;
        uint32_t window_seq = 0;
        uint32_t domain_id = 0;
        uint32_t reject_reason = 0;
        uint64_t object_key = 0;
        uint64_t transaction_id = 0;
        uint64_t consumer_bitmap = 0;
        uint64_t ready_token = 0;
    };

    struct StatsSnapshot {
        uint64_t ingress_packets_total = 0;
        uint64_t ingress_spike_packets_total = 0;
        uint64_t ingress_spikekey_packets_total = 0;
        uint64_t ingress_spiketilekey_packets_total = 0;
        uint64_t ingress_core_dispatch_total = 0;
        uint64_t ingress_shared_buffered_total = 0;
        uint64_t ingress_shared_dispatch_total = 0;
        uint64_t ingress_direct_deliver_total = 0;
        uint64_t ingress_bypass_total = 0;
        uint64_t ingress_pressure_bypass_total = 0;
        uint64_t ingress_singleton_bypass_total = 0;
        uint64_t ingress_deadline_bypass_total = 0;
        uint64_t ingress_pressure_cycles_total = 0;
        uint32_t ingress_entries_current = 0;
        uint32_t ingress_entries_peak = 0;
        uint32_t core_queue_entries_current_max = 0;
        uint32_t core_queue_entries_peak = 0;
        uint64_t harbor_buckets_total = 0;
        uint64_t harbor_packet_sum = 0;
        uint64_t harbor_consumer_sum = 0;
        uint64_t harbor_bucket_peak = 0;
        uint64_t harbor_singleton_buckets_total = 0;
        uint64_t descriptor_total = 0;
        uint64_t descriptor_packet_sum = 0;
        uint64_t descriptor_consumer_sum = 0;
        uint64_t descriptor_singleton_drop_total = 0;
        uint32_t control_entries_current = 0;
        uint32_t control_entries_peak = 0;
        uint64_t control_backlog_cycles_total = 0;
        uint64_t control_messages_enqueued_total = 0;
        uint64_t control_messages_dequeued_total = 0;
        uint64_t control_frontier_export_total = 0;
        uint64_t control_frontier_export_consumed_total = 0;
        uint64_t control_owner_announce_total = 0;
        uint64_t control_owner_announce_consumed_total = 0;
        uint64_t control_join_request_total = 0;
        uint64_t control_join_request_consumed_total = 0;
        uint64_t control_ready_fanout_total = 0;
        uint64_t control_ready_fanout_consumed_total = 0;
        uint64_t control_join_reject_total = 0;
        uint64_t control_join_reject_consumed_total = 0;
        bool has_last_observation = false;
        PacketKind last_packet_kind = PacketKind::Other;
        int last_endpoint_id = -1;
        uint32_t last_packet_bytes = 0;
    };

    struct DispatchTicket {
        uint64_t token = 0;
        int endpoint_id = -1;
    };

    explicit PeSharedCoreFabric(const Config& cfg);

    const Config& config() const { return config_; }

    IngressDecision observeIngress(const IngressObservation& observation);
    IngressDecision decideBypass() const;
    void observeIngressDrain();
    void observeCoreQueueEnqueue(int endpoint_id);
    void observeCoreQueueDequeue(int endpoint_id);
    void observeCoreDispatch(int endpoint_id);
    void observeSharedIngressBuffered();
    void observeSharedDispatch();
    void observeDirectDeliver();
    void observeGatherHarbor(const IngressObservation& observation);
    void closeGatherHarborStep(uint32_t step_seq);
    void finalizeGatherHarbor();
    bool enqueueDispatchToken(uint64_t token, int endpoint_id);
    size_t collectDispatchBatch(size_t max_dispatch, std::vector<DispatchTicket>& out);
    size_t pendingDispatchCount() const { return dispatch_queue_.size(); }
    bool enqueueControlMessage(const ControlMessage& message);
    size_t collectControlBatch(size_t max_dispatch, std::vector<ControlMessage>& out);
    void observeControlBacklogCycle();
    size_t pendingControlCount() const { return control_queue_.size(); }

    StatsSnapshot snapshotStats() const { return stats_; }

private:
    struct GatherHarborKey {
        uint32_t step_id = 0;
        uint32_t post_block_id = 0;
        uint32_t weight_region_id = 0;
        uint32_t retire_domain_id = 0;

        bool operator==(const GatherHarborKey& other) const {
            return step_id == other.step_id &&
                   post_block_id == other.post_block_id &&
                   weight_region_id == other.weight_region_id &&
                   retire_domain_id == other.retire_domain_id;
        }
    };

    struct GatherHarborKeyHash {
        size_t operator()(const GatherHarborKey& key) const;
    };

    struct GatherHarborBucket {
        uint32_t packet_count = 0;
        uint32_t consumer_count = 0;
        uint64_t consumer_bitmap = 0;
        uint64_t first_arrival_cycle = 0;
        uint64_t last_arrival_cycle = 0;
        bool region_safe = true;
    };

    struct QueueMirrorState {
        uint32_t capacity_entries = 0;
        uint32_t occupancy = 0;
        uint32_t peak = 0;
    };

    static uint32_t clampPercent_(uint32_t value);
    static size_t normalizeCoreCount_(size_t num_cores);
    static uint32_t harborEndpointId_(int endpoint_id);
    static uint32_t harborWeightRegionId_(const IngressObservation& observation);
    static GatherHarborKey harborKey_(const IngressObservation& observation);
    static GatherHarborKey descriptorKey_(const IngressObservation& observation);
    static uint32_t popcount64_(uint64_t value);

    uint32_t bypassHighWatermarkEntries_() const;
    bool shouldLiftDescriptor_(const GatherHarborBucket& bucket) const;
    PulseActivationDescriptor makeDescriptor_(const GatherHarborKey& key,
                                             const GatherHarborBucket& bucket) const;
    void observeBucket_(std::unordered_map<GatherHarborKey, GatherHarborBucket, GatherHarborKeyHash>& buckets,
                        const GatherHarborKey& key,
                        const IngressObservation& observation,
                        bool track_harbor_peak);
    void observePacketKind_(PacketKind kind);
    void observeControlKind_(ControlMessageKind kind);
    void observeConsumedControlKind_(ControlMessageKind kind);
    void refreshCoreQueueCurrentMax_();
    QueueMirrorState* coreQueueState_(int endpoint_id);

    Config config_{};
    StatsSnapshot stats_{};
    QueueMirrorState ingress_mirror_{};
    QueueMirrorState control_mirror_{};
    std::vector<QueueMirrorState> core_queue_mirrors_{};
    std::deque<DispatchTicket> dispatch_queue_{};
    std::deque<ControlMessage> control_queue_{};
    std::unordered_map<GatherHarborKey, GatherHarborBucket, GatherHarborKeyHash> harbor_buckets_{};
    std::unordered_map<GatherHarborKey, GatherHarborBucket, GatherHarborKeyHash> descriptor_observe_buckets_{};
};

}} // namespace SST::SnnDL
