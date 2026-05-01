// -*- c++ -*-
//
// StageEventHub: GAS阶段事件调度与统计汇报助手

#pragma once

// ⚠️ Legacy reference only (Phase5.2-A1):
// StageEventHub 已被吸收进 `control/SnnPESubComponent_impl.h` 的 `SnnPESubComponent::Impl`。
// 本文件迁入 `services/legacy/`，用于保留历史实现思路与旧日志口径；不参与主链路构建。
//
// 注意：该 legacy 版本可能无法直接在当前主线编译（已移除对 SnnPESubComponent 私有成员的 friend 访问）。

#include <cstdint>

namespace SST { namespace SnnDL {

class SnnPESubComponent;

struct StageEventHub {
    SnnPESubComponent* core = nullptr;
    uint64_t t_begin_gather = 0;
    uint64_t t_begin_apply = 0;
    uint64_t t_begin_scatter = 0;
    bool have_begin_gather = false;
    bool have_begin_apply = false;
    bool have_begin_scatter = false;

    void init(SnnPESubComponent* owner) { core = owner; }
    void markBeginGather(uint32_t seq);
    void markBeginApply(uint32_t seq);
    void markBeginScatter(uint32_t seq);
    void markEndScatter(uint32_t seq, uint64_t spikes_emitted);
};

}} // namespace SST::SnnDL
