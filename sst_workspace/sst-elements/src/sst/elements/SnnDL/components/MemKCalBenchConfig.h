// -*- c++ -*-
//
// MemKCalBenchConfig:
// - 将 MemKCalBench 构造期 params.find(...) 收敛到一处，降低“胶水”分散与漂移风险。
// - 仅做参数解析/默认值，不改变既有 benchmark 语义。
//

#pragma once

#include <algorithm>
#include <cstdint>
#include <sstream>
#include <string>
#include <vector>

#include <sst/core/params.h>

namespace SST { namespace SnnDL {

struct MemKCalBenchConfig {
    int verbose = 0;
    uint64_t base_addr = 0;
    uint32_t row_bytes = 8192;
    uint32_t bank_bits = 0;
    uint32_t bank_shift = 0;
    std::string clock = "1GHz";
    std::string output_csv = "sst_dram_si/stats/kcal/bench_results.csv";

    std::vector<uint32_t> payload_sizes = {4096, 8192, 16384, 32768};
    uint32_t gap_start = 0;
    uint32_t gap_end = 65536;
    uint32_t gap_step = 512;

    bool do_row_hit = true;
    bool do_row_switch = true;
};

inline MemKCalBenchConfig parseMemKCalBenchConfig(const SST::Params& params) {
    MemKCalBenchConfig c{};

    c.verbose = params.find<int>("verbose", 0);
    c.base_addr = params.find<uint64_t>("base_addr", 0);
    c.row_bytes = params.find<uint32_t>("row_bytes", 8192);
    c.bank_bits = params.find<uint32_t>("bank_bits", 0);
    c.bank_shift = params.find<uint32_t>("bank_shift", 0);
    c.clock = params.find<std::string>("clock", "1GHz");
    c.output_csv = params.find<std::string>("output_csv", "sst_dram_si/stats/kcal/bench_results.csv");

    // payload sizes
    {
        const std::string pls = params.find<std::string>("payload_sizes", "4096,8192,16384,32768");
        std::vector<uint32_t> payloads;
        payloads.reserve(8);
        std::stringstream ss(pls);
        std::string tok;
        while (std::getline(ss, tok, ',')) {
            try {
                uint32_t v = static_cast<uint32_t>(std::stoul(tok));
                if (v) payloads.push_back(v);
            } catch (...) {
            }
        }
        if (!payloads.empty()) c.payload_sizes = std::move(payloads);
    }

    c.gap_start = params.find<uint32_t>("gap_start", 0);
    c.gap_end = params.find<uint32_t>("gap_end", 65536);
    c.gap_step = params.find<uint32_t>("gap_step", 512);
    if (c.gap_step == 0) c.gap_step = 1;

    {
        const std::string scenes = params.find<std::string>("scenes", "row_hit,row_switch");
        c.do_row_hit = (scenes.find("row_hit") != std::string::npos);
        c.do_row_switch = (scenes.find("row_switch") != std::string::npos);
    }

    return c;
}

}} // namespace SST::SnnDL
