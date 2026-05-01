// -*- c++ -*-
//
// PulseFrontierObserveRegistry:
// - Minimal PE-scoped observe-only registry for PULSE frontier overlap studies.
// - Tracks whether top-H frontier lines are seen by multiple cores in the same PE/window.

#pragma once

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace SST { namespace SnnDL {

class PulseFrontierObserveRegistry final {
public:
    struct FrontierKey {
        uint32_t scope_id = 0;
        uint32_t window_seq = 0;
        uint64_t line_addr = 0;

        bool operator==(const FrontierKey& other) const {
            return scope_id == other.scope_id &&
                   window_seq == other.window_seq &&
                   line_addr == other.line_addr;
        }
    };

    struct ObserveResult {
        uint32_t prior_consumers = 0;
        uint32_t consumers_after = 0;
        size_t active_entries = 0;
    };

    static ObserveResult observeLine(uint32_t scope_id,
                                     uint32_t window_seq,
                                     uint64_t line_addr,
                                     uint32_t core_id) {
        std::lock_guard<std::mutex> lock(mutex_());
        FrontierKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;

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
        std::vector<FrontierKey> erase_keys;
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
    struct FrontierEntry {
        uint64_t consumer_bitmap = 0;
        uint32_t consumer_count = 0;
    };

    struct FrontierKeyHash {
        size_t operator()(const FrontierKey& key) const {
            size_t seed = static_cast<size_t>(key.scope_id);
            seed ^= static_cast<size_t>(key.window_seq) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            seed ^= static_cast<size_t>(key.line_addr) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            return seed;
        }
    };

    static std::unordered_map<FrontierKey, FrontierEntry, FrontierKeyHash>& entries_() {
        static std::unordered_map<FrontierKey, FrontierEntry, FrontierKeyHash> entries;
        return entries;
    }

    static std::mutex& mutex_() {
        static std::mutex mutex;
        return mutex;
    }
};

}} // namespace SST::SnnDL
