// -*- c++ -*-
//
// MulticastRouterConfig:
// - 将 MulticastRouter 构造期 params.find(...) 收敛到一处，降低“胶水”分散与漂移风险。
// - 仅做参数解析/默认值，不改变现有行为。
//

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

struct MulticastRouterConfig {
    int verbose = 0;
    uint32_t node_id = 0;
    uint64_t router_latency_cycles = 0;
    bool serialize_output_enable = false;
    uint64_t serialize_service_cycles = 1;
    bool serialize_output_byte_enable = false;
    uint64_t serialize_bytes_per_cycle = 16;
    uint64_t serialize_header_bytes = 24;
    bool local_endpoint_multicast_enable = false;
    std::string multicast_inter_policy = "xy";
    std::string multicast_intra_policy = "manhattan_x_first";
    bool adaptive_telemetry_enable = false;
    uint64_t adaptive_inter_w_wait = 1;
    uint64_t adaptive_inter_w_service = 1;
    uint64_t adaptive_inter_w_len = 0;
    uint64_t adaptive_intra_w_bytes = 1;
    uint64_t adaptive_intra_w_queue = 1;
    std::string mesh_shape = "4x4";
};

inline MulticastRouterConfig parseMulticastRouterConfig(const SST::Params& params) {
    MulticastRouterConfig c{};
    c.verbose = params.find<int>("verbose", 0);
    c.node_id = params.find<uint32_t>("node_id", 0);
    c.router_latency_cycles = params.find<uint64_t>("router_latency_cycles", 0);
    c.serialize_output_enable = params.find<int>("serialize_output_enable", 0) != 0;
    c.serialize_service_cycles = params.find<uint64_t>("serialize_service_cycles", 1);
    if (c.serialize_service_cycles == 0) c.serialize_service_cycles = 1;
    c.serialize_output_byte_enable = params.find<int>("serialize_output_byte_enable", 0) != 0;
    c.serialize_bytes_per_cycle = params.find<uint64_t>("serialize_bytes_per_cycle", 16);
    if (c.serialize_bytes_per_cycle == 0) c.serialize_bytes_per_cycle = 1;
    c.serialize_header_bytes = params.find<uint64_t>("serialize_header_bytes", 24);
    c.local_endpoint_multicast_enable = params.find<int>("local_endpoint_multicast_enable", 0) != 0;
    c.multicast_inter_policy = params.find<std::string>("multicast_inter_policy", "xy");
    c.multicast_intra_policy = params.find<std::string>("multicast_intra_policy", "manhattan_x_first");
    c.adaptive_telemetry_enable = params.find<int>("adaptive_telemetry_enable", 0) != 0;
    c.adaptive_inter_w_wait = params.find<uint64_t>("adaptive_inter_w_wait", 1);
    c.adaptive_inter_w_service = params.find<uint64_t>("adaptive_inter_w_service", 1);
    c.adaptive_inter_w_len = params.find<uint64_t>("adaptive_inter_w_len", 0);
    c.adaptive_intra_w_bytes = params.find<uint64_t>("adaptive_intra_w_bytes", 1);
    c.adaptive_intra_w_queue = params.find<uint64_t>("adaptive_intra_w_queue", 1);
    c.mesh_shape = params.find<std::string>("mesh_shape", "4x4");
    return c;
}

}} // namespace SST::SnnDL
