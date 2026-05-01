// -*- c++ -*-
//
// ISpikeWorkload: SNN 语义 workload 的扩展接口（Phase4，方案 B）
// - 继承 ICoreWorkload，仅在“需要 SpikeEvent 输入语义”的 workload 中实现。
// - 目的：保持 stream 等通用 workload 不依赖 SpikeEvent 类型，边界更硬。
//

#pragma once

#include "ICoreWorkload.h"

namespace SST { namespace SnnDL {

class SpikeEvent;

class ISpikeWorkload : public ICoreWorkload {
public:
    ~ISpikeWorkload() override = default;
    virtual void deliverSpike(SpikeEvent* spike) = 0;
};

}} // namespace SST::SnnDL
