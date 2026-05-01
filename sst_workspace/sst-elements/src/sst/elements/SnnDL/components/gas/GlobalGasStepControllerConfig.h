// -*- c++ -*-
//
// GlobalGasStepControllerConfig:
// - 将 GlobalGasStepController 构造期 params.find(...) 收敛到一处，降低“胶水”分散与漂移风险。
// - 仅做参数解析/默认值，行为由使用侧决定。
//

#pragma once

#include <cstdint>

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

struct GlobalGasStepControllerConfig {
    int verbose = 0;
    uint32_t start_seq = 1;
    uint32_t max_steps = 0;
    bool require_all_ready = true;
    bool strict_seq_check = false;
    // Experimental: progress watchdog (disabled by default).
    bool experimental_progress_enable = false;
    uint64_t experimental_progress_period_cycles = 0;
    uint32_t experimental_progress_max_reports = 0;
    uint32_t experimental_progress_dump_first_n = 8;
    // Experimental: step-level global apply bank credit control.
    bool credit_ctrl_enable = false;
    uint32_t credit_ctrl_credit_min = 1;
    uint32_t credit_ctrl_credit_max = 2;
    uint32_t credit_ctrl_top_k = 0; // 0=disable (even if enable=1)
    bool gating_event_enable = false;
    uint32_t gating_event_rows_per_pe = 0;
    uint32_t gating_event_top_k = 0;
    uint64_t gating_event_ttl_cycles = 0;
    uint32_t gating_event_target_offset = 1;
    uint32_t gating_event_target_stride = 1;
    bool gating_event_include_self = false;
};

inline GlobalGasStepControllerConfig parseGlobalGasStepControllerConfig(const SST::Params& params) {
    GlobalGasStepControllerConfig c{};
    c.verbose = params.find<int>("verbose", 0);
    c.start_seq = params.find<uint32_t>("start_seq", 1);
    c.max_steps = params.find<uint32_t>("max_steps", 0);
    c.require_all_ready = params.find<int>("require_all_ready", 1) != 0;
    c.strict_seq_check = params.find<int>("strict_seq_check", 0) != 0;
    c.experimental_progress_enable = params.find<int>("experimental_progress_enable", 0) != 0;
    c.experimental_progress_period_cycles = params.find<uint64_t>("experimental_progress_period_cycles", 0);
    c.experimental_progress_max_reports = params.find<uint32_t>("experimental_progress_max_reports", 0);
    c.experimental_progress_dump_first_n = params.find<uint32_t>("experimental_progress_dump_first_n", 8);
    c.credit_ctrl_enable = params.find<int>("credit_ctrl_enable", 0) != 0;
    c.credit_ctrl_credit_min = params.find<uint32_t>("credit_ctrl_credit_min", 1);
    c.credit_ctrl_credit_max = params.find<uint32_t>("credit_ctrl_credit_max", 2);
    c.credit_ctrl_top_k = params.find<uint32_t>("credit_ctrl_top_k", 0);
    c.gating_event_enable = params.find<int>("gating_event_enable", 0) != 0;
    c.gating_event_rows_per_pe = params.find<uint32_t>("gating_event_rows_per_pe", 0);
    c.gating_event_top_k = params.find<uint32_t>("gating_event_top_k", 0);
    c.gating_event_ttl_cycles = params.find<uint64_t>("gating_event_ttl_cycles", 0);
    c.gating_event_target_offset = params.find<uint32_t>("gating_event_target_offset", 1);
    c.gating_event_target_stride = params.find<uint32_t>("gating_event_target_stride", 1);
    c.gating_event_include_self = params.find<int>("gating_event_include_self", 0) != 0;
    return c;
}

}} // namespace SST::SnnDL
