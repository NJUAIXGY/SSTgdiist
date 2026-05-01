// -*- c++ -*-

#pragma once

#include <array>
#include <cstdint>
#include <string>

#include <sst/core/component.h>
#include <sst/core/link.h>
#include <sst/core/output.h>
#include <sst/core/timeConverter.h>

#include "services/synapse/route3d/Route3DNodeMapper.h"

namespace SST { namespace SnnDL {

class NocPacketEvent;

class MulticastRouter3DNative final : public SST::Component {
public:
    SST_ELI_REGISTER_COMPONENT(
        MulticastRouter3DNative,
        "SnnDL",
        "MulticastRouter3DNative",
        SST_ELI_ELEMENT_VERSION(1, 0, 0),
        "SnnDL 3D native multicast router",
        COMPONENT_CATEGORY_NETWORK
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"node_id", "Router node id (must match PE node_id)", "0"},
        {"mesh_shape", "Mesh shape as 'WxHxZ' (e.g. '4x4x2')", "4x4x2"},
        {"vertical_route_order", "3D INTER-stage route order (zxy|zyx)", "zxy"},
        {"router_latency_cycles", "Additional per-hop latency in cycles", "0"},
        {"verbose", "日志详细级别", "0"}
    )

    SST_ELI_DOCUMENT_PORTS(
        {"local", "本地端口（连接到 MultiCorePE.network）", {"SnnDL.NocPacketEvent"}},
        {"north", "北向端口（连接到相邻 router）", {"SnnDL.NocPacketEvent"}},
        {"south", "南向端口（连接到相邻 router）", {"SnnDL.NocPacketEvent"}},
        {"east", "东向端口（连接到相邻 router）", {"SnnDL.NocPacketEvent"}},
        {"west", "西向端口（连接到相邻 router）", {"SnnDL.NocPacketEvent"}},
        {"up", "上层端口（连接到 z+1 router）", {"SnnDL.NocPacketEvent"}},
        {"down", "下层端口（连接到 z-1 router）", {"SnnDL.NocPacketEvent"}}
    )

    MulticastRouter3DNative(SST::ComponentId_t id, SST::Params& params);
    ~MulticastRouter3DNative() override;

    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    enum class VerticalRouteOrder : uint8_t { ZXY = 0, ZYX = 1 };

    void handleLocalLinkEvent(SST::Event* event);
    void handleNorthLinkEvent(SST::Event* event);
    void handleSouthLinkEvent(SST::Event* event);
    void handleEastLinkEvent(SST::Event* event);
    void handleWestLinkEvent(SST::Event* event);
    void handleUpLinkEvent(SST::Event* event);
    void handleDownLinkEvent(SST::Event* event);

    void routePacket_(NocPacketEvent* pkt);
    void routeUnicast3D_(NocPacketEvent* pkt, uint32_t dest_node);
    void routeSpikeKey_(NocPacketEvent* pkt);
    void routeSpikeInterBundle_(NocPacketEvent* pkt);

    void sendToLocal_(NocPacketEvent* pkt);
    void sendToNorth_(NocPacketEvent* pkt);
    void sendToSouth_(NocPacketEvent* pkt);
    void sendToEast_(NocPacketEvent* pkt);
    void sendToWest_(NocPacketEvent* pkt);
    void sendToUp_(NocPacketEvent* pkt);
    void sendToDown_(NocPacketEvent* pkt);

    static bool parseMeshShape3D_(const std::string& shape, MeshShape3D& out_shape);
    static bool parseVerticalRouteOrder_(const std::string& raw, VerticalRouteOrder& out_order);

    SST::Output out_;
    SST::TimeConverter timebase_;
    uint32_t node_id_ = 0;
    MeshShape3D mesh_shape_{};
    uint64_t router_latency_cycles_ = 0;
    VerticalRouteOrder vertical_route_order_ = VerticalRouteOrder::ZXY;
    uint32_t multicast_block_dim_z_ = 1;
    bool multicast_die_local_only_ = false;

    SST::Link* local_link_ = nullptr;
    SST::Link* north_link_ = nullptr;
    SST::Link* south_link_ = nullptr;
    SST::Link* east_link_ = nullptr;
    SST::Link* west_link_ = nullptr;
    SST::Link* up_link_ = nullptr;
    SST::Link* down_link_ = nullptr;

    uint64_t pkts_in_total_ = 0;
    uint64_t pkts_out_total_ = 0;
    uint64_t pkts_to_local_ = 0;
    uint64_t pkts_forward_xy_total_ = 0;
    uint64_t pkts_forward_z_total_ = 0;
    uint64_t bundle_v1_rx_total_ = 0;
    uint64_t bundle_v2_rx_total_ = 0;
    uint64_t bundle_v3_rx_total_ = 0;
    uint64_t bundle_v3_invalid_shape_total_ = 0;
    uint64_t bundle_v3_block_z_mismatch_total_ = 0;
    uint64_t bundle_v3_ingress_out_of_block_total_ = 0;
    uint64_t bundle_v3_rebuild_fail_total_ = 0;
};

}} // namespace SST::SnnDL
