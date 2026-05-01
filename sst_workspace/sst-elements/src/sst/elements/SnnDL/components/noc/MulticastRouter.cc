// -*- c++ -*-
//
// MulticastRouter implementation
//

#include "MulticastRouter.h"
#include "MulticastRouterConfig.h"
#include "LocalEndpointMulticastCodec.h"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <cstdlib>
#include <string>
#include <inttypes.h>
#include <vector>

#include <sst/core/event.h>
#include <sst/core/params.h>

#include "SnnDLStringUtil.h"
#include "NocPacketEvent.h"
#include "synapse/route/SpikeInterBundleCodec.h"
#include "synapse/route/SpikeNocCodec.h"
#include "synapse/route/SpikeTileNocCodec.h"

namespace SST { namespace SnnDL {

namespace {

inline bool anyMask_(const SpikeNocCodec::WireSpikeKeyV2& ws, uint32_t cells) {
    const uint32_t n = std::min<uint32_t>(cells, kMaxMulticastBlockCells);
    for (uint32_t i = 0; i < n; ++i) {
        if (ws.core_mask[i] != 0) return true;
    }
    return false;
}

inline uint32_t idxOfLocal_(uint32_t local_x, uint32_t local_y, uint32_t block_w) {
    return local_y * block_w + local_x;
}

} // namespace

MulticastRouter::MulticastRouter(SST::ComponentId_t id, SST::Params& params)
    : SST::Component(id),
      out_("SnnDL.MulticastRouter", 0, 0, SST::Output::STDOUT),
      timebase_(getTimeConverter("1ns")) {
    const MulticastRouterConfig cfg = parseMulticastRouterConfig(params);
    out_.setVerboseLevel(cfg.verbose);

    node_id_ = cfg.node_id;
    router_latency_cycles_ = cfg.router_latency_cycles;
    serialize_output_enable_ = cfg.serialize_output_enable;
    serialize_service_cycles_ = cfg.serialize_service_cycles;
    serialize_output_byte_enable_ = cfg.serialize_output_byte_enable;
    serialize_bytes_per_cycle_ = (cfg.serialize_bytes_per_cycle > 0) ? cfg.serialize_bytes_per_cycle : 1;
    serialize_header_bytes_ = cfg.serialize_header_bytes;
    local_endpoint_multicast_enable_ = cfg.local_endpoint_multicast_enable;
    adaptive_telemetry_enable_ = cfg.adaptive_telemetry_enable;
    adaptive_inter_w_wait_ = cfg.adaptive_inter_w_wait;
    adaptive_inter_w_service_ = cfg.adaptive_inter_w_service;
    adaptive_inter_w_len_ = cfg.adaptive_inter_w_len;
    adaptive_intra_w_bytes_ = cfg.adaptive_intra_w_bytes;
    adaptive_intra_w_queue_ = cfg.adaptive_intra_w_queue;

    {
        const std::string inter = cfg.multicast_inter_policy;
        if (!parseInterPolicy_(inter, multicast_inter_policy_)) {
            out_.fatal(
                CALL_INFO, -1,
                "Invalid multicast_inter_policy='%s' (supported: xy,yx,hash_xy,adaptive_xy_yx)\n",
                inter.c_str());
        }
        const std::string intra = cfg.multicast_intra_policy;
        if (!parseIntraPolicy_(intra, multicast_intra_policy_)) {
            out_.fatal(
                CALL_INFO, -1,
                "Invalid multicast_intra_policy='%s' (supported: manhattan_x_first,manhattan_y_first,adaptive)\n",
                intra.c_str());
        }
    }

    const std::string mesh_shape = cfg.mesh_shape;
    if (!parseMeshShape_(mesh_shape, mesh_w_, mesh_h_, mesh_z_) || mesh_w_ == 0 || mesh_h_ == 0 || mesh_z_ == 0) {
        out_.fatal(CALL_INFO, -1, "Invalid mesh_shape='%s'\n", mesh_shape.c_str());
    }

    local_link_ = configureLink("local", new SST::Event::Handler2<MulticastRouter, &MulticastRouter::handleLocalLinkEvent>(this));
    north_link_ = configureLink("north", new SST::Event::Handler2<MulticastRouter, &MulticastRouter::handleNorthLinkEvent>(this));
    south_link_ = configureLink("south", new SST::Event::Handler2<MulticastRouter, &MulticastRouter::handleSouthLinkEvent>(this));
    east_link_ = configureLink("east", new SST::Event::Handler2<MulticastRouter, &MulticastRouter::handleEastLinkEvent>(this));
    west_link_ = configureLink("west", new SST::Event::Handler2<MulticastRouter, &MulticastRouter::handleWestLinkEvent>(this));
}

MulticastRouter::~MulticastRouter() = default;

void MulticastRouter::init(unsigned int /*phase*/) {}
void MulticastRouter::setup() {}
void MulticastRouter::finish() {
    // 注意：避免使用 Output::output() 造成默认刷屏；统一走 verbose 门控
    out_.verbose(
        CALL_INFO, 1, 0,
        "[mcast-router] node=%u in=%" PRIu64 " out=%" PRIu64 " local=%" PRIu64 " fwd_xy=%" PRIu64
        " bytes_in=%" PRIu64 " bytes_out=%" PRIu64 " bytes_local=%" PRIu64 " bytes_fwd_xy=%" PRIu64
        " byte_hops=%" PRIu64
        " spikekey_in=%" PRIu64 " stage_inter=%" PRIu64 " stage_intra=%" PRIu64 " clones=%" PRIu64
        " adi_inter_decisions=%" PRIu64 " adi_inter_choose_x=%" PRIu64 " adi_inter_choose_y=%" PRIu64
        " adi_inter_tie=%" PRIu64 " adi_inter_cost_x=%" PRIu64 " adi_inter_cost_y=%" PRIu64
        " adi_inter_cost_chosen=%" PRIu64 " adi_inter_cost_delta_abs=%" PRIu64
        " adi_intra_decisions=%" PRIu64 " adi_intra_choose_x=%" PRIu64 " adi_intra_choose_y=%" PRIu64
        " adi_intra_tie=%" PRIu64 " adi_intra_cost_x=%" PRIu64 " adi_intra_cost_y=%" PRIu64
        " adi_intra_cost_chosen=%" PRIu64 " adi_intra_cost_delta_abs=%" PRIu64
        " adi_intra_pred_bytes_x=%" PRIu64 " adi_intra_pred_bytes_y=%" PRIu64
        " adi_intra_pred_bytes_chosen=%" PRIu64 " adi_intra_pred_bytes_delta_abs=%" PRIu64
        " adi_intra_queue_x=%" PRIu64 " adi_intra_queue_y=%" PRIu64 " adi_intra_queue_chosen=%" PRIu64
        "\n",
        node_id_,
        pkts_in_total_,
        pkts_out_total_,
        pkts_to_local_,
        pkts_forward_xy_,
        bytes_in_total_,
        bytes_out_total_,
        bytes_to_local_,
        bytes_forward_xy_,
        byte_hops_total_,
        spikekey_in_total_,
        spikekey_stage_inter_,
        spikekey_stage_intra_,
        spikekey_clones_total_,
        adaptive_inter_decisions_total_,
        adaptive_inter_choose_x_total_,
        adaptive_inter_choose_y_total_,
        adaptive_inter_tie_total_,
        adaptive_inter_cost_x_total_,
        adaptive_inter_cost_y_total_,
        adaptive_inter_cost_chosen_total_,
        adaptive_inter_cost_delta_abs_total_,
        adaptive_intra_decisions_total_,
        adaptive_intra_choose_x_total_,
        adaptive_intra_choose_y_total_,
        adaptive_intra_tie_total_,
        adaptive_intra_cost_x_total_,
        adaptive_intra_cost_y_total_,
        adaptive_intra_cost_chosen_total_,
        adaptive_intra_cost_delta_abs_total_,
        adaptive_intra_pred_bytes_x_total_,
        adaptive_intra_pred_bytes_y_total_,
        adaptive_intra_pred_bytes_chosen_total_,
        adaptive_intra_pred_bytes_delta_abs_total_,
        adaptive_intra_queue_x_total_,
        adaptive_intra_queue_y_total_,
        adaptive_intra_queue_chosen_total_);
}

void MulticastRouter::handleLocalLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    handlePacket_(pkt);
}

void MulticastRouter::handleNorthLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    handlePacket_(pkt);
}

void MulticastRouter::handleSouthLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    handlePacket_(pkt);
}

void MulticastRouter::handleEastLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    handlePacket_(pkt);
}

void MulticastRouter::handleWestLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    handlePacket_(pkt);
}

void MulticastRouter::handlePacket_(NocPacketEvent* pkt) {
    if (!pkt) return;
    pkt->hop_count += 1;
    pkts_in_total_ += 1;
    bytes_in_total_ += packetBytes_(pkt);
    if (pkt->packetKind() == NocPacketKind::SpikeKey || pkt->packetKind() == NocPacketKind::SpikeTileKey) {
        spikekey_in_total_ += 1;
    }

    if (pkt->packetKind() == NocPacketKind::SpikeKey || pkt->packetKind() == NocPacketKind::SpikeTileKey) {
        routeSpikeKey_(pkt);
        return;
    }

    routeUnicastXY_(pkt);
}

void MulticastRouter::routeUnicastXY_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (pkt->dst_node == node_id_) {
        sendToLocal_(pkt);
        return;
    }

    if (mesh_w_ == 0) { delete pkt; return; }
    uint32_t x = 0, y = 0, z = 0;
    uint32_t dest_x = 0, dest_y = 0, dest_z = 0;
    if (!nodeIdToCoord2DLayered_(node_id_, mesh_w_, mesh_h_, mesh_z_, x, y, z) ||
        !nodeIdToCoord2DLayered_(pkt->dst_node, mesh_w_, mesh_h_, mesh_z_, dest_x, dest_y, dest_z)) {
        delete pkt;
        return;
    }
    if (z != dest_z) {
        // layered-2d router cannot forward across z; each die remains an independent 2D plane.
        out_.verbose(CALL_INFO, 2, 0,
                     "[mcast-router] drop cross-z unicast self=%u dst=%u self_z=%u dst_z=%u\n",
                     node_id_, pkt->dst_node, z, dest_z);
        delete pkt;
        return;
    }

    if (x < dest_x) { sendToEast_(pkt); return; }
    if (x > dest_x) { sendToWest_(pkt); return; }
    if (y < dest_y) { sendToSouth_(pkt); return; }
    if (y > dest_y) { sendToNorth_(pkt); return; }

    sendToLocal_(pkt);
}

void MulticastRouter::routeUnicastYX_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (pkt->dst_node == node_id_) {
        sendToLocal_(pkt);
        return;
    }

    if (mesh_w_ == 0) { delete pkt; return; }
    uint32_t x = 0, y = 0, z = 0;
    uint32_t dest_x = 0, dest_y = 0, dest_z = 0;
    if (!nodeIdToCoord2DLayered_(node_id_, mesh_w_, mesh_h_, mesh_z_, x, y, z) ||
        !nodeIdToCoord2DLayered_(pkt->dst_node, mesh_w_, mesh_h_, mesh_z_, dest_x, dest_y, dest_z)) {
        delete pkt;
        return;
    }
    if (z != dest_z) {
        // layered-2d router cannot forward across z; each die remains an independent 2D plane.
        out_.verbose(CALL_INFO, 2, 0,
                     "[mcast-router] drop cross-z unicast self=%u dst=%u self_z=%u dst_z=%u\n",
                     node_id_, pkt->dst_node, z, dest_z);
        delete pkt;
        return;
    }

    if (y < dest_y) { sendToSouth_(pkt); return; }
    if (y > dest_y) { sendToNorth_(pkt); return; }
    if (x < dest_x) { sendToEast_(pkt); return; }
    if (x > dest_x) { sendToWest_(pkt); return; }

    sendToLocal_(pkt);
}

void MulticastRouter::routeSpikeKey_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (SpikeInterBundleCodec::isBundlePayload(pkt->payload)) {
        routeSpikeInterBundle_(pkt);
        return;
    }

    SpikeNocCodec::WireSpikeKeyV2 ws{};
    if (!SpikeNocCodec::decodeSpikeKeyAny(pkt->payload, ws)) {
        delete pkt;
        return;
    }
    if (ws.version != 1 && ws.version != 2 && ws.version != 3) { delete pkt; return; }

    constexpr uint16_t kStageInter = 0;
    constexpr uint16_t kStageIntra = 1;

    const uint32_t block_w = static_cast<uint32_t>((ws.block_w_h >> 8) & 0xffu);
    const uint32_t block_h = static_cast<uint32_t>((ws.block_w_h) & 0xffu);
    if (block_w == 0 || block_h == 0) { delete pkt; return; }
    const uint32_t block_cells = block_w * block_h;
    if (block_cells == 0 || block_cells > kMaxMulticastBlockCells) { delete pkt; return; }
    if (!anyMask_(ws, block_cells)) { delete pkt; return; }

    // INTER: unicast XY towards ingress (dst_node should already be ingress_node).
    if (ws.stage == kStageInter) {
        spikekey_stage_inter_ += 1;
        if (node_id_ == ws.ingress_node) {
            ws.stage = kStageIntra;
            // Preserve optional payload tails (e.g. SpikeTileKey) and compact V3 layouts by patching only stage in-place.
            if (!SpikeNocCodec::patchStageInPayload(pkt->payload, ws.stage)) {
                delete pkt;
                return;
            }
            // fallthrough to INTRA routing on ingress
        } else {
            if (mesh_w_ == 0 || mesh_h_ == 0) {
                delete pkt;
                return;
            }
            pkt->dst_node = ws.ingress_node;

            uint32_t self_x_inter = 0, self_y_inter = 0, self_z_inter = 0;
            uint32_t dest_x_inter = 0, dest_y_inter = 0, dest_z_inter = 0;
            if (!nodeIdToCoord2DLayered_(node_id_, mesh_w_, mesh_h_, mesh_z_, self_x_inter, self_y_inter, self_z_inter) ||
                !nodeIdToCoord2DLayered_(ws.ingress_node, mesh_w_, mesh_h_, mesh_z_, dest_x_inter, dest_y_inter, dest_z_inter)) {
                delete pkt;
                return;
            }
            if (self_z_inter != dest_z_inter) {
                // layered-2d router cannot forward across z; each die remains an independent 2D plane.
                out_.verbose(CALL_INFO, 2, 0,
                             "[mcast-router] drop cross-z inter self=%u ingress=%u self_z=%u dst_z=%u\n",
                             node_id_, ws.ingress_node, self_z_inter, dest_z_inter);
                delete pkt;
                return;
            }

            auto estimateInterDirCost = [&](uint8_t dir, uint64_t payload_bytes, uint64_t len_bias) -> uint64_t {
                uint32_t port_idx = 0;
                if (dir == 1) port_idx = 1;      // north
                else if (dir == 2) port_idx = 2; // south
                else if (dir == 3) port_idx = 3; // east
                else if (dir == 4) port_idx = 4; // west
                else return 0;
                uint64_t wait = 0;
                uint64_t service_cycles = 1;
                if (serialize_output_enable_) {
                    const uint64_t now = static_cast<uint64_t>(getCurrentSimTime(timebase_));
                    const uint64_t next_free = port_next_free_cycle_[port_idx];
                    wait = (next_free > now) ? (next_free - now) : 0;
                    service_cycles = serialize_service_cycles_;
                    if (serialize_output_byte_enable_) {
                        const uint64_t total_bytes = serialize_header_bytes_ + payload_bytes;
                        service_cycles = (total_bytes + serialize_bytes_per_cycle_ - 1ull) / serialize_bytes_per_cycle_;
                        if (service_cycles == 0) service_cycles = 1;
                    }
                }
                return adaptive_inter_w_wait_ * wait + adaptive_inter_w_service_ * service_cycles
                       + adaptive_inter_w_len_ * len_bias;
            };

            uint8_t inter_dir = 0;
            if (multicast_inter_policy_ == InterBlockRoutePolicy::HashXY) {
                const uint64_t h = ws.group_id ^ static_cast<uint64_t>(ws.pre_global) ^ static_cast<uint64_t>(ws.block_id);
                const bool use_yx = ((h & 1ull) != 0ull);
                if (use_yx) {
                    if (self_y_inter < dest_y_inter) inter_dir = 2;
                    else if (self_y_inter > dest_y_inter) inter_dir = 1;
                    else if (self_x_inter < dest_x_inter) inter_dir = 3;
                    else if (self_x_inter > dest_x_inter) inter_dir = 4;
                } else {
                    if (self_x_inter < dest_x_inter) inter_dir = 3;
                    else if (self_x_inter > dest_x_inter) inter_dir = 4;
                    else if (self_y_inter < dest_y_inter) inter_dir = 2;
                    else if (self_y_inter > dest_y_inter) inter_dir = 1;
                }
            } else if (multicast_inter_policy_ == InterBlockRoutePolicy::YX) {
                if (self_y_inter < dest_y_inter) inter_dir = 2;
                else if (self_y_inter > dest_y_inter) inter_dir = 1;
                else if (self_x_inter < dest_x_inter) inter_dir = 3;
                else if (self_x_inter > dest_x_inter) inter_dir = 4;
            } else if (multicast_inter_policy_ == InterBlockRoutePolicy::AdaptiveXYYX) {
                const uint8_t dir_x = (self_x_inter < dest_x_inter) ? 3u : ((self_x_inter > dest_x_inter) ? 4u : 0u);
                const uint8_t dir_y = (self_y_inter < dest_y_inter) ? 2u : ((self_y_inter > dest_y_inter) ? 1u : 0u);
                if (dir_x != 0u && dir_y != 0u) {
                    const uint64_t dx = (self_x_inter > dest_x_inter)
                                            ? static_cast<uint64_t>(self_x_inter - dest_x_inter)
                                            : static_cast<uint64_t>(dest_x_inter - self_x_inter);
                    const uint64_t dy = (self_y_inter > dest_y_inter)
                                            ? static_cast<uint64_t>(self_y_inter - dest_y_inter)
                                            : static_cast<uint64_t>(dest_y_inter - self_y_inter);
                    const uint64_t payload_bytes = static_cast<uint64_t>(pkt->payload.size());
                    const uint64_t cost_x = estimateInterDirCost(dir_x, payload_bytes, dy);
                    const uint64_t cost_y = estimateInterDirCost(dir_y, payload_bytes, dx);
                    if (cost_x < cost_y) inter_dir = dir_x;
                    else if (cost_y < cost_x) inter_dir = dir_y;
                    else {
                        const uint64_t h =
                            ws.group_id ^ static_cast<uint64_t>(ws.pre_global) ^ static_cast<uint64_t>(ws.block_id);
                        inter_dir = ((h & 1ull) != 0ull) ? dir_y : dir_x;
                    }

                    if (adaptive_telemetry_enable_) {
                        adaptive_inter_decisions_total_ += 1;
                        adaptive_inter_cost_x_total_ += cost_x;
                        adaptive_inter_cost_y_total_ += cost_y;
                        const uint64_t delta_abs = (cost_x > cost_y) ? (cost_x - cost_y) : (cost_y - cost_x);
                        adaptive_inter_cost_delta_abs_total_ += delta_abs;
                        if (cost_x == cost_y) adaptive_inter_tie_total_ += 1;
                        if (inter_dir == dir_x) adaptive_inter_choose_x_total_ += 1;
                        else adaptive_inter_choose_y_total_ += 1;
                        const uint64_t chosen_cost = (inter_dir == dir_x) ? cost_x : cost_y;
                        adaptive_inter_cost_chosen_total_ += chosen_cost;
                    }
                } else {
                    inter_dir = (dir_x != 0u) ? dir_x : dir_y;
                }
            } else {
                if (self_x_inter < dest_x_inter) inter_dir = 3;
                else if (self_x_inter > dest_x_inter) inter_dir = 4;
                else if (self_y_inter < dest_y_inter) inter_dir = 2;
                else if (self_y_inter > dest_y_inter) inter_dir = 1;
            }
            if (inter_dir == 1u) sendToNorth_(pkt);
            else if (inter_dir == 2u) sendToSouth_(pkt);
            else if (inter_dir == 3u) sendToEast_(pkt);
            else if (inter_dir == 4u) sendToWest_(pkt);
            else sendToLocal_(pkt);
            return;
        }
    }

    if (ws.stage != kStageIntra) {
        delete pkt;
        return;
    }
    spikekey_stage_intra_ += 1;

    // INTRA: blocked multicast tree (arbitrary block_w x block_h, rooted at ingress_node).
    if (mesh_w_ == 0) { delete pkt; return; }
    uint32_t self_x = 0, self_y = 0, self_z = 0;
    if (!nodeIdToCoord2DLayered_(node_id_, mesh_w_, mesh_h_, mesh_z_, self_x, self_y, self_z)) {
        delete pkt;
        return;
    }

    // block origin derived from block_id (core_mask indices are always in block-top-left order)
    const uint32_t blocks_w = mesh_w_ / block_w;
    const uint32_t blocks_h = mesh_h_ / block_h;
    if (blocks_w == 0 || blocks_h == 0) { delete pkt; return; }
    if (ws.block_id >= blocks_w * blocks_h) { delete pkt; return; }
    const uint32_t block_x0 = (ws.block_id % blocks_w) * block_w;
    const uint32_t block_y0 = (ws.block_id / blocks_w) * block_h;

    if (self_x < block_x0 || self_y < block_y0) { delete pkt; return; }
    const uint32_t local_x = self_x - block_x0;
    const uint32_t local_y = self_y - block_y0;
    if (local_x >= block_w || local_y >= block_h) { delete pkt; return; }

    const uint32_t idx_self = idxOfLocal_(local_x, local_y, block_w); // block-relative
    if (idx_self >= block_cells || idx_self >= kMaxMulticastBlockCells) { delete pkt; return; }

    uint32_t ingress_x = 0, ingress_y = 0, ingress_z = 0;
    if (!nodeIdToCoord2DLayered_(ws.ingress_node, mesh_w_, mesh_h_, mesh_z_, ingress_x, ingress_y, ingress_z)) {
        delete pkt;
        return;
    }
    if (self_z != ingress_z) {
        // layered-2d router cannot forward across z; each die remains an independent 2D plane.
        out_.verbose(CALL_INFO, 2, 0,
                     "[mcast-router] drop cross-z intra self=%u ingress=%u self_z=%u ingress_z=%u\n",
                     node_id_, ws.ingress_node, self_z, ingress_z);
        delete pkt;
        return;
    }
    if (ingress_x < block_x0 || ingress_y < block_y0) { delete pkt; return; }
    if (ingress_x >= block_x0 + block_w || ingress_y >= block_y0 + block_h) { delete pkt; return; }
    const uint32_t ingress_lx = ingress_x - block_x0;
    const uint32_t ingress_ly = ingress_y - block_y0;
    if (ingress_lx >= block_w || ingress_ly >= block_h) { delete pkt; return; }

    auto deliverLocalMask = [&](uint32_t core_mask) {
        if (!core_mask) return;
        if (local_endpoint_multicast_enable_ && ((core_mask & (core_mask - 1u)) != 0u)) {
            auto* c = static_cast<NocPacketEvent*>(pkt->clone());
            c->dst_node = node_id_;
            c->dst_endpoint = kEndpointFanoutSentinel;
            appendLocalEndpointMaskTail(c->payload, core_mask);
            spikekey_clones_total_ += 1;
            sendToLocal_(c);
            return;
        }
        for (uint32_t bit = 0; bit < 32; ++bit) {
            if ((core_mask & (1u << bit)) == 0) continue;
            auto* c = static_cast<NocPacketEvent*>(pkt->clone());
            spikekey_clones_total_ += 1;
            c->dst_node = node_id_;
            c->dst_endpoint = static_cast<uint16_t>(bit);
            sendToLocal_(c);
        }
    };

    auto estimateQueueDirCost = [&](uint8_t dir, uint64_t payload_bytes) -> uint64_t {
        uint32_t port_idx = 0;
        if (dir == 1) port_idx = 1;      // north
        else if (dir == 2) port_idx = 2; // south
        else if (dir == 3) port_idx = 3; // east
        else if (dir == 4) port_idx = 4; // west
        else return 0;
        uint64_t wait = 0;
        uint64_t service_cycles = 1;
        if (serialize_output_enable_) {
            const uint64_t now = static_cast<uint64_t>(getCurrentSimTime(timebase_));
            const uint64_t next_free = port_next_free_cycle_[port_idx];
            wait = (next_free > now) ? (next_free - now) : 0;
            service_cycles = serialize_service_cycles_;
            if (serialize_output_byte_enable_) {
                const uint64_t total_bytes = serialize_header_bytes_ + payload_bytes;
                service_cycles = (total_bytes + serialize_bytes_per_cycle_ - 1ull) / serialize_bytes_per_cycle_;
                if (service_cycles == 0) service_cycles = 1;
            }
        }
        return wait + service_cycles;
    };

    auto localDeliveryUnits = [&](uint32_t core_mask) -> uint64_t {
        if (core_mask == 0u) return 0;
        if (local_endpoint_multicast_enable_ && ((core_mask & (core_mask - 1u)) != 0u)) return 1;
        return static_cast<uint64_t>(__builtin_popcount(core_mask));
    };

    auto parentOf = [&](bool x_first, uint32_t cx, uint32_t cy, uint32_t& out_px, uint32_t& out_py) {
        out_px = cx;
        out_py = cy;
        if (cx == ingress_lx && cy == ingress_ly) return; // root has no parent
        if (x_first) {
            if (cx != ingress_lx) {
                out_px = (ingress_lx > cx) ? (cx + 1u) : (cx - 1u);
                return;
            }
            if (cy != ingress_ly) {
                out_py = (ingress_ly > cy) ? (cy + 1u) : (cy - 1u);
                return;
            }
        } else {
            if (cy != ingress_ly) {
                out_py = (ingress_ly > cy) ? (cy + 1u) : (cy - 1u);
                return;
            }
            if (cx != ingress_lx) {
                out_px = (ingress_lx > cx) ? (cx + 1u) : (cx - 1u);
                return;
            }
        }
    };

    auto isChild = [&](uint32_t child_x, uint32_t child_y, bool x_first) -> bool {
        if (child_x >= block_w || child_y >= block_h) return false;
        uint32_t px = 0, py = 0;
        parentOf(x_first, child_x, child_y, px, py);
        return (px == local_x) && (py == local_y);
    };

    auto subtreeHasAny = [&](uint32_t child_x, uint32_t child_y, bool x_first) -> bool {
        // quick reject for invalid child
        if (!isChild(child_x, child_y, x_first)) return false;
        for (uint32_t idx = 0; idx < block_cells && idx < kMaxMulticastBlockCells; ++idx) {
            if (ws.core_mask[idx] == 0) continue;
            const uint32_t cx0 = idx % block_w;
            const uint32_t cy0 = idx / block_w;
            if (cx0 == local_x && cy0 == local_y) continue;

            uint32_t cx = cx0;
            uint32_t cy = cy0;
            while (!(cx == ingress_lx && cy == ingress_ly) &&
                   !(cx == local_x && cy == local_y) &&
                   !(cx == child_x && cy == child_y)) {
                uint32_t px = 0, py = 0;
                parentOf(x_first, cx, cy, px, py);
                if (px == cx && py == cy) break;
                cx = px;
                cy = py;
            }
            if (cx == child_x && cy == child_y) return true;
        }
        return false;
    };

    auto buildChildUse = [&](bool x_first, std::array<bool, 4>& used) {
        used = {false, false, false, false}; // east,west,south,north
        if (local_x + 1u < block_w) used[0] = subtreeHasAny(local_x + 1u, local_y, x_first);
        if (local_x > 0u) used[1] = subtreeHasAny(local_x - 1u, local_y, x_first);
        if (local_y + 1u < block_h) used[2] = subtreeHasAny(local_x, local_y + 1u, x_first);
        if (local_y > 0u) used[3] = subtreeHasAny(local_x, local_y - 1u, x_first);
    };

    auto buildIntraEstimate = [&](bool x_first,
                                  std::array<bool, 4>& used,
                                  uint64_t& pred_bytes_out,
                                  uint64_t& queue_cost) {
        buildChildUse(x_first, used);
        const uint64_t payload_bytes = static_cast<uint64_t>(pkt->payload.size());

        queue_cost = 0;
        if (used[0]) queue_cost += estimateQueueDirCost(3, payload_bytes); // east
        if (used[1]) queue_cost += estimateQueueDirCost(4, payload_bytes); // west
        if (used[2]) queue_cost += estimateQueueDirCost(2, payload_bytes); // south
        if (used[3]) queue_cost += estimateQueueDirCost(1, payload_bytes); // north

        uint64_t local_units_sum = 0;
        std::vector<uint32_t> edge_keys;
        edge_keys.reserve(block_cells * 2u);
        auto addEdge = [&](uint32_t parent_idx, uint32_t child_idx) {
            const uint32_t key = (parent_idx << 16u) | (child_idx & 0xffffu);
            for (const uint32_t existed : edge_keys) {
                if (existed == key) return;
            }
            edge_keys.push_back(key);
        };

        for (uint32_t idx = 0; idx < block_cells && idx < kMaxMulticastBlockCells; ++idx) {
            if (ws.core_mask[idx] == 0u) continue;
            const uint32_t rx = idx % block_w;
            const uint32_t ry = idx / block_w;
            if (rx == local_x && ry == local_y) {
                local_units_sum += localDeliveryUnits(ws.core_mask[idx]);
                continue;
            }

            uint32_t cx = rx;
            uint32_t cy = ry;
            bool under_local = false;
            while (!(cx == ingress_lx && cy == ingress_ly)) {
                uint32_t px = 0, py = 0;
                parentOf(x_first, cx, cy, px, py);
                if (px == cx && py == cy) break;
                if (px == local_x && py == local_y) {
                    under_local = true;
                    break;
                }
                cx = px;
                cy = py;
            }
            if (!under_local) continue;

            local_units_sum += localDeliveryUnits(ws.core_mask[idx]);

            uint32_t ex = rx;
            uint32_t ey = ry;
            while (!(ex == local_x && ey == local_y)) {
                uint32_t px = 0, py = 0;
                parentOf(x_first, ex, ey, px, py);
                if (px == ex && py == ey) break;
                const uint32_t parent_idx = py * block_w + px;
                const uint32_t child_idx = ey * block_w + ex;
                addEdge(parent_idx, child_idx);
                ex = px;
                ey = py;
            }
        }

        pred_bytes_out = payload_bytes * (local_units_sum + static_cast<uint64_t>(edge_keys.size()));
    };

    std::array<bool, 4> child_used{};
    if (multicast_intra_policy_ == IntraBlockTreePolicy::Adaptive) {
        std::array<bool, 4> child_used_x{};
        std::array<bool, 4> child_used_y{};
        uint64_t pred_bytes_x = 0;
        uint64_t pred_bytes_y = 0;
        uint64_t queue_cost_x = 0;
        uint64_t queue_cost_y = 0;
        buildIntraEstimate(/*x_first=*/true, child_used_x, pred_bytes_x, queue_cost_x);
        buildIntraEstimate(/*x_first=*/false, child_used_y, pred_bytes_y, queue_cost_y);
        const uint64_t cost_x = adaptive_intra_w_bytes_ * pred_bytes_x + adaptive_intra_w_queue_ * queue_cost_x;
        const uint64_t cost_y = adaptive_intra_w_bytes_ * pred_bytes_y + adaptive_intra_w_queue_ * queue_cost_y;
        if (cost_x < cost_y) {
            child_used = child_used_x;
        } else if (cost_y < cost_x) {
            child_used = child_used_y;
        } else {
            const uint64_t h = ws.group_id ^ static_cast<uint64_t>(ws.pre_global) ^ static_cast<uint64_t>(ws.block_id);
            child_used = ((h & 1ull) != 0ull) ? child_used_y : child_used_x;
        }

        if (adaptive_telemetry_enable_) {
            adaptive_intra_decisions_total_ += 1;
            adaptive_intra_cost_x_total_ += cost_x;
            adaptive_intra_cost_y_total_ += cost_y;
            const uint64_t cost_delta_abs = (cost_x > cost_y) ? (cost_x - cost_y) : (cost_y - cost_x);
            adaptive_intra_cost_delta_abs_total_ += cost_delta_abs;
            adaptive_intra_pred_bytes_x_total_ += pred_bytes_x;
            adaptive_intra_pred_bytes_y_total_ += pred_bytes_y;
            adaptive_intra_queue_x_total_ += queue_cost_x;
            adaptive_intra_queue_y_total_ += queue_cost_y;
            const bool choose_x = (child_used == child_used_x);
            if (choose_x) {
                adaptive_intra_choose_x_total_ += 1;
                adaptive_intra_cost_chosen_total_ += cost_x;
                adaptive_intra_pred_bytes_chosen_total_ += pred_bytes_x;
                adaptive_intra_queue_chosen_total_ += queue_cost_x;
            } else {
                adaptive_intra_choose_y_total_ += 1;
                adaptive_intra_cost_chosen_total_ += cost_y;
                adaptive_intra_pred_bytes_chosen_total_ += pred_bytes_y;
                adaptive_intra_queue_chosen_total_ += queue_cost_y;
            }
            const uint64_t pred_delta_abs =
                (pred_bytes_x > pred_bytes_y) ? (pred_bytes_x - pred_bytes_y) : (pred_bytes_y - pred_bytes_x);
            adaptive_intra_pred_bytes_delta_abs_total_ += pred_delta_abs;
            if (cost_x == cost_y) adaptive_intra_tie_total_ += 1;
        }
    } else {
        const bool x_first = (multicast_intra_policy_ == IntraBlockTreePolicy::ManhattanXFirst);
        buildChildUse(x_first, child_used);
    }

    // Forward to tree children if their subtree contains at least one recipient.
    if (child_used[0]) {
        auto* c = static_cast<NocPacketEvent*>(pkt->clone());
        spikekey_clones_total_ += 1;
        sendToEast_(c);
    }
    if (child_used[1]) {
        auto* c = static_cast<NocPacketEvent*>(pkt->clone());
        spikekey_clones_total_ += 1;
        sendToWest_(c);
    }
    if (child_used[2]) {
        auto* c = static_cast<NocPacketEvent*>(pkt->clone());
        spikekey_clones_total_ += 1;
        sendToSouth_(c);
    }
    if (child_used[3]) {
        auto* c = static_cast<NocPacketEvent*>(pkt->clone());
        spikekey_clones_total_ += 1;
        sendToNorth_(c);
    }

    deliverLocalMask(ws.core_mask[idx_self]);
    delete pkt;
}

void MulticastRouter::routeSpikeInterBundle_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (mesh_w_ == 0 || mesh_h_ == 0) {
        delete pkt;
        return;
    }

    constexpr uint16_t kStageInter = 0;
    constexpr uint16_t kStageIntra = 1;
    uint32_t self_x = 0, self_y = 0, self_z = 0;
    if (!nodeIdToCoord2DLayered_(node_id_, mesh_w_, mesh_h_, mesh_z_, self_x, self_y, self_z)) {
        delete pkt;
        return;
    }
    auto pick_inter_dir = [&](uint32_t ingress_node,
                              uint64_t group_id,
                              uint32_t pre_global,
                              uint32_t block_id,
                              uint64_t payload_bytes) -> uint8_t {
        uint32_t dest_x = 0, dest_y = 0, dest_z = 0;
        if (!nodeIdToCoord2DLayered_(ingress_node, mesh_w_, mesh_h_, mesh_z_, dest_x, dest_y, dest_z)) {
            return 0xffu;
        }
        if (dest_z != self_z) {
            // layered-2d router cannot forward across z; each die remains an independent 2D plane.
            return 0xffu;
        }
        if (dest_x == self_x && dest_y == self_y) return 0;

        auto estimateInterDirCost = [&](uint8_t dir, uint64_t len_bias) -> uint64_t {
            uint32_t port_idx = 0;
            if (dir == 1) port_idx = 1;      // north
            else if (dir == 2) port_idx = 2; // south
            else if (dir == 3) port_idx = 3; // east
            else if (dir == 4) port_idx = 4; // west
            else return 0;
            uint64_t wait = 0;
            uint64_t service_cycles = 1;
            if (serialize_output_enable_) {
                const uint64_t now = static_cast<uint64_t>(getCurrentSimTime(timebase_));
                const uint64_t next_free = port_next_free_cycle_[port_idx];
                wait = (next_free > now) ? (next_free - now) : 0;
                service_cycles = serialize_service_cycles_;
                if (serialize_output_byte_enable_) {
                    const uint64_t total_bytes = serialize_header_bytes_ + payload_bytes;
                    service_cycles = (total_bytes + serialize_bytes_per_cycle_ - 1ull) / serialize_bytes_per_cycle_;
                    if (service_cycles == 0) service_cycles = 1;
                }
            }
            return adaptive_inter_w_wait_ * wait + adaptive_inter_w_service_ * service_cycles
                   + adaptive_inter_w_len_ * len_bias;
        };

        if (multicast_inter_policy_ == InterBlockRoutePolicy::AdaptiveXYYX) {
            const uint8_t dir_x = (self_x < dest_x) ? 3u : ((self_x > dest_x) ? 4u : 0u);
            const uint8_t dir_y = (self_y < dest_y) ? 2u : ((self_y > dest_y) ? 1u : 0u);
            if (dir_x != 0u && dir_y != 0u) {
                const uint64_t dx =
                    (self_x > dest_x) ? static_cast<uint64_t>(self_x - dest_x) : static_cast<uint64_t>(dest_x - self_x);
                const uint64_t dy =
                    (self_y > dest_y) ? static_cast<uint64_t>(self_y - dest_y) : static_cast<uint64_t>(dest_y - self_y);
                const uint64_t cost_x = estimateInterDirCost(dir_x, dy);
                const uint64_t cost_y = estimateInterDirCost(dir_y, dx);
                uint8_t chosen = dir_x;
                if (cost_x < cost_y) {
                    chosen = dir_x;
                } else if (cost_y < cost_x) {
                    chosen = dir_y;
                } else {
                    const uint64_t h = group_id ^ static_cast<uint64_t>(pre_global) ^ static_cast<uint64_t>(block_id);
                    chosen = ((h & 1ull) != 0ull) ? dir_y : dir_x;
                }

                if (adaptive_telemetry_enable_) {
                    adaptive_inter_decisions_total_ += 1;
                    adaptive_inter_cost_x_total_ += cost_x;
                    adaptive_inter_cost_y_total_ += cost_y;
                    const uint64_t delta_abs = (cost_x > cost_y) ? (cost_x - cost_y) : (cost_y - cost_x);
                    adaptive_inter_cost_delta_abs_total_ += delta_abs;
                    if (cost_x == cost_y) adaptive_inter_tie_total_ += 1;
                    if (chosen == dir_x) adaptive_inter_choose_x_total_ += 1;
                    else adaptive_inter_choose_y_total_ += 1;
                    const uint64_t chosen_cost = (chosen == dir_x) ? cost_x : cost_y;
                    adaptive_inter_cost_chosen_total_ += chosen_cost;
                }
                return chosen;
            }
            return (dir_x != 0u) ? dir_x : dir_y;
        }

        bool use_yx = false;
        if (multicast_inter_policy_ == InterBlockRoutePolicy::YX) {
            use_yx = true;
        } else if (multicast_inter_policy_ == InterBlockRoutePolicy::HashXY) {
            const uint64_t h = group_id ^ static_cast<uint64_t>(pre_global) ^ static_cast<uint64_t>(block_id);
            use_yx = ((h & 1ull) != 0ull);
        }

        if (use_yx) {
            if (self_y < dest_y) return 2;
            if (self_y > dest_y) return 1;
            if (self_x < dest_x) return 3;
            if (self_x > dest_x) return 4;
            return 0;
        }
        if (self_x < dest_x) return 3;
        if (self_x > dest_x) return 4;
        if (self_y < dest_y) return 2;
        if (self_y > dest_y) return 1;
        return 0;
    };

    uint16_t bundle_version = 0;
    if (!SpikeInterBundleCodec::decodeVersion(pkt->payload, bundle_version)) {
        delete pkt;
        return;
    }

    if (bundle_version == SpikeInterBundleCodec::kVersionV1) {
        SpikeInterBundleCodec::WireBundlePrefixV1 prefix{};
        std::vector<std::vector<uint8_t>> entries;
        if (!SpikeInterBundleCodec::decode(pkt->payload, prefix, entries) || entries.empty()) {
            delete pkt;
            return;
        }
        spikekey_stage_inter_ += static_cast<uint64_t>(entries.size());

        std::vector<std::vector<uint8_t>> local_entries;
        std::vector<std::vector<uint8_t>> north_entries;
        std::vector<std::vector<uint8_t>> south_entries;
        std::vector<std::vector<uint8_t>> east_entries;
        std::vector<std::vector<uint8_t>> west_entries;
        local_entries.reserve(entries.size());
        north_entries.reserve(entries.size());
        south_entries.reserve(entries.size());
        east_entries.reserve(entries.size());
        west_entries.reserve(entries.size());

        for (auto& entry_payload : entries) {
            SpikeNocCodec::WireSpikeKeyV2 ws{};
            if (!SpikeNocCodec::decodeSpikeKeyAny(entry_payload, ws)) continue;
            if (ws.version != 1 && ws.version != 2 && ws.version != 3) continue;
            if (ws.stage != kStageInter) continue;

            const uint8_t dir = pick_inter_dir(
                ws.ingress_node,
                ws.group_id,
                ws.pre_global,
                ws.block_id,
                static_cast<uint64_t>(entry_payload.size()));
            if (dir == 0) {
                local_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 1) {
                north_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 2) {
                south_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 3) {
                east_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 4) {
                west_entries.emplace_back(std::move(entry_payload));
            }
        }

        for (auto& local_payload : local_entries) {
            if (!SpikeNocCodec::patchStageInPayload(local_payload, kStageIntra)) continue;
            auto* sub_pkt = static_cast<NocPacketEvent*>(pkt->clone());
            sub_pkt->dst_node = node_id_;
            sub_pkt->payload = std::move(local_payload);
            routeSpikeKey_(sub_pkt);
        }

        auto emit_bundle_v1 = [&](std::vector<std::vector<uint8_t>>& grouped_entries,
                                  uint64_t salt,
                                  uint8_t dir) {
            if (grouped_entries.empty()) return;
            auto* out_pkt = static_cast<NocPacketEvent*>(pkt->clone());
            if (!SpikeInterBundleCodec::encode(
                    prefix.packet_kind,
                    prefix.bundle_id ^ salt,
                    grouped_entries,
                    out_pkt->payload)) {
                delete out_pkt;
                return;
            }
            spikekey_clones_total_ += 1;
            if (dir == 1) {
                sendToNorth_(out_pkt);
            } else if (dir == 2) {
                sendToSouth_(out_pkt);
            } else if (dir == 3) {
                sendToEast_(out_pkt);
            } else if (dir == 4) {
                sendToWest_(out_pkt);
            } else {
                delete out_pkt;
            }
        };

        emit_bundle_v1(north_entries, 0x11ull, 1);
        emit_bundle_v1(south_entries, 0x22ull, 2);
        emit_bundle_v1(east_entries, 0x33ull, 3);
        emit_bundle_v1(west_entries, 0x44ull, 4);
        delete pkt;
        return;
    }

    if (bundle_version == SpikeInterBundleCodec::kVersionV2) {
        SpikeInterBundleCodec::WireBundlePrefixV2 prefix{};
        std::vector<SpikeInterBundleCodec::BundleEntryV2> entries;
        if (!SpikeInterBundleCodec::decodeV2(pkt->payload, prefix, entries) || entries.empty()) {
            delete pkt;
            return;
        }
        if (prefix.stage == kStageInter) {
            spikekey_stage_inter_ += static_cast<uint64_t>(entries.size());
        }
        const uint32_t v2_block_cells = SpikeInterBundleCodec::blockCellsFromBlockWH(prefix.block_w_h);
        const uint64_t v2_entry_payload_bytes =
            sizeof(SpikeInterBundleCodec::WireEntryMetaV2) +
            static_cast<uint64_t>(v2_block_cells) * sizeof(uint32_t);

        std::vector<SpikeInterBundleCodec::BundleEntryV2> local_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> north_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> south_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> east_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> west_entries;
        local_entries.reserve(entries.size());
        north_entries.reserve(entries.size());
        south_entries.reserve(entries.size());
        east_entries.reserve(entries.size());
        west_entries.reserve(entries.size());

        for (auto& entry : entries) {
            if (prefix.stage != kStageInter) {
                local_entries.emplace_back(std::move(entry));
                continue;
            }
            const uint8_t dir =
                pick_inter_dir(
                    entry.meta.ingress_node,
                    entry.meta.group_id,
                    entry.meta.pre_global,
                    entry.meta.block_id,
                    v2_entry_payload_bytes);
            if (dir == 0) {
                local_entries.emplace_back(std::move(entry));
            } else if (dir == 1) {
                north_entries.emplace_back(std::move(entry));
            } else if (dir == 2) {
                south_entries.emplace_back(std::move(entry));
            } else if (dir == 3) {
                east_entries.emplace_back(std::move(entry));
            } else if (dir == 4) {
                west_entries.emplace_back(std::move(entry));
            }
        }

        auto build_local_payload = [&](const SpikeInterBundleCodec::BundleEntryV2& entry, std::vector<uint8_t>& out_payload) -> bool {
            SpikeNocCodec::WireSpikeKeyV2 ws{};
            ws.version = 2;
            ws.route_mode = prefix.route_mode;
            ws.stage = (prefix.stage == kStageInter) ? kStageIntra : prefix.stage;
            ws.block_w_h = prefix.block_w_h;
            ws.block_id = entry.meta.block_id;
            ws.ingress_node = entry.meta.ingress_node;
            ws.pre_global = entry.meta.pre_global;
            ws.group_id = entry.meta.group_id;
            ws.core_mask = entry.core_mask;

            if (prefix.packet_kind == static_cast<uint16_t>(NocPacketKind::SpikeKey)) {
                if ((entry.meta.reserved0 & SpikeInterBundleCodec::kEntryFlagCompactRouteV3) != 0u &&
                    SpikeNocCodec::encodeSpikeKeyCompactV3(ws, out_payload)) {
                    return true;
                }
                SpikeNocCodec::encodeSpikeKey(ws, out_payload);
                return true;
            }
            if (prefix.packet_kind == static_cast<uint16_t>(NocPacketKind::SpikeTileKey)) {
                const uint16_t tile_version =
                    (entry.meta.tile_version == SpikeTileNocCodec::kTileVersionV2)
                        ? static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV2)
                        : static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV1);
                if (tile_version == SpikeTileNocCodec::kTileVersionV2 &&
                    SpikeTileNocCodec::encodeCompactV2(
                        ws,
                        entry.meta.tile_block_col,
                        entry.meta.tile_pre_mask,
                        out_payload)) {
                    return true;
                }
                SpikeTileNocCodec::WireSpikeTileKeyV1 wt{};
                wt.route = ws;
                wt.tile.tile_version = tile_version;
                wt.tile.block_col = entry.meta.tile_block_col;
                wt.tile.pre_mask = entry.meta.tile_pre_mask;
                SpikeTileNocCodec::encode(wt, out_payload);
                return true;
            }
            return false;
        };

        for (const auto& local_entry : local_entries) {
            std::vector<uint8_t> local_payload;
            if (!build_local_payload(local_entry, local_payload)) continue;
            auto* sub_pkt = static_cast<NocPacketEvent*>(pkt->clone());
            sub_pkt->dst_node = node_id_;
            sub_pkt->kind = prefix.packet_kind;
            sub_pkt->payload = std::move(local_payload);
            routeSpikeKey_(sub_pkt);
        }

        auto emit_bundle_v2 = [&](std::vector<SpikeInterBundleCodec::BundleEntryV2>& grouped_entries,
                                  uint64_t salt,
                                  uint8_t dir) {
            if (grouped_entries.empty()) return;
            auto* out_pkt = static_cast<NocPacketEvent*>(pkt->clone());
            out_pkt->kind = prefix.packet_kind;
            if (!SpikeInterBundleCodec::encodeV2(
                    prefix.packet_kind,
                    prefix.route_mode,
                    prefix.stage,
                    prefix.block_w_h,
                    prefix.bundle_id ^ salt,
                    grouped_entries,
                    out_pkt->payload)) {
                delete out_pkt;
                return;
            }
            spikekey_clones_total_ += 1;
            if (dir == 1) {
                sendToNorth_(out_pkt);
            } else if (dir == 2) {
                sendToSouth_(out_pkt);
            } else if (dir == 3) {
                sendToEast_(out_pkt);
            } else if (dir == 4) {
                sendToWest_(out_pkt);
            } else {
                delete out_pkt;
            }
        };

        emit_bundle_v2(north_entries, 0x11ull, 1);
        emit_bundle_v2(south_entries, 0x22ull, 2);
        emit_bundle_v2(east_entries, 0x33ull, 3);
        emit_bundle_v2(west_entries, 0x44ull, 4);
        delete pkt;
        return;
    }

    delete pkt;
}

void MulticastRouter::sendToLocal_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!local_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_to_local_ += 1;
    sendOnPort_(local_link_, 0, pkt);
}

void MulticastRouter::sendToNorth_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!north_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_xy_ += 1;
    sendOnPort_(north_link_, 1, pkt);
}

void MulticastRouter::sendToSouth_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!south_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_xy_ += 1;
    sendOnPort_(south_link_, 2, pkt);
}

void MulticastRouter::sendToEast_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!east_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_xy_ += 1;
    sendOnPort_(east_link_, 3, pkt);
}

void MulticastRouter::sendToWest_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!west_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_xy_ += 1;
    sendOnPort_(west_link_, 4, pkt);
}

void MulticastRouter::sendOnPort_(SST::Link* link, uint32_t port_idx, NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!link) { delete pkt; return; }
    const uint64_t pkt_bytes = packetBytes_(pkt);
    bytes_out_total_ += pkt_bytes;
    byte_hops_total_ += pkt_bytes;
    if (port_idx == 0u) {
        bytes_to_local_ += pkt_bytes;
    } else {
        bytes_forward_xy_ += pkt_bytes;
    }
    if (!serialize_output_enable_) {
        link->send(router_latency_cycles_, timebase_, pkt);
        return;
    }
    if (port_idx >= port_next_free_cycle_.size()) {
        link->send(router_latency_cycles_, timebase_, pkt);
        return;
    }

    const uint64_t now = static_cast<uint64_t>(getCurrentSimTime(timebase_));
    const uint64_t next_free = port_next_free_cycle_[port_idx];
    const uint64_t start = (next_free > now) ? next_free : now;
    const uint64_t wait = start - now;
    const uint64_t delay = wait + router_latency_cycles_;
    link->send(delay, timebase_, pkt);

    uint64_t service_cycles = serialize_service_cycles_;
    if (serialize_output_byte_enable_) {
        const uint64_t total_bytes = serialize_header_bytes_ + static_cast<uint64_t>(pkt->payload.size());
        service_cycles = (total_bytes + serialize_bytes_per_cycle_ - 1ull) / serialize_bytes_per_cycle_;
        if (service_cycles == 0) service_cycles = 1;
    }
    port_next_free_cycle_[port_idx] = start + service_cycles;
}

uint64_t MulticastRouter::packetBytes_(const NocPacketEvent* pkt) const {
    if (!pkt) return 0;
    return serialize_header_bytes_ + static_cast<uint64_t>(pkt->payload.size());
}

bool MulticastRouter::parseMeshShape_(const std::string& shape, uint32_t& out_w, uint32_t& out_h, uint32_t& out_z) {
    out_w = 0;
    out_h = 0;
    out_z = 1;
    if (shape.empty()) return false;

    const std::string s = toLowerCopy(shape);

    const auto pos0 = s.find('x');
    if (pos0 == std::string::npos) return false;
    const auto pos1 = s.find('x', pos0 + 1);
    const std::string a = s.substr(0, pos0);
    const std::string b = (pos1 == std::string::npos) ? s.substr(pos0 + 1) : s.substr(pos0 + 1, pos1 - pos0 - 1);
    const std::string c = (pos1 == std::string::npos) ? "1" : s.substr(pos1 + 1);
    if (a.empty() || b.empty() || c.empty()) return false;

    char* endp = nullptr;
    const long w = std::strtol(a.c_str(), &endp, 10);
    if (!endp || *endp != '\0' || w <= 0) return false;
    endp = nullptr;
    const long h = std::strtol(b.c_str(), &endp, 10);
    if (!endp || *endp != '\0' || h <= 0) return false;
    endp = nullptr;
    const long z = std::strtol(c.c_str(), &endp, 10);
    if (!endp || *endp != '\0' || z <= 0) return false;

    out_w = static_cast<uint32_t>(w);
    out_h = static_cast<uint32_t>(h);
    out_z = static_cast<uint32_t>(z);
    return true;
}

bool MulticastRouter::nodeIdToCoord2DLayered_(uint32_t node_id,
                                              uint32_t mesh_w,
                                              uint32_t mesh_h,
                                              uint32_t mesh_z,
                                              uint32_t& out_x,
                                              uint32_t& out_y,
                                              uint32_t& out_z) {
    out_x = 0;
    out_y = 0;
    out_z = 0;
    if (mesh_w == 0 || mesh_h == 0 || mesh_z == 0) return false;
    const uint64_t layer_nodes = static_cast<uint64_t>(mesh_w) * static_cast<uint64_t>(mesh_h);
    const uint64_t total_nodes = layer_nodes * static_cast<uint64_t>(mesh_z);
    if (layer_nodes == 0 || static_cast<uint64_t>(node_id) >= total_nodes) return false;
    out_x = node_id % mesh_w;
    const uint32_t yz = node_id / mesh_w;
    out_y = yz % mesh_h;
    out_z = yz / mesh_h;
    return true;
}

bool MulticastRouter::parseInterPolicy_(const std::string& s, InterBlockRoutePolicy& out) {
    const std::string v = toLowerCopy(s);
    if (v == "xy") { out = InterBlockRoutePolicy::XY; return true; }
    if (v == "yx") { out = InterBlockRoutePolicy::YX; return true; }
    if (v == "hash_xy" || v == "hashxy") { out = InterBlockRoutePolicy::HashXY; return true; }
    if (v == "adaptive_xy_yx" || v == "adaptive_xyyx" || v == "adaptive") {
        out = InterBlockRoutePolicy::AdaptiveXYYX;
        return true;
    }
    return false;
}

bool MulticastRouter::parseIntraPolicy_(const std::string& s, IntraBlockTreePolicy& out) {
    const std::string v = toLowerCopy(s);
    if (v == "manhattan_x_first" || v == "x_first" || v == "xfirst") { out = IntraBlockTreePolicy::ManhattanXFirst; return true; }
    if (v == "manhattan_y_first" || v == "y_first" || v == "yfirst") { out = IntraBlockTreePolicy::ManhattanYFirst; return true; }
    if (v == "adaptive" || v == "adaptive_tree") {
        out = IntraBlockTreePolicy::Adaptive;
        return true;
    }
    return false;
}

}} // namespace SST::SnnDL
