#include <cassert>
#include <vector>

#include "components/multicore/GlobalStepDrainDecision.h"

using SST::SnnDL::GlobalStepDrainCoreState;
using SST::SnnDL::GlobalStepDrainDecision;
using SST::SnnDL::GlobalStepDrainInputs;

namespace {

void test_bg_only_core_blocks_pe_done_until_stage_progress_completes() {
    GlobalStepDrainInputs in{};
    in.injected = true;
    in.noc_idle = true;
    in.stage_arrays_ready = true;
    in.cores = {
        GlobalStepDrainCoreState{5, false},
        GlobalStepDrainCoreState{5, false},
        GlobalStepDrainCoreState{1, false},
        GlobalStepDrainCoreState{1, false},
    };

    const GlobalStepDrainDecision d = SST::SnnDL::evaluateGlobalStepDrainDecision(in);
    assert(d.uses_stage_events);
    assert(d.stage_done_cores == 2);
    assert(d.stage_bg_only_cores == 2);
    assert(d.hold_for_gather_completion);
    assert(d.active);
}

void test_all_end_scatter_and_idle_allows_quiet_countdown() {
    GlobalStepDrainInputs in{};
    in.injected = true;
    in.noc_idle = true;
    in.stage_arrays_ready = true;
    in.cores = {
        GlobalStepDrainCoreState{5, false},
        GlobalStepDrainCoreState{5, false},
        GlobalStepDrainCoreState{5, false},
    };

    const GlobalStepDrainDecision d = SST::SnnDL::evaluateGlobalStepDrainDecision(in);
    assert(d.uses_stage_events);
    assert(d.stage_done_cores == 3);
    assert(d.stage_bg_only_cores == 0);
    assert(!d.hold_for_gather_completion);
    assert(!d.active);
}

void test_begin_apply_core_keeps_step_active() {
    GlobalStepDrainInputs in{};
    in.injected = true;
    in.noc_idle = true;
    in.stage_arrays_ready = true;
    in.cores = {
        GlobalStepDrainCoreState{2, false},
        GlobalStepDrainCoreState{5, false},
    };

    const GlobalStepDrainDecision d = SST::SnnDL::evaluateGlobalStepDrainDecision(in);
    assert(d.stage_begin_apply_cores == 1);
    assert(d.stage_done_cores == 1);
    assert(d.active);
}

} // namespace

int main() {
    test_bg_only_core_blocks_pe_done_until_stage_progress_completes();
    test_all_end_scatter_and_idle_allows_quiet_countdown();
    test_begin_apply_core_keeps_step_active();
    return 0;
}
