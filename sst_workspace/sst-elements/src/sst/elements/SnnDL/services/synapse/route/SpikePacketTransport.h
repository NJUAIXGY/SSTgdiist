// -*- c++ -*-
//
// SpikePacketTransport: ISpikeTransport 的 synapse/route 侧实现
// - 将 SpikeCommSubsystem 的 transport->send(SpikeEvent*) 映射为 NoC packet（NocPacketEvent）
// - 通过 SpikePacketBridge 统一承担 SpikeEvent <-> packet 的编解码（唯一适配点）
//

#pragma once

#include "ISpikeTransport.h"

#include "GlobalNeuronLayout.h"
#include "INocTransport.h"
#include "SpikePacketBridge.h"

namespace SST { namespace SnnDL {

// 注意：该 transport 属于 synapse 域实现（非 api 稳定接口），用于保持边界清晰：
// - api/ 只保留抽象接口（IMemoryAccess/INocTransport/ISpikeTransport/...）
// - SpikeEvent <-> packet 的适配由 synapse/route 侧承担
class SpikePacketTransport final : public ISpikeTransport {
public:
    SpikePacketTransport() = default;

    void setLog(SST::Output* log) { rt_.log = log; bridge_.bindRuntime(rt_); }
    void setNodeId(int node_id) { rt_.node_id = node_id; bridge_.bindRuntime(rt_); }
    void setNumCores(int num_cores) { rt_.num_cores = num_cores; bridge_.bindRuntime(rt_); }
    void setSourceCore(int src_core) { src_core_ = src_core; }
    void setNocTransport(INocTransport* noc) { rt_.noc = noc; bridge_.bindRuntime(rt_); }

    void configureLayout(uint32_t total_nodes, uint32_t cores_per_pe, uint32_t neurons_per_core) {
        layout_ = GlobalNeuronLayout(total_nodes, cores_per_pe, neurons_per_core);
        rt_.layout = &layout_;
        bridge_.bindRuntime(rt_);
    }

    void send(SpikeEvent* event) override {
        if (!event) return;
        if (!rt_.noc || !rt_.layout || !rt_.layout->valid()) {
            delete event;
            return;
        }
        bridge_.sendFromCore(src_core_, event);
    }

private:
    int src_core_ = 0;
    GlobalNeuronLayout layout_{};
    SpikePacketBridge::Runtime rt_{};
    SpikePacketBridge bridge_{};
};

}} // namespace SST::SnnDL

