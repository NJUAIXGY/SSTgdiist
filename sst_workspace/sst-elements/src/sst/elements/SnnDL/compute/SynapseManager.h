#ifndef SNNDL_SYNAPSE_MANAGER_H
#define SNNDL_SYNAPSE_MANAGER_H

#include <map>
#include <vector>
#include <cstdint>
#include <utility>
#include <string>

namespace SST { namespace SnnDL {

class SynapseManager {
public:
    SynapseManager(uint32_t local_base = 0, uint32_t neurons_per_pe = 0)
        : local_neuron_base_(local_base), neurons_per_pe_(neurons_per_pe) {}

    float getSynapticWeight(uint32_t pre_neuron, uint32_t post_neuron) const {
        auto it = weight_matrix_.find({pre_neuron, post_neuron});
        return (it != weight_matrix_.end()) ? it->second : 0.0f;
    }

    void setSynapticWeight(uint32_t pre_neuron, uint32_t post_neuron, float weight) {
        weight_matrix_[{pre_neuron, post_neuron}] = weight;
    }

    std::vector<std::pair<uint32_t, float>> getConnections(uint32_t pre_neuron) const {
        auto it = connections_cache_.find(pre_neuron);
        if (it != connections_cache_.end()) return it->second;
        // fallback build from weight_matrix_
        std::vector<std::pair<uint32_t, float>> conns;
        for (const auto& kv : weight_matrix_) {
            if (kv.first.first == pre_neuron) conns.emplace_back(kv.first.second, kv.second);
        }
        return conns;
    }

    void addConnection(uint32_t pre_neuron, uint32_t post_neuron, float weight) {
        connections_cache_[pre_neuron].emplace_back(post_neuron, weight);
        setSynapticWeight(pre_neuron, post_neuron, weight);
    }

    void removeConnection(uint32_t pre_neuron, uint32_t post_neuron) {
        weight_matrix_.erase({pre_neuron, post_neuron});
        auto it = connections_cache_.find(pre_neuron);
        if (it != connections_cache_.end()) {
            auto& vec = it->second;
            vec.erase(std::remove_if(vec.begin(), vec.end(), [&](const auto& p){return p.first==post_neuron;}), vec.end());
        }
    }

    void setUniformWeight(float weight) {
        for (auto& kv : weight_matrix_) kv.second = weight;
    }

    void loadFromFile(const std::string& /*weights_file*/) {
        // Stub: no-op for now
    }

    bool isLocalConnection(uint32_t pre_neuron, uint32_t post_neuron) const {
        return getDestinationPE(pre_neuron) == getDestinationPE(post_neuron);
    }

    uint32_t getDestinationPE(uint32_t neuron_id) const {
        if (neurons_per_pe_ == 0) return 0;
        return (neuron_id - local_neuron_base_) / neurons_per_pe_;
    }

    size_t getConnectionCount() const { return weight_matrix_.size(); }

    size_t getLocalConnectionCount() const {
        size_t c = 0;
        for (const auto& kv : weight_matrix_) if (isLocalConnection(kv.first.first, kv.first.second)) ++c;
        return c;
    }

    size_t getCrossConnectionCount() const { return getConnectionCount() - getLocalConnectionCount(); }

private:
    std::map<std::pair<uint32_t,uint32_t>, float> weight_matrix_;
    std::map<uint32_t, std::vector<std::pair<uint32_t,float>>> connections_cache_;
    uint32_t local_neuron_base_ = 0;
    uint32_t neurons_per_pe_ = 0;
};

}} // namespace

#endif // SNNDL_SYNAPSE_MANAGER_H
