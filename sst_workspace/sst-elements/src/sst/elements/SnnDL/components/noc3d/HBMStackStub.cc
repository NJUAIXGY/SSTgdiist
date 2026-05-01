// -*- c++ -*-

#include "HBMStackStub.h"

namespace SST { namespace SnnDL {

HBMStackStub::HBMStackStub(SST::ComponentId_t id, SST::Params& params)
    : SST::Component(id),
      out_("SnnDL.HBMStackStub", 0, 0, SST::Output::STDOUT) {
    out_.setVerboseLevel(params.find<int>("verbose", 0));
    stack_id_ = params.find<uint32_t>("stack_id", 0);
    channels_per_stack_ = params.find<uint32_t>("channels_per_stack", 4);
    channel_interleave_bytes_ = params.find<uint32_t>("channel_interleave_bytes", 256);
    attached_nodes_ = params.find<std::string>("attached_nodes", "");
    min_attach_latency_ns_ = params.find<uint32_t>("min_attach_latency_ns", 0);
    max_attach_latency_ns_ = params.find<uint32_t>("max_attach_latency_ns", 0);
}

HBMStackStub::~HBMStackStub() = default;

void HBMStackStub::init(unsigned int /*phase*/) {}
void HBMStackStub::setup() {}
void HBMStackStub::finish() {
    out_.verbose(
        CALL_INFO, 1, 0,
        "[hbm-stack-stub] stack=%u channels=%u interleave=%u attached=\"%s\" latency_ns=[%u,%u]\n",
        stack_id_,
        channels_per_stack_,
        channel_interleave_bytes_,
        attached_nodes_.c_str(),
        min_attach_latency_ns_,
        max_attach_latency_ns_);
}

}} // namespace SST::SnnDL
