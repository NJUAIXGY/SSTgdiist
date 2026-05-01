// -*- c++ -*-

#include "Noc3DSmokeSink.h"

#include <fstream>

#include <sst/core/event.h>

#include "NocPacketEvent.h"

namespace SST { namespace SnnDL {

Noc3DSmokeSink::Noc3DSmokeSink(SST::ComponentId_t id, SST::Params& params)
    : SST::Component(id),
      out_("SnnDL.Noc3DSmokeSink", 0, 0, SST::Output::STDOUT) {
    out_.setVerboseLevel(params.find<int>("verbose", 0));

    node_id_ = params.find<uint32_t>("node_id", 0);
    expected_packets_ = params.find<uint64_t>("expected_packets", 1);
    expected_kind_ = params.find<uint16_t>("expected_kind", 0);
    expected_dst_endpoint_ = params.find<int64_t>("expected_dst_endpoint", -1);
    output_json_ = params.find<std::string>("output_json", "");

    network_link_ = configureLink(
        "network",
        new SST::Event::Handler2<Noc3DSmokeSink, &Noc3DSmokeSink::handleNetworkEvent_>(this));
    if (!network_link_) {
        out_.fatal(CALL_INFO, -1, "Noc3DSmokeSink requires port 'network'\n");
    }
}

Noc3DSmokeSink::~Noc3DSmokeSink() = default;

void Noc3DSmokeSink::init(unsigned int /*phase*/) {}
void Noc3DSmokeSink::setup() {}

void Noc3DSmokeSink::finish() {
    const bool passed = matched_packets_ >= expected_packets_;
    writeReport_(passed);
    out_.verbose(
        CALL_INFO, 1, 0,
        "[noc3d-smoke-sink] node=%u received=%" PRIu64 " matched=%" PRIu64 " expected=%" PRIu64 " pass=%d\n",
        node_id_,
        received_packets_,
        matched_packets_,
        expected_packets_,
        passed ? 1 : 0);
}

void Noc3DSmokeSink::handleNetworkEvent_(SST::Event* ev) {
    auto* pkt = dynamic_cast<NocPacketEvent*>(ev);
    if (!pkt) {
        delete ev;
        return;
    }

    received_packets_ += 1;
    last_kind_ = pkt->kind;
    last_dst_endpoint_ = pkt->dst_endpoint;
    last_hop_count_ = pkt->hop_count;

    bool kind_match = true;
    bool endpoint_match = true;
    if (expected_kind_ != 0) {
        kind_match = pkt->kind == expected_kind_;
    }
    if (expected_dst_endpoint_ >= 0) {
        endpoint_match = pkt->dst_endpoint == static_cast<uint16_t>(expected_dst_endpoint_);
    }
    if (kind_match && endpoint_match) {
        matched_packets_ += 1;
    }
    delete pkt;
}

void Noc3DSmokeSink::writeReport_(bool passed) const {
    if (output_json_.empty()) return;
    std::ofstream out(output_json_, std::ios::out | std::ios::trunc);
    if (!out.good()) return;
    out << "{\n"
        << "  \"node_id\": " << node_id_ << ",\n"
        << "  \"received_packets\": " << received_packets_ << ",\n"
        << "  \"matched_packets\": " << matched_packets_ << ",\n"
        << "  \"expected_packets\": " << expected_packets_ << ",\n"
        << "  \"last_kind\": " << last_kind_ << ",\n"
        << "  \"last_dst_endpoint\": " << last_dst_endpoint_ << ",\n"
        << "  \"last_hop_count\": " << last_hop_count_ << ",\n"
        << "  \"pass\": " << (passed ? "true" : "false") << "\n"
        << "}\n";
}

}} // namespace SST::SnnDL
