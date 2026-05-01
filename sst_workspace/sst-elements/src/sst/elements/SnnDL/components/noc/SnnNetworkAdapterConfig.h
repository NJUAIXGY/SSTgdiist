// -*- c++ -*-
//
// SnnNetworkAdapterConfig:
// - 将 SnnNetworkAdapter 构造期 params.find(...) 收敛到一处，降低“胶水”分散与漂移风险。
// - 仅做参数解析/默认值，不改变现有行为。
//

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

struct SnnNetworkAdapterConfig {
    int verbose = 0;

    uint32_t node_id = 0;
    std::string routing_algorithm = "XY";
    std::string link_bw = "40GiB/s";
    std::string packet_size = "64B";
    std::string input_buf_size = "1KiB";
    std::string output_buf_size = "1KiB";

    bool enable_adaptive_routing = false;
    double congestion_threshold = 0.8;
    bool enable_merlin_router = false;
    bool use_direct_link = false;
    bool use_multi_port = false;
    std::string port_name = "network";

    std::string topology_type = "mesh2d";
    std::string topology_shape = "4x4";
};

inline SnnNetworkAdapterConfig parseSnnNetworkAdapterConfig(const SST::Params& params) {
    SnnNetworkAdapterConfig c{};

    c.verbose = params.find<int>("verbose", 0);
    c.node_id = params.find<uint32_t>("node_id", 0);
    c.routing_algorithm = params.find<std::string>("routing_algorithm", "XY");
    c.link_bw = params.find<std::string>("link_bw", "40GiB/s");
    c.packet_size = params.find<std::string>("packet_size", "64B");
    c.input_buf_size = params.find<std::string>("input_buf_size", "1KiB");
    c.output_buf_size = params.find<std::string>("output_buf_size", "1KiB");

    c.enable_adaptive_routing = params.find<bool>("enable_adaptive_routing", false);
    c.congestion_threshold = params.find<double>("congestion_threshold", 0.8);
    c.enable_merlin_router = params.find<bool>("enable_merlin_router", false);
    c.use_direct_link = params.find<bool>("use_direct_link", false);
    c.use_multi_port = params.find<bool>("use_multi_port", false);
    c.port_name = params.find<std::string>("port_name", "network");

    c.topology_type = params.find<std::string>("topology_type", "mesh2d");
    c.topology_shape = params.find<std::string>("topology_shape", "4x4");

    return c;
}

}} // namespace SST::SnnDL

