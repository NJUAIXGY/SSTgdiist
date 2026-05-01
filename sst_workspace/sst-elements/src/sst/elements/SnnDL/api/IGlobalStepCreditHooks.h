// -*- c++ -*-
//
// IGlobalStepCreditHooks: PE -> core 的全局 Step credit 配置钩子接口（窄接口）。
//
// 目的：
// - GlobalGasStepController 可在 START_STEP(seq) 时为每个 PE 下发控制面参数（例如 Apply bank credit 目标值）；
// - MultiCorePE 在 beginGlobalStep_(seq) 前把该参数广播到本地 cores；
// - core 再把该信息传给 memory(GatherBufferIF) 以影响下一窗口的 Apply 并发。
//

#pragma once

#include <cstdint>

namespace SST { namespace SnnDL {

class IGlobalStepCreditHooks {
public:
    virtual ~IGlobalStepCreditHooks() = default;
    virtual void onGlobalStepApplyBankCredit(uint32_t seq, uint32_t apply_bank_credit) = 0;
};

}} // namespace SST::SnnDL

