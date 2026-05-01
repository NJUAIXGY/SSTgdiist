// -*- c++ -*-
//
// GasOps: GAS 控制面操作码（纯枚举；不依赖 StandardMem）
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

// 注意：数值需与 GatherBufferIF / GasCustomCmd 约定保持一致（历史兼容）。
enum class GasOp : uint8_t {
    BeginGather  = 1,
    EndGather    = 2,
    BeginApply   = 3,
    EndApply     = 4,
    BeginScatter = 5,
    EndScatter   = 6,
    FlushSRAM    = 7,
    SetSlice     = 8,
};

}} // namespace SST::SnnDL

