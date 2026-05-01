// -*- c++ -*-
//
// ISpikeTransport: 抽象脉冲传输层，屏蔽父组件/NIC/MPI等具体实现。
//

#pragma once

#include "events/SpikeEvent.h"

namespace SST { namespace SnnDL {

class ISpikeTransport {
public:
    virtual ~ISpikeTransport() = default;
    // 语义：接管 SpikeEvent 生命周期（与 parent_->sendSpike 一致）
    virtual void send(SpikeEvent* event) = 0;
};

}} // namespace SST::SnnDL
