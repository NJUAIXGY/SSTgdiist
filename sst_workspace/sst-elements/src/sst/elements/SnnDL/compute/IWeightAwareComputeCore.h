// -*- c++ -*-
//
// IWeightAwareComputeCore: 可选扩展接口（权重/缓存语义）
// - Phase5.4：从 ISnnComputeCore 中迁出，避免 compute core 被迫实现权重/缓存请求
// - Control 侧应优先通过 ComputeCoreContext.weight_reader 进行权重读取（由 synapse/weights 提供）
//

#pragma once

#include <cstdint>
#include <functional>

namespace SST { namespace SnnDL {

class IWeightAwareComputeCore {
public:
    virtual ~IWeightAwareComputeCore() = default;

    virtual bool requestWeight(uint32_t pre, uint32_t post,
                               const std::function<void(float)>& cb) = 0;
    virtual bool requestWeightBCSR(uint32_t pre, uint32_t post,
                                   const std::function<void(float)>& cb) = 0;
    virtual bool weightCacheTryGet(uint64_t key, float& out) const = 0;
    virtual void weightCacheStore(uint64_t key, float v) = 0;
    virtual bool resolveWeightKey(uint32_t pre_global, uint32_t post_local,
                                  uint32_t& req_pre, uint32_t& req_post,
                                  uint64_t& cache_key) const = 0;
};

}} // namespace SST::SnnDL

