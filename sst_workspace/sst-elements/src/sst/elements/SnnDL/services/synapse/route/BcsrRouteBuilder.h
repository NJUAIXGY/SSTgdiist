// -*- c++ -*-
//
// BcsrRouteBuilder:
// - 解析 BCSR meta（.meta.json）与占位符模板；
// - 从 BCSR bin 追加构建 reachability routes（pre_global -> [post_global]）。
//

#pragma once

#include <cstdint>
#include <limits>
#include <string>
#include <unordered_map>

#include "ISynapseRoute.h"
#include "SynapseRouteBuildConfig.h"

namespace SST { class Output; }

namespace SST { namespace SnnDL {

struct BcsrAppendOptions {
    uint32_t pre_begin = 0;
    uint32_t pre_end = std::numeric_limits<uint32_t>::max();
};

using RouteWeightMap = std::unordered_map<uint64_t, float>;

bool parseBcsrMetaJson(const std::string& meta_path,
                       uint32_t& rows_out, uint32_t& cols_out,
                       uint32_t& br_out, uint32_t& bc_out,
                       uint32_t& idx_bytes_out, uint32_t& val_bytes_out,
                       uint64_t& rowptr_off_out, uint64_t& colidx_off_out,
                       uint64_t& blockdata_off_out, uint64_t& blockids_off_out,
                       uint32_t& total_blocks_out);

std::string resolveBcsrTemplate(const std::string& tmpl, uint32_t pe, int core);

bool appendRoutesFromBcsrFile(const SynapseRouteBuildConfig& cfg,
                              SST::Output* out,
                              const std::string& path,
                              uint32_t pe_index,
                              int core_index,
                              uint32_t rows_hint,
                              ISynapseRoute::RouteMap& routes_out,
                              const BcsrAppendOptions& opt,
                              RouteWeightMap* route_weights_out = nullptr);

}} // namespace SST::SnnDL
