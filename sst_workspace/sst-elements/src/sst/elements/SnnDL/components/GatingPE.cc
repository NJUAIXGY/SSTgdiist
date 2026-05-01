// -*- c++ -*-
#include "GatingPE.h"
#include <cctype>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <random>
#include "SnnNIC.h"
#include "SnnInterface.h"
#include "GatingDecisionEvent.h"
#include "GatingPEConfig.h"

using namespace SST;
using namespace SST::SnnDL;

namespace {

static inline void trimAsciiInplace_(std::string& s) {
    size_t b = 0;
    while (b < s.size() && std::isspace(static_cast<unsigned char>(s[b]))) ++b;
    size_t e = s.size();
    while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) --e;
    if (b == 0 && e == s.size()) return;
    s = s.substr(b, e - b);
}

static inline bool parseU32Strict_(const std::string& in, uint32_t& out) {
    std::string s = in;
    trimAsciiInplace_(s);
    if (s.empty()) return false;
    try {
        size_t pos = 0;
        const unsigned long long v = std::stoull(s, &pos, 10);
        if (pos != s.size()) return false;
        if (v > static_cast<unsigned long long>(std::numeric_limits<uint32_t>::max())) return false;
        out = static_cast<uint32_t>(v);
        return true;
    } catch (...) {
        return false;
    }
}

} // namespace

GatingPE::GatingPE(ComponentId_t id, Params& params)
    : Component(id)
{
    const GatingPEConfig cfg = parseGatingPEConfig(params);
    total_nodes_  = cfg.total_nodes;
    rows_per_pe_  = cfg.rows_per_pe;
    top_k_        = cfg.top_k;
    weight_value_ = cfg.weight_value;
    transitions_  = cfg.transitions;
    edges_path_   = cfg.edges_output_file;
    csv_header_   = cfg.csv_header;
    selection_    = cfg.selection;
    seed_         = cfg.seed;

    gate_targets_ = cfg.gate_targets;
    emit_period_ns_ = cfg.emit_period_ns;
    emit_count_ = cfg.emit_count;
    nic_node_id_ = cfg.node_id;
    nic_vns_ = cfg.virtual_channels;
    nic_vn_control_ = cfg.vn_control;
    nic_link_bw_ = cfg.link_bw;
    nic_in_buf_ = cfg.input_buf_size;
    nic_out_buf_ = cfg.output_buf_size;

    out_ = new Output("GatingPE[@p:@l]: ", cfg.verbose, 0, Output::STDOUT);

    // stats
    stat_tokens_ = registerStatistic<uint64_t>("gating_tokens");
    stat_edges_  = registerStatistic<uint64_t>("edges_generated");
    stat_evt_sent_ = registerStatistic<uint64_t>("gating_events_sent");

    // No clock required
}

GatingPE::~GatingPE() {
    if (out_) { delete out_; out_ = nullptr; }
}

void GatingPE::init(unsigned int phase) {
    if (phase == 0) {
        if (edges_path_.empty()) {
            out_->verbose(CALL_INFO, 1, 0, "⚠️ 未设置edges_output_file，跳过CSV生成\n");
        } else {
            writeCSV();
        }
        // 加载NIC（用于控制事件发射）
        Params p;
        p.insert("node_id", std::to_string(nic_node_id_));
        p.insert("link_bw", nic_link_bw_);
        p.insert("input_buf_size", nic_in_buf_);
        p.insert("output_buf_size", nic_out_buf_);
        p.insert("virtual_channels", std::to_string(nic_vns_));
        p.insert("vn_control", std::to_string(nic_vn_control_));
        p.insert("total_nodes", std::to_string(total_nodes_));
        nic_ = loadAnonymousSubComponent<SnnInterface>("SnnDL.SnnNIC", "network_interface", 0,
            ComponentInfo::SHARE_PORTS | ComponentInfo::INSERT_STATS, p);
        if (!nic_) {
            out_->verbose(CALL_INFO, 1, 0, "⚠️ 未能加载SnnNIC，控制事件将不可用\n");
        }
        // 注册定时器
        if (emit_period_ns_ > 0 && nic_) {
            std::string per = std::to_string(emit_period_ns_) + "ns";
            registerClock(per, new SST::Clock::Handler2<GatingPE, &GatingPE::onEmitTick>(this));
        }
    }
}

void GatingPE::setup() { /* no-op */ }
void GatingPE::finish() { /* no-op */ }

bool GatingPE::parseTransitions(const std::string& s, std::vector<Transition>& out) {
    // format: a-b:c-d, e-f:g-h, ... (inclusive bounds)
    out.clear();
    std::istringstream ss(s);
    std::string tok;
    while (std::getline(ss, tok, ',')) {
        trimAsciiInplace_(tok);
        if (tok.empty()) continue;
        size_t colon = tok.find(':');
        if (colon == std::string::npos) {
            if (out_) out_->verbose(CALL_INFO, 1, 0, "⚠️ transitions token缺少':'分隔符: '%s'\n", tok.c_str());
            return false;
        }
        std::string left = tok.substr(0, colon);
        std::string right = tok.substr(colon+1);
        trimAsciiInplace_(left);
        trimAsciiInplace_(right);
        auto parseRange = [](const std::string& r, Range& out_range)->bool{
            size_t dash = r.find('-');
            if (dash == std::string::npos) {
                uint32_t v = 0;
                if (!parseU32Strict_(r, v)) return false;
                out_range.a = v;
                out_range.b = v;
                return true;
            }

            uint32_t a = 0, b = 0;
            if (!parseU32Strict_(r.substr(0, dash), a)) return false;
            if (!parseU32Strict_(r.substr(dash + 1), b)) return false;
            if (b < a) return false;
            out_range.a = a;
            out_range.b = b;
            return true;
        };
        Transition tr;
        if (!parseRange(left, tr.src)) {
            if (out_) out_->verbose(CALL_INFO, 1, 0, "⚠️ transitions源范围解析失败: '%s'\n", left.c_str());
            return false;
        }
        if (!parseRange(right, tr.dst)) {
            if (out_) out_->verbose(CALL_INFO, 1, 0, "⚠️ transitions目标范围解析失败: '%s'\n", right.c_str());
            return false;
        }
        out.push_back(tr);
    }
    return !out.empty();
}

void GatingPE::writeCSV() {
    std::vector<Transition> trs; trs.reserve(8);
    if (!parseTransitions(transitions_, trs)) {
        out_->verbose(CALL_INFO, 1, 0, "⚠️ transitions参数解析失败: %s\n", transitions_.c_str());
        return;
    }
    std::ofstream fout(edges_path_);
    if (!fout.good()) {
        out_->verbose(CALL_INFO, 1, 0, "⚠️ 无法打开CSV输出路径: %s\n", edges_path_.c_str());
        return;
    }
    if (csv_header_) fout << "src_global,dst_global,weight\n";

    std::mt19937 rng(seed_);

    uint64_t edges = 0, tokens = 0;
    for (const auto& tr : trs) {
        if (tr.src.b < tr.src.a || tr.dst.b < tr.dst.a) continue;
        std::vector<uint32_t> dst_pes;
        for (uint32_t p = tr.dst.a; p <= tr.dst.b; ++p) dst_pes.push_back(p);
        const uint32_t cnt = (uint32_t) dst_pes.size();
        if (cnt == 0) continue;
        for (uint32_t src_pe = tr.src.a; src_pe <= tr.src.b; ++src_pe) {
            uint32_t off = (selection_ == "round_robin") ? (src_pe - tr.src.a) % cnt
                                                          : 0u; // 其他策略后续补充
            uint32_t choose = std::min(top_k_, cnt);
            for (uint32_t row = 0; row < rows_per_pe_; ++row) {
                uint32_t src_global = src_pe * rows_per_pe_ + row;
                for (uint32_t i = 0; i < choose; ++i) {
                    uint32_t dst_pe = dst_pes[(off + i) % cnt];
                    uint32_t dst_global = dst_pe * rows_per_pe_ + row;
                    fout << src_global << "," << dst_global << "," << weight_value_ << "\n";
                    edges++;
                }
                tokens++;
            }
        }
    }
    if (stat_edges_) stat_edges_->addData(edges);
    if (stat_tokens_) stat_tokens_->addData(tokens);
    out_->verbose(CALL_INFO, 1, 0, "✅ 生成门控CSV: %s (edges=%" PRIu64 ", tokens=%" PRIu64 ")\n",
                  edges_path_.c_str(), edges, tokens);
}

bool GatingPE::parseTargets(const std::string& s, std::vector<uint32_t>& out) {
    // format: a-b,c,d-e
    out.clear();
    std::istringstream ss(s);
    std::string tok;
    while (std::getline(ss, tok, ',')) {
        trimAsciiInplace_(tok);
        if (tok.empty()) continue;
        size_t dash = tok.find('-');
        if (dash == std::string::npos) {
            uint32_t v = 0;
            if (!parseU32Strict_(tok, v)) {
                if (out_) out_->verbose(CALL_INFO, 1, 0, "⚠️ gate_targets项解析失败: '%s'\n", tok.c_str());
                return false;
            }
            out.push_back(v);
        } else {
            uint32_t a = 0, b = 0;
            if (!parseU32Strict_(tok.substr(0, dash), a) ||
                !parseU32Strict_(tok.substr(dash + 1), b)) {
                if (out_) out_->verbose(CALL_INFO, 1, 0, "⚠️ gate_targets范围解析失败: '%s'\n", tok.c_str());
                return false;
            }
            if (b < a) {
                if (out_) out_->verbose(CALL_INFO, 1, 0, "⚠️ gate_targets范围无效(右端小于左端): '%s'\n", tok.c_str());
                return false;
            }
            for (uint32_t x=a; x<=b; ++x) out.push_back(x);
        }
    }
    return !out.empty();
}

bool GatingPE::onEmitTick(SST::Cycle_t) {
    if (!nic_) return false;
    // 解析一次targets
    if (parsed_targets_.empty()) parseTargets(gate_targets_, parsed_targets_);
    // 解析一次transitions
    if (parsed_transitions_.empty()) parseTransitions(transitions_, parsed_transitions_);
    if (parsed_targets_.empty() || parsed_transitions_.empty()) return false;

    // 简单轮转：每个目标源PE发一个决策（src_row按emit_sent_轮转）
    uint32_t row = (rows_per_pe_ == 0) ? 0u : (uint32_t)(emit_sent_ % rows_per_pe_);
    for (uint32_t src_pe : parsed_targets_) {
        // 找到对应的dst范围
        std::vector<uint32_t> dst_pes;
        for (auto &tr : parsed_transitions_) if (src_pe >= tr.src.a && src_pe <= tr.src.b) {
            for (uint32_t p=tr.dst.a; p<=tr.dst.b; ++p) dst_pes.push_back(p);
        }
        if (dst_pes.empty()) continue;
        // 选Top-k（round-robin起点）
        uint32_t cnt = (uint32_t)dst_pes.size();
        uint32_t choose = std::min(top_k_, cnt);
        uint32_t off = (src_pe + (uint32_t)emit_sent_) % cnt;
        std::vector<uint32_t> pick; pick.reserve(choose);
        for (uint32_t i=0;i<choose;i++) pick.push_back(dst_pes[(off+i)%cnt]);
        // 组包并发送
        auto* ev = new GatingDecisionEvent();
        ev->token_id = (uint32_t)emit_sent_;
        ev->src_pe = src_pe;
        ev->src_row = row;
        ev->top_k = choose;
        ev->ttl_cycles = 1000; // 简易TTL，可加入参数化
        ev->dest_pes = pick;
        if (auto* nic_impl = dynamic_cast<SnnNIC*>(nic_)) {
            if (nic_impl->sendControl(ev, src_pe)) {
                if (stat_evt_sent_) stat_evt_sent_->addData(1);
            } else {
                delete ev; // 发送失败，避免泄漏
            }
        } else {
            delete ev;
        }
    }
    emit_sent_++;
    if (emit_count_ > 0 && emit_sent_ >= emit_count_) return true; // 停止
    return false; // 继续
}
