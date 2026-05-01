// GatherBufferIF.cc: GAS-aware StandardMem front-end with scratchpad buffering

#include <sst/core/sst_config.h>
#include "GatherBufferIF.h"

#include <algorithm>
#include <cstring>
#include <cmath>
#include <fstream>
#include <cstdlib>
#include <cstdio>
#include <mutex>

#include "gather/GatherBufferIFConfig.h"
#include "components/gather/apply/DramCmdCostMergeModel.h"
#include "SnnDLStringUtil.h"

using namespace SST;
using namespace SST::Interfaces;
using namespace SST::SnnDL;

namespace {

struct P2ApplySpreadAgg {
    uint64_t samples = 0;
    uint64_t sum_apply_cycles = 0;
    uint64_t min_apply_cycles = 0;
    uint64_t max_apply_cycles = 0;
};

std::mutex g_p2_apply_spread_mu;
std::unordered_map<uint64_t, P2ApplySpreadAgg> g_p2_apply_spread_by_gid;

void p2RecordApplySpreadSample(uint64_t gather_id, uint64_t apply_cycles) {
    if (apply_cycles == 0) return;
    std::lock_guard<std::mutex> lk(g_p2_apply_spread_mu);
    auto& agg = g_p2_apply_spread_by_gid[gather_id];
    if (agg.samples == 0) {
        agg.samples = 1;
        agg.sum_apply_cycles = apply_cycles;
        agg.min_apply_cycles = apply_cycles;
        agg.max_apply_cycles = apply_cycles;
    } else {
        agg.samples += 1;
        agg.sum_apply_cycles += apply_cycles;
        if (apply_cycles < agg.min_apply_cycles) agg.min_apply_cycles = apply_cycles;
        if (apply_cycles > agg.max_apply_cycles) agg.max_apply_cycles = apply_cycles;
    }
    if (gather_id > 32) {
        const uint64_t keep_from = gather_id - 32;
        for (auto it = g_p2_apply_spread_by_gid.begin(); it != g_p2_apply_spread_by_gid.end();) {
            if (it->first < keep_from) it = g_p2_apply_spread_by_gid.erase(it);
            else ++it;
        }
    }
}

bool p2QueryApplySpread(uint64_t gather_id, uint64_t* out_samples, uint64_t* out_spread_permille) {
    if (!out_samples || !out_spread_permille) return false;
    std::lock_guard<std::mutex> lk(g_p2_apply_spread_mu);
    auto it = g_p2_apply_spread_by_gid.find(gather_id);
    if (it == g_p2_apply_spread_by_gid.end()) return false;
    const P2ApplySpreadAgg& agg = it->second;
    if (agg.samples == 0 || agg.sum_apply_cycles == 0) return false;
    const uint64_t mean = agg.sum_apply_cycles / agg.samples;
    if (mean == 0) return false;
    uint64_t spread_permille = 0;
    if (agg.max_apply_cycles > agg.min_apply_cycles) {
        spread_permille =
            ((agg.max_apply_cycles - agg.min_apply_cycles) * 1000ull + (mean / 2ull)) / mean;
    }
    *out_samples = agg.samples;
    *out_spread_permille = spread_permille;
    return true;
}

} // namespace

// P2: 移除TU级别的 getenv 依赖；改为构造期解析的成员 debug/diag 标志

GatherBufferIF::GatherBufferIF(ComponentId_t id, Params& params, TimeConverter* time, HandlerBase* handler)
    : StandardMem(id, params, time, handler), time_(time), upstream_handler_(handler)
{
    setDefaultTimeBase(*time);
    const GatherBufferIFConfig cfg = parseGatherBufferIFConfig(params);

    // P2: 解析 diag/debug/sentinel（参数优先；未设置回退环境变量）
    // P2 Step3：移除 getenv 回退，仅参数驱动（默认禁用）
    diag_enable_ = cfg.diag_enable;
    debug_enable_ = cfg.debug_enable;
    sentinel_enable_ = cfg.sentinel_enable;
    experimental_stepgate_progress_enable_ = cfg.experimental_stepgate_progress_enable;
    experimental_stepgate_progress_period_cycles_ = cfg.experimental_stepgate_progress_period_cycles;
    experimental_stepgate_progress_max_reports_ = cfg.experimental_stepgate_progress_max_reports;
    experimental_stepgate_progress_dump_level_ = cfg.experimental_stepgate_progress_dump_level;
    experimental_stepgate_progress_owner_node_ = cfg.experimental_stepgate_progress_owner_node;
    experimental_stepgate_progress_owner_core_ = cfg.experimental_stepgate_progress_owner_core;
    experimental_stepgate_apply_finish_poll_period_cycles_ = cfg.experimental_stepgate_apply_finish_poll_period_cycles;
    if (experimental_stepgate_apply_finish_poll_period_cycles_ == 0) {
        experimental_stepgate_apply_finish_poll_period_cycles_ = 1;
    }

    out_.init("GatherBufferIF[@p:@l]: ", cfg.verbose, 0, Output::STDOUT);

    // Dense microbench correctness: byte-exact verification (optional).
    byte_exact_verify_enable_ = cfg.byte_exact_verify_enable;
    byte_exact_verify_mode_ = cfg.byte_exact_verify_mode;
    byte_exact_verify_row_scale_ = cfg.byte_exact_verify_row_scale;
    byte_exact_verify_max_mismatch_ = cfg.byte_exact_verify_max_mismatch;
    byte_exact_base_addr_ = cfg.byte_exact_verify_base_addr;
    byte_exact_rows_ = cfg.byte_exact_verify_rows;
    byte_exact_cols_ = cfg.byte_exact_verify_cols;
    byte_exact_dense_layout_mode_ = cfg.byte_exact_dense_layout_mode;
    byte_exact_dense_phys_dram_row_bytes_ = cfg.byte_exact_dense_phys_dram_row_bytes;
    byte_exact_file_path_ = cfg.byte_exact_verify_file_path;
    byte_exact_sample_bytes_ = cfg.byte_exact_verify_sample_bytes;
    byte_exact_max_resps_ = cfg.byte_exact_verify_max_resps;
    byte_exact_owner_node_ = cfg.byte_exact_verify_owner_node;
    byte_exact_owner_core_ = cfg.byte_exact_verify_owner_core;
    byte_exact_rowptr_offset_ = cfg.byte_exact_verify_rowptr_offset;
    byte_exact_colidx_offset_ = cfg.byte_exact_verify_colidx_offset;
    byte_exact_blockdata_offset_ = cfg.byte_exact_verify_blockdata_offset;
    if (byte_exact_verify_enable_) {
        out_.verbose(CALL_INFO, 1, 0,
            "[byte-exact] GatherBufferIF enabled=1 mode=%s base=0x%llx rows=%u cols=%u row_scale=%u max_mismatch=%u\n",
            byte_exact_verify_mode_.c_str(),
            (unsigned long long)byte_exact_base_addr_,
            byte_exact_rows_, byte_exact_cols_,
            byte_exact_verify_row_scale_, byte_exact_verify_max_mismatch_);
    }
    // raw_bcsr_v1: open file early (best-effort validation is still gated later).
    if (byte_exact_verify_enable_ && toLowerCopy(byte_exact_verify_mode_) == "raw_bcsr_v1") {
        // Default behavior: allow enabling on a single target node/core via owner filters.
        if ((byte_exact_owner_node_ >= 0 && (int)cfg.node_id != byte_exact_owner_node_) ||
            (byte_exact_owner_core_ >= 0 && (int)cfg.core_id != byte_exact_owner_core_)) {
            byte_exact_verify_enable_ = false;
        } else {
            if (byte_exact_file_path_.empty()) {
                out_.fatal(CALL_INFO, -1, "raw_bcsr_v1 requires byte_exact_verify_file_path\n");
            }
            if (byte_exact_base_addr_ == 0) {
                out_.fatal(CALL_INFO, -1, "raw_bcsr_v1 requires byte_exact_verify_base_addr\n");
            }
            byte_exact_file_.open(byte_exact_file_path_, std::ios::in | std::ios::binary);
            if (!byte_exact_file_.good()) {
                out_.fatal(CALL_INFO, -1, "raw_bcsr_v1 failed to open file: %s\n", byte_exact_file_path_.c_str());
            }
            byte_exact_file_.seekg(0, std::ios::end);
            byte_exact_file_size_ = (uint64_t)byte_exact_file_.tellg();
            byte_exact_file_.seekg(0, std::ios::beg);
            if (byte_exact_file_size_ == 0) {
                out_.fatal(CALL_INFO, -1, "raw_bcsr_v1 file size is 0: %s\n", byte_exact_file_path_.c_str());
            }
            byte_exact_region_verified_mask_ = 0;
            byte_exact_inconclusive_ = false;
            byte_exact_inconclusive_reason_.clear();
            const bool offsets_sane =
                (byte_exact_colidx_offset_ > byte_exact_rowptr_offset_) &&
                (byte_exact_colidx_offset_ < byte_exact_file_size_) &&
                (byte_exact_blockdata_offset_ > byte_exact_colidx_offset_) &&
                (byte_exact_blockdata_offset_ < byte_exact_file_size_);
            if (!offsets_sane) {
                byte_exact_inconclusive_ = true;
                byte_exact_inconclusive_reason_ = "meta_offsets_unsane_or_missing";
            }
            out_.verbose(CALL_INFO, 1, 0,
                "[byte-exact] raw_bcsr_v1 enabled: node=%u core=%u file=%s size=%" PRIu64 " sample_bytes=%u max_resps=%u\n",
                cfg.node_id, cfg.core_id, byte_exact_file_path_.c_str(),
                byte_exact_file_size_, byte_exact_sample_bytes_, byte_exact_max_resps_);
        }
    }

    merge_ = parseMerge(cfg.merge_policy);
    sort_  = parseSort(cfg.sort_policy);
    row_bytes_guess_ = cfg.row_bytes_guess;
    row_bytes_effective_ = row_bytes_guess_;
    sram_bytes_ = cfg.sram_bytes;
    gap_merge_enable_ = cfg.gap_merge_enable;
    gap_k_bytes_ = cfg.gap_merge_k_bytes;
    burst_bytes_max_ = cfg.burst_bytes_max;
    vlf_enable_ = cfg.vlf_enable;
    vlf_run_enable_ = cfg.vlf_run_enable;
    bank_bits_ = cfg.bank_bits;
    bank_shift_ = cfg.bank_shift;
    bank_auto_enable_ = cfg.bank_auto_enable;
    bank_auto_min_banks_ = cfg.bank_auto_min_banks;
    bank_auto_max_banks_ = cfg.bank_auto_max_banks;
    apply_issue_policy_ = parseApplyIssuePolicy(cfg.apply_issue_policy);
    dram_cmd_cost_merge_enable_ = cfg.dram_cmd_cost_merge_enable;
    dram_cmd_t_row_hit_ns_ = cfg.dram_cmd_t_row_hit_ns;
    dram_cmd_t_row_miss_ns_ = cfg.dram_cmd_t_row_miss_ns;
    if (dram_cmd_t_row_hit_ns_ == 0) dram_cmd_t_row_hit_ns_ = 1;
    if (dram_cmd_t_row_miss_ns_ < dram_cmd_t_row_hit_ns_) {
        dram_cmd_t_row_miss_ns_ = dram_cmd_t_row_hit_ns_;
    }
    apply_frags_per_issue_ = cfg.apply_frags_per_issue;
    apply_bank_credit_ = cfg.apply_bank_credit;
    apply_age_fair_ns_ = cfg.apply_age_fair_ns;
    apply_bank_credit_dyn_ = apply_bank_credit_;
    row_window_enable_ = cfg.row_window_enable;
    row_window_bytes_  = cfg.row_window_bytes;
    row_window_timeout_ns_ = cfg.row_window_timeout_ns;
    sram_access_ns_ = cfg.sram_access_ns;
    max_inflight_reads_ = cfg.max_inflight_reads;
    tail_wait_timeout_ns_ = cfg.tail_wait_timeout_ns;
    allow_apply_miss_read_ = cfg.allow_apply_miss_read;
    flush_after_scatter_ = cfg.flush_after_scatter;
    strict_mode_ = cfg.strict_mode;
    double_buffer_enable_ = cfg.double_buffer_enable;
    window_auto_ = cfg.window_auto;
    step_gate_enable_ = cfg.step_gate_enable;
    // Deprecate manual_window_drive: keep param for compatibility but force-disable
    (void)cfg.manual_window_drive_ignored;
    win_cyc_gather_ = cfg.window_cycles_gather;
    win_cyc_apply_  = cfg.window_cycles_apply;
    win_cyc_scatter_= cfg.window_cycles_scatter;
    apply_auto_end_enable_ = cfg.apply_auto_end_enable;
    scatter_immediate_complete_ = cfg.scatter_immediate_complete;
    clock_freq_ = cfg.clock;
    emit_stage_events_ = cfg.emit_stage_events;
    emit_lenient_ = cfg.emit_stage_events_lenient;
    if (step_gate_enable_ && !emit_stage_events_) {
        out_.fatal(CALL_INFO, -1,
                   "GatherBufferIF fatal: step_gate_enable=1 requires emit_stage_events=1 (needed for global step synchronization)\n");
    }
    if (step_gate_enable_ && emit_lenient_) {
        out_.fatal(CALL_INFO, -1,
                   "GatherBufferIF fatal: step_gate_enable=1 forbids emit_stage_events_lenient=1 (would allow step to advance with inflight traffic)\n");
    }
    stage_cycles_csv_ = cfg.stage_cycles_csv;
    stage_cycles_export_enable_ = !stage_cycles_csv_.empty();
    probe_csv_path_ = cfg.probe_gas_csv;
    defer_issue_until_apply_ = cfg.defer_issue_until_apply;
    gather_auto_end_bytes_ = cfg.gather_auto_end_bytes;
    gather_auto_end_reads_ = cfg.gather_auto_end_reads;
    // Gating: if k or Lmax invalid, disable gap merge
    if (!gap_merge_enable_ || gap_k_bytes_ == 0 || burst_bytes_max_ == 0) {
        gap_merge_enable_ = false;
    }

    // Load downstream memHierarchy.standardInterface anonymously, sharing our 'lowlink' port
    Params bp; bp.insert("port", std::string("lowlink"));
    backend_ = loadAnonymousSubComponent<SST::Interfaces::StandardMem>(
        "memHierarchy.standardInterface", "lowlink", 0,
        ComponentInfo::SHARE_PORTS | ComponentInfo::INSERT_STATS,
        bp, time_, new StandardMem::Handler2<GatherBufferIF, &GatherBufferIF::onDownstreamResp_>(this));
    if (!backend_) {
        out_.fatal(CALL_INFO, -1, "Failed to load downstream memHierarchy.standardInterface\n");
    }
    // Stats registration
    stat_unique_reads_ = registerStatistic<uint64_t>("gas_unique_reads");
    stat_unique_bytes_ = registerStatistic<uint64_t>("gas_unique_bytes");
    stat_up_reads_     = registerStatistic<uint64_t>("gas_upstream_reads");
    stat_evictions_    = registerStatistic<uint64_t>("gas_evictions");
    stat_inflight_peak_= registerStatistic<uint64_t>("gas_inflight_peak");
    stat_tail_wait_ns_ = registerStatistic<uint64_t>("gas_tail_wait_ns");
    stat_stage_cycles_g_ = registerStatistic<uint64_t>("gas_stage_cycles_gather");
    stat_stage_cycles_a_ = registerStatistic<uint64_t>("gas_stage_cycles_apply");
    stat_stage_cycles_s_ = registerStatistic<uint64_t>("gas_stage_cycles_scatter");
    stat_coalesce_granule_size_ = registerStatistic<uint64_t>("gas_req_coalesce_size_bytes");
    stat_buffer_occupancy_bytes_ = registerStatistic<uint64_t>("gas_buffer_occupancy_bytes");
    stat_gap_absorbed_bytes_ = registerStatistic<uint64_t>("gas_gap_absorbed_bytes");
    stat_row_window_triggers_ = registerStatistic<uint64_t>("gas_row_window_triggers");
    stat_row_window_bytes_    = registerStatistic<uint64_t>("gas_row_window_bytes");
    stat_cmd_cost_veto_       = registerStatistic<uint64_t>("gas_cmd_cost_veto");
    stat_cmd_cost_veto_fine_gap_ = registerStatistic<uint64_t>("gas_cmd_cost_veto_fine_gap");
    stat_cmd_cost_veto_row_window_ = registerStatistic<uint64_t>("gas_cmd_cost_veto_row_window");
    // Segment diagnostics.
    stat_overfetch_bytes_     = registerStatistic<uint64_t>("gas_overfetch_bytes");
    stat_unique_line_count_   = registerStatistic<uint64_t>("gas_unique_line_count");
    stat_covered_line_count_  = registerStatistic<uint64_t>("gas_covered_line_count");
    stat_apply_bank_credit_effective_ = registerStatistic<uint64_t>("gas_apply_bank_credit_effective");
    // 门控诊断：下发到下游的唯一granule读次数
    stat_reads_issued_        = registerStatistic<uint64_t>("gas_reads_issued");
    // Adaptive k stats (optional)
    stat_k_dyn_bytes_         = registerStatistic<uint64_t>("gas_k_dyn_bytes");
    stat_oeff_ns_avg_         = registerStatistic<uint64_t>("gas_oeff_ns_avg");
    stat_bw_eff_bytes_per_us_ = registerStatistic<uint64_t>("gas_bw_eff_bytes_per_us");
    // Control stats
    stat_ctrl_probes_  = registerStatistic<uint64_t>("gas_ctrl_probes");
    stat_ctrl_adopts_  = registerStatistic<uint64_t>("gas_ctrl_adopts");
    stat_ctrl_reverts_ = registerStatistic<uint64_t>("gas_ctrl_reverts");
    inflight_down_.reserve(128);
    queued_non_gather_reads_.reserve(32);
    last_stage_change_ns_ = getCurrentSimTimeNano();
    // Adaptive k params
    k_adapt_enable_   = cfg.k_adapt_enable;
    k_adapt_window_N_ = cfg.k_adapt_window_N;
    k_alpha_bw_       = cfg.k_alpha_bw;
    k_alpha_k_        = cfg.k_alpha_k;
    k_min_bytes_      = cfg.k_min_bytes;
    k_max_bytes_      = cfg.k_max_bytes;
    k_delta_bytes_    = cfg.k_delta_bytes;
    // Adaptive control params
    ctrl_enable_ = cfg.ctrl_enable;
    ctrl_probe_every_N_ = cfg.ctrl_probe_every_N;
    ctrl_cooldown_N_ = cfg.ctrl_cooldown_N;
    ctrl_eps_reqs_ = cfg.ctrl_eps_reqs;
    ctrl_eps_burst_ = cfg.ctrl_eps_burst;
    ctrl_lat_tol_ns_ = cfg.ctrl_lat_tol_ns;
    ctrl_k_list_ = parseCsvU64_(cfg.ctrl_k_list);
    ctrl_rowwin_list_ = parseCsvU64_(cfg.ctrl_rowwin_list);
    ctrl_timeout_list_ = parseCsvU64_(cfg.ctrl_timeout_list);
    // Initial control cfg from current params
    ctrl_curr_cfg_.k = gap_k_bytes_;
    ctrl_curr_cfg_.rowwin_bytes = row_window_bytes_;
    ctrl_curr_cfg_.timeout_ns = row_window_timeout_ns_;

    // P1-2: granule export CSV (optional)
    export_granules_csv_ = cfg.export_granules_csv;
    node_id_param_ = cfg.node_id;
    core_id_param_ = cfg.core_id;
    export_window_metrics_csv_ = cfg.export_window_metrics_csv;

    resetGatherAutoCounters_();
}

GatherBufferIF::~GatherBufferIF() {
    if (!export_window_metrics_csv_.empty() && !window_metrics_written_) {
        exportWindowMetricsRow_(current_gather_id_, win_payload_bytes_, win_bursts_, win_inflight_peak_, win_buffer_max_bytes_);
    }
}

void GatherBufferIF::init(unsigned int phase) {
    backend_->init(phase);
    // 记录所有 phase 的初始化情况（仅在显式启用时打印）
    if (sentinel_enable_) {
        out_.verbose(CALL_INFO, 2, 0,
            "[[sentinel-gbi-init]] phase=%u window_auto=%d manual=%d clock=%s win_cyc_g=%" PRIu64 " win_cyc_a=%" PRIu64 " win_cyc_s=%" PRIu64 " auto_bytes=%" PRIu64 " auto_reads=%" PRIu64 " defer=%d\n",
            phase, window_auto_ ? 1 : 0, 0, clock_freq_.c_str(),
            win_cyc_gather_, win_cyc_apply_, win_cyc_scatter_,
            gather_auto_end_bytes_, gather_auto_end_reads_, defer_issue_until_apply_ ? 1 : 0);
    }
    if (phase == 0 && window_auto_) {
        if (out_.getVerboseLevel() >= 2) {
            out_.verbose(CALL_INFO, 2, 0,
                "[diag-gbi-init] window_auto=%d manual=%d(clock-forced) clock=%s win_cyc_g=%" PRIu64 " win_cyc_a=%" PRIu64 " win_cyc_s=%" PRIu64 " auto_bytes=%" PRIu64 " auto_reads=%" PRIu64 " defer=%d\n",
                window_auto_ ? 1 : 0, 0, clock_freq_.c_str(), win_cyc_gather_, win_cyc_apply_, win_cyc_scatter_,
                gather_auto_end_bytes_, gather_auto_end_reads_, defer_issue_until_apply_ ? 1 : 0);
        }
        // Always register clock for time-driven windows (manual drive deprecated)
        registerClock(clock_freq_, new Clock::Handler2<GatherBufferIF, &GatherBufferIF::clockTick>(this));
        resetWindowMetrics_();
        resetGatherAutoCounters_();
        stage_counter_ = 0;
        if (step_gate_enable_) {
            // Step-level gate: 等待上层 openStep(seq) 显式打开窗口
            stage_ = Stage::Idle;
        } else {
            stage_ = Stage::Gather;
            current_gather_id_++;
            if (emit_stage_events_ && upstream_handler_) {
                auto* ev = new GasOpData(GasOp::BeginGather, (uint32_t)current_gather_id_, 0, 1, false);
                auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, ev, 0, 0, 0);
                (*upstream_handler_)(cr);
            }
        }
        sb_[gather_buf_index_].end_gather_seen = false;
    }
}

void GatherBufferIF::complete(unsigned int phase) {
    backend_->complete(phase);
}

void GatherBufferIF::setup() { backend_->setup(); }

void GatherBufferIF::finish() {
    finishByteExact_();
    if (!export_window_metrics_csv_.empty() && !window_metrics_written_) {
        exportWindowMetricsRow_(current_gather_id_, win_payload_bytes_, win_bursts_, win_inflight_peak_, win_buffer_max_bytes_);
    }
    backend_->finish();
}

void GatherBufferIF::sendUntimedData(Request* req) { backend_->sendUntimedData(req); }

StandardMem::Request* GatherBufferIF::recvUntimedData() { return backend_->recvUntimedData(); }

StandardMem::Addr GatherBufferIF::getLineSize() { return backend_ ? backend_->getLineSize() : 64; }

void GatherBufferIF::setMemoryMappedAddressRegion(Addr start, Addr size) {
    if (backend_) backend_->setMemoryMappedAddressRegion(start, size);
}

void GatherBufferIF::manualWindowTick() {
    // Deprecated no-op for legacy compatibility.
    return;
}

void GatherBufferIF::setApplyBankCreditTarget(uint32_t seq, uint32_t apply_bank_credit) {
    if (seq == 0) return;
    apply_credit_external_enable_ = true;
    apply_credit_external_pending_seq_ = seq;
    apply_credit_external_pending_credit_ = apply_bank_credit;
}

void GatherBufferIF::openStep(uint32_t seq) {
    if (!step_gate_enable_) return;
    if (!window_auto_) {
        out_.fatal(CALL_INFO, -1, "GatherBufferIF fatal: openStep requires window_auto=1\n");
        return;
    }
    if (experimental_stepgate_progress_enable_) {
        const bool owner_ok =
            (experimental_stepgate_progress_owner_node_ < 0 || (int)node_id_param_ == experimental_stepgate_progress_owner_node_) &&
            (experimental_stepgate_progress_owner_core_ < 0 || (int)core_id_param_ == experimental_stepgate_progress_owner_core_);
        const bool cap_ok =
            (experimental_stepgate_progress_max_reports_ == 0 ||
             experimental_stepgate_progress_reports_ < experimental_stepgate_progress_max_reports_);
        if (owner_ok && cap_ok) {
            out_.verbose(
                CALL_INFO, 0, 0,
                "[exp-gbi-stepgate] openStep seq=%u node=%u core=%u stage=%d cur_gid=%" PRIu64
                " inflight0=%" PRIu64 " inflight1=%" PRIu64 " down=%zu\n",
                (unsigned)seq, node_id_param_, core_id_param_, (int)stage_,
                (uint64_t)current_gather_id_,
                (uint64_t)inflight_counts_[0], (uint64_t)inflight_counts_[1], inflight_down_.size());
        }
    }
    if (seq == 0) {
        out_.fatal(CALL_INFO, -1, "GatherBufferIF fatal: openStep(seq=0) invalid\n");
        return;
    }
    if (stage_ != Stage::Idle) {
        out_.fatal(CALL_INFO, -1,
                   "GatherBufferIF fatal: openStep called while stage=%d (expected Idle)\n",
                   (int)stage_);
        return;
    }
    if (!inflight_down_.empty() ||
        inflight_counts_[0] != 0 ||
        inflight_counts_[1] != 0) {
        out_.fatal(CALL_INFO, -1,
                   "GatherBufferIF fatal: openStep with inflight not drained (down=%zu inflight0=%" PRIu64 " inflight1=%" PRIu64 ")\n",
                   inflight_down_.size(),
                   (uint64_t)inflight_counts_[0],
                   (uint64_t)inflight_counts_[1]);
        return;
    }
    if (current_gather_id_ != 0 && seq <= current_gather_id_) {
        out_.fatal(CALL_INFO, -1,
                   "GatherBufferIF fatal: non-monotonic openStep seq=%u current_gather_id=%" PRIu64 "\n",
                   seq, current_gather_id_);
        return;
    }

    // 保护：新的 gather 缓冲必须是干净的（step gate 模式下禁止跨窗预构建）
    if (!sb_[gather_buf_index_].granules.empty() ||
        !sb_[gather_buf_index_].required_set.empty() ||
        !sb_[gather_buf_index_].pending_up_reads.empty() ||
        !sb_[gather_buf_index_].staging_reads.empty()) {
        out_.fatal(CALL_INFO, -1,
                   "GatherBufferIF fatal: openStep expects clean gather buffer (buf=%d granules=%zu req=%zu pending_up=%zu staging=%zu)\n",
                   gather_buf_index_,
                   sb_[gather_buf_index_].granules.size(),
                   sb_[gather_buf_index_].required_set.size(),
                   sb_[gather_buf_index_].pending_up_reads.size(),
                   sb_[gather_buf_index_].staging_reads.size());
        return;
    }

    if (step_gate_wait_cycles_pending_ > 0 && upstream_handler_) {
        auto* s = new GasStatData(seq, 0, 0);
        s->stall_on_step_gate_cycles = step_gate_wait_cycles_pending_;
        auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, s, 0, 0, 0);
        (*upstream_handler_)(cr);
        step_gate_wait_cycles_pending_ = 0;
    }

    current_gather_id_ = seq;
    // Apply external credit target (if any) at the step boundary.
    if (apply_credit_external_enable_ && apply_credit_external_pending_seq_ == seq) {
        if (apply_credit_external_pending_credit_ > 0) {
            apply_bank_credit_dyn_ = apply_credit_external_pending_credit_;
        }
        apply_credit_external_pending_seq_ = 0;
        apply_credit_external_pending_credit_ = 0;
    }
    stage_ = Stage::Gather;
    stage_counter_ = 0;
    resetWindowMetrics_();
    resetGatherAutoCounters_();
    sb_[gather_buf_index_].end_gather_seen = false;

    if (emit_stage_events_ && upstream_handler_) {
        auto* ev = new GasOpData(GasOp::BeginGather, (uint32_t)current_gather_id_, 0, 1, false);
        auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, ev, 0, 0, 0);
        (*upstream_handler_)(cr);
    }

    // 将非Gather阶段拦截的读请求归属到本窗口并下发（与原 EndScatter->BeginGather 行为保持一致）
    if (!drainQueuedNonGatherReadsToGather_(ReadAttachKind::OpenStep, seq, (int)stage_)) {
        return;
    }
}

void GatherBufferIF::send(Request* req) {
    // Control-plane: CustomReq
    if (auto* cr = dynamic_cast<StandardMem::CustomReq*>(req)) {
        auto* data = dynamic_cast<GasOpData*>(&cr->getData());
        if (data) {
            // In auto mode, most external GasOp control requests are ignored (manual drive deprecated).
            // Exception: in step-gate mode we accept EndGather/EndScatter as "explicit end handshake"
            // so Gather/Scatter can be load-driven and globally synchronized.
            if (window_auto_) {
                const bool allow_explicit_end = step_gate_enable_ &&
                                                (data->op == GasOp::EndGather || data->op == GasOp::EndScatter);
                if (!allow_explicit_end) {
                    if (!warned_auto_custom_req_ && diagEnabled_()) {
                        warned_auto_custom_req_ = true;
                        out_.verbose(CALL_INFO, 2, 0,
                            "[diag-gbi] CustomReq ignored: window_auto=1 manual_drive=0 (logged once)");
                    }
                    delete req;
                    return;
                }

                if (data->op == GasOp::EndGather) {
                    // Tolerant in mixed modes: if Gather already ended (cycle fallback), ignore late EndGather.
                    if (stage_ != Stage::Gather) { delete req; return; }
                    if (data->superstep == 0 || static_cast<uint64_t>(data->superstep) != current_gather_id_) {
                        delete req;
                        return;
                    }
                    // Latch end_gather_seen; clockTick will advance to Apply (avoid re-entrancy).
                    sb_[gather_buf_index_].end_gather_seen = true;
                    tail_wait_start_ns_ = getCurrentSimTimeNano();
                    delete req;
                    return;
                }

                if (data->op == GasOp::EndScatter) {
                    if (data->superstep == 0 || static_cast<uint64_t>(data->superstep) != current_gather_id_) {
                        delete req;
                        return;
                    }
                    // Ignore late EndScatter after we already returned to Idle.
                    if (stage_ == Stage::Idle) { delete req; return; }
                    if (end_scatter_req_pending_ && end_scatter_req_seq_ == data->superstep) {
                        delete req;
                        return;
                    }
                    // Latch early EndScatter and consume when Scatter stage is reached.
                    if (stage_ != Stage::Scatter) {
                        end_scatter_early_count_++;
                        if (!warned_end_scatter_early_) {
                            warned_end_scatter_early_ = true;
                            out_.verbose(CALL_INFO, 0, 0,
                                "[warn-gbi] step_gate EndScatter arrived early (stage=%d); latched for Scatter (count=%" PRIu64 ")\n",
                                (int)stage_, (uint64_t)end_scatter_early_count_);
                        }
                    }
                    // Latch and let clockTick emit EndScatter + advance (avoid recursive callbacks).
                    end_scatter_req_pending_ = true;
                    end_scatter_req_seq_ = data->superstep;
                    delete req;
                    return;
                }
            }
            if (out_.getVerboseLevel() >= 1) {
                out_.verbose(CALL_INFO, 1, 0,
                    "[diag-gbi] CustomReq op=%d (manual=%d) stage=%d gid=%" PRIu64 "\n",
                    (int)data->op, 0, (int)stage_, current_gather_id_);
            }
            switch (data->op) {
                case GasOp::BeginGather:
                    stage_ = Stage::Gather; sb_[gather_buf_index_].end_gather_seen = false; current_gather_id_++;
                    resetGatherAutoCounters_();
                    sb_[gather_buf_index_].granules.clear(); sb_[gather_buf_index_].required_set.clear();
                    sb_[gather_buf_index_].issue_order.clear();
                    sb_[gather_buf_index_].issue_cursor = 0;
                    sb_[gather_buf_index_].issue_order_dirty = true;
                    // 将非Gather阶段缓存的读导入当前Gather窗口
                    if (!drainQueuedNonGatherReadsToGather_(ReadAttachKind::ManualBeginGather, 0, (int)stage_)) {
                        return;
                    }
                    break;
                case GasOp::EndGather:
                    sb_[gather_buf_index_].end_gather_seen = true; tail_wait_start_ns_ = getCurrentSimTimeNano();
                    if (out_.getVerboseLevel() >= 1) {
                        out_.verbose(CALL_INFO, 1, 0,
                            "[diag-gbi] EndGather recv: granules=%zu required_set=%zu stage=%d\n",
                            sb_[gather_buf_index_].granules.size(), sb_[gather_buf_index_].required_set.size(), (int)stage_);
                    }
                    maybeEnterApply_();
                    break;
                case GasOp::BeginApply:
                    stage_ = Stage::Apply; emitApplyResponsesBuf_(apply_buf_index_); break;
                case GasOp::EndApply:
                    stage_ = Stage::Scatter; if (flush_after_scatter_) doFlushBuf_(apply_buf_index_); stage_ = Stage::Idle; break;
                case GasOp::BeginScatter:
                    stage_ = Stage::Scatter; break;
                case GasOp::EndScatter:
                    if (flush_after_scatter_) doFlushBuf_(apply_buf_index_); stage_ = Stage::Idle; break;
                case GasOp::FlushSRAM:
                    doFlushBuf_(apply_buf_index_); break;
                case GasOp::SetSlice:
                    // no-op for v1
                    break;
            }
            delete req; return;
        }
        // Unknown CustomReq: pass-through
    }

    // Data-plane
    if (auto* rd = dynamic_cast<StandardMem::Read*>(req)) {
        // Noncacheable reads bypass Gather/Apply coalescing & SRAM cache (universal workload support).
        if (rd->getNoncacheable()) {
            backend_->send(req);
            return;
        }
        // Apply 阶段的读属于“当前窗口的 apply_buf”，与 step_gate_enable 无关。
        // 若在 step_gate_enable=1 时把 Apply 读拦到 queued_non_gather_reads_，
        // 会导致 Apply/Scatter 在权重未返回时提前推进，最终出现 dv 全 0/发放归 0。
        bool can_gather_now = (stage_ == Stage::Gather) || (stage_ == Stage::Apply);
        if (can_gather_now) {
            // 回归正确归属：Apply 阶段的读属于当前窗口，应进入 apply_buf。
            // 混入“下一窗口 gather”会导致当前窗口缺权重；但需要额外防御 pending 悬挂。
            int tgt = (stage_ == Stage::Gather) ? gather_buf_index_ : apply_buf_index_;
            sb_[tgt].pending_up_reads[rd->getID()] = rd;
            gather_bytes_accum_ += (uint64_t)rd->size;
            gather_reads_accum_++;
            if (stage_ == Stage::Gather) {
                tryAutoEndGather_();
            }
            // Deferred "collect → build segments → issue" path:
            // - Gather stage: always safe to stage when enabled.
            // - Apply stage: stage is also allowed in window_auto mode, but we MUST ensure clockTick()
            //   will drain staging_reads into granules; otherwise Apply could deadlock.
            const bool allow_staging_in_apply = window_auto_;
            const bool take_staging_path =
                defer_issue_until_apply_ &&
                (gap_merge_enable_ || row_window_enable_ || vlf_enable_) &&
                (stage_ == Stage::Gather || (stage_ == Stage::Apply && allow_staging_in_apply));
            if (defer_issue_until_apply_ && (gap_merge_enable_ || row_window_enable_ || vlf_enable_) &&
                stage_ == Stage::Apply && !window_auto_) {
                static bool warned_defer_apply_requires_clock = false;
                if (!warned_defer_apply_requires_clock) {
                    warned_defer_apply_requires_clock = true;
                    out_.verbose(CALL_INFO, 0, 0,
                        "[warn-gbi] defer_issue_until_apply=1 with window_auto=0: Apply-stage Read cannot be staged; forcing immediate issue for forward progress\n");
                }
            }
            out_.verbose(CALL_INFO, 2, 0,
                "[diag-gbi] send() Read: stage=%d tgt_buf=%d gap_merge=%d defer=%d -> path=%s\n",
                (int)stage_, tgt, (int)gap_merge_enable_, (int)defer_issue_until_apply_,
                take_staging_path ? "STAGING" : "IMMEDIATE");
            if (defer_issue_until_apply_ && take_staging_path && !warned_defer_issue_path_ && diagEnabled_()) {
                warned_defer_issue_path_ = true;
                out_.verbose(CALL_INFO, 2, 0,
                    "[diag-gbi] defer_issue_until_apply=1: upstream Read IDs will be remapped via staged granules (logged once)");
            }
            if (take_staging_path) {
                // Stage later for gap/Lmax (and optional row-window) merging
                sb_[tgt].staging_reads.push_back(rd);
                sb_[tgt].staged_arrival_ns[rd->getID()] = getCurrentSimTimeNano();
            } else {
                // NOTE:
                // - When defer_issue_until_apply_=1, Gather-stage reads are issued at Apply entry after building segments.
                // - Apply-stage reads, however, arrive *after* Apply has already started (e.g. miss-reads / late requests).
                //   They must be issued immediately to guarantee forward progress; otherwise they will sit in granules
                //   without another Apply entry to trigger issuance, causing a deadlock.
                const bool issue_now = (stage_ == Stage::Apply || !defer_issue_until_apply_);
                if (!attachReadToGranule_(tgt, rd, ReadAttachKind::ImmediateSend, issue_now, 0, (int)stage_, tgt)) {
                    return;
                }
            }
            if (stat_up_reads_) stat_up_reads_->addData(1);
            return; // keep rd queued; deletion deferred after we emit ReadResp
        } else {
            if (strict_mode_) { queued_non_gather_reads_.push_back(rd); return; }
            backend_->send(req); return;
        }
    }

    // Writes/flush: pass-through; optionally invalidate overlapping SRAM
    if (auto* wr = dynamic_cast<StandardMem::Write*>(req)) {
        // Invalidate overlapping blocks for both SBs
        for (int b=0;b<2;++b) {
            if (!sb_[b].sram_blocks.empty()) {
                std::vector<GranuleKey> toErase;
                for (auto& kv : sb_[b].sram_blocks) {
                    uint64_t base = kv.first.base; uint32_t sz = kv.first.size;
                    if (!(wr->pAddr + wr->size <= base || wr->pAddr >= base + sz)) toErase.push_back(kv.first);
                }
                for (auto k : toErase) { sb_[b].sram_blocks.erase(k); }
            }
        }
        backend_->send(req); return;
    }

    // Other requests: pass-through
    backend_->send(req);
}

StandardMem::Request* GatherBufferIF::poll() {
    // We use push-based handler; upstream does not poll. Return nullptr.
    return nullptr;
}

// === helpers ===
bool GatherBufferIF::attachReadToGranule_(int tgt_buf,
                                         StandardMem::Read* rd,
                                         ReadAttachKind kind,
                                         bool issue_now,
                                         uint32_t seq,
                                         int stage,
                                         int buf) {
    uint64_t gsz = granuleSize();
    bool use_row = (merge_ == Merge::Row) || (merge_ == Merge::Auto && row_bytes_guess_ > gsz);
    uint64_t base = (merge_ == Merge::Cacheline || (merge_ == Merge::Auto && !use_row))
                        ? alignDown(rd->pAddr, gsz)
                        : (use_row ? alignDown(rd->pAddr, row_bytes_guess_) : rd->pAddr);
    uint32_t sz = (merge_ == Merge::None) ? rd->size : (use_row ? row_bytes_guess_ : gsz);
    uint64_t off = (rd->pAddr >= base) ? (rd->pAddr - base) : 0;
    uint64_t need = off + (uint64_t)rd->size;

    if (need > (uint64_t)sz) {
        const uint64_t align_unit = use_row ? (uint64_t)row_bytes_guess_ : gsz;
        const uint64_t au = (align_unit == 0) ? 64 : align_unit;
        const uint64_t sz_u64 = ((need + au - 1) / au) * au;
        if (sz_u64 > 0xffffffffull) {
            switch (kind) {
                case ReadAttachKind::OpenStep:
                    out_.fatal(CALL_INFO, -1,
                               "GatherBufferIF fatal: openStep computed granule sz too large (seq=%u need=%" PRIu64 " align_unit=%" PRIu64 " sz_u64=%" PRIu64 ")\n",
                               (uint32_t)seq, (uint64_t)need, (uint64_t)au, (uint64_t)sz_u64);
                    return false;
                case ReadAttachKind::ManualBeginGather:
                    out_.fatal(CALL_INFO, -1,
                               "GatherBufferIF fatal: manual BeginGather computed granule sz too large (need=%" PRIu64 " align_unit=%" PRIu64 " sz_u64=%" PRIu64 ")\n",
                               (uint64_t)need, (uint64_t)au, (uint64_t)sz_u64);
                    return false;
                case ReadAttachKind::QueuedImport:
                    out_.fatal(CALL_INFO, -1,
                               "GatherBufferIF fatal: queued computed granule sz too large (need=%" PRIu64 " align_unit=%" PRIu64 " sz_u64=%" PRIu64 ")\n",
                               (uint64_t)need, (uint64_t)au, (uint64_t)sz_u64);
                    return false;
                case ReadAttachKind::ImmediateSend:
                    out_.fatal(CALL_INFO, -1,
                               "GatherBufferIF fatal: computed granule sz too large (need=%" PRIu64 " align_unit=%" PRIu64 " sz_u64=%" PRIu64 ")\n",
                               (uint64_t)need, (uint64_t)au, (uint64_t)sz_u64);
                    return false;
                default:
                    out_.fatal(CALL_INFO, -1,
                               "GatherBufferIF fatal: computed granule sz too large (need=%" PRIu64 " align_unit=%" PRIu64 " sz_u64=%" PRIu64 ")\n",
                               (uint64_t)need, (uint64_t)au, (uint64_t)sz_u64);
                    return false;
            }
        }
        sz = (uint32_t)sz_u64;
    }

    GranuleKey key = makeGranuleKey_(base, sz);
    auto& g = ensureGranule_(tgt_buf, key);
    const uint64_t arr_ns = getCurrentSimTimeNano();
    if (g.min_arrival_ns == 0 || arr_ns < g.min_arrival_ns) g.min_arrival_ns = arr_ns;
    if (off + (uint64_t)rd->size > (uint64_t)g.size) {
        switch (kind) {
            case ReadAttachKind::OpenStep:
                out_.fatal(CALL_INFO, -1,
                           "GatherBufferIF fatal: openStep sub-read out of granule bounds (seq=%u merge=%d use_row=%d base=0x%lx sz=%u addr=0x%lx size=%zu off=%" PRIu64 ")\n",
                           (uint32_t)seq, (int)merge_, (int)use_row,
                           (uint64_t)base, (uint32_t)g.size, (uint64_t)rd->pAddr, (size_t)rd->size, (uint64_t)off);
                return false;
            case ReadAttachKind::ManualBeginGather:
                out_.fatal(CALL_INFO, -1,
                           "GatherBufferIF fatal: manual BeginGather sub-read out of granule bounds (merge=%d use_row=%d base=0x%lx sz=%u addr=0x%lx size=%zu off=%" PRIu64 ")\n",
                           (int)merge_, (int)use_row,
                           (uint64_t)base, (uint32_t)g.size, (uint64_t)rd->pAddr, (size_t)rd->size, (uint64_t)off);
                return false;
            case ReadAttachKind::QueuedImport:
                out_.fatal(CALL_INFO, -1,
                           "GatherBufferIF fatal: queued sub-read out of granule bounds (stage=%d merge=%d use_row=%d base=0x%lx sz=%u addr=0x%lx size=%zu off=%" PRIu64 ")\n",
                           stage, (int)merge_, (int)use_row,
                           (uint64_t)base, (uint32_t)g.size, (uint64_t)rd->pAddr, (size_t)rd->size, (uint64_t)off);
                return false;
            case ReadAttachKind::ImmediateSend:
                out_.fatal(CALL_INFO, -1,
                           "GatherBufferIF fatal: sub-read out of granule bounds (stage=%d buf=%d merge=%d use_row=%d base=0x%lx sz=%u addr=0x%lx size=%zu off=%" PRIu64 ")\n",
                           stage, buf, (int)merge_, (int)use_row,
                           (uint64_t)base, (uint32_t)g.size, (uint64_t)rd->pAddr, (size_t)rd->size, (uint64_t)off);
                return false;
            default:
                out_.fatal(CALL_INFO, -1,
                           "GatherBufferIF fatal: sub-read out of granule bounds (stage=%d buf=%d merge=%d use_row=%d base=0x%lx sz=%u addr=0x%lx size=%zu off=%" PRIu64 ")\n",
                           stage, buf, (int)merge_, (int)use_row,
                           (uint64_t)base, (uint32_t)g.size, (uint64_t)rd->pAddr, (size_t)rd->size, (uint64_t)off);
                return false;
        }
    }

    g.subs.push_back({rd->getID(), off, (uint32_t)rd->size});
    g.payload_bytes += (uint64_t)rd->size;
    if (issue_now) {
        if (!g.issued) { issueGranuleBuf_(tgt_buf, key, g); }
    }
    return true;
}

bool GatherBufferIF::drainQueuedNonGatherReadsToGather_(ReadAttachKind kind, uint32_t seq, int stage) {
    if (queued_non_gather_reads_.empty()) return true;
    for (auto* r : queued_non_gather_reads_) {
        sb_[gather_buf_index_].pending_up_reads[r->getID()] = r;
        if (!attachReadToGranule_(gather_buf_index_, r, kind, true, seq, stage, gather_buf_index_)) {
            return false;
        }
        if (stat_up_reads_) stat_up_reads_->addData(1);
    }
    queued_non_gather_reads_.clear();
    return true;
}

GatherBufferIF::Merge GatherBufferIF::parseMerge(const std::string& s) const {
    if (s == "none") return Merge::None;
    if (s == "cacheline") return Merge::Cacheline;
    if (s == "row") return Merge::Row;
    return Merge::Auto;
}

GatherBufferIF::Sort GatherBufferIF::parseSort(const std::string& s) const {
    if (s == "addr") return Sort::Addr;
    if (s == "bank_row") return Sort::BankRow;
    return Sort::Row;
}

GatherBufferIF::ApplyIssuePolicy GatherBufferIF::parseApplyIssuePolicy(const std::string& s) const {
    const std::string v = toLowerCopy(s);
    if (v.empty() || v == "order") return ApplyIssuePolicy::Order;
    out_.fatal(CALL_INFO, -1,
               "invalid apply_issue_policy=%s (expected order)\n",
               v.c_str());
    return ApplyIssuePolicy::Order;
}

GatherBufferIF::GranuleKey GatherBufferIF::makeGranuleKey_(uint64_t base, uint32_t size) const {
    return GranuleKey{base, size};
}

GatherBufferIF::Granule& GatherBufferIF::ensureGranule_(int buf, const GranuleKey& key) {
    auto& S = sb_[buf];
    auto it = S.granules.find(key);
    if (it == S.granules.end()) {
        auto res = S.granules.emplace(key, Granule{});
        it = res.first;
        auto& g = it->second;
        g.base = key.base;
        g.size = key.size;
        g.window_id = current_gather_id_;
        g.payload_bytes = 0;
        S.required_set.insert(key);
        S.issue_order_dirty = true;
        if (stat_coalesce_granule_size_) {
            stat_coalesce_granule_size_->addData((uint64_t)key.size);
        }
    }
    return it->second;
}

bool GatherBufferIF::granuleKeyLess_(const GranuleKey& a, const GranuleKey& b) {
    if (a.base != b.base) return a.base < b.base;
    return a.size < b.size;
}

uint64_t GatherBufferIF::ensureSortKey_(Granule& g) {
    if (!g.sort_key_valid) {
        if (sort_ == Sort::Addr) {
            g.cached_sort_key = g.base;
        } else if (sort_ == Sort::BankRow) {
            g.cached_sort_key = bankRowIndex(g.base);
        } else {
            g.cached_sort_key = rowIndex(g.base);
        }
        g.sort_key_valid = true;
    }
    return g.cached_sort_key;
}

void GatherBufferIF::rebuildIssueOrder_(int buf) {
    auto& S = sb_[buf];
    S.issue_order.clear();
    S.issue_order.reserve(S.granules.size());
    for (auto& kv : S.granules) {
        S.issue_order.emplace_back(ensureSortKey_(kv.second), kv.first);
    }
    std::sort(S.issue_order.begin(), S.issue_order.end(),
              [this](const auto& a, const auto& b){
                  if (a.first != b.first) return a.first < b.first;
                  return granuleKeyLess_(a.second, b.second);
              });
    S.issue_cursor = 0;
    S.issue_order_dirty = false;
}

void GatherBufferIF::issueMoreUnissuedFromOrder_(int buf) {
    auto& S = sb_[buf];
    if (S.issue_order_dirty) {
        rebuildIssueOrder_(buf);
    }

    // Only "start" new granules here. Fragment continuation is handled by
    // onDownstreamResp_ per-granule (issueGranuleBuf_ called on the same key).
    while ((inflight_counts_[0] + inflight_counts_[1]) < max_inflight_reads_) {
        // Skip already-issued / erased granules.
        while (S.issue_cursor < S.issue_order.size()) {
            const GranuleKey& key = S.issue_order[S.issue_cursor].second;
            auto it = S.granules.find(key);
            if (it == S.granules.end() || it->second.issued) {
                ++S.issue_cursor;
                continue;
            }

            Granule& g = it->second;
            const uint32_t before_frags = g.frags_issued;
            const bool before_issued = g.issued;
            issueGranuleBuf_(buf, key, g);

            // If we couldn't issue anything (most commonly due to inflight saturation),
            // stop here and wait for the next downstream response to free credits.
            if (g.frags_issued == before_frags && g.issued == before_issued) {
                if (buf == apply_buf_index_ && stage_ == Stage::Apply) {
                    const uint64_t inflight_total = static_cast<uint64_t>(inflight_counts_[0] + inflight_counts_[1]);
                    if (inflight_total < max_inflight_reads_) {
                        apply_issue_block_downstream_busy_total_++;
                    }
                }
                return;
            }

            // We successfully started this granule; move to the next candidate.
            ++S.issue_cursor;
            break;
        }

        if (S.issue_cursor >= S.issue_order.size()) {
            return;
        }
    }
}

void GatherBufferIF::issueUnissuedGranulesDeterministic_(int buf) {
    auto& S = sb_[buf];
    auto& gmap = S.granules;
    if (gmap.empty()) return;

    std::vector<std::pair<uint64_t, GranuleKey>> sorted;
    sorted.reserve(gmap.size());
    for (auto& kv : gmap) {
        if (kv.second.issued) continue;
        sorted.emplace_back(ensureSortKey_(kv.second), kv.first);
    }
    std::sort(sorted.begin(), sorted.end(),
              [this](const auto& a, const auto& b){
                  if (a.first != b.first) return a.first < b.first;
                  return granuleKeyLess_(a.second, b.second);
              });
    for (auto& p : sorted) {
        auto it = gmap.find(p.second);
        if (it != gmap.end() && !it->second.issued) {
            issueGranuleBuf_(buf, p.second, it->second);
        }
    }
}

uint64_t GatherBufferIF::countApplyIssuableGranules_(int buf) const {
    if (buf < 0 || buf >= 2) return 0;
    const auto& gmap = sb_[buf].granules;
    uint64_t issuable = 0;
    for (const auto& kv : gmap) {
        const Granule& g = kv.second;
        if (g.ready) continue;
        if (!g.issued) {
            issuable += 1;
            continue;
        }
        if (g.frags_total > 0 && g.frags_issued < g.frags_total) {
            issuable += 1;
        }
    }
    return issuable;
}

uint64_t GatherBufferIF::granuleSize() const {
    // Use downstream line size if available for cacheline policy
    auto ls = backend_ ? backend_->getLineSize() : 64;
    if (ls == 0) ls = 64;
    return (uint64_t)ls;
}

void GatherBufferIF::issueGranuleBuf_(int buf, const GranuleKey& key, Granule& g) {
    issueGranuleBufBudget_(buf, key, g, /*max_frags_to_issue=*/0);
}

void GatherBufferIF::issueGranuleBufBudget_(int buf, const GranuleKey& key, Granule& g, uint32_t max_frags_to_issue) {
    // 关键：memHierarchy.Cache（尤其 Incoherent L1）无法正确处理一次性 size>cache_line 的 GetS payload。
    // 这里将一个 granule 的下游读拆分为 cacheline 级分片并在 SRAM 中拼接，避免权重读出脏/非确定性。
    const uint64_t gsz_u64 = granuleSize();
    const uint32_t gsz = (gsz_u64 > 0 && gsz_u64 <= (1ull << 20)) ? static_cast<uint32_t>(gsz_u64) : 64u;

    if (g.frag_bytes == 0) {
        g.frag_bytes = gsz;
        g.frags_total = (g.size + g.frag_bytes - 1u) / g.frag_bytes;
        g.frags_issued = 0;
        g.frags_done = 0;
    }
    if (g.frags_issued >= g.frags_total) return;
    const bool is_apply_issue_ctx = (buf == apply_buf_index_ && stage_ == Stage::Apply);
    const uint32_t frags_before_issue = g.frags_issued;
    if (is_apply_issue_ctx) {
        apply_issue_attempt_total_++;
    }

    uint32_t issued_now = 0;
    while (g.frags_issued < g.frags_total &&
           (inflight_counts_[0] + inflight_counts_[1]) < max_inflight_reads_ &&
           (max_frags_to_issue == 0 || issued_now < max_frags_to_issue)) {
        if (!g.issued) {
            g.issued = true;
            g.issue_ns = getCurrentSimTimeNano();
            if (diagEnabled_(1)) {
                out_.verbose(CALL_INFO, 1, 0,
                    "[diag-gbi-issue] node=%u core=%u buf=%d base=0x%llx size=%u frags=%u frag_bytes=%u window=%" PRIu64 "\n",
                    node_id_param_, core_id_param_, buf, (unsigned long long)g.base, g.size,
                    g.frags_total, g.frag_bytes, (uint64_t)current_gather_id_);
            }
        }
        const uint32_t off = g.frags_issued * g.frag_bytes;
        const uint32_t sz = std::min<uint32_t>(g.frag_bytes, g.size - off);
        auto* rd = new StandardMem::Read(g.base + off, sz);
        const auto id = rd->getID();
        g.down_id = id;
        inflight_down_[id] = DownFrag{buf, key, off, sz};
        inflight_counts_[buf]++;
        if (buf == apply_buf_index_ && stage_ == Stage::Apply && apply_first_down_issue_ns_ == 0) {
            apply_first_down_issue_ns_ = getCurrentSimTimeNano();
        }
        if (stat_reads_issued_) stat_reads_issued_->addData(1);
        backend_->send(rd);
        g.frags_issued++;
        issued_now++;
    }
    if (is_apply_issue_ctx && g.frags_issued > frags_before_issue) {
        apply_issue_success_total_++;
    }
    if (is_apply_issue_ctx &&
        g.frags_issued == frags_before_issue &&
        g.frags_issued < g.frags_total &&
        (inflight_counts_[0] + inflight_counts_[1]) >= max_inflight_reads_) {
        apply_issue_block_inflight_cap_total_++;
    }
}

void GatherBufferIF::onDownstreamResp_(Request* r) {
    // Only expecting ReadResp for now
    if (auto* rr = dynamic_cast<StandardMem::ReadResp*>(r)) {
        auto it = inflight_down_.find(rr->getID());
        // Pass-through ReadResp (i.e., requests not issued by GatherBufferIF) must be forwarded upstream.
        // Otherwise upstream pending maps (e.g., StandardMemAccess) will never see the response and may deadlock.
        if (it == inflight_down_.end()) {
            // Debug: if downstream returns unexpected IDs, granules may never retire.
            // Limit printing to avoid log explosion.
            if (diagEnabled_(1)) {
                static int diag_untracked_rr = 0;
                if (diag_untracked_rr < 64) {
                    out_.verbose(CALL_INFO, 1, 0,
                        "[diag-gbi] ReadResp UNTRACKED id=%" PRIu64 " bytes=%zu node=%u core=%u stage=%d inflight0=%" PRIu64 " inflight1=%" PRIu64 "\n",
                        (uint64_t)rr->getID(), rr->data.size(), node_id_param_, core_id_param_, (int)stage_,
                        (uint64_t)inflight_counts_[0], (uint64_t)inflight_counts_[1]);
                    ++diag_untracked_rr;
                }
            }
            if (upstream_handler_) {
                (*upstream_handler_)(r);
            } else {
                delete r;
            }
            return;
        }
        if (diagEnabled_(1)) {
            GranuleKey key_dbg = (it != inflight_down_.end()) ? it->second.key : GranuleKey{0, 0};
            int buf_dbg = (it != inflight_down_.end()) ? it->second.buf : -1;
            out_.verbose(CALL_INFO, 1, 0,
                "[diag-gbi] ReadResp id=%" PRIu64 " bytes=%zu buf=%d base=0x%llx size=%u node=%u core=%u\n",
                (uint64_t)rr->getID(), rr->data.size(), buf_dbg,
                (unsigned long long)key_dbg.base, key_dbg.size, node_id_param_, core_id_param_);
        }
	        if (it != inflight_down_.end()) {
	            const int buf_index = it->second.buf;
	            const GranuleKey key = it->second.key;
	            const uint32_t frag_off = it->second.off;
	            const uint32_t frag_sz = it->second.size;
	            if (buf_index == apply_buf_index_ && stage_ == Stage::Apply) {
	                if (apply_first_down_resp_ns_ == 0) {
	                    apply_first_down_resp_ns_ = getCurrentSimTimeNano();
	                }
	                apply_down_resp_total_++;
	            }
	            inflight_down_.erase(it);
	            if (buf_index >=0 && buf_index < 2) {
	                auto& sb = sb_[buf_index];
                auto git = sb.granules.find(key);
                if (git != sb.granules.end()) {
                auto& g = git->second;
                // allocate SRAM block once per granule
                auto bit = sb.sram_blocks.find(key);
                if (bit == sb.sram_blocks.end()) {
                    ensureCapacity_(buf_index, g.size);
                    auto& nb = sb.sram_blocks[key];
                    nb.resize(g.size);
                    bit = sb.sram_blocks.find(key);
                }
                auto& sram = bit->second;
                // 断言式诊断：下游 ReadResp 必须返回完整分片，否则视为内存层异常（易导致 BCSR 读脏数据）
                if (frag_sz > 0) {
                    if (rr->data.size() < frag_sz) {
                        out_.fatal(CALL_INFO, -1,
                            "[gbi-assert] node=%u core=%u buf=%d base=0x%llx size=%u frag_off=%u frag_sz=%u resp_bytes=%zu -- payload truncated, potential cache payload corruption\n",
                            node_id_param_, core_id_param_, buf_index,
                            (unsigned long long)g.base, g.size, frag_off, frag_sz, rr->data.size());
                    }
                }
                if (byteExactVerifyEnabled_()) {
                    const std::string mode_l = toLowerCopy(byte_exact_verify_mode_);
                    if (mode_l == "dense_rowcol_v1") {
                        verifyByteExactDenseRowcol_(g.base + frag_off, rr->data);
                    } else if (mode_l == "raw_bcsr_v1") {
                        verifyByteExactRawBcsr_(g.base + frag_off, rr->data);
                    }
                }
                if (!rr->data.empty() && frag_off < sram.size()) {
                    const size_t cap = std::min<size_t>(frag_sz, sram.size() - frag_off);
                    const size_t ncpy = std::min<size_t>(cap, rr->data.size());
                    std::memcpy(sram.data() + frag_off, rr->data.data(), ncpy);
                }
                if (g.frags_total > 0 && g.frags_done < g.frags_total) g.frags_done++;
                if (inflight_counts_[buf_index] > 0) inflight_counts_[buf_index]--;

                // 若还有未发分片，继续发起（受 max_inflight 限制）
                if (g.frags_total > 0 && g.frags_issued < g.frags_total) {
                    issueGranuleBuf_(buf_index, key, g);
                }

                bool completed_now = false;
                // 全部分片完成后，标记 ready 并做一次性统计/LRU
                if (!g.ready && g.frags_total > 0 && g.frags_done >= g.frags_total) {
                    // 诊断：落入SRAM时记录首float与地址（全节点，前若干条）
                    static int diag_sram_store = 0;
                    if (diagEnabled_(1) && diag_sram_store < 128 && !sram.empty()) {
                        float f0_store = 0.0f;
                        std::memcpy(&f0_store, sram.data(), std::min<size_t>(sizeof(float), sram.size()));
                        out_.verbose(CALL_INFO, 1, 0,
                            "[diag-sram-store] node=%u core=%u buf=%d base=0x%llx size=%zu f0=%.6f\n",
                            node_id_param_, core_id_param_, buf_index,
                            (unsigned long long)g.base, sram.size(), f0_store);
                        ++diag_sram_store;
                    }
                    touchLRU_(buf_index, key);
                    g.ready = true;
                    if (out_.getVerboseLevel() >= 1) {
                        out_.verbose(CALL_INFO, 1, 0,
                            "[diag-gbi] mark ready buf=%d base=0x%llx size=%u subs=%zu\n",
                            buf_index, (unsigned long long)g.base, g.size, (size_t)g.subs.size());
                    }
                    if (stat_unique_reads_) stat_unique_reads_->addData(1);
                    if (stat_unique_bytes_) stat_unique_bytes_->addData(g.size);
                    completed_now = true;
                }
                if (completed_now) {
                    if (buf_index == apply_buf_index_ && stage_ == Stage::Apply) {
                        if (apply_first_granule_done_ns_ == 0) {
                            apply_first_granule_done_ns_ = getCurrentSimTimeNano();
                        }
                        apply_completed_granules_total_++;
                    }
                    // Diagnostic: dump per-sub first-float values into CSV
                    // Use SRAM block (sram) as the source of truth so we still produce samples even if rr->data is empty.
                    #ifdef SNNDL_ENABLE_DEBUG_LOG
                    if (!probe_csv_path_.empty()) {
                        FILE* fp = fopen(probe_csv_path_.c_str(), probe_csv_header_written_? "a" : "w");
                        if (fp) {
                            if (!probe_csv_header_written_) { fprintf(fp, "abs_addr,size,f0\n"); probe_csv_header_written_ = true; }
                            for (auto &sub : g.subs) {
                                float f0 = 0.0f;
                                if ((size_t)sub.offset + sizeof(float) <= sram.size()) {
                                    std::memcpy(&f0, sram.data() + sub.offset, sizeof(float));
                                }
                                unsigned long abs = (unsigned long)(g.base + (uint64_t)sub.offset);
                                fprintf(fp, "0x%lx,%u,%.6f\n", abs, (unsigned)sub.size, f0);
                            }
                            fclose(fp);
                        }
                    }
                    #endif

                    // --- Adaptive k: segment timing and payload ---
                    if (k_adapt_enable_ || ctrl_enable_) {
                        uint64_t end_ns = getCurrentSimTimeNano();
                        uint64_t t_seg_ns = (end_ns >= g.issue_ns) ? (end_ns - g.issue_ns) : 0;
                        const uint64_t payload = g.payload_bytes;
                        // accumulate window metrics
                        win_payload_bytes_ += payload;
                        win_bursts_ += 1;
                        if (t_seg_ns > 0) { win_seg_latency_sum_ns_ += t_seg_ns; win_seg_count_ += 1; }
                        // update B_eff (EMA) using segment throughput
                        if (k_adapt_enable_ && t_seg_ns > 0 && payload > 0) {
                            double inst_bw = (double)payload / (double)t_seg_ns; // bytes/ns
                            if (bw_eff_bytes_per_ns_ <= 0.0) bw_eff_bytes_per_ns_ = inst_bw;
                            else bw_eff_bytes_per_ns_ = (1.0 - k_alpha_bw_) * bw_eff_bytes_per_ns_ + k_alpha_bw_ * inst_bw;
                            // derive O_eff sample (ns): max(0, T - payload/B)
                            double ideal_ns = (bw_eff_bytes_per_ns_ > 0.0) ? ((double)payload / bw_eff_bytes_per_ns_) : (double)t_seg_ns;
                            double oeff = std::max(0.0, (double)t_seg_ns - ideal_ns);
                            oeff_samples_ns_.push_back((uint64_t)std::llround(oeff));
                        }
                    }

                    // Also propagate a lightweight stat update upstream so PE层可累计到 CSV
                    if (upstream_handler_) {
                        auto* s = new GasStatData((uint32_t)current_gather_id_, 1, (uint64_t)g.size);
                        auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, s, 0, 0, 0);
                        (*upstream_handler_)(cr);
                    }

                    if (stat_buffer_occupancy_bytes_) {
                        uint64_t sum_bytes = sb_[0].bytes_in_sram + sb_[1].bytes_in_sram;
                        stat_buffer_occupancy_bytes_->addData(sum_bytes);
                        if (sum_bytes > win_buffer_max_bytes_) win_buffer_max_bytes_ = sum_bytes;
                    }
                }
                // 即时回传：若处于Apply阶段且本响应属于当前apply缓冲，尽快向上游发回，避免窗口切换时机错过
                if (stage_ == Stage::Apply && buf_index == apply_buf_index_) {
                    emitApplyResponsesBuf_(apply_buf_index_);
                    // 非延后模式：Apply 阶段也需要继续补发未发的 granule，
                    // 否则在高压力/小 inflight 下可能出现“未发→inflight=0→窗口提前结束”的丢读问题。
                    if (!defer_issue_until_apply_) {
                        issueUnissuedGranulesDeterministic_(apply_buf_index_);
                    }
                    // 延后模式：Apply entry 只会“尽可能发射”，其余 granule 必须在 ReadResp 回调里持续补发，
                    // 否则 inflight 限流会导致部分 granule 永远不被 issue，从而 required_set 永远不 ready → 卡死。
                    if (defer_issue_until_apply_) {
                        issueMoreUnissuedFromOrder_(apply_buf_index_);
                    }
                }
            }
            }
        }
        delete r;
        // 进入或推进阶段判定
        if (stage_ == Stage::Gather) {
            // If all granules returned and EndGather seen, move to APPLY
            maybeEnterApply_();
            // 非延后模式：仍在Gather，继续发射未发granule
            if (!defer_issue_until_apply_ && stage_ == Stage::Gather) {
                issueUnissuedGranulesDeterministic_(gather_buf_index_);
            }
        } else if (stage_ == Stage::Apply && apply_pending_emit_) {
            // In window_auto mode (including GLOBAL_STEP_SYNC), stage transitions are driven
            // by clockTick()/tryAutoEndApply_ to avoid re-entrancy hazards:
            // - upstream ReadResp callbacks can synchronously enqueue new Apply-stage reads
            //   (staging_reads/pending_up_reads) while we are inside onDownstreamResp_.
            // Advancing Apply->Scatter here based only on required_set readiness can therefore
            // prematurely end Apply before staged reads are converted into required granules.
            if (window_auto_) return;
            // 检查是否全部ready，若是且无需等待Apply窗口，则发放
            bool allReady = true;
            for (auto key : sb_[apply_buf_index_].required_set) {
                auto it2 = sb_[apply_buf_index_].granules.find(key);
                if (it2 == sb_[apply_buf_index_].granules.end() || !it2->second.ready) { allReady = false; break; }
            }
            if (!allReady && out_.getVerboseLevel() >= 2) {
                size_t ready_cnt = 0;
                for (auto key : sb_[apply_buf_index_].required_set) {
                    auto it2 = sb_[apply_buf_index_].granules.find(key);
                    if (it2 != sb_[apply_buf_index_].granules.end() && it2->second.ready) ++ready_cnt;
                }
                out_.verbose(CALL_INFO, 2, 0,
                    "[diag-gbi] Apply waiting: ready=%zu / total=%zu\n",
                    ready_cnt, sb_[apply_buf_index_].required_set.size());
            }
            if (allReady) {
                if (!window_auto_ || win_cyc_apply_ == 0) {
                    emitApplyResponsesBuf_(apply_buf_index_);
                    // EndApply barrier: ensure no inflight downstream reads
                    if (emit_stage_events_ && upstream_handler_) {
                        if (inflight_counts_[apply_buf_index_] == 0) {
                            auto* ea = new GasOpData(GasOp::EndApply, (uint32_t)current_gather_id_, 0, 1, false);
                            auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, ea, 0, 0, 0);
                            (*upstream_handler_)(cr);
                        } else {
                            apply_pending_emit_ = true; // wait for drain
                            return;
                        }
                    }
                    stage_ = Stage::Scatter; stage_counter_ = 0;
                    if (emit_stage_events_ && upstream_handler_) {
                        auto* bs = new GasOpData(GasOp::BeginScatter, (uint32_t)current_gather_id_, 0, 1, false);
                        auto* cr2 = new StandardMem::CustomResp((StandardMem::Request::id_t)0, bs, 0, 0, 0);
                        (*upstream_handler_)(cr2);
                    }
                    if (flush_after_scatter_) doFlushBuf_(apply_buf_index_);
                    if (emit_stage_events_ && upstream_handler_) {
                        auto* es = new GasOpData(GasOp::EndScatter, (uint32_t)current_gather_id_, 0, 1, false);
                        auto* cr3 = new StandardMem::CustomResp((StandardMem::Request::id_t)0, es, 0, 0, 0);
                        (*upstream_handler_)(cr3);
                    }
                    stage_counter_ = 0;
                    if (window_auto_ && step_gate_enable_) {
                        // Step-level gate：停在 Idle，等待 openStep(seq) 进入下一窗
                        stage_ = Stage::Idle;
                        sb_[gather_buf_index_].end_gather_seen = false;
                    } else {
                        stage_ = window_auto_ ? Stage::Gather : Stage::Idle;
                        if (window_auto_) { sb_[gather_buf_index_].end_gather_seen = false; current_gather_id_++; }
                        if (window_auto_ && emit_stage_events_ && upstream_handler_) {
                            auto* bg = new GasOpData(GasOp::BeginGather, (uint32_t)current_gather_id_, 0, 1, false);
                            auto* cr4 = new StandardMem::CustomResp((StandardMem::Request::id_t)0, bg, 0, 0, 0);
                            (*upstream_handler_)(cr4);
                        }
                    }
                }
            }
        }
        return;
    }

    // Pass-through for other responses
    if (upstream_handler_) (*upstream_handler_)(r);
}

void GatherBufferIF::maybeEnterApply_() {
    if (stage_ != Stage::Gather || !sb_[gather_buf_index_].end_gather_seen) {
        if (out_.getVerboseLevel() >= 2) {
            out_.verbose(CALL_INFO, 2, 0,
                "[diag-gbi] maybeEnterApply_ gate: stage=%d end_gather_seen=%d required_set=%zu granules=%zu\n",
                (int)stage_, sb_[gather_buf_index_].end_gather_seen?1:0,
                sb_[gather_buf_index_].required_set.size(), sb_[gather_buf_index_].granules.size());
        }
        return;
    }
    // 进入 APPLY；对于延后发射模式，在此时统一构建/排序并下发；否则要求全部ready再进入
    flushStageCycles_(Stage::Gather, false);
    stage_ = Stage::Apply; stage_counter_ = 0; apply_pending_emit_ = true;
    apply_begin_ns_ = getCurrentSimTimeNano();
    apply_first_down_issue_ns_ = 0;
    apply_first_down_resp_ns_ = 0;
    apply_first_granule_done_ns_ = 0;
    apply_first_up_resp_ns_ = 0;
    apply_down_resp_total_ = 0;
    apply_completed_granules_total_ = 0;
    apply_emitted_subreads_total_ = 0;
    apply_backlog_granules_residual_peak_ = 0;
    apply_backlog_pending_up_reads_residual_peak_ = 0;
    apply_backlog_inflight_residual_peak_ = 0;
    apply_backlog_granules_peak_after_due_ = 0;
    apply_backlog_pending_up_reads_peak_after_due_ = 0;
    apply_backlog_inflight_peak_after_due_ = 0;
    apply_issue_attempt_total_ = 0;
    apply_issue_success_total_ = 0;
    apply_issue_block_no_ready_total_ = 0;
    apply_issue_block_inflight_cap_total_ = 0;
    apply_issue_block_bank_credit_total_ = 0;
    apply_issue_block_downstream_busy_total_ = 0;
    apply_issue_block_retire_guard_total_ = 0;
    apply_ready_queue_peak_ = 0;
    apply_ready_queue_nonempty_cycles_total_ = 0;
    // [DEBUG] 在切换前记录当前 Gather 缓冲区状态
    out_.verbose(CALL_INFO, 1, 0,
        "[diag-gbi] BEFORE switch: gather_buf=%d granules=%zu required_set=%zu pending_up_reads=%zu\n",
        gather_buf_index_, sb_[gather_buf_index_].granules.size(),
        sb_[gather_buf_index_].required_set.size(), sb_[gather_buf_index_].pending_up_reads.size());
    // Double buffer: 当前Gather缓冲区切换为Apply缓冲区，Gather切到另一页
    apply_buf_index_ = gather_buf_index_;
    gather_buf_index_ ^= 1;
    resetGatherAutoCounters_();
    // Apply 缓冲的 granules 集合在此刻“定格”，后续会在 Apply 阶段用确定性顺序补发未发 granule。
    sb_[apply_buf_index_].issue_order_dirty = true;
    sb_[apply_buf_index_].issue_cursor = 0;
    // [DEBUG] 切换后记录 Apply 缓冲区状态
    out_.verbose(CALL_INFO, 1, 0,
        "[diag-gbi] AFTER switch: apply_buf=%d gather_buf=%d; apply granules=%zu required_set=%zu\n",
        apply_buf_index_, gather_buf_index_, sb_[apply_buf_index_].granules.size(),
        sb_[apply_buf_index_].required_set.size());
    // 关键：BeginApply 回调中会触发权重读发起；必须在 buffer index 切换完成后再通知上游，
    // 否则 Apply 阶段的读会错误落到“旧 apply_buf”（下一窗口的 gather_buf），导致 req/granules 统计为 0，
    // 进而 Apply 提前结束、WMS outstanding 悬挂，最终出现发放归 0/step_gate openStep inflight 未清空等问题。
    if (emit_stage_events_ && upstream_handler_) {
        auto* ev = new GasOpData(GasOp::BeginApply, (uint32_t)current_gather_id_, 0, 1, false);
        auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, ev, 0, 0, 0);
        (*upstream_handler_)(cr);
    }
    if (defer_issue_until_apply_) {
        // If we staged reads (for gap-merge and/or row-window), build segments now.
        if (gap_merge_enable_ || row_window_enable_ || vlf_enable_) {
            buildGranulesWithGapMergeBuf_(apply_buf_index_);
        }
        // 排序（确定性）并“尽可能发射”：受 inflight 限制时，后续靠 ReadResp 回调持续补发，保证 forward progress。
        rebuildIssueOrder_(apply_buf_index_);
        auto& gmap = sb_[apply_buf_index_].granules;
        auto& sorted = sb_[apply_buf_index_].issue_order;

        // Compute pseudo row-adjacency for this window (before issuing)
        if (sorted.size() > 1) {
            for (size_t i = 1; i < sorted.size(); ++i) {
                auto itp = gmap.find(sorted[i-1].second);
                auto itc = gmap.find(sorted[i].second);
                if (itp != gmap.end() && itc != gmap.end()) {
                    ++win_row_adj_total_;
                    if (sort_ == Sort::BankRow) {
                        if (bankRowIndex(itp->second.base) == bankRowIndex(itc->second.base)) ++win_row_adj_same_;
                    } else {
                        if (rowIndex(itp->second.base) == rowIndex(itc->second.base)) ++win_row_adj_same_;
                    }
                }
            }
        }

        issueMoreUnissuedFromOrder_(apply_buf_index_);
    } else {
        // 非延后：在窗口切换到 Apply 时也补发未发 granule，避免在 Gather 结束时仍有未发请求被遗漏。
        issueUnissuedGranulesDeterministic_(apply_buf_index_);

        // 非延后：只有当全部ready时才会立刻发放
        bool allReady = true;
        for (auto key : sb_[apply_buf_index_].required_set) {
            auto it = sb_[apply_buf_index_].granules.find(key);
            if (it == sb_[apply_buf_index_].granules.end() || !it->second.ready) { allReady = false; break; }
        }
        if (!allReady && out_.getVerboseLevel() >= 2) {
            size_t ready_cnt = 0;
            for (auto key : sb_[apply_buf_index_].required_set) {
                auto it2 = sb_[apply_buf_index_].granules.find(key);
                if (it2 != sb_[apply_buf_index_].granules.end() && it2->second.ready) ++ready_cnt;
            }
            out_.verbose(CALL_INFO, 2, 0,
                "[diag] BeginApply: waiting for ReadResp (%zu/%zu granules ready)\n",
                ready_cnt, sb_[apply_buf_index_].required_set.size());
        }
        // 标记需要在窗口结束时统一回传（FinishApplyWindow_将无条件emit）
        apply_pending_emit_ = true;
        if (!window_auto_ && win_cyc_apply_ == 0 && allReady) {
            emitApplyResponsesBuf_(apply_buf_index_);
            stage_ = Stage::Scatter; stage_counter_ = 0;
            if (flush_after_scatter_) doFlushBuf_(apply_buf_index_);
            stage_ = Stage::Idle;
            return;
        }
    }
    if (tail_wait_start_ns_ && stat_tail_wait_ns_) {
        uint64_t now = getCurrentSimTimeNano();
        if (now >= tail_wait_start_ns_) stat_tail_wait_ns_->addData(now - tail_wait_start_ns_);
        tail_wait_start_ns_ = 0;
    }
    if (out_.getVerboseLevel() >= 1) {
        out_.verbose(CALL_INFO, 1, 0,
            "[diag-gbi] maybeEnterApply_: post-switch apply_buf=%d granules=%zu required_set=%zu\n",
            apply_buf_index_, sb_[apply_buf_index_].granules.size(), sb_[apply_buf_index_].required_set.size());
    }
}

// Build granules from staged reads with gap/Lmax and bank/row grouping for a specific SB
void GatherBufferIF::buildGranulesWithGapMergeBuf_(int buf) {
    auto& S = sb_[buf];
    if (S.staging_reads.empty()) return;

    // Re-entrancy safety:
    // buildGranulesWithGapMergeBuf_ may call upstream_handler_ (e.g., CustomResp stats), and
    // upstream callbacks can synchronously issue new Read requests back into this GatherBufferIF.
    // If we iterate/clear S.staging_reads directly, those re-entrant reads can be accidentally
    // dropped, leading to pending_up_reads hanging and Apply deadlock under GLOBAL_STEP_SYNC.
    std::vector<SST::Interfaces::StandardMem::Read*> staged_reads;
    staged_reads.swap(S.staging_reads);
    std::unordered_map<Request::id_t, uint64_t> staged_arrival_ns;
    staged_arrival_ns.swap(S.staged_arrival_ns);
    if (staged_reads.empty()) return;

    const uint64_t line_bytes_u64 = granuleSize();
    const uint64_t line_bytes = (line_bytes_u64 > 0 && line_bytes_u64 <= (1ull << 20)) ? line_bytes_u64 : 64ull;

    uint64_t payload_bytes_total = 0;
    uint64_t frontend_staged_reads_count = static_cast<uint64_t>(staged_reads.size());
    uint64_t frontend_staged_line_touches = 0;
    uint64_t frontend_granules_built_count = 0;
    uint64_t unique_line_count = 0;
    std::unordered_set<uint64_t> uniq_lines;
    uniq_lines.reserve(staged_reads.size() * 2);
    for (auto* rd : staged_reads) {
        payload_bytes_total += (uint64_t)rd->size;
        const uint64_t a0 = rd->pAddr;
        const uint64_t a1 = rd->pAddr + (uint64_t)rd->size;
        const uint64_t l0 = a0 / line_bytes;
        const uint64_t l1 = (a1 + line_bytes - 1) / line_bytes;
        if (l1 > l0) frontend_staged_line_touches += (l1 - l0);
        for (uint64_t li = l0; li < l1; ++li) uniq_lines.insert(li);
    }
    unique_line_count = (uint64_t)uniq_lines.size();

    bool gap_merge_enable_eff = gap_merge_enable_;
    uint64_t gap_k_bytes_eff = gap_k_bytes_;
    uint64_t overfetch_budget_left = 0; // 0 => unlimited

    // Experimental: DRAM command-cost guided gap-merge guardrail.
    // This caps "k" to a deterministic threshold derived from DRAM hit/miss service costs,
    // and is intended to prevent pathological over-fetch when logical rows are smaller than
    // the physical DRAM row (e.g., dense weight rows).
    const bool cmd_cost_merge = dram_cmd_cost_merge_enable_;
    uint64_t cmd_cost_k_bytes = 0;
    if (cmd_cost_merge) {
        const auto base_ns = cmdCostNsForBank_(0);
        cmd_cost_k_bytes = gather::apply::DramCmdCostMergeModel::deriveGapKBytes(
            line_bytes,
            static_cast<uint64_t>(base_ns.first),
            static_cast<uint64_t>(base_ns.second));
        if (gap_merge_enable_eff) {
            if (gap_k_bytes_eff == 0) {
                gap_k_bytes_eff = cmd_cost_k_bytes;
            } else if (cmd_cost_k_bytes > 0) {
                gap_k_bytes_eff = std::min<uint64_t>(gap_k_bytes_eff, cmd_cost_k_bytes);
            }
        }
    }

    // Per-window DRAM-aware counters (exported as statistics; only meaningful when dram_aware=1).
    uint64_t win_overfetch_bytes = 0;
    uint64_t win_covered_line_count = 0;
    uint64_t win_cmd_cost_veto = 0;
    uint64_t win_cmd_cost_veto_fine_gap = 0;
    uint64_t win_cmd_cost_veto_row_window = 0;

    // Heuristic bank bits/shift detection if requested
    if (!bank_auto_done_ && bank_auto_enable_ && bank_bits_ == 0) {
        // Simple heuristic: reuse staged addrs of this buffer
        // (keep existing API by inlining logic here)
        std::vector<uint64_t> addrs;
        addrs.reserve(staged_reads.size());
        for (auto* rd : staged_reads) addrs.push_back(rd->pAddr);
        if (addrs.size() >= 16) {
            uint32_t best_bits = 0, best_shift = 0; uint64_t best_score = (uint64_t)-1;
            uint32_t minb = std::max<uint32_t>(1, bank_auto_min_banks_);
            uint32_t maxb = std::max<uint32_t>(minb, bank_auto_max_banks_);
            uint32_t target = (minb + maxb) / 2;
            for (uint32_t bits = 2; bits <= 6; ++bits) {
                for (uint32_t shift = 12; shift <= 24; ++shift) {
                    std::unordered_set<uint32_t> banks; banks.reserve(addrs.size());
                    for (auto a : addrs) {
                        uint32_t b = (uint32_t)((a >> shift) & ((1ull << bits) - 1ull));
                        banks.insert(b); if (banks.size() > maxb) break;
                    }
                    uint32_t uniq = (uint32_t)banks.size();
                    if (uniq < minb || uniq > maxb) continue;
                    uint64_t score = (uniq > target) ? (uniq - target) : (target - uniq);
                    score = score * 8 + (shift > 16 ? (shift - 16) : (16 - shift));
                    if (score < best_score) { best_score = score; best_bits = bits; best_shift = shift; }
                }
            }
            if (best_bits != 0) { bank_bits_ = best_bits; bank_shift_ = best_shift; }
            bank_auto_done_ = true;
        }
    }

    // === Experimental: Value-Line Fusion (VLF) ===
    //
    // Motivation:
    // - GCSS value-only paths often issue many small (e.g., 4B) reads.
    // - The existing staged segment builder can absorb byte-gaps (gap_merge / row_window),
    //   which may create large "holes" and inflate covered cachelines (overfetch) dramatically.
    // - VLF aligns each staged read to cacheline boundaries and only fuses overlapping spans
    //   (and optionally adjacent spans when vlf_run_enable_=1). It never absorbs holes.
    if (vlf_enable_) {
        struct VlfReq {
            uint64_t base;   // cacheline-aligned base (inclusive)
            uint64_t end;    // cacheline-aligned end (exclusive)
            uint64_t addr;   // original request addr
            uint32_t size;   // original request size
            uint64_t arr_ns; // arrival time (ns), best-effort
            Request::id_t up_id;
        };
        auto alignUp = [](uint64_t x, uint64_t a) -> uint64_t {
            if (a == 0) return x;
            return ((x + a - 1u) / a) * a;
        };

        // Group by (bank,rowIndex) using aligned base; keep consistent with legacy ordering knobs.
        std::unordered_map<uint64_t, std::vector<VlfReq>> groups;
        size_t estimated_groups = staged_reads.size() / 8;
        if (estimated_groups < 8) estimated_groups = 8;
        groups.reserve(estimated_groups);

        for (auto* rd : staged_reads) {
            const uint64_t addr = rd->pAddr;
            const uint32_t sz = static_cast<uint32_t>(rd->size);
            const uint64_t base = alignDown(addr, line_bytes);
            const uint64_t end = alignUp(addr + (uint64_t)sz, line_bytes);
            const uint64_t key = (bank_bits_ ? (bankIndex(base) << 32) : 0ull) | (uint32_t)rowIndex(base);
            uint64_t arr = 0;
            auto itst = staged_arrival_ns.find(rd->getID());
            if (itst != staged_arrival_ns.end()) arr = itst->second;
            auto& vec = groups[key];
            if (vec.empty()) vec.reserve(8);
            vec.push_back({base, end, addr, sz, arr, rd->getID()});
        }

        // Per-window counters for evidence (same meaning as legacy).
        win_overfetch_bytes = 0;
        win_covered_line_count = 0;

        for (auto& kv : groups) {
            auto& vec = kv.second;
            std::sort(vec.begin(), vec.end(),
                      [](const VlfReq& a, const VlfReq& b){
                          if (a.base != b.base) return a.base < b.base;
                          if (a.end != b.end) return a.end < b.end;
                          if (a.addr != b.addr) return a.addr < b.addr;
                          return a.up_id < b.up_id;
                      });

            uint64_t cur_base = 0, cur_end = 0;
            bool has = false;
            uint64_t seg_sum_bytes = 0;
            uint64_t seg_start_ns = 0;
            std::vector<VlfReq> segSubs;
            segSubs.reserve(vec.size() / 2 + 2);

            auto flush_segment = [&]() {
                if (!has) return;
                const uint64_t base = cur_base;
                const uint64_t sz_u64 = (cur_end >= cur_base) ? (cur_end - cur_base) : 0;
                if (sz_u64 == 0) { segSubs.clear(); has = false; seg_sum_bytes = 0; seg_start_ns = 0; return; }
                if (sz_u64 > 0xffffffffull) {
                    out_.fatal(CALL_INFO, -1,
                               "GatherBufferIF VLF fatal: segment too large (base=0x%llx sz=%" PRIu64 ")\n",
                               (unsigned long long)base, (uint64_t)sz_u64);
                }
                const uint32_t sz = static_cast<uint32_t>(sz_u64);

                // Issue-size accounting (cacheline-aligned, no holes).
                if ((uint64_t)sz > seg_sum_bytes) win_overfetch_bytes += ((uint64_t)sz - seg_sum_bytes);
                win_covered_line_count += (((uint64_t)sz + line_bytes - 1) / line_bytes);

                GranuleKey gkey = makeGranuleKey_(base, sz);
                if (diag_granule_build_logged_ < 64) {
                    out_.verbose(CALL_INFO, 2, 0,
                        "[diag-gbi-vlf-granule] node=%u core=%u buf=%d base=0x%llx size=%u subs=%zu\n",
                        node_id_param_, core_id_param_, buf,
                        (unsigned long long)base,
                        sz, segSubs.size());
                    ++diag_granule_build_logged_;
                }
                const bool granule_exists = (S.granules.find(gkey) != S.granules.end());
                auto& g = ensureGranule_(buf, gkey);
                if (!granule_exists) ++frontend_granules_built_count;
                if (seg_start_ns != 0) {
                    if (g.min_arrival_ns == 0 || seg_start_ns < g.min_arrival_ns) g.min_arrival_ns = seg_start_ns;
                }
                g.subs.reserve(g.subs.size() + segSubs.size());
                for (auto& it : segSubs) {
                    const uint64_t off_u64 = (it.addr >= base) ? (it.addr - base) : 0;
                    if (off_u64 + (uint64_t)it.size > (uint64_t)sz) {
                        out_.fatal(CALL_INFO, -1,
                                   "GatherBufferIF VLF fatal: sub-read out of segment bounds (base=0x%llx sz=%u addr=0x%llx size=%u off=%" PRIu64 ")\n",
                                   (unsigned long long)base, (unsigned)sz,
                                   (unsigned long long)it.addr, (unsigned)it.size, (uint64_t)off_u64);
                    }
                    g.subs.push_back({it.up_id, (uint32_t)off_u64, it.size});
                    g.payload_bytes += (uint64_t)it.size;
                }

                // Optional: export granule size samples (kept consistent with legacy path).
                if (!export_granules_csv_.empty()) {
                    exportGranuleRow_(seg_start_ns, (uint32_t)sz);
                }

                // Upstream aggregation: report per-segment metrics (bursts/payload).
                if (upstream_handler_) {
                    const uint64_t bursts = 1;
                    const uint64_t payload = seg_sum_bytes;
                    auto* s = new GasStatData((uint32_t)current_gather_id_, 0, 0, /*rwt=*/0, /*rwb=*/0, bursts, payload);
                    auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, s, 0, 0, 0);
                    (*upstream_handler_)(cr);
                }

                segSubs.clear();
                has = false;
                seg_sum_bytes = 0;
                seg_start_ns = 0;
            };

            for (auto& it : vec) {
                const uint64_t a = it.base;
                const uint64_t b = it.end;
                if (!has) {
                    cur_base = a; cur_end = b; has = true;
                    seg_sum_bytes = it.size;
                    segSubs.clear(); segSubs.push_back(it);
                    seg_start_ns = it.arr_ns;
                    continue;
                }

                const bool overlap = (a < cur_end);
                const bool adjacent = (a == cur_end);
                const bool can_adj_merge = adjacent && vlf_run_enable_;
                const uint64_t new_end = (b > cur_end) ? b : cur_end;
                const uint64_t new_len = (new_end >= cur_base) ? (new_end - cur_base) : 0;

                if (overlap || can_adj_merge) {
                    // Bound run length by burst_bytes_max_ (reuse existing Lmax knob).
                    if (burst_bytes_max_ == 0 || new_len <= burst_bytes_max_) {
                        cur_end = new_end;
                        segSubs.push_back(it);
                        seg_sum_bytes += it.size;
                        if (it.arr_ns > 0 && (seg_start_ns == 0 || it.arr_ns < seg_start_ns)) seg_start_ns = it.arr_ns;
                        continue;
                    }
                }

                // Gap or run too large: flush and start a new segment.
                flush_segment();
                cur_base = a; cur_end = b; has = true;
                segSubs.clear(); segSubs.push_back(it);
                seg_sum_bytes = it.size;
                seg_start_ns = it.arr_ns;
            }
            flush_segment();
        }

        // Surface VLF window-level metrics to PE stats sink (align with legacy semantics).
        if (upstream_handler_) {
            auto* s = new GasStatData((uint32_t)current_gather_id_, 0, 0, 0, 0, 0, 0, 0, 0,
                                      /*gap_abs=*/0,
                                      frontend_staged_reads_count,
                                      frontend_staged_line_touches,
                                      frontend_granules_built_count,
                                      unique_line_count,
                                      win_covered_line_count,
                                      win_overfetch_bytes,
                                      /*apply_credit_eff=*/0,
                                      /*cmd_veto=*/0,
                                      /*cmd_veto_fine=*/0,
                                      /*cmd_veto_rowwin=*/0);
            auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, s, 0, 0, 0);
            (*upstream_handler_)(cr);
        }
        if (stat_unique_line_count_) stat_unique_line_count_->addData(unique_line_count);
        if (stat_covered_line_count_) stat_covered_line_count_->addData(win_covered_line_count);
        if (stat_overfetch_bytes_) stat_overfetch_bytes_->addData(win_overfetch_bytes);
        return;
    }

    // Group by (bank,rowIndex)
    struct ReadItem {
        uint64_t addr;
        uint32_t size;
        uint64_t arr_ns;
        StandardMem::Read* rd;
    };
    std::unordered_map<uint64_t, std::vector<ReadItem>> groups;

    // 优化3：预分配groups容器（假设平均每组4个读请求）
    size_t estimated_groups = staged_reads.size() / 4;
    if (estimated_groups < 8) estimated_groups = 8;  // 最少预留8组
    groups.reserve(estimated_groups);

    for (auto* rd : staged_reads) {
        uint64_t addr = rd->pAddr; uint32_t sz = rd->size;
        uint64_t key = (bank_bits_? (bankIndex(addr)<<32):0) | (uint32_t)rowIndex(addr);
        uint64_t arr = 0;
        auto itst = staged_arrival_ns.find(rd->getID());
        if (itst != staged_arrival_ns.end()) arr = itst->second;

        // 优化3：预分配每组的vector空间（假设平均每组8个元素）
        auto& vec = groups[key];
        if (vec.empty()) vec.reserve(8);
        vec.push_back({addr, sz, arr, rd});
    }
    uint64_t gap_abs_sum = 0;
    // For each group, sort by addr and build segments
    for (auto &kv : groups) {
        auto &vec = kv.second;
        std::sort(vec.begin(), vec.end(), [](const ReadItem&a, const ReadItem&b){ return a.addr < b.addr; });
        uint32_t group_bank_idx = 0;
        if (!vec.empty()) {
            group_bank_idx = bank_bits_ ? static_cast<uint32_t>(kv.first >> 32)
                                        : static_cast<uint32_t>(bankIndex(vec.front().addr));
        }
        const auto cmd_cost_ns = cmdCostNsForBank_(group_bank_idx);
        const uint64_t cmd_hit_ns = cmd_cost_ns.first;
        const uint64_t cmd_miss_ns = cmd_cost_ns.second;
        uint64_t cur_base = 0, cur_end = 0; bool has=false;
        uint64_t seg_sum_bytes = 0;      // sum of sub-read sizes in current segment
        bool seg_used_row_window = false; // whether coarse row-window absorption was used
        uint64_t seg_start_ns = 0;        // min arrival time across sub-reads in segment
        // temp list of sub-reads per current segment
        std::vector<ReadItem> segSubs;
        // 优化3：预分配segSubs容器（假设每段平均包含vec的一半元素）
        segSubs.reserve(vec.size() / 2 + 2);
        auto flush_segment = [&](bool mark_rowwin=false) {
            if (!has) return;
            uint64_t base = cur_base; uint32_t sz = (uint32_t)(cur_end - cur_base);
            const uint64_t payload = seg_sum_bytes;
            if ((uint64_t)sz > payload) win_overfetch_bytes += ((uint64_t)sz - payload);
            win_covered_line_count += (((uint64_t)sz + line_bytes - 1) / line_bytes);
            GranuleKey gkey = makeGranuleKey_(base, sz);
            if (diag_granule_build_logged_ < 64) {
                out_.verbose(CALL_INFO, 2, 0,
                    "[diag-gbi-granule] node=%u core=%u buf=%d base=0x%llx size=%u subs=%zu\n",
                    node_id_param_, core_id_param_, buf,
                    (unsigned long long)base,
                    sz, segSubs.size());
                ++diag_granule_build_logged_;
            }
            const bool granule_exists = (S.granules.find(gkey) != S.granules.end());
            auto& g = ensureGranule_(buf, gkey);
            if (!granule_exists) ++frontend_granules_built_count;
            if (seg_start_ns != 0) {
                if (g.min_arrival_ns == 0 || seg_start_ns < g.min_arrival_ns) g.min_arrival_ns = seg_start_ns;
            }
            // 优化3：预分配subs空间（已知即将添加segSubs.size()个元素）
            g.subs.reserve(g.subs.size() + segSubs.size());
            for (auto &it : segSubs) {
                uint64_t off = (it.addr >= base) ? (it.addr - base) : 0;
                g.subs.push_back({it.rd->getID(), off, it.size});
                g.payload_bytes += (uint64_t)it.size;
            }
            // P1-2: export granule row if enabled
            if (!export_granules_csv_.empty()) {
                exportGranuleRow_(seg_start_ns, (uint32_t)sz);
            }
            // Row-window stats: count only if we actually used row-window absorption or explicitly marked (e.g., timeout)
            if (row_window_enable_ && stat_row_window_triggers_ && stat_row_window_bytes_) {
                if (seg_used_row_window || mark_rowwin) {
                    stat_row_window_triggers_->addData(1);
                    stat_row_window_bytes_->addData((uint64_t)sz); // bytes actually issued on DRAM (including holes)
                }
            }
            // Upstream aggregation: report per-segment metrics (bursts/payload, and row-window if used)
            if (upstream_handler_) {
                uint64_t rwt = (seg_used_row_window || mark_rowwin) ? 1 : 0;
                uint64_t rwb = (seg_used_row_window || mark_rowwin) ? (uint64_t)sz : 0;
                uint64_t bursts = 1;
                uint64_t payload = seg_sum_bytes; // sum of sub-read sizes in this segment
                auto* s = new GasStatData((uint32_t)current_gather_id_, 0, 0, rwt, rwb, bursts, payload);
                auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, s, 0, 0, 0);
                (*upstream_handler_)(cr);
            }
            segSubs.clear(); has=false;
            seg_sum_bytes = 0; seg_used_row_window = false; seg_start_ns = 0;
        };
        for (auto &it : vec) {
            uint64_t a = it.addr, b = it.addr + it.size;
            if (!has) {
                cur_base = a; cur_end = b; seg_sum_bytes = it.size; segSubs.clear(); segSubs.push_back(it); has=true; seg_start_ns = it.arr_ns; continue;
            }
            if (a <= cur_end) {
                // overlap/adjacent
                if (b > cur_end) cur_end = b;
                segSubs.push_back(it);
                seg_sum_bytes += it.size;
                if (it.arr_ns > 0 && (seg_start_ns == 0 || it.arr_ns < seg_start_ns)) seg_start_ns = it.arr_ns;
            } else {
                uint64_t gap = a - cur_end;
                uint64_t new_len = (b - cur_base);
                bool absorbed = false;
                if (gap_merge_enable_eff && gap_k_bytes_eff>0 && gap <= gap_k_bytes_eff && new_len <= burst_bytes_max_) {
                    bool cmd_allow_absorb = true;
                    if (cmd_cost_merge) {
                        cmd_allow_absorb = gather::apply::DramCmdCostMergeModel::allowAbsorbGap(
                            gap, line_bytes, cmd_hit_ns, cmd_miss_ns);
                        if (!cmd_allow_absorb) {
                            if (stat_cmd_cost_veto_) stat_cmd_cost_veto_->addData(1);
                            if (stat_cmd_cost_veto_fine_gap_) stat_cmd_cost_veto_fine_gap_->addData(1);
                            win_cmd_cost_veto += 1;
                            win_cmd_cost_veto_fine_gap += 1;
                        }
                    }
                    // absorb gap (optional budget guard)
                    if (cmd_allow_absorb && (overfetch_budget_left == 0 || gap <= overfetch_budget_left)) {
                        cur_end = b;
                        gap_abs_sum += gap;
                        if (overfetch_budget_left > 0) overfetch_budget_left -= gap;
                        segSubs.push_back(it);
                        absorbed = true;
                        seg_sum_bytes += it.size;
                        if (it.arr_ns > 0 && (seg_start_ns == 0 || it.arr_ns < seg_start_ns)) seg_start_ns = it.arr_ns;
                    }
                }
                // Row-window timeout trigger: if enabled and window has waited too long, flush before adding
                if (!absorbed && row_window_enable_ && row_window_timeout_ns_>0 && seg_start_ns>0 && it.arr_ns>0) {
                    if (it.arr_ns >= seg_start_ns && (it.arr_ns - seg_start_ns) >= row_window_timeout_ns_) {
                        // flush current segment as a row-window burst due to timeout
                        flush_segment(/*mark_rowwin=*/true);
                        // start new segment with current item
                        cur_base = a; cur_end = b; has=true; segSubs.push_back(it); seg_sum_bytes = it.size; seg_start_ns = it.arr_ns; continue;
                    }
                }
                // Row-window coarse merge (allow larger gap if within row_window_bytes threshold of sum-bytes, and not exceeding Lmax)
                if (!absorbed && row_window_enable_ && row_window_bytes_>0) {
                    uint64_t tentative_sum = seg_sum_bytes + it.size;
                    if (tentative_sum <= row_window_bytes_ && new_len <= burst_bytes_max_) {
                        bool cmd_allow_absorb = true;
                        if (cmd_cost_merge) {
                            cmd_allow_absorb = gather::apply::DramCmdCostMergeModel::allowAbsorbGap(
                                gap, line_bytes, cmd_hit_ns, cmd_miss_ns);
                            if (!cmd_allow_absorb) {
                                if (stat_cmd_cost_veto_) stat_cmd_cost_veto_->addData(1);
                                if (stat_cmd_cost_veto_row_window_) stat_cmd_cost_veto_row_window_->addData(1);
                                win_cmd_cost_veto += 1;
                                win_cmd_cost_veto_row_window += 1;
                            }
                        }
                        if (cmd_allow_absorb) {
                            // absorb regardless of gap size (optional budget guard)
                            if (overfetch_budget_left == 0 || gap <= overfetch_budget_left) {
                                cur_end = b;
                                if (overfetch_budget_left > 0) overfetch_budget_left -= gap;
                                segSubs.push_back(it);
                                absorbed = true;
                                seg_sum_bytes = tentative_sum;
                                seg_used_row_window = true;
                                if (it.arr_ns > 0 && (seg_start_ns == 0 || it.arr_ns < seg_start_ns)) seg_start_ns = it.arr_ns;
                            }
                        }
                    }
                }
                if (!absorbed) {
                    // neither fine nor coarse merge possible: flush and start new
                    flush_segment();
                    cur_base = a; cur_end = b; has=true; segSubs.push_back(it); seg_sum_bytes = it.size; seg_start_ns = it.arr_ns; seg_used_row_window = false;
                }
            }
        }
        // Flush the last segment; mark as row-window only if we used row-window absorption at least once
        flush_segment(/*mark_rowwin=*/seg_used_row_window);
    }
    if (stat_gap_absorbed_bytes_ && gap_abs_sum) stat_gap_absorbed_bytes_->addData(gap_abs_sum);
    // Surface window-level merge diagnostics to the PE-level stats sink (SnnPESubComponent) via CustomResp,
    // because GatherBufferIF is instantiated during init() and cannot reliably emit CSV stats itself.
    if ((gap_abs_sum || frontend_staged_reads_count || frontend_staged_line_touches || frontend_granules_built_count ||
         unique_line_count || win_covered_line_count || win_overfetch_bytes ||
         win_cmd_cost_veto || win_cmd_cost_veto_fine_gap || win_cmd_cost_veto_row_window) &&
        upstream_handler_) {
        auto* s = new GasStatData((uint32_t)current_gather_id_, 0, 0, 0, 0, 0, 0, 0, 0,
                                  gap_abs_sum,
                                  frontend_staged_reads_count,
                                  frontend_staged_line_touches,
                                  frontend_granules_built_count,
                                  unique_line_count,
                                  win_covered_line_count,
                                  win_overfetch_bytes,
                                  0,
                                  win_cmd_cost_veto,
                                  win_cmd_cost_veto_fine_gap,
                                  win_cmd_cost_veto_row_window);
        auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, s, 0, 0, 0);
        (*upstream_handler_)(cr);
    }
    if (stat_unique_line_count_) stat_unique_line_count_->addData(unique_line_count);
    if (stat_covered_line_count_) stat_covered_line_count_->addData(win_covered_line_count);
    if (stat_overfetch_bytes_) stat_overfetch_bytes_->addData(win_overfetch_bytes);
    // NOTE: do NOT clear S.staging_reads / S.staged_arrival_ns here. New staged reads may have been
    // added re-entrantly during upstream callbacks above; those must be preserved for the next tick.
}

void GatherBufferIF::emitApplyResponsesBuf_(int buf) {
    // For each upstream Read queued in this gather, emit a ReadResp from SRAM
    auto& S = sb_[buf];
    out_.verbose(CALL_INFO, 1, 0,
        "[diag-gbi] emitApplyResponses buf=%d granules=%zu pending_up_reads=%zu\n",
        buf, (size_t)S.granules.size(), S.pending_up_reads.size());

    // 收集已处理完成的 granule keys（ready 且已发回所有 sub-reads）
    std::vector<GranuleKey> completed_keys;
    completed_keys.reserve(S.granules.size());

    // Deterministic traversal: granule and sub-read emission order must be stable across runs.
    std::vector<std::pair<uint64_t, GranuleKey>> sorted_keys;
    sorted_keys.reserve(S.granules.size());
    for (auto& kvg : S.granules) {
        auto& g = kvg.second;
        if (!g.sort_key_valid) {
            if (sort_ == Sort::Addr) {
                g.cached_sort_key = g.base;
            } else if (sort_ == Sort::BankRow) {
                g.cached_sort_key = bankRowIndex(g.base);
            } else {
                g.cached_sort_key = rowIndex(g.base);
            }
            g.sort_key_valid = true;
        }
        sorted_keys.emplace_back(g.cached_sort_key, kvg.first);
    }
    std::sort(sorted_keys.begin(), sorted_keys.end(),
              [this](const auto& a, const auto& b){
                  if (a.first != b.first) return a.first < b.first;
                  return granuleKeyLess_(a.second, b.second);
              });

    for (auto& pk : sorted_keys) {
        GranuleKey key = pk.second;
        auto git = S.granules.find(key);
        if (git == S.granules.end()) continue;
        auto& g = git->second;

        // 跳过未 ready 的 granule（保留到下次处理）
        if (!g.ready) {
            out_.verbose(CALL_INFO, 1, 0,
                "[diag-gbi] granule base=0x%llx size=%u NOT ready; window=%" PRIu64 " buf=%d (will retry next Apply)\n",
                (unsigned long long)g.base, g.size, (uint64_t)g.window_id, buf);
            continue;
        }

        auto bit = S.sram_blocks.find(key);
        if (bit == S.sram_blocks.end()) {
            out_.verbose(CALL_INFO, 1, 0,
                "[diag-gbi] granule base=0x%llx size=%u missing SRAM entry (buf=%d)\n",
                (unsigned long long)g.base, g.size, buf);
            continue;
        }

        const auto& blk = bit->second;
        if (g.subs.empty()) {
            out_.verbose(CALL_INFO, 1, 0,
                "[diag-gbi] granule base=0x%llx size=%u READY but subs=0 (buf=%d) pending_up_reads=%zu\n",
                (unsigned long long)g.base, g.size, buf, S.pending_up_reads.size());
        }
        out_.verbose(CALL_INFO, 1, 0,
            "[diag-gbi] granule base=0x%llx size=%u subs=%zu ready=%d buf=%d\n",
            (unsigned long long)g.base, g.size, (size_t)g.subs.size(), (int)g.ready, buf);

        // Make sub-read emission stable across runs even when upstream Read arrival order differs.
        std::sort(g.subs.begin(), g.subs.end(),
                  [](const SubReq& a, const SubReq& b){
                      if (a.offset != b.offset) return a.offset < b.offset;
                      if (a.size != b.size) return a.size < b.size;
                      return a.up_id < b.up_id;
                  });

        // 发回所有 sub-reads
        for (auto& s : g.subs) {
            // 防御性：如果 upstream 已不再跟踪该 up_id（例如重复 sub、已提前回包），则不要再发回 ReadResp，
            // 否则会导致上游 StandardMemAccess 出现 untracked ReadResp（非确定性/潜在崩溃）。
            auto itup = S.pending_up_reads.find(s.up_id);
            if (itup == S.pending_up_reads.end()) {
                out_.verbose(CALL_INFO, 1, 0,
                    "[diag-gbi] skip respond: missing pending_up_reads up_id=%" PRIu64 " base=0x%llx size=%u off=%u size=%u buf=%d\n",
                    (uint64_t)s.up_id, (unsigned long long)g.base, g.size,
                    (unsigned)s.offset, (unsigned)s.size, buf);
                continue;
            }
            // 使用 up_id 构造响应，避免依赖上游 Read* 指针的生命周期
            auto* resp = new StandardMem::ReadResp(
                s.up_id,
                g.base + s.offset,                  // 物理地址可选，这里使用granule内的绝对地址
                (uint64_t)s.size,
                std::vector<uint8_t>(s.size)
            );
            // Fill payload
            if (s.offset + s.size <= blk.size()) {
                std::memcpy(resp->data.data(), blk.data() + s.offset, s.size);
            }
            out_.verbose(CALL_INFO, 1, 0,
                "[diag-gbi] respond up_id=%" PRIu64 " base=0x%llx size=%u off=%u size=%u pending=%zu data_empty=%d buf=%d\n",
                (uint64_t)s.up_id, (unsigned long long)g.base, g.size, (unsigned)s.offset,
                (unsigned)s.size, (size_t)S.pending_up_reads.size(), resp->data.empty()?1:0, buf);
            // 限量权重返回探针：仅 node_id=0 打印前16条，附带首float与地址
            if (node_id_param_ == 0) {
                static int diag_weightresp_gbi = 0;
                    if (diag_weightresp_gbi < 16 && !resp->data.empty()) {
                    float f0_dbg = 0.0f;
                    if (resp->data.size() >= sizeof(float)) {
                        std::memcpy(&f0_dbg, resp->data.data(), sizeof(float));
                    }
                    out_.verbose(CALL_INFO, 2, 0,
                        "[diag-weightresp-gbi] node=%u base=0x%llx size=%u off=%u size=%u f0=%.6f\n",
                        node_id_param_, (unsigned long long)g.base, g.size,
                        (unsigned)s.offset, (unsigned)s.size, f0_dbg);
                    ++diag_weightresp_gbi;
                }
            }
#ifdef SNNDL_ENABLE_DEBUG_LOG
            // Debug probe: print first-float value of this sub-read (noise-prone; keep debug-only).
            if (out_.getVerboseLevel() >= 1 && !resp->data.empty()) {
                float f0 = 0.0f;
                if (resp->data.size() >= sizeof(float)) {
                    std::memcpy(&f0, resp->data.data(), sizeof(float));
                }
                uint64_t abs_addr = g.base + (uint64_t)s.offset;
                out_.verbose(CALL_INFO, 1, 0,
                    "[diag-gbi][probe-gas] granule_base=0x%lx sub_off=%u abs=0x%lx size=%u f0=%.6f\n",
                    (unsigned long)g.base, (unsigned)s.offset,
                    (unsigned long)abs_addr, (unsigned)s.size, f0);
            }
            if (!probe_csv_path_.empty()) {
                // write one line per sub-read with addr,size,first-float (read from SRAM block)
                FILE* fp = fopen(probe_csv_path_.c_str(), probe_csv_header_written_? "a" : "w");
                if (fp) {
                    if (!probe_csv_header_written_) { fprintf(fp, "abs_addr,size,f0\n"); probe_csv_header_written_ = true; }
                    float f0 = 0.0f;
                    if ((size_t)s.offset + sizeof(float) <= blk.size()) std::memcpy(&f0, blk.data() + s.offset, sizeof(float));
                    unsigned long abs = (unsigned long)(g.base + (uint64_t)s.offset);
                    fprintf(fp, "0x%lx,%u,%.6f\n", abs, (unsigned)s.size, f0);
                    fclose(fp);
                }
            }
#endif
            if (buf == apply_buf_index_) {
                if (apply_first_up_resp_ns_ == 0) {
                    apply_first_up_resp_ns_ = getCurrentSimTimeNano();
                }
                apply_emitted_subreads_total_++;
            }
            if (upstream_handler_) (*upstream_handler_)(resp);
            // 注意：上游StandardMem::Read的所有权由上游组件管理。
            // 这里不再delete上游请求指针，仅从追踪表移除，避免重复释放导致的崩溃。
            // Re-entrancy safety: upstream handler can synchronously issue new reads which may
            // insert into pending_up_reads and trigger rehash; avoid erasing with a potentially
            // invalidated iterator.
            S.pending_up_reads.erase(s.up_id);
#ifdef SNNDL_ENABLE_DEBUG_LOG
            out_.verbose(CALL_INFO, 2, 0,
                "[diag-gbi] pending erase up_id=%" PRIu64 " remaining=%zu\n",
                (uint64_t)s.up_id, (size_t)S.pending_up_reads.size());
#endif
        }

        // 标记此 granule 为已完成（可以清空）
        completed_keys.push_back(key);
    }

    // 只清空已完成的 granules（ready 且已发回的）
    for (auto key : completed_keys) {
        S.granules.erase(key);
        S.required_set.erase(key);
    }

    // 诊断：报告有多少 granules 被保留到下次处理
    size_t remaining_granules = S.granules.size();
    size_t remaining_pending = S.pending_up_reads.size();
    if (remaining_granules > 0 || remaining_pending > 0) {
        out_.verbose(CALL_INFO, 1, 0,
            "[diag-gbi] Apply buf=%d RETAINED: granules=%zu (not ready), pending_up_reads=%zu\n",
            buf, remaining_granules, remaining_pending);
    }

    // 清理其他窗口状态（但保留未完成的 granules 和 pending_up_reads）
    S.end_gather_seen = false;
    // Re-entrancy safety: do not clear staging_reads here; upstream callbacks during emission can
    // synchronously stage new reads that must be drained by clockTick() in the same Apply window.
    apply_pending_emit_ = !(S.granules.empty() && S.pending_up_reads.empty() && S.staging_reads.empty());
}

void GatherBufferIF::latchApplyBacklogResiduals_() {
    const auto& S = sb_[apply_buf_index_];
    apply_backlog_granules_residual_peak_ =
        std::max<uint64_t>(apply_backlog_granules_residual_peak_, static_cast<uint64_t>(S.granules.size()));
    apply_backlog_pending_up_reads_residual_peak_ =
        std::max<uint64_t>(apply_backlog_pending_up_reads_residual_peak_,
                           static_cast<uint64_t>(S.pending_up_reads.size()));
    // Keep this aligned with the step-gate debug probe's `down=` notion of in-flight downstream fragments.
    apply_backlog_inflight_residual_peak_ =
        std::max<uint64_t>(apply_backlog_inflight_residual_peak_, static_cast<uint64_t>(inflight_down_.size()));
}

void GatherBufferIF::latchApplyBacklogPeakAfterDue_() {
    const auto& S = sb_[apply_buf_index_];
    apply_backlog_granules_peak_after_due_ =
        std::max<uint64_t>(apply_backlog_granules_peak_after_due_, static_cast<uint64_t>(S.granules.size()));
    apply_backlog_pending_up_reads_peak_after_due_ =
        std::max<uint64_t>(apply_backlog_pending_up_reads_peak_after_due_,
                           static_cast<uint64_t>(S.pending_up_reads.size()));
    apply_backlog_inflight_peak_after_due_ =
        std::max<uint64_t>(apply_backlog_inflight_peak_after_due_, static_cast<uint64_t>(inflight_down_.size()));
}

bool GatherBufferIF::rebuildPendingAsGranules_(int buf) {
    auto& S = sb_[buf];
    if (S.pending_up_reads.empty()) return false;
    // 仅在当前窗口 granule 为空时尝试重建
    if (!S.granules.empty()) return false;
    uint64_t gsz = granuleSize();
    bool rebuilt = false;
    for (auto& kv : S.pending_up_reads) {
        auto* rd = kv.second;
        if (!rd) continue;
        bool use_row = (merge_==Merge::Row) || (merge_==Merge::Auto && row_bytes_guess_ > gsz);
        uint64_t base = (merge_==Merge::Cacheline || (merge_==Merge::Auto && !use_row)) ? alignDown(rd->pAddr, gsz)
                       : (use_row ? alignDown(rd->pAddr, row_bytes_guess_) : rd->pAddr);
        uint32_t sz = (merge_==Merge::None) ? rd->size : (use_row ? row_bytes_guess_ : gsz);
        GranuleKey key = makeGranuleKey_(base, sz);
        auto& g = ensureGranule_(buf, key);
        uint64_t off = (rd->pAddr >= base) ? (rd->pAddr - base) : 0;
        g.subs.push_back({rd->getID(), off, (uint32_t)rd->size});
        g.payload_bytes += (uint64_t)rd->size;
        rebuilt = true;
    }
    if (rebuilt && !defer_issue_until_apply_) {
        // Non-defer: issue all granules deterministically (bounded by inflight credits).
        issueUnissuedGranulesDeterministic_(buf);
    }
    if (rebuilt && out_.getVerboseLevel() >= 1) {
        out_.verbose(CALL_INFO, 1, 0,
            "[diag-gbi] rebuild pending->granules buf=%d granules=%zu pending=%zu\n",
            buf, S.granules.size(), S.pending_up_reads.size());
    }
    return rebuilt;
}

void GatherBufferIF::doFlushBuf_(int buf) {
    auto& S = sb_[buf];

    // 清理LRU结构（RAII容器直接清空）
    S.lru_list.clear();
    S.lru_map.clear();

    // 清理SRAM数据
    S.sram_blocks.clear();
    S.bytes_in_sram = 0;
}

void GatherBufferIF::touchLRU_(int buf, const GranuleKey& key) {
    auto& S = sb_[buf];

    auto it = S.lru_map.find(key);
    if (it != S.lru_map.end()) {
        // 移动到队尾（最近使用）
        S.lru_list.splice(S.lru_list.end(), S.lru_list, it->second);
    } else {
        // 新key：插入尾部并记录迭代器
        S.lru_list.push_back(key);
        auto it_list = std::prev(S.lru_list.end());
        S.lru_map.emplace(key, it_list);
    }
}

void GatherBufferIF::ensureCapacity_(int buf, uint64_t need) {
    auto& S = sb_[buf];

    // 淘汰最久未使用的节点（从front开始）
    while (S.bytes_in_sram + need > sram_bytes_ && !S.lru_list.empty()) {
        GranuleKey k = S.lru_list.front();
        S.lru_list.pop_front();
        S.lru_map.erase(k);
        // 从SRAM中移除对应数据（若存在）
        auto it = S.sram_blocks.find(k);
        if (it != S.sram_blocks.end()) {
            S.bytes_in_sram -= it->second.size();
            S.sram_blocks.erase(it);
            if (stat_evictions_) {
                stat_evictions_->addData(1);
            }
        }
    }

    S.bytes_in_sram += need;
}

bool GatherBufferIF::clockTick(Cycle_t) {
    if (!window_auto_) return false;
    if (experimental_stepgate_progress_enable_) {
        experimental_stepgate_progress_tick_++;
        const bool owner_ok =
            (experimental_stepgate_progress_owner_node_ < 0 || (int)node_id_param_ == experimental_stepgate_progress_owner_node_) &&
            (experimental_stepgate_progress_owner_core_ < 0 || (int)core_id_param_ == experimental_stepgate_progress_owner_core_);
        const bool cap_ok =
            (experimental_stepgate_progress_max_reports_ == 0 ||
             experimental_stepgate_progress_reports_ < experimental_stepgate_progress_max_reports_);
        if (owner_ok && cap_ok &&
            experimental_stepgate_progress_period_cycles_ > 0 &&
            (experimental_stepgate_progress_tick_ % experimental_stepgate_progress_period_cycles_) == 0) {
            const auto& gb = sb_[gather_buf_index_];
            const auto& ab = sb_[apply_buf_index_];
            uint64_t ab_frags_issued = 0;
            uint64_t ab_frags_done = 0;
            uint64_t ab_frags_total = 0;
            uint64_t ab_ready = 0;
            uint64_t ab_subs = 0;
            uint32_t ab_max_granule = 0;
            const uint64_t progress_now_ns = getCurrentSimTimeNano();
            uint64_t oldest_inflight_granule_age_ns = 0;
            for (const auto& kv : ab.granules) {
                const auto& g = kv.second;
                ab_frags_issued += static_cast<uint64_t>(g.frags_issued);
                ab_frags_done += static_cast<uint64_t>(g.frags_done);
                ab_frags_total += static_cast<uint64_t>(g.frags_total);
                ab_subs += static_cast<uint64_t>(g.subs.size());
                if (g.ready) ab_ready += 1;
                if (g.size > ab_max_granule) ab_max_granule = g.size;
                if (g.issued && !g.ready && g.issue_ns != 0 && progress_now_ns >= g.issue_ns) {
                    const uint64_t age_ns = progress_now_ns - g.issue_ns;
                    if (age_ns > oldest_inflight_granule_age_ns) {
                        oldest_inflight_granule_age_ns = age_ns;
                    }
                }
            }
            uint64_t apply_first_issue_delay_ns = 0;
            if (apply_begin_ns_ != 0 && apply_first_down_issue_ns_ != 0 &&
                apply_first_down_issue_ns_ >= apply_begin_ns_) {
                apply_first_issue_delay_ns = apply_first_down_issue_ns_ - apply_begin_ns_;
            }
            uint64_t apply_first_resp_delay_ns = 0;
            if (apply_begin_ns_ != 0 && apply_first_down_resp_ns_ != 0 &&
                apply_first_down_resp_ns_ >= apply_begin_ns_) {
                apply_first_resp_delay_ns = apply_first_down_resp_ns_ - apply_begin_ns_;
            }
            uint64_t apply_first_granule_done_delay_ns = 0;
            if (apply_begin_ns_ != 0 && apply_first_granule_done_ns_ != 0 &&
                apply_first_granule_done_ns_ >= apply_begin_ns_) {
                apply_first_granule_done_delay_ns = apply_first_granule_done_ns_ - apply_begin_ns_;
            }
            uint64_t apply_first_up_resp_delay_ns = 0;
            if (apply_begin_ns_ != 0 && apply_first_up_resp_ns_ != 0 &&
                apply_first_up_resp_ns_ >= apply_begin_ns_) {
                apply_first_up_resp_delay_ns = apply_first_up_resp_ns_ - apply_begin_ns_;
            }
            out_.verbose(
                CALL_INFO, 0, 0,
                "[exp-gbi-progress] node=%u core=%u tick=%" PRIu64 " stage=%d gid=%" PRIu64 " sc=%" PRIu64
                " inflight0=%" PRIu64 " inflight1=%" PRIu64 " down=%zu"
                " gb(g=%zu req=%zu pend=%zu stg=%zu end_g=%d)"
                " ab(g=%zu req=%zu pend=%zu stg=%zu ready=%" PRIu64 " subs=%" PRIu64 " fi=%" PRIu64 " fd=%" PRIu64 " ft=%" PRIu64 " gmax=%u aid=%" PRIu64 " ard=%" PRIu64 " acd=%" PRIu64 " aud=%" PRIu64 " dr=%" PRIu64 " gd=%" PRIu64 " ur=%" PRIu64 " oldest=%" PRIu64 ")"
                " end_scatter_pending=%d end_scatter_seq=%u apply_pending_emit=%d\n",
                node_id_param_, core_id_param_,
                (uint64_t)experimental_stepgate_progress_tick_,
                (int)stage_, (uint64_t)current_gather_id_, (uint64_t)stage_counter_,
                (uint64_t)inflight_counts_[0], (uint64_t)inflight_counts_[1], inflight_down_.size(),
                gb.granules.size(), gb.required_set.size(), gb.pending_up_reads.size(), gb.staging_reads.size(),
                gb.end_gather_seen ? 1 : 0,
                ab.granules.size(), ab.required_set.size(), ab.pending_up_reads.size(), ab.staging_reads.size(),
                ab_ready, ab_subs, ab_frags_issued, ab_frags_done, ab_frags_total, ab_max_granule,
                apply_first_issue_delay_ns, apply_first_resp_delay_ns,
                apply_first_granule_done_delay_ns, apply_first_up_resp_delay_ns,
                apply_down_resp_total_, apply_completed_granules_total_, apply_emitted_subreads_total_,
                oldest_inflight_granule_age_ns,
                end_scatter_req_pending_ ? 1 : 0,
                (unsigned)end_scatter_req_seq_,
                apply_pending_emit_ ? 1 : 0);
            experimental_stepgate_progress_reports_++;
        }
    }
    if (step_gate_enable_ && stage_ == Stage::Idle) {
        // step gate 模式下 Idle 表示“等待全局 START_STEP”，无需推进阶段
        uint64_t inflight_total = (uint64_t)(inflight_counts_[0] + inflight_counts_[1]);
        if (stat_inflight_peak_) stat_inflight_peak_->addData(inflight_total);
        if (inflight_total > win_inflight_peak_) win_inflight_peak_ = inflight_total;
        step_gate_wait_cycles_pending_++;
        return false;
    }
    if (!clock_tick_logged_) {
        if (out_.getVerboseLevel() >= 2) {
            out_.verbose(CALL_INFO, 2, 0,
                "[diag-gbi-clock] first tick stage=%d counter=%" PRIu64 " win_cyc_g=%" PRIu64 "\n",
                (int)stage_, stage_counter_, win_cyc_gather_);
        }
        clock_tick_logged_ = true;
    }
    stage_counter_++;
    if (stage_ == Stage::Gather) stage_cycles_accum_[0]++;
    else if (stage_ == Stage::Apply) stage_cycles_accum_[1]++;
    else if (stage_ == Stage::Scatter) stage_cycles_accum_[2]++;
    if (stage_ == Stage::Apply) {
        const uint64_t ready_q = countApplyIssuableGranules_(apply_buf_index_);
        if (ready_q > apply_ready_queue_peak_) {
            apply_ready_queue_peak_ = ready_q;
        }
        if (ready_q > 0) {
            apply_ready_queue_nonempty_cycles_total_++;
        } else {
            apply_issue_block_no_ready_total_++;
        }
    }
    if (stage_ == Stage::Gather) {
        // Step-gate mode: Gather should be ended explicitly by workload (EndGather),
        // not by fixed window_cycles_gather (preferred). For compatibility, window_cycles_gather
        // remains a fallback end condition when explicit EndGather is not used.
        if (step_gate_enable_) {
            if (sb_[gather_buf_index_].end_gather_seen) {
                maybeEnterApply_();
            } else {
                if (win_cyc_gather_ && stage_counter_ >= win_cyc_gather_) {
                    fallback_end_gather_count_++;
                    if (!warned_fallback_end_gather_) {
                        warned_fallback_end_gather_ = true;
                        out_.verbose(CALL_INFO, 0, 0,
                            "[warn-gbi] step_gate fallback EndGather via window_cycles_gather (count=%" PRIu64 ")\n",
                            (uint64_t)fallback_end_gather_count_);
                    }
                    sb_[gather_buf_index_].end_gather_seen = true;
                    maybeEnterApply_();
                } else {
                    tryAutoEndGather_();
                }
            }
        } else {
            const bool empty_window = sb_[gather_buf_index_].granules.empty() && sb_[gather_buf_index_].required_set.empty();
            if (empty_window) {
                // 尝试主动结束 Gather 并进入 Apply（即便没有边），保持窗口推进
                if (win_cyc_gather_ == 0 || stage_counter_ >= win_cyc_gather_) {
                    sb_[gather_buf_index_].end_gather_seen = true;
                    maybeEnterApply_();
                }
            } else {
                if (win_cyc_gather_ && stage_counter_ >= win_cyc_gather_) {
                    sb_[gather_buf_index_].end_gather_seen = true;
                    maybeEnterApply_();
                    // in immediate path stage_ may now be Idle or Scatter; optional wait handled there
                } else {
                    tryAutoEndGather_();
                }
            }
        }
    } else if (stage_ == Stage::Apply) {
        // Drain staged reads (collected during Gather/Apply) into merged granules, then issue.
        // This is required for row-window/gap-merge validation in dense microbench where reads
        // are often triggered at BeginApply.
        if (defer_issue_until_apply_ && (gap_merge_enable_ || row_window_enable_ || vlf_enable_) && !sb_[apply_buf_index_].staging_reads.empty()) {
            buildGranulesWithGapMergeBuf_(apply_buf_index_);
            sb_[apply_buf_index_].issue_order_dirty = true;
            rebuildIssueOrder_(apply_buf_index_);
            issueMoreUnissuedFromOrder_(apply_buf_index_);
        }
        // 并行：在Apply阶段也推进下一窗口的Gather构建与下发
        if (!step_gate_enable_ && double_buffer_enable_ && defer_issue_until_apply_ && !sb_[gather_buf_index_].staging_reads.empty()) {
            buildGranulesWithGapMergeBuf_(gather_buf_index_);
            // 直接按当前排序策略下发新窗口的 granule，实现与 Apply 并行（受 inflight 限制）。
            issueUnissuedGranulesDeterministic_(gather_buf_index_);
        }
        bool sample_apply_backlog_peak_after_due = false;
        if (win_cyc_apply_ != 0) {
            sample_apply_backlog_peak_after_due = (stage_counter_ >= win_cyc_apply_);
        } else {
            // No fixed Apply budget means the whole Apply residency is the overdue frontier we care about.
            sample_apply_backlog_peak_after_due = (stage_counter_ > 0);
        }
        if (sample_apply_backlog_peak_after_due) {
            latchApplyBacklogPeakAfterDue_();
        }
        if (apply_auto_end_enable_) {
            if (tryAutoEndApply_()) return false;
        }
        if (win_cyc_apply_ && stage_counter_ >= win_cyc_apply_) {
            bool attempt_finish = true;
            if (step_gate_enable_) {
                // Step-gate fallback: avoid calling finishApplyWindow_() every cycle after the first due tick.
                // This reduces host-side spin overhead when Apply drains slowly at scale.
                const uint64_t poll = experimental_stepgate_apply_finish_poll_period_cycles_
                                          ? experimental_stepgate_apply_finish_poll_period_cycles_
                                          : 1;
                const uint64_t delta = (stage_counter_ > win_cyc_apply_) ? (stage_counter_ - win_cyc_apply_) : 0;
                if ((delta % poll) != 0) {
                    attempt_finish = false;
                } else {
                    fallback_end_apply_count_++;
                    if (!warned_fallback_end_apply_) {
                        warned_fallback_end_apply_ = true;
                        out_.verbose(CALL_INFO, 0, 0,
                            "[warn-gbi] step_gate fallback EndApply via window_cycles_apply (count=%" PRIu64 ")\n",
                            (uint64_t)fallback_end_apply_count_);
                    }
                }
            }
            if (attempt_finish) {
                if (!finishApplyWindow_("apply-cycle-limit")) return false;
            }
        }
    } else if (stage_ == Stage::Scatter) {
        bool scatter_due = false;
        const char* scatter_reason = nullptr;
        if (step_gate_enable_) {
            if (end_scatter_req_pending_ && end_scatter_req_seq_ == static_cast<uint32_t>(current_gather_id_)) {
                scatter_due = true;
                scatter_reason = "scatter-explicit";
            } else if (scatter_immediate_complete_ && stage_counter_ >= 1) {
                scatter_due = true;
                scatter_reason = "scatter-immediate";
            } else if (win_cyc_scatter_ && stage_counter_ >= win_cyc_scatter_) {
                scatter_due = true;
                scatter_reason = "scatter-cycle";
            }
        } else {
            if (scatter_immediate_complete_ && stage_counter_ >= 1) {
                scatter_due = true;
                scatter_reason = "scatter-immediate";
            } else if (win_cyc_scatter_ && stage_counter_ >= win_cyc_scatter_) {
                scatter_due = true;
                scatter_reason = "scatter-cycle";
            }
        }
        if (step_gate_enable_ && scatter_due && scatter_reason &&
            std::strcmp(scatter_reason, "scatter-explicit") != 0) {
            const auto& ab = sb_[apply_buf_index_];
            const bool drained =
                (inflight_counts_[apply_buf_index_] == 0) &&
                (inflight_counts_[gather_buf_index_] == 0) &&
                ab.pending_up_reads.empty() &&
                ab.required_set.empty() &&
                ab.granules.empty() &&
                ab.staging_reads.empty();
            if (!drained) {
                // Step-gate fallback completion must not end a step with inflight/pending transactions.
                // Keep waiting until downstream drains.
                return false;
            }
        }
        if (scatter_due) {
            if (step_gate_enable_ && scatter_reason && std::strcmp(scatter_reason, "scatter-explicit") != 0) {
                fallback_end_scatter_count_++;
                if (!warned_fallback_end_scatter_) {
                    warned_fallback_end_scatter_ = true;
                    out_.verbose(CALL_INFO, 0, 0,
                        "[warn-gbi] step_gate fallback EndScatter via %s (count=%" PRIu64 ")\n",
                        scatter_reason, (uint64_t)fallback_end_scatter_count_);
                }
            }
            // Byte-exact correctness: emit PASS marker (or fatal) at window boundary.
            finishByteExact_();
            flushStageCycles_(Stage::Scatter, true);
            // start new gather window
            if (emit_stage_events_ && upstream_handler_) {
                auto* es = new GasOpData(GasOp::EndScatter, (uint32_t)current_gather_id_, 0, 1, false);
                auto* cr3 = new StandardMem::CustomResp((StandardMem::Request::id_t)0, es, 0, 0, 0);
                (*upstream_handler_)(cr3);
            }
            if (step_gate_enable_) {
                // Step-level gate：停在 Idle，等待 openStep(seq) 进入下一窗
                stage_ = Stage::Idle;
                stage_counter_ = 0;
                apply_begin_ns_ = 0;
                apply_first_down_issue_ns_ = 0;
                apply_first_down_resp_ns_ = 0;
                apply_first_granule_done_ns_ = 0;
                apply_first_up_resp_ns_ = 0;
                apply_down_resp_total_ = 0;
                apply_completed_granules_total_ = 0;
                apply_emitted_subreads_total_ = 0;
                apply_backlog_granules_residual_peak_ = 0;
                apply_backlog_pending_up_reads_residual_peak_ = 0;
                apply_backlog_inflight_residual_peak_ = 0;
                apply_backlog_granules_peak_after_due_ = 0;
                apply_backlog_pending_up_reads_peak_after_due_ = 0;
                apply_backlog_inflight_peak_after_due_ = 0;
                apply_issue_attempt_total_ = 0;
                apply_issue_success_total_ = 0;
                apply_issue_block_no_ready_total_ = 0;
                apply_issue_block_inflight_cap_total_ = 0;
                apply_issue_block_bank_credit_total_ = 0;
                apply_issue_block_downstream_busy_total_ = 0;
                apply_issue_block_retire_guard_total_ = 0;
                apply_ready_queue_peak_ = 0;
                apply_ready_queue_nonempty_cycles_total_ = 0;
                sb_[gather_buf_index_].end_gather_seen = false;
                end_scatter_req_pending_ = false;
                end_scatter_req_seq_ = 0;
            } else {
                stage_ = Stage::Gather; stage_counter_ = 0; sb_[gather_buf_index_].end_gather_seen = false; current_gather_id_++;
                if (emit_stage_events_ && upstream_handler_) {
                    auto* bg = new GasOpData(GasOp::BeginGather, (uint32_t)current_gather_id_, 0, 1, false);
                    auto* cr4 = new StandardMem::CustomResp((StandardMem::Request::id_t)0, bg, 0, 0, 0);
                    (*upstream_handler_)(cr4);
                }
                // 不清理 gather 缓冲，允许在 Apply 阶段已开始的下一窗口继续累积
                // 导入非Gather缓存
                if (!drainQueuedNonGatherReadsToGather_(ReadAttachKind::QueuedImport, 0, (int)stage_)) {
                    return false;
                }
            }
        }
    }
    // track inflight peak (sum of both buffers)
    uint64_t inflight_total = (uint64_t)(inflight_counts_[0] + inflight_counts_[1]);
    if (stat_inflight_peak_) stat_inflight_peak_->addData(inflight_total);
    if (inflight_total > win_inflight_peak_) win_inflight_peak_ = inflight_total;
    return false; // continue ticking
}

// === Adaptive-control helpers (definitions) ===
void GatherBufferIF::resetWindowMetrics_() {
    win_payload_bytes_ = 0;
    win_bursts_ = 0;
    win_seg_latency_sum_ns_ = 0;
    win_seg_count_ = 0;
    win_inflight_peak_ = inflight_counts_[0] + inflight_counts_[1];
    win_row_adj_same_ = 0;
    win_row_adj_total_ = 0;
    win_buffer_max_bytes_ = 0;
}

void GatherBufferIF::resetGatherAutoCounters_() {
    gather_bytes_accum_ = 0;
    gather_reads_accum_ = 0;
    gather_auto_triggered_ = false;
}

void GatherBufferIF::tryAutoEndGather_() {
    if (!window_auto_) return;
    if (!gather_auto_end_bytes_ && !gather_auto_end_reads_) return;
    // 避免在无任何需求时空转切窗
    if (sb_[gather_buf_index_].granules.empty() && sb_[gather_buf_index_].required_set.empty()) return;
    const bool bytes_hit = (gather_auto_end_bytes_ && gather_bytes_accum_ >= gather_auto_end_bytes_);
    const bool reads_hit = (gather_auto_end_reads_ && gather_reads_accum_ >= gather_auto_end_reads_);
    if (!bytes_hit && !reads_hit) return;
    gather_auto_triggered_ = true;
    if (out_.getVerboseLevel() >= 1) {
        out_.verbose(CALL_INFO, 1, 0,
            "[diag-gbi] AutoEndGather hit: stage=%d counter=%" PRIu64 " bytes=%" PRIu64 "/%" PRIu64 " reads=%" PRIu64 "/%" PRIu64 " granules=%zu required_set=%zu end_gather_seen=%d\n",
            (int)stage_, stage_counter_,
            gather_bytes_accum_, gather_auto_end_bytes_,
            gather_reads_accum_, gather_auto_end_reads_,
            sb_[gather_buf_index_].granules.size(), sb_[gather_buf_index_].required_set.size(),
            sb_[gather_buf_index_].end_gather_seen ? 1 : 0);
    }
    if (!sb_[gather_buf_index_].end_gather_seen) {
        sb_[gather_buf_index_].end_gather_seen = true;
    }
    if (stage_ == Stage::Gather) {
        maybeEnterApply_();
    }
}

bool GatherBufferIF::tryAutoEndApply_() {
    if (!window_auto_) return false;
    if (!apply_auto_end_enable_) return false;
    if (stage_ != Stage::Apply) return false;
    // 断言式诊断/健壮性：
    // Apply 自动结束不能只看 required_set 是否“全 ready”，否则在同一 cycle 内
    // 若有新的上游 Read 在 Apply 阶段到达（先进入 pending/staging、尚未被
    // buildGranulesWithGapMergeBuf_ 纳入 required_set），会出现：
    //   required_set 空 -> allReady=true -> 触发 FinishApplyWindow -> pending_up 仍悬挂
    // 导致窗口无法推进/全局 step barrier 永远 done=0。
    auto& S = sb_[apply_buf_index_];
    // 若存在待合并的 staged reads，说明 Apply 仍有未纳入 required_set 的工作，禁止 auto-end。
    if (!S.staging_reads.empty()) return false;
    // required_set 为空并不等价于“窗口无工作”，可能只是还没来得及把 pending 读转为 granule。
    if (S.required_set.empty()) {
        if (!S.pending_up_reads.empty()) return false;
        if (inflight_counts_[apply_buf_index_] != 0) return false;
        return finishApplyWindow_("apply-auto-empty");
    }
    bool allReady = true;
    for (auto key : S.required_set) {
        auto it = S.granules.find(key);
        if (it == S.granules.end() || !it->second.ready) {
            allReady = false;
            break;
        }
    }
    if (!allReady) return false;
    return finishApplyWindow_("apply-auto-all-ready");
}

bool GatherBufferIF::finishApplyWindow_(const char* reason) {
    if (out_.getVerboseLevel() >= 1) {
        size_t req_sz = sb_[apply_buf_index_].required_set.size();
        size_t gran_sz = sb_[apply_buf_index_].granules.size();
        size_t pend_sz = sb_[apply_buf_index_].pending_up_reads.size();
        out_.verbose(CALL_INFO, 1, 0,
            "[diag-gbi] FinishApplyWindow reason=%s gather_id=%" PRIu64 " stage_counter=%" PRIu64 " req=%zu granules=%zu pending_up=%zu inflight_apply=%" PRIu64 " inflight_gather=%" PRIu64 " gather_auto_triggered=%d bytes_accum=%" PRIu64 " reads_accum=%" PRIu64 "\n",
            (reason ? reason : "unspecified"), current_gather_id_, stage_counter_,
            req_sz, gran_sz, pend_sz,
            inflight_counts_[apply_buf_index_], inflight_counts_[gather_buf_index_],
            gather_auto_triggered_ ? 1 : 0, gather_bytes_accum_, gather_reads_accum_);
    }
    flushStageCycles_(Stage::Apply, false);
    // 始终在窗口结束时向上游发回已ready的响应，避免非defer路径丢失回传
    emitApplyResponsesBuf_(apply_buf_index_);
    latchApplyBacklogResiduals_();
    // 非延后模式：确保 Apply 窗口不会在“仍有 required granule 未发/未完成”时结束；
    // 这类提前结束会导致权重读丢失，从而引入发放统计的非确定性。
    // 额外防护：如果 granules/required 已空、无 inflight，但 pending_up_reads 仍悬挂，
    // 先尝试把 pending 重新构造成 granule 并下发；如仍未清理，则维持在 Apply 等待。
    if (sb_[apply_buf_index_].granules.empty() &&
        sb_[apply_buf_index_].required_set.empty() &&
        inflight_counts_[apply_buf_index_] == 0 &&
        inflight_counts_[gather_buf_index_] == 0 &&
        !sb_[apply_buf_index_].pending_up_reads.empty()) {
        if (rebuildPendingAsGranules_(apply_buf_index_)) {
            apply_pending_emit_ = true;
            apply_issue_block_retire_guard_total_++;
            return false; // 等待重建后的读返回
        }
        // 如确实无法重建，保持等待，避免零填破坏发放
        apply_pending_emit_ = true;
        apply_issue_block_retire_guard_total_++;
        return false;
    }
    if (!defer_issue_until_apply_) {
        // 先尝试补发未发 granule（inflight 限制由 issueGranuleBuf_ 内部处理）
        issueUnissuedGranulesDeterministic_(apply_buf_index_);
        // 若仍有未完成工作，则继续停留在 Apply，等待后续响应/补发完成
        if (!sb_[apply_buf_index_].required_set.empty() ||
            !sb_[apply_buf_index_].granules.empty() ||
            !sb_[apply_buf_index_].pending_up_reads.empty()) {
            apply_pending_emit_ = true;
            apply_issue_block_retire_guard_total_++;
            return false;
        }
    }
    if (emit_stage_events_ && upstream_handler_) {
        if (inflight_counts_[apply_buf_index_] == 0 || emit_lenient_) {
            auto* ea = new GasOpData(GasOp::EndApply, (uint32_t)current_gather_id_, 0, 1, false);
            auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, ea, 0, 0, 0);
            (*upstream_handler_)(cr);
        } else {
            apply_pending_emit_ = true;
            apply_issue_block_retire_guard_total_++;
            return false; // wait for downstream drain
        }
    }
    if (apply_credit_external_enable_ && stat_apply_bank_credit_effective_) {
        stat_apply_bank_credit_effective_->addData(apply_bank_credit_dyn_);
    }
    if (upstream_handler_) {
        uint64_t apply_first_issue_delay_ns = 0;
        if (apply_begin_ns_ != 0 && apply_first_down_issue_ns_ != 0 &&
            apply_first_down_issue_ns_ >= apply_begin_ns_) {
            apply_first_issue_delay_ns = apply_first_down_issue_ns_ - apply_begin_ns_;
        }
        uint64_t apply_first_down_resp_delay_ns = 0;
        if (apply_begin_ns_ != 0 && apply_first_down_resp_ns_ != 0 &&
            apply_first_down_resp_ns_ >= apply_begin_ns_) {
            apply_first_down_resp_delay_ns = apply_first_down_resp_ns_ - apply_begin_ns_;
        }
        uint64_t apply_first_granule_done_delay_ns = 0;
        if (apply_begin_ns_ != 0 && apply_first_granule_done_ns_ != 0 &&
            apply_first_granule_done_ns_ >= apply_begin_ns_) {
            apply_first_granule_done_delay_ns = apply_first_granule_done_ns_ - apply_begin_ns_;
        }
        uint64_t apply_first_up_resp_delay_ns = 0;
        if (apply_begin_ns_ != 0 && apply_first_up_resp_ns_ != 0 &&
            apply_first_up_resp_ns_ >= apply_begin_ns_) {
            apply_first_up_resp_delay_ns = apply_first_up_resp_ns_ - apply_begin_ns_;
        }
        auto* s = new GasStatData((uint32_t)current_gather_id_, 0, 0);
        s->apply_issue_attempt_total = apply_issue_attempt_total_;
        s->apply_issue_success_total = apply_issue_success_total_;
        s->apply_issue_block_no_ready_total = apply_issue_block_no_ready_total_;
        s->apply_issue_block_inflight_cap_total = apply_issue_block_inflight_cap_total_;
        s->apply_issue_block_bank_credit_total = apply_issue_block_bank_credit_total_;
        s->apply_issue_block_downstream_busy_total = apply_issue_block_downstream_busy_total_;
        s->apply_issue_block_retire_guard_total = apply_issue_block_retire_guard_total_;
        s->apply_ready_queue_peak = apply_ready_queue_peak_;
        s->apply_ready_queue_nonempty_cycles_total = apply_ready_queue_nonempty_cycles_total_;
        s->apply_first_issue_delay_ns = apply_first_issue_delay_ns;
        s->apply_first_down_resp_delay_ns = apply_first_down_resp_delay_ns;
        s->apply_first_granule_done_delay_ns = apply_first_granule_done_delay_ns;
        s->apply_first_up_resp_delay_ns = apply_first_up_resp_delay_ns;
        s->apply_down_resp_total = apply_down_resp_total_;
        s->apply_completed_granules_total = apply_completed_granules_total_;
        s->apply_emitted_subreads_total = apply_emitted_subreads_total_;
        s->apply_backlog_granules_residual = apply_backlog_granules_residual_peak_;
        s->apply_backlog_pending_up_reads_residual = apply_backlog_pending_up_reads_residual_peak_;
        s->apply_backlog_inflight_residual = apply_backlog_inflight_residual_peak_;
        s->apply_backlog_granules_peak_after_due = apply_backlog_granules_peak_after_due_;
        s->apply_backlog_pending_up_reads_peak_after_due = apply_backlog_pending_up_reads_peak_after_due_;
        s->apply_backlog_inflight_peak_after_due = apply_backlog_inflight_peak_after_due_;
        auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, s, 0, 0, 0);
        (*upstream_handler_)(cr);
    }
    stage_ = Stage::Scatter;
    stage_counter_ = 0;
    if (emit_stage_events_ && upstream_handler_) {
        auto* bs = new GasOpData(GasOp::BeginScatter, (uint32_t)current_gather_id_, 0, 1, false);
        auto* cr2 = new StandardMem::CustomResp((StandardMem::Request::id_t)0, bs, 0, 0, 0);
        (*upstream_handler_)(cr2);
    }
    if (k_adapt_enable_) {
        if (!oeff_samples_ns_.empty() && bw_eff_bytes_per_ns_ > 0.0) {
            uint64_t sum = 0; for (auto v : oeff_samples_ns_) sum += v;
            uint64_t oeff_avg = sum / (uint64_t)oeff_samples_ns_.size();
            double k_cand = (double)oeff_avg * bw_eff_bytes_per_ns_;
            uint64_t k_cand_bytes = (uint64_t)std::llround(k_cand);
            if (k_cand_bytes < k_min_bytes_) k_cand_bytes = k_min_bytes_;
            if (k_cand_bytes > k_max_bytes_) k_cand_bytes = k_max_bytes_;
            if (k_dyn_bytes_ == 0) k_dyn_bytes_ = k_cand_bytes;
            else {
                k_dyn_bytes_ = (uint64_t)std::llround((1.0 - k_alpha_k_) * (double)k_dyn_bytes_ + k_alpha_k_ * (double)k_cand_bytes);
            }
            k_window_updates_++;
            if (k_window_updates_ >= k_adapt_window_N_) {
                k_window_updates_ = 0;
                uint64_t delta = (k_dyn_bytes_ > gap_k_bytes_) ? (k_dyn_bytes_ - gap_k_bytes_) : (gap_k_bytes_ - k_dyn_bytes_);
                if ((gap_k_bytes_ == 0) || (delta >= k_delta_bytes_)) {
                    gap_k_bytes_ = k_dyn_bytes_;
                }
            }
            if (stat_k_dyn_bytes_) stat_k_dyn_bytes_->addData(k_dyn_bytes_);
            if (stat_oeff_ns_avg_) stat_oeff_ns_avg_->addData(oeff_avg);
            if (stat_bw_eff_bytes_per_us_) stat_bw_eff_bytes_per_us_->addData((uint64_t)std::llround(bw_eff_bytes_per_ns_ * 1000.0));
        }
        oeff_samples_ns_.clear();
    }
    if (flush_after_scatter_) doFlushBuf_(apply_buf_index_);
    controlStep_();
    return true;
}

void GatherBufferIF::flushStageCycles_(Stage stage, bool window_boundary) {
    if (!window_auto_) return;
    int idx = stageIndex_(stage);
    if (idx < 0) return;
    uint64_t val = stage_cycles_accum_[idx];
    stage_cycles_last_[idx] = val;
    stage_cycles_accum_[idx] = 0;
    Statistic<uint64_t>* stat = nullptr;
    if (idx == 0) stat = stat_stage_cycles_g_;
    else if (idx == 1) stat = stat_stage_cycles_a_;
    else if (idx == 2) stat = stat_stage_cycles_s_;
    if (stat) stat->addData(val);
    if (window_boundary && stage == Stage::Scatter) {
        if (stage_cycles_export_enable_ && !stage_cycles_csv_.empty()) {
            if (!stage_cycles_stream_.is_open()) {
                stage_cycles_stream_.open(stage_cycles_csv_, std::ios::out | std::ios::app);
                if (stage_cycles_stream_.good() && stage_cycles_stream_.tellp() > 0) {
                    stage_cycles_header_written_ = true;
                }
                if (stage_cycles_stream_.good() && !stage_cycles_header_written_) {
                    stage_cycles_stream_ << "window_id,gather_cycles,apply_cycles,scatter_cycles\n";
                    stage_cycles_header_written_ = true;
                }
            }
            if (stage_cycles_stream_.good()) {
                stage_cycles_stream_ << current_gather_id_ << ','
                                     << stage_cycles_last_[0] << ','
                                     << stage_cycles_last_[1] << ','
                                     << stage_cycles_last_[2] << '\n';
            }
        }
        stage_cycles_last_[0] = stage_cycles_last_[1] = stage_cycles_last_[2] = 0;
    }
}

int GatherBufferIF::stageIndex_(Stage stage) const {
    switch (stage) {
        case Stage::Gather: return 0;
        case Stage::Apply: return 1;
        case Stage::Scatter: return 2;
        default: return -1;
    }
}

std::vector<uint64_t> GatherBufferIF::parseCsvU64_(const std::string& s) {
    std::vector<uint64_t> v; std::string num;
    for (char c : s) {
        if (c==',' || c==' ' || c=='\t') { if (!num.empty()) { v.push_back((uint64_t)std::stoull(num)); num.clear(); } }
        else num.push_back(c);
    }
    if (!num.empty()) v.push_back((uint64_t)std::stoull(num));
    if (v.empty()) v.push_back(0);
    return v;
}

std::pair<uint64_t, uint64_t> GatherBufferIF::cmdCostNsForBank_(uint32_t bank_idx) const {
    (void)bank_idx;
    uint64_t hit_ns = std::max<uint64_t>(1ull, static_cast<uint64_t>(dram_cmd_t_row_hit_ns_));
    uint64_t miss_ns = std::max<uint64_t>(hit_ns, static_cast<uint64_t>(dram_cmd_t_row_miss_ns_));
    return {hit_ns, miss_ns};
}

bool GatherBufferIF::diagEnabled_(int level) const {
    if (out_.getVerboseLevel() >= level) return true;
    return diag_enable_ || debug_enable_;
}

void GatherBufferIF::exportGranuleRow_(uint64_t start_ns, uint32_t bytes) {
    if (export_granules_csv_.empty()) return;
    if (!granule_stream_.is_open()) {
        granule_stream_.open(export_granules_csv_, std::ios::out | std::ios::app);
        if (!granule_stream_.good()) return;
        if (granule_stream_.tellp() > 0) export_header_written_ = true;
        if (!export_header_written_) {
            granule_stream_ << "step,req_tile,owner_tile,burst_bytes,start_ns\n";
            export_header_written_ = true;
        }
    }
    granule_stream_ << current_gather_id_ << ','
                    << node_id_param_ << ','
                    << node_id_param_ << ','
                    << bytes << ','
                    << start_ns << '\n';
}

void GatherBufferIF::exportWindowMetricsRow_(uint64_t window_id, uint64_t payload_bytes, uint64_t bursts,
                                 uint64_t inflight_peak, uint64_t buffer_max) {
    if (export_window_metrics_csv_.empty()) return;
    if (!window_stream_.is_open()) {
        window_stream_.open(export_window_metrics_csv_, std::ios::out | std::ios::app);
        if (!window_stream_.good()) return;
        if (window_stream_.tellp() > 0) window_metrics_header_written_ = true;
        if (!window_metrics_header_written_) {
            window_stream_ << "window_id,payload_bytes,bursts,inflight_peak,buffer_max_bytes\n";
            window_metrics_header_written_ = true;
        }
    }
    window_stream_ << window_id << ',' << payload_bytes << ',' << bursts << ',' << inflight_peak << ',' << buffer_max << '\n';
    window_metrics_written_ = true;
    // reset buffer max for next window
    win_buffer_max_bytes_ = 0;
}

void GatherBufferIF::applyCtrlConfig_(uint64_t k, uint64_t rowwin_bytes, uint64_t timeout_ns) {
    // Apply k
    if (k == 0 || burst_bytes_max_ == 0) { gap_merge_enable_ = false; gap_k_bytes_ = 0; }
    else { gap_merge_enable_ = true; gap_k_bytes_ = k; }
    // Apply row-window params
    row_window_bytes_ = rowwin_bytes;
    row_window_enable_ = (row_window_bytes_ > 0);
    row_window_timeout_ns_ = timeout_ns;
}

void GatherBufferIF::controlStep_() {
    uint64_t win_payload = win_payload_bytes_;
    uint64_t win_bursts = win_bursts_;
    uint64_t win_inflight = win_inflight_peak_;
    uint64_t win_buffer = win_buffer_max_bytes_;
    if (!export_window_metrics_csv_.empty()) {
        exportWindowMetricsRow_(current_gather_id_, win_payload, win_bursts, win_inflight, win_buffer);
    }
    if (upstream_handler_ && (win_inflight > 0 || win_buffer > 0)) {
        auto* s = new GasStatData((uint32_t)current_gather_id_, 0, 0, 0, 0, 0, 0, win_inflight, win_buffer);
        auto* cr = new StandardMem::CustomResp((StandardMem::Request::id_t)0, s, 0, 0, 0);
        (*upstream_handler_)(cr);
    }
    if (!ctrl_enable_) { resetWindowMetrics_(); return; }
    // Compute window metrics
    double payload_mib = (win_payload_bytes_>0) ? ((double)win_payload_bytes_ / (1024.0*1024.0)) : 0.0;
    double reqs_per_mib = (payload_mib>0.0 && win_bursts_>0) ? ((double)win_bursts_/payload_mib) : 0.0;
    double avg_seg_lat = (win_seg_count_>0) ? ((double)win_seg_latency_sum_ns_/ (double)win_seg_count_) : 0.0;
    // Initialize baseline after first full window
    ctrl_windows_seen_++;
    if (ctrl_windows_seen_ == 1) {
        ctrl_last_score_ = (reqs_per_mib>0)? reqs_per_mib : 1e12;
        ctrl_last_lat_ = avg_seg_lat;
        ctrl_curr_cfg_.k = gap_k_bytes_;
        ctrl_curr_cfg_.rowwin_bytes = row_window_bytes_;
        ctrl_curr_cfg_.timeout_ns = row_window_timeout_ns_;
        resetWindowMetrics_();
        return;
    }
    auto frac_improve = [](double base, double now){ return (base>0) ? ((base - now)/base) : 0.0; };
    bool lat_ok = (avg_seg_lat <= 0.0) || (ctrl_last_lat_<=0.0) || (avg_seg_lat <= ctrl_last_lat_ + (double)ctrl_lat_tol_ns_);
    if (ctrl_probe_active_) {
        // Decide adoption
        double imp_reqs = frac_improve(ctrl_last_score_, reqs_per_mib);
        double old_burst = (win_bursts_>0) ? ((double)win_payload_bytes_/(double)win_bursts_) : 0.0;
        // Allow adoption if reqs_per_mib improves or avg_burst increases, while latency is acceptable
        bool adopt = ((imp_reqs >= ctrl_eps_reqs_) || (old_burst > 0)) && lat_ok;
        if (adopt) {
            ctrl_curr_cfg_ = ctrl_probe_cfg_;
            ctrl_last_score_ = (reqs_per_mib>0)? reqs_per_mib : ctrl_last_score_;
            ctrl_last_lat_ = (avg_seg_lat>0)? avg_seg_lat : ctrl_last_lat_;
            if (stat_ctrl_adopts_) stat_ctrl_adopts_->addData(1);
            ctrl_cooldown_left_ = ctrl_cooldown_N_;
        } else {
            // revert
            applyCtrlConfig_(ctrl_curr_cfg_.k, ctrl_curr_cfg_.rowwin_bytes, ctrl_curr_cfg_.timeout_ns);
            if (stat_ctrl_reverts_) stat_ctrl_reverts_->addData(1);
            ctrl_cooldown_left_ = ctrl_cooldown_N_;
        }
        ctrl_probe_active_ = false;
    } else if (ctrl_cooldown_left_>0) {
        ctrl_cooldown_left_--;
    } else if (ctrl_probe_every_N_>0 && (ctrl_windows_seen_ % ctrl_probe_every_N_ == 0)) {
        // Choose next neighbor along current dimension
        auto idxOf=[&](const std::vector<uint64_t>&v, uint64_t x){ for(size_t i=0;i<v.size();++i) if (v[i]==x) return (int)i; return -1; };
        if (ctrl_dim_cursor_==0 && !ctrl_k_list_.empty()){
            int idx = idxOf(ctrl_k_list_, ctrl_curr_cfg_.k); if (idx<0) idx=0; int nxt = (idx+1) % (int)ctrl_k_list_.size();
            ctrl_probe_cfg_ = { ctrl_k_list_[nxt], ctrl_curr_cfg_.rowwin_bytes, ctrl_curr_cfg_.timeout_ns };
        } else if (ctrl_dim_cursor_==1 && !ctrl_rowwin_list_.empty()){
            int idx = idxOf(ctrl_rowwin_list_, ctrl_curr_cfg_.rowwin_bytes); if (idx<0) idx=0; int nxt = (idx+1) % (int)ctrl_rowwin_list_.size();
            ctrl_probe_cfg_ = { ctrl_curr_cfg_.k, ctrl_rowwin_list_[nxt], ctrl_curr_cfg_.timeout_ns };
        } else if (ctrl_dim_cursor_==2 && !ctrl_timeout_list_.empty()){
            int idx = idxOf(ctrl_timeout_list_, ctrl_curr_cfg_.timeout_ns); if (idx<0) idx=0; int nxt = (idx+1) % (int)ctrl_timeout_list_.size();
            ctrl_probe_cfg_ = { ctrl_curr_cfg_.k, ctrl_curr_cfg_.rowwin_bytes, ctrl_timeout_list_[nxt] };
        } else {
            resetWindowMetrics_();
            return;
        }
        applyCtrlConfig_(ctrl_probe_cfg_.k, ctrl_probe_cfg_.rowwin_bytes, ctrl_probe_cfg_.timeout_ns);
        ctrl_probe_active_ = true;
        ctrl_dim_cursor_ = (ctrl_dim_cursor_+1) % 3;
        if (stat_ctrl_probes_) stat_ctrl_probes_->addData(1);
    }
    // Reset metrics
    resetWindowMetrics_();
}

bool GatherBufferIF::byteExactVerifyEnabled_() const {
    return byte_exact_verify_enable_;
}

void GatherBufferIF::verifyByteExactDenseRowcol_(uint64_t addr, const std::vector<uint8_t>& data) {
    if (!byteExactVerifyEnabled_()) return;
    if (toLowerCopy(byte_exact_verify_mode_) != "dense_rowcol_v1") return;
    if (data.empty()) return;
    if (byte_exact_base_addr_ == 0 || byte_exact_cols_ == 0 || byte_exact_rows_ == 0) return;
    if (addr < byte_exact_base_addr_) return;

    const uint64_t off_bytes = addr - byte_exact_base_addr_;
    if ((off_bytes & 0x3ull) != 0ull) {
        out_.fatal(CALL_INFO, -1,
            "❌ [byte-exact] unaligned addr: node=%u core=%u base=0x%llx addr=0x%llx off=%" PRIu64 "\n",
            node_id_param_, core_id_param_,
            (unsigned long long)byte_exact_base_addr_,
            (unsigned long long)addr,
            off_bytes);
    }

    const std::string layout = toLowerCopy(byte_exact_dense_layout_mode_);
    const uint64_t cols = static_cast<uint64_t>(byte_exact_cols_);
    const uint64_t rows = static_cast<uint64_t>(byte_exact_rows_);
    const uint64_t logical_total_bytes = rows * cols * 4ull;

    auto alignUp = [&](uint64_t v, uint64_t a) -> uint64_t {
        if (a == 0) return v;
        return ((v + a - 1ull) / a) * a;
    };

    auto checkFloat = [&](uint32_t row, uint32_t col, const uint8_t* got_b, size_t float_i, bool padding_zero) {
        uint8_t expect_b[4] = {0, 0, 0, 0};
        float expect_f = 0.0f;
        if (!padding_zero) {
            const uint64_t v =
                static_cast<uint64_t>(row) * static_cast<uint64_t>(byte_exact_verify_row_scale_) +
                static_cast<uint64_t>(col);
            expect_f = static_cast<float>(v);
            std::memcpy(expect_b, &expect_f, sizeof(expect_b));
        }
        if (std::memcmp(got_b, expect_b, 4u) != 0) {
            byte_exact_mismatch_count_ += 1;
            if (byte_exact_mismatch_logged_ < byte_exact_verify_max_mismatch_) {
                byte_exact_mismatch_logged_ += 1;
                float got_f = 0.0f;
                std::memcpy(&got_f, got_b, sizeof(got_f));
                out_.verbose(CALL_INFO, 0, 0,
                    "[byte-exact] mismatch node=%u core=%u addr=0x%llx float_i=%zu row=%u col=%u got_f=%.9g expect_f=%.9g got=[%02x %02x %02x %02x] expect=[%02x %02x %02x %02x]\n",
                    node_id_param_, core_id_param_,
                    (unsigned long long)addr,
                    float_i, row, col,
                    got_f, expect_f,
                    got_b[0], got_b[1], got_b[2], got_b[3],
                    expect_b[0], expect_b[1], expect_b[2], expect_b[3]);
            }
            if (byte_exact_mismatch_count_ >= byte_exact_verify_max_mismatch_) {
                out_.fatal(CALL_INFO, -1,
                    "❌ [byte-exact] too many mismatches: node=%u core=%u mismatches=%u max=%u\n",
                    node_id_param_, core_id_param_,
                    byte_exact_mismatch_count_, byte_exact_verify_max_mismatch_);
            }
        }
    };

    if (layout == "phys_v1" || layout == "physv1") {
        const uint64_t line_bytes_u64 = granuleSize();
        const uint64_t line_bytes = (line_bytes_u64 > 0 && line_bytes_u64 <= (1ull << 20)) ? line_bytes_u64 : 64ull;
        const uint64_t dram_row_bytes = (byte_exact_dense_phys_dram_row_bytes_ > 0)
                                           ? static_cast<uint64_t>(byte_exact_dense_phys_dram_row_bytes_)
                                           : 0ull;
        if (dram_row_bytes == 0 || cols == 0) return;

        const uint64_t logical_row_bytes = cols * 4ull;
        const uint64_t row_stride_bytes = alignUp(logical_row_bytes, line_bytes);
        const uint64_t rows_per_dram_row = (row_stride_bytes <= dram_row_bytes)
                                               ? std::max<uint64_t>(1ull, dram_row_bytes / row_stride_bytes)
                                               : 1ull;
        const uint64_t group_stride_bytes = (row_stride_bytes <= dram_row_bytes)
                                                ? dram_row_bytes
                                                : alignUp(row_stride_bytes, dram_row_bytes);
        const uint64_t total_groups = (rows + rows_per_dram_row - 1ull) / rows_per_dram_row;
        const uint64_t phys_total_bytes = total_groups * group_stride_bytes;
        if (off_bytes >= phys_total_bytes) return;

        const size_t nbytes = std::min<size_t>(data.size(), static_cast<size_t>(phys_total_bytes - off_bytes));
        const size_t nfloat = nbytes / 4u;
        for (size_t i = 0; i < nfloat; ++i) {
            const uint64_t cur_off = off_bytes + static_cast<uint64_t>(i) * 4ull;
            const uint64_t group = cur_off / group_stride_bytes;
            const uint64_t within_group = cur_off % group_stride_bytes;
            const uint64_t within = within_group / row_stride_bytes;
            const uint64_t within_row = within_group % row_stride_bytes;
            const uint64_t row_u64 = group * rows_per_dram_row + within;
            const uint64_t col_u64 = within_row / 4ull;
            const bool padding_zero = (row_u64 >= rows) || (within_row >= logical_row_bytes);
            checkFloat(static_cast<uint32_t>(row_u64), static_cast<uint32_t>(col_u64), data.data() + i * 4u, i, padding_zero);
        }
        if (nfloat > 0) byte_exact_verified_frags_ += 1;
        return;
    }

    // Default: legacy row-major decoding.
    if (off_bytes >= logical_total_bytes) return;
    const size_t nbytes = std::min<size_t>(data.size(), static_cast<size_t>(logical_total_bytes - off_bytes));
    const size_t nfloat = nbytes / 4u;
    const uint64_t start_float = off_bytes / 4ull;
    for (size_t i = 0; i < nfloat; ++i) {
        const uint64_t idx = start_float + static_cast<uint64_t>(i);
        const uint32_t row = static_cast<uint32_t>(idx / cols);
        const uint32_t col = static_cast<uint32_t>(idx % cols);
        checkFloat(row, col, data.data() + i * 4u, i, /*padding_zero=*/false);
    }

    if (nfloat > 0) byte_exact_verified_frags_ += 1;
}

void GatherBufferIF::verifyByteExactRawBcsr_(uint64_t addr, const std::vector<uint8_t>& data) {
    if (!byteExactVerifyEnabled_()) return;
    if (toLowerCopy(byte_exact_verify_mode_) != "raw_bcsr_v1") return;
    if (data.empty()) return;
    if (byte_exact_max_resps_ == 0) return;
    if (byte_exact_base_addr_ == 0 || byte_exact_file_size_ == 0) return;
    if (!byte_exact_file_.is_open()) return;

    // Only verify addresses that map into the raw BCSR file region.
    if (addr < byte_exact_base_addr_) return;
    const uint64_t off = addr - byte_exact_base_addr_;
    if (off >= byte_exact_file_size_) {
        if (!byte_exact_skip_logged_) {
            out_.verbose(CALL_INFO, 0, 0,
                "BCSR_MERGE_READ_VERIFY: SKIP_OUT_OF_RANGE mode=%s node=%u core=%u addr=0x%llx base=0x%llx file_size=%" PRIu64 "\n",
                byte_exact_verify_mode_.c_str(),
                node_id_param_, core_id_param_,
                (unsigned long long)addr,
                (unsigned long long)byte_exact_base_addr_,
                byte_exact_file_size_);
            byte_exact_skip_logged_ = true;
        }
        return;
    }

    const bool offsets_sane =
        (byte_exact_colidx_offset_ > byte_exact_rowptr_offset_) &&
        (byte_exact_colidx_offset_ < byte_exact_file_size_) &&
        (byte_exact_blockdata_offset_ > byte_exact_colidx_offset_) &&
        (byte_exact_blockdata_offset_ < byte_exact_file_size_);
    const uint32_t required_mask = offsets_sane ? ((1u << 0) | (1u << 1) | (1u << 2)) : 0u;
    uint8_t region = 0;
    if (offsets_sane) {
        if (off >= byte_exact_blockdata_offset_) region = 2;
        else if (off >= byte_exact_colidx_offset_) region = 1;
        else region = 0;
    }

    // Coverage-driven sampling:
    // - When offsets are sane, prioritize verifying one fragment per segment (rowptr/colidx/blockdata).
    // - Skip already-covered regions to preserve the limited response budget.
    if (offsets_sane) {
        if ((byte_exact_region_verified_mask_ & required_mask) != required_mask) {
            if (byte_exact_region_verified_mask_ & (1u << region)) {
                return;
            }
        }
    }
    if (byte_exact_verified_resps_ >= byte_exact_max_resps_) return;

    const size_t nmax_data = std::min<size_t>(data.size(), (size_t)byte_exact_sample_bytes_);
    const size_t nmax_file = (size_t)std::min<uint64_t>((uint64_t)nmax_data, byte_exact_file_size_ - off);
    if (nmax_file == 0) return;

    std::vector<uint8_t> expect;
    expect.resize(nmax_file);
    {
        std::lock_guard<std::mutex> lk(byte_exact_mu_);
        byte_exact_file_.clear();
        byte_exact_file_.seekg((std::streamoff)off, std::ios::beg);
        byte_exact_file_.read(reinterpret_cast<char*>(expect.data()), (std::streamsize)nmax_file);
        const auto got = (size_t)byte_exact_file_.gcount();
        if (got != nmax_file) {
            out_.fatal(CALL_INFO, -1,
                "BCSR_MERGE_READ_VERIFY: file read short node=%u core=%u off=%" PRIu64 " want=%zu got=%zu file=%s\n",
                node_id_param_, core_id_param_, off, nmax_file, got, byte_exact_file_path_.c_str());
        }
    }

    if (std::memcmp(expect.data(), data.data(), nmax_file) != 0) {
        byte_exact_mismatch_count_ += 1;
        if (byte_exact_mismatch_logged_ < byte_exact_verify_max_mismatch_) {
            byte_exact_mismatch_logged_ += 1;
            // Print a short hexdump (first 16B) for debugging without log explosion.
            const size_t k = std::min<size_t>(16, nmax_file);
            std::string got_hex, exp_hex;
            got_hex.reserve(k * 3);
            exp_hex.reserve(k * 3);
            char buf[8];
            for (size_t i = 0; i < k; ++i) {
                std::snprintf(buf, sizeof(buf), "%02x", (unsigned)data[i]);
                got_hex += buf;
                if (i + 1 < k) got_hex += ' ';
                std::snprintf(buf, sizeof(buf), "%02x", (unsigned)expect[i]);
                exp_hex += buf;
                if (i + 1 < k) exp_hex += ' ';
            }
            out_.verbose(CALL_INFO, 0, 0,
                "BCSR_MERGE_READ_VERIFY: MISMATCH node=%u core=%u addr=0x%llx off=%" PRIu64 " n=%zu got=[%s] expect=[%s]\n",
                node_id_param_, core_id_param_,
                (unsigned long long)addr, off, nmax_file,
                got_hex.c_str(), exp_hex.c_str());
        }
        if (byte_exact_mismatch_count_ >= byte_exact_verify_max_mismatch_) {
            out_.fatal(CALL_INFO, -1,
                "BCSR_MERGE_READ_VERIFY: too many mismatches node=%u core=%u mismatches=%u max=%u\n",
                node_id_param_, core_id_param_,
                byte_exact_mismatch_count_, byte_exact_verify_max_mismatch_);
        }
    }

    if (offsets_sane) {
        byte_exact_region_verified_mask_ |= (1u << static_cast<uint32_t>(region));
    } else {
        // Without sane offsets, we cannot certify segment coverage.
        byte_exact_inconclusive_ = true;
        if (byte_exact_inconclusive_reason_.empty()) byte_exact_inconclusive_reason_ = "meta_offsets_unsane_or_missing";
    }
    byte_exact_verified_resps_ += 1;
}

void GatherBufferIF::finishByteExact_() {
    if (!byteExactVerifyEnabled_()) return;
    const std::string mode_l = toLowerCopy(byte_exact_verify_mode_);
    if (byte_exact_pass_logged_) return;
    if (byte_exact_mismatch_count_ != 0) {
        out_.fatal(CALL_INFO, -1,
            "BYTE_EXACT_VERIFY: mismatches=%u (expected 0) mode=%s node=%u core=%u\n",
            byte_exact_mismatch_count_, byte_exact_verify_mode_.c_str(), node_id_param_, core_id_param_);
    }
    if (mode_l == "dense_rowcol_v1") {
        if (byte_exact_verified_frags_ == 0) {
            // Multi-PE runs may legitimately have some PEs/cores with no local reads in a given step.
            // Do not fail the whole simulation; the validator still requires at least one PASS marker
            // when byte-exact is enabled (prevents false positives in 1PE).
            if (!byte_exact_skip_logged_) {
                out_.verbose(CALL_INFO, 0, 0,
                    "BYTE_EXACT_VERIFY: SKIP mode=%s node=%u core=%u verified_frags=0\n",
                    byte_exact_verify_mode_.c_str(),
                    node_id_param_, core_id_param_);
                byte_exact_skip_logged_ = true;
            }
            return;
        }
        out_.verbose(CALL_INFO, 0, 0,
            "BYTE_EXACT_VERIFY: PASS mode=%s node=%u core=%u verified_frags=%" PRIu64 "\n",
            byte_exact_verify_mode_.c_str(),
            node_id_param_, core_id_param_,
            byte_exact_verified_frags_);
        byte_exact_pass_logged_ = true;
        return;
    }
    if (mode_l == "raw_bcsr_v1") {
        const bool offsets_sane =
            (byte_exact_colidx_offset_ > byte_exact_rowptr_offset_) &&
            (byte_exact_colidx_offset_ < byte_exact_file_size_) &&
            (byte_exact_blockdata_offset_ > byte_exact_colidx_offset_) &&
            (byte_exact_blockdata_offset_ < byte_exact_file_size_);
        const uint32_t required_mask = offsets_sane ? ((1u << 0) | (1u << 1) | (1u << 2)) : 0u;
        const int rowptr_ok = (byte_exact_region_verified_mask_ & (1u << 0)) ? 1 : 0;
        const int colidx_ok = (byte_exact_region_verified_mask_ & (1u << 1)) ? 1 : 0;
        const int block_ok  = (byte_exact_region_verified_mask_ & (1u << 2)) ? 1 : 0;
        const bool regions_ok = offsets_sane && ((byte_exact_region_verified_mask_ & required_mask) == required_mask);

        if (byte_exact_verified_resps_ == 0) {
            out_.verbose(CALL_INFO, 0, 0,
                "BCSR_MERGE_READ_VERIFY: WARN INCONCLUSIVE mode=%s node=%u core=%u verified_resps=0 reason=no_verified_resps\n",
                byte_exact_verify_mode_.c_str(),
                node_id_param_, core_id_param_);
            byte_exact_pass_logged_ = true;
            return;
        }

        if (!regions_ok || required_mask == 0u || byte_exact_inconclusive_) {
            out_.verbose(CALL_INFO, 0, 0,
                "BCSR_MERGE_READ_VERIFY: WARN INCONCLUSIVE mode=%s node=%u core=%u regions=rowptr=%d colidx=%d blockdata=%d verified_resps=%u sample_bytes=%u reason=%s\n",
                byte_exact_verify_mode_.c_str(),
                node_id_param_, core_id_param_,
                rowptr_ok, colidx_ok, block_ok,
                byte_exact_verified_resps_,
                byte_exact_sample_bytes_,
                byte_exact_inconclusive_reason_.empty() ? "insufficient_region_coverage" : byte_exact_inconclusive_reason_.c_str());
        } else {
            out_.verbose(CALL_INFO, 0, 0,
                "BCSR_MERGE_READ_VERIFY: PASS mode=%s node=%u core=%u regions=rowptr=%d colidx=%d blockdata=%d verified_resps=%u sample_bytes=%u\n",
                byte_exact_verify_mode_.c_str(),
                node_id_param_, core_id_param_,
                rowptr_ok, colidx_ok, block_ok,
                byte_exact_verified_resps_,
                byte_exact_sample_bytes_);
        }
        byte_exact_pass_logged_ = true;
        return;
    }
}
