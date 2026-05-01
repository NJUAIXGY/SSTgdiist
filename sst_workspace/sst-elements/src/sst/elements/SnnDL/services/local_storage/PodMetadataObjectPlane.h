// -*- c++ -*-
//
// PodMetadataObjectPlane:
// - Minimal pod-shared metadata object tracker for PE-internal Phase-1.
// - Tracks unique metadata objects and consumer overlap before private issue.

#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <limits>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

namespace SST { namespace SnnDL {

class PodMetadataObjectPlane {
public:
    enum class MetadataKind : uint8_t {
        Invalid = 0,
        PreMphfBase = 1,
        PreMphfBand = 2,
        Idx2Row = 3,
        RowIndex = 4,
        RowDescriptor = 5,
    };

    struct Config {
        bool enable = false;
        uint32_t num_pods = 1;
        uint32_t capacity_entries_per_pod = 0;
    };

    struct ObserveRequest {
        uint32_t pod_id = 0;
        uint32_t window_seq = 0;
        MetadataKind kind = MetadataKind::Invalid;
        uint64_t object_id = 0;
        uint32_t core_id = 0;
    };

    struct ObserveResult {
        bool valid = false;
        bool accepted = false;
        bool duplicate_consumer = false;
        uint64_t object_key = 0;
        uint64_t consumer_bitmap = 0;
        uint32_t prior_consumers = 0;
        uint32_t total_consumers = 0;
        uint32_t first_core_id = 0;
    };

    struct StatsSnapshot {
        bool enabled = false;
        uint64_t observe_total = 0;
        uint64_t unique_object_total = 0;
        uint64_t overlap_hit_total = 0;
        uint64_t duplicate_consumer_total = 0;
        uint64_t evict_total = 0;
        uint64_t active_entries_total = 0;
        uint64_t active_entries_peak_total = 0;
    };

    struct KindStats {
        uint64_t observe_total = 0;
        uint64_t unique_object_total = 0;
        uint64_t overlap_hit_total = 0;
        uint64_t duplicate_consumer_total = 0;
        uint64_t evict_total = 0;
        uint64_t active_entries_total = 0;
        uint64_t active_entries_peak_total = 0;
    };

    PodMetadataObjectPlane() = default;
    explicit PodMetadataObjectPlane(const Config& cfg) { configure(cfg); }

    void configure(const Config& cfg) {
        cfg_ = cfg;
        const size_t pods = std::max<size_t>(1u, static_cast<size_t>(cfg_.num_pods));
        pod_states_.assign(pods, PodState{});
        stats_ = StatsSnapshot{};
        stats_.enabled = cfg_.enable;
        observe_by_kind_.fill(0u);
        unique_by_kind_.fill(0u);
        overlap_by_kind_.fill(0u);
        duplicate_by_kind_.fill(0u);
        evict_by_kind_.fill(0u);
        active_by_kind_.fill(0u);
        active_peak_by_kind_.fill(0u);
        current_active_entries_total_ = 0u;
    }

    const Config& config() const { return cfg_; }
    bool enabled() const { return cfg_.enable; }

    ObserveResult observe(const ObserveRequest& request) {
        ObserveResult result{};
        if (!enabled()) return result;
        if (request.kind == MetadataKind::Invalid) return result;
        if (request.pod_id >= pod_states_.size()) return result;

        stats_.observe_total += 1u;
        noteKindCounter_(observe_by_kind_, request.kind);
        auto& pod = pod_states_[request.pod_id];
        const Key key{request.window_seq, request.kind, request.object_id};
        const uint64_t object_key = composeObjectKey(request.kind, request.object_id);

        auto it = pod.entries.find(key);
        if (it == pod.entries.end()) {
            evictIfNeeded_(pod);

            Entry entry{};
            entry.window_seq = request.window_seq;
            entry.kind = request.kind;
            entry.object_id = request.object_id;
            entry.first_core_id = request.core_id;
            pod.order.push_back(key);
            it = pod.entries.emplace(key, entry).first;
            stats_.unique_object_total += 1u;
            noteKindCounter_(unique_by_kind_, request.kind);
            noteActiveInsert_(request.kind);
        } else {
            touch_(pod, key);
        }

        Entry& entry = it->second;
        result.valid = true;
        result.accepted = true;
        result.object_key = object_key;
        result.consumer_bitmap = entry.consumer_bitmap;
        result.prior_consumers = entry.consumer_count;
        result.first_core_id = entry.first_core_id;

        const uint64_t bit = consumerBit_(request.core_id);
        if (bit != 0u && (entry.consumer_bitmap & bit) != 0u) {
            result.duplicate_consumer = true;
            result.total_consumers = entry.consumer_count;
            stats_.duplicate_consumer_total += 1u;
            noteKindCounter_(duplicate_by_kind_, request.kind);
            return result;
        }

        if (entry.consumer_count > 0u) {
            stats_.overlap_hit_total += 1u;
            noteKindCounter_(overlap_by_kind_, request.kind);
        }
        if (bit != 0u) {
            entry.consumer_bitmap |= bit;
            entry.consumer_count += 1u;
            result.consumer_bitmap = entry.consumer_bitmap;
        }
        result.total_consumers = entry.consumer_count;
        return result;
    }

    StatsSnapshot snapshotStats() const {
        StatsSnapshot stats = stats_;
        stats.active_entries_total = current_active_entries_total_;
        return stats;
    }

    KindStats snapshotKindStats(MetadataKind kind) const {
        KindStats stats{};
        const int index = trackedKindIndex_(kind);
        if (index < 0) {
            return stats;
        }

        const size_t slot = static_cast<size_t>(index);
        stats.observe_total = observe_by_kind_[slot];
        stats.unique_object_total = unique_by_kind_[slot];
        stats.overlap_hit_total = overlap_by_kind_[slot];
        stats.duplicate_consumer_total = duplicate_by_kind_[slot];
        stats.evict_total = evict_by_kind_[slot];
        stats.active_entries_total = active_by_kind_[slot];
        stats.active_entries_peak_total = active_peak_by_kind_[slot];
        return stats;
    }

    void exportStatsToMap(std::map<std::string, uint64_t>& stats,
                          const std::string& prefix) const {
        const auto snap = snapshotStats();
        stats[prefix + "enabled"] = snap.enabled ? 1u : 0u;
        stats[prefix + "observe_total"] = snap.observe_total;
        stats[prefix + "unique_object_total"] = snap.unique_object_total;
        stats[prefix + "overlap_hit_total"] = snap.overlap_hit_total;
        stats[prefix + "duplicate_consumer_total"] = snap.duplicate_consumer_total;
        stats[prefix + "evict_total"] = snap.evict_total;
        stats[prefix + "active_entries_total"] = snap.active_entries_total;
        stats[prefix + "active_entries_peak_total"] = snap.active_entries_peak_total;

        exportKindStats_(stats, prefix, MetadataKind::PreMphfBase);
        exportKindStats_(stats, prefix, MetadataKind::PreMphfBand);
        exportKindStats_(stats, prefix, MetadataKind::Idx2Row);
        exportKindStats_(stats, prefix, MetadataKind::RowIndex);
        exportKindStats_(stats, prefix, MetadataKind::RowDescriptor);
    }

    static uint64_t composeObjectKey(MetadataKind kind, uint64_t object_id) {
        return (static_cast<uint64_t>(static_cast<uint8_t>(kind)) << 56) ^
               (object_id & 0x00ffffffffffffffull);
    }

private:
    struct Key {
        uint32_t window_seq = 0;
        MetadataKind kind = MetadataKind::Invalid;
        uint64_t object_id = 0;

        bool operator==(const Key& other) const {
            return window_seq == other.window_seq &&
                   kind == other.kind &&
                   object_id == other.object_id;
        }
    };

    struct KeyHash {
        size_t operator()(const Key& key) const {
            const uint64_t mixed =
                (static_cast<uint64_t>(key.window_seq) << 32) ^
                (static_cast<uint64_t>(static_cast<uint8_t>(key.kind)) << 24) ^
                key.object_id;
            return static_cast<size_t>(mixed ^ (mixed >> 33));
        }
    };

    struct Entry {
        uint32_t window_seq = 0;
        MetadataKind kind = MetadataKind::Invalid;
        uint64_t object_id = 0;
        uint32_t first_core_id = 0;
        uint64_t consumer_bitmap = 0;
        uint32_t consumer_count = 0;
    };

    struct PodState {
        std::unordered_map<Key, Entry, KeyHash> entries;
        std::deque<Key> order;
    };

    static uint64_t consumerBit_(uint32_t core_id) {
        if (core_id >= 64u) return 0u;
        return (1ull << core_id);
    }

    static int trackedKindIndex_(MetadataKind kind) {
        switch (kind) {
            case MetadataKind::PreMphfBase:
                return 0;
            case MetadataKind::PreMphfBand:
                return 1;
            case MetadataKind::Idx2Row:
                return 2;
            case MetadataKind::RowIndex:
                return 3;
            case MetadataKind::RowDescriptor:
                return 4;
            default:
                return -1;
        }
    }

    static const char* kindToken_(MetadataKind kind) {
        switch (kind) {
            case MetadataKind::PreMphfBase:
                return "premphf_base";
            case MetadataKind::PreMphfBand:
                return "premphf_band";
            case MetadataKind::Idx2Row:
                return "idx2row";
            case MetadataKind::RowIndex:
                return "rowindex";
            case MetadataKind::RowDescriptor:
                return "rowdescriptor";
            default:
                return nullptr;
        }
    }

    static void noteKindCounter_(std::array<uint64_t, 5>& counters, MetadataKind kind) {
        const int index = trackedKindIndex_(kind);
        if (index < 0) return;
        counters[static_cast<size_t>(index)] += 1u;
    }

    void noteActiveInsert_(MetadataKind kind) {
        const int index = trackedKindIndex_(kind);
        if (index < 0) return;
        const size_t slot = static_cast<size_t>(index);
        active_by_kind_[slot] += 1u;
        active_peak_by_kind_[slot] = std::max(active_peak_by_kind_[slot], active_by_kind_[slot]);
        current_active_entries_total_ += 1u;
        stats_.active_entries_peak_total =
            std::max(stats_.active_entries_peak_total, current_active_entries_total_);
    }

    void noteActiveErase_(MetadataKind kind) {
        const int index = trackedKindIndex_(kind);
        if (index < 0) return;
        const size_t slot = static_cast<size_t>(index);
        if (active_by_kind_[slot] > 0u) {
            active_by_kind_[slot] -= 1u;
        }
        if (current_active_entries_total_ > 0u) {
            current_active_entries_total_ -= 1u;
        }
    }

    void evictIfNeeded_(PodState& pod) {
        if (cfg_.capacity_entries_per_pod == 0u) return;
        while (pod.entries.size() >= static_cast<size_t>(cfg_.capacity_entries_per_pod) &&
               !pod.order.empty()) {
            const Key victim = pod.order.front();
            pod.order.pop_front();
            auto it = pod.entries.find(victim);
            if (it == pod.entries.end()) continue;
            noteKindCounter_(evict_by_kind_, it->second.kind);
            noteActiveErase_(it->second.kind);
            pod.entries.erase(it);
            stats_.evict_total += 1u;
        }
    }

    void touch_(PodState& pod, const Key& key) {
        if (pod.order.empty()) return;
        if (pod.order.back() == key) return;
        for (auto it = pod.order.begin(); it != pod.order.end(); ++it) {
            if (!(*it == key)) continue;
            pod.order.erase(it);
            pod.order.push_back(key);
            return;
        }
        pod.order.push_back(key);
    }

    void exportKindStats_(std::map<std::string, uint64_t>& stats,
                          const std::string& prefix,
                          MetadataKind kind) const {
        const char* token = kindToken_(kind);
        if (!token) return;
        const auto snap = snapshotKindStats(kind);
        const std::string family_prefix = prefix + token + "_";
        stats[family_prefix + "observe_total"] = snap.observe_total;
        stats[family_prefix + "unique_object_total"] = snap.unique_object_total;
        stats[family_prefix + "overlap_hit_total"] = snap.overlap_hit_total;
        stats[family_prefix + "duplicate_consumer_total"] = snap.duplicate_consumer_total;
        stats[family_prefix + "evict_total"] = snap.evict_total;
        stats[family_prefix + "active_entries_total"] = snap.active_entries_total;
        stats[family_prefix + "active_entries_peak_total"] = snap.active_entries_peak_total;
    }

    Config cfg_{};
    StatsSnapshot stats_{};
    std::array<uint64_t, 5> observe_by_kind_{};
    std::array<uint64_t, 5> unique_by_kind_{};
    std::array<uint64_t, 5> overlap_by_kind_{};
    std::array<uint64_t, 5> duplicate_by_kind_{};
    std::array<uint64_t, 5> evict_by_kind_{};
    std::array<uint64_t, 5> active_by_kind_{};
    std::array<uint64_t, 5> active_peak_by_kind_{};
    uint64_t current_active_entries_total_ = 0u;
    std::vector<PodState> pod_states_{};
};

}} // namespace SST::SnnDL
