// -*- c++ -*-
//
// Observe-only agenda scorer for PULSE Phase 1.

#pragma once

#include <cstdint>
#include <limits>

namespace SST { namespace SnnDL {

class PulseAgendaScorer {
public:
    enum class RejectReason : uint8_t {
        None = 0,
        MixedLine = 1,
        RowUnsafe = 2,
        SegmentUnsafe = 3,
        RetireSpan = 4,
        HeadPressure = 5,
    };

    struct Candidate {
        bool same_line = true;
        bool row_safe = true;
        bool segment_safe = true;
        bool retire_span_ok = true;
        bool head_pressure_ok = true;
        uint32_t reuse_gain = 0;
        uint32_t residency_gain = 0;
        uint32_t ingress_relief = 0;
        uint32_t head_block_risk = 0;
        uint32_t bank_conflict_risk = 0;
        uint32_t split_risk = 0;
    };

    struct Result {
        bool accepted = false;
        int64_t score = std::numeric_limits<int64_t>::min();
        RejectReason reject_reason = RejectReason::None;
    };

    static constexpr int64_t kRejectedScore = std::numeric_limits<int64_t>::min();

    Result evaluate(const Candidate& candidate) const;
};

}} // namespace SST::SnnDL
