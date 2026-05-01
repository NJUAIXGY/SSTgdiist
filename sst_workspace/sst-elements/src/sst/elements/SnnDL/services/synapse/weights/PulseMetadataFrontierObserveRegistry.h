// -*- c++ -*-
//
// PulseMetadataFrontierObserveRegistry:
// - Minimal PE-scoped observe-only registry for PULSE metadata-frontier overlap studies.
// - Tracks whether pre-MPHF metadata objects are seen by multiple cores in the same PE/window.

#pragma once

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace SST { namespace SnnDL {

class PulseMetadataFrontierObserveRegistry final {
public:
    enum class MetadataKind : uint8_t {
        PreMphfBase = 0,
        PreMphfBand = 1,
    };

    struct MetadataKey {
        uint32_t scope_id = 0;
        uint32_t window_seq = 0;
        MetadataKind kind = MetadataKind::PreMphfBase;
        uint64_t object_id = 0;

        bool operator==(const MetadataKey& other) const {
            return scope_id == other.scope_id &&
                   window_seq == other.window_seq &&
                   kind == other.kind &&
                   object_id == other.object_id;
        }
    };

    struct ObserveResult {
        uint32_t prior_consumers = 0;
        uint32_t consumers_after = 0;
        size_t active_entries = 0;
    };

    static ObserveResult observeObject(uint32_t scope_id,
                                       uint32_t window_seq,
                                       MetadataKind kind,
                                       uint64_t object_id,
                                       uint32_t core_id) {
        std::lock_guard<std::mutex> lock(mutex_());
        MetadataKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.kind = kind;
        key.object_id = object_id;

        auto& entry = entries_()[key];
        const uint64_t bit = (core_id < 64u) ? (1ull << core_id) : 0ull;
        const bool already_seen =
            (bit != 0ull) ? ((entry.consumer_bitmap & bit) != 0ull) : false;

        ObserveResult result{};
        result.prior_consumers = entry.consumer_count;
        if (!already_seen) {
            if (bit != 0ull) entry.consumer_bitmap |= bit;
            entry.consumer_count += 1u;
        }
        result.consumers_after = entry.consumer_count;
        result.active_entries = entries_().size();
        return result;
    }

    static void closeWindow(uint32_t scope_id, uint32_t window_seq) {
        std::lock_guard<std::mutex> lock(mutex_());
        if (entries_().empty()) return;
        std::vector<MetadataKey> erase_keys;
        erase_keys.reserve(entries_().size());
        for (const auto& kv : entries_()) {
            if (kv.first.scope_id == scope_id && kv.first.window_seq == window_seq) {
                erase_keys.push_back(kv.first);
            }
        }
        for (const auto& key : erase_keys) {
            entries_().erase(key);
        }
    }

    static void resetForTests() {
        std::lock_guard<std::mutex> lock(mutex_());
        entries_().clear();
    }

private:
    struct MetadataEntry {
        uint64_t consumer_bitmap = 0;
        uint32_t consumer_count = 0;
    };

    struct MetadataKeyHash {
        size_t operator()(const MetadataKey& key) const {
            size_t seed = static_cast<size_t>(key.scope_id);
            seed ^= static_cast<size_t>(key.window_seq) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            seed ^= static_cast<size_t>(key.kind) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            seed ^= static_cast<size_t>(key.object_id) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            return seed;
        }
    };

    static std::unordered_map<MetadataKey, MetadataEntry, MetadataKeyHash>& entries_() {
        static std::unordered_map<MetadataKey, MetadataEntry, MetadataKeyHash> entries;
        return entries;
    }

    static std::mutex& mutex_() {
        static std::mutex mutex;
        return mutex;
    }
};

}} // namespace SST::SnnDL
