// -*- c++ -*-

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

struct MulticastRouter3DNativeConfig final {
    int verbose = 0;
    uint32_t node_id = 0;
    uint64_t router_latency_cycles = 0;
    std::string mesh_shape = "4x4x2";
    std::string vertical_route_order = "zxy";
    uint32_t multicast_block_dim_z = 1;
    bool multicast_die_local_only = false;
};

inline MulticastRouter3DNativeConfig parseMulticastRouter3DNativeConfig(const SST::Params& params) {
    MulticastRouter3DNativeConfig cfg{};
    cfg.verbose = params.find<int>("verbose", 0);
    cfg.node_id = params.find<uint32_t>("node_id", 0);
    cfg.router_latency_cycles = params.find<uint64_t>("router_latency_cycles", 0);
    cfg.mesh_shape = params.find<std::string>("mesh_shape", "4x4x2");
    cfg.vertical_route_order = params.find<std::string>("vertical_route_order", "zxy");
    cfg.multicast_block_dim_z = params.find<uint32_t>("multicast_block_dim_z", 1);
    cfg.multicast_die_local_only = params.find<int>("multicast_die_local_only", 0) != 0;
    return cfg;
}

}} // namespace SST::SnnDL
