// -*- c++ -*-
//
// SpikeTileBatchEmitter:
// - Experimental sender-side aggregation for SpikeTileKey.
// - Aggregates fired pre neurons by (target block_id, ingress_node, block_col)
//   and emits one packet with block_col + pre_mask.
//

#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "INocTransport.h"
#include "ISynapseRoute.h"
#include "NocPacketEvent.h"
#include "SpikeInterBundleCodec.h"
#include "SpikeTileNocCodec.h"

namespace SST { namespace SnnDL {

struct SpikeTileBatchEmitConfig final {
    uint32_t source_node = 0;
    uint16_t source_core = 0;
    uint32_t block_w = 0;
    uint32_t block_h = 0;
    uint32_t block_d = 1;
    uint32_t block_cols = 0;
    uint32_t max_pre_bits = 64;
    uint64_t* emit_seq = nullptr; // required for group-id uniqueness
    bool experimental_compact_mask_enable = false;
    bool experimental_inter_bundle_enable = false;
    uint32_t experimental_inter_bundle_max_entries = 64;
    bool experimental_inter_bundle_v2_enable = false;
    bool route_is_mesh_3d = false;
    bool native_target_authority = false;
    bool native_target_synthesis_active = false;
};

struct SpikeTileBatchStats final {
    uint64_t cohort_packets_total = 0;
    uint64_t cohort_pres_total = 0;
    uint64_t cohort_bandcolor_switch_total = 0;
    uint64_t tx_spiketilekey_v4_packets_total = 0;
    uint64_t tx_bundle_v1_packets_total = 0;
    uint64_t tx_bundle_v2_packets_total = 0;
    uint64_t tx_bundle_v3_packets_total = 0;
};

namespace detail {

struct TileAggKey final {
    uint32_t block_id = 0;
    uint32_t block_z = 0;
    uint32_t ingress_node = 0;
    uint32_t block_col = 0;

    bool operator==(const TileAggKey& rhs) const {
        return block_id == rhs.block_id &&
               block_z == rhs.block_z &&
               ingress_node == rhs.ingress_node &&
               block_col == rhs.block_col;
    }
};

struct TileAggKeyHash final {
    std::size_t operator()(const TileAggKey& key) const {
        const uint64_t a = (static_cast<uint64_t>(key.block_id) << 32) | static_cast<uint64_t>(key.block_z);
        const uint64_t b = (static_cast<uint64_t>(key.ingress_node) << 32) | static_cast<uint64_t>(key.block_col);
        return static_cast<std::size_t>((a * 11400714819323198485ull) ^ (b * 14029467366897019727ull));
    }
};

struct TileAggValue final {
    std::array<uint32_t, kMaxMulticastBlockCells> core_mask{};
    uint64_t pre_mask = 0;
};

} // namespace detail

inline bool emitSpikeTileBatchExperimental(const std::vector<uint32_t>& neuron_indices,
                                           uint64_t global_neuron_base,
                                           uint64_t now_cycle,
                                           const ISynapseRoute& route,
                                           INocTransport& noc,
                                           const SpikeTileBatchEmitConfig& cfg,
                                           uint64_t* emitted_packets = nullptr,
                                           SpikeTileBatchStats* batch_stats = nullptr) {
    if (neuron_indices.empty()) return false;
    if (cfg.block_cols == 0 || cfg.block_cols > 64) return false;
    if (cfg.max_pre_bits == 0 || cfg.max_pre_bits > 64) return false;
    if (cfg.block_cols > cfg.max_pre_bits) return false;
    if (cfg.experimental_inter_bundle_max_entries == 0) return false;
    if (cfg.block_w == 0 || cfg.block_h == 0 || cfg.block_d == 0) return false;
    if (!cfg.emit_seq) return false;
    if (!route.multicastEnabled()) return false;
    const uint32_t block_d = std::max<uint32_t>(cfg.block_d, 1u);
    const bool semantic_native_3d_target =
        cfg.route_is_mesh_3d &&
        cfg.native_target_authority &&
        cfg.native_target_synthesis_active;
    if (block_d > 1u && !semantic_native_3d_target) return false;
    const bool explicit_3d = semantic_native_3d_target && (block_d > 1u);
    const uint16_t block_w_h = static_cast<uint16_t>(((cfg.block_w & 0xffu) << 8) | (cfg.block_h & 0xffu));
    if (cfg.experimental_inter_bundle_enable &&
        cfg.experimental_inter_bundle_v2_enable &&
        !explicit_3d &&
        SpikeInterBundleCodec::blockCellsFromBlockWH(block_w_h) == 0) {
        return false;
    }
    if (cfg.experimental_inter_bundle_enable &&
        cfg.experimental_inter_bundle_v2_enable &&
        explicit_3d &&
        SpikeInterBundleCodec::blockCellsFromBlockShape(
            static_cast<uint16_t>(cfg.block_w),
            static_cast<uint16_t>(cfg.block_h),
            static_cast<uint16_t>(block_d)) == 0) {
        return false;
    }

    std::unordered_map<detail::TileAggKey, detail::TileAggValue, detail::TileAggKeyHash> agg;
    agg.reserve(neuron_indices.size());

    for (uint32_t neuron_idx : neuron_indices) {
        const uint32_t pre_global = static_cast<uint32_t>(global_neuron_base + static_cast<uint64_t>(neuron_idx));
        const uint32_t bit = pre_global % cfg.block_cols;
        if (bit >= cfg.max_pre_bits) continue;
        const uint32_t block_col = pre_global / cfg.block_cols;
        const uint64_t bit_mask = (1ull << bit);

        std::vector<ISynapseRoute::BlockTarget> targets;
        bool applied_gating = false;
        if (!route.computeMulticastTargets(pre_global, neuron_idx, now_cycle, targets, applied_gating) || targets.empty()) continue;
        (void)applied_gating;

        for (const auto& target : targets) {
            detail::TileAggKey key{};
            key.block_id = target.block_id;
            key.block_z = target.block_z;
            key.ingress_node = target.ingress_node;
            key.block_col = block_col;

            auto it = agg.find(key);
            if (it == agg.end()) {
                detail::TileAggValue init{};
                init.pre_mask = bit_mask;
                init.core_mask = target.core_mask;
                agg.emplace(key, std::move(init));
            } else {
                it->second.pre_mask |= bit_mask;
                for (uint32_t i = 0; i < kMaxMulticastBlockCells; ++i) {
                    it->second.core_mask[i] |= target.core_mask[i];
                }
            }
        }
    }

    if (agg.empty()) return false;

    uint64_t local_emitted_packets = 0;
    uint64_t local_cohort_packets = 0;
    uint64_t local_cohort_pres = 0;
    uint64_t local_tx_spiketilekey_v4_packets = 0;
    uint64_t local_tx_bundle_v1_packets = 0;
    uint64_t local_tx_bundle_v2_packets = 0;
    uint64_t local_tx_bundle_v3_packets = 0;
    std::vector<std::vector<uint8_t>> bundle_entries_v1;
    std::vector<SpikeInterBundleCodec::BundleEntryV2> bundle_entries_v2;
    std::vector<SpikeInterBundleCodec::BundleEntryV3> bundle_entries_v3;
    if (cfg.experimental_inter_bundle_enable) {
        if (cfg.experimental_inter_bundle_v2_enable) {
            if (explicit_3d) {
                bundle_entries_v3.reserve(agg.size());
            } else {
                bundle_entries_v2.reserve(agg.size());
            }
        } else {
            bundle_entries_v1.reserve(agg.size());
        }
    }
    for (const auto& kv : agg) {
        const auto& key = kv.first;
        const auto& val = kv.second;
        if (val.pre_mask == 0) continue;
        local_cohort_packets += 1;
        local_cohort_pres += static_cast<uint64_t>(__builtin_popcountll(static_cast<unsigned long long>(val.pre_mask)));
        const uint64_t seq = ++(*cfg.emit_seq);
        const uint64_t group_id = (seq << 32) | static_cast<uint64_t>(key.block_col);
        const uint32_t pre_global = static_cast<uint32_t>(
            static_cast<uint64_t>(key.block_col) * static_cast<uint64_t>(cfg.block_cols));
        const uint32_t target_block_d = std::max<uint32_t>(cfg.block_d, 1u);

        if (cfg.experimental_inter_bundle_enable && cfg.experimental_inter_bundle_v2_enable) {
            if (explicit_3d) {
                SpikeInterBundleCodec::BundleEntryV3 entry{};
                entry.meta.block_id = key.block_id;
                entry.meta.block_z = key.block_z;
                entry.meta.ingress_node = key.ingress_node;
                entry.meta.pre_global = pre_global;
                entry.meta.group_id = group_id;
                entry.meta.tile_version =
                    cfg.experimental_compact_mask_enable
                        ? static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV2)
                        : static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV1);
                entry.meta.tile_block_col = key.block_col;
                entry.meta.tile_pre_mask = val.pre_mask;
                entry.core_mask = val.core_mask;
                bundle_entries_v3.emplace_back(std::move(entry));
                continue;
            }

            SpikeInterBundleCodec::BundleEntryV2 entry{};
            entry.meta.block_id = key.block_id;
            entry.meta.ingress_node = key.ingress_node;
            entry.meta.pre_global = pre_global;
            entry.meta.group_id = group_id;
            entry.meta.tile_version =
                cfg.experimental_compact_mask_enable
                    ? static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV2)
                    : static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV1);
            entry.meta.tile_block_col = key.block_col;
            entry.meta.tile_pre_mask = val.pre_mask;
            entry.core_mask = val.core_mask;
            bundle_entries_v2.emplace_back(std::move(entry));
            continue;
        }

        std::vector<uint8_t> encoded_payload;
        bool encoded = false;
        if (explicit_3d) {
            SpikeTileNocCodec::WireSpikeTileKeyV2 ws{};
            ws.route.version = 4;
            ws.route.route_mode = SpikeTileNocCodec::kRouteModeSpikeTile;
            ws.route.stage = 0; // INTER
            ws.route.block_w = static_cast<uint16_t>(cfg.block_w);
            ws.route.block_h = static_cast<uint16_t>(cfg.block_h);
            ws.route.block_d = static_cast<uint16_t>(target_block_d);
            ws.route.block_id = key.block_id;
            ws.route.ingress_node = key.ingress_node;
            ws.route.pre_global = pre_global;
            ws.route.group_id = group_id;
            ws.route.core_mask = val.core_mask;
            ws.tile.tile_version =
                cfg.experimental_compact_mask_enable
                    ? static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV2)
                    : static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV1);
            ws.tile.block_col = key.block_col;
            ws.tile.pre_mask = val.pre_mask;

            if (cfg.experimental_compact_mask_enable) {
                encoded = SpikeTileNocCodec::encodeCompactV4(
                    ws.route,
                    ws.tile.block_col,
                    ws.tile.pre_mask,
                    encoded_payload);
            }
            if (!encoded) {
                SpikeTileNocCodec::encode(ws, encoded_payload);
            }
        } else {
            SpikeTileNocCodec::WireSpikeTileKeyV1 ws{};
            ws.route.version = 2;
            ws.route.route_mode = SpikeTileNocCodec::kRouteModeSpikeTile;
            ws.route.stage = 0; // INTER
            ws.route.block_w_h = block_w_h;
            ws.route.block_id = key.block_id;
            ws.route.ingress_node = key.ingress_node;
            ws.route.pre_global = pre_global;
            ws.route.group_id = group_id;
            ws.route.core_mask = val.core_mask;
            ws.tile.tile_version =
                cfg.experimental_compact_mask_enable
                    ? static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV2)
                    : static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV1);
            ws.tile.block_col = key.block_col;
            ws.tile.pre_mask = val.pre_mask;

            if (cfg.experimental_compact_mask_enable) {
                encoded = SpikeTileNocCodec::encodeCompactV2(
                    ws.route,
                    ws.tile.block_col,
                    ws.tile.pre_mask,
                    encoded_payload);
            }
            if (!encoded) {
                SpikeTileNocCodec::encode(ws, encoded_payload);
            }
        }

        if (cfg.experimental_inter_bundle_enable) {
            bundle_entries_v1.emplace_back(std::move(encoded_payload));
            continue;
        }

        auto* pkt = new NocPacketEvent();
        pkt->src_node = cfg.source_node;
        pkt->dst_node = key.ingress_node;
        pkt->src_endpoint = cfg.source_core;
        pkt->dst_endpoint = 0;
        pkt->kind = static_cast<uint16_t>(NocPacketKind::SpikeTileKey);
        pkt->timestamp = now_cycle;
        pkt->payload = std::move(encoded_payload);
        noc.sendFromCore(static_cast<int>(cfg.source_core), pkt);
        local_emitted_packets += 1;
        if (explicit_3d) {
            local_tx_spiketilekey_v4_packets += 1;
        }
    }

    if (cfg.experimental_inter_bundle_enable &&
        !cfg.experimental_inter_bundle_v2_enable &&
        !bundle_entries_v1.empty()) {
        const size_t chunk = static_cast<size_t>(cfg.experimental_inter_bundle_max_entries);
        for (size_t begin = 0; begin < bundle_entries_v1.size(); begin += chunk) {
            const size_t end = std::min(bundle_entries_v1.size(), begin + chunk);
            std::vector<std::vector<uint8_t>> part(bundle_entries_v1.begin() + begin, bundle_entries_v1.begin() + end);
            auto* pkt = new NocPacketEvent();
            pkt->src_node = cfg.source_node;
            pkt->dst_node = cfg.source_node;
            pkt->src_endpoint = cfg.source_core;
            pkt->dst_endpoint = 0;
            pkt->kind = static_cast<uint16_t>(NocPacketKind::SpikeTileKey);
            pkt->timestamp = now_cycle;
            const uint64_t bseq = ++(*cfg.emit_seq);
            const uint64_t bundle_id = (bseq << 32) | static_cast<uint64_t>(cfg.source_node);
            if (!SpikeInterBundleCodec::encode(
                    static_cast<uint16_t>(NocPacketKind::SpikeTileKey),
                    bundle_id,
                    part,
                    pkt->payload)) {
                delete pkt;
                continue;
            }
            noc.sendFromCore(static_cast<int>(cfg.source_core), pkt);
            local_emitted_packets += 1;
            local_tx_bundle_v1_packets += 1;
        }
    }
    if (cfg.experimental_inter_bundle_enable &&
        cfg.experimental_inter_bundle_v2_enable &&
        !bundle_entries_v2.empty()) {
        const size_t chunk = static_cast<size_t>(cfg.experimental_inter_bundle_max_entries);
        for (size_t begin = 0; begin < bundle_entries_v2.size(); begin += chunk) {
            const size_t end = std::min(bundle_entries_v2.size(), begin + chunk);
            std::vector<SpikeInterBundleCodec::BundleEntryV2> part(
                bundle_entries_v2.begin() + begin,
                bundle_entries_v2.begin() + end);
            auto* pkt = new NocPacketEvent();
            pkt->src_node = cfg.source_node;
            pkt->dst_node = cfg.source_node;
            pkt->src_endpoint = cfg.source_core;
            pkt->dst_endpoint = 0;
            pkt->kind = static_cast<uint16_t>(NocPacketKind::SpikeTileKey);
            pkt->timestamp = now_cycle;
            const uint64_t bseq = ++(*cfg.emit_seq);
            const uint64_t bundle_id = (bseq << 32) | static_cast<uint64_t>(cfg.source_node);
            if (!SpikeInterBundleCodec::encodeV2(
                    static_cast<uint16_t>(NocPacketKind::SpikeTileKey),
                    /*route_mode=*/SpikeTileNocCodec::kRouteModeSpikeTile,
                    /*stage=*/0,
                    block_w_h,
                    bundle_id,
                    part,
                    pkt->payload)) {
                delete pkt;
                continue;
            }
            noc.sendFromCore(static_cast<int>(cfg.source_core), pkt);
            local_emitted_packets += 1;
            local_tx_bundle_v2_packets += 1;
        }
    }
    if (cfg.experimental_inter_bundle_enable &&
        cfg.experimental_inter_bundle_v2_enable &&
        !bundle_entries_v3.empty()) {
        const size_t chunk = static_cast<size_t>(cfg.experimental_inter_bundle_max_entries);
        for (size_t begin = 0; begin < bundle_entries_v3.size(); begin += chunk) {
            const size_t end = std::min(bundle_entries_v3.size(), begin + chunk);
            std::vector<SpikeInterBundleCodec::BundleEntryV3> part(
                bundle_entries_v3.begin() + begin,
                bundle_entries_v3.begin() + end);
            auto* pkt = new NocPacketEvent();
            pkt->src_node = cfg.source_node;
            pkt->dst_node = cfg.source_node;
            pkt->src_endpoint = cfg.source_core;
            pkt->dst_endpoint = 0;
            pkt->kind = static_cast<uint16_t>(NocPacketKind::SpikeTileKey);
            pkt->timestamp = now_cycle;
            const uint64_t bseq = ++(*cfg.emit_seq);
            const uint64_t bundle_id = (bseq << 32) | static_cast<uint64_t>(cfg.source_node);
            if (!SpikeInterBundleCodec::encodeV3(
                    static_cast<uint16_t>(NocPacketKind::SpikeTileKey),
                    /*route_mode=*/SpikeTileNocCodec::kRouteModeSpikeTile,
                    /*stage=*/0,
                    static_cast<uint16_t>(cfg.block_w),
                    static_cast<uint16_t>(cfg.block_h),
                    static_cast<uint16_t>(block_d),
                    bundle_id,
                    part,
                    pkt->payload)) {
                delete pkt;
                continue;
            }
            noc.sendFromCore(static_cast<int>(cfg.source_core), pkt);
            local_emitted_packets += 1;
            local_tx_bundle_v3_packets += 1;
        }
    }

    if (emitted_packets) {
        *emitted_packets += local_emitted_packets;
    }
    if (batch_stats) {
        batch_stats->cohort_packets_total += local_cohort_packets;
        batch_stats->cohort_pres_total += local_cohort_pres;
        batch_stats->cohort_bandcolor_switch_total += 0;
        batch_stats->tx_spiketilekey_v4_packets_total += local_tx_spiketilekey_v4_packets;
        batch_stats->tx_bundle_v1_packets_total += local_tx_bundle_v1_packets;
        batch_stats->tx_bundle_v2_packets_total += local_tx_bundle_v2_packets;
        batch_stats->tx_bundle_v3_packets_total += local_tx_bundle_v3_packets;
    }

    return true;
}

}} // namespace SST::SnnDL
