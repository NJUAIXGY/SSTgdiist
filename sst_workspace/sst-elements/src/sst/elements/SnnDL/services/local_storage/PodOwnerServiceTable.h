// -*- c++ -*-
//
// PodOwnerServiceTable:
// - Minimal pod-shared owner-first transaction table for PE-internal Phase-1.
// - Allocates one owner per pod/window/object and records exact joins.

#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

#include "services/local_storage/PodMetadataObjectPlane.h"

namespace SST { namespace SnnDL {

class PodOwnerServiceTable {
public:
    enum class RejectReason : uint8_t {
        None = 0,
        Disabled = 1,
        InvalidPod = 2,
        TableFull = 3,
        NotFound = 4,
        JoinTableDisabled = 5,
        DuplicateConsumer = 6,
    };

    struct Config {
        bool enable = false;
        uint32_t num_pods = 1;
        uint32_t owner_entries_per_pod = 0;
        uint32_t join_entries_per_pod = 0;
    };

    struct LookupRequest {
        uint32_t pod_id = 0;
        uint32_t window_seq = 0;
        uint64_t object_key = 0;
        uint32_t core_id = 0;
    };

    struct LookupResult {
        bool valid = false;
        bool allocated_owner = false;
        bool owner_hit = false;
        RejectReason reject_reason = RejectReason::None;
        uint32_t owner_core_id = 0;
        uint64_t transaction_id = 0;
        uint64_t consumer_bitmap = 0;
    };

    struct JoinRequest {
        uint32_t pod_id = 0;
        uint32_t window_seq = 0;
        uint64_t object_key = 0;
        uint32_t consumer_core_id = 0;
    };

    struct JoinResult {
        bool valid = false;
        bool granted = false;
        bool duplicate_consumer = false;
        RejectReason reject_reason = RejectReason::None;
        uint32_t owner_core_id = 0;
        uint64_t transaction_id = 0;
        uint64_t consumer_bitmap = 0;
    };

    struct StatsSnapshot {
        bool enabled = false;
        uint64_t lookup_total = 0;
        uint64_t owner_alloc_total = 0;
        uint64_t owner_hit_total = 0;
        uint64_t owner_reject_total = 0;
        uint64_t join_request_total = 0;
        uint64_t join_grant_total = 0;
        uint64_t join_reject_total = 0;
        uint64_t active_entries_total = 0;
        uint64_t active_entries_peak_total = 0;
    };

    struct KindStats {
        uint64_t owner_alloc_total = 0;
        uint64_t owner_hit_total = 0;
        uint64_t owner_reject_total = 0;
        uint64_t join_request_total = 0;
        uint64_t join_grant_total = 0;
        uint64_t join_reject_total = 0;
        uint64_t active_entries_total = 0;
        uint64_t active_entries_peak_total = 0;
    };

    PodOwnerServiceTable() = default;
    explicit PodOwnerServiceTable(const Config& cfg) { configure(cfg); }

    void configure(const Config& cfg) {
        cfg_ = cfg;
        const size_t pods = std::max<size_t>(1u, static_cast<size_t>(cfg_.num_pods));
        pod_states_.assign(pods, PodState{});
        next_transaction_id_ = 1u;
        stats_ = StatsSnapshot{};
        stats_.enabled = cfg_.enable;
        owner_alloc_by_kind_.fill(0u);
        owner_hit_by_kind_.fill(0u);
        owner_reject_by_kind_.fill(0u);
        join_request_by_kind_.fill(0u);
        join_grant_by_kind_.fill(0u);
        join_reject_by_kind_.fill(0u);
        active_by_kind_.fill(0u);
        active_peak_by_kind_.fill(0u);
        current_active_entries_total_ = 0u;
    }

    const Config& config() const { return cfg_; }
    bool enabled() const { return cfg_.enable; }

    LookupResult lookupOrAllocate(const LookupRequest& request) {
        LookupResult result{};
        stats_.lookup_total += 1u;
        if (!enabled()) {
            stats_.owner_reject_total += 1u;
            result.reject_reason = RejectReason::Disabled;
            return result;
        }
        if (request.pod_id >= pod_states_.size()) {
            stats_.owner_reject_total += 1u;
            result.reject_reason = RejectReason::InvalidPod;
            return result;
        }

        auto& pod = pod_states_[request.pod_id];
        const Key key{request.window_seq, request.object_key};
        const PodMetadataObjectPlane::MetadataKind kind = kindFromObjectKey_(request.object_key);
        auto it = pod.entries.find(key);
        if (it != pod.entries.end()) {
            touch_(pod, key);
            result.valid = true;
            result.owner_hit = true;
            result.owner_core_id = it->second.owner_core_id;
            result.transaction_id = it->second.transaction_id;
            result.consumer_bitmap = it->second.consumer_bitmap;
            stats_.owner_hit_total += 1u;
            noteKindCounter_(owner_hit_by_kind_, kind);
            return result;
        }

        if (cfg_.owner_entries_per_pod != 0u &&
            pod.entries.size() >= static_cast<size_t>(cfg_.owner_entries_per_pod)) {
            stats_.owner_reject_total += 1u;
            noteKindCounter_(owner_reject_by_kind_, kind);
            result.reject_reason = RejectReason::TableFull;
            return result;
        }

        Entry entry{};
        entry.window_seq = request.window_seq;
        entry.object_key = request.object_key;
        entry.owner_core_id = request.core_id;
        entry.transaction_id = next_transaction_id_++;
        entry.consumer_bitmap = consumerBit_(request.core_id);
        entry.consumer_count = (entry.consumer_bitmap != 0u) ? 1u : 0u;
        pod.order.push_back(key);
        it = pod.entries.emplace(key, entry).first;

        result.valid = true;
        result.allocated_owner = true;
        result.owner_core_id = entry.owner_core_id;
        result.transaction_id = entry.transaction_id;
        result.consumer_bitmap = entry.consumer_bitmap;
        stats_.owner_alloc_total += 1u;
        noteKindCounter_(owner_alloc_by_kind_, kind);
        noteActiveInsert_(kind);
        return result;
    }

    JoinResult join(const JoinRequest& request) {
        JoinResult result{};
        stats_.join_request_total += 1u;
        const PodMetadataObjectPlane::MetadataKind kind = kindFromObjectKey_(request.object_key);
        noteKindCounter_(join_request_by_kind_, kind);
        if (!enabled()) {
            stats_.join_reject_total += 1u;
            noteKindCounter_(join_reject_by_kind_, kind);
            result.reject_reason = RejectReason::Disabled;
            return result;
        }
        if (request.pod_id >= pod_states_.size()) {
            stats_.join_reject_total += 1u;
            noteKindCounter_(join_reject_by_kind_, kind);
            result.reject_reason = RejectReason::InvalidPod;
            return result;
        }
        if (cfg_.join_entries_per_pod == 0u) {
            stats_.join_reject_total += 1u;
            noteKindCounter_(join_reject_by_kind_, kind);
            result.reject_reason = RejectReason::JoinTableDisabled;
            return result;
        }

        auto& pod = pod_states_[request.pod_id];
        const Key key{request.window_seq, request.object_key};
        auto it = pod.entries.find(key);
        if (it == pod.entries.end()) {
            stats_.join_reject_total += 1u;
            noteKindCounter_(join_reject_by_kind_, kind);
            result.reject_reason = RejectReason::NotFound;
            return result;
        }

        touch_(pod, key);
        Entry& entry = it->second;
        const uint64_t bit = consumerBit_(request.consumer_core_id);

        result.valid = true;
        result.owner_core_id = entry.owner_core_id;
        result.transaction_id = entry.transaction_id;
        result.consumer_bitmap = entry.consumer_bitmap;

        if (bit != 0u && (entry.consumer_bitmap & bit) != 0u) {
            result.granted = true;
            result.duplicate_consumer = true;
            result.reject_reason = RejectReason::DuplicateConsumer;
            return result;
        }

        const uint32_t max_consumers =
            std::max<uint32_t>(1u, cfg_.join_entries_per_pod + 1u);
        if (entry.consumer_count >= max_consumers) {
            stats_.join_reject_total += 1u;
            noteKindCounter_(join_reject_by_kind_, kind);
            result.reject_reason = RejectReason::TableFull;
            return result;
        }

        if (bit != 0u) {
            entry.consumer_bitmap |= bit;
            entry.consumer_count += 1u;
        }
        result.granted = true;
        result.consumer_bitmap = entry.consumer_bitmap;
        stats_.join_grant_total += 1u;
        noteKindCounter_(join_grant_by_kind_, kind);
        return result;
    }

    StatsSnapshot snapshotStats() const {
        StatsSnapshot stats = stats_;
        stats.active_entries_total = current_active_entries_total_;
        return stats;
    }

    KindStats snapshotKindStats(PodMetadataObjectPlane::MetadataKind kind) const {
        KindStats stats{};
        const int index = trackedKindIndex_(kind);
        if (index < 0) {
            return stats;
        }

        const size_t slot = static_cast<size_t>(index);
        stats.owner_alloc_total = owner_alloc_by_kind_[slot];
        stats.owner_hit_total = owner_hit_by_kind_[slot];
        stats.owner_reject_total = owner_reject_by_kind_[slot];
        stats.join_request_total = join_request_by_kind_[slot];
        stats.join_grant_total = join_grant_by_kind_[slot];
        stats.join_reject_total = join_reject_by_kind_[slot];
        stats.active_entries_total = active_by_kind_[slot];
        stats.active_entries_peak_total = active_peak_by_kind_[slot];
        return stats;
    }

    void exportStatsToMap(std::map<std::string, uint64_t>& stats,
                          const std::string& prefix) const {
        const auto snap = snapshotStats();
        stats[prefix + "enabled"] = snap.enabled ? 1u : 0u;
        stats[prefix + "lookup_total"] = snap.lookup_total;
        stats[prefix + "owner_alloc_total"] = snap.owner_alloc_total;
        stats[prefix + "owner_hit_total"] = snap.owner_hit_total;
        stats[prefix + "owner_reject_total"] = snap.owner_reject_total;
        stats[prefix + "join_request_total"] = snap.join_request_total;
        stats[prefix + "join_grant_total"] = snap.join_grant_total;
        stats[prefix + "join_reject_total"] = snap.join_reject_total;
        stats[prefix + "active_entries_total"] = snap.active_entries_total;
        stats[prefix + "active_entries_peak_total"] = snap.active_entries_peak_total;

        exportKindStats_(stats, prefix, PodMetadataObjectPlane::MetadataKind::PreMphfBase);
        exportKindStats_(stats, prefix, PodMetadataObjectPlane::MetadataKind::PreMphfBand);
        exportKindStats_(stats, prefix, PodMetadataObjectPlane::MetadataKind::Idx2Row);
        exportKindStats_(stats, prefix, PodMetadataObjectPlane::MetadataKind::RowIndex);
        exportKindStats_(stats, prefix, PodMetadataObjectPlane::MetadataKind::RowDescriptor);
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
        uint64_t transaction_id = 0;
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

    static int trackedKindIndex_(PodMetadataObjectPlane::MetadataKind kind) {
        switch (kind) {
            case PodMetadataObjectPlane::MetadataKind::PreMphfBase:
                return 0;
            case PodMetadataObjectPlane::MetadataKind::PreMphfBand:
                return 1;
            case PodMetadataObjectPlane::MetadataKind::Idx2Row:
                return 2;
            case PodMetadataObjectPlane::MetadataKind::RowIndex:
                return 3;
            case PodMetadataObjectPlane::MetadataKind::RowDescriptor:
                return 4;
            default:
                return -1;
        }
    }

    static const char* kindToken_(PodMetadataObjectPlane::MetadataKind kind) {
        switch (kind) {
            case PodMetadataObjectPlane::MetadataKind::PreMphfBase:
                return "premphf_base";
            case PodMetadataObjectPlane::MetadataKind::PreMphfBand:
                return "premphf_band";
            case PodMetadataObjectPlane::MetadataKind::Idx2Row:
                return "idx2row";
            case PodMetadataObjectPlane::MetadataKind::RowIndex:
                return "rowindex";
            case PodMetadataObjectPlane::MetadataKind::RowDescriptor:
                return "rowdescriptor";
            default:
                return nullptr;
        }
    }

    static PodMetadataObjectPlane::MetadataKind kindFromObjectKey_(uint64_t object_key) {
        const uint8_t raw = static_cast<uint8_t>((object_key >> 56) & 0xffu);
        switch (raw) {
            case 1u:
                return PodMetadataObjectPlane::MetadataKind::PreMphfBase;
            case 2u:
                return PodMetadataObjectPlane::MetadataKind::PreMphfBand;
            case 3u:
                return PodMetadataObjectPlane::MetadataKind::Idx2Row;
            case 4u:
                return PodMetadataObjectPlane::MetadataKind::RowIndex;
            case 5u:
                return PodMetadataObjectPlane::MetadataKind::RowDescriptor;
            default:
                return PodMetadataObjectPlane::MetadataKind::Invalid;
        }
    }

    static void noteKindCounter_(std::array<uint64_t, 5>& counters,
                                 PodMetadataObjectPlane::MetadataKind kind) {
        const int index = trackedKindIndex_(kind);
        if (index < 0) return;
        counters[static_cast<size_t>(index)] += 1u;
    }

    void noteActiveInsert_(PodMetadataObjectPlane::MetadataKind kind) {
        current_active_entries_total_ += 1u;
        stats_.active_entries_peak_total =
            std::max(stats_.active_entries_peak_total, current_active_entries_total_);
        const int index = trackedKindIndex_(kind);
        if (index < 0) return;
        const size_t slot = static_cast<size_t>(index);
        active_by_kind_[slot] += 1u;
        active_peak_by_kind_[slot] = std::max(active_peak_by_kind_[slot], active_by_kind_[slot]);
    }

    static void touch_(PodState& pod, const Key& key) {
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
                          PodMetadataObjectPlane::MetadataKind kind) const {
        const char* token = kindToken_(kind);
        if (!token) return;
        const auto snap = snapshotKindStats(kind);
        const std::string family_prefix = prefix + token + "_";
        stats[family_prefix + "owner_alloc_total"] = snap.owner_alloc_total;
        stats[family_prefix + "owner_hit_total"] = snap.owner_hit_total;
        stats[family_prefix + "owner_reject_total"] = snap.owner_reject_total;
        stats[family_prefix + "join_request_total"] = snap.join_request_total;
        stats[family_prefix + "join_grant_total"] = snap.join_grant_total;
        stats[family_prefix + "join_reject_total"] = snap.join_reject_total;
        stats[family_prefix + "active_entries_total"] = snap.active_entries_total;
        stats[family_prefix + "active_entries_peak_total"] = snap.active_entries_peak_total;
    }

    Config cfg_{};
    StatsSnapshot stats_{};
    std::array<uint64_t, 5> owner_alloc_by_kind_{};
    std::array<uint64_t, 5> owner_hit_by_kind_{};
    std::array<uint64_t, 5> owner_reject_by_kind_{};
    std::array<uint64_t, 5> join_request_by_kind_{};
    std::array<uint64_t, 5> join_grant_by_kind_{};
    std::array<uint64_t, 5> join_reject_by_kind_{};
    std::array<uint64_t, 5> active_by_kind_{};
    std::array<uint64_t, 5> active_peak_by_kind_{};
    std::vector<PodState> pod_states_{};
    uint64_t current_active_entries_total_ = 0u;
    uint64_t next_transaction_id_ = 1u;
};

}} // namespace SST::SnnDL
