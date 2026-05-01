// -*- c++ -*-
//
// GatingPEConfig:
// - 将 GatingPE 构造期 params.find(...) 收敛到一处，降低“胶水”分散与漂移风险。
// - 仅做参数解析/默认值，不改变既有实现结构。
//

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

struct GatingPEConfig {
    uint32_t total_nodes = 16;
    uint32_t rows_per_pe = 16;
    uint32_t top_k = 4;
    float weight_value = 1.0f;
    std::string transitions = "0-3:4-7,4-7:8-11,8-11:12-15";
    std::string edges_output_file;
    bool csv_header = true;
    std::string selection = "round_robin";
    uint32_t seed = 42;
    int verbose = 0;

    // Control-plane emit (optional)
    std::string gate_targets = "0-3";
    uint64_t emit_period_ns = 100000;
    uint64_t emit_count = 0;

    // NIC parameters (SnnNIC)
    uint32_t node_id = 0;
    std::string link_bw = "40GiB/s";
    std::string input_buf_size = "1KiB";
    std::string output_buf_size = "1KiB";
    uint32_t virtual_channels = 2;
    uint32_t vn_control = 1;
};

inline GatingPEConfig parseGatingPEConfig(const SST::Params& params) {
    GatingPEConfig c{};

    c.total_nodes = params.find<uint32_t>("total_nodes", 16);
    c.rows_per_pe = params.find<uint32_t>("rows_per_pe", 16);
    c.top_k = params.find<uint32_t>("top_k", 4);
    c.weight_value = params.find<float>("weight_value", 1.0f);
    c.transitions = params.find<std::string>("transitions", "0-3:4-7,4-7:8-11,8-11:12-15");
    c.edges_output_file = params.find<std::string>("edges_output_file", "");
    c.csv_header = params.find<int>("csv_header", 1) != 0;
    c.selection = params.find<std::string>("selection", "round_robin");
    c.seed = params.find<uint32_t>("seed", 42);

    c.verbose = params.find<int>("verbose", 0);

    c.gate_targets = params.find<std::string>("gate_targets", "0-3");
    c.emit_period_ns = params.find<uint64_t>("emit_period_ns", 100000);
    c.emit_count = params.find<uint64_t>("emit_count", 0);

    c.node_id = params.find<uint32_t>("node_id", 0);
    c.link_bw = params.find<std::string>("link_bw", "40GiB/s");
    c.input_buf_size = params.find<std::string>("input_buf_size", "1KiB");
    c.output_buf_size = params.find<std::string>("output_buf_size", "1KiB");
    c.virtual_channels = params.find<uint32_t>("virtual_channels", 2);
    c.vn_control = params.find<uint32_t>("vn_control", 1);

    return c;
}

}} // namespace SST::SnnDL

