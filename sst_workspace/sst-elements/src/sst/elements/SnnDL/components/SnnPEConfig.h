// -*- c++ -*-
//
// SnnPEConfig:
// - 旧架构兼容组件（Deprecated）仍在仓库内保留；为降低“胶水”分散与默认值漂移风险，
//   将其构造期 params.find(...) 收敛到一处。
// - 仅做参数解析/默认值，不改变既有实现结构。
//

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

struct SnnPEConfig {
    int verbose = 0;
    uint32_t num_neurons = 0; // required
    uint32_t node_id = 0;

    float v_thresh = 1.0f;
    float v_reset = 0.0f;
    float v_rest = 0.0f;
    float tau_mem = 20.0f;
    uint32_t t_ref = 2;

    uint64_t base_addr = 0;
    uint32_t weights_per_neuron = 0;

    std::string neuron_model = "LIF";
    std::string clock = "1GHz";

    std::string weights_file;
    uint32_t neuron_id_start = 0;
    std::string binary_weights_file;

    bool enable_test_traffic = false;
    uint32_t test_target_node = 0;
    uint32_t test_period = 100;
    uint32_t test_spikes_per_burst = 4;
    float test_weight = 0.2f;
};

inline SnnPEConfig parseSnnPEConfig(const SST::Params& params) {
    SnnPEConfig c{};
    c.verbose = params.find<int>("verbose", 0);
    c.num_neurons = params.find<uint32_t>("num_neurons", 0);
    c.node_id = params.find<uint32_t>("node_id", 0);

    c.v_thresh = params.find<float>("v_thresh", 1.0f);
    c.v_reset = params.find<float>("v_reset", 0.0f);
    c.v_rest = params.find<float>("v_rest", 0.0f);
    c.tau_mem = params.find<float>("tau_mem", 20.0f);
    c.t_ref = params.find<uint32_t>("t_ref", 2);

    c.base_addr = params.find<uint64_t>("base_addr", 0);
    c.weights_per_neuron = params.find<uint32_t>("weights_per_neuron", 0);

    c.neuron_model = params.find<std::string>("neuron_model", "LIF");
    c.clock = params.find<std::string>("clock", "1GHz");

    c.weights_file = params.find<std::string>("weights_file", "");
    c.neuron_id_start = params.find<uint32_t>("neuron_id_start", 0);
    c.binary_weights_file = params.find<std::string>("binary_weights_file", "");

    c.enable_test_traffic = params.find<bool>("enable_test_traffic", false);
    c.test_target_node = params.find<uint32_t>("test_target_node", 0);
    c.test_period = params.find<uint32_t>("test_period", 100);
    c.test_spikes_per_burst = params.find<uint32_t>("test_spikes_per_burst", 4);
    c.test_weight = params.find<float>("test_weight", 0.2f);
    return c;
}

}} // namespace SST::SnnDL

