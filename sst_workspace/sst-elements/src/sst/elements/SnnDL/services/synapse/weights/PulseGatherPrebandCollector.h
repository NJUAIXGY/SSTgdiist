// -*- c++ -*-
//
// PulseGatherPrebandCollector:
// - Minimal per-core/window gather-time collector for PULSE-MFB gather-preband.
// - Tracks earliest touch rank per band and per aligned line for deterministic replay.

#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <vector>

namespace SST { namespace SnnDL {

class PulseGatherPrebandCollector final {
public:
    struct ReplayLine {
        uint64_t line_addr = 0;
        uint32_t first_touch_rank = 0;
    };

    struct ReplayBand {
        uint64_t band_id = 0;
        uint32_t min_touch_rank = 0;
        std::vector<ReplayLine> selected_lines;
        std::vector<uint64_t> selected_line_addrs;
    };

    void reset() { bands_.clear(); }

    bool empty() const { return bands_.empty(); }

    void noteLine(uint64_t band_id,
                  uint64_t line_addr,
                  uint64_t line_size_bytes,
                  uint32_t touch_rank) {
        const uint64_t align_bytes = std::max<uint64_t>(
            line_size_bytes, static_cast<uint64_t>(sizeof(float)));
        const uint64_t aligned_line_addr = (line_addr / align_bytes) * align_bytes;

        auto& band = bands_[band_id];
        band.min_touch_rank = std::min<uint32_t>(band.min_touch_rank, touch_rank);

        auto line_it = std::find_if(
            band.lines.begin(),
            band.lines.end(),
            [&](const LineEntry& entry) { return entry.line_addr == aligned_line_addr; });
        if (line_it == band.lines.end()) {
            LineEntry entry{};
            entry.line_addr = aligned_line_addr;
            entry.first_touch_rank = touch_rank;
            band.lines.push_back(entry);
            return;
        }
        line_it->first_touch_rank = std::min<uint32_t>(
            line_it->first_touch_rank, touch_rank);
    }

    std::vector<ReplayBand> collect(uint32_t top_bands,
                                    uint32_t lines_per_band) const {
        const size_t band_cap = std::max<size_t>(1u, static_cast<size_t>(top_bands));
        const size_t line_cap = std::max<size_t>(1u, static_cast<size_t>(lines_per_band));

        std::vector<BandPair> ordered_bands;
        ordered_bands.reserve(bands_.size());
        for (const auto& kv : bands_) {
            ordered_bands.push_back(BandPair{kv.first, kv.second});
        }
        std::sort(
            ordered_bands.begin(),
            ordered_bands.end(),
            [](const BandPair& lhs, const BandPair& rhs) {
                if (lhs.entry.min_touch_rank != rhs.entry.min_touch_rank) {
                    return lhs.entry.min_touch_rank < rhs.entry.min_touch_rank;
                }
                return lhs.band_id < rhs.band_id;
            });
        if (ordered_bands.size() > band_cap) {
            ordered_bands.resize(band_cap);
        }

        std::vector<ReplayBand> replay;
        replay.reserve(ordered_bands.size());
        for (const auto& band_pair : ordered_bands) {
            std::vector<LineEntry> lines = band_pair.entry.lines;
            std::sort(
                lines.begin(),
                lines.end(),
                [](const LineEntry& lhs, const LineEntry& rhs) {
                    if (lhs.first_touch_rank != rhs.first_touch_rank) {
                        return lhs.first_touch_rank < rhs.first_touch_rank;
                    }
                    return lhs.line_addr < rhs.line_addr;
                });
            if (lines.size() > line_cap) {
                lines.resize(line_cap);
            }

            ReplayBand band{};
            band.band_id = band_pair.band_id;
            band.min_touch_rank = band_pair.entry.min_touch_rank;
            band.selected_lines.reserve(lines.size());
            band.selected_line_addrs.reserve(lines.size());
            for (const auto& line : lines) {
                ReplayLine replay_line{};
                replay_line.line_addr = line.line_addr;
                replay_line.first_touch_rank = line.first_touch_rank;
                band.selected_lines.push_back(replay_line);
                band.selected_line_addrs.push_back(line.line_addr);
            }
            replay.push_back(std::move(band));
        }
        return replay;
    }

private:
    struct LineEntry {
        uint64_t line_addr = 0;
        uint32_t first_touch_rank = std::numeric_limits<uint32_t>::max();
    };

    struct BandEntry {
        uint32_t min_touch_rank = std::numeric_limits<uint32_t>::max();
        std::vector<LineEntry> lines;
    };

    struct BandPair {
        uint64_t band_id = 0;
        BandEntry entry{};
    };

    // std::map keeps the collector deterministic without relying on unordered
    // hash table bucket invariants inside long-running optimized simulations.
    std::map<uint64_t, BandEntry> bands_;
};

}} // namespace SST::SnnDL
