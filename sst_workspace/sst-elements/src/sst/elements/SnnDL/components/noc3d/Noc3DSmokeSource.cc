// -*- c++ -*-

#include "Noc3DSmokeSource.h"

#include <cctype>

#include "NocPacketEvent.h"

namespace SST { namespace SnnDL {

namespace {

inline int hexNibble_(char ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return 10 + (ch - 'a');
    if (ch >= 'A' && ch <= 'F') return 10 + (ch - 'A');
    return -1;
}

} // namespace

Noc3DSmokeSource::Noc3DSmokeSource(SST::ComponentId_t id, SST::Params& params)
    : SST::Component(id),
      out_("SnnDL.Noc3DSmokeSource", 0, 0, SST::Output::STDOUT) {
    out_.setVerboseLevel(params.find<int>("verbose", 0));

    node_id_ = params.find<uint32_t>("node_id", 0);
    dst_node_ = params.find<uint32_t>("dst_node", node_id_);
    src_endpoint_ = params.find<uint16_t>("src_endpoint", 0);
    dst_endpoint_ = params.find<uint16_t>("dst_endpoint", 0);
    packet_kind_ = params.find<uint16_t>("packet_kind", static_cast<uint16_t>(NocPacketKind::SpikeKey));
    send_cycle_ = params.find<uint64_t>("send_cycle", 0);

    const std::string payload_hex = params.find<std::string>("payload_hex", "");
    if (payload_hex.empty() || !decodeHexPayload_(payload_hex, payload_)) {
        out_.fatal(CALL_INFO, -1, "Noc3DSmokeSource requires a valid payload_hex\n");
    }

    network_link_ = configureLink("network");
    if (!network_link_) {
        out_.fatal(CALL_INFO, -1, "Noc3DSmokeSource requires port 'network'\n");
    }

    const std::string clock = params.find<std::string>("clock", "1GHz");
    registerClock(clock, new SST::Clock::Handler2<Noc3DSmokeSource, &Noc3DSmokeSource::clockTick_>(this));
}

Noc3DSmokeSource::~Noc3DSmokeSource() = default;

void Noc3DSmokeSource::init(unsigned int /*phase*/) {}
void Noc3DSmokeSource::setup() {}
void Noc3DSmokeSource::finish() {
    out_.verbose(CALL_INFO, 1, 0, "[noc3d-smoke-source] node=%u sent=%d\n", node_id_, sent_ ? 1 : 0);
}

bool Noc3DSmokeSource::clockTick_(SST::Cycle_t current_cycle) {
    if (sent_) return true;
    if (static_cast<uint64_t>(current_cycle) < send_cycle_) return false;

    auto* pkt = new NocPacketEvent();
    pkt->src_node = node_id_;
    pkt->dst_node = dst_node_;
    pkt->src_endpoint = src_endpoint_;
    pkt->dst_endpoint = dst_endpoint_;
    pkt->kind = packet_kind_;
    pkt->timestamp = static_cast<uint64_t>(current_cycle);
    pkt->payload = payload_;

    network_link_->send(pkt);
    sent_ = true;
    return true;
}

bool Noc3DSmokeSource::decodeHexPayload_(const std::string& hex, std::vector<uint8_t>& out_payload) {
    out_payload.clear();
    if (hex.empty() || (hex.size() % 2u) != 0u) return false;
    out_payload.reserve(hex.size() / 2u);
    for (size_t idx = 0; idx < hex.size(); idx += 2u) {
        const int hi = hexNibble_(hex[idx]);
        const int lo = hexNibble_(hex[idx + 1u]);
        if (hi < 0 || lo < 0) return false;
        out_payload.push_back(static_cast<uint8_t>((hi << 4) | lo));
    }
    return !out_payload.empty();
}

}} // namespace SST::SnnDL
