// -*- c++ -*-
//
// WorkloadStatsRegistry:
// - 统一注册/构建 workload 统计模块，避免 MultiCorePE 继续堆叠 if/else
//

#pragma once

#include <memory>
#include <string>
#include <vector>

#include "IWorkloadStatsModule.h"

namespace SST { namespace SnnDL {

class WorkloadStatsRegistry {
public:
    using ModulePtr = std::unique_ptr<IWorkloadStatsModule>;

    static std::vector<ModulePtr> buildModules(const std::string& workload_impl,
                                               const std::string& modules_csv,
                                               std::vector<std::string>* unknown = nullptr);
};

}} // namespace SST::SnnDL

