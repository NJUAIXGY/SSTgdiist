// -*- c++ -*-

#include "services/pe_fabric/PeSharedCoreFabric.h"

#include <algorithm>
#include <utility>

namespace SST { namespace SnnDL {

PeSharedCoreFabric::PeSharedCoreFabric(const Config& cfg)
    : config_(cfg),
      core_queue_mirrors_(normalizeCoreCount_(cfg.num_cores)) {
    config_.num_cores = core_queue_mirrors_.size();
    config_.bypass_high_watermark_pct = clampPercent_(config_.bypass_high_watermark_pct);
    if (config_.descriptor_packet_min == 0) {
        config_.descriptor_packet_min = 2;
    }
    ingress_mirror_.capacity_entries = config_.ingress_entries;
    for (auto& mirror : core_queue_mirrors_) {
        mirror.capacity_entries = config_.core_queue_entries;
    }
}

PeSharedCoreFabric::IngressDecision
PeSharedCoreFabric::observeIngress(const IngressObservation& observation) {
    if (!config_.enable || !config_.ingress_enable) {
        return IngressDecision::ForwardToCore;
    }

    ++stats_.ingress_packets_total;
    ++ingress_mirror_.occupancy;
    ingress_mirror_.peak = std::max(ingress_mirror_.peak, ingress_mirror_.occupancy);
    stats_.ingress_entries_current = ingress_mirror_.occupancy;
    stats_.ingress_entries_peak = ingress_mirror_.peak;
    stats_.has_last_observation = true;
    stats_.last_packet_kind = observation.kind;
    stats_.last_endpoint_id = observation.endpoint_id;
    stats_.last_packet_bytes = observation.bytes;
    observePacketKind_(observation.kind);

    const IngressDecision decision = decideBypass();
    if (decision == IngressDecision::Bypass) {
        ++stats_.ingress_bypass_total;
        ++stats_.ingress_pressure_bypass_total;
        ++stats_.ingress_pressure_cycles_total;
    }

    if (config_.observe_only) {
        return IngressDecision::ForwardToCore;
    }
    return decision;
}

PeSharedCoreFabric::IngressDecision PeSharedCoreFabric::decideBypass() const {
    if (!config_.enable || !config_.ingress_enable) {
        return IngressDecision::ForwardToCore;
    }
    if (config_.bypass_mode != BypassMode::HighWatermark) {
        return IngressDecision::ForwardToCore;
    }

    const uint32_t threshold = bypassHighWatermarkEntries_();
    if (threshold == 0) {
        return IngressDecision::ForwardToCore;
    }
    return (stats_.ingress_entries_current >= threshold)
               ? IngressDecision::Bypass
               : IngressDecision::ForwardToCore;
}

void PeSharedCoreFabric::observeIngressDrain() {
    if (!config_.enable || !config_.ingress_enable) return;

    if (ingress_mirror_.occupancy > 0) {
        --ingress_mirror_.occupancy;
    }
    stats_.ingress_entries_current = ingress_mirror_.occupancy;
}

void PeSharedCoreFabric::observeCoreQueueEnqueue(int endpoint_id) {
    if (!config_.enable) return;

    QueueMirrorState* mirror = coreQueueState_(endpoint_id);
    if (!mirror) return;

    ++stats_.ingress_core_dispatch_total;
    ++mirror->occupancy;
    mirror->peak = std::max(mirror->peak, mirror->occupancy);
    stats_.core_queue_entries_peak = std::max(stats_.core_queue_entries_peak, mirror->peak);
    refreshCoreQueueCurrentMax_();
}

void PeSharedCoreFabric::observeCoreQueueDequeue(int endpoint_id) {
    if (!config_.enable) return;

    QueueMirrorState* mirror = coreQueueState_(endpoint_id);
    if (!mirror) return;

    if (mirror->occupancy > 0) {
        --mirror->occupancy;
    }
    refreshCoreQueueCurrentMax_();
}

void PeSharedCoreFabric::observeCoreDispatch(int endpoint_id) {
    if (!config_.enable) return;

    observeIngressDrain();
    observeCoreQueueEnqueue(endpoint_id);
    observeCoreQueueDequeue(endpoint_id);
}

void PeSharedCoreFabric::observeSharedIngressBuffered() {
    if (!config_.enable) return;
    ++stats_.ingress_shared_buffered_total;
}

void PeSharedCoreFabric::observeSharedDispatch() {
    if (!config_.enable) return;
    ++stats_.ingress_shared_dispatch_total;
}

void PeSharedCoreFabric::observeDirectDeliver() {
    if (!config_.enable) return;
    ++stats_.ingress_direct_deliver_total;
}

void PeSharedCoreFabric::observeGatherHarbor(const IngressObservation& observation) {
    if (!config_.enable || !config_.harbor_enable) return;
    if (observation.step_seq == 0) return;

    observeBucket_(harbor_buckets_, harborKey_(observation), observation, /*track_harbor_peak=*/true);
    if (config_.descriptor_enable) {
        observeBucket_(
            descriptor_observe_buckets_,
            descriptorKey_(observation),
            observation,
            /*track_harbor_peak=*/false);
    }
}

void PeSharedCoreFabric::closeGatherHarborStep(uint32_t step_seq) {
    if (!config_.enable || !config_.harbor_enable) return;
    if (harbor_buckets_.empty() && descriptor_observe_buckets_.empty()) return;

    std::vector<GatherHarborKey> retired_keys;
    retired_keys.reserve(harbor_buckets_.size());
    for (const auto& kv : harbor_buckets_) {
        if (kv.first.step_id == step_seq) {
            retired_keys.push_back(kv.first);
        }
    }

    for (const auto& key : retired_keys) {
        auto it = harbor_buckets_.find(key);
        if (it == harbor_buckets_.end()) continue;
        const GatherHarborBucket& bucket = it->second;
        ++stats_.harbor_buckets_total;
        stats_.harbor_packet_sum += bucket.packet_count;
        stats_.harbor_consumer_sum += std::max<uint32_t>(bucket.consumer_count, 1u);
        if (bucket.packet_count <= 1u) {
            ++stats_.harbor_singleton_buckets_total;
        }
        harbor_buckets_.erase(it);
    }

    if (!config_.descriptor_enable) return;

    retired_keys.clear();
    retired_keys.reserve(descriptor_observe_buckets_.size());
    for (const auto& kv : descriptor_observe_buckets_) {
        if (kv.first.step_id == step_seq) {
            retired_keys.push_back(kv.first);
        }
    }

    for (const auto& key : retired_keys) {
        auto it = descriptor_observe_buckets_.find(key);
        if (it == descriptor_observe_buckets_.end()) continue;
        const GatherHarborBucket& bucket = it->second;
        if (shouldLiftDescriptor_(bucket)) {
            const PulseActivationDescriptor descriptor = makeDescriptor_(key, bucket);
            ++stats_.descriptor_total;
            stats_.descriptor_packet_sum += descriptor.packet_count;
            stats_.descriptor_consumer_sum += std::max<uint32_t>(descriptor.consumer_count, 1u);
        } else {
            ++stats_.descriptor_singleton_drop_total;
        }
        descriptor_observe_buckets_.erase(it);
    }
}

void PeSharedCoreFabric::finalizeGatherHarbor() {
    if (!config_.enable || !config_.harbor_enable) return;
    if (harbor_buckets_.empty() && descriptor_observe_buckets_.empty()) return;

    std::vector<uint32_t> step_ids;
    step_ids.reserve(harbor_buckets_.size() + descriptor_observe_buckets_.size());
    for (const auto& kv : harbor_buckets_) {
        step_ids.push_back(kv.first.step_id);
    }
    for (const auto& kv : descriptor_observe_buckets_) {
        step_ids.push_back(kv.first.step_id);
    }
    std::sort(step_ids.begin(), step_ids.end());
    step_ids.erase(std::unique(step_ids.begin(), step_ids.end()), step_ids.end());
    for (uint32_t step_id : step_ids) {
        closeGatherHarborStep(step_id);
    }
}

bool PeSharedCoreFabric::enqueueDispatchToken(uint64_t token, int endpoint_id) {
    if (!config_.enable || config_.observe_only || !config_.ingress_enable) return false;
    if (token == 0) return false;
    if (!coreQueueState_(endpoint_id)) return false;

    dispatch_queue_.push_back(DispatchTicket{token, endpoint_id});
    return true;
}

size_t PeSharedCoreFabric::collectDispatchBatch(size_t max_dispatch,
                                               std::vector<DispatchTicket>& out) {
    out.clear();
    if (!config_.enable || config_.observe_only || !config_.ingress_enable) return 0;
    if (max_dispatch == 0 || dispatch_queue_.empty()) return 0;

    const size_t budget = std::min(max_dispatch, core_queue_mirrors_.size());
    std::vector<uint8_t> endpoint_seen(core_queue_mirrors_.size(), 0);
    const size_t scan_limit = dispatch_queue_.size();
    for (size_t scan = 0; scan < scan_limit && out.size() < budget; ++scan) {
        DispatchTicket item = dispatch_queue_.front();
        dispatch_queue_.pop_front();
        if (item.endpoint_id < 0 ||
            static_cast<size_t>(item.endpoint_id) >= endpoint_seen.size()) {
            out.push_back(item);
            continue;
        }
        const size_t endpoint = static_cast<size_t>(item.endpoint_id);
        if (endpoint_seen[endpoint] != 0) {
            dispatch_queue_.push_back(item);
            continue;
        }
        endpoint_seen[endpoint] = 1;
        out.push_back(item);
    }
    return out.size();
}

bool PeSharedCoreFabric::enqueueControlMessage(const ControlMessage& message) {
    if (!config_.enable) return false;

    control_queue_.push_back(message);
    ++control_mirror_.occupancy;
    control_mirror_.peak = std::max(control_mirror_.peak, control_mirror_.occupancy);
    stats_.control_entries_current = control_mirror_.occupancy;
    stats_.control_entries_peak = control_mirror_.peak;
    ++stats_.control_messages_enqueued_total;
    observeControlKind_(message.kind);
    return true;
}

size_t PeSharedCoreFabric::collectControlBatch(size_t max_dispatch,
                                               std::vector<ControlMessage>& out) {
    out.clear();
    if (!config_.enable) return 0;
    if (max_dispatch == 0 || control_queue_.empty()) return 0;

    const size_t budget = std::min(max_dispatch, control_queue_.size());
    for (size_t i = 0; i < budget; ++i) {
        out.push_back(control_queue_.front());
        observeConsumedControlKind_(out.back().kind);
        control_queue_.pop_front();
        if (control_mirror_.occupancy > 0) {
            --control_mirror_.occupancy;
        }
    }
    stats_.control_entries_current = control_mirror_.occupancy;
    stats_.control_messages_dequeued_total += out.size();
    return out.size();
}

void PeSharedCoreFabric::observeControlBacklogCycle() {
    if (!config_.enable) return;
    if (control_queue_.empty()) return;
    ++stats_.control_backlog_cycles_total;
}

uint32_t PeSharedCoreFabric::clampPercent_(uint32_t value) {
    if (value == 0) return 100;
    return std::min<uint32_t>(value, 100);
}

size_t PeSharedCoreFabric::normalizeCoreCount_(size_t num_cores) {
    return std::max<size_t>(num_cores, 1);
}

size_t PeSharedCoreFabric::GatherHarborKeyHash::operator()(const GatherHarborKey& key) const {
    size_t seed = static_cast<size_t>(key.step_id);
    seed ^= static_cast<size_t>(key.post_block_id) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
    seed ^= static_cast<size_t>(key.weight_region_id) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
    seed ^= static_cast<size_t>(key.retire_domain_id) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
    return seed;
}

uint32_t PeSharedCoreFabric::harborEndpointId_(int endpoint_id) {
    return (endpoint_id >= 0) ? static_cast<uint32_t>(endpoint_id) : 0u;
}

uint32_t PeSharedCoreFabric::harborWeightRegionId_(const IngressObservation& observation) {
    const uint32_t kind = static_cast<uint32_t>(observation.kind);
    const uint32_t bytes = observation.bytes & 0x0000ffffu;
    return (kind << 16) ^ bytes;
}

PeSharedCoreFabric::GatherHarborKey
PeSharedCoreFabric::harborKey_(const IngressObservation& observation) {
    const uint32_t endpoint_id = harborEndpointId_(observation.endpoint_id);
    GatherHarborKey key{};
    key.step_id = observation.step_seq;
    key.post_block_id = endpoint_id;
    key.weight_region_id = harborWeightRegionId_(observation);
    key.retire_domain_id = endpoint_id;
    return key;
}

PeSharedCoreFabric::GatherHarborKey
PeSharedCoreFabric::descriptorKey_(const IngressObservation& observation) {
    if (!observation.descriptor_surrogate_valid) {
        return harborKey_(observation);
    }

    GatherHarborKey key{};
    key.step_id = observation.step_seq;
    key.post_block_id = observation.descriptor_post_block_id;
    key.weight_region_id = observation.descriptor_weight_region_id;
    key.retire_domain_id = observation.descriptor_retire_domain_id;
    return key;
}

uint32_t PeSharedCoreFabric::popcount64_(uint64_t value) {
    uint32_t count = 0;
    while (value != 0) {
        value &= (value - 1);
        ++count;
    }
    return count;
}

uint32_t PeSharedCoreFabric::bypassHighWatermarkEntries_() const {
    if (config_.ingress_entries == 0) return 0;
    const uint64_t scaled =
        static_cast<uint64_t>(config_.ingress_entries) *
        static_cast<uint64_t>(config_.bypass_high_watermark_pct);
    const uint32_t threshold = static_cast<uint32_t>((scaled + 99u) / 100u);
    return std::max<uint32_t>(threshold, 1u);
}

bool PeSharedCoreFabric::shouldLiftDescriptor_(const GatherHarborBucket& bucket) const {
    if (bucket.consumer_count >= 2u) return true;
    return bucket.packet_count >= config_.descriptor_packet_min;
}

PulseActivationDescriptor
PeSharedCoreFabric::makeDescriptor_(const GatherHarborKey& key,
                                    const GatherHarborBucket& bucket) const {
    PulseActivationDescriptor descriptor{};
    descriptor.step_id = key.step_id;
    descriptor.window_id = key.step_id;
    descriptor.post_block_id = key.post_block_id;
    descriptor.weight_region_id = key.weight_region_id;
    descriptor.retire_domain_id = key.retire_domain_id;
    descriptor.consumer_bitmap = bucket.consumer_bitmap;
    descriptor.consumer_count = std::max<uint32_t>(bucket.consumer_count, 1u);
    descriptor.packet_count = bucket.packet_count;
    descriptor.slack_to_apply_close = 0;
    descriptor.region_safe = bucket.region_safe;
    return descriptor;
}

void PeSharedCoreFabric::observeBucket_(
    std::unordered_map<GatherHarborKey, GatherHarborBucket, GatherHarborKeyHash>& buckets,
    const GatherHarborKey& key,
    const IngressObservation& observation,
    bool track_harbor_peak) {
    const uint32_t endpoint_id = harborEndpointId_(observation.endpoint_id);
    GatherHarborBucket& bucket = buckets[key];
    if (bucket.packet_count == 0) {
        bucket.first_arrival_cycle = observation.step_seq;
        bucket.region_safe = observation.descriptor_region_safe;
        if (track_harbor_peak) {
            stats_.harbor_bucket_peak =
                std::max<uint64_t>(stats_.harbor_bucket_peak, static_cast<uint64_t>(buckets.size()));
        }
    } else {
        bucket.region_safe = bucket.region_safe && observation.descriptor_region_safe;
    }
    ++bucket.packet_count;
    if (endpoint_id < 64u) {
        bucket.consumer_bitmap |= (uint64_t{1} << endpoint_id);
    }
    bucket.consumer_count = popcount64_(bucket.consumer_bitmap);
    if (bucket.consumer_count == 0) bucket.consumer_count = 1;
    bucket.last_arrival_cycle = observation.step_seq;
}

void PeSharedCoreFabric::observePacketKind_(PacketKind kind) {
    switch (kind) {
        case PacketKind::Spike:
            ++stats_.ingress_spike_packets_total;
            break;
        case PacketKind::SpikeKey:
            ++stats_.ingress_spikekey_packets_total;
            break;
        case PacketKind::SpikeTileKey:
            ++stats_.ingress_spiketilekey_packets_total;
            break;
        case PacketKind::Other:
        default:
            break;
    }
}

void PeSharedCoreFabric::observeControlKind_(ControlMessageKind kind) {
    switch (kind) {
        case ControlMessageKind::FrontierExport:
            ++stats_.control_frontier_export_total;
            break;
        case ControlMessageKind::OwnerAnnounce:
            ++stats_.control_owner_announce_total;
            break;
        case ControlMessageKind::JoinRequest:
            ++stats_.control_join_request_total;
            break;
        case ControlMessageKind::ReadyFanout:
            ++stats_.control_ready_fanout_total;
            break;
        case ControlMessageKind::JoinReject:
            ++stats_.control_join_reject_total;
            break;
    }
}

void PeSharedCoreFabric::observeConsumedControlKind_(ControlMessageKind kind) {
    switch (kind) {
        case ControlMessageKind::FrontierExport:
            ++stats_.control_frontier_export_consumed_total;
            break;
        case ControlMessageKind::OwnerAnnounce:
            ++stats_.control_owner_announce_consumed_total;
            break;
        case ControlMessageKind::JoinRequest:
            ++stats_.control_join_request_consumed_total;
            break;
        case ControlMessageKind::ReadyFanout:
            ++stats_.control_ready_fanout_consumed_total;
            break;
        case ControlMessageKind::JoinReject:
            ++stats_.control_join_reject_consumed_total;
            break;
    }
}

void PeSharedCoreFabric::refreshCoreQueueCurrentMax_() {
    uint32_t current_max = 0;
    for (const auto& mirror : core_queue_mirrors_) {
        current_max = std::max(current_max, mirror.occupancy);
    }
    stats_.core_queue_entries_current_max = current_max;
}

PeSharedCoreFabric::QueueMirrorState* PeSharedCoreFabric::coreQueueState_(int endpoint_id) {
    if (endpoint_id < 0) return nullptr;
    const size_t core = static_cast<size_t>(endpoint_id);
    if (core >= core_queue_mirrors_.size()) return nullptr;
    return &core_queue_mirrors_[core];
}

}} // namespace SST::SnnDL
