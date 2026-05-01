// -*- c++ -*-
//
// IGasCreditGate: core/control -> memory 的 Apply credit 控制窄接口。
//
// 目的：
// - 在 window/step 边界给 GatherBufferIF 下发“Apply bank credit”目标；
// - 保持 control/** 不依赖 GatherBufferIF 的具体实现（只依赖窄接口）。
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

class IGasCreditGate {
public:
    virtual ~IGasCreditGate() = default;
    virtual void setApplyBankCreditTarget(uint32_t seq, uint32_t apply_bank_credit) = 0;
};

}} // namespace SST::SnnDL

