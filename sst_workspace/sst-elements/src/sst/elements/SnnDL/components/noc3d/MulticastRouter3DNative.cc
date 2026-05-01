// -*- c++ -*-

#include "MulticastRouter3DNative.h"

#include <algorithm>
#include <cctype>
#include <inttypes.h>
#include <vector>

#include <sst/core/event.h>
#include <sst/core/params.h>

#include "MulticastRouter3DNativeConfig.h"
#include "NocPacketEvent.h"
#include "services/synapse/route/SpikeInterBundleCodec.h"
#include "services/synapse/route/SpikeNocCodec.h"
#include "services/synapse/route/SpikeTileNocCodec.h"
#include "services/synapse/route3d/Route3DNodeMapper.h"

namespace SST { namespace SnnDL {

namespace {

inline bool anyMask3D_(const SpikeNocCodec::WireSpikeKeyV2& ws, uint32_t cells) {
    const uint32_t n = std::min<uint32_t>(cells, kMaxMulticastBlockCells);
    for (uint32_t i = 0; i < n; ++i) {
        if (ws.core_mask[i] != 0u) return true;
    }
    return false;
}

inline uint32_t idxOfLocal3D_(uint32_t local_x,
                              uint32_t local_y,
                              uint32_t local_z,
                              uint32_t block_w,
                              uint32_t block_h) {
    return ((local_z * block_h) + local_y) * block_w + local_x;
}

inline void parentOf3D_(bool x_first,
                        uint32_t cx,
                        uint32_t cy,
                        uint32_t cz,
                        uint32_t ingress_lx,
                        uint32_t ingress_ly,
                        uint32_t ingress_lz,
                        uint32_t& out_px,
                        uint32_t& out_py,
                        uint32_t& out_pz) {
    out_px = cx;
    out_py = cy;
    out_pz = cz;
    if (cx == ingress_lx && cy == ingress_ly && cz == ingress_lz) return;

    if (cz != ingress_lz) {
        out_pz = (ingress_lz > cz) ? (cz + 1u) : (cz - 1u);
        return;
    }

    if (x_first) {
        if (cx != ingress_lx) {
            out_px = (ingress_lx > cx) ? (cx + 1u) : (cx - 1u);
            return;
        }
        if (cy != ingress_ly) {
            out_py = (ingress_ly > cy) ? (cy + 1u) : (cy - 1u);
        }
        return;
    }

    if (cy != ingress_ly) {
        out_py = (ingress_ly > cy) ? (cy + 1u) : (cy - 1u);
        return;
    }
    if (cx != ingress_lx) {
        out_px = (ingress_lx > cx) ? (cx + 1u) : (cx - 1u);
    }
}

} // namespace

MulticastRouter3DNative::MulticastRouter3DNative(SST::ComponentId_t id, SST::Params& params)
    : SST::Component(id),
      out_("SnnDL.MulticastRouter3DNative", 0, 0, SST::Output::STDOUT),
      timebase_(getTimeConverter("1ns")) {
    const MulticastRouter3DNativeConfig cfg = parseMulticastRouter3DNativeConfig(params);
    out_.setVerboseLevel(cfg.verbose);

    node_id_ = cfg.node_id;
    router_latency_cycles_ = cfg.router_latency_cycles;
    multicast_block_dim_z_ = (cfg.multicast_block_dim_z > 0) ? cfg.multicast_block_dim_z : 1u;
    multicast_die_local_only_ = cfg.multicast_die_local_only;
    if (!parseMeshShape3D_(cfg.mesh_shape, mesh_shape_)) {
        out_.fatal(CALL_INFO, -1, "Invalid mesh_shape='%s'\n", cfg.mesh_shape.c_str());
    }
    if (!parseVerticalRouteOrder_(cfg.vertical_route_order, vertical_route_order_)) {
        out_.fatal(CALL_INFO, -1, "Invalid vertical_route_order='%s' (supported: zxy, zyx)\n", cfg.vertical_route_order.c_str());
    }

    local_link_ = configureLink("local", new SST::Event::Handler2<MulticastRouter3DNative, &MulticastRouter3DNative::handleLocalLinkEvent>(this));
    north_link_ = configureLink("north", new SST::Event::Handler2<MulticastRouter3DNative, &MulticastRouter3DNative::handleNorthLinkEvent>(this));
    south_link_ = configureLink("south", new SST::Event::Handler2<MulticastRouter3DNative, &MulticastRouter3DNative::handleSouthLinkEvent>(this));
    east_link_ = configureLink("east", new SST::Event::Handler2<MulticastRouter3DNative, &MulticastRouter3DNative::handleEastLinkEvent>(this));
    west_link_ = configureLink("west", new SST::Event::Handler2<MulticastRouter3DNative, &MulticastRouter3DNative::handleWestLinkEvent>(this));
    up_link_ = configureLink("up", new SST::Event::Handler2<MulticastRouter3DNative, &MulticastRouter3DNative::handleUpLinkEvent>(this));
    down_link_ = configureLink("down", new SST::Event::Handler2<MulticastRouter3DNative, &MulticastRouter3DNative::handleDownLinkEvent>(this));
}

MulticastRouter3DNative::~MulticastRouter3DNative() = default;

void MulticastRouter3DNative::init(unsigned int /*phase*/) {}
void MulticastRouter3DNative::setup() {}
void MulticastRouter3DNative::finish() {
    out_.verbose(CALL_INFO, 0, 0,
                 "[mcast-router-3d] node=%u in=%" PRIu64 " out=%" PRIu64 " local=%" PRIu64
                 " fwd_xy=%" PRIu64 " fwd_z=%" PRIu64
                 " bundle_v1_rx=%" PRIu64 " bundle_v2_rx=%" PRIu64 " bundle_v3_rx=%" PRIu64
                 " bundle_v3_invalid_shape=%" PRIu64 " bundle_v3_block_z_mismatch=%" PRIu64
                 " bundle_v3_ingress_out_of_block=%" PRIu64 " bundle_v3_rebuild_fail=%" PRIu64 "\n",
                 node_id_,
                 pkts_in_total_,
                 pkts_out_total_,
                 pkts_to_local_,
                 pkts_forward_xy_total_,
                 pkts_forward_z_total_,
                 bundle_v1_rx_total_,
                 bundle_v2_rx_total_,
                 bundle_v3_rx_total_,
                 bundle_v3_invalid_shape_total_,
                 bundle_v3_block_z_mismatch_total_,
                 bundle_v3_ingress_out_of_block_total_,
                 bundle_v3_rebuild_fail_total_);
}

void MulticastRouter3DNative::handleLocalLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    routePacket_(pkt);
}

void MulticastRouter3DNative::handleNorthLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    routePacket_(pkt);
}

void MulticastRouter3DNative::handleSouthLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    routePacket_(pkt);
}

void MulticastRouter3DNative::handleEastLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    routePacket_(pkt);
}

void MulticastRouter3DNative::handleWestLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    routePacket_(pkt);
}

void MulticastRouter3DNative::handleUpLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    routePacket_(pkt);
}

void MulticastRouter3DNative::handleDownLinkEvent(SST::Event* event) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(event);
    if (!pkt) { delete event; return; }
    routePacket_(pkt);
}

void MulticastRouter3DNative::routePacket_(NocPacketEvent* pkt) {
    if (!pkt) return;
    pkt->hop_count += 1;
    pkts_in_total_ += 1;

    if (pkt->packetKind() == NocPacketKind::SpikeKey || pkt->packetKind() == NocPacketKind::SpikeTileKey) {
        routeSpikeKey_(pkt);
        return;
    }

    routeUnicast3D_(pkt, pkt->dst_node);
}

void MulticastRouter3DNative::routeUnicast3D_(NocPacketEvent* pkt, uint32_t dest_node) {
    if (!pkt) return;
    if (dest_node == node_id_) {
        sendToLocal_(pkt);
        return;
    }

    MeshCoord3D self{};
    MeshCoord3D dest{};
    if (!nodeIdToCoord3D(mesh_shape_, node_id_, self) || !nodeIdToCoord3D(mesh_shape_, dest_node, dest)) {
        delete pkt;
        return;
    }

    if (self.z < dest.z) {
        sendToUp_(pkt);
        return;
    }
    if (self.z > dest.z) {
        sendToDown_(pkt);
        return;
    }

    if (vertical_route_order_ == VerticalRouteOrder::ZYX) {
        if (self.y < dest.y) { sendToSouth_(pkt); return; }
        if (self.y > dest.y) { sendToNorth_(pkt); return; }
        if (self.x < dest.x) { sendToEast_(pkt); return; }
        if (self.x > dest.x) { sendToWest_(pkt); return; }
    } else {
        if (self.x < dest.x) { sendToEast_(pkt); return; }
        if (self.x > dest.x) { sendToWest_(pkt); return; }
        if (self.y < dest.y) { sendToSouth_(pkt); return; }
        if (self.y > dest.y) { sendToNorth_(pkt); return; }
    }

    sendToLocal_(pkt);
}

void MulticastRouter3DNative::routeSpikeKey_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (SpikeInterBundleCodec::isBundlePayload(pkt->payload)) {
        routeSpikeInterBundle_(pkt);
        return;
    }

    SpikeNocCodec::WireSpikeKeyV2 ws{};
    SpikeNocCodec::DecodedSpikeKeyMeta decoded_meta{};
    if (!SpikeNocCodec::decodeSpikeKeyAny(pkt->payload, ws, &decoded_meta)) {
        delete pkt;
        return;
    }

    constexpr uint16_t kStageInter = 0;
    constexpr uint16_t kStageIntra = 1;
    const uint32_t block_w = decoded_meta.block_w;
    const uint32_t block_h = decoded_meta.block_h;
    const uint32_t block_d = decoded_meta.block_d;
    const uint64_t block_cells64 =
        static_cast<uint64_t>(block_w) * static_cast<uint64_t>(block_h) * static_cast<uint64_t>(block_d);
    if (block_w == 0 || block_h == 0 || block_d == 0 ||
        block_cells64 == 0 || block_cells64 > static_cast<uint64_t>(kMaxMulticastBlockCells)) {
        delete pkt;
        return;
    }
    const uint32_t block_cells = static_cast<uint32_t>(block_cells64);
    if (!anyMask3D_(ws, block_cells)) {
        delete pkt;
        return;
    }

    if (ws.stage == kStageInter) {
        if (node_id_ == ws.ingress_node) {
            if (!SpikeNocCodec::patchStageInPayload(pkt->payload, kStageIntra)) {
                delete pkt;
                return;
            }
            ws.stage = kStageIntra;
        } else {
            pkt->dst_node = ws.ingress_node;
            routeUnicast3D_(pkt, ws.ingress_node);
            return;
        }
    }

    if (ws.stage != kStageIntra) {
        delete pkt;
        return;
    }

    uint32_t block_x0 = 0;
    uint32_t block_y0 = 0;
    uint32_t block_z0 = 0;
    if (!decodeBlockId3DVolumetric(mesh_shape_, block_w, block_h, block_d, ws.block_id, block_x0, block_y0, block_z0)) {
        delete pkt;
        return;
    }

    MeshCoord3D self{};
    MeshCoord3D ingress{};
    if (!nodeIdToCoord3D(mesh_shape_, node_id_, self) || !nodeIdToCoord3D(mesh_shape_, ws.ingress_node, ingress)) {
        delete pkt;
        return;
    }
    if (self.x < block_x0 || self.y < block_y0 || self.z < block_z0 ||
        self.x >= block_x0 + block_w || self.y >= block_y0 + block_h || self.z >= block_z0 + block_d) {
        delete pkt;
        return;
    }
    if (ingress.x < block_x0 || ingress.y < block_y0 || ingress.z < block_z0 ||
        ingress.x >= block_x0 + block_w || ingress.y >= block_y0 + block_h || ingress.z >= block_z0 + block_d) {
        delete pkt;
        return;
    }

    const uint32_t local_x = self.x - block_x0;
    const uint32_t local_y = self.y - block_y0;
    const uint32_t local_z = self.z - block_z0;
    const uint32_t ingress_lx = ingress.x - block_x0;
    const uint32_t ingress_ly = ingress.y - block_y0;
    const uint32_t ingress_lz = ingress.z - block_z0;
    const uint32_t idx_self = idxOfLocal3D_(local_x, local_y, local_z, block_w, block_h);
    if (idx_self >= block_cells || idx_self >= kMaxMulticastBlockCells) {
        delete pkt;
        return;
    }

    auto deliverLocalMask = [&](uint32_t core_mask) {
        for (uint32_t bit = 0; bit < 32u; ++bit) {
            if ((core_mask & (1u << bit)) == 0u) continue;
            auto* clone = static_cast<NocPacketEvent*>(pkt->clone());
            clone->dst_node = node_id_;
            clone->dst_endpoint = static_cast<uint16_t>(bit);
            sendToLocal_(clone);
        }
    };

    auto parentOf = [&](bool x_first,
                        uint32_t cx,
                        uint32_t cy,
                        uint32_t cz,
                        uint32_t& out_px,
                        uint32_t& out_py,
                        uint32_t& out_pz) {
        parentOf3D_(x_first, cx, cy, cz, ingress_lx, ingress_ly, ingress_lz, out_px, out_py, out_pz);
    };

    auto isChild = [&](uint32_t child_x, uint32_t child_y, uint32_t child_z, bool x_first) -> bool {
        if (child_x >= block_w || child_y >= block_h || child_z >= block_d) return false;
        uint32_t px = 0;
        uint32_t py = 0;
        uint32_t pz = 0;
        parentOf(x_first, child_x, child_y, child_z, px, py, pz);
        return px == local_x && py == local_y && pz == local_z;
    };

    auto subtreeHasAny = [&](uint32_t child_x, uint32_t child_y, uint32_t child_z, bool x_first) -> bool {
        if (!isChild(child_x, child_y, child_z, x_first)) return false;
        for (uint32_t idx = 0; idx < block_cells && idx < kMaxMulticastBlockCells; ++idx) {
            if (ws.core_mask[idx] == 0u) continue;
            const uint32_t cx0 = idx % block_w;
            const uint32_t yz0 = idx / block_w;
            const uint32_t cy0 = yz0 % block_h;
            const uint32_t cz0 = yz0 / block_h;
            if (cx0 == local_x && cy0 == local_y && cz0 == local_z) continue;

            uint32_t cx = cx0;
            uint32_t cy = cy0;
            uint32_t cz = cz0;
            while (!(cx == ingress_lx && cy == ingress_ly && cz == ingress_lz) &&
                   !(cx == local_x && cy == local_y && cz == local_z) &&
                   !(cx == child_x && cy == child_y && cz == child_z)) {
                uint32_t px = 0;
                uint32_t py = 0;
                uint32_t pz = 0;
                parentOf(x_first, cx, cy, cz, px, py, pz);
                if (px == cx && py == cy && pz == cz) break;
                cx = px;
                cy = py;
                cz = pz;
            }
            if (cx == child_x && cy == child_y && cz == child_z) return true;
        }
        return false;
    };

    const bool x_first = (vertical_route_order_ == VerticalRouteOrder::ZXY);
    const bool east = (local_x + 1u < block_w) && subtreeHasAny(local_x + 1u, local_y, local_z, x_first);
    const bool west = (local_x > 0u) && subtreeHasAny(local_x - 1u, local_y, local_z, x_first);
    const bool south = (local_y + 1u < block_h) && subtreeHasAny(local_x, local_y + 1u, local_z, x_first);
    const bool north = (local_y > 0u) && subtreeHasAny(local_x, local_y - 1u, local_z, x_first);
    const bool up = (local_z + 1u < block_d) && subtreeHasAny(local_x, local_y, local_z + 1u, x_first);
    const bool down = (local_z > 0u) && subtreeHasAny(local_x, local_y, local_z - 1u, x_first);

    if (east) {
        auto* clone = static_cast<NocPacketEvent*>(pkt->clone());
        sendToEast_(clone);
    }
    if (west) {
        auto* clone = static_cast<NocPacketEvent*>(pkt->clone());
        sendToWest_(clone);
    }
    if (south) {
        auto* clone = static_cast<NocPacketEvent*>(pkt->clone());
        sendToSouth_(clone);
    }
    if (north) {
        auto* clone = static_cast<NocPacketEvent*>(pkt->clone());
        sendToNorth_(clone);
    }
    if (up) {
        auto* clone = static_cast<NocPacketEvent*>(pkt->clone());
        sendToUp_(clone);
    }
    if (down) {
        auto* clone = static_cast<NocPacketEvent*>(pkt->clone());
        sendToDown_(clone);
    }

    deliverLocalMask(ws.core_mask[idx_self]);
    delete pkt;
}

void MulticastRouter3DNative::routeSpikeInterBundle_(NocPacketEvent* pkt) {
    if (!pkt) return;

    constexpr uint16_t kStageInter = 0;
    constexpr uint16_t kStageIntra = 1;

    MeshCoord3D self{};
    if (!nodeIdToCoord3D(mesh_shape_, node_id_, self)) {
        delete pkt;
        return;
    }

    auto pick_inter_dir = [&](uint32_t ingress_node) -> uint8_t {
        MeshCoord3D dest{};
        if (!nodeIdToCoord3D(mesh_shape_, ingress_node, dest)) {
            return 0xffu;
        }
        if (self.x == dest.x && self.y == dest.y && self.z == dest.z) return 0u;
        if (self.z < dest.z) return 5u;
        if (self.z > dest.z) return 6u;
        if (vertical_route_order_ == VerticalRouteOrder::ZYX) {
            if (self.y < dest.y) return 2u;
            if (self.y > dest.y) return 1u;
            if (self.x < dest.x) return 3u;
            if (self.x > dest.x) return 4u;
            return 0u;
        }
        if (self.x < dest.x) return 3u;
        if (self.x > dest.x) return 4u;
        if (self.y < dest.y) return 2u;
        if (self.y > dest.y) return 1u;
        return 0u;
    };

    auto sendByDir = [&](uint8_t dir, NocPacketEvent* out_pkt) {
        if (!out_pkt) return;
        if (dir == 0u) {
            sendToLocal_(out_pkt);
        } else if (dir == 1u) {
            sendToNorth_(out_pkt);
        } else if (dir == 2u) {
            sendToSouth_(out_pkt);
        } else if (dir == 3u) {
            sendToEast_(out_pkt);
        } else if (dir == 4u) {
            sendToWest_(out_pkt);
        } else if (dir == 5u) {
            sendToUp_(out_pkt);
        } else if (dir == 6u) {
            sendToDown_(out_pkt);
        } else {
            delete out_pkt;
        }
    };

    uint16_t bundle_version = 0;
    if (!SpikeInterBundleCodec::decodeVersion(pkt->payload, bundle_version)) {
        delete pkt;
        return;
    }

    if (bundle_version == SpikeInterBundleCodec::kVersionV1) {
        bundle_v1_rx_total_ += 1;
        SpikeInterBundleCodec::WireBundlePrefixV1 prefix{};
        std::vector<std::vector<uint8_t>> entries;
        if (!SpikeInterBundleCodec::decode(pkt->payload, prefix, entries) || entries.empty()) {
            delete pkt;
            return;
        }

        std::vector<std::vector<uint8_t>> local_entries;
        std::vector<std::vector<uint8_t>> north_entries;
        std::vector<std::vector<uint8_t>> south_entries;
        std::vector<std::vector<uint8_t>> east_entries;
        std::vector<std::vector<uint8_t>> west_entries;
        std::vector<std::vector<uint8_t>> up_entries;
        std::vector<std::vector<uint8_t>> down_entries;

        for (auto& entry_payload : entries) {
            SpikeNocCodec::WireSpikeKeyV2 ws{};
            if (!SpikeNocCodec::decodeSpikeKeyAny(entry_payload, ws)) continue;
            if (ws.version != 1 && ws.version != 2 && ws.version != 3 && ws.version != 4) continue;
            if (ws.stage != kStageInter) continue;

            const uint8_t dir = pick_inter_dir(ws.ingress_node);
            if (dir == 0u) {
                local_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 1u) {
                north_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 2u) {
                south_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 3u) {
                east_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 4u) {
                west_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 5u) {
                up_entries.emplace_back(std::move(entry_payload));
            } else if (dir == 6u) {
                down_entries.emplace_back(std::move(entry_payload));
            }
        }

        for (auto& local_payload : local_entries) {
            if (!SpikeNocCodec::patchStageInPayload(local_payload, kStageIntra)) continue;
            auto* sub_pkt = static_cast<NocPacketEvent*>(pkt->clone());
            sub_pkt->dst_node = node_id_;
            sub_pkt->kind = prefix.packet_kind;
            sub_pkt->payload = std::move(local_payload);
            routeSpikeKey_(sub_pkt);
        }

        auto emit_bundle_v1 = [&](std::vector<std::vector<uint8_t>>& grouped_entries,
                                  uint64_t salt,
                                  uint8_t dir) {
            if (grouped_entries.empty()) return;
            auto* out_pkt = static_cast<NocPacketEvent*>(pkt->clone());
            out_pkt->kind = prefix.packet_kind;
            if (!SpikeInterBundleCodec::encode(
                    prefix.packet_kind,
                    prefix.bundle_id ^ salt,
                    grouped_entries,
                    out_pkt->payload)) {
                delete out_pkt;
                return;
            }
            sendByDir(dir, out_pkt);
        };

        emit_bundle_v1(north_entries, 0x11ull, 1u);
        emit_bundle_v1(south_entries, 0x22ull, 2u);
        emit_bundle_v1(east_entries, 0x33ull, 3u);
        emit_bundle_v1(west_entries, 0x44ull, 4u);
        emit_bundle_v1(up_entries, 0x55ull, 5u);
        emit_bundle_v1(down_entries, 0x66ull, 6u);
        delete pkt;
        return;
    }

    if (bundle_version == SpikeInterBundleCodec::kVersionV2) {
        bundle_v2_rx_total_ += 1;
        SpikeInterBundleCodec::WireBundlePrefixV2 prefix{};
        std::vector<SpikeInterBundleCodec::BundleEntryV2> entries;
        if (!SpikeInterBundleCodec::decodeV2(pkt->payload, prefix, entries) || entries.empty()) {
            delete pkt;
            return;
        }

        std::vector<SpikeInterBundleCodec::BundleEntryV2> local_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> north_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> south_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> east_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> west_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> up_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV2> down_entries;

        for (auto& entry : entries) {
            if (prefix.stage != kStageInter) {
                local_entries.emplace_back(std::move(entry));
                continue;
            }

            const uint8_t dir = pick_inter_dir(entry.meta.ingress_node);
            if (dir == 0u) {
                local_entries.emplace_back(std::move(entry));
            } else if (dir == 1u) {
                north_entries.emplace_back(std::move(entry));
            } else if (dir == 2u) {
                south_entries.emplace_back(std::move(entry));
            } else if (dir == 3u) {
                east_entries.emplace_back(std::move(entry));
            } else if (dir == 4u) {
                west_entries.emplace_back(std::move(entry));
            } else if (dir == 5u) {
                up_entries.emplace_back(std::move(entry));
            } else if (dir == 6u) {
                down_entries.emplace_back(std::move(entry));
            }
        }

        auto build_local_payload =
            [&](const SpikeInterBundleCodec::BundleEntryV2& entry, std::vector<uint8_t>& out_payload) -> bool {
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
            sendByDir(dir, out_pkt);
        };

        emit_bundle_v2(north_entries, 0x11ull, 1u);
        emit_bundle_v2(south_entries, 0x22ull, 2u);
        emit_bundle_v2(east_entries, 0x33ull, 3u);
        emit_bundle_v2(west_entries, 0x44ull, 4u);
        emit_bundle_v2(up_entries, 0x55ull, 5u);
        emit_bundle_v2(down_entries, 0x66ull, 6u);
        delete pkt;
        return;
    }

    if (bundle_version == SpikeInterBundleCodec::kVersionV3) {
        bundle_v3_rx_total_ += 1;
        SpikeInterBundleCodec::WireBundlePrefixV3 prefix{};
        std::vector<SpikeInterBundleCodec::BundleEntryV3> entries;
        if (!SpikeInterBundleCodec::decodeV3(pkt->payload, prefix, entries) || entries.empty()) {
            delete pkt;
            return;
        }

        std::vector<SpikeInterBundleCodec::BundleEntryV3> local_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV3> north_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV3> south_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV3> east_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV3> west_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV3> up_entries;
        std::vector<SpikeInterBundleCodec::BundleEntryV3> down_entries;

        const uint32_t block_cells =
            SpikeInterBundleCodec::blockCellsFromBlockShape(prefix.block_w, prefix.block_h, prefix.block_d);
        auto validate_entry =
            [&](const SpikeInterBundleCodec::BundleEntryV3& entry) -> bool {
            if (block_cells == 0) {
                bundle_v3_invalid_shape_total_ += 1;
                return false;
            }

            uint32_t block_x0 = 0;
            uint32_t block_y0 = 0;
            uint32_t block_z0 = 0;
            if (!decodeBlockId3DVolumetric(
                    mesh_shape_,
                    prefix.block_w,
                    prefix.block_h,
                    prefix.block_d,
                    entry.meta.block_id,
                    block_x0,
                    block_y0,
                    block_z0)) {
                bundle_v3_invalid_shape_total_ += 1;
                return false;
            }
            if (block_z0 != entry.meta.block_z) {
                bundle_v3_block_z_mismatch_total_ += 1;
                return false;
            }

            MeshCoord3D ingress{};
            if (!nodeIdToCoord3D(mesh_shape_, entry.meta.ingress_node, ingress)) {
                bundle_v3_ingress_out_of_block_total_ += 1;
                return false;
            }
            if (ingress.x < block_x0 || ingress.y < block_y0 || ingress.z < block_z0 ||
                ingress.x >= block_x0 + prefix.block_w ||
                ingress.y >= block_y0 + prefix.block_h ||
                ingress.z >= block_z0 + prefix.block_d) {
                bundle_v3_ingress_out_of_block_total_ += 1;
                return false;
            }
            return true;
        };

        for (auto& entry : entries) {
            if (!validate_entry(entry)) {
                continue;
            }
            if (prefix.stage != kStageInter) {
                local_entries.emplace_back(std::move(entry));
                continue;
            }

            const uint8_t dir = pick_inter_dir(entry.meta.ingress_node);
            if (dir == 0u) {
                local_entries.emplace_back(std::move(entry));
            } else if (dir == 1u) {
                north_entries.emplace_back(std::move(entry));
            } else if (dir == 2u) {
                south_entries.emplace_back(std::move(entry));
            } else if (dir == 3u) {
                east_entries.emplace_back(std::move(entry));
            } else if (dir == 4u) {
                west_entries.emplace_back(std::move(entry));
            } else if (dir == 5u) {
                up_entries.emplace_back(std::move(entry));
            } else if (dir == 6u) {
                down_entries.emplace_back(std::move(entry));
            }
        }

        auto build_local_payload =
            [&](const SpikeInterBundleCodec::BundleEntryV3& entry, std::vector<uint8_t>& out_payload) -> bool {
            SpikeNocCodec::WireSpikeKeyV4 ws{};
            ws.version = 4;
            ws.route_mode = prefix.route_mode;
            ws.stage = (prefix.stage == kStageInter) ? kStageIntra : prefix.stage;
            ws.block_w = prefix.block_w;
            ws.block_h = prefix.block_h;
            ws.block_d = prefix.block_d;
            ws.block_id = entry.meta.block_id;
            ws.ingress_node = entry.meta.ingress_node;
            ws.pre_global = entry.meta.pre_global;
            ws.group_id = entry.meta.group_id;
            ws.core_mask = entry.core_mask;

            if (prefix.packet_kind == static_cast<uint16_t>(NocPacketKind::SpikeKey)) {
                SpikeNocCodec::encodeSpikeKey(ws, out_payload);
                return true;
            }
            if (prefix.packet_kind == static_cast<uint16_t>(NocPacketKind::SpikeTileKey)) {
                const uint16_t tile_version =
                    (entry.meta.tile_version == SpikeTileNocCodec::kTileVersionV2)
                        ? static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV2)
                        : static_cast<uint16_t>(SpikeTileNocCodec::kTileVersionV1);
                if (tile_version == SpikeTileNocCodec::kTileVersionV2 &&
                    SpikeTileNocCodec::encodeCompactV4(
                        ws,
                        entry.meta.tile_block_col,
                        entry.meta.tile_pre_mask,
                        out_payload)) {
                    return true;
                }
                SpikeTileNocCodec::WireSpikeTileKeyV2 wt{};
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
            if (!build_local_payload(local_entry, local_payload)) {
                bundle_v3_rebuild_fail_total_ += 1;
                continue;
            }
            auto* sub_pkt = static_cast<NocPacketEvent*>(pkt->clone());
            sub_pkt->dst_node = node_id_;
            sub_pkt->kind = prefix.packet_kind;
            sub_pkt->payload = std::move(local_payload);
            routeSpikeKey_(sub_pkt);
        }

        auto emit_bundle_v3 = [&](std::vector<SpikeInterBundleCodec::BundleEntryV3>& grouped_entries,
                                  uint64_t salt,
                                  uint8_t dir) {
            if (grouped_entries.empty()) return;
            auto* out_pkt = static_cast<NocPacketEvent*>(pkt->clone());
            out_pkt->kind = prefix.packet_kind;
            if (!SpikeInterBundleCodec::encodeV3(
                    prefix.packet_kind,
                    prefix.route_mode,
                    prefix.stage,
                    prefix.block_w,
                    prefix.block_h,
                    prefix.block_d,
                    prefix.bundle_id ^ salt,
                    grouped_entries,
                    out_pkt->payload)) {
                delete out_pkt;
                return;
            }
            sendByDir(dir, out_pkt);
        };

        emit_bundle_v3(north_entries, 0x11ull, 1u);
        emit_bundle_v3(south_entries, 0x22ull, 2u);
        emit_bundle_v3(east_entries, 0x33ull, 3u);
        emit_bundle_v3(west_entries, 0x44ull, 4u);
        emit_bundle_v3(up_entries, 0x55ull, 5u);
        emit_bundle_v3(down_entries, 0x66ull, 6u);
        delete pkt;
        return;
    }

    delete pkt;
}

void MulticastRouter3DNative::sendToLocal_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!local_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_to_local_ += 1;
    local_link_->send(router_latency_cycles_, timebase_, pkt);
}

void MulticastRouter3DNative::sendToNorth_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!north_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_xy_total_ += 1;
    north_link_->send(router_latency_cycles_, timebase_, pkt);
}

void MulticastRouter3DNative::sendToSouth_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!south_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_xy_total_ += 1;
    south_link_->send(router_latency_cycles_, timebase_, pkt);
}

void MulticastRouter3DNative::sendToEast_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!east_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_xy_total_ += 1;
    east_link_->send(router_latency_cycles_, timebase_, pkt);
}

void MulticastRouter3DNative::sendToWest_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!west_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_xy_total_ += 1;
    west_link_->send(router_latency_cycles_, timebase_, pkt);
}

void MulticastRouter3DNative::sendToUp_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!up_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_z_total_ += 1;
    up_link_->send(router_latency_cycles_, timebase_, pkt);
}

void MulticastRouter3DNative::sendToDown_(NocPacketEvent* pkt) {
    if (!pkt) return;
    if (!down_link_) { delete pkt; return; }
    pkts_out_total_ += 1;
    pkts_forward_z_total_ += 1;
    down_link_->send(router_latency_cycles_, timebase_, pkt);
}

bool MulticastRouter3DNative::parseMeshShape3D_(const std::string& shape, MeshShape3D& out_shape) {
    return parseMeshShape3D(shape, out_shape);
}

bool MulticastRouter3DNative::parseVerticalRouteOrder_(const std::string& raw, VerticalRouteOrder& out_order) {
    std::string v = raw;
    for (char& ch : v) {
        ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    if (v == "zxy") {
        out_order = VerticalRouteOrder::ZXY;
        return true;
    }
    if (v == "zyx") {
        out_order = VerticalRouteOrder::ZYX;
        return true;
    }
    return false;
}

}} // namespace SST::SnnDL
