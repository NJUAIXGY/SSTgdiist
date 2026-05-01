#include <cassert>
#include <cstdint>
#include <limits>

#include "services/pe_fabric/PulseAgendaScorer.h"

using SST::SnnDL::PulseAgendaScorer;

namespace {

void test_gate_failure_rejects_candidate() {
    PulseAgendaScorer scorer;
    PulseAgendaScorer::Candidate candidate{};
    candidate.same_line = false;
    candidate.row_safe = true;
    candidate.segment_safe = true;
    candidate.retire_span_ok = true;
    candidate.head_pressure_ok = true;
    candidate.reuse_gain = 4;
    candidate.residency_gain = 2;
    candidate.ingress_relief = 1;

    const auto result = scorer.evaluate(candidate);
    assert(!result.accepted);
    assert(result.score == PulseAgendaScorer::kRejectedScore);
    assert(result.reject_reason == PulseAgendaScorer::RejectReason::MixedLine);
}

void test_better_candidate_scores_higher() {
    PulseAgendaScorer scorer;

    PulseAgendaScorer::Candidate base{};
    base.same_line = true;
    base.row_safe = true;
    base.segment_safe = true;
    base.retire_span_ok = true;
    base.head_pressure_ok = true;
    base.reuse_gain = 2;
    base.residency_gain = 1;
    base.ingress_relief = 0;
    base.head_block_risk = 3;
    base.bank_conflict_risk = 1;
    base.split_risk = 1;

    PulseAgendaScorer::Candidate better = base;
    better.reuse_gain = 6;
    better.head_block_risk = 1;

    const auto base_result = scorer.evaluate(base);
    const auto better_result = scorer.evaluate(better);
    assert(base_result.accepted);
    assert(better_result.accepted);
    assert(better_result.score > base_result.score);
    assert(base_result.reject_reason == PulseAgendaScorer::RejectReason::None);
    assert(better_result.reject_reason == PulseAgendaScorer::RejectReason::None);
}

} // namespace

int main() {
    test_gate_failure_rejects_candidate();
    test_better_candidate_scores_higher();
    return 0;
}
