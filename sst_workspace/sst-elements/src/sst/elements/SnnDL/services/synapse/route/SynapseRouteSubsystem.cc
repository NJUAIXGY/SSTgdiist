// -*- c++ -*-
//
// SynapseRouteSubsystem: 权重驱动路由构建 + 进程级共享缓存
//

#include "SynapseRouteSubsystem.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <inttypes.h>
#include <iterator>
#include <limits>
#include <sstream>
#include <unordered_set>

#include <sst/core/output.h>
#include <sst/core/statapi/stataccumulator.h>

#include "synapse/route/BcsrRouteBuilder.h"
#include "SnnDLStringUtil.h"

namespace SST { namespace SnnDL {

// Process-wide shared route cache (avoid per-core route table duplication).
std::mutex SynapseRouteSubsystem::s_route_cache_mtx_;
std::unordered_map<std::string, std::weak_ptr<const SynapseRouteSubsystem::RouteMap>> SynapseRouteSubsystem::s_route_cache_;
std::mutex SynapseRouteSubsystem::s_route_weight_cache_mtx_;
std::unordered_map<std::string, std::weak_ptr<const SynapseRouteSubsystem::RouteWeightMap>> SynapseRouteSubsystem::s_route_weight_cache_;

std::mutex SynapseRouteSubsystem::s_multicast_cache_mtx_;
std::unordered_map<std::string, std::weak_ptr<const SynapseRouteSubsystem::MulticastTargetMap>> SynapseRouteSubsystem::s_multicast_cache_;

namespace {

uint32_t layerIdFromPe_(uint32_t pe) {
    // 固定4x4网格层划分：I:0-3, H1:4-7, H2:8-11, O:12-15
    if (pe <= 3) return 0;
    if (pe <= 7) return 1;
    if (pe <= 11) return 2;
    return 3;
}

enum class IngressPolicy : uint8_t {
    TopLeft = 0,
    TopRight = 1,
    BottomLeft = 2,
    BottomRight = 3,
    Hash4 = 4,
};

bool parseIngressPolicy_(const std::string& s, IngressPolicy& out) {
    if (s == "top_left") { out = IngressPolicy::TopLeft; return true; }
    if (s == "top_right") { out = IngressPolicy::TopRight; return true; }
    if (s == "bottom_left") { out = IngressPolicy::BottomLeft; return true; }
    if (s == "bottom_right") { out = IngressPolicy::BottomRight; return true; }
    if (s == "hash4") { out = IngressPolicy::Hash4; return true; }
    return false;
}

std::string sourcePrimaryKindFromCfg_(const SynapseRouteBuildConfig& cfg) {
    const bool edges_csv_bootstrap =
        cfg.mapping_mode == "edges_csv" && !cfg.mapping_edges_file.empty();
    const bool legacy_route_tables_bootstrap =
        !edges_csv_bootstrap && (!cfg.weights_template.empty() || cfg.real_synapse_inputs_available);
    if (edges_csv_bootstrap) return "edges_csv_bootstrap";
    if (legacy_route_tables_bootstrap && cfg.real_synapse_inputs_available) {
        return "legacy_route_tables_with_real_synapse_inputs";
    }
    if (legacy_route_tables_bootstrap) return "legacy_route_tables_bootstrap";
    if (cfg.real_synapse_inputs_available) return "real_synapse_inputs_only";
    return "legacy_only";
}

inline bool parseU32CsvField_(std::string tok, uint32_t& out) {
    size_t b = 0;
    while (b < tok.size() && std::isspace(static_cast<unsigned char>(tok[b]))) ++b;
    size_t e = tok.size();
    while (e > b && std::isspace(static_cast<unsigned char>(tok[e - 1]))) --e;
    tok = tok.substr(b, e - b);
    if (tok.empty()) return false;
    try {
        size_t pos = 0;
        const unsigned long long v = std::stoull(tok, &pos, 10);
        if (pos != tok.size()) return false;
        if (v > static_cast<unsigned long long>(std::numeric_limits<uint32_t>::max())) return false;
        out = static_cast<uint32_t>(v);
        return true;
    } catch (...) {
        return false;
    }
}

inline uint32_t selectIngressNodeBlocked_(IngressPolicy policy,
                                         uint32_t pre_global,
                                         uint32_t block_id,
                                         uint32_t block_x0,
                                         uint32_t block_y0,
                                         uint32_t block_w,
                                         uint32_t block_h,
                                         uint32_t mesh_w) {
    if (block_w == 0 || block_h == 0) return block_y0 * mesh_w + block_x0;
    uint32_t lx = 0;
    uint32_t ly = 0;
    switch (policy) {
    case IngressPolicy::TopLeft:
        lx = 0; ly = 0;
        break;
    case IngressPolicy::TopRight:
        lx = block_w - 1; ly = 0;
        break;
    case IngressPolicy::BottomLeft:
        lx = 0; ly = block_h - 1;
        break;
    case IngressPolicy::BottomRight:
        lx = block_w - 1; ly = block_h - 1;
        break;
    case IngressPolicy::Hash4: {
        const uint32_t cells = block_w * block_h;
        if (cells == 0) {
            lx = 0; ly = 0;
            break;
        }
        const uint32_t pick = (pre_global ^ (block_id * 0x9e3779b9u));
        const uint32_t idx = (cells ? (pick % cells) : 0u);
        lx = idx % block_w;
        ly = idx / block_w;
        break;
    }
    default:
        lx = 0; ly = 0;
        break;
    }
    return (block_y0 + ly) * mesh_w + (block_x0 + lx);
}

inline uint32_t blockBaseNodeFromId_(uint32_t block_id,
                                     uint32_t mesh_w,
                                     uint32_t block_w,
                                     uint32_t block_h) {
    if (mesh_w == 0 || block_w == 0 || block_h == 0) return 0;
    const uint32_t blocks_w = mesh_w / block_w;
    const uint32_t bx0 = (block_id % blocks_w) * block_w;
    const uint32_t by0 = (block_id / blocks_w) * block_h;
    return by0 * mesh_w + bx0;
}

void parseLayerMask_(const std::string& mask_in,
                     std::unordered_set<uint32_t>& allowed_edges,
                     bool& allow_all_layers) {
    allowed_edges.clear();
    allow_all_layers = true;
    if (mask_in.empty()) return;

    allow_all_layers = false;
    std::string mask = mask_in;
    for (auto& ch : mask) ch = (char)std::toupper((unsigned char)ch);

    std::vector<std::string> toks;
    size_t start = 0;
    for (size_t i = 0; i <= mask.size(); ++i) {
        if (i == mask.size() || mask[i] == ',' || mask[i] == ';') {
            if (i > start) toks.emplace_back(mask.substr(start, i - start));
            start = i + 1;
        }
    }

    auto layerId = [](const std::string& s)->int{
        if (s == "I") return 0;
        if (s == "H1") return 1;
        if (s == "H2") return 2;
        if (s == "O") return 3;
        return -1;
    };

    for (auto& t : toks) {
        size_t p = t.find('>');
        if (p == std::string::npos) continue;
        std::string a = t.substr(0, p);
        std::string b = t.substr(p + 1);
        int la = layerId(a);
        int lb = layerId(b);
        if (la >= 0 && lb >= 0) {
            uint32_t key = ((uint32_t)la << 8) | (uint32_t)lb;
            allowed_edges.insert(key);
        }
    }
}

std::string buildRouteCacheKey_(const SynapseRouteBuildConfig& cfg) {
    std::ostringstream oss;
    oss << "routes-v1"
        << "-rows" << cfg.rows
        << "-cols" << cfg.cols
        << "-total_nodes" << cfg.total_nodes
        << "-cores_per_pe" << cfg.cores_per_pe
        << "-neurons_per_pe" << cfg.neurons_per_pe
        << "-idxmode" << (cfg.use_post_row_pre_col ? "post_row_pre_col" : "pre_row_post_col")
        << "-template" << cfg.weights_template
        << "-bcsr_br" << cfg.bcsr_br
        << "-bcsr_bc" << cfg.bcsr_bc
        << "-bcsr_ib" << cfg.bcsr_idx_bytes
        << "-bcsr_vb" << cfg.bcsr_val_bytes
        << "-topk" << cfg.routing_topk
        << "-topkpe" << cfg.routing_topk_per_pe
        << "-exself" << (cfg.route_exclude_self_pe ? 1 : 0)
        << "-layers" << cfg.route_layers_mask
        << "-eps" << cfg.routing_epsilon
        << "-mapmode" << cfg.mapping_mode
        << "-mapfile" << cfg.mapping_edges_file
        << "-maphdr" << (cfg.mapping_csv_has_header ? 1 : 0)
        << "-mapsplit" << cfg.mapping_csv_separator
        << "-mapblk" << (cfg.mapping_assume_block_ids ? 1 : 0);
    return oss.str();
}

bool deriveSquareMeshDims_(uint32_t total_nodes, uint32_t& out_w, uint32_t& out_h) {
    out_w = 0;
    out_h = 0;
    if (total_nodes == 0) return false;
    uint32_t w = static_cast<uint32_t>(std::sqrt(static_cast<double>(total_nodes)));
    while (w * w < total_nodes) ++w;
    if (w * w != total_nodes) return false;
    out_w = w;
    out_h = w;
    return true;
}

void buildRoutesFromCandidates_(const SynapseRouteBuildConfig& cfg,
                               Output* out,
                               bool verify_routing_weights,
                               const std::unordered_map<uint32_t, std::vector<std::pair<float,uint32_t>>>& tmp,
                               uint32_t rows,
                               bool group_by_pe,
                               SynapseRouteSubsystem::RouteMap& routes_out,
                               SynapseRouteSubsystem::RouteWeightMap* route_weights_out) {
    if (group_by_pe && rows == 0) {
        if (out) out->verbose(CALL_INFO, 1, 0,
                              "⚠️ 路由构建：rows=0 且 group_by_pe=1，已回退为 group_by_pe=0（避免除零）\n");
        group_by_pe = false;
    }
    for (auto& kv : tmp) {
        uint32_t pre = kv.first;
        const auto& lst_in = kv.second;
        if (lst_in.empty()) continue;

        std::vector<std::pair<float,uint32_t>> lst = lst_in;
        std::vector<uint32_t> final_routes;

        if (cfg.routing_topk_per_pe > 0) {
            std::unordered_map<uint32_t, std::vector<std::pair<float,uint32_t>>> by_group;
            by_group.reserve(16);
            for (auto& p : lst) {
                uint32_t gid = group_by_pe ? (p.second / rows) : 0u;
                by_group[gid].push_back(p);
            }
            std::vector<uint32_t> out_routes;
            for (auto& g : by_group) {
                auto& vec = g.second;
                if (vec.size() > cfg.routing_topk_per_pe) {
                    std::partial_sort(vec.begin(), vec.begin() + cfg.routing_topk_per_pe, vec.end(),
                        [](const auto& a, const auto& b) {
                            float aw = std::fabs(a.first);
                            float bw = std::fabs(b.first);
                            if (aw == bw) return a.second < b.second;
                            return aw > bw;
                        });
                    vec.resize(cfg.routing_topk_per_pe);
                }
                for (auto& p : vec) out_routes.push_back(p.second);
            }
            if (cfg.routing_topk > 0 && out_routes.size() > cfg.routing_topk) {
                std::vector<std::pair<float,uint32_t>> tmp2;
                tmp2.reserve(out_routes.size());
                std::unordered_set<uint32_t> keep(out_routes.begin(), out_routes.end());
                for (auto& p : lst) if (keep.count(p.second)) tmp2.push_back(p);
                std::partial_sort(tmp2.begin(), tmp2.begin() + cfg.routing_topk, tmp2.end(),
                    [](const auto& a, const auto& b) {
                        float aw = std::fabs(a.first);
                        float bw = std::fabs(b.first);
                        if (aw == bw) return a.second < b.second;
                        return aw > bw;
                    });
                tmp2.resize(cfg.routing_topk);
                std::vector<uint32_t> final_out;
                final_out.reserve(tmp2.size());
                for (auto& p : tmp2) final_out.push_back(p.second);
                final_routes = std::move(final_out);
            } else {
                final_routes = std::move(out_routes);
            }
        } else if (cfg.routing_topk > 0) {
            if (lst.size() > cfg.routing_topk) {
                std::partial_sort(lst.begin(), lst.begin() + cfg.routing_topk, lst.end(),
                    [](const auto& a, const auto& b) {
                        float aw = std::fabs(a.first);
                        float bw = std::fabs(b.first);
                        if (aw == bw) return a.second < b.second;
                        return aw > bw;
                    });
                lst.resize(cfg.routing_topk);
            }
            std::vector<uint32_t> out_routes;
            out_routes.reserve(lst.size());
            for (auto& p : lst) out_routes.push_back(p.second);
            final_routes = std::move(out_routes);
        } else {
            std::sort(lst.begin(), lst.end(), [](const auto& a, const auto& b) { return a.second < b.second; });
            lst.erase(std::unique(lst.begin(), lst.end(),
                                  [](const auto& a, const auto& b) { return a.second == b.second; }),
                      lst.end());
            std::vector<uint32_t> out_routes;
            out_routes.reserve(lst.size());
            for (auto& p : lst) out_routes.push_back(p.second);
            final_routes = std::move(out_routes);
        }

        if (verify_routing_weights && out) {
            uint64_t mismatch = 0;
            float min_abs = std::numeric_limits<float>::infinity();
            for (uint32_t dest : final_routes) {
                float w = 0.0f;
                bool found = false;
                for (const auto& cand : lst_in) {
                    if (cand.second == dest) { w = cand.first; found = true; break; }
                }
                if (!found) {
                    out->verbose(CALL_INFO, 0, 0,
                                 "⚠️ 路由验证: pre=%u dest=%u 未在候选列表中找到原始权重\n",
                                 pre, dest);
                    continue;
                }
                float absw = std::fabs(w);
                if (absw < min_abs) min_abs = absw;
                if (absw <= cfg.routing_epsilon) {
                    mismatch++;
                    out->verbose(CALL_INFO, 0, 0,
                                 "⚠️ 路由验证: pre=%u dest=%u weight=%.6f <= epsilon=%.6f\n",
                                 pre, dest, w, cfg.routing_epsilon);
                }
            }
            if (!final_routes.empty()) {
                float report_min = std::isfinite(min_abs) ? min_abs : 0.0f;
                out->verbose(CALL_INFO, 0, 0,
                             "🔍 路由验证: pre=%u fanout=%zu min_abs_weight=%.6f\n",
                             pre, final_routes.size(), report_min);
            }
            if (mismatch > 0) {
                out->verbose(CALL_INFO, 0, 0,
                             "⚠️ 路由验证: pre=%u 存在%" PRIu64 "个未达阈值的扇出\n",
                             pre, mismatch);
            }
        }

        // 确定性保证：
        // routes 的“发送顺序”会影响同一时间戳下事件入队次序（尤其在 MPI 多 rank），
        // 进而放大为窗口边界/发放统计的非确定性。这里统一对目的列表做排序与去重，
        // 保证跨运行的路由发射顺序稳定且无重复目的。
        std::sort(final_routes.begin(), final_routes.end());
        final_routes.erase(std::unique(final_routes.begin(), final_routes.end()), final_routes.end());

        if (route_weights_out) {
            for (uint32_t dest : final_routes) {
                bool found = false;
                float selected = 0.0f;
                float selected_abs = 0.0f;
                for (const auto& cand : lst_in) {
                    if (cand.second != dest) continue;
                    const float absw = std::fabs(cand.first);
                    if (!found || absw > selected_abs) {
                        found = true;
                        selected = cand.first;
                        selected_abs = absw;
                    }
                }
                if (!found) continue;
                const uint64_t key =
                    (static_cast<uint64_t>(pre) << 32) | static_cast<uint64_t>(dest);
                (*route_weights_out)[key] = selected;
            }
        }

        routes_out[pre] = std::move(final_routes);
    }
}

bool buildRoutesFromEdgesCSV_(const SynapseRouteBuildConfig& cfg,
                             Output* out,
                             const std::unordered_set<uint32_t>& allowed_layer_edges,
                             bool allow_all_layers,
                             SynapseRouteSubsystem::RouteMap& routes_out,
                             SynapseRouteSubsystem::RouteWeightMap* route_weights_out) {
    routes_out.clear();
    const uint32_t rows = cfg.rows;
    std::ifstream fin(cfg.mapping_edges_file);
    if (!fin.good()) {
        if (out) out->verbose(CALL_INFO, 1, 0, "⚠️ 无法打开映射边文件: %s\n", cfg.mapping_edges_file.c_str());
        return false;
    }
    std::string line;
    if (cfg.mapping_csv_has_header) std::getline(fin, line);
    auto trim_inplace = [](std::string& t) {
        size_t b = 0;
        while (b < t.size() && std::isspace(static_cast<unsigned char>(t[b]))) ++b;
        size_t e = t.size();
        while (e > b && std::isspace(static_cast<unsigned char>(t[e - 1]))) --e;
        if (b == 0 && e == t.size()) return;
        t = t.substr(b, e - b);
    };
    auto split = [&cfg, &trim_inplace](const std::string& s)->std::vector<std::string>{
        std::vector<std::string> outv;
        std::string cur;
        char sep = cfg.mapping_csv_separator.empty() ? ',' : cfg.mapping_csv_separator[0];
        std::istringstream ss(s);
        while (std::getline(ss, cur, sep)) { trim_inplace(cur); outv.push_back(cur); }
        if (outv.empty()) { std::istringstream ss2(s); while (ss2 >> cur) { trim_inplace(cur); outv.push_back(cur); } }
        return outv;
    };
    std::unordered_map<uint32_t, std::vector<std::pair<float,uint32_t>>> tmp;
    uint64_t dropped_self = 0, dropped_layer = 0;
    uint64_t bad_rows = 0;
    uint64_t bad_rows_logged = 0;
    uint64_t total_rows = 0;
    constexpr uint64_t kMaxBadRowsLog = 8;
    while (std::getline(fin, line)) {
        if (line.empty()) continue;
        total_rows++;
        auto toks = split(line);
        if (toks.size() < 2) {
            bad_rows++;
            if (out && bad_rows_logged < kMaxBadRowsLog) {
                out->verbose(CALL_INFO, 1, 0,
                             "⚠️ 映射CSV坏行(列数<2) line='%s'\n",
                             line.c_str());
                bad_rows_logged++;
            }
            continue;
        }
        uint32_t src = 0, dst = 0;
        if (!parseU32CsvField_(toks[0], src) || !parseU32CsvField_(toks[1], dst)) {
            bad_rows++;
            if (out && bad_rows_logged < kMaxBadRowsLog) {
                out->verbose(CALL_INFO, 1, 0,
                             "⚠️ 映射CSV坏行(src/dst解析失败) src='%s' dst='%s' line='%s'\n",
                             toks[0].c_str(), toks[1].c_str(), line.c_str());
                bad_rows_logged++;
            }
            continue;
        }
        float w = 1.0f;
        if (toks.size() >= 3) { try { w = std::stof(toks[2]); } catch(...) { w = 1.0f; } }
        if (std::fabs(w) <= cfg.routing_epsilon) continue;
        if (cfg.mapping_assume_block_ids) {
            uint32_t src_pe = src / rows;
            uint32_t dst_pe = dst / rows;
            if (cfg.route_exclude_self_pe && src_pe == dst_pe) { dropped_self++; continue; }
            if (!allow_all_layers) {
                uint32_t la = layerIdFromPe_(src_pe);
                uint32_t lb = layerIdFromPe_(dst_pe);
                uint32_t key = (la<<8) | lb;
                if (allowed_layer_edges.find(key) == allowed_layer_edges.end()) { dropped_layer++; continue; }
            }
        }
        tmp[src].emplace_back(w, dst);
    }
    if (bad_rows > 0 && out) {
        out->verbose(CALL_INFO, 1, 0,
                     "⚠️ 映射CSV解析存在坏行: file=%s total_rows=%" PRIu64 " bad_rows=%" PRIu64 "\n",
                     cfg.mapping_edges_file.c_str(), total_rows, bad_rows);
    }
    buildRoutesFromCandidates_(cfg, out, cfg.verify_routing_weights, tmp, rows,
                              /*group_by_pe=*/cfg.mapping_assume_block_ids, routes_out, route_weights_out);
    if ((cfg.route_exclude_self_pe || !allow_all_layers) && cfg.route_filter_warn && out) {
        out->verbose(CALL_INFO, 1, 0,
            "⚠️ 路由过滤(映射CSV)启用: exclude_self_pe=%d, layers_mask='%s' (丢弃: self=%" PRIu64 ", layer=%" PRIu64 ")\n",
            cfg.route_exclude_self_pe ? 1 : 0, cfg.route_layers_mask.c_str(), dropped_self, dropped_layer);
    }
    return !routes_out.empty();
}

bool buildWeightDrivenRoutesFromBcsr_(const SynapseRouteBuildConfig& cfg,
                                     Output* out,
                                     SynapseRouteSubsystem::RouteMap& routes_out,
                                     SynapseRouteSubsystem::RouteWeightMap* route_weights_out) {
    routes_out.clear();
    if (route_weights_out) route_weights_out->clear();
    const uint32_t cores_per_pe = (cfg.cores_per_pe > 0) ? cfg.cores_per_pe : 1u;
    uint32_t rows_hint = (cores_per_pe > 0) ? static_cast<uint32_t>((cfg.rows + cores_per_pe - 1) / cores_per_pe) : cfg.rows;
    if (rows_hint == 0) rows_hint = cfg.rows;
    bool ok = true;
    for (uint32_t pe = 0; pe < cfg.total_nodes; ++pe) {
        for (uint32_t core = 0; core < cores_per_pe; ++core) {
            std::string path = resolveBcsrTemplate(cfg.weights_template, pe, static_cast<int>(core));
            if (path.empty()) { ok = false; break; }
            if (!appendRoutesFromBcsrFile(cfg, out, path, pe, static_cast<int>(core),
                                          rows_hint, routes_out, BcsrAppendOptions{}, route_weights_out)) {
                ok = false;
                break;
            }
        }
        if (!ok) break;
    }
    if (!ok) {
        routes_out.clear();
        return false;
    }
    return !routes_out.empty();
}

bool buildWeightDrivenRoutesDense_(const SynapseRouteBuildConfig& cfg,
                                  Output* out,
                                  const std::unordered_set<uint32_t>& allowed_layer_edges,
                                  bool allow_all_layers,
                                  SynapseRouteSubsystem::RouteMap& routes_out,
                                  SynapseRouteSubsystem::RouteWeightMap* route_weights_out) {
    routes_out.clear();
    if (route_weights_out) route_weights_out->clear();
    if (cfg.weights_template.empty()) {
        if (out) out->verbose(CALL_INFO, 1, 0, "⚠️ 路由构建失败：weights_template 未提供\n");
        return false;
    }
    if (cfg.weights_template.find(".bcsr") != std::string::npos ||
        cfg.weights_template.find(".BCSR") != std::string::npos) {
        return buildWeightDrivenRoutesFromBcsr_(cfg, out, routes_out, route_weights_out);
    }

    const uint32_t rows = cfg.rows;
    const uint32_t cols = cfg.cols;
    const uint32_t total_nodes = cfg.total_nodes;
    if (rows == 0 || cols == 0) {
        if (out) out->verbose(CALL_INFO, 1, 0, "⚠️ 路由构建失败：rows/cols 非法（rows=%u cols=%u）\n", rows, cols);
        return false;
    }
    const uint64_t expected64 = static_cast<uint64_t>(rows) * static_cast<uint64_t>(cols);
    if (expected64 > static_cast<uint64_t>(std::numeric_limits<size_t>::max())) {
        if (out) out->verbose(CALL_INFO, 1, 0, "⚠️ 路由构建失败：rows*cols 溢出 size_t（rows=%u cols=%u）\n", rows, cols);
        return false;
    }
    const size_t expected = static_cast<size_t>(expected64);
    std::unordered_map<uint32_t, std::vector<std::pair<float,uint32_t>>> tmp;
    tmp.reserve(cols);
    uint64_t dropped_self_pe = 0;
    uint64_t dropped_layer_mask = 0;

    for (uint32_t pe = 0; pe < total_nodes; ++pe) {
        std::string path = cfg.weights_template;
        replaceAllIndexed(path, "{pe:02d}", pe, 2);
        replaceAll(path, "{pe}", std::to_string(pe));
        std::ifstream fin(path, std::ios::binary);
        if (!fin.good()) {
            if (out) out->verbose(CALL_INFO, 1, 0, "⚠️ 路由构建：无法读取权重文件 %s\n", path.c_str());
            continue;
        }
        fin.seekg(0, std::ios::end);
        std::streamsize bytes = fin.tellg();
        fin.seekg(0, std::ios::beg);
        if (bytes <= 0 || (bytes % sizeof(float) != 0)) {
            if (out) out->verbose(CALL_INFO, 1, 0, "⚠️ 路由构建：文件尺寸异常 %s\n", path.c_str());
            continue;
        }
        size_t count = static_cast<size_t>(bytes / sizeof(float));
        if (count < expected) {
            if (out) out->verbose(CALL_INFO, 1, 0, "⚠️ 路由构建：文件过短 %s (%zu<%zu)\n", path.c_str(), count, expected);
            continue;
        }
        std::vector<float> buf(count);
        fin.read(reinterpret_cast<char*>(buf.data()), bytes);
        for (uint32_t row = 0; row < rows; ++row) {
            for (uint32_t col = 0; col < cols; ++col) {
                size_t idx = static_cast<size_t>(row) * static_cast<size_t>(cols) + col;
                float w = buf[idx];
                if (std::fabs(w) > cfg.routing_epsilon) {
                    uint32_t pre_global = col;
                    const uint64_t dest_global64 =
                        static_cast<uint64_t>(pe) * static_cast<uint64_t>(rows) + static_cast<uint64_t>(row);
                    if (dest_global64 > static_cast<uint64_t>(std::numeric_limits<uint32_t>::max())) continue;
                    uint32_t dest_global = static_cast<uint32_t>(dest_global64);
                    if (cfg.route_exclude_self_pe) {
                        uint32_t src_pe = pre_global / rows;
                        if (src_pe == pe) { dropped_self_pe++; continue; }
                    }
                    if (!allow_all_layers) {
                        uint32_t src_pe = pre_global / rows;
                        uint32_t la = layerIdFromPe_(src_pe);
                        uint32_t lb = layerIdFromPe_(pe);
                        uint32_t key = (la<<8) | lb;
                        if (allowed_layer_edges.find(key) == allowed_layer_edges.end()) { dropped_layer_mask++; continue; }
                    }
                    tmp[pre_global].emplace_back(w, dest_global);
                }
            }
        }
    }
    buildRoutesFromCandidates_(cfg, out, cfg.verify_routing_weights, tmp, rows,
                               /*group_by_pe=*/true, routes_out, route_weights_out);
    if ((cfg.route_exclude_self_pe || !allow_all_layers) && cfg.route_filter_warn && out) {
        out->verbose(CALL_INFO, 1, 0,
            "⚠️ 路由过滤启用: exclude_self_pe=%d, layers_mask='%s' (丢弃: self_pe=%" PRIu64 ", layer_mask=%" PRIu64 ")\n",
            cfg.route_exclude_self_pe ? 1 : 0, cfg.route_layers_mask.c_str(), dropped_self_pe, dropped_layer_mask);
    }
    return !routes_out.empty();
}

} // namespace

void SynapseRouteSubsystem::configure(const SynapseRouteBuildConfig& cfg) {
    cfg_ = cfg;
    routing_weight_driven_active_ = false;
    routes_shared_.reset();
    routes_local_fallback_.clear();
    route_weights_shared_.reset();
    route_weights_local_fallback_.clear();
    route_summary_logged_ = false;
    fanout_provider_ready_ = false;
    gating_cache_.clear();
    multicast_ready_ = false;
    mesh_w_ = 0;
    mesh_h_ = 0;
    multicast_targets_shared_.reset();
    multicast_targets_local_.clear();
}

void SynapseRouteSubsystem::configureGating(bool gating_event_mode,
                                            uint64_t gating_ttl_cycles,
                                            bool gating_scope_inputs_only) {
    gating_event_mode_ = gating_event_mode;
    gating_ttl_cycles_ = gating_ttl_cycles;
    gating_scope_inputs_only_ = gating_scope_inputs_only;
}

void SynapseRouteSubsystem::bindRuntime(Output* log,
                                        uint32_t node_id,
                                        uint32_t core_id,
                                        uint32_t num_neurons,
                                        uint32_t neurons_per_pe_cfg,
                                        SST::Statistics::Statistic<uint64_t>* stat_routes_entries) {
    if (log) log_ = log;
    node_id_ = node_id;
    core_id_ = core_id;
    num_neurons_ = num_neurons;
    neurons_per_pe_cfg_ = neurons_per_pe_cfg;
    if (stat_routes_entries) stat_routes_entries_ = stat_routes_entries;
}

void SynapseRouteSubsystem::bindFanoutStat(SST::Statistics::Statistic<uint64_t>* stat_fanout_per_spike) {
    if (stat_fanout_per_spike) stat_fanout_per_spike_ = stat_fanout_per_spike;
}

void SynapseRouteSubsystem::bindRouteRuntimeStats(const RouteRuntimeStatSinks& stats) {
    route_runtime_stats_ = stats;
}

bool SynapseRouteSubsystem::initRoutes() {
    routes_shared_.reset();
    routes_local_fallback_.clear();
    route_weights_shared_.reset();
    route_weights_local_fallback_.clear();
    fanout_provider_ready_ = false;
    multicast_ready_ = false;
    mesh_w_ = 0;
    mesh_h_ = 0;
    multicast_targets_shared_.reset();
    multicast_targets_local_.clear();

    routing_weight_driven_active_ = cfg_.routing_weight_driven;
    if (!routing_weight_driven_active_) {
        // fixed 路由模式：无需构建 routes，但仍需配置 fanout provider。
        configureFanoutProvider_();
        return false;
    }

    const std::string cache_key = buildRouteCacheKey_(cfg_);
    bool ok = false;
    bool hit_cache = false;

    if (!cache_key.empty()) {
        std::shared_ptr<const RouteMap> hit;
        std::shared_ptr<const RouteWeightMap> hit_weights;
        {
            std::lock_guard<std::mutex> g(s_route_cache_mtx_);
            auto it = s_route_cache_.find(cache_key);
            if (it != s_route_cache_.end()) hit = it->second.lock();
        }
        {
            std::lock_guard<std::mutex> g(s_route_weight_cache_mtx_);
            auto it = s_route_weight_cache_.find(cache_key);
            if (it != s_route_weight_cache_.end()) hit_weights = it->second.lock();
        }
        if (hit && hit_weights) {
            routes_shared_ = hit;
            route_weights_shared_ = hit_weights;
            ok = true;
            hit_cache = true;
            uint64_t total_entries = 0;
            for (auto& kv : *routes_shared_) total_entries += (uint64_t)kv.second.size();
            if (stat_routes_entries_) stat_routes_entries_->addData(total_entries);
            if (log_) {
                log_->verbose(CALL_INFO, 3, 0,
                    "🔁 命中共享路由缓存: 核心%u, 源条目=%zu, 总目的=%" PRIu64 "\n",
                    core_id_, routes_shared_->size(), total_entries);
            }
        }
    }

    if (!ok) {
        std::unordered_set<uint32_t> allowed_layer_edges;
        bool allow_all_layers = true;
        parseLayerMask_(cfg_.route_layers_mask, allowed_layer_edges, allow_all_layers);

        RouteMap built_routes;
        RouteWeightMap built_weights;
        if (cfg_.mapping_mode == "edges_csv" && !cfg_.mapping_edges_file.empty()) {
            ok = buildRoutesFromEdgesCSV_(cfg_, log_, allowed_layer_edges, allow_all_layers,
                                          built_routes, &built_weights);
        } else {
            ok = buildWeightDrivenRoutesDense_(cfg_, log_, allowed_layer_edges, allow_all_layers,
                                               built_routes, &built_weights);
        }

        if (!ok) {
            if (log_) {
                log_->verbose(CALL_INFO, 1, 0,
                    "⚠️ 核心%u权重驱动路由构建失败，将回退fixed路由\n",
                    core_id_);
            }
            routing_weight_driven_active_ = false;
        } else {
            auto shared = std::make_shared<RouteMap>(std::move(built_routes));
            auto shared_weights = std::make_shared<RouteWeightMap>(std::move(built_weights));
            routes_shared_ = shared;
            route_weights_shared_ = shared_weights;
            uint64_t total_entries = 0;
            for (auto& kv : *routes_shared_) total_entries += (uint64_t)kv.second.size();
            if (stat_routes_entries_) stat_routes_entries_->addData(total_entries);

            // One-shot local/remote ratio summary (per core)
            if (cfg_.route_summary_enable && log_ && !route_summary_logged_) {
                route_summary_logged_ = true;
                uint64_t local_edges = 0, remote_edges = 0;
                const uint32_t denom = (neurons_per_pe_cfg_ > 0) ? neurons_per_pe_cfg_ : num_neurons_;
                for (const auto& kv : *routes_shared_) {
                    for (auto post_global : kv.second) {
                        uint32_t pe_of_post = (denom ? (post_global / denom) : 0);
                        if (pe_of_post == node_id_) ++local_edges; else ++remote_edges;
                    }
                }
                double local_ratio = (total_entries > 0) ? (double)local_edges / (double)total_entries : 0.0;
                double remote_ratio = (total_entries > 0) ? (double)remote_edges / (double)total_entries : 0.0;
                log_->verbose(CALL_INFO, 0, 0,
                    "[route-summary] node=%u core=%u entries=%zu total=%" PRIu64
                    " local=%" PRIu64 " (%.2f) remote=%" PRIu64 " (%.2f)\n",
                    node_id_, core_id_, routes_shared_->size(), total_entries,
                    local_edges, local_ratio, remote_edges, remote_ratio);
            }

            if (!cache_key.empty()) {
                std::lock_guard<std::mutex> g(s_route_cache_mtx_);
                s_route_cache_[cache_key] = shared;
            }
            if (!cache_key.empty()) {
                std::lock_guard<std::mutex> g(s_route_weight_cache_mtx_);
                s_route_weight_cache_[cache_key] = shared_weights;
            }
        }
    }

    if (cfg_.route_summary_enable && log_) {
        logRoutingSummary_("init", routing_weight_driven_active_ ? (hit_cache ? "active(cache)" : "active") : "fallback_fixed");
    }

    initMulticastTargets_();
    configureFanoutProvider_();
    return routing_weight_driven_active_;
}

void SynapseRouteSubsystem::computeFanout(uint32_t source_global, uint32_t neuron_idx,
                                          uint64_t now_cycles,
                                          std::vector<FanoutEntry>& out_entries,
                                          bool& applied_gating) const {
    out_entries.clear();
    applied_gating = false;
    if (!fanout_provider_ready_) return;
    fanout_provider_.computeFanout(source_global, neuron_idx, now_cycles, out_entries, applied_gating);
}

void SynapseRouteSubsystem::applyGatingDecision(uint32_t src_global,
                                                const std::vector<uint32_t>& dest_pes,
                                                uint64_t current_cycle,
                                                uint64_t ttl_cycles) {
    if (!gating_event_mode_) return;
    GatingEntry e;
    e.dest_pes = dest_pes;
    e.expire_cycle = current_cycle + (ttl_cycles ? ttl_cycles : gating_ttl_cycles_);
    gating_cache_[src_global] = std::move(e);
    if (log_) {
        log_->verbose(CALL_INFO, 3, 0,
            "📥 应用门控: src_g=%u, k=%zu, expire=%" PRIu64 "\n",
            src_global, dest_pes.size(), gating_cache_[src_global].expire_cycle);
    }
}

SynapseRouteSubsystem::RouteSemanticDescriptor SynapseRouteSubsystem::describeRouteSemantics() const {
    RouteSemanticDescriptor descriptor{};
    descriptor.source_semantics_authority = "legacy_provider";
    descriptor.source_primary_kind = sourcePrimaryKindFromCfg_(cfg_);
    descriptor.route_topology = "mesh_2d";
    descriptor.target_semantics_authority = "legacy_multicast_fallback";
    descriptor.real_synapse_inputs_available = cfg_.real_synapse_inputs_available;
    descriptor.native_synapse_source_candidate = false;
    descriptor.native_source_fanout_active = false;
    descriptor.native_target_synthesis_active = false;
    descriptor.bootstrap_dependency_active = false;
    descriptor.native_bootstrap_source.clear();
    if (descriptor.source_primary_kind == "edges_csv_bootstrap") {
        descriptor.bootstrap_dependency_active = true;
        descriptor.native_bootstrap_source = "edges_csv";
    } else if (
        descriptor.source_primary_kind == "legacy_route_tables_bootstrap"
        || descriptor.source_primary_kind == "legacy_route_tables_with_real_synapse_inputs"
    ) {
        descriptor.bootstrap_dependency_active = true;
        descriptor.native_bootstrap_source = "legacy_route_tables";
    }
    return descriptor;
}

bool SynapseRouteSubsystem::multicastEnabled() const {
    return routing_weight_driven_active_ && cfg_.multicast_enable;
}

bool SynapseRouteSubsystem::computeMulticastTargets(uint32_t source_global,
                                                    uint32_t neuron_idx,
                                                    uint64_t now_cycles,
                                                    std::vector<BlockTarget>& out_targets,
                                                    bool& applied_gating) const {
    (void)neuron_idx;

    out_targets.clear();
    applied_gating = false;
    if (!multicast_ready_) return false;

    const MulticastTargetMap* table = multicast_targets_shared_ ? multicast_targets_shared_.get() : &multicast_targets_local_;
    auto it = table->find(source_global);
    if (it == table->end()) return false;
    out_targets = it->second;

    // gating 过滤：仅保留 allowed dest_pes 的块内 core_mask（保持“按 PE 选择”的语义）
    if (gating_event_mode_) {
        bool scope_ok = !gating_scope_inputs_only_ ? true : (node_id_ <= 3);
        if (scope_ok) {
            auto itg = gating_cache_.find(source_global);
            if (itg != gating_cache_.end() && now_cycles <= itg->second.expire_cycle) {
                const auto& dpes = itg->second.dest_pes;
                if (!dpes.empty()) {
                    std::unordered_set<uint32_t> allowed_nodes(dpes.begin(), dpes.end());
                    for (auto& bt : out_targets) {
                        // 注意：block 的 4 个节点集合应由 block_id 推导，不能从 ingress_node 推导，
                        // 否则当 ingress policy 不是 top_left 时会错杀/漏杀。
                        const uint32_t base = blockBaseNodeFromId_(bt.block_id, mesh_w_, cfg_.multicast_block_w, cfg_.multicast_block_h);
                        const uint32_t bw = cfg_.multicast_block_w;
                        const uint32_t bh = cfg_.multicast_block_h;
                        const uint32_t cells = bw * bh;
                        for (uint32_t idx = 0; idx < cells && idx < kMaxMulticastBlockCells; ++idx) {
                            const uint32_t lx = idx % bw;
                            const uint32_t ly = idx / bw;
                            const uint32_t node = base + lx + ly * mesh_w_;
                            if (allowed_nodes.find(node) == allowed_nodes.end()) bt.core_mask[idx] = 0;
                        }
                    }

                    const uint32_t bw = cfg_.multicast_block_w;
                    const uint32_t bh = cfg_.multicast_block_h;
                    const uint32_t cells = bw * bh;
                    out_targets.erase(std::remove_if(out_targets.begin(), out_targets.end(),
                                                    [&](const BlockTarget& bt) {
                                                        for (uint32_t idx = 0; idx < cells && idx < kMaxMulticastBlockCells; ++idx) {
                                                            if (bt.core_mask[idx] != 0) return false;
                                                        }
                                                        return true;
                                                    }),
                                      out_targets.end());
                    applied_gating = true;
                }
            }
        }
    }
    return !out_targets.empty();
}

void SynapseRouteSubsystem::initMulticastTargets_() {
    multicast_ready_ = false;
    mesh_w_ = 0;
    mesh_h_ = 0;
    multicast_targets_shared_.reset();
    multicast_targets_local_.clear();

    if (!routing_weight_driven_active_ || !cfg_.multicast_enable) return;
    if (!routes_shared_) return;

    if (cfg_.multicast_block_w == 0 || cfg_.multicast_block_h == 0) {
        if (log_) log_->verbose(CALL_INFO, 1, 0, "⚠️ multicast block 尺寸非法（当前=%ux%u），已禁用\n",
                                cfg_.multicast_block_w, cfg_.multicast_block_h);
        return;
    }
    const uint32_t block_cells = cfg_.multicast_block_w * cfg_.multicast_block_h;
    if (block_cells == 0 || block_cells > kMaxMulticastBlockCells) {
        if (log_) log_->verbose(CALL_INFO, 1, 0, "⚠️ multicast block 过大（当前=%ux%u, cells=%u, max=%u），已禁用\n",
                                cfg_.multicast_block_w, cfg_.multicast_block_h, block_cells, kMaxMulticastBlockCells);
        return;
    }
    IngressPolicy ingress_policy{};
    if (!parseIngressPolicy_(cfg_.multicast_ingress_policy, ingress_policy)) {
        if (log_) log_->verbose(CALL_INFO, 1, 0,
                                "⚠️ multicast ingress_policy 不支持（当前='%s'），已禁用\n",
                                cfg_.multicast_ingress_policy.c_str());
        return;
    }

    if (!deriveSquareMeshDims_(cfg_.total_nodes, mesh_w_, mesh_h_)) {
        if (log_) log_->verbose(CALL_INFO, 1, 0, "⚠️ multicast 需要 square mesh（total_nodes=%u），已禁用\n",
                                cfg_.total_nodes);
        return;
    }
    if (mesh_w_ % cfg_.multicast_block_w != 0 || mesh_h_ % cfg_.multicast_block_h != 0) {
        if (log_) log_->verbose(CALL_INFO, 1, 0, "⚠️ multicast block 无法整除 mesh（mesh=%ux%u, block=%ux%u），已禁用\n",
                                mesh_w_, mesh_h_, cfg_.multicast_block_w, cfg_.multicast_block_h);
        return;
    }

    const std::string cache_key = buildRouteCacheKey_(cfg_);
    std::string mc_key;
    if (!cache_key.empty()) {
        mc_key = cache_key;
        mc_key.append("|mc:blocked:").append(std::to_string(cfg_.multicast_block_w)).append("x").append(std::to_string(cfg_.multicast_block_h));
        mc_key.append("|ingress:").append(cfg_.multicast_ingress_policy);
    }

    if (!mc_key.empty()) {
        std::shared_ptr<const MulticastTargetMap> hit;
        {
            std::lock_guard<std::mutex> g(s_multicast_cache_mtx_);
            auto it = s_multicast_cache_.find(mc_key);
            if (it != s_multicast_cache_.end()) hit = it->second.lock();
        }
        if (hit) {
            multicast_targets_shared_ = hit;
            multicast_ready_ = true;
            return;
        }
    }

    const uint32_t denom = (neurons_per_pe_cfg_ > 0) ? neurons_per_pe_cfg_ : num_neurons_;
    if (denom == 0 || num_neurons_ == 0 || cfg_.cores_per_pe == 0) return;

    const uint32_t blocks_w = mesh_w_ / cfg_.multicast_block_w;

    MulticastTargetMap built;
    built.reserve(routes_shared_->size());

    for (const auto& kv : *routes_shared_) {
        const uint32_t pre_global = kv.first;
        const auto& dests = kv.second;
        if (dests.empty()) continue;

        std::unordered_map<uint32_t, BlockTarget> per_block;
        for (uint32_t dest_global : dests) {
            const uint32_t dest_node = denom ? (dest_global / denom) : 0;
            if (dest_node >= cfg_.total_nodes) continue;

            const uint32_t local_in_pe = denom ? (dest_global % denom) : dest_global;
            const uint32_t dest_core = (num_neurons_ ? (local_in_pe / num_neurons_) : 0);
            if (dest_core >= cfg_.cores_per_pe) continue;

            const uint32_t x = dest_node % mesh_w_;
            const uint32_t y = dest_node / mesh_w_;

            const uint32_t block_x = (x / cfg_.multicast_block_w) * cfg_.multicast_block_w;
            const uint32_t block_y = (y / cfg_.multicast_block_h) * cfg_.multicast_block_h;
            const uint32_t block_id = (y / cfg_.multicast_block_h) * blocks_w + (x / cfg_.multicast_block_w);
            const uint32_t ingress = selectIngressNodeBlocked_(ingress_policy,
                                                               pre_global,
                                                               block_id,
                                                               block_x,
                                                               block_y,
                                                               cfg_.multicast_block_w,
                                                               cfg_.multicast_block_h,
                                                               mesh_w_);

            const uint32_t local_x = x - block_x;
            const uint32_t local_y = y - block_y;
            const uint32_t idx = local_y * cfg_.multicast_block_w + local_x;
            if (idx >= block_cells || idx >= kMaxMulticastBlockCells) continue;

            auto& bt = per_block[block_id];
            bt.block_id = block_id;
            bt.ingress_node = ingress;
            bt.core_mask[idx] |= (1u << dest_core);
        }

        if (!per_block.empty()) {
            std::vector<BlockTarget> vec;
            vec.reserve(per_block.size());
            for (auto& itb : per_block) {
                itb.second.cohort_id = 0;
                itb.second.band_color = 0;
                vec.push_back(itb.second);
            }
            std::sort(vec.begin(), vec.end(),
                      [](const BlockTarget& a, const BlockTarget& b) { return a.block_id < b.block_id; });
            built.emplace(pre_global, std::move(vec));
        }
    }

    auto shared = std::make_shared<MulticastTargetMap>(std::move(built));
    multicast_targets_shared_ = shared;
    if (!mc_key.empty()) {
        std::lock_guard<std::mutex> g(s_multicast_cache_mtx_);
        s_multicast_cache_[mc_key] = shared;
    }
    multicast_ready_ = true;
}

void SynapseRouteSubsystem::configureFanoutProvider_() {
    SnnRouteProvider::Config cfg{};
    cfg.routing_weight_driven = routing_weight_driven_active_;
    cfg.log_weight_details = cfg_.log_weight_details;
    cfg.num_neurons = num_neurons_;
    cfg.neurons_per_pe_cfg = neurons_per_pe_cfg_;
    cfg.node_id = node_id_;
    cfg.gating_event_mode = gating_event_mode_;
    cfg.gating_scope_inputs_only = gating_scope_inputs_only_;
    cfg.gating_cache = &gating_cache_;
    cfg.out = log_;
    cfg.stat_fanout = stat_fanout_per_spike_;

    const RouteWeightMap* route_weights =
        route_weights_shared_ ? route_weights_shared_.get() : &route_weights_local_fallback_;
    fanout_provider_.configure(cfg, routes_shared_, &routes_local_fallback_, route_weights);
    fanout_provider_ready_ = true;
}

void SynapseRouteSubsystem::logRoutingSummary_(const char* phase, const char* reason) const {
    if (!(cfg_.route_summary_enable && log_)) return;
    const size_t shared_entries = routes_shared_ ? routes_shared_->size() : 0;
    const size_t local_entries = shared_entries ? 0 : routes_local_fallback_.size();
    log_->verbose(CALL_INFO, 0, 0,
        "[route-summary][%s] node=%u core=%u routes_shared=%zu routes_local=%zu %s\n",
        phase ? phase : "-", node_id_, core_id_, shared_entries, local_entries,
        reason ? reason : "");
}

}} // namespace SST::SnnDL
