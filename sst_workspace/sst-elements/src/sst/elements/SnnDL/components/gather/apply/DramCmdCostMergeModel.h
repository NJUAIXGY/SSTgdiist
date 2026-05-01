// -*- c++ -*-
// DramCmdCostMergeModel.h: deterministic DRAM command-cost guided merge guardrails
//
// Purpose:
// - Provide a simple, deterministic rule to decide whether absorbing a hole (gap) is ever
//   worthwhile under a cacheline-oriented DRAM interface.
// - This is an exploration hook for GAS segment building. Default behavior is unchanged
//   unless explicitly enabled via params (see GatherBufferIF).
//
// Model:
// - Treat the benefit of "not splitting" as avoiding one expected row-miss penalty.
// - Treat the cost of absorbing a gap as reading extra cachelines (row-hit service).
// - The resulting threshold is deterministic, derived only from {t_hit, t_miss, line_bytes}.

#pragma once

#include <cstdint>
#include <algorithm>

namespace SST { namespace SnnDL { namespace gather { namespace apply {

struct DramCmdCostMergeModel {
    static uint64_t deriveGapKBytes(uint64_t line_bytes, uint64_t t_row_hit_ns, uint64_t t_row_miss_ns) {
        const uint64_t line = (line_bytes == 0) ? 64ull : line_bytes;
        const uint64_t th = std::max<uint64_t>(1ull, t_row_hit_ns);
        const uint64_t tm = std::max<uint64_t>(th, t_row_miss_ns);
        const uint64_t benefit = (tm > th) ? (tm - th) : 0ull;
        const uint64_t max_extra_lines = benefit / th;
        return max_extra_lines * line;
    }

    static bool allowAbsorbGap(uint64_t gap_bytes, uint64_t line_bytes, uint64_t t_row_hit_ns, uint64_t t_row_miss_ns) {
        if (gap_bytes == 0) return true;
        const uint64_t line = (line_bytes == 0) ? 64ull : line_bytes;
        const uint64_t th = std::max<uint64_t>(1ull, t_row_hit_ns);
        const uint64_t tm = std::max<uint64_t>(th, t_row_miss_ns);
        const uint64_t benefit = (tm > th) ? (tm - th) : 0ull;
        if (benefit == 0) return false;
        const uint64_t extra_lines = (gap_bytes + line - 1ull) / line;
        return (extra_lines * th) <= benefit;
    }
};

}}}} // namespace SST::SnnDL::gather::apply

