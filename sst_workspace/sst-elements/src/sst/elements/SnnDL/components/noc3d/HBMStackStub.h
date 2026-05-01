// -*- c++ -*-

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/component.h>
#include <sst/core/output.h>

namespace SST { namespace SnnDL {

class HBMStackStub final : public SST::Component {
public:
    SST_ELI_REGISTER_COMPONENT(
        HBMStackStub,
        "SnnDL",
        "HBMStackStub",
        SST_ELI_ELEMENT_VERSION(1, 0, 0),
        "Minimal HBM-like stack stub for isolated snn3dexp object graphs",
        COMPONENT_CATEGORY_MEMORY
    )

    SST_ELI_DOCUMENT_PARAMS(
        {"stack_id", "HBM stack id", "0"},
        {"channels_per_stack", "Logical channels per stack", "4"},
        {"channel_interleave_bytes", "Channel interleave bytes", "256"},
        {"home_x0", "Home region x start", "0"},
        {"home_x1", "Home region x end", "0"},
        {"home_y0", "Home region y start", "0"},
        {"home_y1", "Home region y end", "0"},
        {"attached_nodes", "Comma-separated node ids attached to the stack", ""},
        {"min_attach_latency_ns", "Minimum attachment latency", "0"},
        {"max_attach_latency_ns", "Maximum attachment latency", "0"},
        {"verbose", "Verbose logging level", "0"}
    )

    HBMStackStub(SST::ComponentId_t id, SST::Params& params);
    ~HBMStackStub() override;

    void init(unsigned int phase) override;
    void setup() override;
    void finish() override;

private:
    SST::Output out_;
    uint32_t stack_id_ = 0;
    uint32_t channels_per_stack_ = 0;
    uint32_t channel_interleave_bytes_ = 0;
    std::string attached_nodes_;
    uint32_t min_attach_latency_ns_ = 0;
    uint32_t max_attach_latency_ns_ = 0;
};

}} // namespace SST::SnnDL
