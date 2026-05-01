#ifndef SST_ELEMENTS_SNNDL_SNNWEIGHTREADER_H
#define SST_ELEMENTS_SNNDL_SNNWEIGHTREADER_H

#include <cstdint>
#include <functional>

namespace SST {
namespace SnnDL {

// 轻量权重读取接口：面向 orchestrator/核心，屏蔽 StandardMem/缓存细节。
class IWeightReader {
public:
    virtual ~IWeightReader() = default;
    virtual void requestDense(uint32_t pre, uint32_t post, std::function<void(float)> cb) = 0;
    virtual void requestBCSR(uint32_t pre_global, uint32_t post_local, std::function<void(float)> cb) = 0;
    virtual bool tryCache(uint64_t key, float& out) = 0;
    virtual void putCache(uint64_t key, float value) = 0;
};

// 适配器：包装回调，便于从现有 SnnPESubComponent 注入。
class CallbackWeightReader final : public IWeightReader {
public:
    using DenseReqFn = std::function<void(uint32_t,uint32_t,std::function<void(float)>)>;
    using BcsrReqFn  = std::function<void(uint32_t,uint32_t,std::function<void(float)>)>;
    using CacheTryFn = std::function<bool(uint64_t,float&)>;
    using CachePutFn = std::function<void(uint64_t,float)>;

    CallbackWeightReader(DenseReqFn dense_fn,
                         BcsrReqFn bcsr_fn,
                         CacheTryFn cache_try_fn,
                         CachePutFn cache_put_fn)
        : dense_fn_(std::move(dense_fn)),
          bcsr_fn_(std::move(bcsr_fn)),
          cache_try_fn_(std::move(cache_try_fn)),
          cache_put_fn_(std::move(cache_put_fn)) {}

    void requestDense(uint32_t pre, uint32_t post, std::function<void(float)> cb) override {
        if (dense_fn_) dense_fn_(pre, post, std::move(cb));
    }

    void requestBCSR(uint32_t pre_global, uint32_t post_local, std::function<void(float)> cb) override {
        if (bcsr_fn_) bcsr_fn_(pre_global, post_local, std::move(cb));
    }

    bool tryCache(uint64_t key, float& out) override {
        return cache_try_fn_ ? cache_try_fn_(key, out) : false;
    }

    void putCache(uint64_t key, float value) override {
        if (cache_put_fn_) cache_put_fn_(key, value);
    }

private:
    DenseReqFn dense_fn_;
    BcsrReqFn bcsr_fn_;
    CacheTryFn cache_try_fn_;
    CachePutFn cache_put_fn_;
};

} // namespace SnnDL
} // namespace SST

#endif // SST_ELEMENTS_SNNDL_SNNWEIGHTREADER_H
