// -*- c++ -*-
//
// ISynapseRoute: Synapse/Route 子系统的最小路由抽象。
//
// 目标（Phase2）：
// - 将“权重驱动路由的构建 + 共享缓存”从 SpikeCommSubsystem 下移到 Synapse/Route；
// - SpikeCommSubsystem 仅消费最终 routes 来计算 fanout 并发送事件（传输语义不变）。
//
// Phase3 扩展：
// - fanout 计算与门控缓存同样属于“路由/突触语义”，下沉至 Synapse/Route；
// - SpikeCommSubsystem 退化为纯 transport façade（只做事件构造 + send）。

#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "MulticastLimits.h"

namespace SST {
class Output;
namespace Statistics {
template <typename T> class Statistic;
}
}

namespace SST { namespace SnnDL {

struct SynapseRouteBuildConfig;

class ISynapseRoute {
public:
    using RouteMap = std::unordered_map<uint32_t, std::vector<uint32_t>>;

    struct FanoutEntry {
        uint32_t dest_global = 0;
        uint32_t dest_node = 0;
        float weight = 1.0f;
    };

    struct BlockTarget final {
        uint32_t block_id = 0;
        uint32_t ingress_node = 0;
        uint32_t block_z = 0;
        uint32_t block_d = 1;
        uint16_t cohort_id = 0;
        uint16_t band_color = 0;
        std::array<uint32_t, kMaxMulticastBlockCells> core_mask{};
    };

    struct RouteSemanticDescriptor final {
        std::string source_semantics_authority = "legacy_provider";
        std::string source_primary_kind = "legacy_only";
        std::string route_topology = "mesh_2d";
        std::string target_semantics_authority = "legacy_multicast_fallback";
        bool real_synapse_inputs_available = false;
        bool native_synapse_source_candidate = false;
        bool native_source_fanout_active = false;
        bool native_target_synthesis_active = false;
        bool bootstrap_dependency_active = false;
        std::string native_bootstrap_source{};
    };

    struct RouteRuntimeStatSinks final {
        uint64_t* route3d_native_activation_total = nullptr;
        uint64_t* route3d_native_gating_activation_total = nullptr;
        uint64_t* route3d_native_direct_activation_total = nullptr;
        uint64_t* route3d_native_unique_sources_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_route3d_native_activation_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_route3d_native_gating_activation_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_route3d_native_direct_activation_total = nullptr;
        SST::Statistics::Statistic<uint64_t>* stat_route3d_native_unique_sources_total = nullptr;
    };

    virtual ~ISynapseRoute() = default;

    virtual void configure(const SynapseRouteBuildConfig& cfg) = 0;
    virtual void configureGating(bool gating_event_mode,
                                 uint64_t gating_ttl_cycles,
                                 bool gating_scope_inputs_only) = 0;
    virtual void bindRuntime(Output* log,
                             uint32_t node_id,
                             uint32_t core_id,
                             uint32_t num_neurons,
                             uint32_t neurons_per_pe_cfg,
                             SST::Statistics::Statistic<uint64_t>* stat_routes_entries) = 0;
    virtual void bindFanoutStat(SST::Statistics::Statistic<uint64_t>* stat_fanout_per_spike) = 0;
    virtual void bindRouteRuntimeStats(const RouteRuntimeStatSinks& stats) = 0;

    // 初始化路由（幂等）。返回 true 表示权重驱动路由可用；false 表示应回退 fixed。
    virtual bool initRoutes() = 0;

    // 当前权重驱动路由是否处于启用/可用状态。
    virtual bool routingWeightDrivenActive() const = 0;

    // 权重驱动路由表（进程级共享）。可能为空（例如未启用或构建失败）。
    virtual std::shared_ptr<const RouteMap> routesShared() const = 0;

    // 可选：本地 fallback 路由表（Phase2 允许为空；保留以兼容现有 fanout provider）。
    virtual const RouteMap* routesLocalFallback() const = 0;

    // 基于“当前路由模式 + gating cache（若开启）”计算 fanout。
    virtual void computeFanout(uint32_t source_global, uint32_t neuron_idx,
                               uint64_t now_cycles,
                               std::vector<FanoutEntry>& out_entries,
                               bool& applied_gating) const = 0;

    // 应用门控决策（若 gating 模式关闭则为 no-op）。
    virtual void applyGatingDecision(uint32_t src_global,
                                     const std::vector<uint32_t>& dest_pes,
                                     uint64_t current_cycle,
                                     uint64_t ttl_cycles) = 0;

    virtual bool multicastEnabled() const = 0;
    virtual uint32_t multicastBlockW() const = 0;
    virtual uint32_t multicastBlockH() const = 0;
    virtual uint32_t multicastBlockD() const = 0;
    virtual uint32_t bcsrBlockCols() const = 0;
    virtual RouteSemanticDescriptor describeRouteSemantics() const = 0;
    virtual bool computeMulticastTargets(uint32_t source_global,
                                         uint32_t neuron_idx,
                                         uint64_t now_cycles,
                                         std::vector<BlockTarget>& out_targets,
                                         bool& applied_gating) const = 0;
};

}} // namespace SST::SnnDL
