// -*- c++ -*-
//
// IGasStepGate: GAS 窗口的“Step 级门控”窄接口（core -> memory）。
//
// 目的：
// - 当启用全局 Step 同步时，GatherBufferIF 不再在 EndScatter 后自动进入下一窗口；
// - 由控制层在收到全局 START_STEP(seq) 后显式打开新窗口，以保证跨 PE 同步。
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

class IGasStepGate {
public:
    virtual ~IGasStepGate() = default;

    // 打开 seq 对应的 Gather 窗口（通常在 Stage::Idle/paused 时调用）。
    virtual void openStep(uint32_t seq) = 0;
};

}} // namespace SST::SnnDL

