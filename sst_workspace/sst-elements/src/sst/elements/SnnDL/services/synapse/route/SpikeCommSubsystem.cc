// -*- c++ -*-
//
// SpikeCommSubsystem: fanout + 事件构造 + 传输调用
//

#include "SpikeCommSubsystem.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <inttypes.h>
#include <iterator>
#include <limits>
#include <sstream>
#include <unordered_set>

#include <sst/core/statapi/stataccumulator.h>

#include "INocTransport.h"
#include "SpikeInterBundleCodec.h"
#include "SpikeNocCodec.h"
#include "SpikeTileBatchEmitter.h"
#include "events/SpikeEvent.h"

namespace SST { namespace SnnDL {


void SpikeCommSubsystem::configure() {
    route_provider_ready_ = false;
    emit_seq_ = 0;
    active_step_seq_ = nullptr;
    experimental_spiketile_enable_ = false;
    experimental_spiketile_max_pre_bits_ = 64;
    experimental_spiketile_block_cols_ = 0;
    experimental_compact_mask_enable_ = false;
    experimental_inter_bundle_enable_ = false;
    experimental_inter_bundle_max_entries_ = 64;
    experimental_inter_bundle_v2_enable_ = false;
    tx_spike_packets_total_ = 0;
    tx_spikekey_packets_total_ = 0;
    tx_spiketilekey_packets_total_ = 0;
    tx_spikekey_v4_packets_total_ = 0;
    tx_spiketilekey_v4_packets_total_ = 0;
    tx_bundle_v1_packets_total_ = 0;
    tx_bundle_v2_packets_total_ = 0;
    tx_bundle_v3_packets_total_ = 0;
    tx_cohort_packets_total_ = 0;
    tx_cohort_pres_total_ = 0;
    tx_cohort_bandcolor_switch_total_ = 0;
    bundle_v3_diag_attempt_total_ = 0;
    bundle_v3_diag_success_total_ = 0;
    bundle_v3_diag_fallback_total_ = 0;
    bundle_v3_diag_emitted_packets_total_ = 0;
    bundle_v3_diag_logs_emitted_ = 0;
}

void SpikeCommSubsystem::bindRuntime(const SpikeCommRuntimeConfig& rt) {
    if (rt.log) log_ = rt.log;
    if (rt.transport) transport_ = rt.transport;
    if (rt.noc) noc_ = rt.noc;
    src_core_ = rt.src_core;
    node_id_ = rt.node_id;
    active_step_seq_ = rt.active_step_seq;
    if (rt.synapse_route) synapse_route_ = rt.synapse_route;
    global_neuron_base_ = rt.global_neuron_base;
    experimental_spiketile_enable_ = rt.experimental_spiketile_enable;
    experimental_spiketile_max_pre_bits_ = rt.experimental_spiketile_max_pre_bits;
    experimental_spiketile_block_cols_ = rt.experimental_spiketile_block_cols;
    experimental_compact_mask_enable_ = rt.experimental_compact_mask_enable;
    experimental_inter_bundle_enable_ = rt.experimental_inter_bundle_enable;
    experimental_inter_bundle_max_entries_ = rt.experimental_inter_bundle_max_entries;
    experimental_inter_bundle_v2_enable_ = rt.experimental_inter_bundle_v2_enable;
    if (experimental_spiketile_max_pre_bits_ == 0 || experimental_spiketile_max_pre_bits_ > 64) {
        experimental_spiketile_max_pre_bits_ = 64;
    }
    if (experimental_inter_bundle_max_entries_ == 0) {
        experimental_inter_bundle_max_entries_ = 64;
    }
    route_provider_ready_ = false;
    emit_seq_ = 0;
    tx_spike_packets_total_ = 0;
    tx_spikekey_packets_total_ = 0;
    tx_spiketilekey_packets_total_ = 0;
    tx_spikekey_v4_packets_total_ = 0;
    tx_spiketilekey_v4_packets_total_ = 0;
    tx_bundle_v1_packets_total_ = 0;
    tx_bundle_v2_packets_total_ = 0;
    tx_bundle_v3_packets_total_ = 0;
    tx_cohort_packets_total_ = 0;
    tx_cohort_pres_total_ = 0;
    tx_cohort_bandcolor_switch_total_ = 0;
    bundle_v3_diag_attempt_total_ = 0;
    bundle_v3_diag_success_total_ = 0;
    bundle_v3_diag_fallback_total_ = 0;
    bundle_v3_diag_emitted_packets_total_ = 0;
    bundle_v3_diag_logs_emitted_ = 0;
}

void SpikeCommSubsystem::initRouting() {
    route_provider_ready_ = false;
    if (!synapse_route_) return;
    // Phase3：fanout provider 已下沉至 Synapse/Route；SpikeComm 仅确保其初始化。
    (void)synapse_route_->initRoutes();
    route_provider_ready_ = true;
}

void SpikeCommSubsystem::emitNeuronFire(uint32_t neuron_idx, uint64_t now_cycle) {
    uint32_t source_global = static_cast<uint32_t>(global_neuron_base_ + neuron_idx);
    emitCommon_(source_global, neuron_idx, now_cycle);
}

uint64_t SpikeCommSubsystem::emitNeuronFireBatch(const std::vector<uint32_t>& neuron_indices, uint64_t now_cycle) {
    if (neuron_indices.empty()) return 0;

    const uint64_t tx_spiketilekey_packets_before = tx_spiketilekey_packets_total_;
    const uint64_t tx_bundle_v3_packets_before = tx_bundle_v3_packets_total_;
    const bool experimental_ok = emitSpikeTileBatchExperimental_(neuron_indices, now_cycle);
    if (experimental_spiketile_enable_) {
        bundle_v3_diag_attempt_total_ += 1;
        const uint64_t emitted_packets = tx_spiketilekey_packets_total_ - tx_spiketilekey_packets_before;
        const uint64_t emitted_bundle_v3_packets = tx_bundle_v3_packets_total_ - tx_bundle_v3_packets_before;
        if (experimental_ok) {
            bundle_v3_diag_success_total_ += 1;
            bundle_v3_diag_emitted_packets_total_ += emitted_packets;
        } else {
            bundle_v3_diag_fallback_total_ += 1;
        }
        if (log_ && bundle_v3_diag_logs_emitted_ < bundle_v3_diag_log_cap_) {
            const uint32_t step_seq = active_step_seq_ ? *active_step_seq_ : 0u;
            const int route_ready = (route_provider_ready_ && synapse_route_ && noc_) ? 1 : 0;
            const int multicast_enabled =
                (route_provider_ready_ && synapse_route_ && synapse_route_->multicastEnabled()) ? 1 : 0;
            log_->verbose(
                CALL_INFO,
                0,
                0,
                "[bundle-v3-diag] node=%u core=%d cycle=%" PRIu64
                " step_seq=%u batch_size=%zu experimental=1 route_ready=%d multicast=%d"
                " ok=%d fallback=%d emitted_packets=%" PRIu64 " tx_bundle_v3_packets=%" PRIu64
                " attempt_total=%" PRIu64 " success_total=%" PRIu64 " fallback_total=%" PRIu64
                " emitted_packets_total=%" PRIu64 " tx_bundle_v3_packets_total=%" PRIu64 "\n",
                node_id_,
                src_core_,
                now_cycle,
                step_seq,
                neuron_indices.size(),
                route_ready,
                multicast_enabled,
                experimental_ok ? 1 : 0,
                experimental_ok ? 0 : 1,
                emitted_packets,
                emitted_bundle_v3_packets,
                bundle_v3_diag_attempt_total_,
                bundle_v3_diag_success_total_,
                bundle_v3_diag_fallback_total_,
                bundle_v3_diag_emitted_packets_total_,
                tx_bundle_v3_packets_total_);
            bundle_v3_diag_logs_emitted_ += 1;
        }
    }

    if (experimental_ok) {
        return static_cast<uint64_t>(neuron_indices.size());
    }

    uint64_t emitted = 0;
    for (uint32_t neuron_idx : neuron_indices) {
        emitNeuronFire(neuron_idx, now_cycle);
        emitted += 1;
    }
    return emitted;
}

void SpikeCommSubsystem::emitSource(uint32_t source_global, uint32_t source_local, uint64_t now_cycle) {
    emitCommon_(source_global, source_local, now_cycle);
}

bool SpikeCommSubsystem::emitSpikeTileBatchExperimental_(const std::vector<uint32_t>& neuron_indices, uint64_t now_cycle) {
    if (!experimental_spiketile_enable_ || !route_provider_ready_ || !synapse_route_ || !noc_) return false;

    if (!synapse_route_->multicastEnabled()) return false;
    const auto semantics = synapse_route_->describeRouteSemantics();
    if (!semantics.native_target_synthesis_active) return false;
    const bool route_is_mesh_3d = semantics.route_topology == "mesh_3d";
    const bool native_target_authority =
        semantics.target_semantics_authority == "native_3d_target_synthesis";
    if (!route_is_mesh_3d || !native_target_authority) return false;

    SpikeTileBatchEmitConfig cfg{};
    cfg.source_node = node_id_;
    cfg.source_core = static_cast<uint16_t>(src_core_);
    cfg.block_w = synapse_route_->multicastBlockW();
    cfg.block_h = synapse_route_->multicastBlockH();
    cfg.block_d = synapse_route_->multicastBlockD();
    cfg.block_cols = (experimental_spiketile_block_cols_ > 0) ? experimental_spiketile_block_cols_ : synapse_route_->bcsrBlockCols();
    cfg.max_pre_bits = experimental_spiketile_max_pre_bits_;
    cfg.emit_seq = &emit_seq_;
    cfg.experimental_compact_mask_enable = experimental_compact_mask_enable_;
    cfg.experimental_inter_bundle_enable = experimental_inter_bundle_enable_;
    cfg.experimental_inter_bundle_max_entries = experimental_inter_bundle_max_entries_;
    cfg.experimental_inter_bundle_v2_enable = experimental_inter_bundle_v2_enable_;
    cfg.route_is_mesh_3d = route_is_mesh_3d;
    cfg.native_target_authority = native_target_authority;
    cfg.native_target_synthesis_active = semantics.native_target_synthesis_active;
    uint64_t emitted_packets = 0;
    SpikeTileBatchStats batch_stats{};

    const bool ok = SST::SnnDL::emitSpikeTileBatchExperimental(neuron_indices,
                                                                global_neuron_base_,
                                                                now_cycle,
                                                                *synapse_route_,
                                                                *noc_,
                                                                cfg,
                                                                &emitted_packets,
                                                                &batch_stats);
    tx_spiketilekey_packets_total_ += emitted_packets;
    tx_spiketilekey_v4_packets_total_ += batch_stats.tx_spiketilekey_v4_packets_total;
    tx_bundle_v1_packets_total_ += batch_stats.tx_bundle_v1_packets_total;
    tx_bundle_v2_packets_total_ += batch_stats.tx_bundle_v2_packets_total;
    tx_bundle_v3_packets_total_ += batch_stats.tx_bundle_v3_packets_total;
    tx_cohort_packets_total_ += batch_stats.cohort_packets_total;
    tx_cohort_pres_total_ += batch_stats.cohort_pres_total;
    tx_cohort_bandcolor_switch_total_ += batch_stats.cohort_bandcolor_switch_total;
    return ok;
}

void SpikeCommSubsystem::emitCommon_(uint32_t source_global, uint32_t source_local, uint64_t now_cycle) {
    if (!route_provider_ready_ || !synapse_route_) return;

    if (noc_ && synapse_route_->multicastEnabled()) {
            const auto semantics = synapse_route_->describeRouteSemantics();
            const bool route_is_mesh_3d = semantics.route_topology == "mesh_3d";
            const bool native_target_authority =
                semantics.target_semantics_authority == "native_3d_target_synthesis";
            const bool allow_bundle_v2 =
                experimental_inter_bundle_enable_ && experimental_inter_bundle_v2_enable_;
            const bool allow_bundle_v3 =
                allow_bundle_v2 &&
                route_is_mesh_3d &&
                native_target_authority &&
                semantics.native_target_synthesis_active;
            std::vector<ISynapseRoute::BlockTarget> targets;
            bool applied_gating = false;
            if (synapse_route_->computeMulticastTargets(source_global, source_local, now_cycle, targets, applied_gating) && !targets.empty()) {
                const uint32_t bw = synapse_route_->multicastBlockW();
                const uint32_t bh = synapse_route_->multicastBlockH();
                const uint32_t bd = synapse_route_->multicastBlockD();
                std::vector<std::vector<uint8_t>> bundle_entries_v1;
                std::vector<SpikeInterBundleCodec::BundleEntryV2> bundle_entries_v2;
                std::vector<SpikeInterBundleCodec::BundleEntryV3> bundle_entries_v3;
                if (experimental_inter_bundle_enable_ && !experimental_inter_bundle_v2_enable_) {
                    bundle_entries_v1.reserve(targets.size());
                }
                if (allow_bundle_v2) {
                    bundle_entries_v2.reserve(targets.size());
                }
                if (allow_bundle_v3) {
                    bundle_entries_v3.reserve(targets.size());
                }
                const uint16_t block_w_h = static_cast<uint16_t>(((bw & 0xffu) << 8) | (bh & 0xffu));
                if (allow_bundle_v2 &&
                    bd <= 1u &&
                    SpikeInterBundleCodec::blockCellsFromBlockWH(block_w_h) == 0) {
                    return;
                }
                if (allow_bundle_v3 &&
                    bd > 1u &&
                    SpikeInterBundleCodec::blockCellsFromBlockShape(
                        static_cast<uint16_t>(bw),
                        static_cast<uint16_t>(bh),
                        static_cast<uint16_t>(bd)) == 0) {
                    return;
                }
                for (const auto& t : targets) {
                    const uint32_t target_block_z = t.block_z;
                    // group_id：一次仿真运行内必须“每次发射唯一”。
                    // 这里使用“单调递增序号 + pre_global”的结构化组合，避免 XOR/哈希导致的周期性重复与碰撞。
                    const uint64_t seq = ++emit_seq_;
                    const uint64_t group_id = (seq << 32) | static_cast<uint64_t>(source_global);
                    const uint32_t target_block_d = (t.block_d > 0) ? t.block_d : std::max<uint32_t>(bd, 1u);
                    const bool explicit_3d_target = target_block_d > 1u;
                    const bool force_direct_send = explicit_3d_target && !allow_bundle_v3;

                    if (allow_bundle_v2) {
                        if (explicit_3d_target && allow_bundle_v3) {
                            SpikeInterBundleCodec::BundleEntryV3 entry{};
                            entry.meta.block_id = t.block_id;
                            entry.meta.block_z = target_block_z;
                            entry.meta.ingress_node = t.ingress_node;
                            entry.meta.pre_global = source_global;
                            entry.meta.group_id = group_id;
                            entry.core_mask = t.core_mask;
                            bundle_entries_v3.emplace_back(std::move(entry));
                            continue;
                        }
                        if (!explicit_3d_target) {
                            SpikeInterBundleCodec::BundleEntryV2 entry{};
                            entry.meta.block_id = t.block_id;
                            entry.meta.ingress_node = t.ingress_node;
                            entry.meta.pre_global = source_global;
                            entry.meta.group_id = group_id;
                            entry.meta.reserved0 |= static_cast<uint16_t>(std::min<uint32_t>(target_block_z, 0xffu) << 8);
                            if (experimental_compact_mask_enable_) {
                                entry.meta.reserved0 |= SpikeInterBundleCodec::kEntryFlagCompactRouteV3;
                            }
                            entry.core_mask = t.core_mask;
                            bundle_entries_v2.emplace_back(std::move(entry));
                            continue;
                        }
                    }

                    std::vector<uint8_t> encoded_payload;
                    if (explicit_3d_target) {
                        SpikeNocCodec::WireSpikeKeyV4 ws{};
                        ws.version = 4;
                        ws.route_mode = 1; // blocked
                        ws.stage = 0;      // INTER
                        ws.block_w = static_cast<uint16_t>(bw);
                        ws.block_h = static_cast<uint16_t>(bh);
                        ws.block_d = static_cast<uint16_t>(target_block_d);
                        ws.block_id = t.block_id;
                        ws.ingress_node = t.ingress_node;
                        ws.pre_global = source_global;
                        ws.group_id = group_id;
                        ws.core_mask = t.core_mask;
                        SpikeNocCodec::encodeSpikeKey(ws, encoded_payload);
                    } else {
                        SpikeNocCodec::WireSpikeKeyV2 ws{};
                        ws.version = 2;
                        ws.route_mode = 1; // blocked
                        ws.stage = 0;      // INTER
                        ws.block_w_h = block_w_h;
                        ws.block_id = t.block_id;
                        ws.ingress_node = t.ingress_node;
                        ws.pre_global = source_global;
                        ws.group_id = group_id;
                        ws.core_mask = t.core_mask;

                        bool encoded = false;
                        if (experimental_compact_mask_enable_) {
                            encoded = SpikeNocCodec::encodeSpikeKeyCompactV3(ws, encoded_payload);
                        }
                        if (!encoded) {
                            SpikeNocCodec::encodeSpikeKey(ws, encoded_payload);
                        }
                    }

                    if (experimental_inter_bundle_enable_ && !force_direct_send) {
                        bundle_entries_v1.emplace_back(std::move(encoded_payload));
                        continue;
                    }

                    auto* pkt = new NocPacketEvent();
                    pkt->src_node = node_id_;
                    pkt->dst_node = t.ingress_node;
                    pkt->src_endpoint = static_cast<uint16_t>(src_core_);
                    pkt->dst_endpoint = 0;
                    pkt->kind = static_cast<uint16_t>(NocPacketKind::SpikeKey);
                    pkt->timestamp = now_cycle;
                    pkt->payload = std::move(encoded_payload);

                    noc_->sendFromCore(src_core_, pkt);
                    tx_spikekey_packets_total_ += 1;
                    if (explicit_3d_target) {
                        tx_spikekey_v4_packets_total_ += 1;
                    }
                }

                if (experimental_inter_bundle_enable_ && !bundle_entries_v1.empty()) {
                    const size_t chunk = static_cast<size_t>(experimental_inter_bundle_max_entries_);
                    for (size_t begin = 0; begin < bundle_entries_v1.size(); begin += chunk) {
                        const size_t end = std::min(bundle_entries_v1.size(), begin + chunk);
                        std::vector<std::vector<uint8_t>> part(bundle_entries_v1.begin() + begin, bundle_entries_v1.begin() + end);
                        auto* pkt = new NocPacketEvent();
                        pkt->src_node = node_id_;
                        pkt->dst_node = node_id_;
                        pkt->src_endpoint = static_cast<uint16_t>(src_core_);
                        pkt->dst_endpoint = 0;
                        pkt->kind = static_cast<uint16_t>(NocPacketKind::SpikeKey);
                        pkt->timestamp = now_cycle;
                        const uint64_t bseq = ++emit_seq_;
                        const uint64_t bundle_id = (bseq << 32) | static_cast<uint64_t>(source_global);
                        if (!SpikeInterBundleCodec::encode(
                                static_cast<uint16_t>(NocPacketKind::SpikeKey),
                                bundle_id,
                                part,
                                pkt->payload)) {
                            delete pkt;
                            continue;
                        }
                        noc_->sendFromCore(src_core_, pkt);
                        tx_spikekey_packets_total_ += 1;
                        tx_bundle_v1_packets_total_ += 1;
                    }
                }
                if (allow_bundle_v2 && !bundle_entries_v2.empty()) {
                    const size_t chunk = static_cast<size_t>(experimental_inter_bundle_max_entries_);
                    for (size_t begin = 0; begin < bundle_entries_v2.size(); begin += chunk) {
                        const size_t end = std::min(bundle_entries_v2.size(), begin + chunk);
                        std::vector<SpikeInterBundleCodec::BundleEntryV2> part(
                            bundle_entries_v2.begin() + begin,
                            bundle_entries_v2.begin() + end);
                        auto* pkt = new NocPacketEvent();
                        pkt->src_node = node_id_;
                        pkt->dst_node = node_id_;
                        pkt->src_endpoint = static_cast<uint16_t>(src_core_);
                        pkt->dst_endpoint = 0;
                        pkt->kind = static_cast<uint16_t>(NocPacketKind::SpikeKey);
                        pkt->timestamp = now_cycle;
                        const uint64_t bseq = ++emit_seq_;
                        const uint64_t bundle_id = (bseq << 32) | static_cast<uint64_t>(source_global);
                        if (!SpikeInterBundleCodec::encodeV2(
                                static_cast<uint16_t>(NocPacketKind::SpikeKey),
                                /*route_mode=*/1,
                                /*stage=*/0,
                                block_w_h,
                                bundle_id,
                                part,
                                pkt->payload)) {
                            delete pkt;
                            continue;
                        }
                        noc_->sendFromCore(src_core_, pkt);
                        tx_spikekey_packets_total_ += 1;
                        tx_bundle_v2_packets_total_ += 1;
                    }
                }
                if (allow_bundle_v3 && !bundle_entries_v3.empty()) {
                    const size_t chunk = static_cast<size_t>(experimental_inter_bundle_max_entries_);
                    for (size_t begin = 0; begin < bundle_entries_v3.size(); begin += chunk) {
                        const size_t end = std::min(bundle_entries_v3.size(), begin + chunk);
                        std::vector<SpikeInterBundleCodec::BundleEntryV3> part(
                            bundle_entries_v3.begin() + begin,
                            bundle_entries_v3.begin() + end);
                        auto* pkt = new NocPacketEvent();
                        pkt->src_node = node_id_;
                        pkt->dst_node = node_id_;
                        pkt->src_endpoint = static_cast<uint16_t>(src_core_);
                        pkt->dst_endpoint = 0;
                        pkt->kind = static_cast<uint16_t>(NocPacketKind::SpikeKey);
                        pkt->timestamp = now_cycle;
                        const uint64_t bseq = ++emit_seq_;
                        const uint64_t bundle_id = (bseq << 32) | static_cast<uint64_t>(source_global);
                        if (!SpikeInterBundleCodec::encodeV3(
                                static_cast<uint16_t>(NocPacketKind::SpikeKey),
                                /*route_mode=*/1,
                                /*stage=*/0,
                                static_cast<uint16_t>(bw),
                                static_cast<uint16_t>(bh),
                                static_cast<uint16_t>(bd),
                                bundle_id,
                                part,
                                pkt->payload)) {
                            delete pkt;
                            continue;
                        }
                        noc_->sendFromCore(src_core_, pkt);
                        tx_spikekey_packets_total_ += 1;
                        tx_bundle_v3_packets_total_ += 1;
                    }
                }
                return;
            }
    }

    if (!transport_) return;
    std::vector<ISynapseRoute::FanoutEntry> fanouts;
    bool applied_gating = false;
    synapse_route_->computeFanout(source_global, source_local, now_cycle, fanouts, applied_gating);
    if (fanouts.empty()) return;

    for (const auto& fe : fanouts) {
        auto* ev = new SpikeEvent(
            source_global,
            fe.dest_global,
            fe.dest_node,
            /*weight=*/fe.weight,
            now_cycle);
        // 传输层接管生命周期
        transport_->send(ev);
        tx_spike_packets_total_ += 1;
    }
}

void SpikeCommSubsystem::applyGatingDecision(uint32_t src_global,
                                             const std::vector<uint32_t>& dest_pes,
                                             uint64_t current_cycle,
                                             uint64_t ttl_cycles) {
    if (!synapse_route_) return;
    synapse_route_->applyGatingDecision(src_global, dest_pes, current_cycle, ttl_cycles);
}

}} // namespace SST::SnnDL
