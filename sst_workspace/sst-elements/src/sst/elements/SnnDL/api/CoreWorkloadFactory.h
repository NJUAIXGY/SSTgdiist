// -*- c++ -*-
//
// CoreWorkloadFactory: 创建 workload 插件（Phase6/Phase3）
//

#pragma once

#include <memory>
#include <string>

namespace SST { namespace SnnDL {

class ICoreWorkload;

// Returns nullptr if name unknown.
std::unique_ptr<ICoreWorkload> createWorkloadByName(const std::string& name);

}} // namespace SST::SnnDL

