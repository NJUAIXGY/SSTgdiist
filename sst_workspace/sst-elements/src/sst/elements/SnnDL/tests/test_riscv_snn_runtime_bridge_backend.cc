// -*- c++ -*-

#include "api/ICoreWorkload.h"
#include "api/ISnnAccelRuntimeServices.h"
#include "workload/common/SnnAccelBackend.h"
#include "workload/common/SnnAccelBackendContract.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"

#include <cassert>
#include <cstdint>
#include <map>

namespace {

class FakeRuntimeServices final : public SST::SnnDL::ISnnAccelRuntimeServices {
public:
    bool runtimeBridgeReady() const override { return ready; }

    bool tickRuntime(uint64_t now_cycle) override {
        last_cycle = now_cycle;
        ++tick_count;
        if (remaining_runtime_ticks > 0) {
            --remaining_runtime_ticks;
            return true;
        }
        return false;
    }

    bool deliverIngressPacket(SST::SnnDL::NocPacketEvent* packet) override {
        (void)packet;
        ++packet_count;
        return packet_accept;
    }

    bool hasRuntimeWork() const override { return remaining_runtime_ticks > 0; }

    double runtimeUtilization() const override { return tick_count == 0 ? 0.0 : 1.0; }

    void snapshotRuntimeStats(std::map<std::string, uint64_t>& stats) const override {
        stats["fake_tick_count"] = tick_count;
        stats["fake_packet_count"] = packet_count;
        stats["fake_last_cycle"] = last_cycle;
    }

    bool ready = true;
    bool packet_accept = true;
    uint32_t remaining_runtime_ticks = 1;
    uint64_t tick_count = 0;
    uint64_t packet_count = 0;
    uint64_t last_cycle = 0;
};

SST::SnnDL::SnnAccelCommand makeStatSnapshot(uint64_t ticket,
                                             uint64_t token,
                                             SST::SnnDL::riscv_snn::StatSnapshotSelector selector) {
    using namespace SST::SnnDL;
    using namespace SST::SnnDL::riscv_snn;

    SnnAccelCommand command;
    command.ticket = ticket;
    command.version = 1;
    command.opcode = static_cast<uint8_t>(CommandOpcode::StatSnapshot);
    command.desc_bytes = kCommandDescriptorBytes;
    command.token = token;
    command.arg0 = makeStatSnapshotSelectorArg0(selector);
    return command;
}

SST::SnnDL::SnnAccelCommand makeRawStatSnapshot(uint64_t ticket,
                                                uint64_t token,
                                                uint32_t raw_selector) {
    SST::SnnDL::SnnAccelCommand command = makeStatSnapshot(
        ticket,
        token,
        SST::SnnDL::riscv_snn::StatSnapshotSelector::AcceptedCommands);
    command.arg0 = raw_selector;
    return command;
}

SST::SnnDL::SnnAccelCommand makeFusedStep(uint64_t ticket, uint64_t token) {
    using namespace SST::SnnDL;
    using namespace SST::SnnDL::riscv_snn;

    SnnAccelCommand command;
    command.ticket = ticket;
    command.version = 1;
    command.opcode = static_cast<uint8_t>(CommandOpcode::FusedStep);
    command.desc_bytes = kCommandDescriptorBytes;
    command.token = token;
    return command;
}

uint64_t readStatSnapshotValue(const SST::SnnDL::SnnAccelCompletion& completion) {
    return SST::SnnDL::riscv_snn::decodeStatSnapshotResult(completion.aux0, completion.aux1);
}

void assertInvalidSelectorFault(const SST::SnnDL::SnnAccelCompletion& completion,
                                uint32_t raw_selector) {
    using namespace SST::SnnDL::riscv_snn;

    assert(completionPrimaryStatus(completion.status_code) == CompletionPrimaryStatus::BadPolicy);
    assert(completionSeverity(completion.status_code) == CompletionSeverity::FaultAfterAccept);
    assert((completion.event_mask & eventMask(EventBit::Fault)) != 0u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    const uint64_t fault_snapshot = completionFaultSnapshot(completion.aux0, completion.aux1);
    assert(faultCode(fault_snapshot) == FaultCode::BadPolicy);
    assert(faultSource(fault_snapshot) == FaultSource::Descriptor);
    assert(faultAux(fault_snapshot) == raw_selector);
}

} // namespace

int main() {
    using namespace SST::SnnDL;
    using namespace SST::SnnDL::riscv_snn;

    auto null_backend = makeSnnAccelBackendByName("null");
    auto bridge_backend = makeSnnAccelBackendByName("runtime_bridge");
    assert(null_backend);
    assert(bridge_backend);

    SnnAccelBackend::Config null_cfg;
    null_cfg.backend_name = "null";
    null_backend->configure(null_cfg);

    FakeRuntimeServices provider;
    ICoreWorkload::Runtime rt{};
    rt.accel_runtime = &provider;

    SnnAccelBackend::Config cfg;
    cfg.runtime = rt;
    cfg.backend_name = "runtime_bridge";
    bridge_backend->configure(cfg);

    SnnAccelCompletion completion{};

    const SnnAccelCommand null_accepted_snapshot = makeStatSnapshot(
        /*ticket=*/1,
        /*token=*/0xAA10,
        StatSnapshotSelector::AcceptedCommands);
    assert(null_backend->submitCommand(null_accepted_snapshot));
    assert(null_backend->tick(1));
    assert(null_backend->pollCompletion(completion));
    assert(completion.token == null_accepted_snapshot.token);
    assert(completion.status_code ==
           encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success));
    assert(readStatSnapshotValue(completion) == 1u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    const SnnAccelCommand null_completed_snapshot = makeStatSnapshot(
        /*ticket=*/2,
        /*token=*/0xAA20,
        StatSnapshotSelector::CompletedCommands);
    assert(null_backend->submitCommand(null_completed_snapshot));
    assert(null_backend->tick(2));
    assert(null_backend->pollCompletion(completion));
    assert(readStatSnapshotValue(completion) == 1u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    const uint32_t null_invalid_selector = 0x55u;
    const SnnAccelCommand null_invalid_snapshot = makeRawStatSnapshot(
        /*ticket=*/3,
        /*token=*/0xAA25,
        null_invalid_selector);
    assert(null_backend->submitCommand(null_invalid_snapshot));
    assert(null_backend->tick(3));
    assert(null_backend->pollCompletion(completion));
    assertInvalidSelectorFault(completion, null_invalid_selector);

    const SnnAccelCommand null_completed_after_fault = makeStatSnapshot(
        /*ticket=*/4,
        /*token=*/0xAA28,
        StatSnapshotSelector::CompletedCommands);
    assert(null_backend->submitCommand(null_completed_after_fault));
    assert(null_backend->tick(4));
    assert(null_backend->pollCompletion(completion));
    assert(readStatSnapshotValue(completion) == 2u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    const SnnAccelCommand null_provider_snapshot = makeStatSnapshot(
        /*ticket=*/5,
        /*token=*/0xAA30,
        StatSnapshotSelector::ProviderBound);
    assert(null_backend->submitCommand(null_provider_snapshot));
    assert(null_backend->tick(5));
    assert(null_backend->pollCompletion(completion));
    assert(readStatSnapshotValue(completion) == 0u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    const SnnAccelCommand fused_step = makeFusedStep(/*ticket=*/3, /*token=*/0x1234);
    assert(bridge_backend->submitCommand(fused_step));

    SnnAccelStepState state = bridge_backend->readArchitecturalStepState();
    assert(state.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::Accepted));
    assert(state.busy);

    assert(!bridge_backend->pollCompletion(completion));

    assert(bridge_backend->tick(1));
    state = bridge_backend->readArchitecturalStepState();
    assert(state.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::Executing));
    assert(provider.tick_count == 1u);

    assert(bridge_backend->tick(2));
    state = bridge_backend->readArchitecturalStepState();
    assert(state.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::OutboundDraining));

    assert(bridge_backend->tick(3));
    state = bridge_backend->readArchitecturalStepState();
    assert(state.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::BarrierWaiting));

    assert(bridge_backend->tick(4));
    state = bridge_backend->readArchitecturalStepState();
    assert(state.phase == accelRuntimePhaseValue(SnnAccelRuntimePhase::Completed));
    assert(state.committed_seq == 1u);
    assert(bridge_backend->pollCompletion(completion));
    assert(completion.token == fused_step.token);
    assert(completion.status_code ==
           encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success));
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) != 0u);

    std::map<std::string, uint64_t> stats;
    bridge_backend->snapshotStats(stats);
    assert(stats["riscv_snn_backend_runtime_bridge_ticks"] == provider.tick_count);
    assert(stats["riscv_snn_backend_runtime_bridge_packets"] == provider.packet_count);

    assert(bridge_backend->injectPacket(nullptr));
    bridge_backend->snapshotStats(stats);
    assert(stats["riscv_snn_backend_runtime_bridge_packets"] == 1u);

    const SnnAccelCommand bridge_accepted_snapshot = makeStatSnapshot(
        /*ticket=*/4,
        /*token=*/0x3333,
        StatSnapshotSelector::AcceptedCommands);
    assert(bridge_backend->submitCommand(bridge_accepted_snapshot));
    assert(bridge_backend->tick(5));
    assert(bridge_backend->pollCompletion(completion));
    assert(completion.status_code ==
           encodeStatusCode(CompletionPrimaryStatus::Success, CompletionSeverity::Success));
    assert(readStatSnapshotValue(completion) == 2u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    const SnnAccelCommand bridge_provider_snapshot = makeStatSnapshot(
        /*ticket=*/5,
        /*token=*/0x4444,
        StatSnapshotSelector::ProviderBound);
    assert(bridge_backend->submitCommand(bridge_provider_snapshot));
    assert(bridge_backend->tick(6));
    assert(bridge_backend->pollCompletion(completion));
    assert(readStatSnapshotValue(completion) == 1u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    provider.remaining_runtime_ticks = 0;
    SnnAccelCommand bad_opcode = makeFusedStep(/*ticket=*/6, /*token=*/0x7777);
    bad_opcode.opcode = 0xFF;
    assert(bridge_backend->submitCommand(bad_opcode));
    assert(bridge_backend->tick(7));
    assert(bridge_backend->pollCompletion(completion));
    assert(completion.status_code ==
           encodeStatusCode(
               CompletionPrimaryStatus::BadOpcode,
               CompletionSeverity::FaultAfterAccept));

    FakeRuntimeServices visibility_provider;
    visibility_provider.ready = false;
    visibility_provider.remaining_runtime_ticks = 0;

    ICoreWorkload::Runtime visibility_rt{};
    visibility_rt.accel_runtime = &visibility_provider;

    auto bridge_visibility_backend = makeSnnAccelBackendByName("runtime_bridge");
    assert(bridge_visibility_backend);

    SnnAccelBackend::Config visibility_cfg;
    visibility_cfg.runtime = visibility_rt;
    visibility_cfg.backend_name = "runtime_bridge";
    bridge_visibility_backend->configure(visibility_cfg);

    std::map<std::string, uint64_t> visibility_stats;
    bridge_visibility_backend->snapshotStats(visibility_stats);
    assert(visibility_stats["riscv_snn_backend_runtime_bridge_provider_bound"] == 0u);

    const SnnAccelCommand bridge_provider_unbound = makeStatSnapshot(
        /*ticket=*/10,
        /*token=*/0x5510,
        StatSnapshotSelector::ProviderBound);
    assert(bridge_visibility_backend->submitCommand(bridge_provider_unbound));
    assert(bridge_visibility_backend->tick(8));
    assert(bridge_visibility_backend->pollCompletion(completion));
    assert(readStatSnapshotValue(completion) == 0u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    visibility_provider.ready = true;
    bridge_visibility_backend->snapshotStats(visibility_stats);
    assert(visibility_stats["riscv_snn_backend_runtime_bridge_provider_bound"] == 1u);

    const SnnAccelCommand bridge_provider_bound = makeStatSnapshot(
        /*ticket=*/11,
        /*token=*/0x5520,
        StatSnapshotSelector::ProviderBound);
    assert(bridge_visibility_backend->submitCommand(bridge_provider_bound));
    assert(bridge_visibility_backend->tick(9));
    assert(bridge_visibility_backend->pollCompletion(completion));
    assert(readStatSnapshotValue(completion) == 1u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    const SnnAccelCommand bridge_completed_visible = makeStatSnapshot(
        /*ticket=*/12,
        /*token=*/0x5530,
        StatSnapshotSelector::CompletedCommands);
    assert(bridge_visibility_backend->submitCommand(bridge_completed_visible));
    assert(bridge_visibility_backend->tick(10));
    assert(bridge_visibility_backend->pollCompletion(completion));
    assert(readStatSnapshotValue(completion) == 2u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    const uint32_t bridge_invalid_selector = 0xA5u;
    const SnnAccelCommand bridge_invalid_snapshot = makeRawStatSnapshot(
        /*ticket=*/13,
        /*token=*/0x5540,
        bridge_invalid_selector);
    assert(bridge_visibility_backend->submitCommand(bridge_invalid_snapshot));
    assert(bridge_visibility_backend->tick(11));
    assert(bridge_visibility_backend->pollCompletion(completion));
    assertInvalidSelectorFault(completion, bridge_invalid_selector);

    const SnnAccelCommand bridge_completed_after_fault = makeStatSnapshot(
        /*ticket=*/14,
        /*token=*/0x5550,
        StatSnapshotSelector::CompletedCommands);
    assert(bridge_visibility_backend->submitCommand(bridge_completed_after_fault));
    assert(bridge_visibility_backend->tick(12));
    assert(bridge_visibility_backend->pollCompletion(completion));
    assert(readStatSnapshotValue(completion) == 3u);
    assert((completion.event_mask & eventMask(EventBit::BarrierRelease)) == 0u);

    return 0;
}
