// -*- c++ -*-
//
// ExternalSpikeInputSubsystem:
// - 处理来自 external_spike_input 端口的 SpikeEvent* 直接注入；
// - 语义冻结：仅本地投递（不做 relay/forward），非本节点目标直接丢弃。
//

#pragma once

#include <cstdint>

namespace SST { class Output; }

namespace SST { namespace SnnDL {

class GlobalNeuronLayout;
class INocTransport;
class SpikeEvent;

class ExternalSpikeInputSubsystem final {
public:
    struct Runtime {
        SST::Output* log = nullptr;
        int node_id = 0;
        const GlobalNeuronLayout* layout = nullptr;
        INocTransport* noc = nullptr;
        bool enabled = true;

        // Legacy fields (kept for diagnostics/compat): not used for routing when layout is available.
        uint64_t global_neuron_base = 0;
        int num_cores = 1;
        int neurons_per_core = 1;
        int total_neurons = 1;
    };

    void bindRuntime(const Runtime& rt) { rt_ = rt; }

    // 语义：接管 spike 生命周期；若无法本地投递将直接 delete。
    void onSpike(SpikeEvent* spike);

private:
    int determineTargetUnit_(uint32_t global_neuron_id) const;

    Runtime rt_{};
};

}} // namespace SST::SnnDL
