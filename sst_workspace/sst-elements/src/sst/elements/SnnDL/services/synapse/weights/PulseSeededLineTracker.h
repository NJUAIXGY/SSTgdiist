// -*- c++ -*-
//
// PulseSeededLineTracker:
// - Minimal PE-scoped window-local tracker for seeded line lead-time diagnostics.
// - Tracks launch/ready/first-demand ordering without changing service semantics.

#pragma once

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace SST { namespace SnnDL {

class PulseSeededLineTracker final {
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

    struct DemandResult {
        bool tracked = false;
        bool first_demand = false;
        bool ready = false;
        uint64_t launch_cycle = 0;
        uint64_t ready_cycle = 0;
        uint8_t source_tag = 0;
        uint8_t aux_tag = 0;
    };

    struct WindowSourceSummary {
        uint64_t tracked_total = 0;
        uint64_t first_demand_total = 0;
        uint64_t undemanded_total = 0;
        uint64_t resident_hit_total = 0;
    };

    struct LineStateSnapshot {
        bool valid = false;
        bool ready = false;
        bool first_demand_seen = false;
        uint64_t resident_hit_total = 0;
        uint8_t source_tag = 0;
        uint8_t aux_tag = 0;
    };

    static void registerLine(uint32_t scope_id,
                             uint32_t window_seq,
                             uint64_t line_addr,
                             uint64_t launch_cycle,
                             uint8_t source_tag = 0,
                             uint8_t aux_tag = 0) {
        std::lock_guard<std::mutex> lock(mutex_());
        LineKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;

        auto& entry = entries_()[key];
        if (!entry.valid) {
            entry.valid = true;
            entry.launch_cycle = launch_cycle;
            entry.source_tag = source_tag;
            entry.aux_tag = aux_tag;
            return;
        }
        entry.launch_cycle = std::min<uint64_t>(entry.launch_cycle, launch_cycle);
        entry.source_tag = source_tag;
        entry.aux_tag = aux_tag;
    }

    static void markReady(uint32_t scope_id,
                          uint32_t window_seq,
                          uint64_t line_addr,
                          uint64_t ready_cycle) {
        std::lock_guard<std::mutex> lock(mutex_());
        LineKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;

        auto it = entries_().find(key);
        if (it == entries_().end()) return;
        it->second.ready = true;
        it->second.ready_cycle = ready_cycle;
    }

    static DemandResult noteDemand(uint32_t scope_id,
                                   uint32_t window_seq,
                                   uint64_t line_addr) {
        std::lock_guard<std::mutex> lock(mutex_());
        DemandResult result{};
        LineKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;

        auto it = entries_().find(key);
        if (it == entries_().end()) return result;
        result.tracked = it->second.valid;
        result.first_demand = !it->second.first_demand_seen;
        result.ready = it->second.ready;
        result.launch_cycle = it->second.launch_cycle;
        result.ready_cycle = it->second.ready_cycle;
        result.source_tag = it->second.source_tag;
        result.aux_tag = it->second.aux_tag;
        it->second.first_demand_seen = true;
        return result;
    }

    static void noteResidentHit(uint32_t scope_id,
                                uint32_t window_seq,
                                uint64_t line_addr) {
        std::lock_guard<std::mutex> lock(mutex_());
        LineKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;

        auto it = entries_().find(key);
        if (it == entries_().end()) return;
        it->second.resident_hit_total += 1u;
    }

    static void eraseLine(uint32_t scope_id,
                          uint32_t window_seq,
                          uint64_t line_addr) {
        std::lock_guard<std::mutex> lock(mutex_());
        LineKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;
        entries_().erase(key);
    }

    static LineStateSnapshot queryLine(uint32_t scope_id,
                                       uint32_t window_seq,
                                       uint64_t line_addr) {
        std::lock_guard<std::mutex> lock(mutex_());
        LineStateSnapshot snapshot{};
        LineKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.line_addr = line_addr;

        const auto it = entries_().find(key);
        if (it == entries_().end()) return snapshot;

        snapshot.valid = it->second.valid;
        snapshot.ready = it->second.ready;
        snapshot.first_demand_seen = it->second.first_demand_seen;
        snapshot.resident_hit_total = it->second.resident_hit_total;
        snapshot.source_tag = it->second.source_tag;
        snapshot.aux_tag = it->second.aux_tag;
        return snapshot;
    }

    static WindowSourceSummary summarizeWindowBySource(uint32_t scope_id,
                                                       uint32_t window_seq,
                                                       uint8_t source_tag) {
        std::lock_guard<std::mutex> lock(mutex_());
        WindowSourceSummary summary{};
        for (const auto& kv : entries_()) {
            if (kv.first.scope_id != scope_id || kv.first.window_seq != window_seq) {
                continue;
            }
            if (kv.second.source_tag != source_tag || !kv.second.valid) {
                continue;
            }
            summary.tracked_total += 1u;
            if (kv.second.first_demand_seen) {
                summary.first_demand_total += 1u;
            } else {
                summary.undemanded_total += 1u;
            }
            summary.resident_hit_total += kv.second.resident_hit_total;
        }
        return summary;
    }

    static WindowSourceSummary summarizeWindowBySourceAndAux(uint32_t scope_id,
                                                             uint32_t window_seq,
                                                             uint8_t source_tag,
                                                             uint8_t aux_tag) {
        std::lock_guard<std::mutex> lock(mutex_());
        WindowSourceSummary summary{};
        for (const auto& kv : entries_()) {
            if (kv.first.scope_id != scope_id || kv.first.window_seq != window_seq) {
                continue;
            }
            if (kv.second.source_tag != source_tag ||
                kv.second.aux_tag != aux_tag ||
                !kv.second.valid) {
                continue;
            }
            summary.tracked_total += 1u;
            if (kv.second.first_demand_seen) {
                summary.first_demand_total += 1u;
            } else {
                summary.undemanded_total += 1u;
            }
            summary.resident_hit_total += kv.second.resident_hit_total;
        }
        return summary;
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
    }

private:
    struct Entry {
        bool valid = false;
        bool ready = false;
        bool first_demand_seen = false;
        uint64_t launch_cycle = 0;
        uint64_t ready_cycle = 0;
        uint8_t source_tag = 0;
        uint8_t aux_tag = 0;
        uint64_t resident_hit_total = 0;
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
};

}} // namespace SST::SnnDL
