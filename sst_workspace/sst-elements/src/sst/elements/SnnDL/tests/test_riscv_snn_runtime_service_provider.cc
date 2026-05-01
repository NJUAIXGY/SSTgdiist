// -*- c++ -*-

#include "api/ICoreWorkload.h"
#include "api/ISnnAccelRuntimeServices.h"
#include "workload/common/SnnAccelBackend.h"
#include "workload/riscv_snn/RiscvSnnAbi.h"
#include "workload/riscv_snn/RiscvSnnShadowTransportExport.h"

#include <cassert>
#include <cstdint>
#include <map>

namespace {

class StubRuntimeServices final : public SST::SnnDL::ISnnAccelRuntimeServices {
public:
    bool runtimeBridgeReady() const override { return true; }

    bool tickRuntime(uint64_t now_cycle) override {
        last_cycle = now_cycle;
        ++tick_count;
        return true;
    }

    bool deliverIngressPacket(SST::SnnDL::NocPacketEvent* packet) override {
        (void)packet;
        ++packet_count;
        return true;
    }

    bool hasRuntimeWork() const override { return false; }

    double runtimeUtilization() const override { return tick_count == 0 ? 0.0 : 1.0; }

    void snapshotRuntimeStats(std::map<std::string, uint64_t>& stats) const override {
        stats["stub_tick_count"] = tick_count;
        stats["stub_packet_count"] = packet_count;
        stats["stub_last_cycle"] = last_cycle;
        stats["shadow_snn_tx_spike_packets_total"] = 11;
        stats["shadow_snn_tx_spikekey_packets_total"] = 2;
        stats["shadow_snn_tx_spiketilekey_packets_total"] = 1;
        stats["shadow_snn_rx_spike_packets_total"] = 7;
        stats["shadow_snn_rx_spikekey_total"] = 3;
        stats["shadow_snn_rx_spiketilekey_total"] = 1;
        stats["shadow_snn_rx_fastpath_packets_total"] = 3;
        stats["shadow_snn_rx_fallback_packets_total"] = 1;
    }

    uint64_t tick_count = 0;
    uint64_t packet_count = 0;
    uint64_t last_cycle = 0;
};

} // namespace

int main(int argc, char** argv) {
    (void)argc;
    (void)argv;
    using namespace SST::SnnDL;
    using namespace SST::SnnDL::riscv_snn;

    ICoreWorkload::Runtime rt{};
    assert(rt.accel_runtime == nullptr);

    StubRuntimeServices provider;
    rt.accel_runtime = &provider;
    assert(rt.accel_runtime != nullptr);
    assert(rt.accel_runtime->runtimeBridgeReady());
    assert(rt.accel_runtime->tickRuntime(17));
    assert(provider.tick_count == 1u);

    std::map<std::string, uint64_t> stats;
    rt.accel_runtime->snapshotRuntimeStats(stats);
    assert(stats["stub_tick_count"] == 1u);
    assert(stats["stub_last_cycle"] == 17u);

    auto backend = makeSnnAccelBackendByName("runtime_bridge");
    assert(backend);

    SnnAccelBackend::Config cfg;
    cfg.backend_name = "runtime_bridge";
    backend->configure(cfg);

    SnnAccelCommand command;
    command.ticket = 1;
    command.version = 1;
    command.opcode = static_cast<uint8_t>(CommandOpcode::FusedStep);
    command.desc_bytes = kCommandDescriptorBytes;
    command.token = 0x99;

    assert(backend->submitCommand(command));
    assert(backend->tick(1));

    SnnAccelCompletion completion{};
    assert(backend->pollCompletion(completion));
    assert(completion.ticket == command.ticket);
    assert(completion.status_code ==
           encodeStatusCode(
               CompletionPrimaryStatus::BackendInternalError,
               CompletionSeverity::FaultAfterAccept));
    assert((completion.event_mask & eventMask(EventBit::Fault)) != 0u);

    auto export_backend = makeSnnAccelBackendByName("runtime_bridge");
    assert(export_backend);

    SnnAccelBackend::Config export_cfg;
    export_cfg.backend_name = "runtime_bridge";
    export_cfg.runtime = rt;
    export_backend->configure(export_cfg);

    std::map<std::string, uint64_t> workload_stats;
    export_backend->snapshotStats(workload_stats);
    exportRiscvSnnRuntimeBridgeShadowTransportStats(workload_stats);
    assert(workload_stats["snn_tx_spike_packets_total"] == 11u);
    assert(workload_stats["snn_tx_spikekey_packets_total"] == 2u);
    assert(workload_stats["snn_tx_spiketilekey_packets_total"] == 1u);
    assert(workload_stats["snn_rx_spike_packets_total"] == 7u);
    assert(workload_stats["snn_rx_spikekey_total"] == 3u);
    assert(workload_stats["snn_rx_spiketilekey_total"] == 1u);
    assert(workload_stats["snn_rx_fastpath_packets_total"] == 3u);
    assert(workload_stats["snn_rx_fallback_packets_total"] == 1u);

    return 0;
}
