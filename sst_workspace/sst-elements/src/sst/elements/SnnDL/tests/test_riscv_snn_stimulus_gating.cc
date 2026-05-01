// -*- c++ -*-

#include "api/WorkloadConfig.h"
#include "services/stimulus/ExternalSpikeInputSubsystem.h"

#include <cassert>

namespace {

void assertWorkloadHelperSemantics() {
    using namespace SST::SnnDL;

    assert(workloadAllowsPureSnnDatapathFeatures(WorkloadKind::Snn));
    assert(!workloadAllowsPureSnnDatapathFeatures(WorkloadKind::RiscvSnn));
    assert(!workloadAllowsPureSnnDatapathFeatures(WorkloadKind::Stream));
    assert(!workloadAllowsPureSnnDatapathFeatures(WorkloadKind::Traffic));
    assert(!workloadAllowsPureSnnDatapathFeatures(WorkloadKind::TrafficMem));
    assert(!workloadAllowsPureSnnDatapathFeatures(WorkloadKind::Tensor));

    assert(workloadAllowsSnnStimulus(WorkloadKind::Snn));
    assert(workloadAllowsSnnStimulus(WorkloadKind::RiscvSnn));
    assert(!workloadAllowsSnnStimulus(WorkloadKind::Stream));
    assert(!workloadAllowsSnnStimulus(WorkloadKind::Traffic));
    assert(!workloadAllowsSnnStimulus(WorkloadKind::TrafficMem));
    assert(!workloadAllowsSnnStimulus(WorkloadKind::Tensor));

    assert(!isNonSnnWorkloadKind(WorkloadKind::Snn));
    assert(isNonSnnWorkloadKind(WorkloadKind::RiscvSnn));
    assert(workloadAllowsSnnStimulus(WorkloadKind::RiscvSnn) &&
           !workloadAllowsPureSnnDatapathFeatures(WorkloadKind::RiscvSnn));
}

void assertExternalSpikeRuntimeSurface(SST::SnnDL::WorkloadKind workload_kind,
                                       bool expect_enable) {
    using namespace SST::SnnDL;

    ExternalSpikeInputSubsystem::Runtime rt;
    rt.enabled = workloadAllowsSnnStimulus(workload_kind);
    assert(rt.enabled == expect_enable);
}

} // namespace

int main(int argc, char** argv) {
    (void)argc;
    (void)argv;

    assertWorkloadHelperSemantics();
    assertExternalSpikeRuntimeSurface(SST::SnnDL::WorkloadKind::Snn, true);
    assertExternalSpikeRuntimeSurface(SST::SnnDL::WorkloadKind::RiscvSnn, true);
    assertExternalSpikeRuntimeSurface(SST::SnnDL::WorkloadKind::Stream, false);
    assertExternalSpikeRuntimeSurface(SST::SnnDL::WorkloadKind::Traffic, false);
    assertExternalSpikeRuntimeSurface(SST::SnnDL::WorkloadKind::TrafficMem, false);
    assertExternalSpikeRuntimeSurface(SST::SnnDL::WorkloadKind::Tensor, false);

    return 0;
}
