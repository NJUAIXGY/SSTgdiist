// -*- c++ -*-

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/component.h>
#include <sst/core/link.h>
#include <sst/core/output.h>

namespace SST { namespace SnnDL {

class Noc3DSmokeSink final : public SST::Component {
public:
    SST_ELI_REGISTER_COMPONENT(
        Noc3DSmokeSink,
        "SnnDL",
        "Noc3DSmokeSink",
        SST_ELI_ELEMENT_VERSION(1, 0, 0),
        "Collect packets delivered to router.local during isolated 3D smoke runs",
        COMPONENT_CATEGORY_PROCESSOR
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"node_id", "Sink node id", "0"},
        {"expected_packets", "Expected matching packets", "1"},
        {"expected_kind", "Expected NocPacketKind numeric value (0 disables check)", "0"},
        {"expected_dst_endpoint", "Expected destination endpoint (-1 disables check)", "-1"},
        {"output_json", "Path to write sink result json", ""},
        {"verbose", "Verbose logging level", "0"}
    )

    SST_ELI_DOCUMENT_PORTS(
        {"network", "Connected to router.local", {"SnnDL.NocPacketEvent"}}
    )

    Noc3DSmokeSink(SST::ComponentId_t id, SST::Params& params);
    ~Noc3DSmokeSink() override;

    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    void handleNetworkEvent_(SST::Event* ev);
    void writeReport_(bool passed) const;

    SST::Output out_;
    SST::Link* network_link_ = nullptr;
    uint32_t node_id_ = 0;
    uint64_t expected_packets_ = 1;
    uint16_t expected_kind_ = 0;
    int64_t expected_dst_endpoint_ = -1;
    std::string output_json_;
    uint64_t received_packets_ = 0;
    uint64_t matched_packets_ = 0;
    uint16_t last_kind_ = 0;
    uint16_t last_dst_endpoint_ = 0;
    uint16_t last_hop_count_ = 0;
};

}} // namespace SST::SnnDL
