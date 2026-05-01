// -*- c++ -*-
//
// GlobalNeuronLayout:
// - 全局 neuron_id ↔ (node/core/local_index) 的统一映射口径
// - 作为“单一真源”供 Step/Route/NoC 等模块共享，避免各处自行除法/取模导致口径漂移
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

class GlobalNeuronLayout final {
public:
    GlobalNeuronLayout() = default;

    GlobalNeuronLayout(uint32_t total_nodes, uint32_t num_cores, uint32_t neurons_per_core)
        : total_nodes_(total_nodes), num_cores_(num_cores), neurons_per_core_(neurons_per_core) {
        neurons_per_pe_ = static_cast<uint64_t>(num_cores_) * static_cast<uint64_t>(neurons_per_core_);
        max_global_neurons_ = static_cast<uint64_t>(total_nodes_) * neurons_per_pe_;
    }

    bool valid() const { return total_nodes_ > 0 && num_cores_ > 0 && neurons_per_core_ > 0 && neurons_per_pe_ > 0; }

    uint32_t totalNodes() const { return total_nodes_; }
    uint32_t numCores() const { return num_cores_; }
    uint32_t neuronsPerCore() const { return neurons_per_core_; }
    uint64_t neuronsPerPE() const { return neurons_per_pe_; }
    uint64_t maxGlobalNeurons() const { return max_global_neurons_; }

    uint64_t globalBaseOfNode(uint32_t node_id) const { return static_cast<uint64_t>(node_id) * neurons_per_pe_; }

    uint32_t nodeOf(uint64_t global_neuron_id) const {
        return neurons_per_pe_ ? static_cast<uint32_t>(global_neuron_id / neurons_per_pe_) : 0u;
    }

    uint32_t coreOf(uint64_t global_neuron_id) const {
        if (!neurons_per_pe_ || !neurons_per_core_) return 0u;
        const uint64_t in_pe = global_neuron_id % neurons_per_pe_;
        return static_cast<uint32_t>(in_pe / static_cast<uint64_t>(neurons_per_core_));
    }

    uint32_t localIndexOf(uint64_t global_neuron_id) const {
        if (!neurons_per_pe_ || !neurons_per_core_) return 0u;
        const uint64_t in_pe = global_neuron_id % neurons_per_pe_;
        return static_cast<uint32_t>(in_pe % static_cast<uint64_t>(neurons_per_core_));
    }

    bool inGlobalRange(uint64_t global_neuron_id) const {
        return max_global_neurons_ > 0 ? (global_neuron_id < max_global_neurons_) : false;
    }

    bool isLocalToNode(uint64_t global_neuron_id, uint32_t node_id) const {
        return nodeOf(global_neuron_id) == node_id;
    }

private:
    uint32_t total_nodes_ = 0;
    uint32_t num_cores_ = 0;
    uint32_t neurons_per_core_ = 0;
    uint64_t neurons_per_pe_ = 0;
    uint64_t max_global_neurons_ = 0;
};

}} // namespace SST::SnnDL

