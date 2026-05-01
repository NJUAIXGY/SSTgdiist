// -*- c++ -*-
//
// MulticastNIC implementation
//

#include "MulticastNIC.h"
#include "MulticastNICConfig.h"
#include "LocalEndpointMulticastCodec.h"

#include <inttypes.h>

#include <sst/core/event.h>
#include <sst/core/params.h>

#include "NocPacketEvent.h"

namespace SST { namespace SnnDL {

MulticastNIC::MulticastNIC(SST::ComponentId_t id, SST::Params& params)
    : SnnInterface(id, params),
      out_("SnnDL.MulticastNIC", 0, 0, SST::Output::STDOUT) {
    const MulticastNICConfig cfg = parseMulticastNICConfig(params);
    out_.setVerboseLevel(cfg.verbose);

    node_id_ = cfg.node_id;
    port_name_ = cfg.port_name;
    stats_header_bytes_ = cfg.stats_header_bytes;
    local_endpoint_multicast_enable_ = cfg.local_endpoint_multicast_enable;
    network_link_ = configureLink(port_name_,
                                  new SST::Event::Handler2<MulticastNIC, &MulticastNIC::handleNetworkLinkEvent_>(this));
}

MulticastNIC::~MulticastNIC() = default;

void MulticastNIC::init(unsigned int /*phase*/) {}
void MulticastNIC::setup() {}
void MulticastNIC::finish() {
    out_.verbose(
        CALL_INFO, 1, 0,
        "[mcast-nic] node=%u tx_pkts=%" PRIu64 " tx_bytes=%" PRIu64 " rx_pkts=%" PRIu64 " rx_bytes=%" PRIu64 "\n",
        node_id_,
        pkts_sent_total_,
        bytes_sent_total_,
        pkts_recv_total_,
        bytes_recv_total_);
}

void MulticastNIC::setReceiveHandler(ReceiveHandler handler) {
    recv_handler_ = std::move(handler);
}

void MulticastNIC::sendToNode(uint32_t /*dest_node*/, SST::Event* event) {
    if (!event) return;
    if (!network_link_) {
        delete event;
        return;
    }
    pkts_sent_total_ += 1;
    bytes_sent_total_ += packetBytes_(event);
    network_link_->send(event);
}

void MulticastNIC::setNodeId(uint32_t node_id) {
    node_id_ = node_id;
}

uint32_t MulticastNIC::getNodeId() const {
    return node_id_;
}

std::string MulticastNIC::getNetworkStatus() const {
    return std::string("MulticastNIC(node_id=") + std::to_string(node_id_) + ", port=" + port_name_ + ")";
}

void MulticastNIC::handleNetworkLinkEvent_(SST::Event* ev) {
    if (!ev) return;
    pkts_recv_total_ += 1;
    bytes_recv_total_ += packetBytes_(ev);
    if (local_endpoint_multicast_enable_) {
        auto* pkt = dynamic_cast<NocPacketEvent*>(ev);
        if (pkt && pkt->dst_endpoint == kEndpointFanoutSentinel) {
            LocalEndpointMaskTailV1 tail{};
            size_t payload_prefix_bytes = 0;
            if (!extractLocalEndpointMaskTail(pkt->payload, tail, payload_prefix_bytes)) {
                delete pkt;
                return;
            }
            pkt->payload.resize(payload_prefix_bytes);
            if (!recv_handler_) {
                delete pkt;
                return;
            }
            for (uint32_t bit = 0; bit < 32; ++bit) {
                if ((tail.endpoint_mask & (1u << bit)) == 0u) continue;
                auto* c = static_cast<NocPacketEvent*>(pkt->clone());
                c->dst_endpoint = static_cast<uint16_t>(bit);
                recv_handler_(c); // handler takes ownership
            }
            delete pkt;
            return;
        }
    }
    if (!recv_handler_) {
        delete ev;
        return;
    }
    recv_handler_(ev); // handler takes ownership
}

uint64_t MulticastNIC::packetBytes_(const SST::Event* ev) const {
    if (!ev) return 0;
    const auto* pkt = dynamic_cast<const NocPacketEvent*>(ev);
    if (!pkt) return 0;
    return stats_header_bytes_ + static_cast<uint64_t>(pkt->payload.size());
}

}} // namespace SST::SnnDL
