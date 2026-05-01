// -*- c++ -*-

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include <sst/core/clock.h>
#include <sst/core/component.h>
#include <sst/core/link.h>
#include <sst/core/output.h>

namespace SST { namespace SnnDL {

class Noc3DSmokeSource final : public SST::Component {
public:
    SST_ELI_REGISTER_COMPONENT(
        Noc3DSmokeSource,
        "SnnDL",
        "Noc3DSmokeSource",
        SST_ELI_ELEMENT_VERSION(1, 0, 0),
        "Inject a single NocPacketEvent for isolated 3D smoke runs",
        COMPONENT_CATEGORY_PROCESSOR
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"node_id", "Source node id", "0"},
        {"dst_node", "Initial dst node metadata", "0"},
        {"src_endpoint", "Source endpoint id", "0"},
        {"dst_endpoint", "Destination endpoint id", "0"},
        {"packet_kind", "NocPacketKind numeric value", "4"},
        {"payload_hex", "Hex-encoded packet payload", ""},
        {"clock", "Source injection clock", "1GHz"},
        {"send_cycle", "Cycle when the packet is injected", "0"},
        {"verbose", "Verbose logging level", "0"}
    )

    SST_ELI_DOCUMENT_PORTS(
        {"network", "Connected to router.local", {"SnnDL.NocPacketEvent"}}
    )

    Noc3DSmokeSource(SST::ComponentId_t id, SST::Params& params);
    ~Noc3DSmokeSource() override;

    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    bool clockTick_(SST::Cycle_t current_cycle);
    static bool decodeHexPayload_(const std::string& hex, std::vector<uint8_t>& out_payload);

    SST::Output out_;
    SST::Link* network_link_ = nullptr;
    uint32_t node_id_ = 0;
    uint32_t dst_node_ = 0;
    uint16_t src_endpoint_ = 0;
    uint16_t dst_endpoint_ = 0;
    uint16_t packet_kind_ = 0;
    uint64_t send_cycle_ = 0;
    std::vector<uint8_t> payload_;
    bool sent_ = false;
};

}} // namespace SST::SnnDL
