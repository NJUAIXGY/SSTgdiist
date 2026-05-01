// -*- c++ -*-
//
// IGasCmdSender: GAS 控制面命令发送接口（Control → 下游 StandardMem 前端）
// - 目的：让 control/ 不直接 new StandardMem::CustomReq，也不依赖 GasOpData/StandardMem 类型
//

#pragma once

#include <cstdint>

#include "GasOps.h"

namespace SST { namespace SnnDL {

class IGasCmdSender {
public:
    virtual ~IGasCmdSender() = default;

    // 语义：发送 GAS 控制面命令（实现侧负责将其编码为下游可理解的控制事件）。
    virtual void sendGasCmd(GasOp op,
                            uint32_t superstep,
                            uint32_t slice,
                            uint32_t total_slices,
                            bool flag = false) = 0;
};

}} // namespace SST::SnnDL

