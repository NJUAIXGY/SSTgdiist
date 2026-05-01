// -*- c++ -*-
//
// IManualWindowDrive: 控制层用于“手动窗口驱动”的窄接口（避免 control 反向依赖具体 components 实现）。
//

#pragma once

namespace SST { namespace SnnDL {

class IManualWindowDrive {
public:
    virtual ~IManualWindowDrive() = default;
    virtual void manualWindowTick() = 0;
};

}} // namespace SST::SnnDL

