#ifndef SST_ELEMENTS_SNNDL_SNNROUTEPROVIDER_H
#define SST_ELEMENTS_SNNDL_SNNROUTEPROVIDER_H

#include <cstdint>
#include <memory>
#include <unordered_map>
#include <vector>

#include <sst/core/output.h>

#include "ISynapseRoute.h"

namespace SST {
namespace Statistics {
template <typename T> class Statistic;
} }

namespace SST { namespace SnnDL {

struct GatingEntry { std::vector<uint32_t> dest_pes; uint64_t expire_cycle; };

class SnnRouteProvider {
public:
    using RouteMap = std::unordered_map<uint32_t, std::vector<uint32_t>>;
    using RouteWeightMap = std::unordered_map<uint64_t, float>;
    using FanoutEntry = ISynapseRoute::FanoutEntry;
    struct Config {
        bool routing_weight_driven = false;
        bool log_weight_details = false;
        uint32_t num_neurons = 0;
        uint32_t neurons_per_pe_cfg = 0;
        uint32_t node_id = 0;
        bool gating_event_mode = false;
        bool gating_scope_inputs_only = true;
        std::unordered_map<uint32_t, GatingEntry>* gating_cache = nullptr;
        Output* out = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_fanout = nullptr;
    };

    void configure(const Config& cfg,
                   const std::shared_ptr<const RouteMap>& routes_shared,
                   const RouteMap* routes_local,
                   const RouteWeightMap* route_weights);

    // 计算扇出列表；applied_gating=true 表示命中 gating 并已替代常规路由。
    void computeFanout(uint32_t source_global, uint32_t neuron_idx,
                       uint64_t now_cycles,
                       std::vector<FanoutEntry>& out_entries,
                       bool& applied_gating) const;

private:
    const RouteMap* chooseRouteTable_() const;
    void fanoutWeightDriven_(uint32_t source_global, uint32_t neuron_idx,
                             std::vector<FanoutEntry>& out_entries) const;
    void fanoutFixed_(uint32_t neuron_idx,
                      std::vector<FanoutEntry>& out_entries) const;
    float resolveWeight_(uint32_t source_global, uint32_t dest_global) const;

    Config cfg_{};
    std::shared_ptr<const RouteMap> routes_shared_;
    const RouteMap* routes_local_ = nullptr;
    const RouteWeightMap* route_weights_ = nullptr;
};

} } // namespace SST::SnnDL

#endif // SST_ELEMENTS_SNNDL_SNNROUTEPROVIDER_H
