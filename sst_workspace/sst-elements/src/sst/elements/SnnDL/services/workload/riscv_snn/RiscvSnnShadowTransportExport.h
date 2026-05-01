// -*- c++ -*-
//
// RiscvSnnShadowTransportExport:
// - 将 runtime_bridge shadow provider 导出的 transport 统计重新映射回 canonical snn_tx/snn_rx surface。
// - 只在 canonical key 缺失时回填，避免覆盖未来原生导出。
//

#pragma once

#include <cstdint>
#include <map>
#include <string>

namespace SST { namespace SnnDL {

void exportRiscvSnnRuntimeBridgeShadowTransportStats(std::map<std::string, uint64_t>& stats);

}} // namespace SST::SnnDL
