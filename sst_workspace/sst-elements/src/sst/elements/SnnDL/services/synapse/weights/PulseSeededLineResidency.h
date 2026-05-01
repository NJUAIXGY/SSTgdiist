// -*- c++ -*-
//
// PulseSeededLineResidency:
// - Minimal PE-scoped window-local resident line store for metadata-seeded shared lines.
// - Lets later exact demand requests hit a previously seeded line without reissuing memory traffic.

#pragma once

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <utility>
#include <vector>

namespace SST { namespace SnnDL {

class PulseSeededLineResidency final {
public:
    struct LineKey {
        uint32_t scope_id = 0;
        uint32_t window_seq = 0;
        uint64_t line_addr = 0;

        bool operator==(const LineKey& other) const {
            return scope_id == other.scope_id &&
                   window_seq == other.window_seq &&
                   line_addr == other.line_addr;
        }
    };

    struct LookupResult {
        bool hit = false;
        bool first_use = false;
        size_t active_entries = 0;
        std::vector<uint8_t> line_bytes;
    };

    struct ProbeResult {
        bool hit = false;
        size_t active_entries = 0;
    };

    static LookupResult lookupLine(uint32_t scope_id,
                                   uint32_t window_seq,
                                   uint64_t line_addr) {
        std::lock_guard<std::mutex> lock(mutex_());
        LookupResult result{};
        LineKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;

        auto it = entries_().find(key);
        if (it == entries_().end()) return result;
        result.hit = true;
        result.first_use = !it->second.used;
        it->second.used = true;
        result.active_entries = entries_().size();
        result.line_bytes = it->second.line_bytes;
        return result;
    }

    static size_t storeLine(uint32_t scope_id,
                            uint32_t window_seq,
                            uint64_t line_addr,
                            const std::vector<uint8_t>& line_bytes) {
        std::lock_guard<std::mutex> lock(mutex_());
        LineKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;

        auto& entry = entries_()[key];
        entry.line_bytes = line_bytes;
        peak_() = std::max<uint64_t>(peak_(), static_cast<uint64_t>(entries_().size()));
        return entries_().size();
    }

    static void closeWindow(uint32_t scope_id, uint32_t window_seq) {
        std::lock_guard<std::mutex> lock(mutex_());
        if (entries_().empty()) return;
        std::vector<LineKey> erase_keys;
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
        peak_() = 0;
    }

    static ProbeResult probeLine(uint32_t scope_id,
                                 uint32_t window_seq,
                                 uint64_t line_addr) {
        std::lock_guard<std::mutex> lock(mutex_());
        ProbeResult result{};
        result.active_entries = entries_().size();
        LineKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;

        result.hit = (entries_().find(key) != entries_().end());
        return result;
    }

private:
    struct Entry {
        bool used = false;
        std::vector<uint8_t> line_bytes;
    };

    struct LineKeyHash {
        size_t operator()(const LineKey& key) const {
            size_t seed = static_cast<size_t>(key.scope_id);
            seed ^= static_cast<size_t>(key.window_seq) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            seed ^= static_cast<size_t>(key.line_addr) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            return seed;
        }
    };

    static std::unordered_map<LineKey, Entry, LineKeyHash>& entries_() {
        static std::unordered_map<LineKey, Entry, LineKeyHash> entries;
        return entries;
    }

    static std::mutex& mutex_() {
        static std::mutex mutex;
        return mutex;
    }

    static uint64_t& peak_() {
        static uint64_t peak = 0;
        return peak;
    }
};

}} // namespace SST::SnnDL
