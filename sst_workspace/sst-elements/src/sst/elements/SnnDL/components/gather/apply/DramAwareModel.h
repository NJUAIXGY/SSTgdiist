// -*- c++ -*-
// DramAwareModel.h: lightweight DRAM cost model helpers for GAS Apply tuning

#pragma once

#include <cstdint>
#include <string>
#include <algorithm>

namespace SST { namespace SnnDL { namespace gather { namespace apply {

struct DramAwareParams {
    uint32_t line_bytes = 64;
    uint32_t row_bytes = 0;                // 0 = unknown (use row_bytes_guess)
    uint32_t bank_count = 0;               // 0 = derive/disable
    uint32_t read_burst_bytes = 64;        // minimum meaningful burst (bytes)
    uint32_t row_miss_penalty_cycles = 0;  // relative weight of row-miss vs overfetch (heuristic)
    uint64_t overfetch_budget_bytes = 0;   // 0 = unlimited
};

struct WindowAccessSummary {
    uint64_t unique_line_count = 0;   // unique cachelines touched (approx)
    uint64_t covered_line_count = 0;  // span cachelines covered by segments (approx)
    uint64_t payload_bytes = 0;       // sum of upstream sub-read sizes (bytes)
    uint64_t issued_bytes = 0;        // sum of issued segment sizes (bytes, incl holes)
};

class DramAwareModel {
public:
    explicit DramAwareModel(const DramAwareParams& p) : p_(p) {}

    uint32_t lineBytes() const { return (p_.line_bytes == 0) ? 64 : p_.line_bytes; }
    uint32_t readBurstBytes() const { return (p_.read_burst_bytes == 0) ? lineBytes() : p_.read_burst_bytes; }

    // Density in [0,1], based on unique vs covered cachelines.
    double estimateDensity(const WindowAccessSummary& s) const {
        if (s.covered_line_count == 0) return 0.0;
        const double u = static_cast<double>(s.unique_line_count);
        const double c = static_cast<double>(s.covered_line_count);
        double d = u / c;
        if (d < 0.0) d = 0.0;
        if (d > 1.0) d = 1.0;
        return d;
    }

    // Recommend an effective k (gap threshold) cap for this window, in bytes.
    // This does not enforce budget; budget enforcement happens in segment builder.
    uint64_t recommendGapKBytes(uint64_t k_cap_bytes, const WindowAccessSummary& s) const {
        const uint32_t line = lineBytes();
        if (line == 0) return 0;
        if (k_cap_bytes == 0) return 0;

        // Heuristic:
        // - Higher access density means gaps are more likely to be beneficial to absorb (fewer holes).
        // - Higher row-miss penalty (cycles) means we can tolerate larger k to retain row-locality.
        const double density = estimateDensity(s);
        const uint64_t base = static_cast<uint64_t>(std::max<uint32_t>(line, readBurstBytes()));

        const uint64_t dense_term = static_cast<uint64_t>(base * (1.0 + 7.0 * density)); // [1..8]*base
        const uint64_t pen = p_.row_miss_penalty_cycles;
        const uint64_t penalty_scale = 1ull + std::min<uint64_t>(7ull, pen / 50ull);     // 1..8
        const uint64_t k = dense_term * penalty_scale;

        return std::min<uint64_t>(k_cap_bytes, k);
    }

private:
    DramAwareParams p_{};
};

}}}} // namespace SST::SnnDL::gather::apply
