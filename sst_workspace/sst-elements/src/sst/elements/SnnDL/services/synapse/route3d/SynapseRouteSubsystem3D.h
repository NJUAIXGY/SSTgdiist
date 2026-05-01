// -*- c++ -*-

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "ISynapseRoute.h"
#include "synapse/route/SnnRouteProvider.h"
#include "synapse/route/SynapseRouteSubsystem.h"
#include "Route3DNodeMapper.h"

namespace SST { namespace SnnDL {

class SynapseRouteSubsystem3D final : public ISynapseRoute {
public:
    using RouteMap = ISynapseRoute::RouteMap;
    using BlockTarget = ISynapseRoute::BlockTarget;
    using RouteSemanticDescriptor = ISynapseRoute::RouteSemanticDescriptor;
    using RouteRuntimeStatSinks = ISynapseRoute::RouteRuntimeStatSinks;
    using RouteWeightMap = SnnRouteProvider::RouteWeightMap;

    void configure(const SynapseRouteBuildConfig& cfg) override;
    void configureGating(bool gating_event_mode,
                         uint64_t gating_ttl_cycles,
                         bool gating_scope_inputs_only) override;
    void bindRuntime(SST::Output* log,
                     uint32_t node_id,
                     uint32_t core_id,
                     uint32_t num_neurons,
                     uint32_t neurons_per_pe_cfg,
                     SST::Statistics::Statistic<uint64_t>* stat_routes_entries) override;
    void bindFanoutStat(SST::Statistics::Statistic<uint64_t>* stat_fanout_per_spike) override;
    void bindRouteRuntimeStats(const RouteRuntimeStatSinks& stats) override;

    bool initRoutes() override;
    bool routingWeightDrivenActive() const override;
    std::shared_ptr<const RouteMap> routesShared() const override;
    const RouteMap* routesLocalFallback() const override;
    void computeFanout(uint32_t source_global, uint32_t neuron_idx,
                       uint64_t now_cycles,
                       std::vector<FanoutEntry>& out_entries,
                       bool& applied_gating) const override;
    void applyGatingDecision(uint32_t src_global,
                             const std::vector<uint32_t>& dest_pes,
                             uint64_t current_cycle,
                             uint64_t ttl_cycles) override;

    bool multicastEnabled() const override;
    uint32_t multicastBlockW() const override { return cfg_.multicast_block_w; }
    uint32_t multicastBlockH() const override { return cfg_.multicast_block_h; }
    uint32_t multicastBlockD() const override;
    uint32_t bcsrBlockCols() const override { return cfg_.bcsr_bc; }
    RouteSemanticDescriptor describeRouteSemantics() const override;
    bool computeMulticastTargets(uint32_t source_global,
                                 uint32_t neuron_idx,
                                 uint64_t now_cycles,
                                 std::vector<BlockTarget>& out_targets,
                                 bool& applied_gating) const override;

private:
    const RouteMap* activeNativeRouteTable_() const;
    bool tryApplyNativeGating_(uint32_t source_global,
                               uint32_t neuron_idx,
                               uint64_t now_cycles,
                               std::vector<FanoutEntry>& out_entries,
                               bool& applied_gating) const;
    float resolveNativeWeight_(uint32_t source_global, uint32_t dest_global) const;
    void appendNativeFanoutEntries_(uint32_t source_global,
                                    uint32_t neuron_idx,
                                    const std::vector<uint32_t>& native_destinations,
                                    bool destinations_are_pes,
                                    std::vector<FanoutEntry>& out_entries) const;
    void emitNativeRuntimeMarker_(uint32_t source_global,
                                  size_t fanout_count,
                                  bool applied_gating) const;
    void recordNativeRuntimeStats_(uint32_t source_global,
                                   size_t fanout_count,
                                   bool applied_gating) const;
    void computeFanoutNative3D_(uint32_t source_global,
                                uint32_t neuron_idx,
                                uint64_t now_cycles,
                                std::vector<FanoutEntry>& out_entries,
                                bool& applied_gating) const;
    bool tryInitNativeRoutes_();
    bool buildNativeRoutesFromEdgesCsv3D_();
    bool buildNativeRoutesFromLegacyBuiltRoutes3D_();
    uint32_t resolvedMulticastBlockDepth_() const;
    uint32_t multicastBlockDepthCompat_() const;
    bool preferNativeTargetSynthesis_() const;
    bool multicastGeometryValid_() const;
    bool synthesizeMulticastTargetsForBlockDepth_(uint32_t source_global,
                                                  uint32_t neuron_idx,
                                                  uint64_t now_cycles,
                                                  uint32_t block_d,
                                                  std::vector<BlockTarget>& out_targets,
                                                  bool& applied_gating) const;
    bool computeMulticastTargetsNative3D_(uint32_t source_global,
                                          uint32_t neuron_idx,
                                          uint64_t now_cycles,
                                          std::vector<BlockTarget>& out_targets,
                                          bool& applied_gating) const;
    bool computeMulticastTargetsCompatFallback_(uint32_t source_global,
                                                uint32_t neuron_idx,
                                                uint64_t now_cycles,
                                                std::vector<BlockTarget>& out_targets,
                                                bool& applied_gating) const;
    void configureFanoutProvider_();

    SynapseRouteBuildConfig cfg_{};
    SynapseRouteBuildConfig legacy_cfg_{};
    SynapseRouteSubsystem legacy_;
    SST::Output* log_ = nullptr;
    uint32_t node_id_ = 0;
    uint32_t core_id_ = 0;
    uint32_t num_neurons_ = 0;
    SST::Statistics::Statistic<uint64_t>* stat_routes_entries_ = nullptr;
    SST::Statistics::Statistic<uint64_t>* stat_fanout_per_spike_ = nullptr;
    RouteRuntimeStatSinks route_runtime_stats_{};
    bool routing_weight_driven_active_ = false;
    std::shared_ptr<const RouteMap> routes_shared_;
    RouteMap routes_local_fallback_;
    std::shared_ptr<const RouteWeightMap> route_weights_shared_;
    RouteWeightMap route_weights_local_fallback_;
    bool native_route_synthesis_active_ = false;
    std::shared_ptr<const RouteMap> native_routes_shared_;
    RouteMap native_routes_local_;
    std::shared_ptr<const RouteWeightMap> native_route_weights_shared_;
    RouteWeightMap native_route_weights_local_;
    bool fanout_provider_ready_ = false;
    SnnRouteProvider fanout_provider_;
    bool gating_event_mode_ = false;
    uint64_t gating_ttl_cycles_ = 1000;
    bool gating_scope_inputs_only_ = true;
    std::unordered_map<uint32_t, GatingEntry> gating_cache_;
    MeshShape3D mesh_shape_{};
    bool mesh_shape_valid_ = false;
    uint32_t neurons_per_pe_cfg_ = 0;
    mutable uint32_t native_runtime_marker_logs_emitted_ = 0;
    mutable std::unordered_set<uint32_t> native_runtime_unique_sources_seen_;
};

}} // namespace SST::SnnDL
