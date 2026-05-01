// -*- c++ -*-
//
// PulseMetadataLookupRegistry:
// - Minimal PE-scoped coordination registry for shared {pre_global -> (base,len)} lookups.
// - Keeps metadata sharing on the service plane only; exact value issue/retire stays unchanged.

#pragma once

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace SST { namespace SnnDL {

class PulseMetadataLookupRegistry final {
public:
    struct LookupKey {
        uint32_t scope_id = 0;
        uint32_t window_seq = 0;
        uint32_t pre_global = 0;

        bool operator==(const LookupKey& other) const {
            return scope_id == other.scope_id &&
                   window_seq == other.window_seq &&
                   pre_global == other.pre_global;
        }
    };

    struct LookupResult {
        bool hit = false;
        bool owner_fill = false;
        bool shared_hit = false;
        uint32_t base = 0;
        uint32_t len = 0;
        uint32_t owner_core_id = 0;
        uint32_t consumer_count = 0;
        size_t active_entries = 0;
    };

    static LookupResult findPreBase(uint32_t scope_id,
                                    uint32_t window_seq,
                                    uint32_t pre_global,
                                    uint32_t core_id) {
        std::lock_guard<std::mutex> lock(mutex_());
        LookupKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.pre_global = pre_global;

        LookupResult result{};
        auto it = entries_().find(key);
        if (it == entries_().end()) {
            result.active_entries = entries_().size();
            return result;
        }

        Entry& entry = it->second;
        entry.consumer_count += 1u;
        result.hit = true;
        result.owner_fill = false;
        result.shared_hit = true;
        result.base = entry.base;
        result.len = entry.len;
        result.owner_core_id = entry.owner_core_id;
        result.consumer_count = entry.consumer_count;
        result.active_entries = entries_().size();
        if (core_id < 64u) {
            entry.consumer_bitmap |= (1ull << core_id);
        }
        return result;
    }

    static LookupResult publishPreBase(uint32_t scope_id,
                                       uint32_t window_seq,
                                       uint32_t pre_global,
                                       uint32_t base,
                                       uint32_t len,
                                       uint32_t core_id) {
        std::lock_guard<std::mutex> lock(mutex_());
        LookupKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.pre_global = pre_global;

        Entry& entry = entries_()[key];
        if (entry.consumer_count == 0u) {
            entry.base = base;
            entry.len = len;
            entry.owner_core_id = core_id;
        }
        entry.consumer_count += 1u;
        if (core_id < 64u) {
            entry.consumer_bitmap |= (1ull << core_id);
        }

        LookupResult result{};
        result.hit = true;
        result.owner_fill = (entry.consumer_count == 1u);
        result.shared_hit = false;
        result.base = entry.base;
        result.len = entry.len;
        result.owner_core_id = entry.owner_core_id;
        result.consumer_count = entry.consumer_count;
        result.active_entries = entries_().size();
        return result;
    }

    static void closeWindow(uint32_t scope_id, uint32_t window_seq) {
        std::lock_guard<std::mutex> lock(mutex_());
        if (entries_().empty()) {
            return;
        }
        std::vector<LookupKey> erase_keys;
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
    struct Entry {
        uint32_t base = 0;
        uint32_t len = 0;
        uint32_t owner_core_id = 0;
        uint32_t consumer_count = 0;
        uint64_t consumer_bitmap = 0;
    };

    struct LookupKeyHash {
        size_t operator()(const LookupKey& key) const {
            size_t seed = static_cast<size_t>(key.scope_id);
            seed ^= static_cast<size_t>(key.window_seq) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            seed ^= static_cast<size_t>(key.pre_global) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            return seed;
        }
    };

    static std::unordered_map<LookupKey, Entry, LookupKeyHash>& entries_() {
        static std::unordered_map<LookupKey, Entry, LookupKeyHash> entries;
        return entries;
    }

    static std::mutex& mutex_() {
        static std::mutex mutex;
        return mutex;
    }
};

}} // namespace SST::SnnDL
