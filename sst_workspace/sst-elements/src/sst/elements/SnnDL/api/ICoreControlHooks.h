// -*- c++ -*-
//
// ICoreControlHooks: MultiCorePE -> Core 的控制壳注入接口（窄接口）。
//
// 目的：
// - MultiCorePE 不再依赖具体 control 实现（如 SnnPESubComponent），而只依赖该接口；
// - 便于未来替换/并存不同 control 子核实现，同时保持 MultiCorePE “纯控制壳”。
//

#pragma once

#include <cstdint>
#include <vector>

namespace SST { namespace SnnDL {

class INocTransport;

class ICoreControlHooks {
public:
    virtual ~ICoreControlHooks() = default;

    // 注入 NoC 抽象接口（由 core 侧选择使用 NocSpikeTransport 或 fallback）。
    virtual void setNocTransport(INocTransport* noc) = 0;

    // 手动驱动一拍：仅用于 debug/回退路径；正常情况下 core 应由 SST clock 自动驱动。
    virtual void driveOneCycle() = 0;

    // 门控决策事件：由 MultiCorePE 从 NIC 收到后广播到所有 core（core 侧自行命中/忽略）。
    virtual void applyGatingDecision(uint32_t src_global,
                                     const std::vector<uint32_t>& dest_pes,
                                     uint64_t current_cycle,
                                     uint64_t ttl_cycles) = 0;
};

}} // namespace SST::SnnDL

