// -*- c++ -*-
//
// SnnNICConfig:
// - 将 SnnNIC 构造期 params.find(...) 收敛到一处，降低“胶水”分散与漂移风险。
// - 仅做参数解析与轻量规范化，不改变现有行为。
//

#pragma once

#include <algorithm>
#include <cstdint>
#include <string>

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

struct SnnNICConfig {
    bool sentinel_enable = false;

    uint32_t node_id = 0;
    std::string link_bw = "40GiB/s";
    std::string input_buf_size = "1KiB";
    std::string output_buf_size = "1KiB";
    std::string port_name = "network";
    bool use_direct_link = false;

    uint32_t virtual_channels = 2;
    uint32_t network_num_vns = 0;
    bool auto_vn_fallback = true;
    uint32_t effective_num_vns = 2;
    uint32_t vn_spike_data = 0;
    uint32_t vn_batch_data = 1;
    uint32_t vn_control = 1;

    bool enable_batching = false;
    bool flush_on_credit = true;
    bool probe_vn_on_setup = false;
    uint32_t batch_size_local = 8;
    uint32_t batch_size_remote = 32;
    uint64_t batch_flush_window_ns = 1000;

    uint32_t total_nodes = 16;

    // Inter-rank proxy batching (currently forced off by SnnNIC; keep parsed for compatibility)
    bool enable_inter_rank_batching = false;
    uint64_t inter_rank_batch_window_ns = 0;
    uint32_t nodes_per_rank = 0;

    int verbose = 0;
};

inline SnnNICConfig parseSnnNICConfig(const SST::Params& params) {
    SnnNICConfig c{};

    c.sentinel_enable = params.find<int>("sentinel_enable", 0) != 0;

    c.node_id = params.find<uint32_t>("node_id", 0);
    c.link_bw = params.find<std::string>("link_bw", "40GiB/s");
    c.input_buf_size = params.find<std::string>("input_buf_size", "1KiB");
    c.output_buf_size = params.find<std::string>("output_buf_size", "1KiB");
    c.port_name = params.find<std::string>("port_name", "network");
    c.use_direct_link = params.find<bool>("use_direct_link", false);

    c.virtual_channels = params.find<uint32_t>("virtual_channels", 2);
    c.network_num_vns = params.find<uint32_t>("network_num_vns", 0);
    c.auto_vn_fallback = params.find<bool>("auto_vn_fallback", true);
    c.effective_num_vns =
        (c.network_num_vns > 0) ? std::min(c.virtual_channels, c.network_num_vns) : c.virtual_channels;
    if (c.effective_num_vns == 0) c.effective_num_vns = 1;

    c.vn_spike_data = params.find<uint32_t>("vn_spike_data", 0);
    c.vn_batch_data = params.find<uint32_t>("vn_batch_data", 1);
    c.vn_control = params.find<uint32_t>("vn_control", 1);
    if (c.vn_spike_data >= c.effective_num_vns) c.vn_spike_data = 0;
    if (c.vn_batch_data >= c.effective_num_vns) c.vn_batch_data = 0;
    if (c.vn_control >= c.effective_num_vns) c.vn_control = 0;

    c.enable_batching = params.find<bool>("enable_batching", false);
    c.flush_on_credit = params.find<bool>("flush_on_credit", true);
    c.probe_vn_on_setup = params.find<bool>("probe_vn_on_setup", false);
    c.batch_size_local = params.find<uint32_t>("batch_size_local", 8);
    c.batch_size_remote = params.find<uint32_t>("batch_size_remote", 32);
    c.batch_flush_window_ns = params.find<uint64_t>("batch_flush_window", 1000);
    c.total_nodes = params.find<uint32_t>("total_nodes", 16);

    c.enable_inter_rank_batching = params.find<bool>("enable_inter_rank_batching", false);
    c.inter_rank_batch_window_ns = params.find<uint64_t>("inter_rank_batch_window", 0);
    c.nodes_per_rank = params.find<uint32_t>("nodes_per_rank", 0);

    c.verbose = params.find<int>("verbose", 0);
    if (c.sentinel_enable && c.verbose == 0) c.verbose = 1;

    return c;
}

}} // namespace SST::SnnDL

