// -*- c++ -*-
//
// WorkloadConfig: 统一的 workload 选择入口（集中读取环境变量并缓存）
// - 仅用于“保持脚本不改”的 Phase6 兼容路径
// - 读一次 env，后续 O(1) 查询，避免在热路径重复 getenv/strcmp
//

#pragma once

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>

#include <sst/core/params.h>

#include "SnnDLStringUtil.h"

namespace SST { namespace SnnDL {

inline uint64_t clampNonZeroU64(uint64_t v) { return v ? v : 1ull; }

// Workload 分类（供 PE/CoreShell 做策略选择，避免散落的 string if/else 堆叠）。
enum class WorkloadKind : uint8_t {
    Snn = 0,
    RiscvSnn = 1,
    Stream = 2,
    Traffic = 3,
    TrafficMem = 4,
    Tensor = 5,
};

inline WorkloadKind workloadKindFromString(const std::string& impl) {
    const std::string w = toLowerCopy(std::string(impl));
    if (w == "riscv_snn") return WorkloadKind::RiscvSnn;
    if (w == "stream") return WorkloadKind::Stream;
    if (w == "traffic") return WorkloadKind::Traffic;
    if (w == "traffic_mem") return WorkloadKind::TrafficMem;
    if (w == "tensor") return WorkloadKind::Tensor;
    return WorkloadKind::Snn;
}

inline const char* workloadKindName(WorkloadKind k) {
    switch (k) {
        case WorkloadKind::Snn: return "snn";
        case WorkloadKind::RiscvSnn: return "riscv_snn";
        case WorkloadKind::Stream: return "stream";
        case WorkloadKind::Traffic: return "traffic";
        case WorkloadKind::TrafficMem: return "traffic_mem";
        case WorkloadKind::Tensor: return "tensor";
        default: return "snn";
    }
}

inline bool isNonSnnWorkloadKind(WorkloadKind k) {
    return k != WorkloadKind::Snn;
}

// `riscv_snn` still needs SNN-style stimulus injection when it fronts a shadow/runtime
// datapath. Keep this narrower than "is SNN-like" so other feature gates can stay strict.
inline bool workloadAllowsSnnStimulus(WorkloadKind k) {
    return k == WorkloadKind::Snn || k == WorkloadKind::RiscvSnn;
}

// Pure SNN datapath features stay reserved for the native `snn` workload. Experimental
// control-plane workloads such as `riscv_snn` may share stimulus semantics without inheriting
// DMA/local-storage/pulse infrastructure by accident.
inline bool workloadAllowsPureSnnDatapathFeatures(WorkloadKind k) {
    return k == WorkloadKind::Snn;
}

inline const char* workloadImplFromEnvCached() {
    static const char* cached = []() -> const char* {
        const char* v = std::getenv("SNNDL_WORKLOAD_IMPL");
        if (!v || !*v) return nullptr;
        return v;
    }();
    return cached;
}

inline std::string workloadImplFromParamsOrEnv(const SST::Params& params, const std::string& default_impl = "snn") {
    std::string w = params.find<std::string>("workload_impl", "");
    if (w.empty()) {
        if (const char* env = workloadImplFromEnvCached()) w = std::string(env);
    }
    w = toLowerCopy(std::move(w));
    if (w.empty()) w = default_impl;
    return w;
}

// Compatibility path: env overrides params when SNNDL_WORKLOAD_IMPL is set.
// Use this only where legacy scripts relied on global env to switch workload_impl without editing configs.
inline std::string workloadImplFromParamsOrEnvOverride(const SST::Params& params, const std::string& default_impl = "snn") {
    std::string w = params.find<std::string>("workload_impl", default_impl);
    if (const char* env = workloadImplFromEnvCached()) w = std::string(env);
    w = toLowerCopy(std::move(w));
    if (w.empty()) w = default_impl;
    return w;
}

inline std::string execModeFromParams(const SST::Params& params, const std::string& default_mode = "gas") {
    std::string e = params.find<std::string>("exec_mode", "");
    e = toLowerCopy(std::move(e));
    if (e == "naive_opt") e = "naive_raw";
    if (e.empty()) e = default_mode;
    return e;
}

inline bool isStreamWorkloadEnv() {
    const char* v = workloadImplFromEnvCached();
    if (!v || !*v) return false;
    return toLowerCopy(std::string(v)) == "stream";
}

}} // namespace SST::SnnDL
