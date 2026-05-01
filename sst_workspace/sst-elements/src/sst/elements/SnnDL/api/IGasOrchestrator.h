// -*- c++ -*-
//
// IGasOrchestrator: GAS 阶段编排接口（供 GasPhaseController 调用）。
//
// 目的：
// - services/GasPhaseController 不再 include control/SnnPESubComponent.h；
// - 由控制层实现该接口，services 仅依赖 api/ 的窄接口。
//

#pragma once

namespace SST { namespace SnnDL {

class IGasOrchestrator {
public:
    virtual ~IGasOrchestrator() = default;

    virtual void orchestratePrepareApplyWindow() = 0;
    virtual void orchestrateApplyWindowEntry() = 0;
    virtual void orchestrateBeginApplyIssueFallback(bool strict_active) = 0;
    virtual void orchestrateBeginScatterSequence() = 0;
    virtual void orchestrateEndScatterSequence() = 0;
};

}} // namespace SST::SnnDL

