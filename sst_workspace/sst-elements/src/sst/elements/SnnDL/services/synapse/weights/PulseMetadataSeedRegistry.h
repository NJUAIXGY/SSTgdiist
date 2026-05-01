// -*- c++ -*-
//
// PulseMetadataSeedRegistry:
// - Minimal PE-scoped coordination registry for PULSE metadata-seeding studies.
// - Promotes a shared pre-base object into a single seeded line prefetch opportunity.

#pragma once

#include <cstddef>
#include <cstdint>
#include <algorithm>
#include <limits>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace SST { namespace SnnDL {

class PulseMetadataSeedRegistry final {
public:
    struct BaseKey {
        uint32_t scope_id = 0;
        uint32_t window_seq = 0;
        uint32_t pre_base = 0;

        bool operator==(const BaseKey& other) const {
            return scope_id == other.scope_id &&
                   window_seq == other.window_seq &&
                   pre_base == other.pre_base;
        }
    };

    struct RegisterResult {
        uint32_t prior_consumers = 0;
        uint32_t consumers_after = 0;
        bool trigger_seed = false;
        uint64_t selected_line_addr = 0;
        size_t active_entries = 0;
    };

    struct BandKey {
        uint32_t scope_id = 0;
        uint32_t window_seq = 0;
        uint64_t band_id = 0;

        bool operator==(const BandKey& other) const {
            return scope_id == other.scope_id &&
                   window_seq == other.window_seq &&
                   band_id == other.band_id;
        }
    };

    struct BandRegisterResult {
        uint32_t prior_consumers = 0;
        uint32_t consumers_after = 0;
        bool trigger_seed = false;
        std::vector<uint64_t> selected_line_addrs;
        size_t active_entries = 0;
    };

    struct BandProbeResult {
        bool valid = false;
        bool seed_triggered = false;
        uint32_t consumer_count = 0;
        std::vector<uint64_t> selected_line_addrs;
    };

    struct GatherBandLine {
        uint64_t line_addr = 0;
        uint32_t first_touch_rank = 0;
    };

    struct GatherBandInput {
        uint64_t band_id = 0;
        uint32_t min_touch_rank = 0;
        std::vector<GatherBandLine> selected_lines;
    };

    struct GatherBarrierReplayBand {
        uint64_t band_id = 0;
        uint32_t min_touch_rank = 0;
        uint32_t consumers = 0;
        std::vector<uint64_t> selected_line_addrs;
    };

    struct GatherBarrierResult {
        uint32_t arrived_cores = 0;
        bool barrier_satisfied = false;
        bool finalized_now = false;
        size_t active_windows = 0;
        std::vector<GatherBarrierReplayBand> replay_bands;
    };

    static RegisterResult registerBaseCandidate(uint32_t scope_id,
                                                uint32_t window_seq,
                                                uint32_t pre_base,
                                                uint64_t line_addr,
                                                uint64_t line_size_bytes,
                                                uint32_t core_id) {
        std::lock_guard<std::mutex> lock(mutex_());
        BaseKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.pre_base = pre_base;

        const uint64_t align_bytes =
            (line_size_bytes >= static_cast<uint64_t>(sizeof(float)))
                ? line_size_bytes
                : static_cast<uint64_t>(sizeof(float));
        const uint64_t aligned_line_addr = (line_addr / align_bytes) * align_bytes;

        auto& entry = entries_()[key];
        if (entry.consumer_count == 0u) {
            entry.seed_line_addr = aligned_line_addr;
        } else {
            entry.seed_line_addr = std::min<uint64_t>(entry.seed_line_addr, aligned_line_addr);
        }

        const uint64_t bit = (core_id < 64u) ? (1ull << core_id) : 0ull;
        const bool already_seen =
            (bit != 0ull) ? ((entry.consumer_bitmap & bit) != 0ull) : false;

        RegisterResult result{};
        result.prior_consumers = entry.consumer_count;
        if (!already_seen) {
            if (bit != 0ull) entry.consumer_bitmap |= bit;
            entry.consumer_count += 1u;
        }
        if (!entry.seed_triggered && entry.consumer_count >= 2u) {
            entry.seed_triggered = true;
            result.trigger_seed = true;
        }
        result.consumers_after = entry.consumer_count;
        result.selected_line_addr = entry.seed_line_addr;
        result.active_entries = entries_().size();
        return result;
    }

    static BandRegisterResult registerBandCandidate(uint32_t scope_id,
                                                    uint32_t window_seq,
                                                    uint64_t band_id,
                                                    uint64_t line_addr,
                                                    uint64_t line_size_bytes,
                                                    uint32_t core_id,
                                                    uint32_t max_lines) {
        std::lock_guard<std::mutex> lock(mutex_());
        BandKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.band_id = band_id;

        const uint64_t align_bytes =
            (line_size_bytes >= static_cast<uint64_t>(sizeof(float)))
                ? line_size_bytes
                : static_cast<uint64_t>(sizeof(float));
        const uint64_t aligned_line_addr = (line_addr / align_bytes) * align_bytes;
        const size_t cap = std::max<size_t>(1u, static_cast<size_t>(max_lines));

        auto& entry = band_entries_()[key];
        const auto existing = std::find(
            entry.selected_line_addrs.begin(),
            entry.selected_line_addrs.end(),
            aligned_line_addr);
        if (existing == entry.selected_line_addrs.end() &&
            entry.selected_line_addrs.size() < cap) {
            entry.selected_line_addrs.push_back(aligned_line_addr);
        }

        const uint64_t bit = (core_id < 64u) ? (1ull << core_id) : 0ull;
        const bool already_seen =
            (bit != 0ull) ? ((entry.consumer_bitmap & bit) != 0ull) : false;

        BandRegisterResult result{};
        result.prior_consumers = entry.consumer_count;
        if (!already_seen) {
            if (bit != 0ull) entry.consumer_bitmap |= bit;
            entry.consumer_count += 1u;
        }
        if (!entry.seed_triggered && entry.consumer_count >= 2u) {
            entry.seed_triggered = true;
            result.trigger_seed = true;
        }
        result.consumers_after = entry.consumer_count;
        result.selected_line_addrs = entry.selected_line_addrs;
        result.active_entries = band_entries_().size();
        return result;
    }

    static BandRegisterResult registerGatherBandCandidate(
        uint32_t scope_id,
        uint32_t window_seq,
        uint64_t band_id,
        const std::vector<uint64_t>& selected_line_addrs,
        uint32_t core_id,
        uint32_t max_lines,
        uint32_t min_consumers = 2u) {
        std::lock_guard<std::mutex> lock(mutex_());
        BandKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.band_id = band_id;

        const size_t cap = std::max<size_t>(1u, static_cast<size_t>(max_lines));
        auto& entry = band_entries_()[key];
        for (uint64_t line_addr : selected_line_addrs) {
            const auto existing = std::find(
                entry.selected_line_addrs.begin(),
                entry.selected_line_addrs.end(),
                line_addr);
            if (existing != entry.selected_line_addrs.end()) continue;
            if (entry.selected_line_addrs.size() >= cap) break;
            entry.selected_line_addrs.push_back(line_addr);
        }

        const uint64_t bit = (core_id < 64u) ? (1ull << core_id) : 0ull;
        const bool already_seen =
            (bit != 0ull) ? ((entry.consumer_bitmap & bit) != 0ull) : false;

        const uint32_t consumer_threshold = std::max<uint32_t>(2u, min_consumers);
        BandRegisterResult result{};
        result.prior_consumers = entry.consumer_count;
        if (!already_seen) {
            if (bit != 0ull) entry.consumer_bitmap |= bit;
            entry.consumer_count += 1u;
        }
        if (!entry.seed_triggered && entry.consumer_count >= consumer_threshold) {
            entry.seed_triggered = true;
            result.trigger_seed = true;
        }
        result.consumers_after = entry.consumer_count;
        result.selected_line_addrs = entry.selected_line_addrs;
        result.active_entries = band_entries_().size();
        return result;
    }

    static BandProbeResult probeGatherBand(uint32_t scope_id,
                                           uint32_t window_seq,
                                           uint64_t band_id) {
        std::lock_guard<std::mutex> lock(mutex_());
        BandKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;
        key.band_id = band_id;

        BandProbeResult result{};
        const auto it = band_entries_().find(key);
        if (it == band_entries_().end()) {
            return result;
        }

        result.valid = true;
        result.seed_triggered = it->second.seed_triggered;
        result.consumer_count = it->second.consumer_count;
        result.selected_line_addrs = it->second.selected_line_addrs;
        return result;
    }

    static GatherBarrierResult registerGatherBarrierArrival(
        uint32_t scope_id,
        uint32_t window_seq,
        uint32_t core_id,
        uint32_t total_cores,
        const std::vector<GatherBandInput>& gathered_bands,
        uint32_t max_lines,
        uint32_t min_consumers = 2u) {
        std::lock_guard<std::mutex> lock(mutex_());

        WindowKey key{};
        key.scope_id = scope_id;
        key.window_seq = window_seq;

        const uint64_t bit = (core_id < 64u) ? (1ull << core_id) : 0ull;
        const uint32_t expected_cores = std::max<uint32_t>(1u, total_cores);
        const uint32_t consumer_threshold = std::max<uint32_t>(2u, min_consumers);
        const size_t line_cap = std::max<size_t>(1u, static_cast<size_t>(max_lines));

        auto& window = gather_barrier_windows_()[key];
        const bool already_arrived =
            (bit != 0ull) ? ((window.arrived_core_bitmap & bit) != 0ull) : false;
        if (!already_arrived) {
            if (bit != 0ull) window.arrived_core_bitmap |= bit;
            window.arrived_core_count += 1u;
        }

        for (const auto& band : gathered_bands) {
            auto& entry = window.band_entries[band.band_id];
            entry.min_touch_rank = std::min<uint32_t>(
                entry.min_touch_rank,
                band.min_touch_rank);

            const bool already_seen_band =
                (bit != 0ull) ? ((entry.consumer_bitmap & bit) != 0ull) : false;
            if (!already_seen_band) {
                if (bit != 0ull) entry.consumer_bitmap |= bit;
                entry.consumer_count += 1u;
            }

            for (const auto& line : band.selected_lines) {
                auto it = entry.line_touch_ranks.find(line.line_addr);
                if (it == entry.line_touch_ranks.end()) {
                    entry.line_touch_ranks.emplace(line.line_addr, line.first_touch_rank);
                    continue;
                }
                it->second = std::min<uint32_t>(it->second, line.first_touch_rank);
            }
        }

        GatherBarrierResult result{};
        result.arrived_cores = window.arrived_core_count;
        result.barrier_satisfied = (window.arrived_core_count >= expected_cores);
        result.active_windows = gather_barrier_windows_().size();
        if (!result.barrier_satisfied || window.finalized) {
            return result;
        }

        window.finalized = true;
        result.finalized_now = true;
        result.replay_bands.reserve(window.band_entries.size());
        for (const auto& kv : window.band_entries) {
            const auto& entry = kv.second;
            if (entry.consumer_count < consumer_threshold) continue;

            std::vector<GatherBandLine> ordered_lines;
            ordered_lines.reserve(entry.line_touch_ranks.size());
            for (const auto& line_kv : entry.line_touch_ranks) {
                GatherBandLine line{};
                line.line_addr = line_kv.first;
                line.first_touch_rank = line_kv.second;
                ordered_lines.push_back(line);
            }
            std::sort(
                ordered_lines.begin(),
                ordered_lines.end(),
                [](const GatherBandLine& lhs, const GatherBandLine& rhs) {
                    if (lhs.first_touch_rank != rhs.first_touch_rank) {
                        return lhs.first_touch_rank < rhs.first_touch_rank;
                    }
                    return lhs.line_addr < rhs.line_addr;
                });
            if (ordered_lines.size() > line_cap) {
                ordered_lines.resize(line_cap);
            }

            GatherBarrierReplayBand replay{};
            replay.band_id = kv.first;
            replay.min_touch_rank = entry.min_touch_rank;
            replay.consumers = entry.consumer_count;
            replay.selected_line_addrs.reserve(ordered_lines.size());
            for (const auto& line : ordered_lines) {
                replay.selected_line_addrs.push_back(line.line_addr);
            }
            result.replay_bands.push_back(std::move(replay));
        }

        std::sort(
            result.replay_bands.begin(),
            result.replay_bands.end(),
            [](const GatherBarrierReplayBand& lhs, const GatherBarrierReplayBand& rhs) {
                if (lhs.min_touch_rank != rhs.min_touch_rank) {
                    return lhs.min_touch_rank < rhs.min_touch_rank;
                }
                return lhs.band_id < rhs.band_id;
            });
        return result;
    }

    static void closeWindow(uint32_t scope_id, uint32_t window_seq) {
        std::lock_guard<std::mutex> lock(mutex_());
        if (!entries_().empty()) {
            std::vector<BaseKey> erase_keys;
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
        if (!band_entries_().empty()) {
            std::vector<BandKey> erase_band_keys;
            erase_band_keys.reserve(band_entries_().size());
            for (const auto& kv : band_entries_()) {
                if (kv.first.scope_id == scope_id && kv.first.window_seq == window_seq) {
                    erase_band_keys.push_back(kv.first);
                }
            }
            for (const auto& key : erase_band_keys) {
                band_entries_().erase(key);
            }
        }
        if (!gather_barrier_windows_().empty()) {
            std::vector<WindowKey> erase_window_keys;
            erase_window_keys.reserve(gather_barrier_windows_().size());
            for (const auto& kv : gather_barrier_windows_()) {
                if (kv.first.scope_id == scope_id && kv.first.window_seq == window_seq) {
                    erase_window_keys.push_back(kv.first);
                }
            }
            for (const auto& key : erase_window_keys) {
                gather_barrier_windows_().erase(key);
            }
        }
    }

    static void resetForTests() {
        std::lock_guard<std::mutex> lock(mutex_());
        entries_().clear();
        band_entries_().clear();
        gather_barrier_windows_().clear();
    }

private:
    struct Entry {
        uint64_t consumer_bitmap = 0;
        uint32_t consumer_count = 0;
        bool seed_triggered = false;
        uint64_t seed_line_addr = 0;
    };

    struct BandEntry {
        uint64_t consumer_bitmap = 0;
        uint32_t consumer_count = 0;
        bool seed_triggered = false;
        std::vector<uint64_t> selected_line_addrs;
    };

    struct WindowKey {
        uint32_t scope_id = 0;
        uint32_t window_seq = 0;

        bool operator==(const WindowKey& other) const {
            return scope_id == other.scope_id &&
                   window_seq == other.window_seq;
        }
    };

    struct GatherBarrierBandEntry {
        uint64_t consumer_bitmap = 0;
        uint32_t consumer_count = 0;
        uint32_t min_touch_rank = std::numeric_limits<uint32_t>::max();
        std::unordered_map<uint64_t, uint32_t> line_touch_ranks;
    };

    struct GatherBarrierWindowEntry {
        uint64_t arrived_core_bitmap = 0;
        uint32_t arrived_core_count = 0;
        bool finalized = false;
        std::unordered_map<uint64_t, GatherBarrierBandEntry> band_entries;
    };

    struct BaseKeyHash {
        size_t operator()(const BaseKey& key) const {
            size_t seed = static_cast<size_t>(key.scope_id);
            seed ^= static_cast<size_t>(key.window_seq) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            seed ^= static_cast<size_t>(key.pre_base) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            return seed;
        }
    };

    static std::unordered_map<BaseKey, Entry, BaseKeyHash>& entries_() {
        static std::unordered_map<BaseKey, Entry, BaseKeyHash> entries;
        return entries;
    }

    struct BandKeyHash {
        size_t operator()(const BandKey& key) const {
            size_t seed = static_cast<size_t>(key.scope_id);
            seed ^= static_cast<size_t>(key.window_seq) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            seed ^= static_cast<size_t>(key.band_id) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            return seed;
        }
    };

    static std::unordered_map<BandKey, BandEntry, BandKeyHash>& band_entries_() {
        static std::unordered_map<BandKey, BandEntry, BandKeyHash> entries;
        return entries;
    }

    struct WindowKeyHash {
        size_t operator()(const WindowKey& key) const {
            size_t seed = static_cast<size_t>(key.scope_id);
            seed ^= static_cast<size_t>(key.window_seq) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            return seed;
        }
    };

    static std::unordered_map<WindowKey, GatherBarrierWindowEntry, WindowKeyHash>&
    gather_barrier_windows_() {
        static std::unordered_map<WindowKey, GatherBarrierWindowEntry, WindowKeyHash> entries;
        return entries;
    }

    static std::mutex& mutex_() {
        static std::mutex mutex;
        return mutex;
    }
};

}} // namespace SST::SnnDL
