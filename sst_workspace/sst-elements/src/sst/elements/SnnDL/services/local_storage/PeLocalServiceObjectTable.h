// -*- c++ -*-
//
// PeLocalServiceObjectTable:
// - Minimal PE-local shadow table for owner/live/ready/late service-object studies.
// - Keeps service state observational and isolated from the architectural commit path.

#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <limits>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

namespace SST { namespace SnnDL {

class PeLocalServiceObjectTable {
public:
    enum class ServiceState : uint8_t {
        Invalid = 0,
        OwnerActive = 1,
        Ready = 2,
    };

    struct Config {
        bool enable = false;
        uint32_t num_pods = 1;
        uint32_t active_entries_per_pod = 0;
        uint32_t released_entries_per_pod = 0;
        bool ready_lease_enable = false;
        uint64_t ready_lease_ttl = 0;
        uint32_t ready_lease_kind_mask = 0;
    };

    struct OwnerRequest {
        uint32_t pod_id = 0;
        uint32_t window_seq = 0;
        uint64_t object_key = 0;
        uint32_t owner_core_id = 0;
    };

    struct OwnerResult {
        bool valid = false;
        bool formed_owner = false;
        bool owner_exists = false;
        ServiceState state = ServiceState::Invalid;
        uint32_t owner_core_id = 0;
        uint64_t consumer_bitmap = 0;
        uint64_t ready_token = 0;
    };

    struct JoinRequest {
        uint32_t pod_id = 0;
        uint32_t window_seq = 0;
        uint64_t object_key = 0;
        uint32_t consumer_core_id = 0;
    };

    struct JoinResult {
        bool valid = false;
        bool joined_live = false;
        bool joined_ready = false;
        bool late_join = false;
        bool ready_lease_hit = false;
        bool ready_lease_expired = false;
        bool duplicate_consumer = false;
        ServiceState state = ServiceState::Invalid;
        uint32_t owner_core_id = 0;
        uint64_t consumer_bitmap = 0;
        uint64_t ready_token = 0;
    };

    struct ReadyRequest {
        uint32_t pod_id = 0;
        uint32_t window_seq = 0;
        uint64_t object_key = 0;
        uint64_t ready_token = 0;
    };

    struct ReadyResult {
        bool valid = false;
        bool transitioned = false;
        bool released_after_transition = false;
        uint64_t ready_token = 0;
        uint64_t consumer_bitmap = 0;
        uint32_t consumer_count = 0;
    };

    struct ProbeRequest {
        uint32_t pod_id = 0;
        uint32_t window_seq = 0;
        uint64_t object_key = 0;
    };

    struct ProbeResult {
        bool valid = false;
        bool active = false;
        bool released = false;
        bool ready = false;
        bool release_pending = false;
        ServiceState state = ServiceState::Invalid;
        uint32_t owner_core_id = 0;
        uint64_t consumer_bitmap = 0;
        uint64_t ready_token = 0;
    };

    struct ReleaseRequest {
        uint32_t pod_id = 0;
        uint32_t window_seq = 0;
        uint64_t object_key = 0;
        bool defer_until_ready = false;
    };

    struct ReleaseResult {
        bool valid = false;
        bool released = false;
        bool deferred = false;
    };

    struct StatsSnapshot {
        bool enabled = false;
        uint64_t owner_form_total = 0;
        uint64_t join_live_total = 0;
        uint64_t join_ready_total = 0;
        uint64_t late_join_total = 0;
        uint64_t duplicate_join_total = 0;
        uint64_t ready_transition_total = 0;
        uint64_t ready_fanout_total = 0;
        uint64_t ready_fanout_consumers_sum = 0;
        uint64_t ready_fanout_consumers_peak = 0;
        uint64_t released_total = 0;
        uint64_t release_deferred_total = 0;
        uint64_t ready_release_total = 0;
        uint64_t ready_lease_hit_total = 0;
        uint64_t ready_lease_expired_total = 0;
        uint64_t potential_private_service_elide_total = 0;
        uint64_t active_entries_total = 0;
        uint64_t release_pending_active_total = 0;
        // PE-Atlas v2 machine-visibility skeleton at the service-object-table boundary.
        // In this layer:
        // - materialize/publicize happen when an object is first inserted into the table
        // - owner_form happens when that insertion successfully establishes authority
        // - ready/release follow the table's own lifecycle transitions
        // - private_only means the object was released without any non-owner consumer
        uint64_t atlas_obj_materialize_total = 0;
        uint64_t atlas_obj_publicize_total = 0;
        uint64_t atlas_obj_owner_form_total = 0;
        uint64_t atlas_obj_ready_total = 0;
        uint64_t atlas_obj_release_total = 0;
        uint64_t atlas_obj_private_only_total = 0;
    };

    static constexpr uint32_t kMetadataKindMaskPreMphfBase = (1u << 1);
    static constexpr uint32_t kMetadataKindMaskPreMphfBand = (1u << 2);
    static constexpr uint32_t kMetadataKindMaskPreband =
        kMetadataKindMaskPreMphfBase | kMetadataKindMaskPreMphfBand;
    static constexpr uint32_t kMetadataKindMaskIdx2Row = (1u << 3);
    static constexpr uint32_t kMetadataKindMaskRowIndex = (1u << 4);
    static constexpr uint32_t kMetadataKindMaskRowDescriptor = (1u << 5);
    static constexpr uint32_t kMetadataKindMaskAll =
        kMetadataKindMaskPreMphfBase |
        kMetadataKindMaskPreMphfBand |
        kMetadataKindMaskIdx2Row |
        kMetadataKindMaskRowIndex |
        kMetadataKindMaskRowDescriptor;

    PeLocalServiceObjectTable() = default;
    explicit PeLocalServiceObjectTable(const Config& cfg) { configure(cfg); }

    void configure(const Config& cfg) {
        cfg_ = cfg;
        const size_t pods = std::max<size_t>(1u, static_cast<size_t>(cfg_.num_pods));
        pod_states_.assign(pods, PodState{});
        next_ready_token_ = 1u;
        now_cycle_ = 0u;
        stats_ = StatsSnapshot{};
        stats_.enabled = cfg_.enable;
    }

    const Config& config() const { return cfg_; }
    bool enabled() const { return cfg_.enable; }

    void onClockTick(uint64_t now_cycle) {
        now_cycle_ = now_cycle;
        if (!enabled()) return;

        for (auto& pod : pod_states_) {
            for (auto& kv : pod.released_entries) {
                ReleasedEntry& entry = kv.second;
                if (!entry.leased_ready) continue;
                if (entry.lease_expire_cycle > now_cycle_) continue;
                entry.leased_ready = false;
            }
        }
    }

    OwnerResult noteOwnerForm(const OwnerRequest& request) {
        OwnerResult result{};
        if (!enabled()) return result;
        if (request.pod_id >= pod_states_.size()) return result;

        auto& pod = pod_states_[request.pod_id];
        const Key key{request.window_seq, request.object_key};
        auto it = pod.active_entries.find(key);
        if (it != pod.active_entries.end()) {
            touch_(pod.active_order, key);
            result.valid = true;
            result.owner_exists = true;
            result.state = it->second.state;
            result.owner_core_id = it->second.owner_core_id;
            result.consumer_bitmap = it->second.consumer_bitmap;
            result.ready_token = it->second.ready_token;
            return result;
        }

        evictIfNeeded_(pod);

        Entry entry{};
        entry.window_seq = request.window_seq;
        entry.object_key = request.object_key;
        entry.owner_core_id = request.owner_core_id;
        entry.consumer_bitmap = consumerBit_(request.owner_core_id);
        entry.consumer_count = (entry.consumer_bitmap != 0u) ? 1u : 0u;
        entry.state = ServiceState::OwnerActive;
        pod.active_order.push_back(key);
        const auto inserted = pod.active_entries.emplace(key, entry).first;

        result.valid = true;
        result.formed_owner = true;
        result.state = ServiceState::OwnerActive;
        result.owner_core_id = inserted->second.owner_core_id;
        result.consumer_bitmap = inserted->second.consumer_bitmap;
        stats_.owner_form_total += 1u;
        stats_.atlas_obj_materialize_total += 1u;
        stats_.atlas_obj_publicize_total += 1u;
        stats_.atlas_obj_owner_form_total += 1u;
        return result;
    }

    JoinResult join(const JoinRequest& request) {
        JoinResult result{};
        if (!enabled()) return result;
        if (request.pod_id >= pod_states_.size()) return result;

        auto& pod = pod_states_[request.pod_id];
        const Key key{request.window_seq, request.object_key};
        auto it = pod.active_entries.find(key);
        if (it == pod.active_entries.end()) {
            result.valid = true;
            auto released_it = pod.released_entries.find(key);
            if (released_it == pod.released_entries.end()) {
                return result;
            }

            ReleasedEntry& released = released_it->second;
            result.owner_core_id = released.owner_core_id;
            result.consumer_bitmap = released.consumer_bitmap;
            result.ready_token = released.ready_token;
            if (released.leased_ready) {
                result.state = ServiceState::Ready;
                const uint64_t bit = consumerBit_(request.consumer_core_id);
                if (bit != 0u && (released.consumer_bitmap & bit) != 0u) {
                    result.duplicate_consumer = true;
                    stats_.duplicate_join_total += 1u;
                    return result;
                }

                if (bit != 0u) {
                    released.consumer_bitmap |= bit;
                    released.consumer_count += 1u;
                    result.consumer_bitmap = released.consumer_bitmap;
                }

                touch_(pod.released_order, key);
                result.joined_ready = true;
                result.ready_lease_hit = true;
                stats_.join_ready_total += 1u;
                stats_.ready_lease_hit_total += 1u;
                stats_.potential_private_service_elide_total += 1u;
                return result;
            }

            result.late_join = true;
            result.ready_lease_expired = released.had_ready_lease;
            if (result.ready_lease_expired) {
                stats_.ready_lease_expired_total += 1u;
            }
            if (result.late_join) {
                stats_.late_join_total += 1u;
            }
            return result;
        }

        touch_(pod.active_order, key);
        Entry& entry = it->second;
        result.valid = true;
        result.state = entry.state;
        result.owner_core_id = entry.owner_core_id;
        result.consumer_bitmap = entry.consumer_bitmap;
        result.ready_token = entry.ready_token;

        const uint64_t bit = consumerBit_(request.consumer_core_id);
        if (bit != 0u && (entry.consumer_bitmap & bit) != 0u) {
            result.duplicate_consumer = true;
            stats_.duplicate_join_total += 1u;
            return result;
        }

        if (bit != 0u) {
            entry.consumer_bitmap |= bit;
            entry.consumer_count += 1u;
            result.consumer_bitmap = entry.consumer_bitmap;
        }

        if (entry.state == ServiceState::Ready) {
            result.joined_ready = true;
            result.ready_token = entry.ready_token;
            stats_.join_ready_total += 1u;
        } else {
            result.joined_live = true;
            stats_.join_live_total += 1u;
        }
        stats_.potential_private_service_elide_total += 1u;
        return result;
    }

    ReadyResult markReady(const ReadyRequest& request) {
        ReadyResult result{};
        if (!enabled()) return result;
        if (request.pod_id >= pod_states_.size()) return result;

        auto& pod = pod_states_[request.pod_id];
        const Key key{request.window_seq, request.object_key};
        auto it = pod.active_entries.find(key);
        if (it == pod.active_entries.end()) {
            return result;
        }

        touch_(pod.active_order, key);
        Entry& entry = it->second;
        result.valid = true;
        result.consumer_bitmap = entry.consumer_bitmap;
        result.consumer_count = entry.consumer_count;

        if (entry.state == ServiceState::Ready) {
            result.ready_token = entry.ready_token;
            return result;
        }

        entry.state = ServiceState::Ready;
        entry.ready_token = (request.ready_token != 0u) ? request.ready_token : next_ready_token_++;
        result.transitioned = true;
        result.ready_token = entry.ready_token;
        stats_.ready_transition_total += 1u;
        stats_.ready_fanout_total += 1u;
        stats_.ready_fanout_consumers_sum += static_cast<uint64_t>(entry.consumer_count);
        stats_.ready_fanout_consumers_peak = std::max<uint64_t>(
            stats_.ready_fanout_consumers_peak,
            static_cast<uint64_t>(entry.consumer_count));
        stats_.atlas_obj_ready_total += 1u;

        if (entry.release_pending) {
            ReleasedEntry released{};
            released.owner_core_id = entry.owner_core_id;
            released.consumer_bitmap = entry.consumer_bitmap;
            released.consumer_count = entry.consumer_count;
            released.ready_token = entry.ready_token;
            if (readyLeaseEnabledForObjectKey_(request.object_key)) {
                released.leased_ready = true;
                released.had_ready_lease = true;
                released.lease_expire_cycle = saturatingAdd_(now_cycle_, cfg_.ready_lease_ttl);
            }
            eraseFromOrder_(pod.active_order, key);
            pod.active_entries.erase(it);
            recordReleased_(pod, key, released);
            result.released_after_transition = true;
            stats_.released_total += 1u;
            stats_.ready_release_total += 1u;
            stats_.atlas_obj_release_total += 1u;
            if (released.consumer_count <= 1u) {
                stats_.atlas_obj_private_only_total += 1u;
            }
        }
        return result;
    }

    ProbeResult probe(const ProbeRequest& request) const {
        ProbeResult result{};
        if (!enabled()) return result;
        if (request.pod_id >= pod_states_.size()) return result;

        const auto& pod = pod_states_[request.pod_id];
        const Key key{request.window_seq, request.object_key};
        const auto it = pod.active_entries.find(key);
        if (it != pod.active_entries.end()) {
            result.valid = true;
            result.active = true;
            result.state = it->second.state;
            result.ready = (it->second.state == ServiceState::Ready);
            result.release_pending = it->second.release_pending;
            result.owner_core_id = it->second.owner_core_id;
            result.consumer_bitmap = it->second.consumer_bitmap;
            result.ready_token = it->second.ready_token;
            return result;
        }

        const auto released_it = pod.released_entries.find(key);
        if (released_it != pod.released_entries.end()) {
            result.valid = true;
            result.released = true;
            result.owner_core_id = released_it->second.owner_core_id;
            result.consumer_bitmap = released_it->second.consumer_bitmap;
            result.ready_token = released_it->second.ready_token;
            if (released_it->second.leased_ready) {
                result.ready = true;
                result.state = ServiceState::Ready;
            }
        }
        return result;
    }

    ReleaseResult release(const ReleaseRequest& request) {
        ReleaseResult result{};
        if (!enabled()) return result;
        if (request.pod_id >= pod_states_.size()) return result;

        auto& pod = pod_states_[request.pod_id];
        const Key key{request.window_seq, request.object_key};
        auto it = pod.active_entries.find(key);
        if (it == pod.active_entries.end()) {
            return result;
        }

        if (request.defer_until_ready &&
            it->second.state != ServiceState::Ready) {
            touch_(pod.active_order, key);
            it->second.release_pending = true;
            result.valid = true;
            result.deferred = true;
            stats_.release_deferred_total += 1u;
            return result;
        }

        eraseFromOrder_(pod.active_order, key);
        ReleasedEntry released{};
        released.owner_core_id = it->second.owner_core_id;
        released.consumer_bitmap = it->second.consumer_bitmap;
        released.consumer_count = it->second.consumer_count;
        released.ready_token = it->second.ready_token;
        if (it->second.state == ServiceState::Ready &&
            readyLeaseEnabledForObjectKey_(request.object_key)) {
            released.leased_ready = true;
            released.had_ready_lease = true;
            released.lease_expire_cycle = saturatingAdd_(now_cycle_, cfg_.ready_lease_ttl);
        }
        pod.active_entries.erase(it);
        recordReleased_(pod, key, released);
        result.valid = true;
        result.released = true;
        stats_.released_total += 1u;
        stats_.atlas_obj_release_total += 1u;
        if (released.consumer_count <= 1u) {
            stats_.atlas_obj_private_only_total += 1u;
        }
        return result;
    }

    StatsSnapshot snapshotStats() const {
        StatsSnapshot stats = stats_;
        uint64_t active = 0;
        uint64_t pending_release = 0;
        for (const auto& pod : pod_states_) {
            active += static_cast<uint64_t>(pod.active_entries.size());
            for (const auto& kv : pod.active_entries) {
                if (kv.second.release_pending) {
                    pending_release += 1u;
                }
            }
        }
        stats.active_entries_total = active;
        stats.release_pending_active_total = pending_release;
        return stats;
    }

    void exportStatsToMap(std::map<std::string, uint64_t>& stats,
                          const std::string& prefix) const {
        const auto snap = snapshotStats();
        stats[prefix + "enabled"] = snap.enabled ? 1u : 0u;
        stats[prefix + "owner_form_total"] = snap.owner_form_total;
        stats[prefix + "join_live_total"] = snap.join_live_total;
        stats[prefix + "join_ready_total"] = snap.join_ready_total;
        stats[prefix + "late_join_total"] = snap.late_join_total;
        stats[prefix + "duplicate_join_total"] = snap.duplicate_join_total;
        stats[prefix + "ready_transition_total"] = snap.ready_transition_total;
        stats[prefix + "ready_fanout_total"] = snap.ready_fanout_total;
        stats[prefix + "ready_fanout_consumers_sum"] = snap.ready_fanout_consumers_sum;
        stats[prefix + "ready_fanout_consumers_peak"] = snap.ready_fanout_consumers_peak;
        stats[prefix + "released_total"] = snap.released_total;
        stats[prefix + "release_deferred_total"] = snap.release_deferred_total;
        stats[prefix + "ready_release_total"] = snap.ready_release_total;
        stats[prefix + "ready_lease_hit_total"] = snap.ready_lease_hit_total;
        stats[prefix + "ready_lease_expired_total"] = snap.ready_lease_expired_total;
        stats[prefix + "potential_private_service_elide_total"] =
            snap.potential_private_service_elide_total;
        stats[prefix + "active_entries_total"] = snap.active_entries_total;
        stats[prefix + "release_pending_active_total"] = snap.release_pending_active_total;
        stats[prefix + "atlas_obj_materialize_total"] = snap.atlas_obj_materialize_total;
        stats[prefix + "atlas_obj_publicize_total"] = snap.atlas_obj_publicize_total;
        stats[prefix + "atlas_obj_owner_form_total"] = snap.atlas_obj_owner_form_total;
        stats[prefix + "atlas_obj_ready_total"] = snap.atlas_obj_ready_total;
        stats[prefix + "atlas_obj_release_total"] = snap.atlas_obj_release_total;
        stats[prefix + "atlas_obj_private_only_total"] = snap.atlas_obj_private_only_total;
    }

private:
    struct Key {
        uint32_t window_seq = 0;
        uint64_t object_key = 0;

        bool operator==(const Key& other) const {
            return window_seq == other.window_seq &&
                   object_key == other.object_key;
        }
    };

    struct KeyHash {
        size_t operator()(const Key& key) const {
            const uint64_t mixed =
                (static_cast<uint64_t>(key.window_seq) << 32) ^ key.object_key;
            return static_cast<size_t>(mixed ^ (mixed >> 29));
        }
    };

    struct Entry {
        uint32_t window_seq = 0;
        uint64_t object_key = 0;
        uint32_t owner_core_id = 0;
        uint64_t consumer_bitmap = 0;
        uint32_t consumer_count = 0;
        uint64_t ready_token = 0;
        ServiceState state = ServiceState::Invalid;
        bool release_pending = false;
    };

    struct ReleasedEntry {
        uint32_t owner_core_id = 0;
        uint64_t consumer_bitmap = 0;
        uint32_t consumer_count = 0;
        uint64_t ready_token = 0;
        bool leased_ready = false;
        bool had_ready_lease = false;
        uint64_t lease_expire_cycle = 0;
    };

    struct PodState {
        std::unordered_map<Key, Entry, KeyHash> active_entries;
        std::deque<Key> active_order;
        std::unordered_map<Key, ReleasedEntry, KeyHash> released_entries;
        std::deque<Key> released_order;
    };

    static uint64_t consumerBit_(uint32_t core_id) {
        if (core_id >= 64u) return 0u;
        return (1ull << core_id);
    }

    static void eraseFromOrder_(std::deque<Key>& order, const Key& key) {
        for (auto it = order.begin(); it != order.end(); ++it) {
            if (!(*it == key)) continue;
            order.erase(it);
            return;
        }
    }

    static void touch_(std::deque<Key>& order, const Key& key) {
        if (order.empty()) return;
        if (order.back() == key) return;
        eraseFromOrder_(order, key);
        order.push_back(key);
    }

    void evictIfNeeded_(PodState& pod) {
        if (cfg_.active_entries_per_pod == 0u) return;
        while (pod.active_entries.size() >= static_cast<size_t>(cfg_.active_entries_per_pod) &&
               !pod.active_order.empty()) {
            const Key victim = pod.active_order.front();
            pod.active_order.pop_front();
            pod.active_entries.erase(victim);
        }
    }

    void recordReleased_(PodState& pod, const Key& key, const ReleasedEntry& released) {
        if (cfg_.released_entries_per_pod == 0u) return;
        eraseFromOrder_(pod.released_order, key);
        pod.released_order.push_back(key);
        pod.released_entries[key] = released;
        while (pod.released_entries.size() >
                   static_cast<size_t>(cfg_.released_entries_per_pod) &&
               !pod.released_order.empty()) {
            const Key victim = pod.released_order.front();
            pod.released_order.pop_front();
            pod.released_entries.erase(victim);
        }
    }

    static constexpr uint32_t metadataKindMaskBit_(uint8_t encoded_kind) {
        return (encoded_kind < 32u) ? (1u << encoded_kind) : 0u;
    }

    static constexpr uint8_t encodedKindFromObjectKey_(uint64_t object_key) {
        return static_cast<uint8_t>((object_key >> 56) & 0xffu);
    }

    bool readyLeaseEnabledForObjectKey_(uint64_t object_key) const {
        if (!cfg_.ready_lease_enable || cfg_.ready_lease_ttl == 0u) {
            return false;
        }
        const uint32_t bit = metadataKindMaskBit_(encodedKindFromObjectKey_(object_key));
        if (bit == 0u) return false;
        return (cfg_.ready_lease_kind_mask & bit) != 0u;
    }

    static uint64_t saturatingAdd_(uint64_t lhs, uint64_t rhs) {
        const uint64_t max_value = std::numeric_limits<uint64_t>::max();
        if (max_value - lhs < rhs) return max_value;
        return lhs + rhs;
    }

    Config cfg_{};
    StatsSnapshot stats_{};
    std::vector<PodState> pod_states_{};
    uint64_t next_ready_token_ = 1u;
    uint64_t now_cycle_ = 0u;
};

}} // namespace SST::SnnDL
