// -*- c++ -*-
//
// ISnnSpikeCommWorkload:
// - workload=snn 的“通信窄接口”（Phase4 Task6.3）
// - 目的：CoreShell 不再直接持有 Synapse/Route/SpikeComm 的实现对象，只通过该接口触发：
//   - gating decision 下发
//   - neuron fire 的批量发送
//
// 说明：
// - 该接口只用于 SNN workload；stream 等通用 workload 不需要实现。
// - 该接口不暴露 SpikeEvent 类型，避免把事件语义拉回到 CoreShell。
//

#pragma once

#include <cstdint>
#include <vector>

namespace SST { namespace SnnDL {

class ISnnSpikeCommWorkload {
public:
    virtual ~ISnnSpikeCommWorkload() = default;

    virtual void applyGatingDecision(uint32_t src_global,
                                     const std::vector<uint32_t>& dest_pes,
                                     uint64_t current_cycle,
                                     uint64_t ttl_cycles) = 0;

    // 单条发放（热路径避免构造 vector）。
    virtual void emitNeuronFire(uint32_t neuron_idx, uint64_t now_cycle) = 0;

    // 批量发放：返回实际发送条数（通常等于 neuron_indices.size()）。
    virtual uint64_t emitNeuronFireBatch(const std::vector<uint32_t>& neuron_indices, uint64_t now_cycle) = 0;

    virtual bool ready() const = 0;
};

}} // namespace SST::SnnDL

