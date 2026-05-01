// -*- c++ -*-
//
// CoreShellAPI.h: 通用 CoreShell SubComponent API（严格无 SpikeEvent）
//
// 目标（通用核）：
// - 平台层（PE/NoC/Memory）只与 packet/bytes/time 打交道；
// - Spike/Synapse/GAS/BCSR/Step 等语义全部下沉到可插拔 workload/子系统；
// - 允许未来 compute 完全不是 SNN。
//

#ifndef _CORESHELL_API_H
#define _CORESHELL_API_H

#include <sst/core/subcomponent.h>
#include <sst/core/params.h>

#include <cstdint>
#include <map>
#include <vector>

namespace SST { namespace SnnDL {

class IPeAggregation;
class NocPacketEvent;

class CoreShellAPI : public SST::SubComponent {
public:
    SST_ELI_REGISTER_SUBCOMPONENT_API(SST::SnnDL::CoreShellAPI)

    virtual ~CoreShellAPI() = default;

    using SubComponent::init;
    using SubComponent::setup;
    using SubComponent::finish;

    // 与父组件通信（仅统计/阶段事件汇聚接口；不包含 Spike/路由语义）
    virtual void setParentInterface(IPeAggregation* parent) = 0;

    // 通用 NoC packet 输入（payload-agnostic；Spike packet 由 workload 解释）
    // 返回 true 表示本 core 接管 packet 生命周期；返回 false 表示未处理、由调用方负责 delete。
    virtual bool deliverPacket(NocPacketEvent* /*packet*/) { return false; }

    // Synthetic SNN source hook:
    // - 仅供 MultiCorePE 的 isolated test traffic 使用；
    // - 默认 no-op，非 SNN workload/未实现 core 不参与该路径。
    virtual bool syntheticEmitNeuronFire(uint32_t neuron_idx, uint64_t now_cycle) {
        (void)neuron_idx;
        (void)now_cycle;
        return false;
    }
    virtual uint64_t syntheticEmitNeuronFireBatch(const std::vector<uint32_t>& neuron_indices, uint64_t now_cycle) {
        (void)neuron_indices;
        (void)now_cycle;
        return 0;
    }

    // 统计/状态接口（用于 Mesh 汇聚）
    virtual void getStatistics(std::map<std::string, uint64_t>& stats) const = 0;
    virtual bool hasWork() const = 0;
    virtual double getUtilization() const = 0;

protected:
    CoreShellAPI(SST::ComponentId_t id, SST::Params& /*params*/) : SST::SubComponent(id) {}
};

}} // namespace SST::SnnDL

#endif // _CORESHELL_API_H
