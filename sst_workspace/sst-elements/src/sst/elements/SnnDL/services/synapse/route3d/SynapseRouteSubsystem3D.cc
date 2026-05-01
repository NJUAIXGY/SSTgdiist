// -*- c++ -*-

#include "SynapseRouteSubsystem3D.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <limits>
#include <sstream>
#include <unordered_map>

#include <sst/core/output.h>
#include <sst/core/statapi/stataccumulator.h>

namespace SST { namespace SnnDL {

// Route3DNodeMapper helpers keep node_id <-> (x,y,z) and block_id <-> layer-local block coordinates consistent.

namespace {

constexpr uint32_t kNativeRuntimeMarkerLogCap = 8u;

enum class IngressPolicy : uint8_t {
    TopLeft = 0,
    TopRight = 1,
    BottomLeft = 2,
    BottomRight = 3,
    Hash4 = 4,
};

bool parseIngressPolicy_(std::string s, IngressPolicy& out) {
    for (char& ch : s) {
        ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    if (s == "top_left") { out = IngressPolicy::TopLeft; return true; }
    if (s == "top_right") { out = IngressPolicy::TopRight; return true; }
    if (s == "bottom_left") { out = IngressPolicy::BottomLeft; return true; }
    if (s == "bottom_right") { out = IngressPolicy::BottomRight; return true; }
    if (s == "hash4") { out = IngressPolicy::Hash4; return true; }
    return false;
}

std::string sourcePrimaryKindFromCfg3D_(const SynapseRouteBuildConfig& cfg) {
    const bool edges_csv_bootstrap =
        cfg.mapping_mode == "edges_csv" && !cfg.mapping_edges_file.empty();
    const bool legacy_route_tables_bootstrap =
        !edges_csv_bootstrap && (!cfg.weights_template.empty() || cfg.real_synapse_inputs_available);
    if (edges_csv_bootstrap) return "edges_csv_bootstrap";
    if (legacy_route_tables_bootstrap && cfg.real_synapse_inputs_available) {
        return "legacy_route_tables_with_real_synapse_inputs";
    }
    if (legacy_route_tables_bootstrap) return "legacy_route_tables_bootstrap";
    if (cfg.real_synapse_inputs_available) return "real_synapse_inputs_only";
    return "legacy_only";
}

uint32_t selectIngressNode3D_(const MeshShape3D& shape,
                              IngressPolicy policy,
                              uint32_t pre_global,
                              uint32_t block_id,
                              uint32_t block_x0,
                              uint32_t block_y0,
                              uint32_t block_z0,
                              uint32_t block_w,
                              uint32_t block_h) {
    uint32_t lx = 0;
    uint32_t ly = 0;
    switch (policy) {
    case IngressPolicy::TopLeft:
        break;
    case IngressPolicy::TopRight:
        lx = block_w - 1;
        break;
    case IngressPolicy::BottomLeft:
        ly = block_h - 1;
        break;
    case IngressPolicy::BottomRight:
        lx = block_w - 1;
        ly = block_h - 1;
        break;
    case IngressPolicy::Hash4: {
        const uint32_t cells = block_w * block_h;
        const uint32_t pick = pre_global ^ (block_id * 0x9e3779b9u);
        const uint32_t idx = (cells > 0) ? (pick % cells) : 0u;
        lx = idx % block_w;
        ly = idx / block_w;
        break;
    }
    default:
        break;
    }
    return coordToNodeId3D(shape, block_x0 + lx, block_y0 + ly, block_z0);
}

bool deriveLegacy2DShape_(uint32_t total_nodes, MeshShape3D& shape) {
    shape = MeshShape3D{};
    if (total_nodes == 0) return false;
    uint32_t w = 1;
    while (w * w < total_nodes) ++w;
    if (w * w != total_nodes) return false;
    shape.dim_x = w;
    shape.dim_y = w;
    shape.dim_z = 1;
    return true;
}

void trimCsvField3D_(std::string& tok) {
    size_t b = 0;
    while (b < tok.size() && std::isspace(static_cast<unsigned char>(tok[b]))) ++b;
    size_t e = tok.size();
    while (e > b && std::isspace(static_cast<unsigned char>(tok[e - 1]))) --e;
    if (b == 0 && e == tok.size()) return;
    tok = tok.substr(b, e - b);
}

bool parseU32CsvField3D_(std::string tok, uint32_t& out) {
    trimCsvField3D_(tok);
    if (tok.empty()) return false;
    try {
        size_t pos = 0;
        const unsigned long long v = std::stoull(tok, &pos, 10);
        if (pos != tok.size()) return false;
        if (v > static_cast<unsigned long long>(std::numeric_limits<uint32_t>::max())) return false;
        out = static_cast<uint32_t>(v);
        return true;
    } catch (...) {
        return false;
    }
}

float parseWeightCsvField3D_(std::string tok, float fallback = 1.0f) {
    trimCsvField3D_(tok);
    if (tok.empty()) return fallback;
    try {
        return std::stof(tok);
    } catch (...) {
        return fallback;
    }
}

std::vector<std::string> splitCsvLine3D_(const std::string& line, char sep) {
    std::vector<std::string> tokens;
    std::string cur;
    std::istringstream ss(line);
    while (std::getline(ss, cur, sep)) {
        trimCsvField3D_(cur);
        tokens.push_back(cur);
    }
    if (!tokens.empty()) return tokens;
    std::istringstream fallback(line);
    while (fallback >> cur) {
        trimCsvField3D_(cur);
        tokens.push_back(cur);
    }
    return tokens;
}

} // namespace

void SynapseRouteSubsystem3D::configure(const SynapseRouteBuildConfig& cfg) {
    cfg_ = cfg;
    legacy_cfg_ = cfg;
    legacy_cfg_.multicast_enable = false;
    legacy_.configure(legacy_cfg_);
    routing_weight_driven_active_ = false;
    routes_shared_.reset();
    routes_local_fallback_.clear();
    route_weights_shared_.reset();
    route_weights_local_fallback_.clear();
    native_route_synthesis_active_ = false;
    native_routes_shared_.reset();
    native_routes_local_.clear();
    native_route_weights_shared_.reset();
    native_route_weights_local_.clear();
    fanout_provider_ready_ = false;
    gating_cache_.clear();
    native_runtime_marker_logs_emitted_ = 0;
    native_runtime_unique_sources_seen_.clear();

    mesh_shape_valid_ = false;
    mesh_shape_ = MeshShape3D{};
    if (!cfg_.mesh_shape.empty()) {
        mesh_shape_valid_ = parseMeshShape3D(cfg_.mesh_shape, mesh_shape_);
    }
    if (!mesh_shape_valid_) {
        mesh_shape_valid_ = deriveLegacy2DShape_(cfg_.total_nodes, mesh_shape_);
    }
}

void SynapseRouteSubsystem3D::configureGating(bool gating_event_mode,
                                              uint64_t gating_ttl_cycles,
                                              bool gating_scope_inputs_only) {
    gating_event_mode_ = gating_event_mode;
    gating_ttl_cycles_ = gating_ttl_cycles;
    gating_scope_inputs_only_ = gating_scope_inputs_only;
    gating_cache_.clear();
    if (fanout_provider_ready_) configureFanoutProvider_();
}

void SynapseRouteSubsystem3D::bindRuntime(SST::Output* log,
                                          uint32_t node_id,
                                          uint32_t core_id,
                                          uint32_t num_neurons,
                                          uint32_t neurons_per_pe_cfg,
                                          SST::Statistics::Statistic<uint64_t>* stat_routes_entries) {
    log_ = log;
    node_id_ = node_id;
    core_id_ = core_id;
    num_neurons_ = num_neurons;
    neurons_per_pe_cfg_ = neurons_per_pe_cfg;
    stat_routes_entries_ = stat_routes_entries;
    legacy_.bindRuntime(log, node_id, core_id, num_neurons, neurons_per_pe_cfg, stat_routes_entries);
    if (fanout_provider_ready_) configureFanoutProvider_();
}

void SynapseRouteSubsystem3D::bindFanoutStat(SST::Statistics::Statistic<uint64_t>* stat_fanout_per_spike) {
    stat_fanout_per_spike_ = stat_fanout_per_spike;
    if (fanout_provider_ready_) configureFanoutProvider_();
}

void SynapseRouteSubsystem3D::bindRouteRuntimeStats(const RouteRuntimeStatSinks& stats) {
    route_runtime_stats_ = stats;
    legacy_.bindRouteRuntimeStats(stats);
}

bool SynapseRouteSubsystem3D::initRoutes() {
    native_route_synthesis_active_ = false;
    native_routes_shared_.reset();
    native_routes_local_.clear();
    native_route_weights_shared_.reset();
    native_route_weights_local_.clear();
    routes_shared_.reset();
    routes_local_fallback_.clear();
    route_weights_shared_.reset();
    route_weights_local_fallback_.clear();
    native_runtime_marker_logs_emitted_ = 0;
    native_runtime_unique_sources_seen_.clear();

    if (tryInitNativeRoutes_()) {
        configureFanoutProvider_();
        return routing_weight_driven_active_;
    }

    legacy_.initRoutes();
    routing_weight_driven_active_ = legacy_.routingWeightDrivenActive();
    routes_shared_ = legacy_.routesShared();
    routes_local_fallback_.clear();
    if (const RouteMap* local_routes = legacy_.routesLocalFallback()) {
        routes_local_fallback_ = *local_routes;
    }
    route_weights_shared_ = legacy_.routeWeightsShared();
    route_weights_local_fallback_.clear();
    if (const RouteWeightMap* local_weights = legacy_.routeWeightsLocalFallback()) {
        route_weights_local_fallback_ = *local_weights;
    }
    configureFanoutProvider_();
    return routing_weight_driven_active_;
}

bool SynapseRouteSubsystem3D::routingWeightDrivenActive() const {
    return routing_weight_driven_active_;
}

std::shared_ptr<const SynapseRouteSubsystem3D::RouteMap> SynapseRouteSubsystem3D::routesShared() const {
    return routes_shared_;
}

const SynapseRouteSubsystem3D::RouteMap* SynapseRouteSubsystem3D::routesLocalFallback() const {
    return &routes_local_fallback_;
}

void SynapseRouteSubsystem3D::computeFanout(uint32_t source_global, uint32_t neuron_idx,
                                            uint64_t now_cycles,
                                            std::vector<FanoutEntry>& out_entries,
                                            bool& applied_gating) const {
    const RouteSemanticDescriptor semantics = describeRouteSemantics();
    if (semantics.native_source_fanout_active) {
        computeFanoutNative3D_(source_global, neuron_idx, now_cycles, out_entries, applied_gating);
        return;
    }
    if (!fanout_provider_ready_) {
        out_entries.clear();
        applied_gating = false;
        return;
    }
    fanout_provider_.computeFanout(source_global, neuron_idx, now_cycles, out_entries, applied_gating);
}

void SynapseRouteSubsystem3D::applyGatingDecision(uint32_t src_global,
                                                  const std::vector<uint32_t>& dest_pes,
                                                  uint64_t current_cycle,
                                                  uint64_t ttl_cycles) {
    if (!gating_event_mode_) return;
    GatingEntry e{};
    e.dest_pes = dest_pes;
    const uint64_t ttl = (ttl_cycles > 0) ? ttl_cycles : gating_ttl_cycles_;
    e.expire_cycle = current_cycle + ttl;
    gating_cache_[src_global] = std::move(e);
}

SynapseRouteSubsystem3D::RouteSemanticDescriptor SynapseRouteSubsystem3D::describeRouteSemantics() const {
    RouteSemanticDescriptor descriptor{};
    descriptor.source_semantics_authority = "legacy_provider";
    descriptor.source_primary_kind = sourcePrimaryKindFromCfg3D_(cfg_);
    descriptor.route_topology = "mesh_3d";
    descriptor.target_semantics_authority = preferNativeTargetSynthesis_()
        ? "native_3d_target_synthesis"
        : "compat_3d_target_synthesis";
    descriptor.real_synapse_inputs_available = cfg_.real_synapse_inputs_available;
    descriptor.native_synapse_source_candidate = false;
    descriptor.native_source_fanout_active = false;
    descriptor.native_target_synthesis_active = preferNativeTargetSynthesis_();
    descriptor.bootstrap_dependency_active = false;
    descriptor.native_bootstrap_source.clear();
    if (descriptor.source_primary_kind == "edges_csv_bootstrap") {
        descriptor.bootstrap_dependency_active = true;
        descriptor.native_bootstrap_source = "edges_csv";
    } else if (
        descriptor.source_primary_kind == "legacy_route_tables_bootstrap"
        || descriptor.source_primary_kind == "legacy_route_tables_with_real_synapse_inputs"
    ) {
        descriptor.bootstrap_dependency_active = true;
        descriptor.native_bootstrap_source = "legacy_route_tables";
    }

    if (!native_route_synthesis_active_) {
        return descriptor;
    }

    descriptor.native_source_fanout_active = true;
    descriptor.bootstrap_dependency_active = true;
    if (cfg_.mapping_mode == "edges_csv") {
        descriptor.source_semantics_authority = "native_3d_route_table";
        descriptor.native_bootstrap_source = "edges_csv";
        if (cfg_.real_synapse_inputs_available) {
            descriptor.source_primary_kind = "native_3d_route_table_with_real_synapse_inputs";
            descriptor.native_synapse_source_candidate = true;
        }
    } else {
        descriptor.source_semantics_authority = "legacy_built_routes_3d";
        descriptor.native_bootstrap_source = "legacy_route_tables";
        descriptor.native_synapse_source_candidate =
            descriptor.source_primary_kind == "legacy_route_tables_with_real_synapse_inputs";
    }
    return descriptor;
}

const SynapseRouteSubsystem3D::RouteMap* SynapseRouteSubsystem3D::activeNativeRouteTable_() const {
    if (native_routes_shared_) return native_routes_shared_.get();
    if (!native_routes_local_.empty()) return &native_routes_local_;
    return nullptr;
}

bool SynapseRouteSubsystem3D::tryApplyNativeGating_(uint32_t source_global,
                                                    uint32_t neuron_idx,
                                                    uint64_t now_cycles,
                                                    std::vector<FanoutEntry>& out_entries,
                                                    bool& applied_gating) const {
    applied_gating = false;
    if (!routing_weight_driven_active_ || !gating_event_mode_) return false;

    const bool scope_ok = !gating_scope_inputs_only_ ? true : (node_id_ <= 3);
    if (!scope_ok) return false;

    auto itg = gating_cache_.find(source_global);
    if (itg == gating_cache_.end() || now_cycles > itg->second.expire_cycle) return false;
    if (neurons_per_pe_cfg_ == 0) return false;
    if (itg->second.dest_pes.empty()) return false;

    appendNativeFanoutEntries_(
        source_global,
        neuron_idx,
        itg->second.dest_pes,
        true,
        out_entries);
    applied_gating = !out_entries.empty();
    return applied_gating;
}

float SynapseRouteSubsystem3D::resolveNativeWeight_(uint32_t source_global, uint32_t dest_global) const {
    const RouteWeightMap* weights = native_route_weights_shared_
        ? native_route_weights_shared_.get()
        : &native_route_weights_local_;
    if (!weights) return 1.0f;
    const uint64_t key =
        (static_cast<uint64_t>(source_global) << 32) | static_cast<uint64_t>(dest_global);
    auto it = weights->find(key);
    if (it == weights->end()) return 1.0f;
    return it->second;
}

void SynapseRouteSubsystem3D::appendNativeFanoutEntries_(uint32_t source_global,
                                                         uint32_t neuron_idx,
                                                         const std::vector<uint32_t>& native_destinations,
                                                         bool destinations_are_pes,
                                                         std::vector<FanoutEntry>& out_entries) const {
    const uint32_t denom = neurons_per_pe_cfg_;
    if (denom == 0) return;

    for (uint32_t raw_dest : native_destinations) {
        FanoutEntry fe{};
        if (destinations_are_pes) {
            fe.dest_node = raw_dest;
            fe.dest_global = (raw_dest * denom) + neuron_idx;
        } else {
            fe.dest_global = raw_dest;
            fe.dest_node = raw_dest / denom;
        }
        fe.weight = resolveNativeWeight_(source_global, fe.dest_global);
        out_entries.push_back(fe);
    }
}

void SynapseRouteSubsystem3D::emitNativeRuntimeMarker_(uint32_t source_global,
                                                       size_t fanout_count,
                                                       bool applied_gating) const {
    if (!log_) return;
    if (fanout_count == 0u) return;
    if (native_runtime_marker_logs_emitted_ >= kNativeRuntimeMarkerLogCap) return;
    ++native_runtime_marker_logs_emitted_;
    log_->verbose(
        CALL_INFO,
        0,
        0,
        "[route3d-native-runtime] node=%u core=%u source_global=%u fanout=%zu applied_gating=%u\n",
        node_id_,
        core_id_,
        source_global,
        fanout_count,
        applied_gating ? 1u : 0u);
}

void SynapseRouteSubsystem3D::recordNativeRuntimeStats_(uint32_t source_global,
                                                        size_t fanout_count,
                                                        bool applied_gating) const {
    if (fanout_count == 0u) return;

    if (route_runtime_stats_.route3d_native_activation_total) {
        ++(*route_runtime_stats_.route3d_native_activation_total);
    }
    if (route_runtime_stats_.stat_route3d_native_activation_total) {
        route_runtime_stats_.stat_route3d_native_activation_total->addData(1);
    }
    if (applied_gating) {
        if (route_runtime_stats_.route3d_native_gating_activation_total) {
            ++(*route_runtime_stats_.route3d_native_gating_activation_total);
        }
        if (route_runtime_stats_.stat_route3d_native_gating_activation_total) {
            route_runtime_stats_.stat_route3d_native_gating_activation_total->addData(1);
        }
    } else {
        if (route_runtime_stats_.route3d_native_direct_activation_total) {
            ++(*route_runtime_stats_.route3d_native_direct_activation_total);
        }
        if (route_runtime_stats_.stat_route3d_native_direct_activation_total) {
            route_runtime_stats_.stat_route3d_native_direct_activation_total->addData(1);
        }
    }

    const bool first_source = native_runtime_unique_sources_seen_.insert(source_global).second;
    if (first_source && route_runtime_stats_.route3d_native_unique_sources_total) {
        ++(*route_runtime_stats_.route3d_native_unique_sources_total);
    }
    if (first_source && route_runtime_stats_.stat_route3d_native_unique_sources_total) {
        route_runtime_stats_.stat_route3d_native_unique_sources_total->addData(1);
    }
}

void SynapseRouteSubsystem3D::computeFanoutNative3D_(uint32_t source_global,
                                                     uint32_t neuron_idx,
                                                     uint64_t now_cycles,
                                                     std::vector<FanoutEntry>& out_entries,
                                                     bool& applied_gating) const {
    out_entries.clear();
    applied_gating = false;

    const RouteMap* route_tbl = activeNativeRouteTable_();
    if (!route_tbl) return;

    if (tryApplyNativeGating_(source_global, neuron_idx, now_cycles, out_entries, applied_gating)) {
        if (stat_fanout_per_spike_ && !out_entries.empty()) {
            stat_fanout_per_spike_->addData(static_cast<uint64_t>(out_entries.size()));
        }
        recordNativeRuntimeStats_(source_global, out_entries.size(), applied_gating);
        emitNativeRuntimeMarker_(source_global, out_entries.size(), applied_gating);
        return;
    }

    auto it = route_tbl->find(source_global);
    if (it == route_tbl->end() || it->second.empty()) return;

    appendNativeFanoutEntries_(
        source_global,
        neuron_idx,
        it->second,
        false,
        out_entries);

    if (routing_weight_driven_active_ && stat_fanout_per_spike_ && !out_entries.empty()) {
        stat_fanout_per_spike_->addData(static_cast<uint64_t>(out_entries.size()));
    }
    recordNativeRuntimeStats_(source_global, out_entries.size(), applied_gating);
    emitNativeRuntimeMarker_(source_global, out_entries.size(), applied_gating);
}

bool SynapseRouteSubsystem3D::tryInitNativeRoutes_() {
    native_route_synthesis_active_ = false;
    if (!cfg_.routing_weight_driven) return false;
    if (!cfg_.route3d_native_targets) return false;
    if (!mesh_shape_valid_ || !mesh_shape_.valid() || mesh_shape_.dim_z <= 1) return false;

    bool native_routes_ready = false;
    if (cfg_.mapping_mode == "edges_csv") {
        if (cfg_.mapping_edges_file.empty()) return false;
        native_routes_ready = buildNativeRoutesFromEdgesCsv3D_();
    } else {
        native_routes_ready = buildNativeRoutesFromLegacyBuiltRoutes3D_();
    }
    if (!native_routes_ready) return false;

    routes_shared_ = native_routes_shared_;
    routes_local_fallback_ = native_routes_local_;
    route_weights_shared_ = native_route_weights_shared_;
    route_weights_local_fallback_ = native_route_weights_local_;
    routing_weight_driven_active_ = true;
    native_route_synthesis_active_ = true;
    return true;
}

bool SynapseRouteSubsystem3D::buildNativeRoutesFromEdgesCsv3D_() {
    native_routes_local_.clear();
    native_route_weights_local_.clear();

    std::ifstream fin(cfg_.mapping_edges_file);
    if (!fin.good()) return false;

    std::string line;
    if (cfg_.mapping_csv_has_header) std::getline(fin, line);
    const char sep = cfg_.mapping_csv_separator.empty() ? ',' : cfg_.mapping_csv_separator[0];
    const uint32_t neurons_per_pe = (neurons_per_pe_cfg_ > 0) ? neurons_per_pe_cfg_ : cfg_.neurons_per_pe;
    if (neurons_per_pe == 0) return false;

    std::unordered_map<uint32_t, std::vector<std::pair<float, uint32_t>>> candidates;
    while (std::getline(fin, line)) {
        if (line.empty()) continue;
        const auto toks = splitCsvLine3D_(line, sep);
        if (toks.size() < 2) continue;

        uint32_t src = 0;
        uint32_t dst = 0;
        if (!parseU32CsvField3D_(toks[0], src) || !parseU32CsvField3D_(toks[1], dst)) continue;
        const float w = (toks.size() >= 3) ? parseWeightCsvField3D_(toks[2], 1.0f) : 1.0f;
        if (std::fabs(w) <= cfg_.routing_epsilon) continue;

        const uint32_t src_pe = src / neurons_per_pe;
        const uint32_t dst_pe = dst / neurons_per_pe;
        if (cfg_.route_exclude_self_pe && src_pe == dst_pe) continue;

        candidates[src].emplace_back(w, dst);
    }

    if (candidates.empty()) return false;

    for (auto& kv : candidates) {
        auto& lst = kv.second;
        if (cfg_.routing_topk_per_pe > 0) {
            std::unordered_map<uint32_t, std::vector<std::pair<float, uint32_t>>> by_pe;
            for (const auto& cand : lst) {
                by_pe[cand.second / neurons_per_pe].push_back(cand);
            }
            std::vector<std::pair<float, uint32_t>> merged;
            for (auto& grouped : by_pe) {
                auto& vec = grouped.second;
                if (vec.size() > cfg_.routing_topk_per_pe) {
                    std::partial_sort(
                        vec.begin(),
                        vec.begin() + cfg_.routing_topk_per_pe,
                        vec.end(),
                        [](const auto& lhs, const auto& rhs) {
                            const float aw = std::fabs(lhs.first);
                            const float bw = std::fabs(rhs.first);
                            if (aw == bw) return lhs.second < rhs.second;
                            return aw > bw;
                        });
                    vec.resize(cfg_.routing_topk_per_pe);
                }
                merged.insert(merged.end(), vec.begin(), vec.end());
            }
            lst = std::move(merged);
        }

        if (cfg_.routing_topk > 0 && lst.size() > cfg_.routing_topk) {
            std::partial_sort(
                lst.begin(),
                lst.begin() + cfg_.routing_topk,
                lst.end(),
                [](const auto& lhs, const auto& rhs) {
                    const float aw = std::fabs(lhs.first);
                    const float bw = std::fabs(rhs.first);
                    if (aw == bw) return lhs.second < rhs.second;
                    return aw > bw;
                });
            lst.resize(cfg_.routing_topk);
        }

        std::unordered_map<uint32_t, float> best_weight_by_dest;
        for (const auto& cand : lst) {
            auto hit = best_weight_by_dest.find(cand.second);
            if (hit == best_weight_by_dest.end() || std::fabs(cand.first) > std::fabs(hit->second)) {
                best_weight_by_dest[cand.second] = cand.first;
            }
        }

        std::vector<uint32_t> routes;
        routes.reserve(best_weight_by_dest.size());
        for (const auto& cand : best_weight_by_dest) {
            routes.push_back(cand.first);
            const uint64_t key =
                (static_cast<uint64_t>(kv.first) << 32) | static_cast<uint64_t>(cand.first);
            native_route_weights_local_[key] = cand.second;
        }
        std::sort(routes.begin(), routes.end());
        native_routes_local_[kv.first] = std::move(routes);
    }

    if (native_routes_local_.empty()) return false;
    native_routes_shared_ = std::make_shared<RouteMap>(native_routes_local_);
    native_route_weights_shared_ = std::make_shared<RouteWeightMap>(native_route_weights_local_);
    return true;
}

bool SynapseRouteSubsystem3D::buildNativeRoutesFromLegacyBuiltRoutes3D_() {
    native_routes_shared_.reset();
    native_routes_local_.clear();
    native_route_weights_shared_.reset();
    native_route_weights_local_.clear();

    if (!legacy_.initRoutes()) return false;

    native_routes_shared_ = legacy_.routesShared();
    if (const RouteMap* local_routes = legacy_.routesLocalFallback()) {
        native_routes_local_ = *local_routes;
    }
    native_route_weights_shared_ = legacy_.routeWeightsShared();
    if (const RouteWeightMap* local_weights = legacy_.routeWeightsLocalFallback()) {
        native_route_weights_local_ = *local_weights;
    }

    return native_routes_shared_ || !native_routes_local_.empty();
}

uint32_t SynapseRouteSubsystem3D::multicastBlockDepthCompat_() const {
    return 1u;
}

uint32_t SynapseRouteSubsystem3D::resolvedMulticastBlockDepth_() const {
    const uint32_t configured_block_d = (cfg_.multicast_block_d > 0) ? cfg_.multicast_block_d : 1u;
    if (cfg_.multicast_die_local_only) return 1u;
    return configured_block_d;
}

bool SynapseRouteSubsystem3D::preferNativeTargetSynthesis_() const {
    return cfg_.route3d_native_targets &&
           mesh_shape_valid_ &&
           mesh_shape_.valid() &&
           mesh_shape_.dim_z > 1 &&
           resolvedMulticastBlockDepth_() > 1u;
}

bool SynapseRouteSubsystem3D::multicastGeometryValid_() const {
    if (!mesh_shape_valid_ || !mesh_shape_.valid()) return false;
    if (cfg_.multicast_block_w == 0 || cfg_.multicast_block_h == 0) return false;
    const uint32_t block_d = preferNativeTargetSynthesis_() ? resolvedMulticastBlockDepth_() : multicastBlockDepthCompat_();
    if (block_d == 0) return false;
    if ((mesh_shape_.dim_x % cfg_.multicast_block_w) != 0) return false;
    if ((mesh_shape_.dim_y % cfg_.multicast_block_h) != 0) return false;
    if ((mesh_shape_.dim_z % block_d) != 0) return false;
    const uint64_t cells =
        static_cast<uint64_t>(cfg_.multicast_block_w) *
        static_cast<uint64_t>(cfg_.multicast_block_h) *
        static_cast<uint64_t>(block_d);
    return cells > 0u && cells <= static_cast<uint64_t>(kMaxMulticastBlockCells);
}

bool SynapseRouteSubsystem3D::multicastEnabled() const {
    return routingWeightDrivenActive() && cfg_.multicast_enable && multicastGeometryValid_();
}

uint32_t SynapseRouteSubsystem3D::multicastBlockD() const {
    return preferNativeTargetSynthesis_() ? resolvedMulticastBlockDepth_() : multicastBlockDepthCompat_();
}

bool SynapseRouteSubsystem3D::computeMulticastTargets(uint32_t source_global,
                                                      uint32_t neuron_idx,
                                                      uint64_t now_cycles,
                                                      std::vector<BlockTarget>& out_targets,
                                                      bool& applied_gating) const {
    out_targets.clear();
    applied_gating = false;
    if (!multicastEnabled()) return false;

    const RouteSemanticDescriptor semantics = describeRouteSemantics();
    if (semantics.native_target_synthesis_active) {
        return computeMulticastTargetsNative3D_(source_global, neuron_idx, now_cycles, out_targets, applied_gating);
    }
    return computeMulticastTargetsCompatFallback_(source_global, neuron_idx, now_cycles, out_targets, applied_gating);
}

bool SynapseRouteSubsystem3D::synthesizeMulticastTargetsForBlockDepth_(uint32_t source_global,
                                                                       uint32_t neuron_idx,
                                                                       uint64_t now_cycles,
                                                                       uint32_t block_d,
                                                                       std::vector<BlockTarget>& out_targets,
                                                                       bool& applied_gating) const {
    out_targets.clear();
    applied_gating = false;
    if (block_d == 0) return false;

    IngressPolicy ingress_policy{};
    if (!parseIngressPolicy_(cfg_.multicast_ingress_policy, ingress_policy)) {
        return false;
    }

    std::vector<FanoutEntry> fanouts;
    computeFanout(source_global, neuron_idx, now_cycles, fanouts, applied_gating);
    if (fanouts.empty()) return false;

    const uint32_t block_w = cfg_.multicast_block_w;
    const uint32_t block_h = cfg_.multicast_block_h;
    const uint32_t blocks_per_volume = blocksPerVolume3D(mesh_shape_, block_w, block_h, block_d);
    if (blocks_per_volume == 0) return false;

    const uint32_t neurons_per_pe = (neurons_per_pe_cfg_ > 0) ? neurons_per_pe_cfg_ : cfg_.neurons_per_pe;
    const uint32_t cores_per_pe = (cfg_.cores_per_pe > 0) ? cfg_.cores_per_pe : 1u;
    const uint32_t neurons_per_core =
        (neurons_per_pe > 0 && cores_per_pe > 0 && (neurons_per_pe % cores_per_pe) == 0)
            ? (neurons_per_pe / cores_per_pe)
            : 0u;

    std::unordered_map<uint32_t, BlockTarget> grouped;
    grouped.reserve(fanouts.size());

    for (const auto& fe : fanouts) {
        MeshCoord3D coord{};
        if (!nodeIdToCoord3D(mesh_shape_, fe.dest_node, coord)) continue;

        const uint32_t block_id =
            encodeBlockId3DVolumetric(mesh_shape_, block_w, block_h, block_d, coord.x, coord.y, coord.z);
        const uint32_t block_x0 = (coord.x / block_w) * block_w;
        const uint32_t block_y0 = (coord.y / block_h) * block_h;
        const uint32_t block_z0 = (coord.z / block_d) * block_d;
        const uint32_t local_z = coord.z - block_z0;
        const uint32_t local_y = coord.y - block_y0;
        const uint32_t local_x = coord.x - block_x0;
        const uint32_t idx = ((local_z * block_h) + local_y) * block_w + local_x;
        if (idx >= kMaxMulticastBlockCells) continue;

        auto it = grouped.find(block_id);
        if (it == grouped.end()) {
            BlockTarget target{};
            target.block_id = block_id;
            target.block_z = block_z0;
            target.block_d = block_d;
            target.ingress_node = selectIngressNode3D_(
                mesh_shape_,
                ingress_policy,
                source_global,
                block_id,
                block_x0,
                block_y0,
                block_z0,
                block_w,
                block_h);
            it = grouped.emplace(block_id, target).first;
        }

        uint32_t core_mask = 1u;
        if (neurons_per_core > 0 && neurons_per_pe > 0) {
            const uint32_t local_neuron = fe.dest_global % neurons_per_pe;
            const uint32_t dest_core = local_neuron / neurons_per_core;
            if (dest_core >= 32u) continue;
            core_mask = (1u << dest_core);
        }
        it->second.core_mask[idx] |= core_mask;
    }

    out_targets.reserve(grouped.size());
    for (const auto& kv : grouped) {
        bool any = false;
        for (uint32_t mask : kv.second.core_mask) {
            if (mask != 0u) {
                any = true;
                break;
            }
        }
        if (any) out_targets.push_back(kv.second);
    }
    std::sort(out_targets.begin(), out_targets.end(), [](const BlockTarget& lhs, const BlockTarget& rhs) {
        if (lhs.block_id != rhs.block_id) return lhs.block_id < rhs.block_id;
        return lhs.ingress_node < rhs.ingress_node;
    });
    return !out_targets.empty();
}

bool SynapseRouteSubsystem3D::computeMulticastTargetsNative3D_(uint32_t source_global,
                                                               uint32_t neuron_idx,
                                                               uint64_t now_cycles,
                                                               std::vector<BlockTarget>& out_targets,
                                                               bool& applied_gating) const {
    return synthesizeMulticastTargetsForBlockDepth_(
        source_global,
        neuron_idx,
        now_cycles,
        resolvedMulticastBlockDepth_(),
        out_targets,
        applied_gating);
}

bool SynapseRouteSubsystem3D::computeMulticastTargetsCompatFallback_(uint32_t source_global,
                                                                     uint32_t neuron_idx,
                                                                     uint64_t now_cycles,
                                                                     std::vector<BlockTarget>& out_targets,
                                                                     bool& applied_gating) const {
    return synthesizeMulticastTargetsForBlockDepth_(
        source_global,
        neuron_idx,
        now_cycles,
        multicastBlockDepthCompat_(),
        out_targets,
        applied_gating);
}

void SynapseRouteSubsystem3D::configureFanoutProvider_() {
    SnnRouteProvider::Config cfg{};
    cfg.routing_weight_driven = routing_weight_driven_active_;
    cfg.log_weight_details = cfg_.log_weight_details;
    cfg.num_neurons = num_neurons_;
    cfg.neurons_per_pe_cfg = neurons_per_pe_cfg_;
    cfg.node_id = node_id_;
    cfg.gating_event_mode = gating_event_mode_;
    cfg.gating_scope_inputs_only = gating_scope_inputs_only_;
    cfg.gating_cache = &gating_cache_;
    cfg.out = log_;
    cfg.stat_fanout = stat_fanout_per_spike_;

    const RouteWeightMap* route_weights =
        route_weights_shared_ ? route_weights_shared_.get() : &route_weights_local_fallback_;
    fanout_provider_.configure(cfg, routes_shared_, &routes_local_fallback_, route_weights);
    fanout_provider_ready_ = true;
}

}} // namespace SST::SnnDL
