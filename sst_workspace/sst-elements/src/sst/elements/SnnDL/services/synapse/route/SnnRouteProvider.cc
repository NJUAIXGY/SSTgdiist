#include "SnnRouteProvider.h"

#include <algorithm>
#include <sst/core/statapi/stataccumulator.h>

namespace SST { namespace SnnDL {

namespace {

inline uint32_t resolveNeuronsPerPe_(uint32_t neurons_per_pe_cfg) {
    return neurons_per_pe_cfg;
}

} // namespace

void SnnRouteProvider::configure(const Config& cfg,
                                 const std::shared_ptr<const RouteMap>& routes_shared,
                                 const RouteMap* routes_local,
                                 const RouteWeightMap* route_weights) {
    cfg_ = cfg;
    routes_shared_ = routes_shared;
    routes_local_ = routes_local;
    route_weights_ = route_weights;
}

const SnnRouteProvider::RouteMap* SnnRouteProvider::chooseRouteTable_() const {
    if (routes_shared_) return routes_shared_.get();
    return routes_local_;
}

void SnnRouteProvider::computeFanout(uint32_t source_global, uint32_t neuron_idx,
                                     uint64_t now_cycles,
                                     std::vector<FanoutEntry>& out_entries,
                                     bool& applied_gating) const {
    out_entries.clear();
    applied_gating = false;

    // gating 路径
    if (cfg_.routing_weight_driven && cfg_.gating_event_mode && cfg_.gating_cache) {
        bool scope_ok = !cfg_.gating_scope_inputs_only ? true : (cfg_.node_id <= 3);
        if (scope_ok) {
            auto itg = cfg_.gating_cache->find(source_global);
            if (itg != cfg_.gating_cache->end() && now_cycles <= itg->second.expire_cycle) {
                const auto& dpes = itg->second.dest_pes;
                if (!dpes.empty()) {
                    const uint32_t denom = resolveNeuronsPerPe_(cfg_.neurons_per_pe_cfg);
                    if (denom == 0) {
                        if (cfg_.out) {
                            cfg_.out->verbose(CALL_INFO, 1, 0,
                                              "⚠️ gating路径忽略：neurons_per_pe_cfg=0（denom=0） src_g=%u\n",
                                              source_global);
                        }
                    } else {
                    for (uint32_t dpe : dpes) {
                        FanoutEntry fe;
                        fe.dest_node = dpe;
                        fe.dest_global = dpe * denom + neuron_idx;
                        fe.weight = resolveWeight_(source_global, fe.dest_global);
                        out_entries.push_back(fe);
                    }
                    applied_gating = true;
                    if (cfg_.stat_fanout) cfg_.stat_fanout->addData(static_cast<uint64_t>(dpes.size()));
                    if (cfg_.out) {
                        cfg_.out->verbose(CALL_INFO, 2, 0,
                                          "🎯 门控命中: 源g=%u, 目的PE数=%zu\n",
                                          source_global, dpes.size());
                    }
                    return;
                    }
                }
            }
        }
    }

    if (cfg_.routing_weight_driven) {
        fanoutWeightDriven_(source_global, neuron_idx, out_entries);
    } else {
        fanoutFixed_(neuron_idx, out_entries);
    }
    // 兼容旧口径：fanout_per_spike 仅在权重驱动/门控路径统计
    if (cfg_.routing_weight_driven && cfg_.stat_fanout && !out_entries.empty()) {
        cfg_.stat_fanout->addData(static_cast<uint64_t>(out_entries.size()));
    }
}

void SnnRouteProvider::fanoutWeightDriven_(uint32_t source_global, uint32_t neuron_idx,
                                           std::vector<FanoutEntry>& out_entries) const {
    const RouteMap* route_tbl = chooseRouteTable_();
    if (!route_tbl) return;
    auto it = route_tbl->find(source_global);
    if (it == route_tbl->end()) return;
    const auto& dests = it->second;
    if (dests.empty()) return;
    const uint32_t denom = resolveNeuronsPerPe_(cfg_.neurons_per_pe_cfg);
    if (denom == 0) {
        if (cfg_.out) {
            cfg_.out->verbose(CALL_INFO, 0, 0,
                              "⚠️ 权重驱动扇出忽略：neurons_per_pe_cfg=0（denom=0） src_g=%u\n",
                              source_global);
        }
        return;
    }
    for (uint32_t dest_global : dests) {
        FanoutEntry fe;
        fe.dest_global = dest_global;
        fe.dest_node = (dest_global / denom);
        fe.weight = resolveWeight_(source_global, dest_global);
        out_entries.push_back(fe);
    }
    if (cfg_.log_weight_details && cfg_.out) {
        cfg_.out->verbose(CALL_INFO, 2, 0, "🌐 权重驱动扇出: 源g=%u, 目的数=%zu\n", source_global, dests.size());
    }
}

void SnnRouteProvider::fanoutFixed_(uint32_t neuron_idx,
                                    std::vector<FanoutEntry>& out_entries) const {
    // 固定映射沿用原逻辑：输入层 -> 隐藏层；隐藏层 -> 输出层；输出层不再发送
    const uint32_t neurons_per_node = (cfg_.neurons_per_pe_cfg > 0) ? cfg_.neurons_per_pe_cfg : 16u;
    uint32_t target_neuron = 0;
    uint32_t target_node = cfg_.node_id;
    if (cfg_.node_id >= 0 && cfg_.node_id <= 3) {
        uint32_t target_hidden_base = (cfg_.node_id < 2) ? 4 : 8;
        uint32_t target_hidden_node = target_hidden_base + (cfg_.node_id % 2) * 2 + (neuron_idx % 2);
        target_node = target_hidden_node;
        target_neuron = target_hidden_node * neurons_per_node + neuron_idx;
        if (cfg_.log_weight_details && cfg_.out) {
            cfg_.out->verbose(CALL_INFO, 2, 0,
                "🔥 输入层节点%d神经元%d -> 隐藏层节点%d神经元%d\n",
                (int)cfg_.node_id, (int)neuron_idx, (int)target_node, (int)target_neuron);
        }
    } else if (cfg_.node_id >= 4 && cfg_.node_id <= 11) {
        uint32_t target_output_node = 12 + ((cfg_.node_id - 4) / 2);
        target_node = target_output_node;
        const uint32_t fold = (neurons_per_node > 0) ? neurons_per_node : 1u;
        target_neuron = target_output_node * neurons_per_node + (neuron_idx % fold);
        if (cfg_.log_weight_details && cfg_.out) {
            cfg_.out->verbose(CALL_INFO, 2, 0,
                "🔥 隐藏层节点%d神经元%d -> 输出层节点%d神经元%d\n",
                (int)cfg_.node_id, (int)neuron_idx, (int)target_node, (int)target_neuron);
        }
    } else {
        // 输出层节点不再发送
        if (cfg_.log_weight_details && cfg_.out) {
            cfg_.out->verbose(CALL_INFO, 2, 0,
                "🔥 输出层节点%d神经元%d发放，不发送外部脉冲\n",
                (int)cfg_.node_id, (int)neuron_idx);
        }
        return;
    }
    FanoutEntry fe;
    fe.dest_global = target_neuron;
    fe.dest_node = target_node;
    fe.weight = 1.0f;
    out_entries.push_back(fe);
}

float SnnRouteProvider::resolveWeight_(uint32_t source_global, uint32_t dest_global) const {
    if (!route_weights_) return 1.0f;
    const uint64_t key =
        (static_cast<uint64_t>(source_global) << 32) | static_cast<uint64_t>(dest_global);
    auto it = route_weights_->find(key);
    if (it == route_weights_->end()) return 1.0f;
    return it->second;
}

} } // namespace SST::SnnDL
