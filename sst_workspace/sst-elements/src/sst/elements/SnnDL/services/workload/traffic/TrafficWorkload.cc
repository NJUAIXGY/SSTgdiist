// -*- c++ -*-
//
// TrafficWorkload implementation
//

#include "workload/traffic/TrafficWorkload.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cinttypes>
#include <cstdlib>
#include <mutex>
#include <random>
#include <unordered_map>
#include <unordered_set>

#include <sst/core/output.h>
#include <sst/core/params.h>

#include "api/MulticastLimits.h"
#include "api/NocSpikeTransport.h"
#include "api/ISynapseRoute.h"
#include "events/NocPacketEvent.h"
#include "workload/layout/NormalizedNeuronLayout.h"
#include "synapse/route/SpikeNocCodec.h"
#include "synapse/route/SpikeTileNocCodec.h"
#include "services/synapse/route/SpikeCommSubsystem.h"
#include "services/synapse/route/SynapseRouteSubsystem.h"
#include "services/synapse/route3d/Route3DNodeMapper.h"
#include "synapse/route3d/SynapseRouteSubsystem3D.h"

namespace SST { namespace SnnDL {

namespace {

inline uint64_t mixSeed_(uint64_t seed, uint32_t node_id, uint32_t core_id, uint32_t seq) {
    uint64_t x = seed;
    x ^= (static_cast<uint64_t>(node_id) << 32);
    x ^= (static_cast<uint64_t>(core_id) << 16);
    x ^= static_cast<uint64_t>(seq);
    x ^= (x >> 33);
    x *= 0xff51afd7ed558ccdULL;
    x ^= (x >> 33);
    x *= 0xc4ceb9fe1a85ec53ULL;
    x ^= (x >> 33);
    return x;
}

inline bool deriveSquareMeshW_(uint32_t total_nodes, uint32_t& out_w) {
    out_w = 0;
    if (total_nodes == 0) return false;
    const double root = std::sqrt(static_cast<double>(total_nodes));
    const uint32_t w = static_cast<uint32_t>(std::llround(root));
    if (w == 0) return false;
    if (w * w != total_nodes) return false;
    out_w = w;
    return true;
}

inline uint32_t popcount64_(uint64_t x) {
    return static_cast<uint32_t>(__builtin_popcountll(static_cast<unsigned long long>(x)));
}

bool meshShapeHasMultipleLayers_(const std::string& mesh_shape) {
    const auto p0 = mesh_shape.find('x');
    if (p0 == std::string::npos) return false;
    const auto p1 = mesh_shape.find('x', p0 + 1);
    if (p1 == std::string::npos) return false;
    char* endp = nullptr;
    const long z = std::strtol(mesh_shape.c_str() + static_cast<long>(p1 + 1), &endp, 10);
    return endp && *endp == '\0' && z > 1;
}

bool resolveTrafficMeshShape_(const SST::Params* params, uint32_t total_nodes, MeshShape3D& out_shape) {
    out_shape = MeshShape3D{};
    if (params) {
        const std::string mesh_shape = params->find<std::string>("mesh_shape", "");
        if (!mesh_shape.empty()) {
            if (!parseMeshShape3D(mesh_shape, out_shape)) return false;
            return out_shape.totalNodes() == total_nodes;
        }
    }

    uint32_t mesh_w = 0;
    if (!deriveSquareMeshW_(total_nodes, mesh_w)) return false;
    out_shape.dim_x = mesh_w;
    out_shape.dim_y = mesh_w;
    out_shape.dim_z = 1;
    return true;
}

enum class TrafficHomeAccessClass {
    TierLocalHome,
    SameXYCrossTier,
    RemoteHome,
};

uint32_t homeStackForTrafficNode_(const MeshShape3D& shape,
                                  const std::string& memory_kind,
                                  uint32_t node_id) {
    if (!shape.valid()) return 0;
    if (memory_kind == "legacy_per_pe") return node_id;

    MeshCoord3D coord{};
    if (!nodeIdToCoord3D(shape, node_id, coord)) return 0;

    const uint32_t mid_x = std::max<uint32_t>(1, shape.dim_x / 2);
    const uint32_t mid_y = std::max<uint32_t>(1, shape.dim_y / 2);
    const uint32_t quadrant_x = (coord.x < mid_x) ? 0u : 1u;
    const uint32_t quadrant_y = (coord.y < mid_y) ? 0u : 1u;
    return quadrant_y * 2u + quadrant_x;
}

TrafficHomeAccessClass classifyTrafficHomeAccess_(const MeshShape3D& shape,
                                                  const std::string& memory_kind,
                                                  uint32_t source_node,
                                                  uint32_t dest_node) {
    if (!shape.valid()) return TrafficHomeAccessClass::RemoteHome;

    MeshCoord3D src_coord{};
    MeshCoord3D dst_coord{};
    if (!nodeIdToCoord3D(shape, source_node, src_coord) ||
        !nodeIdToCoord3D(shape, dest_node, dst_coord)) {
        return TrafficHomeAccessClass::RemoteHome;
    }

    const uint32_t src_stack = homeStackForTrafficNode_(shape, memory_kind, source_node);
    const uint32_t dst_stack = homeStackForTrafficNode_(shape, memory_kind, dest_node);
    if (src_stack != dst_stack) return TrafficHomeAccessClass::RemoteHome;
    if (src_coord.z == 0 && dst_coord.z == 0) return TrafficHomeAccessClass::TierLocalHome;
    return TrafficHomeAccessClass::SameXYCrossTier;
}

void noteTrafficHomeAwareDemand_(TrafficWorkload::SemanticMemoryDemand& demand,
                                 TrafficHomeAccessClass access_class) {
    switch (access_class) {
        case TrafficHomeAccessClass::TierLocalHome:
            demand.tier_local_home_gather_demands += 1;
            demand.tier_local_home_stream_region_demands += 1;
            break;
        case TrafficHomeAccessClass::SameXYCrossTier:
            demand.same_xy_cross_tier_gather_demands += 1;
            demand.same_xy_cross_tier_stream_region_demands += 1;
            break;
        case TrafficHomeAccessClass::RemoteHome:
        default:
            demand.remote_home_gather_demands += 1;
            demand.remote_home_stream_region_demands += 1;
            break;
    }
}

bool resolveSelfBlockIndex3D_(const MeshShape3D& mesh_shape,
                              uint32_t node_id,
                              uint32_t block_w,
                              uint32_t block_h,
                              uint32_t block_d,
                              uint32_t block_id,
                              uint32_t& out_idx,
                              uint32_t& out_block_cells) {
    out_idx = 0;
    out_block_cells = 0;
    if (!mesh_shape.valid()) return false;
    if (block_w == 0 || block_h == 0 || block_d == 0) return false;

    out_block_cells = block_w * block_h * block_d;
    if (out_block_cells == 0 || out_block_cells > kMaxMulticastBlockCells) return false;

    MeshCoord3D self{};
    if (!nodeIdToCoord3D(mesh_shape, node_id, self)) return false;

    uint32_t block_x0 = 0;
    uint32_t block_y0 = 0;
    uint32_t block_z0 = 0;
    if (block_d <= 1) {
        if (!decodeBlockId3D(mesh_shape, block_w, block_h, block_id, block_x0, block_y0, block_z0)) return false;
    } else {
        if (!decodeBlockId3DVolumetric(mesh_shape, block_w, block_h, block_d, block_id, block_x0, block_y0, block_z0)) return false;
    }

    if (self.x < block_x0 || self.y < block_y0 || self.z < block_z0) return false;
    if (self.x >= block_x0 + block_w || self.y >= block_y0 + block_h || self.z >= block_z0 + block_d) return false;

    const uint32_t local_x = self.x - block_x0;
    const uint32_t local_y = self.y - block_y0;
    const uint32_t local_z = self.z - block_z0;
    out_idx = ((local_z * block_h) + local_y) * block_w + local_x;
    return out_idx < out_block_cells && out_idx < kMaxMulticastBlockCells;
}

std::string normalizeSynapseRouteImpl_(std::string impl) {
    for (char& ch : impl) {
        if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    }
    if (impl.empty()) return "legacy_2d";
    if (impl == "3d" || impl == "native3d") return "native_3d";
    if (impl == "legacy" || impl == "2d") return "legacy_2d";
    return impl;
}

std::unique_ptr<ISynapseRoute> makeSynapseRoute_(const SST::Params& params) {
    std::string impl = normalizeSynapseRouteImpl_(params.find<std::string>("synapse_route_impl", "legacy_2d"));
    if (impl == "auto") {
        const bool native_3d_enable = params.find<int>("native_3d_enable", 0) != 0;
        const std::string mesh_shape = params.find<std::string>("mesh_shape", "");
        impl = (native_3d_enable || meshShapeHasMultipleLayers_(mesh_shape)) ? "native_3d" : "legacy_2d";
    }
    if (impl == "native_3d") {
        return std::make_unique<SynapseRouteSubsystem3D>();
    }
    return std::make_unique<SynapseRouteSubsystem>();
}

struct SpikeKeyGroupState {
    bool expected_set = false;
    bool meta_set = false;
    uint16_t block_w_h = 0;
    uint16_t block_d = 1;
    uint32_t pre_global = 0;
    uint32_t block_id = 0;
    uint32_t ingress_node = 0;
    uint32_t meta_mismatch = 0;
    std::array<uint64_t, kMaxSpikeKeyEndpoints / 64> expected{}; // key=(idx*32+core)
    std::array<uint64_t, kMaxSpikeKeyEndpoints / 64> received{};
    uint32_t duplicates = 0;
};

struct SpikeKeyGroupSummary {
    uint64_t groups_total = 0;
    uint64_t groups_ok = 0;
    uint64_t groups_bad = 0;
    uint64_t endpoints_expected = 0;
    uint64_t endpoints_received = 0;
    uint64_t endpoints_missing = 0;
    uint64_t endpoints_extra = 0;
    uint64_t endpoints_duplicates = 0;
    uint64_t meta_mismatch = 0;
};

struct SpikeKeyGroupBadDetail {
    uint64_t group_id = 0;
    uint32_t exp = 0;
    uint32_t rcv = 0;
    uint32_t miss = 0;
    uint32_t extra = 0;
    uint32_t dup = 0;
    uint32_t meta_mismatch = 0;
    uint16_t block_w_h = 0;
    uint16_t block_d = 1;
    uint32_t pre_global = 0;
    uint32_t block_id = 0;
    uint32_t ingress_node = 0;
};

class SpikeKeyGroupTracker final {
public:
    static void noteRx(uint64_t group_id,
                       uint32_t cores_per_pe,
                       const SpikeNocCodec::WireSpikeKeyV2& ws,
                       const SpikeNocCodec::DecodedSpikeKeyMeta& meta,
                       uint32_t idx_self,
                       uint16_t dst_endpoint) {
        if (cores_per_pe == 0 || cores_per_pe > kMaxCoresPerPe) return;
        if (dst_endpoint >= cores_per_pe) return;

        const uint32_t bw = meta.block_w;
        const uint32_t bh = meta.block_h;
        const uint32_t bd = meta.block_d;
        if (bw == 0 || bh == 0 || bd == 0) return;
        const uint32_t block_cells = meta.block_cells;
        if (block_cells == 0 || block_cells > kMaxMulticastBlockCells) return;
        if (idx_self >= block_cells) return;

        const uint32_t key_self = idx_self * kMaxCoresPerPe + static_cast<uint32_t>(dst_endpoint);
        const uint32_t w_self = key_self >> 6;
        const uint64_t bit_self = 1ull << (key_self & 63u);

        std::lock_guard<std::mutex> g(mtx_);
        auto& st = groups_[group_id];
        if (!st.meta_set) {
            st.meta_set = true;
            st.block_w_h = ws.block_w_h;
            st.block_d = static_cast<uint16_t>(std::min<uint32_t>(bd, 0xffffu));
            st.pre_global = ws.pre_global;
            st.block_id = ws.block_id;
            st.ingress_node = ws.ingress_node;
        } else {
            if (st.block_w_h != ws.block_w_h || st.block_d != static_cast<uint16_t>(std::min<uint32_t>(bd, 0xffffu)) ||
                st.pre_global != ws.pre_global ||
                st.block_id != ws.block_id || st.ingress_node != ws.ingress_node) {
                st.meta_mismatch += 1;
            }
        }
        if (!st.expected_set) {
            st.expected_set = true;
            std::array<uint64_t, kMaxSpikeKeyEndpoints / 64> expected{};
            for (uint32_t idx = 0; idx < block_cells; ++idx) {
                const uint32_t mask = ws.core_mask[idx];
                if (!mask) continue;
                for (uint32_t bit = 0; bit < cores_per_pe; ++bit) {
                    if ((mask & (1u << bit)) == 0u) continue;
                    const uint32_t key = idx * kMaxCoresPerPe + bit; // [0..2047]
                    const uint32_t w = key >> 6;
                    const uint32_t b = key & 63u;
                    if (w < expected.size()) expected[w] |= (1ull << b);
                }
            }
            st.expected = expected;
        }

        // Duplicate detection (same endpoint delivered more than once for this group_id)
        if (w_self < st.received.size()) {
            if (st.received[w_self] & bit_self) st.duplicates += 1;
            st.received[w_self] |= bit_self;
        }
    }

    static bool noteCoreFinish(uint32_t total_nodes,
                              uint32_t cores_per_pe,
                              uint32_t node_id,
                              uint32_t core_id,
                              SST::Output* log,
                              uint32_t bad_group_log_cap,
                              bool fatal_on_bad) {
        if (total_nodes == 0 || cores_per_pe == 0) return true;

        SpikeKeyGroupSummary summary{};
        std::vector<SpikeKeyGroupBadDetail> bad_details;
        bool should_print = false;
        bool ok = true;

        {
            std::lock_guard<std::mutex> g(mtx_);
            if (expected_total_cores_ == 0) expected_total_cores_ = total_nodes * cores_per_pe;
            const uint32_t core_key = node_id * cores_per_pe + core_id;
            finished_cores_.insert(core_key);
            if (!summary_log_ && log) summary_log_ = log;

            if (!finalized_ && finished_cores_.size() >= expected_total_cores_) {
                finalized_ = true;
                summary.groups_total = groups_.size();
                for (const auto& kv : groups_) {
                    const auto& st = kv.second;
                    if (!st.expected_set) continue;

                    uint32_t exp = 0;
                    uint32_t rcv = 0;
                    uint32_t miss = 0;
                    uint32_t extra = 0;
                    for (size_t i = 0; i < st.expected.size(); ++i) {
                        const uint64_t e = st.expected[i];
                        const uint64_t r = st.received[i];
                        exp += popcount64_(e);
                        rcv += popcount64_(r);
                        miss += popcount64_(e & ~r);
                        extra += popcount64_(r & ~e);
                    }

                    summary.endpoints_expected += exp;
                    summary.endpoints_received += rcv;
                    summary.endpoints_missing += miss;
                    summary.endpoints_extra += extra;
                    summary.endpoints_duplicates += st.duplicates;
                    summary.meta_mismatch += st.meta_mismatch;

                    const bool group_ok = (miss == 0u) && (extra == 0u) && (st.duplicates == 0u) &&
                                          (st.meta_mismatch == 0u) && (exp == rcv);
                    if (group_ok) summary.groups_ok += 1;
                    else {
                        summary.groups_bad += 1;
                        if (bad_group_log_cap > 0 && bad_details.size() < bad_group_log_cap) {
                            bad_details.push_back(SpikeKeyGroupBadDetail{
                                /*group_id=*/kv.first,
                                /*exp=*/exp,
                                /*rcv=*/rcv,
                                /*miss=*/miss,
                                /*extra=*/extra,
                                /*dup=*/st.duplicates,
                                /*meta_mismatch=*/st.meta_mismatch,
                                /*block_w_h=*/st.block_w_h,
                                /*block_d=*/st.block_d,
                                /*pre_global=*/st.pre_global,
                                /*block_id=*/st.block_id,
                                /*ingress_node=*/st.ingress_node,
                            });
                        }
                    }
                }

                ok = (summary.groups_bad == 0) && (summary.endpoints_missing == 0) && (summary.endpoints_extra == 0) &&
                     (summary.endpoints_duplicates == 0) && (summary.meta_mismatch == 0);
                cached_summary_ = summary;
                should_print = true;
            } else if (finalized_) {
                summary = cached_summary_;
                ok = (summary.groups_bad == 0) && (summary.endpoints_missing == 0) && (summary.endpoints_extra == 0) &&
                     (summary.endpoints_duplicates == 0) && (summary.meta_mismatch == 0);
            }
        }

        if (should_print && summary_log_) {
            if (!ok && fatal_on_bad) {
                for (const auto& d : bad_details) {
                    summary_log_->verbose(
                        CALL_INFO, 0, 0,
                        "[traffic][sk-group-bad] group_id=0x%016" PRIx64 " exp=%u rcv=%u missing=%u extra=%u dup=%u"
                        " meta_mismatch=%u block_w_h=0x%04x block_d=%u pre_global=%u block_id=%u ingress_node=%u\n",
                        d.group_id,
                        d.exp,
                        d.rcv,
                        d.miss,
                        d.extra,
                        d.dup,
                        d.meta_mismatch,
                        static_cast<unsigned>(d.block_w_h),
                        static_cast<unsigned>(d.block_d),
                        d.pre_global,
                        d.block_id,
                        d.ingress_node);
                }
                summary_log_->fatal(
                    CALL_INFO, -1,
                    "SpikeKey group coverage self-check failed: [traffic][sk-group] groups_total=%" PRIu64 " ok=%" PRIu64
                    " bad=%" PRIu64 " endpoints_expected=%" PRIu64 " received=%" PRIu64 " missing=%" PRIu64
                    " extra=%" PRIu64 " dup=%" PRIu64 " meta_mismatch=%" PRIu64 "\n",
                    summary.groups_total,
                    summary.groups_ok,
                    summary.groups_bad,
                    summary.endpoints_expected,
                    summary.endpoints_received,
                    summary.endpoints_missing,
                    summary.endpoints_extra,
                    summary.endpoints_duplicates,
                    summary.meta_mismatch);
            } else {
                summary_log_->verbose(
                    CALL_INFO, 0, 0,
                    "[traffic][sk-group] groups_total=%" PRIu64 " ok=%" PRIu64 " bad=%" PRIu64
                    " endpoints_expected=%" PRIu64 " received=%" PRIu64 " missing=%" PRIu64 " extra=%" PRIu64
                    " dup=%" PRIu64 " meta_mismatch=%" PRIu64 "\n",
                    summary.groups_total,
                    summary.groups_ok,
                    summary.groups_bad,
                    summary.endpoints_expected,
                    summary.endpoints_received,
                    summary.endpoints_missing,
                    summary.endpoints_extra,
                    summary.endpoints_duplicates,
                    summary.meta_mismatch);
                for (const auto& d : bad_details) {
                    summary_log_->verbose(
                        CALL_INFO, 0, 0,
                        "[traffic][sk-group-bad] group_id=0x%016" PRIx64 " exp=%u rcv=%u missing=%u extra=%u dup=%u"
                        " meta_mismatch=%u block_w_h=0x%04x block_d=%u pre_global=%u block_id=%u ingress_node=%u\n",
                        d.group_id,
                        d.exp,
                        d.rcv,
                        d.miss,
                        d.extra,
                        d.dup,
                        d.meta_mismatch,
                        static_cast<unsigned>(d.block_w_h),
                        static_cast<unsigned>(d.block_d),
                        d.pre_global,
                        d.block_id,
                        d.ingress_node);
                }
            }
        }

        return ok;
    }

private:
    static inline std::mutex mtx_{};
    static inline std::unordered_map<uint64_t, SpikeKeyGroupState> groups_{};
    static inline std::unordered_set<uint32_t> finished_cores_{};
    static inline uint32_t expected_total_cores_ = 0;
    static inline bool finalized_ = false;
    static inline SpikeKeyGroupSummary cached_summary_{};
    static inline SST::Output* summary_log_ = nullptr;
};

} // namespace

TrafficWorkload::TrafficWorkload() = default;
TrafficWorkload::~TrafficWorkload() = default;

void TrafficWorkload::configureFromParams(const SST::Params& params) {
    // Copy params to avoid dangling references (some callers pass temporary Params).
    params_ = std::make_unique<SST::Params>(/*copy*/params);

    traffic_enable_ = params_->find<int>("traffic_enable", 0) != 0;
    traffic_period_cycles_ = params_->find<uint64_t>("traffic_period_cycles", 0);
    traffic_batch_size_ = params_->find<uint32_t>("traffic_batch_size", 0);
    traffic_seed_ = params_->find<uint64_t>("traffic_seed", 0);
    traffic_pre_begin_ = params_->find<uint32_t>("traffic_pre_begin", 0);
    traffic_pre_end_ = params_->find<uint32_t>("traffic_pre_end", 0);
    traffic_stop_cycle_ = params_->find<uint64_t>("traffic_stop_cycle", 0);

    experimental_spiketile_enable_ = params_->find<int>("experimental_spiketile_enable", 0) != 0;
    experimental_spiketile_max_pre_bits_ = params_->find<uint32_t>("experimental_spiketile_max_pre_bits", 64);
    experimental_spiketile_block_cols_ = params_->find<uint32_t>("experimental_spiketile_block_cols", 0);
    experimental_compact_mask_enable_ = params_->find<int>("experimental_compact_mask_enable", 0) != 0;
    experimental_inter_bundle_enable_ = params_->find<int>("experimental_inter_bundle_enable", 0) != 0;
    experimental_inter_bundle_max_entries_ = params_->find<uint32_t>("experimental_inter_bundle_max_entries", 64);
    if (experimental_inter_bundle_max_entries_ == 0) {
        experimental_inter_bundle_max_entries_ = 64;
    }
    experimental_inter_bundle_v2_enable_ = params_->find<int>("experimental_inter_bundle_v2_enable", 0) != 0;

    spikekey_check_enable_ = params_->find<int>("traffic_spikekey_check_enable", 1) != 0;
    spikekey_check_fatal_ = params_->find<int>("traffic_spikekey_check_fatal", 0) != 0;
    spikekey_check_log_cap_ = params_->find<uint32_t>("traffic_spikekey_check_log_cap", 8);
    spikekey_group_log_cap_ = params_->find<uint32_t>("traffic_spikekey_group_log_cap", 8);
    traffic_mesh_shape_ = MeshShape3D{};
    traffic_mesh_shape_valid_ = false;
    traffic_memory_kind_ = toLowerCopy(params_->find<std::string>("memory_kind", "hbm_like"));
    source_global_neuron_base_ = 0;

    configured_ = true;
}

void TrafficWorkload::bindRuntime(const Runtime& rt) {
    rt_ = rt;
    if (synapse_route_) {
        ISynapseRoute::RouteRuntimeStatSinks route_runtime_stats{};
        route_runtime_stats.route3d_native_activation_total = rt_.sinks.route3d_native_activation_total;
        route_runtime_stats.route3d_native_gating_activation_total =
            rt_.sinks.route3d_native_gating_activation_total;
        route_runtime_stats.route3d_native_direct_activation_total =
            rt_.sinks.route3d_native_direct_activation_total;
        route_runtime_stats.route3d_native_unique_sources_total =
            rt_.sinks.route3d_native_unique_sources_total;
        route_runtime_stats.stat_route3d_native_activation_total = rt_.sinks.stat_route3d_native_activation_total;
        route_runtime_stats.stat_route3d_native_gating_activation_total =
            rt_.sinks.stat_route3d_native_gating_activation_total;
        route_runtime_stats.stat_route3d_native_direct_activation_total =
            rt_.sinks.stat_route3d_native_direct_activation_total;
        route_runtime_stats.stat_route3d_native_unique_sources_total =
            rt_.sinks.stat_route3d_native_unique_sources_total;
        synapse_route_->bindRouteRuntimeStats(route_runtime_stats);
    }
}

void TrafficWorkload::onInitPhase(unsigned phase) {
    if (phase != 0) return;
    ensureCommReady_();
}

void TrafficWorkload::onSetup() {
    ensureCommReady_();
}

void TrafficWorkload::onFinish() {
    if (!rt_.log) return;

    // Group-level coverage self-check: verify each SpikeKey group_id delivers exactly to the expected endpoints.
    // Printed once when all cores finish.
    const uint32_t cores_per_pe = params_ ? params_->find<uint32_t>("total_cores", 0) : 0;
    (void)SpikeKeyGroupTracker::noteCoreFinish(rt_.total_nodes,
                                              cores_per_pe,
                                              rt_.node_id,
                                              rt_.core_id,
                                              rt_.log,
                                              spikekey_group_log_cap_,
                                              /*fatal_on_bad=*/spikekey_check_fatal_);

    if (tx_batches_ == 0 && tx_pres_total_ == 0 && rx_spike_total_ == 0 && rx_spikekey_total_ == 0) return;
    const uint64_t tx_spike_pkts = spike_comm_ ? spike_comm_->txSpikePacketsTotal() : 0;
    const uint64_t tx_spikekey_pkts = spike_comm_ ? spike_comm_->txSpikeKeyPacketsTotal() : 0;
    const uint64_t tx_spiketilekey_pkts = spike_comm_ ? spike_comm_->txSpikeTileKeyPacketsTotal() : 0;
    const uint64_t tx_spikekey_v4_pkts = spike_comm_ ? spike_comm_->txSpikeKeyV4PacketsTotal() : 0;
    const uint64_t tx_spiketilekey_v4_pkts = spike_comm_ ? spike_comm_->txSpikeTileKeyV4PacketsTotal() : 0;
    const uint64_t tx_bundle_v1_pkts = spike_comm_ ? spike_comm_->txBundleV1PacketsTotal() : 0;
    const uint64_t tx_bundle_v2_pkts = spike_comm_ ? spike_comm_->txBundleV2PacketsTotal() : 0;
    const uint64_t tx_bundle_v3_pkts = spike_comm_ ? spike_comm_->txBundleV3PacketsTotal() : 0;
    rt_.log->verbose(CALL_INFO, 0, 0,
                     "[traffic] node=%u core=%u tx_batches=%" PRIu64 " tx_pre_total=%" PRIu64
                     " rx_spike=%" PRIu64 " rx_spikekey=%" PRIu64
                     " rx_spike_hops_sum=%" PRIu64 " rx_spike_hops_max=%" PRIu64
                     " rx_spikekey_hops_sum=%" PRIu64 " rx_spikekey_hops_max=%" PRIu64
                     " sk_ok=%" PRIu64 " sk_bad=%" PRIu64
                     " sk_bad_decode=%" PRIu64 " sk_bad_stage=%" PRIu64 " sk_bad_dst=%" PRIu64
                     " sk_bad_blockpos=%" PRIu64 " sk_bad_mask=%" PRIu64
                     " rx_spiketilekey=%" PRIu64 " rx_spikekey_v4=%" PRIu64
                     " rx_spiketilekey_v4=%" PRIu64 " tile_bad_decode=%" PRIu64
                     " tx_spike_pkts=%" PRIu64 " tx_spikekey_pkts=%" PRIu64 " tx_spiketilekey_pkts=%" PRIu64
                     " tx_spikekey_v4_pkts=%" PRIu64 " tx_spiketilekey_v4_pkts=%" PRIu64
                     " tx_bundle_v1_pkts=%" PRIu64 " tx_bundle_v2_pkts=%" PRIu64 " tx_bundle_v3_pkts=%" PRIu64 "\n",
                     rt_.node_id,
                     rt_.core_id,
                     tx_batches_,
                     tx_pres_total_,
                     rx_spike_total_,
                     rx_spikekey_total_,
                     rx_spike_hops_sum_,
                     rx_spike_hops_max_,
                     rx_spikekey_hops_sum_,
                     rx_spikekey_hops_max_,
                     rx_spikekey_ok_total_,
                     rx_spikekey_bad_total_,
                     rx_spikekey_bad_decode_,
                     rx_spikekey_bad_stage_,
                     rx_spikekey_bad_dst_,
                     rx_spikekey_bad_blockpos_,
                     rx_spikekey_bad_mask_,
                     rx_spiketilekey_total_,
                     rx_spikekey_v4_total_,
                     rx_spiketilekey_v4_total_,
                     rx_spiketilekey_bad_decode_,
                     tx_spike_pkts,
                     tx_spikekey_pkts,
                     tx_spiketilekey_pkts,
                     tx_spikekey_v4_pkts,
                     tx_spiketilekey_v4_pkts,
                     tx_bundle_v1_pkts,
                     tx_bundle_v2_pkts,
                     tx_bundle_v3_pkts);
}

bool TrafficWorkload::hasWork() const {
    // traffic is periodic; treat as having work once enabled + configured
    return configured_ && traffic_enable_ && (traffic_period_cycles_ > 0) && (traffic_batch_size_ > 0);
}

double TrafficWorkload::getUtilization() const {
    // not modeling compute; return 0/1 as best-effort
    return hasWork() ? 1.0 : 0.0;
}

TrafficWorkload::SemanticMemoryDemand TrafficWorkload::takeSemanticDemand() {
    const SemanticMemoryDemand out = pending_semantic_demand_;
    pending_semantic_demand_ = SemanticMemoryDemand{};
    return out;
}

void TrafficWorkload::getStatistics(std::map<std::string, uint64_t>& stats) const {
    stats["traffic_tx_batches"] = tx_batches_;
    stats["traffic_tx_pre_total"] = tx_pres_total_;
    stats["traffic_semantic_metadata_lookup_demands_total"] = total_semantic_metadata_lookup_demands_;
    stats["traffic_semantic_synapse_gather_demands_total"] = total_semantic_synapse_gather_demands_;
    stats["traffic_semantic_stream_region_demands_total"] = total_semantic_stream_region_demands_;
    stats["traffic_semantic_writeback_region_demands_total"] = total_semantic_writeback_region_demands_;
    stats["traffic_semantic_tier_local_home_gather_demands_total"] = total_semantic_tier_local_home_gather_demands_;
    stats["traffic_semantic_same_xy_cross_tier_gather_demands_total"] = total_semantic_same_xy_cross_tier_gather_demands_;
    stats["traffic_semantic_remote_home_gather_demands_total"] = total_semantic_remote_home_gather_demands_;
    stats["traffic_semantic_tier_local_home_stream_region_demands_total"] =
        total_semantic_tier_local_home_stream_region_demands_;
    stats["traffic_semantic_same_xy_cross_tier_stream_region_demands_total"] =
        total_semantic_same_xy_cross_tier_stream_region_demands_;
    stats["traffic_semantic_remote_home_stream_region_demands_total"] =
        total_semantic_remote_home_stream_region_demands_;
    stats["traffic_rx_spike_total"] = rx_spike_total_;
    stats["traffic_rx_spikekey_total"] = rx_spikekey_total_;
    stats["traffic_rx_spiketilekey_total"] = rx_spiketilekey_total_;
    stats["traffic_rx_spikekey_v4_total"] = rx_spikekey_v4_total_;
    stats["traffic_rx_spiketilekey_v4_total"] = rx_spiketilekey_v4_total_;
    stats["traffic_rx_spiketilekey_bad_decode"] = rx_spiketilekey_bad_decode_;
    stats["traffic_tx_spike_pkts"] = spike_comm_ ? spike_comm_->txSpikePacketsTotal() : 0;
    stats["traffic_tx_spikekey_pkts"] = spike_comm_ ? spike_comm_->txSpikeKeyPacketsTotal() : 0;
    stats["traffic_tx_spiketilekey_pkts"] = spike_comm_ ? spike_comm_->txSpikeTileKeyPacketsTotal() : 0;
    stats["traffic_tx_spikekey_v4_pkts"] = spike_comm_ ? spike_comm_->txSpikeKeyV4PacketsTotal() : 0;
    stats["traffic_tx_spiketilekey_v4_pkts"] = spike_comm_ ? spike_comm_->txSpikeTileKeyV4PacketsTotal() : 0;
    stats["traffic_tx_bundle_v1_pkts"] = spike_comm_ ? spike_comm_->txBundleV1PacketsTotal() : 0;
    stats["traffic_tx_bundle_v2_pkts"] = spike_comm_ ? spike_comm_->txBundleV2PacketsTotal() : 0;
    stats["traffic_tx_bundle_v3_pkts"] = spike_comm_ ? spike_comm_->txBundleV3PacketsTotal() : 0;
    stats["traffic_rx_spike_hops_sum"] = rx_spike_hops_sum_;
    stats["traffic_rx_spike_hops_max"] = rx_spike_hops_max_;
    stats["traffic_rx_spikekey_hops_sum"] = rx_spikekey_hops_sum_;
    stats["traffic_rx_spikekey_hops_max"] = rx_spikekey_hops_max_;
    stats["traffic_rx_spikekey_ok_total"] = rx_spikekey_ok_total_;
    stats["traffic_rx_spikekey_bad_total"] = rx_spikekey_bad_total_;
    stats["traffic_rx_spikekey_bad_decode"] = rx_spikekey_bad_decode_;
    stats["traffic_rx_spikekey_bad_stage"] = rx_spikekey_bad_stage_;
    stats["traffic_rx_spikekey_bad_dst"] = rx_spikekey_bad_dst_;
    stats["traffic_rx_spikekey_bad_blockpos"] = rx_spikekey_bad_blockpos_;
    stats["traffic_rx_spikekey_bad_mask"] = rx_spikekey_bad_mask_;
    stats["route3d_native_activation_total"] =
        rt_.sinks.route3d_native_activation_total ? *rt_.sinks.route3d_native_activation_total : 0;
    stats["route3d_native_gating_activation_total"] =
        rt_.sinks.route3d_native_gating_activation_total ? *rt_.sinks.route3d_native_gating_activation_total : 0;
    stats["route3d_native_direct_activation_total"] =
        rt_.sinks.route3d_native_direct_activation_total ? *rt_.sinks.route3d_native_direct_activation_total : 0;
    stats["route3d_native_unique_sources_total"] =
        rt_.sinks.route3d_native_unique_sources_total ? *rt_.sinks.route3d_native_unique_sources_total : 0;
}

std::vector<uint32_t> TrafficWorkload::sampleNeuronIndices_(uint64_t /*now_cycle*/) {
    std::vector<uint32_t> out;
    if (!traffic_enable_) return out;
    if (traffic_batch_size_ == 0) return out;

    const uint32_t n = params_ ? params_->find<uint32_t>("num_neurons", 0) : 0;
    if (n == 0) return out;

    uint32_t begin = std::min<uint32_t>(traffic_pre_begin_, n);
    uint32_t end = traffic_pre_end_ ? std::min<uint32_t>(traffic_pre_end_, n) : n;
    if (end <= begin) return out;

    const uint64_t seed = mixSeed_(traffic_seed_, rt_.node_id, rt_.core_id, seq_);
    std::mt19937_64 rng(seed);
    std::uniform_int_distribution<uint32_t> dist(begin, end - 1);

    out.reserve(traffic_batch_size_);
    for (uint32_t i = 0; i < traffic_batch_size_; ++i) {
        out.push_back(dist(rng));
    }

    std::sort(out.begin(), out.end());
    out.erase(std::unique(out.begin(), out.end()), out.end());
    return out;
}

void TrafficWorkload::ensureCommReady_() {
    if (comm_ready_) return;
    if (!configured_) return;
    if (!params_) return;

    if (!rt_.noc) {
        if (rt_.log) rt_.log->fatal(CALL_INFO, -1, "TrafficWorkload requires Runtime.noc (INocTransport)\n");
        std::abort();
    }

    if (!synapse_route_) synapse_route_ = makeSynapseRoute_(*params_);
    if (!spike_comm_) spike_comm_ = std::make_unique<SpikeCommSubsystem>();

    SpikeCommRoutingConfig cfg{};
    cfg.routing_weight_driven = (params_->find<std::string>("routing_mode", "fixed") == "weight_driven");
    cfg.total_nodes = params_->find<uint32_t>("total_nodes", rt_.total_nodes);
    cfg.mesh_shape = params_->find<std::string>("mesh_shape", "");
    cfg.cores_per_pe = params_->find<uint32_t>("total_cores", 1);
    const uint32_t neurons_per_core = params_->find<uint32_t>("num_neurons", 0);
    cfg.neurons_per_pe = params_->find<uint32_t>("neurons_per_pe", 0);
    if (cfg.neurons_per_pe == 0 && neurons_per_core > 0 && cfg.cores_per_pe > 0) {
        const uint64_t npp64 =
            static_cast<uint64_t>(neurons_per_core) * static_cast<uint64_t>(cfg.cores_per_pe);
        cfg.neurons_per_pe = (npp64 > 0xffffffffull) ? 0u : static_cast<uint32_t>(npp64);
    }
    // IMPORTANT: for BCSR routing, cfg.rows is treated as "rows per PE" and then split by cores_per_pe
    // (see SpikeCommSubsystem.cc::buildWeightDrivenRoutesFromBcsr_()). Keep consistent with SnnWorkload.
    // Keep cache-key stable even when not reading dense weights.
    cfg.cols = params_->find<uint32_t>("weights_cols", 0);
    if (cfg.cols == 0 && cfg.total_nodes > 0 && cfg.neurons_per_pe > 0) {
        const uint64_t cols64 =
            static_cast<uint64_t>(cfg.total_nodes) * static_cast<uint64_t>(cfg.neurons_per_pe);
        cfg.cols = (cols64 > 0xffffffffull) ? 0u : static_cast<uint32_t>(cols64);
    }

    // Normalize: keep "per-core" num_neurons + explicit neurons_per_pe as the canonical view.
    const uint64_t base_param = params_->find<uint64_t>("global_neuron_base", 0);
    const auto n =
        normalizeNeuronLayout(rt_.node_id,
                              rt_.core_id,
                              cfg.total_nodes,
                              cfg.cores_per_pe,
                              neurons_per_core,
                              cfg.neurons_per_pe,
                              base_param,
                              cfg.cols);
    cfg.total_nodes = n.total_nodes;
    cfg.cores_per_pe = n.cores_per_pe;
    cfg.neurons_per_pe = n.neurons_per_pe;
    cfg.rows = n.neurons_per_pe;
    cfg.use_post_row_pre_col = true; // irrelevant for edges_csv; keep stable
    cfg.real_synapse_inputs_available = false;

    cfg.weights_template = params_->find<std::string>("weights_template", "");
    cfg.routing_epsilon = params_->find<float>("routing_epsilon", 1e-8f);
    cfg.routing_topk = params_->find<uint32_t>("routing_topk", 0);
    cfg.routing_topk_per_pe = params_->find<uint32_t>("routing_topk_per_pe", 0);
    cfg.route_exclude_self_pe = params_->find<int>("route_exclude_self_pe", 0) != 0;
    cfg.route_layers_mask = params_->find<std::string>("route_layers_mask", "");
    cfg.route_filter_warn = params_->find<int>("route_filter_warn", 1) != 0;

    cfg.mapping_mode = params_->find<std::string>("mapping_mode", "off");
    cfg.mapping_edges_file = params_->find<std::string>("mapping_edges_file", "");
    cfg.mapping_csv_has_header = params_->find<int>("mapping_csv_has_header", 1) != 0;
    cfg.mapping_csv_separator = params_->find<std::string>("mapping_csv_separator", ",");
    cfg.mapping_assume_block_ids = params_->find<int>("mapping_assume_block_ids", 0) != 0;

    const uint32_t multicast_block_dim_x = params_->find<uint32_t>("multicast_block_dim_x", 0);
    const uint32_t multicast_block_dim_y = params_->find<uint32_t>("multicast_block_dim_y", 0);
    const uint32_t multicast_block_dim_z = params_->find<uint32_t>("multicast_block_dim_z", 0);
    cfg.multicast_enable = params_->find<int>("multicast_enable", 0) != 0;
    cfg.multicast_block_w =
        (multicast_block_dim_x > 0) ? multicast_block_dim_x : params_->find<uint32_t>("multicast_block_w", 2);
    cfg.multicast_block_h =
        (multicast_block_dim_y > 0) ? multicast_block_dim_y : params_->find<uint32_t>("multicast_block_h", 2);
    cfg.multicast_block_d = (multicast_block_dim_z > 0) ? multicast_block_dim_z : 1u;
    cfg.multicast_die_local_only = params_->find<int>("multicast_die_local_only", 0) != 0;
    const bool route3d_native_targets_default =
        cfg.multicast_enable &&
        normalizeSynapseRouteImpl_(params_->find<std::string>("synapse_route_impl", "legacy_2d")) == "native_3d" &&
        meshShapeHasMultipleLayers_(cfg.mesh_shape) &&
        cfg.multicast_block_d > 1 &&
        !cfg.multicast_die_local_only;
    cfg.route3d_native_targets =
        params_->find<int>("route3d_native_targets", route3d_native_targets_default ? 1 : 0) != 0;
    cfg.multicast_ingress_policy = params_->find<std::string>("multicast_ingress_policy", "top_left");
    cfg.multicast_inter_policy = params_->find<std::string>("multicast_inter_policy", "xy");
    cfg.multicast_intra_policy = params_->find<std::string>("multicast_intra_policy", "manhattan_x_first");

    cfg.use_bcsr = false;
    cfg.base_addr = params_->find<uint64_t>("base_addr", rt_.base_addr);
    traffic_memory_kind_ = toLowerCopy(params_->find<std::string>("memory_kind", traffic_memory_kind_));
    metadata_base_addr_ = params_->find<uint64_t>("metadata_base_addr", cfg.base_addr);
    gather_base_addr_ = params_->find<uint64_t>("gather_base_addr", cfg.base_addr);
    stream_base_addr_ = params_->find<uint64_t>("stream_base_addr", cfg.base_addr);
    writeback_base_addr_ = params_->find<uint64_t>("writeback_base_addr", cfg.base_addr);
    traffic_mesh_shape_valid_ = resolveTrafficMeshShape_(params_.get(), cfg.total_nodes, traffic_mesh_shape_);

    synapse_route_->configure(cfg);
    synapse_route_->configureGating(/*gating_event_mode=*/false, /*gating_ttl_cycles=*/0, /*gating_scope_inputs_only=*/true);
    synapse_route_->bindRuntime(rt_.log,
                                rt_.node_id,
                                rt_.core_id,
                                n.neurons_per_core,
                                cfg.neurons_per_pe,
                                rt_.sinks.stat_routes_entries_total);
    synapse_route_->bindFanoutStat(rt_.sinks.stat_fanout_per_spike_total);
    ISynapseRoute::RouteRuntimeStatSinks route_runtime_stats{};
    route_runtime_stats.route3d_native_activation_total = rt_.sinks.route3d_native_activation_total;
    route_runtime_stats.route3d_native_gating_activation_total =
        rt_.sinks.route3d_native_gating_activation_total;
    route_runtime_stats.route3d_native_direct_activation_total =
        rt_.sinks.route3d_native_direct_activation_total;
    route_runtime_stats.route3d_native_unique_sources_total =
        rt_.sinks.route3d_native_unique_sources_total;
    route_runtime_stats.stat_route3d_native_activation_total = rt_.sinks.stat_route3d_native_activation_total;
    route_runtime_stats.stat_route3d_native_gating_activation_total =
        rt_.sinks.stat_route3d_native_gating_activation_total;
    route_runtime_stats.stat_route3d_native_direct_activation_total =
        rt_.sinks.stat_route3d_native_direct_activation_total;
    route_runtime_stats.stat_route3d_native_unique_sources_total =
        rt_.sinks.stat_route3d_native_unique_sources_total;
    synapse_route_->bindRouteRuntimeStats(route_runtime_stats);

    // NocSpikeTransport is required for the non-multicast fallback path.
    if (!noc_spike_transport_) noc_spike_transport_ = std::make_unique<NocSpikeTransport>();
    noc_spike_transport_->setNocTransport(rt_.noc);
    noc_spike_transport_->setSourceCore(static_cast<int>(rt_.core_id));
    noc_spike_transport_->configureLayout(cfg.total_nodes, cfg.cores_per_pe, n.neurons_per_core);

    spike_comm_->configure();
    SpikeCommRuntimeConfig crt{};
    crt.log = rt_.log;
    crt.transport = noc_spike_transport_.get();
    crt.noc = rt_.noc;
    crt.src_core = static_cast<int>(rt_.core_id);
    crt.node_id = rt_.node_id;
    crt.active_step_seq = nullptr;
    crt.synapse_route = synapse_route_.get();
    // SpikeCommSubsystem 的 global_neuron_base 必须是“本 core 的 base”（而不是 node base），否则 core_id>0 时 source_global 会错位。
    crt.global_neuron_base = n.core_neuron_base;
    source_global_neuron_base_ = n.core_neuron_base;
    crt.experimental_spiketile_enable = experimental_spiketile_enable_;
    crt.experimental_spiketile_max_pre_bits = experimental_spiketile_max_pre_bits_;
    crt.experimental_spiketile_block_cols = experimental_spiketile_block_cols_;
    crt.experimental_compact_mask_enable = experimental_compact_mask_enable_;
    crt.experimental_inter_bundle_enable = experimental_inter_bundle_enable_;
    crt.experimental_inter_bundle_max_entries = experimental_inter_bundle_max_entries_;
    crt.experimental_inter_bundle_v2_enable = experimental_inter_bundle_v2_enable_;
    spike_comm_->bindRuntime(crt);
    spike_comm_->initRouting();

    comm_ready_ = true;
}

bool TrafficWorkload::onClockTick(uint64_t now_cycle) {
    if (!configured_) return false;
    if (!traffic_enable_) return false;
    if (traffic_period_cycles_ == 0 || traffic_batch_size_ == 0) return false;
    if (traffic_stop_cycle_ > 0 && now_cycle >= traffic_stop_cycle_) return false;
    ensureCommReady_();
    if (!comm_ready_ || !spike_comm_ || !spike_comm_->ready()) return false;

    if (next_cycle_ == 0) {
        next_cycle_ = now_cycle;
        seq_ = 1;
    }
    if (now_cycle < next_cycle_) return false;

    auto pres = sampleNeuronIndices_(now_cycle);
    if (pres.empty()) {
        next_cycle_ += traffic_period_cycles_;
        ++seq_;
        return false;
    }

    const uint64_t tx_spike_pkts_before = spike_comm_->txSpikePacketsTotal();
    const uint64_t tx_spikekey_pkts_before = spike_comm_->txSpikeKeyPacketsTotal();
    const uint64_t tx_spiketilekey_pkts_before = spike_comm_->txSpikeTileKeyPacketsTotal();
    const uint64_t tx_bundle_v1_pkts_before = spike_comm_->txBundleV1PacketsTotal();
    const uint64_t tx_bundle_v2_pkts_before = spike_comm_->txBundleV2PacketsTotal();
    const uint64_t tx_bundle_v3_pkts_before = spike_comm_->txBundleV3PacketsTotal();
    spike_comm_->emitNeuronFireBatch(pres, now_cycle);
    tx_batches_ += 1;
    tx_pres_total_ += static_cast<uint64_t>(pres.size());

    const uint64_t tx_packets_after =
        spike_comm_->txSpikePacketsTotal() +
        spike_comm_->txSpikeKeyPacketsTotal() +
        spike_comm_->txSpikeTileKeyPacketsTotal() +
        spike_comm_->txBundleV1PacketsTotal() +
        spike_comm_->txBundleV2PacketsTotal() +
        spike_comm_->txBundleV3PacketsTotal();
    const uint64_t tx_packets_before =
        tx_spike_pkts_before +
        tx_spikekey_pkts_before +
        tx_spiketilekey_pkts_before +
        tx_bundle_v1_pkts_before +
        tx_bundle_v2_pkts_before +
        tx_bundle_v3_pkts_before;
    const uint64_t emitted_packets = (tx_packets_after >= tx_packets_before) ? (tx_packets_after - tx_packets_before) : 0;
    SemanticMemoryDemand cycle_demand{};
    cycle_demand.metadata_lookup_demands = static_cast<uint64_t>(pres.size());
    cycle_demand.writeback_region_demands = static_cast<uint64_t>(pres.size());
    cycle_demand.emitted_pres = static_cast<uint64_t>(pres.size());
    cycle_demand.multicast_packets = emitted_packets;

    std::vector<ISynapseRoute::FanoutEntry> fanouts;
    for (uint32_t pre : pres) {
        const uint64_t source_global64 = source_global_neuron_base_ + static_cast<uint64_t>(pre);
        if (source_global64 > 0xffffffffull) continue;

        fanouts.clear();
        bool applied_gating = false;
        const uint32_t source_global = static_cast<uint32_t>(source_global64);
        synapse_route_->computeFanout(source_global, pre, now_cycle, fanouts, applied_gating);
        (void)applied_gating;

        for (const auto& fanout : fanouts) {
            cycle_demand.synapse_gather_demands += 1;
            cycle_demand.stream_region_demands += 1;
            noteTrafficHomeAwareDemand_(
                cycle_demand,
                classifyTrafficHomeAccess_(
                    traffic_mesh_shape_valid_ ? traffic_mesh_shape_ : MeshShape3D{},
                    traffic_memory_kind_,
                    rt_.node_id,
                    fanout.dest_node));
        }
    }

    pending_semantic_demand_.metadata_lookup_demands += cycle_demand.metadata_lookup_demands;
    pending_semantic_demand_.synapse_gather_demands += cycle_demand.synapse_gather_demands;
    pending_semantic_demand_.stream_region_demands += cycle_demand.stream_region_demands;
    pending_semantic_demand_.writeback_region_demands += cycle_demand.writeback_region_demands;
    pending_semantic_demand_.tier_local_home_gather_demands += cycle_demand.tier_local_home_gather_demands;
    pending_semantic_demand_.same_xy_cross_tier_gather_demands += cycle_demand.same_xy_cross_tier_gather_demands;
    pending_semantic_demand_.remote_home_gather_demands += cycle_demand.remote_home_gather_demands;
    pending_semantic_demand_.tier_local_home_stream_region_demands += cycle_demand.tier_local_home_stream_region_demands;
    pending_semantic_demand_.same_xy_cross_tier_stream_region_demands += cycle_demand.same_xy_cross_tier_stream_region_demands;
    pending_semantic_demand_.remote_home_stream_region_demands += cycle_demand.remote_home_stream_region_demands;
    pending_semantic_demand_.emitted_pres += cycle_demand.emitted_pres;
    pending_semantic_demand_.multicast_packets += cycle_demand.multicast_packets;
    total_semantic_metadata_lookup_demands_ += cycle_demand.metadata_lookup_demands;
    total_semantic_synapse_gather_demands_ += cycle_demand.synapse_gather_demands;
    total_semantic_stream_region_demands_ += cycle_demand.stream_region_demands;
    total_semantic_writeback_region_demands_ += cycle_demand.writeback_region_demands;
    total_semantic_tier_local_home_gather_demands_ += cycle_demand.tier_local_home_gather_demands;
    total_semantic_same_xy_cross_tier_gather_demands_ += cycle_demand.same_xy_cross_tier_gather_demands;
    total_semantic_remote_home_gather_demands_ += cycle_demand.remote_home_gather_demands;
    total_semantic_tier_local_home_stream_region_demands_ += cycle_demand.tier_local_home_stream_region_demands;
    total_semantic_same_xy_cross_tier_stream_region_demands_ += cycle_demand.same_xy_cross_tier_stream_region_demands;
    total_semantic_remote_home_stream_region_demands_ += cycle_demand.remote_home_stream_region_demands;

    next_cycle_ += traffic_period_cycles_;
    ++seq_;
    return true;
}

bool TrafficWorkload::deliverPacket(NocPacketEvent* packet) {
    if (!packet) return true;
    const auto kind = packet->packetKind();
    if (kind == NocPacketKind::Spike) {
        rx_spike_total_ += 1;
        rx_spike_hops_sum_ += static_cast<uint64_t>(packet->hop_count);
        rx_spike_hops_max_ = std::max<uint64_t>(rx_spike_hops_max_, packet->hop_count);
    }
        if (kind == NocPacketKind::SpikeKey || kind == NocPacketKind::SpikeTileKey) {
            // Key-like packets (SpikeKey + SpikeTileKey) share the same blocked-multicast routing semantics.
            rx_spikekey_total_ += 1;
            if (kind == NocPacketKind::SpikeTileKey) rx_spiketilekey_total_ += 1;
            rx_spikekey_hops_sum_ += static_cast<uint64_t>(packet->hop_count);
            rx_spikekey_hops_max_ = std::max<uint64_t>(rx_spikekey_hops_max_, packet->hop_count);

            if (spikekey_check_enable_) {
                rx_spikekey_checked_total_ += 1;

                bool ok = true;
                SpikeNocCodec::WireSpikeKeyV2 ws{};
                SpikeNocCodec::DecodedSpikeKeyMeta decoded_meta{};
                if (!SpikeNocCodec::decodeSpikeKeyAny(packet->payload, ws, &decoded_meta) ||
                    (ws.version != 1 && ws.version != 2 && ws.version != 3 && ws.version != 4)) {
                    ok = false;
                    rx_spikekey_bad_decode_ += 1;
                }

                // For SpikeTileKey: enforce that the payload tail is preserved through the router (decode must succeed).
                if (ok && kind == NocPacketKind::SpikeTileKey) {
                    SpikeTileNocCodec::WireSpikeTileKeyV1 tile_ws{};
                    SpikeNocCodec::DecodedSpikeKeyMeta tile_meta{};
                    if (!SpikeTileNocCodec::decode(packet->payload, tile_ws, &tile_meta)) {
                        ok = false;
                        rx_spiketilekey_bad_decode_ += 1;
                    } else if (tile_meta.version == 4) {
                        rx_spikekey_v4_total_ += 1;
                        rx_spiketilekey_v4_total_ += 1;
                    }
                }

                if (ok && kind == NocPacketKind::SpikeKey && ws.version == 4) {
                    rx_spikekey_v4_total_ += 1;
                }

                if (ok && ws.stage != 1) {
                    ok = false;
                    rx_spikekey_bad_stage_ += 1;
                }

                if (ok && (packet->dst_node != rt_.node_id || packet->dst_endpoint != rt_.core_id)) {
                    ok = false;
                    rx_spikekey_bad_dst_ += 1;
                }

                MeshShape3D mesh_shape{};
                if (ok && !resolveTrafficMeshShape_(params_.get(), rt_.total_nodes, mesh_shape)) {
                    ok = false;
                    rx_spikekey_bad_blockpos_ += 1;
                }

                uint32_t idx = 0;
                uint32_t block_cells = 0;
                if (ok) {
                    const uint32_t bw = decoded_meta.block_w;
                    const uint32_t bh = decoded_meta.block_h;
                    const uint32_t bd = decoded_meta.block_d;
                    if (!resolveSelfBlockIndex3D_(mesh_shape, rt_.node_id, bw, bh, bd, ws.block_id, idx, block_cells)) {
                        ok = false;
                        rx_spikekey_bad_blockpos_ += 1;
                    }
                }

                if (ok) {
                    if (idx >= kMaxMulticastBlockCells) {
                        ok = false;
                        rx_spikekey_bad_blockpos_ += 1;
                    }
                }

                if (ok) {
                    const uint32_t core_mask = ws.core_mask[idx];
                    const uint32_t bit = (packet->dst_endpoint < 32) ? (1u << packet->dst_endpoint) : 0u;
                    if (bit == 0u || (core_mask & bit) == 0u) {
                        ok = false;
                        rx_spikekey_bad_mask_ += 1;
                    }
                }

                if (!ok) {
                    rx_spikekey_bad_total_ += 1;
                    if (rt_.log && spikekey_check_logged_ < spikekey_check_log_cap_) {
                        spikekey_check_logged_ += 1;
                        const uint32_t mask_val = (idx < kMaxMulticastBlockCells) ? ws.core_mask[idx] : 0u;
                        rt_.log->verbose(
                            CALL_INFO, 0, 0,
                            "[traffic][sk-check] BAD node=%u core=%u pkt_dst=%u:%u kind=%u ingress=%u stage=%u block_w_h=0x%04x idx=%u mask=0x%08x\n",
                            rt_.node_id,
                            rt_.core_id,
                            packet->dst_node,
                            packet->dst_endpoint,
                            static_cast<unsigned>(packet->kind),
                            ws.ingress_node,
                            static_cast<unsigned>(ws.stage),
                            static_cast<unsigned>(ws.block_w_h),
                            idx,
                            mask_val);
                    }
                    if (spikekey_check_fatal_ && rt_.log) {
                        rt_.log->fatal(CALL_INFO, -1, "SpikeKey delivery self-check failed (node=%u core=%u)\n", rt_.node_id, rt_.core_id);
                    }
                } else {
                    rx_spikekey_ok_total_ += 1;
                }

                // Group-level coverage tracking (independent of strict per-packet ok/fail-fast).
                if (ws.stage == 1) {
                    uint32_t cores_per_pe = params_ ? params_->find<uint32_t>("total_cores", 0) : 0;
                    const uint32_t bw = decoded_meta.block_w;
                    const uint32_t bh = decoded_meta.block_h;
                    const uint32_t bd = decoded_meta.block_d;
                    MeshShape3D group_mesh_shape{};
                    uint32_t idx2 = 0;
                    uint32_t group_block_cells = 0;
                    if (cores_per_pe > 0 &&
                        resolveTrafficMeshShape_(params_.get(), rt_.total_nodes, group_mesh_shape) &&
                        resolveSelfBlockIndex3D_(group_mesh_shape, rt_.node_id, bw, bh, bd, ws.block_id, idx2, group_block_cells)) {
                        (void)group_block_cells;
                        SpikeKeyGroupTracker::noteRx(ws.group_id, cores_per_pe, ws, decoded_meta, idx2, packet->dst_endpoint);
                    }
                }
            }
        }
        delete packet;
        return true;
    }

}} // namespace SST::SnnDL
