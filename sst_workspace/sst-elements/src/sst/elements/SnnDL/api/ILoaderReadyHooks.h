// -*- c++ -*-
//
// ILoaderReadyHooks: PE -> core 的权重就绪通知接口（窄接口）。
//
// 目的：
// - loader_done_key 的 SharedArray 在 MPI 多 rank 下运行期不可见且禁止运行期写入；
// - WeightLoader 通过控制面事件通知 MultiCorePE 后，MultiCorePE 再把“就绪”下发到本地 cores，
//   使 core 侧 ensureLoaderReady_ 可以仅依赖本地 latch（不依赖 SharedArray 一致性）。
//

#pragma once

namespace SST { namespace SnnDL {

class ILoaderReadyHooks {
public:
    virtual ~ILoaderReadyHooks() = default;
    virtual void onLoaderReady() = 0;
};

}} // namespace SST::SnnDL

