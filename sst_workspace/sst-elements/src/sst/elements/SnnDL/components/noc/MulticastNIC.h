// -*- c++ -*-
//
// MulticastNIC:
// - Minimal SnnInterface implementation for native router mesh.
// - Sends/receives SST::Event over a single "network" port (connected to MulticastRouter.local).
//

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/link.h>
#include <sst/core/output.h>

#include "SnnInterface.h"

namespace SST { namespace SnnDL {

class MulticastNIC final : public SnnInterface {
public:
    SST_ELI_REGISTER_SUBCOMPONENT(
        MulticastNIC,
        "SnnDL",
        "MulticastNIC",
        SST_ELI_ELEMENT_VERSION(1, 0, 0),
        "Native multicast NIC (inject to local MulticastRouter)",
        SST::SnnDL::SnnInterface
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"node_id", "网络节点ID（用于日志/状态）", "0"},
        {"port_name", "端口名称（连接到 router.local）", "network"},
        {"stats_header_bytes", "Bytes added to payload for NIC byte statistics", "24"},
        {"local_endpoint_multicast_enable", "Expand local endpoint fanout packets emitted by router", "0"},
        {"verbose", "日志详细级别", "0"}
    )

    SST_ELI_DOCUMENT_PORTS(
        {"network", "连接到本地 router 的端口", {"SnnDL.NocPacketEvent"}}
    )

    MulticastNIC(SST::ComponentId_t id, SST::Params& params);
    ~MulticastNIC() override;

    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

    void setReceiveHandler(ReceiveHandler handler) override;
    void sendToNode(uint32_t dest_node, SST::Event* event) override;
    void setNodeId(uint32_t node_id) override;
    uint32_t getNodeId() const override;
    std::string getNetworkStatus() const override;

private:
    void handleNetworkLinkEvent_(SST::Event* ev);
    uint64_t packetBytes_(const SST::Event* ev) const;

    SST::Output out_;
    std::string port_name_;
    uint32_t node_id_ = 0;
    uint64_t stats_header_bytes_ = 24;
    bool local_endpoint_multicast_enable_ = false;
    uint64_t pkts_sent_total_ = 0;
    uint64_t pkts_recv_total_ = 0;
    uint64_t bytes_sent_total_ = 0;
    uint64_t bytes_recv_total_ = 0;
    ReceiveHandler recv_handler_;
    SST::Link* network_link_ = nullptr;
};

}} // namespace SST::SnnDL
