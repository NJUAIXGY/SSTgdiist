// -*- c++ -*-
//
// MulticastRouter:
// - SnnDL 原生 NoC 路由组件（blocked multicast + block 间单播到 ingress）
// - 仅处理 NocPacketEvent（payload bytes 不透明；仅在 kind=SpikeKey 时解析路由头）
//

#pragma once

#include <array>
#include <cstdint>
#include <string>

#include <sst/core/component.h>
#include <sst/core/link.h>
#include <sst/core/output.h>
#include <sst/core/timeConverter.h>

namespace SST { namespace SnnDL {

class NocPacketEvent;

class MulticastRouter final : public SST::Component {
public:
    SST_ELI_REGISTER_COMPONENT(
        MulticastRouter,
        "SnnDL",
        "MulticastRouter",
        SST_ELI_ELEMENT_VERSION(1, 0, 0),
        "SnnDL native multicast router (blocked multicast)",
        COMPONENT_CATEGORY_NETWORK
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"node_id", "Router node id (must match PE node_id)", "0"},
        {"mesh_shape", "Mesh shape as 'WxH' or 'WxHxZ' (e.g. '4x4'|'4x4x2')", "4x4"},
        {"router_latency_cycles", "Additional per-hop latency in cycles (1 cycle ~= 1ns under 1GHz)", "0"},
        {"serialize_output_enable", "Enable per-output-port serialization (simple contention model)", "0"},
        {"serialize_service_cycles", "Per-packet service time per output port (cycles)", "1"},
        {"serialize_output_byte_enable", "When serialization is enabled, derive service cycles from packet bytes", "0"},
        {"serialize_bytes_per_cycle", "Byte service rate used by byte-aware serialization mode", "16"},
        {"serialize_header_bytes", "Header bytes added to payload size in byte-aware serialization mode", "24"},
        {"local_endpoint_multicast_enable", "Send one local fanout packet and let NIC expand endpoint mask", "0"},
        {"multicast_inter_policy", "SpikeKey INTER-stage unicast routing policy (xy|yx|hash_xy|adaptive_xy_yx)", "xy"},
        {"multicast_intra_policy", "SpikeKey INTRA-stage blocked multicast tree policy (manhattan_x_first|manhattan_y_first|adaptive)", "manhattan_x_first"},
        {"adaptive_telemetry_enable", "Enable adaptive route/tree decision telemetry in finish logs", "0"},
        {"adaptive_inter_w_wait", "Adaptive INTER cost weight for per-port wait cycles", "1"},
        {"adaptive_inter_w_service", "Adaptive INTER cost weight for per-port service cycles", "1"},
        {"adaptive_inter_w_len", "Adaptive INTER lookahead weight for orthogonal Manhattan length bias", "0"},
        {"adaptive_intra_w_bytes", "Adaptive INTRA cost weight for subtree predicted bytes_out", "1"},
        {"adaptive_intra_w_queue", "Adaptive INTRA cost weight for immediate child-port queue/service cost", "1"},
        {"verbose", "日志详细级别", "0"}
    )

    SST_ELI_DOCUMENT_PORTS(
        {"local", "本地端口（连接到 MultiCorePE.network）", {"SnnDL.NocPacketEvent"}},
        {"north", "北向端口（连接到相邻 router）", {"SnnDL.NocPacketEvent"}},
        {"south", "南向端口（连接到相邻 router）", {"SnnDL.NocPacketEvent"}},
        {"east", "东向端口（连接到相邻 router）", {"SnnDL.NocPacketEvent"}},
        {"west", "西向端口（连接到相邻 router）", {"SnnDL.NocPacketEvent"}}
    )

    MulticastRouter(SST::ComponentId_t id, SST::Params& params);
    ~MulticastRouter();

    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    enum class InterBlockRoutePolicy : uint8_t { XY = 0, YX = 1, HashXY = 2, AdaptiveXYYX = 3 };
    enum class IntraBlockTreePolicy : uint8_t { ManhattanXFirst = 0, ManhattanYFirst = 1, Adaptive = 2 };

    void handleLocalLinkEvent(SST::Event* event);
    void handleNorthLinkEvent(SST::Event* event);
    void handleSouthLinkEvent(SST::Event* event);
    void handleEastLinkEvent(SST::Event* event);
    void handleWestLinkEvent(SST::Event* event);
    void handlePacket_(NocPacketEvent* pkt);

    void routeUnicastXY_(NocPacketEvent* pkt);
    void routeUnicastYX_(NocPacketEvent* pkt);
    void routeSpikeKey_(NocPacketEvent* pkt);
    void routeSpikeInterBundle_(NocPacketEvent* pkt);

    void sendToLocal_(NocPacketEvent* pkt);
    void sendToNorth_(NocPacketEvent* pkt);
    void sendToSouth_(NocPacketEvent* pkt);
    void sendToEast_(NocPacketEvent* pkt);
    void sendToWest_(NocPacketEvent* pkt);
    void sendOnPort_(SST::Link* link, uint32_t port_idx, NocPacketEvent* pkt);
    uint64_t packetBytes_(const NocPacketEvent* pkt) const;

    static bool parseMeshShape_(const std::string& shape, uint32_t& out_w, uint32_t& out_h, uint32_t& out_z);
    static bool nodeIdToCoord2DLayered_(uint32_t node_id,
                                        uint32_t mesh_w,
                                        uint32_t mesh_h,
                                        uint32_t mesh_z,
                                        uint32_t& out_x,
                                        uint32_t& out_y,
                                        uint32_t& out_z);
    static bool parseInterPolicy_(const std::string& s, InterBlockRoutePolicy& out);
    static bool parseIntraPolicy_(const std::string& s, IntraBlockTreePolicy& out);

    SST::Output out_;
    uint32_t node_id_ = 0;
    uint32_t mesh_w_ = 0;
    uint32_t mesh_h_ = 0;
    uint32_t mesh_z_ = 1;
    SST::TimeConverter timebase_;
    uint64_t router_latency_cycles_ = 0;
    bool serialize_output_enable_ = false;
    uint64_t serialize_service_cycles_ = 1;
    bool serialize_output_byte_enable_ = false;
    uint64_t serialize_bytes_per_cycle_ = 16;
    uint64_t serialize_header_bytes_ = 24;
    bool local_endpoint_multicast_enable_ = false;
    InterBlockRoutePolicy multicast_inter_policy_ = InterBlockRoutePolicy::XY;
    IntraBlockTreePolicy multicast_intra_policy_ = IntraBlockTreePolicy::ManhattanXFirst;
    bool adaptive_telemetry_enable_ = false;
    uint64_t adaptive_inter_w_wait_ = 1;
    uint64_t adaptive_inter_w_service_ = 1;
    uint64_t adaptive_inter_w_len_ = 0;
    uint64_t adaptive_intra_w_bytes_ = 1;
    uint64_t adaptive_intra_w_queue_ = 1;
    std::array<uint64_t, 5> port_next_free_cycle_{{0, 0, 0, 0, 0}}; // local,n,s,e,w

    SST::Link* local_link_ = nullptr;
    SST::Link* north_link_ = nullptr;
    SST::Link* south_link_ = nullptr;
    SST::Link* east_link_ = nullptr;
    SST::Link* west_link_ = nullptr;

    uint64_t pkts_in_total_ = 0;
    uint64_t pkts_out_total_ = 0;
    uint64_t pkts_to_local_ = 0;
    uint64_t pkts_forward_xy_ = 0;
    uint64_t bytes_in_total_ = 0;
    uint64_t bytes_out_total_ = 0;
    uint64_t bytes_to_local_ = 0;
    uint64_t bytes_forward_xy_ = 0;
    uint64_t byte_hops_total_ = 0;

    uint64_t spikekey_in_total_ = 0;
    uint64_t spikekey_stage_inter_ = 0;
    uint64_t spikekey_stage_intra_ = 0;
    uint64_t spikekey_clones_total_ = 0;

    uint64_t adaptive_inter_decisions_total_ = 0;
    uint64_t adaptive_inter_choose_x_total_ = 0;
    uint64_t adaptive_inter_choose_y_total_ = 0;
    uint64_t adaptive_inter_tie_total_ = 0;
    uint64_t adaptive_inter_cost_x_total_ = 0;
    uint64_t adaptive_inter_cost_y_total_ = 0;
    uint64_t adaptive_inter_cost_chosen_total_ = 0;
    uint64_t adaptive_inter_cost_delta_abs_total_ = 0;

    uint64_t adaptive_intra_decisions_total_ = 0;
    uint64_t adaptive_intra_choose_x_total_ = 0;
    uint64_t adaptive_intra_choose_y_total_ = 0;
    uint64_t adaptive_intra_tie_total_ = 0;
    uint64_t adaptive_intra_cost_x_total_ = 0;
    uint64_t adaptive_intra_cost_y_total_ = 0;
    uint64_t adaptive_intra_cost_chosen_total_ = 0;
    uint64_t adaptive_intra_cost_delta_abs_total_ = 0;
    uint64_t adaptive_intra_pred_bytes_x_total_ = 0;
    uint64_t adaptive_intra_pred_bytes_y_total_ = 0;
    uint64_t adaptive_intra_pred_bytes_chosen_total_ = 0;
    uint64_t adaptive_intra_pred_bytes_delta_abs_total_ = 0;
    uint64_t adaptive_intra_queue_x_total_ = 0;
    uint64_t adaptive_intra_queue_y_total_ = 0;
    uint64_t adaptive_intra_queue_chosen_total_ = 0;
};

}} // namespace SST::SnnDL
