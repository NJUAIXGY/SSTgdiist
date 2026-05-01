// -*- c++ -*-
//
// INocTransport: NoC 抽象接口（仅负责脉冲传输/注入，不包含权重/路由语义）
//

#pragma once

// size_t
#include <cstddef>

namespace SST { namespace SnnDL {

class NocPacketEvent;

class INocTransport {
public:
    virtual ~INocTransport() = default;

    // 语义：接管 packet 生命周期（与 MultiCorePE::sendSpike 语义一致）
    virtual void sendFromCore(int src_core, NocPacketEvent* packet) = 0;

    // 语义：仅在本 PE 内本地直达注入（不走 ring），接管 packet 生命周期
    virtual void injectLocal(int dst_core, NocPacketEvent* packet) = 0;

    // 语义：外发到其他 PE，接管 packet 生命周期；成功外发应计入 external_spikes_sent
    virtual void sendExternal(NocPacketEvent* packet) = 0;

    // Optional: platform quiescence hint for step-gated workloads.
    // Default returns true to preserve legacy behavior for transports
    // that do not expose internal queues.
    virtual bool isIdle() const { return true; }
};

}} // namespace SST::SnnDL
