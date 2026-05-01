// -*- c++ -*-
//
// WeightLoaderConfig:
// - 将 WeightLoader 构造期 params.find(...) 收敛到一处，降低“胶水”分散与漂移风险。
// - 仅做参数解析/默认值/规范化，不改变现有行为。
//

#pragma once

#include <algorithm>
#include <cstdint>
#include <string>

#include <sst/core/params.h>

#include "WorkloadConfig.h"

namespace SST { namespace SnnDL {

struct WeightLoaderConfig {
    int verbose = 0;
    uint32_t node_id = 0;

    // Compatibility: workload_impl may be missing in older scripts.
    // If empty, WeightLoader stays enabled.
    std::string workload_impl;

    std::string weight_file;
    uint64_t base_addr_start = 0;
    uint64_t per_core_stride = 0;
    int num_cores = 1;
    uint32_t neurons_per_core = 64;
    uint32_t rows_per_core = 0;
    uint32_t cols_per_core = 0;
    float fill_value = 0.5f;

    std::string weight_format = "bin";
    bool raw_mode = false;

    bool bcsr_enable = false;
    uint32_t bcsr_block_rows = 16;
    uint32_t bcsr_block_cols = 16;
    uint32_t bcsr_val_bytes = 4;
    uint32_t bcsr_idx_bytes = 2;
    std::string bcsr_pattern = "diag";

    bool per_core_files = false;
    std::string file_template;
    std::string single_file;
    bool row_major = true;
    uint32_t chunk_size_bytes = 64;
    bool validate_length = true;
    int file_core_offset = 0;

    bool timed_seed_enable = true;
    uint32_t timed_seed_count = 1;
    bool timed_seed_allow_cache = false;
    uint32_t timed_write_window = 256;

    std::string loader_done_key;

    bool verify_readback_enable = false;
    int verify_readback_core = 0;
    uint32_t verify_readback_bytes = 64;
    std::string verify_readback_mode = "raw_bcsr";
    uint32_t verify_readback_samples = 16;
    uint32_t verify_readback_seed = 314159;
    uint32_t verify_colidx_start_index = 441;
    bool strict_loader_done = false;

    std::string write_pattern_mode = "const";
    uint32_t write_pattern_row_scale = 1024;
    uint32_t min_raw_bcsr_chunk_bytes = 4096;

    bool diag_runtime_read_enable = false;
    int diag_runtime_read_core = 0;
    uint64_t diag_runtime_read_offset = 0;
    uint32_t diag_runtime_read_bytes = 64;

    // Derived: disable WeightLoader for non-snn workloads to avoid clobbering stream regions.
    bool enabled = true;
};

inline WeightLoaderConfig parseWeightLoaderConfig(const SST::Params& params) {
    WeightLoaderConfig c{};

    c.verbose = params.find<int>("verbose", 0);
    c.node_id = params.find<uint32_t>("node_id", 0);
    c.weight_file = params.find<std::string>("weight_file", "");
    c.base_addr_start = params.find<uint64_t>("base_addr_start", 0);
    c.per_core_stride = params.find<uint64_t>("per_core_stride", 0);
    c.num_cores = params.find<int>("num_cores", 1);
    c.neurons_per_core = params.find<uint32_t>("neurons_per_core", 64);

    // 行/列可选参数：未提供或为0时退回到 neurons_per_core
    c.rows_per_core = params.find<uint32_t>("rows_per_core", 0);
    c.cols_per_core = params.find<uint32_t>("cols_per_core", 0);
    if (c.rows_per_core == 0) c.rows_per_core = c.neurons_per_core;
    if (c.cols_per_core == 0) c.cols_per_core = c.neurons_per_core;

    c.fill_value = params.find<float>("fill_value", 0.5f);
    c.weight_format = params.find<std::string>("weight_format", "bin");
    c.raw_mode = (c.weight_format == "raw");

    // weight_format=bcsr 时默认启用 BCSR（与现有行为一致）
    c.bcsr_enable = params.find<int>("bcsr_enable", 0) != 0 || (c.weight_format == "bcsr");
    c.bcsr_block_rows = params.find<uint32_t>("bcsr_block_rows", 16);
    c.bcsr_block_cols = params.find<uint32_t>("bcsr_block_cols", 16);
    c.bcsr_val_bytes = params.find<uint32_t>("bcsr_val_bytes", 4);
    c.bcsr_idx_bytes = params.find<uint32_t>("bcsr_idx_bytes", 2);
    c.bcsr_pattern = params.find<std::string>("bcsr_pattern", "diag");

    c.per_core_files = params.find<int>("per_core_files", 0) != 0;
    c.file_template = params.find<std::string>("file_template", "");
    c.single_file = params.find<std::string>("single_file", "");
    c.row_major = params.find<int>("row_major", 1) != 0;
    c.chunk_size_bytes = params.find<uint32_t>("chunk_size_bytes", 64);
    c.validate_length = params.find<int>("validate_length", 1) != 0;
    c.file_core_offset = params.find<int>("file_core_offset", 0);

    c.timed_seed_enable = params.find<int>("timed_seed_enable", 1) != 0;
    c.timed_seed_count = params.find<uint32_t>("timed_seed_count", 1);
    c.timed_seed_allow_cache = params.find<int>("timed_seed_allow_cache", 0) != 0;
    c.timed_write_window = std::max<uint32_t>(c.timed_seed_count, 256u);

    c.loader_done_key = params.find<std::string>("loader_done_key", "");
    c.verify_readback_enable = params.find<int>("verify_readback_enable", 0) != 0;
    c.verify_readback_core = params.find<int>("verify_readback_core", 0);
    c.verify_readback_bytes = params.find<uint32_t>("verify_readback_bytes", 64);
    c.verify_readback_mode = params.find<std::string>("verify_readback_mode", "raw_bcsr");
    c.verify_readback_samples = params.find<uint32_t>("verify_readback_samples", 16);
    c.verify_readback_seed = params.find<uint32_t>("verify_readback_seed", 314159);
    c.verify_colidx_start_index = params.find<uint32_t>("verify_colidx_start_index", 441);
    c.strict_loader_done = params.find<int>("strict_loader_done", 0) != 0;

    c.write_pattern_mode = params.find<std::string>("write_pattern_mode", "const");
    c.write_pattern_row_scale = params.find<uint32_t>("write_pattern_row_scale", 1024);
    c.min_raw_bcsr_chunk_bytes = params.find<uint32_t>("min_raw_bcsr_chunk_bytes", 4096);
    if (c.min_raw_bcsr_chunk_bytes != 0 && c.min_raw_bcsr_chunk_bytes < 64) {
        c.min_raw_bcsr_chunk_bytes = 64;
    }

    // strict_loader_done 仅对 raw+BCSR 有意义；其他模式直接忽略，避免误伤旧用例。
    if (c.strict_loader_done && !(c.raw_mode && c.bcsr_enable)) {
        c.strict_loader_done = false;
    }
    if (c.strict_loader_done) {
        // strict 模式下必须启用写后读回校验；否则 loader_done 会在“写入不可见/丢写”时误放行。
        c.verify_readback_enable = true;
    }

    c.diag_runtime_read_enable = params.find<int>("diag_runtime_read_enable", 0) != 0;
    c.diag_runtime_read_core = params.find<int>("diag_runtime_read_core", 0);
    c.diag_runtime_read_offset = params.find<uint64_t>("diag_runtime_read_offset", 0);
    c.diag_runtime_read_bytes = params.find<uint32_t>("diag_runtime_read_bytes", 64);

    // 通用 workload（例如 stream）下禁止 WeightLoader 写入任何权重数据，
    // 否则会覆盖通用 workload 的内存测试区域并造成误判/误崩溃。
    {
        c.workload_impl = workloadImplFromParamsOrEnv(params, /*default_impl*/"");
        if (!c.workload_impl.empty() && c.workload_impl != "snn") {
            c.enabled = false;
        }
    }

    return c;
}

}} // namespace SST::SnnDL
