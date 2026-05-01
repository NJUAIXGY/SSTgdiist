// -*- c++ -*-
//
// BcsrRouteBuilder implementation
//

#include "synapse/route/BcsrRouteBuilder.h"

#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <limits>
#include <sstream>
#include <vector>

#include <sst/core/output.h>

#include "synapse/common/BcsrMeta.h"
#include "SnnDLStringUtil.h"

namespace SST { namespace SnnDL {

namespace {

constexpr uint32_t kBcsrSentinelId = 0xFFFFFFFFu;

inline void maybeStoreEdgeWeight(RouteWeightMap* route_weights_out,
                                 uint32_t pre_global,
                                 uint32_t post_global,
                                 float weight) {
    if (!route_weights_out) return;
    const uint64_t key =
        (static_cast<uint64_t>(pre_global) << 32) | static_cast<uint64_t>(post_global);
    auto it = route_weights_out->find(key);
    if (it == route_weights_out->end()) {
        (*route_weights_out)[key] = weight;
        return;
    }
    if (std::fabs(weight) > std::fabs(it->second)) {
        it->second = weight;
    }
}

} // namespace

bool parseBcsrMetaJson(const std::string& meta_path,
                       uint32_t& rows_out, uint32_t& cols_out,
                       uint32_t& br_out, uint32_t& bc_out,
                       uint32_t& idx_bytes_out, uint32_t& val_bytes_out,
                       uint64_t& rowptr_off_out, uint64_t& colidx_off_out,
                       uint64_t& blockdata_off_out, uint64_t& blockids_off_out,
                       uint32_t& total_blocks_out) {
    BcsrMeta meta{};
    if (!parseBcsrMetaJsonFile(meta_path, meta)) return false;
    rows_out = meta.rows;
    cols_out = meta.cols;
    br_out = meta.br;
    bc_out = meta.bc;
    idx_bytes_out = meta.idx_bytes;
    val_bytes_out = meta.val_bytes;
    rowptr_off_out = meta.rowptr_offset;
    colidx_off_out = meta.colidx_offset;
    blockdata_off_out = meta.blockdata_offset;
    blockids_off_out = meta.blockids_offset;
    total_blocks_out = meta.total_blocks;
    return true;
}

std::string resolveBcsrTemplate(const std::string& tmpl, uint32_t pe, int core) {
    if (tmpl.empty()) return "";
    return resolvePeCoreTemplate(tmpl, pe, static_cast<uint32_t>(core));
}

bool appendRoutesFromBcsrFile(const SynapseRouteBuildConfig& cfg,
                              SST::Output* out,
                              const std::string& path,
                              uint32_t pe_index,
                              int core_index,
                              uint32_t rows_hint,
                              ISynapseRoute::RouteMap& routes_out,
                              const BcsrAppendOptions& opt,
                              RouteWeightMap* route_weights_out) {
    uint32_t rows = rows_hint;
    uint32_t cols = cfg.cols;
    uint32_t br = cfg.bcsr_br ? cfg.bcsr_br : 16;
    uint32_t bc = cfg.bcsr_bc ? cfg.bcsr_bc : 16;
    uint32_t idx_bytes = cfg.bcsr_idx_bytes ? cfg.bcsr_idx_bytes : 2;
    uint32_t val_bytes = cfg.bcsr_val_bytes ? cfg.bcsr_val_bytes : 4;
    uint64_t rowptr_off = (cfg.bcsr_rowptr_addr > cfg.base_addr) ? (cfg.bcsr_rowptr_addr - cfg.base_addr) : 0;
    uint64_t colidx_off = (cfg.bcsr_colidx_addr > cfg.base_addr) ? (cfg.bcsr_colidx_addr - cfg.base_addr) : 0;
    uint64_t blockdata_off = (cfg.bcsr_blockdata_addr > cfg.base_addr) ? (cfg.bcsr_blockdata_addr - cfg.base_addr) : 0;
    uint64_t blockids_off = (cfg.bcsr_blockids_addr > cfg.base_addr) ? (cfg.bcsr_blockids_addr - cfg.base_addr) : 0;
    uint32_t total_blocks = 0;
    std::string layout_mode;
    uint32_t colidx_row_stride_bytes = 0;
    uint32_t blockdata_row_stride_bytes = 0;
    uint32_t blockids_row_stride_bytes = 0;

    // 注意：同一目录下不同 core 的 total_blocks 可能不同，导致 blockdata/blockids 的 offset 随文件变化。
    // 因此对于“读文件构建路由”的路径：优先使用每个文件自身的 .meta.json offsets/total_blocks，
    // 以避免使用“全局固定 offset”造成错位读取（会导致 Step reachability 随 run/布局漂移）。
    const std::string meta_path = path + ".meta.json";
    BcsrMeta meta{};
    if (parseBcsrMetaJsonFile(meta_path, meta)) {
        if (rows == 0 && meta.rows) rows = meta.rows;
        if (cols == 0 && meta.cols) cols = meta.cols;
        if (!cfg.bcsr_br && meta.br) br = meta.br;
        if (!cfg.bcsr_bc && meta.bc) bc = meta.bc;
        if (!cfg.bcsr_idx_bytes && meta.idx_bytes) idx_bytes = meta.idx_bytes;
        if (!cfg.bcsr_val_bytes && meta.val_bytes) val_bytes = meta.val_bytes;
        // offsets/blocks：使用 per-file meta（否则在 total_blocks 波动时会错位）
        rowptr_off = meta.rowptr_offset;
        colidx_off = meta.colidx_offset;
        blockdata_off = meta.blockdata_offset;
        blockids_off = meta.blockids_offset;
        if (meta.total_blocks) total_blocks = meta.total_blocks;
        layout_mode = meta.layout_mode;
        colidx_row_stride_bytes = meta.colidx_row_stride_bytes;
        blockdata_row_stride_bytes = meta.blockdata_row_stride_bytes;
        blockids_row_stride_bytes = meta.blockids_row_stride_bytes;
    } else {
        total_blocks = 0;
    }
    if (layout_mode.empty()) layout_mode = "flat";
    if (rows == 0 || cols == 0) {
        if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 元数据缺失 rows/cols %s\n", path.c_str());
        return false;
    }
    if (idx_bytes != 2 && idx_bytes != 4) {
        if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: idx_bytes=%u 不受支持 %s\n", idx_bytes, path.c_str());
        return false;
    }
    if (val_bytes != 4) {
        if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: val_bytes=%u 不受支持 %s\n", val_bytes, path.c_str());
        return false;
    }
    const uint32_t n_block_rows = (rows + br - 1) / br;
    const uint64_t neurons_per_pe =
        (cfg.neurons_per_pe > 0)
            ? static_cast<uint64_t>(cfg.neurons_per_pe)
            : (cfg.cores_per_pe > 0 ? static_cast<uint64_t>(cfg.cores_per_pe) * static_cast<uint64_t>(rows)
                                    : static_cast<uint64_t>(rows));
    const uint64_t core_offset_global = (core_index > 0) ? static_cast<uint64_t>(core_index) * static_cast<uint64_t>(rows) : 0ULL;
    std::ifstream fin(path, std::ios::binary);
    if (!fin.good()) {
        if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 无法读取 %s\n", path.c_str());
        return false;
    }
    // 读取前做一次 offsets/size 校验，尽早发现 meta 漂移/文件不匹配（避免静默构建空 routes）
    fin.seekg(0, std::ios::end);
    const std::streamoff file_size_off = fin.tellg();
    fin.clear();
    fin.seekg(0, std::ios::beg);
    const uint64_t file_size = (file_size_off > 0) ? static_cast<uint64_t>(file_size_off) : 0ULL;
    if (file_size == 0) {
        if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 文件尺寸异常 %s\n", path.c_str());
        return false;
    }
    // blockids 仅作为“有效位/哨兵”使用：若文件不包含完整 blockids 区域，则将其视为 absent。
    if (blockids_off > 0 && total_blocks > 0) {
        const uint64_t need_blockids =
            static_cast<uint64_t>(total_blocks) * static_cast<uint64_t>(br) * static_cast<uint64_t>(bc) * sizeof(uint32_t);
        if (blockids_off + need_blockids > file_size) {
            if (out) out->verbose(CALL_INFO, 1, 0,
                                  "⚠️ BCSR路由: blockids区间超出文件，视为 absent: off=0x%llx need=%llu fsize=%llu path=%s\n",
                                  (unsigned long long)blockids_off,
                                  (unsigned long long)need_blockids,
                                  (unsigned long long)file_size,
                                  path.c_str());
            blockids_off = 0;
        }
    }
    {
        BcsrMeta meta_for_check{};
        meta_for_check.br = br;
        meta_for_check.bc = bc;
        meta_for_check.idx_bytes = idx_bytes;
        meta_for_check.val_bytes = val_bytes;
        meta_for_check.rowptr_offset = rowptr_off;
        meta_for_check.colidx_offset = colidx_off;
        meta_for_check.blockdata_offset = blockdata_off;
        meta_for_check.blockids_offset = blockids_off;
        meta_for_check.total_blocks = total_blocks;
        meta_for_check.layout_mode = layout_mode;
        meta_for_check.colidx_row_stride_bytes = colidx_row_stride_bytes;
        meta_for_check.blockdata_row_stride_bytes = blockdata_row_stride_bytes;
        meta_for_check.blockids_row_stride_bytes = blockids_row_stride_bytes;
        std::string err;
        if (!validateBcsrMetaAgainstFile(meta_for_check, file_size, rows, &err)) {
            if (out) out->verbose(CALL_INFO, 0, 0,
                                  "⚠️ BCSR路由: offsets/size mismatch (%s) path=%s fsize=%llu\n",
                                  err.c_str(), path.c_str(), (unsigned long long)file_size);
            return false;
        }
    }
    fin.seekg(static_cast<std::streamoff>(rowptr_off), std::ios::beg);
    std::vector<uint32_t> rowptr(n_block_rows + 1, 0);
    fin.read(reinterpret_cast<char*>(rowptr.data()), rowptr.size() * sizeof(uint32_t));
    if (!fin.good()) {
        if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 读取rowptr失败 %s\n", path.c_str());
        return false;
    }
    uint32_t derived_blocks = rowptr.back();
    if (total_blocks == 0) total_blocks = derived_blocks;

    const bool rowpack_v1 =
        (layout_mode == "rowpack_v1") &&
        (colidx_row_stride_bytes >= (idx_bytes ? idx_bytes : 2)) &&
        (blockdata_row_stride_bytes > 0);

    std::vector<uint32_t> block_cols;
    if (!rowpack_v1) {
        block_cols.assign(total_blocks, 0u);
        fin.seekg(static_cast<std::streamoff>(colidx_off), std::ios::beg);
        if (idx_bytes == 2) {
            std::vector<uint16_t> tmp(total_blocks, 0);
            fin.read(reinterpret_cast<char*>(tmp.data()), tmp.size() * sizeof(uint16_t));
            if (!fin.good()) {
                if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 读取colidx失败 %s\n", path.c_str());
                return false;
            }
            for (uint32_t i = 0; i < total_blocks; ++i) block_cols[i] = tmp[i];
        } else {
            fin.read(reinterpret_cast<char*>(block_cols.data()), block_cols.size() * sizeof(uint32_t));
            if (!fin.good()) {
                if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 读取colidx失败 %s\n", path.c_str());
                return false;
            }
        }
    }
    std::ifstream fdata(path, std::ios::binary);
    std::ifstream fids(path, std::ios::binary);
    fdata.seekg(static_cast<std::streamoff>(blockdata_off), std::ios::beg);
    if (blockids_off > 0) {
        fids.seekg(static_cast<std::streamoff>(blockids_off), std::ios::beg);
    }
    const size_t floats_per_block = static_cast<size_t>(br) * static_cast<size_t>(bc);
    std::vector<float> blockdata(floats_per_block, 0.0f);
    std::vector<uint32_t> blockids(floats_per_block, kBcsrSentinelId);
    const uint64_t total_global_neurons =
        static_cast<uint64_t>(cfg.total_nodes) * (neurons_per_pe > 0 ? neurons_per_pe : 1ULL);
    if (rowpack_v1) {
        // rowpack_v1 layout:
        // - colidx/blockdata are stored per block_row with fixed row strides (padding included).
        // - blockids remains in legacy flat layout (generator contract), so we read it sequentially.
        for (uint32_t block_row = 0; block_row < n_block_rows; ++block_row) {
            uint32_t begin = rowptr[block_row];
            uint32_t end = rowptr[block_row + 1];
            const uint32_t row_blocks = (end > begin) ? (end - begin) : 0;
            if (row_blocks == 0) continue;

            // Load row colidx (only the used prefix; ignore padding).
            std::vector<uint32_t> row_cols(row_blocks, 0u);
            fin.seekg(static_cast<std::streamoff>(colidx_off + static_cast<uint64_t>(block_row) * colidx_row_stride_bytes),
                      std::ios::beg);
            if (idx_bytes == 2) {
                std::vector<uint16_t> tmp(row_blocks, 0);
                fin.read(reinterpret_cast<char*>(tmp.data()), tmp.size() * sizeof(uint16_t));
                if (!fin.good()) {
                    if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 读取rowpack colidx失败 %s\n", path.c_str());
                    return false;
                }
                for (uint32_t i = 0; i < row_blocks; ++i) row_cols[i] = tmp[i];
            } else {
                fin.read(reinterpret_cast<char*>(row_cols.data()), row_cols.size() * sizeof(uint32_t));
                if (!fin.good()) {
                    if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 读取rowpack colidx失败 %s\n", path.c_str());
                    return false;
                }
            }

            // Load row blockdata prefix (ignore padding).
            fdata.seekg(static_cast<std::streamoff>(blockdata_off + static_cast<uint64_t>(block_row) * blockdata_row_stride_bytes),
                        std::ios::beg);
            for (uint32_t idx_in_row = 0; idx_in_row < row_blocks; ++idx_in_row) {
                const uint32_t block_col = row_cols[idx_in_row];
                fdata.read(reinterpret_cast<char*>(blockdata.data()), blockdata.size() * sizeof(float));
                if (blockids_off > 0) {
                    fids.read(reinterpret_cast<char*>(blockids.data()), blockids.size() * sizeof(uint32_t));
                }
                if (!fdata.good() || (blockids_off > 0 && !fids.good())) {
                    if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 读取rowpack block失败 %s\n", path.c_str());
                    return false;
                }
                for (uint32_t rr = 0; rr < br; ++rr) {
                    uint32_t post_local = block_row * br + rr;
                    if (post_local >= rows) continue;
                    for (uint32_t cc = 0; cc < bc; ++cc) {
                        size_t off = static_cast<size_t>(rr) * bc + cc;
                        float weight = blockdata[off];
                        if (std::fabs(weight) <= cfg.routing_epsilon) continue;
                        if (blockids_off > 0 && blockids[off] == kBcsrSentinelId) continue;
                        const uint64_t post_global_64 =
                            static_cast<uint64_t>(pe_index) * neurons_per_pe + core_offset_global + static_cast<uint64_t>(post_local);
                        if (post_global_64 >= total_global_neurons) continue;
                        const uint32_t post_global = static_cast<uint32_t>(post_global_64);
                        uint32_t pre_global = block_col * bc + cc;
                        if (pre_global >= cols) continue;
                        if (pre_global < opt.pre_begin || pre_global >= opt.pre_end) continue;
                        routes_out[pre_global].push_back(post_global);
                        maybeStoreEdgeWeight(route_weights_out, pre_global, post_global, weight);
                    }
                }
            }
        }
    } else {
        uint64_t block_counter = 0;
        for (uint32_t block_row = 0; block_row < n_block_rows; ++block_row) {
            uint32_t begin = rowptr[block_row];
            uint32_t end = rowptr[block_row + 1];
            for (uint32_t idx = begin; idx < end; ++idx, ++block_counter) {
                if (block_counter >= block_cols.size()) break;
                uint32_t block_col = block_cols[idx];
                fdata.read(reinterpret_cast<char*>(blockdata.data()), blockdata.size() * sizeof(float));
                if (blockids_off > 0) {
                    fids.read(reinterpret_cast<char*>(blockids.data()), blockids.size() * sizeof(uint32_t));
                }
                if (!fdata.good() || (blockids_off > 0 && !fids.good())) {
                    if (out) out->verbose(CALL_INFO, 0, 0, "⚠️ BCSR路由: 读取block数据失败 %s\n", path.c_str());
                    return false;
                }
                for (uint32_t rr = 0; rr < br; ++rr) {
                    uint32_t post_local = block_row * br + rr;
                    if (post_local >= rows) continue;
                    for (uint32_t cc = 0; cc < bc; ++cc) {
                        size_t off = static_cast<size_t>(rr) * bc + cc;
                        float weight = blockdata[off];
                        if (std::fabs(weight) <= cfg.routing_epsilon) continue;
                        // 重要语义：
                        // - blockids 仅作为有效位/哨兵（0xFFFFFFFF 表示无边），不能作为 post_global。
                        // - post_global 必须由 (pe, core, post_local) 计算，保证与 WeightMemorySubsystem 的寻址/落盘口径一致。
                        if (blockids_off > 0 && blockids[off] == kBcsrSentinelId) continue;
                        const uint64_t post_global_64 =
                            static_cast<uint64_t>(pe_index) * neurons_per_pe + core_offset_global + static_cast<uint64_t>(post_local);
                        if (post_global_64 >= total_global_neurons) continue;
                        const uint32_t post_global = static_cast<uint32_t>(post_global_64);
                        uint32_t pre_global = block_col * bc + cc;
                        if (pre_global >= cols) continue;
                        if (pre_global < opt.pre_begin || pre_global >= opt.pre_end) continue;
                        routes_out[pre_global].push_back(post_global);
                        maybeStoreEdgeWeight(route_weights_out, pre_global, post_global, weight);
                    }
                }
            }
        }
    }
    return true;
}

}} // namespace SST::SnnDL
