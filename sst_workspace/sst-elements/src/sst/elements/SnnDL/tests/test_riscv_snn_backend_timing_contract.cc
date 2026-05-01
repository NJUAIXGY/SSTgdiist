// -*- c++ -*-

#include "workload/common/SnnAccelBackend.h"
#include "workload/common/SnnAccelBackendContract.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"

#include <cassert>
#include <cstdint>

int main() {
    using namespace SST::SnnDL;
    using namespace SST::SnnDL::riscv_snn;

    static_assert(
        accelRuntimePhaseValue(SnnAccelRuntimePhase::Accepted) == 1u,
        "accepted phase ABI drift");
    static_assert(
        accelRuntimePhaseValue(SnnAccelRuntimePhase::BarrierWaiting) == 4u,
        "barrier phase ABI drift");
    static_assert(
        completionVisibilityOrderIsMonotonic(
            SnnAccelCompletionVisibility::PayloadWritten,
            SnnAccelCompletionVisibility::WakeEligible),
        "completion visibility order must remain monotonic");

    auto backend = makeSnnAccelBackendByName("null");
    assert(backend);

    SnnAccelBackend::Config cfg;
    cfg.backend_name = "null";
    backend->configure(cfg);

    SnnAccelCommand command;
    command.ticket = 7;
    command.version = 1;
    command.opcode = static_cast<uint8_t>(CommandOpcode::FusedStep);
    command.desc_bytes = kCommandDescriptorBytes;
    command.token = 0x55;

    assert(backend->submitCommand(command));

    const SnnAccelStepState accepted = backend->readArchitecturalStepState();
    assert(accepted.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::Accepted));
    assert(accepted.busy);
    assert(accepted.inflight_seq == 1u);
    assert(!accepted.barrier_waiting);
    assert(!accepted.outbound_draining);
    assert(!fusedStepCompletionBoundaryReached(accepted));

    SnnAccelCompletion completion{};
    assert(!backend->pollCompletion(completion));

    assert(backend->tick(1));
    const SnnAccelStepState executing = backend->readArchitecturalStepState();
    assert(executing.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::Executing));
    assert(executing.busy);
    assert(!backend->pollCompletion(completion));

    assert(backend->tick(2));
    const SnnAccelStepState draining = backend->readArchitecturalStepState();
    assert(draining.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::OutboundDraining));
    assert(draining.outbound_draining);
    assert(!draining.barrier_waiting);
    assert(!backend->pollCompletion(completion));

    assert(backend->tick(3));
    const SnnAccelStepState waiting = backend->readArchitecturalStepState();
    assert(waiting.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::BarrierWaiting));
    assert(waiting.barrier_waiting);
    assert(!waiting.outbound_draining);
    assert(!backend->pollCompletion(completion));

    assert(backend->tick(4));
    const SnnAccelStepState completed = backend->readArchitecturalStepState();
    assert(fusedStepCompletionBoundaryReached(completed));
    assert(completed.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::Completed));
    assert(!completed.busy);
    assert(completed.committed_seq == 1u);

    assert(backend->pollCompletion(completion));
    assert(completion.ticket == command.ticket);
    assert(completion.token == command.token);
    assert(completion.status_code ==
           encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success));
    assert((completion.event_mask & eventMask(EventBit::CmdComplete)) != 0u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) != 0u);
    assert(!backend->pollCompletion(completion));

    return 0;
}
