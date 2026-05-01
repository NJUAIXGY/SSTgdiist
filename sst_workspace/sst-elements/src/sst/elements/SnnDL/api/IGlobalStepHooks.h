// -*- c++ -*-
//
// IGlobalStepHooks: MultiCorePE -> core 的全局 Step 同步钩子接口（窄接口）。
//
// 目的：
// - MultiCorePE 在收到 GlobalGasStepController 的 START_STEP(seq) 后，向所有 core 广播；
// - core 侧通过 IGasStepGate 打开 GatherBufferIF 的新窗口；
// - 保持 MultiCorePE 与具体 control 实现（SnnPESubComponent）解耦。
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

class IGlobalStepHooks {
public:
    virtual ~IGlobalStepHooks() = default;
    virtual void onGlobalStepStart(uint32_t seq) = 0;
};

}} // namespace SST::SnnDL

