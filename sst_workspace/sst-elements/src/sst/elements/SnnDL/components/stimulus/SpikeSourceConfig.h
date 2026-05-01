// -*- c++ -*-
//
// SpikeSourceConfig:
// - 将 SpikeSource 构造期 params.find(...) 收敛到一处，降低“胶水”分散与漂移风险。
// - 仅做参数解析/默认值/轻量规范化，不改变现有行为。
//

#pragma once

#include <cstdint>
#include <string>

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

struct SpikeSourceConfig {
    int verbose = 0;

    std::string dataset_path;
    std::string dataset_format = "TEXT";
    float time_scale = 1.0f;
    uint64_t start_time_us = 0;
    uint32_t neuron_offset = 0;
    uint32_t max_events = 0;

    uint32_t neurons_per_core = 0;
    uint32_t num_cores = 0;
    uint32_t neurons_per_pe = 0;

    float event_weight = 1.0f;

    bool segmented_release = false;
    uint32_t slices_per_superstep = 8;
    uint64_t slice_window_us = 5;
    uint64_t slice_gap_us = 5;
};

inline SpikeSourceConfig parseSpikeSourceConfig(const SST::Params& params) {
    SpikeSourceConfig c{};

    c.verbose = params.find<int>("verbose", 0);
    c.dataset_path = params.find<std::string>("dataset_path", "");
    c.dataset_format = params.find<std::string>("dataset_format", "TEXT");
    c.time_scale = params.find<float>("time_scale", 1.0f);
    c.start_time_us = params.find<uint64_t>("start_time_us", 0);
    c.neuron_offset = params.find<uint32_t>("neuron_offset", 0);
    c.max_events = params.find<uint32_t>("max_events", 0);

    c.neurons_per_core = params.find<uint32_t>("neurons_per_core", 0);
    c.num_cores = params.find<uint32_t>("num_cores", 0);
    c.neurons_per_pe = params.find<uint32_t>("neurons_per_pe", 0);
    if (c.neurons_per_pe == 0 && c.neurons_per_core > 0 && c.num_cores > 0) {
        c.neurons_per_pe = c.neurons_per_core * c.num_cores;
    }

    c.event_weight = params.find<float>("event_weight", 1.0f);

    c.segmented_release = params.find<int>("segmented_release", 0) != 0;
    c.slices_per_superstep = params.find<uint32_t>("slices_per_superstep", 8);
    c.slice_window_us = params.find<uint64_t>("slice_window_us", 5);
    c.slice_gap_us = params.find<uint64_t>("slice_gap_us", 5);

    return c;
}

}} // namespace SST::SnnDL

