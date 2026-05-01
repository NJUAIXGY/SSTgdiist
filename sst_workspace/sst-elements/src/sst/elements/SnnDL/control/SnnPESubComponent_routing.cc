// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnPESubComponent_routing.cc: 路由构建与共享缓存逻辑拆分
//

#include <sst/core/sst_config.h>

#include "SnnPESubComponent.h"
#include "api/ISnnSpikeCommWorkload.h"
#include "synapse/weights/SnnBcsrWeightManager.h"
#include "SnnDLStringUtil.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <inttypes.h>
#include <iterator>
#include <limits>
#include <sstream>

using namespace SST;
using namespace SST::SnnDL;


std::string SnnPESubComponent::resolveWeightTemplate(uint32_t pe, int core) const {
    if (weights_template_.empty()) return "";
    return resolvePeCoreTemplate(weights_template_, pe, static_cast<uint32_t>(core));
}

void SnnPESubComponent::applyGatingDecision(uint32_t src_global, const std::vector<uint32_t>& dest_pes,
                             uint64_t current_cycle, uint64_t ttl_cycles)
{
    // Phase4-Task6.3：门控决策的应用下沉到 workload=snn（synapse/route）。
    if (snn_comm_workload_) {
        snn_comm_workload_->applyGatingDecision(src_global, dest_pes, current_cycle, ttl_cycles);
    }
}
