// -*- c++ -*-

#include "services/pe_fabric/PulseAgendaScorer.h"

namespace SST { namespace SnnDL {

PulseAgendaScorer::Result PulseAgendaScorer::evaluate(const Candidate& candidate) const {
    Result result{};

    if (!candidate.same_line) {
        result.reject_reason = RejectReason::MixedLine;
        result.score = kRejectedScore;
        return result;
    }
    if (!candidate.row_safe) {
        result.reject_reason = RejectReason::RowUnsafe;
        result.score = kRejectedScore;
        return result;
    }
    if (!candidate.segment_safe) {
        result.reject_reason = RejectReason::SegmentUnsafe;
        result.score = kRejectedScore;
        return result;
    }
    if (!candidate.retire_span_ok) {
        result.reject_reason = RejectReason::RetireSpan;
        result.score = kRejectedScore;
        return result;
    }
    if (!candidate.head_pressure_ok) {
        result.reject_reason = RejectReason::HeadPressure;
        result.score = kRejectedScore;
        return result;
    }

    result.accepted = true;
    result.reject_reason = RejectReason::None;
    result.score =
        static_cast<int64_t>(candidate.reuse_gain) +
        static_cast<int64_t>(candidate.residency_gain) +
        static_cast<int64_t>(candidate.ingress_relief) -
        static_cast<int64_t>(candidate.head_block_risk) -
        static_cast<int64_t>(candidate.bank_conflict_risk) -
        static_cast<int64_t>(candidate.split_risk);
    return result;
}

}} // namespace SST::SnnDL
