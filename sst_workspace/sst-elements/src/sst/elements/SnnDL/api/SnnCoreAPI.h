// -*- c++ -*-
//
// SnnCoreAPI.h: SnnPE计算核心的SubComponent接口(API)
//

#ifndef _SNNCORE_API_H
#define _SNNCORE_API_H

#include <sst/core/subcomponent.h>
#include <sst/core/params.h>
#include <sst/core/link.h>
#include <map>

#include "CoreShellAPI.h"

namespace SST {
namespace SnnDL {

class SpikeEvent;
class NocPacketEvent;
class IPeAggregation;

// Legacy API: 保持 deliverSpike(SpikeEvent*) 入口用于历史组件/调试路径。
// 严格通用核（B 方案）下，平台层应仅依赖 CoreShellAPI；SnnCoreAPI 不应被 MultiCorePE 直接引用。
class SnnCoreAPI : public SST::SnnDL::CoreShellAPI {
public:
    // 注册为可加载的SubComponent API，构造签名为 (ComponentId_t, Params&)
    SST_ELI_REGISTER_SUBCOMPONENT_API(SST::SnnDL::SnnCoreAPI)

    virtual ~SnnCoreAPI() = default;

    // 生命周期（可选覆写）
    using SubComponent::init;
    using SubComponent::setup;
    using SubComponent::finish;

    // 与父组件通信（仅汇聚接口；Spike 语义由 workload/子系统承载）
    virtual void setParentInterface(IPeAggregation* parent) override = 0;

    // Legacy 业务接口（Spike 输入）
    virtual void deliverSpike(SpikeEvent* spike) = 0;
    // deliverPacket / hasWork / utilization / statistics 由 CoreShellAPI 统一定义
    // 可选：设置内存连接，默认空实现，具体实现可覆盖
    virtual void setMemoryLink(SST::Link* /*link*/) {}
    // 步级 reset：默认不做操作，具体实现可覆盖
    virtual void resetMembraneState(float /*v_rest*/) {}
    // 手动驱动：强制当前Gather窗口结束（上层在manual_window_drive模式下触发）
    virtual void forceEndGather() {}

protected:
    // 提供构造函数以便派生类在初始化列表中正确调用
    SnnCoreAPI(SST::ComponentId_t id, SST::Params& params) : SST::SnnDL::CoreShellAPI(id, params) {}
};

} // namespace SnnDL
} // namespace SST

#endif // _SNNCORE_API_H
