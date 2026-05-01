// -*- c++ -*-
// GatherBufferIF.h: GAS-aware StandardMem front-end with scratchpad buffering

#pragma once

#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <cstdint>
#include <list>
#include <fstream>
#include <mutex>
#include <functional>

#include <sst/core/sst_config.h>
#include <sst/core/output.h>
#include <sst/core/interfaces/stdMem.h>

#include "IGasCreditGate.h"
#include "IGasStepGate.h"
#include "synapse/gas/GasCustomCmd.h"

namespace SST { namespace SnnDL {

class GatherBufferIF : public SST::Interfaces::StandardMem, public IGasStepGate, public IGasCreditGate {
public:
    SST_ELI_REGISTER_SUBCOMPONENT(
        GatherBufferIF,
        "SnnDL", "GatherBufferIF", SST_ELI_ELEMENT_VERSION(1,0,0),
        "GAS scratchpad + coalescing StandardMem front-end", SST::Interfaces::StandardMem)

    SST_ELI_DOCUMENT_PARAMS(
        {"verbose", "verbosity", "0"},
        {"merge_policy", "none|cacheline|row|auto", "cacheline"},
        {"sort_policy", "addr|row|bank_row", "row"},
        {"row_bytes_guess", "row bytes guess for ordering", "8192"},
        {"sram_bytes", "scratchpad capacity bytes", "262144"},
        {"gap_merge_enable", "Enable fine-grained gap merge (0/1)", "1"},
        {"gap_merge_k_bytes", "Gap merge threshold k (bytes); 0=disable", "0"},
        {"burst_bytes_max", "Max burst size (bytes) when merging", "65536"},
        {"vlf_enable", "Experimental: enable value-line fusion (cacheline-aligned, no-hole fusion) during staged segment build (0/1)", "0"},
        {"vlf_run_enable", "Experimental: allow merging adjacent cachelines into contiguous runs under VLF (0/1)", "0"},
        {"bank_bits", "Number of bits in bank field (0=disable bank_row)", "0"},
        {"bank_shift", "LSB bit index of bank field", "0"},
        {"bank_auto_enable", "Enable heuristic bank bits/shift auto-detect when bank_bits=0", "1"},
        {"bank_auto_min_banks", "Heuristic: minimum distinct banks expected", "4"},
        {"bank_auto_max_banks", "Heuristic: maximum distinct banks expected", "32"},
        {"apply_issue_policy", "Apply-stage issue policy: order", "order"},
        {"apply_frags_per_issue", "Apply-stage max downstream fragments per issue step (0=unlimited)", "1"},
        {"apply_bank_credit", "Apply-stage per-bank max active granules (0=unlimited)", "1"},
        {"apply_age_fair_ns", "Apply-stage fairness threshold (ns): force-issue when age >= threshold (0=disable)", "2000"},
        {"dram_cmd_cost_merge_enable", "Experimental: enable DRAM command-cost guided merge decisions at segment-build (0/1)", "0"},
        {"dram_cmd_t_row_hit_ns", "Experimental: DRAM command-cost model row-hit service ns (per line)", "30"},
        {"dram_cmd_t_row_miss_ns", "Experimental: DRAM command-cost model row-miss service ns (per line)", "120"},
        {"row_window_enable", "Enable coarse row-window merge (0/1)", "0"},
        {"row_window_bytes", "Row-window byte threshold to trigger burst", "0"},
        {"row_window_timeout_ns", "Row-window timeout to trigger burst (ns)", "0"},
        {"gather_auto_end_bytes", "Auto-end Gather window when accumulated upstream bytes reach threshold (0=disable)", "0"},
        {"gather_auto_end_reads", "Auto-end Gather window when accumulated upstream read count reaches threshold (0=disable)", "0"},
        {"sram_access_ns", "SRAM access latency (ns) for response emission", "0"},
        {"max_inflight_reads", "Gather phase max inflight to downstream", "128"},
        {"tail_wait_timeout_ns", "EndGather tail wait timeout (0=wait-all)", "0"},
        {"allow_apply_miss_read", "allow fetching in APPLY on miss", "0"},
        {"flush_after_scatter", "flush SRAM after scatter", "1"},
        {"defer_issue_until_apply", "defer issuing downstream reads until APPLY stage (deprecated; default disabled)", "0"},
        {"strict_mode", "gate reads strictly to Gather phase (1=strict)", "1"},
        {"double_buffer_enable", "enable Gather/Apply overlap with SB double-buffer (0/1)", "1"},
        {"window_auto", "enable time-driven GAS windows", "0"},
        {"step_gate_enable", "Step-level gate: only start new window on openStep() (0/1)", "0"},
        {"manual_window_drive", "deprecated (auto window always clock-driven; param kept for compatibility)", "0"},
        {"window_cycles_gather", "cycles of Gather window when window_auto=1", "0"},
        {"window_cycles_apply", "cycles to hold before emitting Apply responses", "0"},
        {"apply_auto_end_enable", "Enable early end of Apply stage on all data ready (0/1)", "1"},
        {"window_cycles_scatter", "cycles of Scatter window", "0"},
        {"scatter_immediate_complete", "Scatter completes immediately (0/1)", "0"},
        {"clock", "subcomponent clock when window_auto=1", "1GHz"},
        {"emit_stage_events", "Emit Begin/End Apply/Scatter events upstream (0/1). Auto-enabled when step_gate_enable=1", "0"},
        {"emit_stage_events_lenient", "Lenient emission: allow EndApply/Scatter even if inflight>0 at window boundary (0/1). Not allowed with step_gate_enable=1", "0"},
        {"stage_cycles_csv", "Optional CSV path to log per-window stage cycle counts", ""},
        {"probe_gas_csv", "(diagnostic) CSV path to dump probe-gas samples; empty to disable", ""},
        {"port", "shared port name for downstream standardInterface when loaded anonymously"},
        {"diag_enable", "启用诊断打印(0/1)", "0"},
        {"snndl_debug", "调试增强开关(0/1)", "0"},
        {"sentinel_enable", "启用 sentinel 调试输出(0/1)", "0"}
        ,
        // Experimental: step-gate progress watchdog (debugging only; disabled by default).
        {"experimental_stepgate_progress_enable", "启用 step-gate 进度探针(0/1)", "0"},
        {"experimental_stepgate_progress_period_cycles", "进度探针周期(cycles; 0=disable)", "0"},
        {"experimental_stepgate_progress_max_reports", "最多打印次数(0=unbounded)", "0"},
        {"experimental_stepgate_progress_dump_level", "打印信息等级(0=basic)", "0"},
        {"experimental_stepgate_progress_owner_node", "仅对指定 node_id 打印(-1=all)", "-1"},
        {"experimental_stepgate_progress_owner_core", "仅对指定 core_id 打印(-1=all)", "-1"},
        {"experimental_stepgate_apply_finish_poll_period_cycles", "step_gate 回退 EndApply 的 finish 重试周期(cycles; 1=每cycle重试)", "1"}
        ,
        // Dense microbench correctness: byte-exact validation (off by default).
        {"byte_exact_verify_enable", "启用字节级校验(0/1)", "0"},
        {"byte_exact_verify_mode", "校验模式: dense_rowcol_v1|raw_bcsr_v1", ""},
        {"byte_exact_verify_row_scale", "dense_rowcol_v1 的 row_scale（默认1024）", "1024"},
        {"byte_exact_verify_max_mismatch", "最多打印/允许的 mismatch 数（超过 fatal）", "8"},
        {"byte_exact_verify_base_addr", "dense_rowcol_v1 权重区基址（字节）", "0"},
        {"byte_exact_verify_rows", "dense_rowcol_v1 rows（用于范围约束）", "0"},
        {"byte_exact_verify_cols", "dense_rowcol_v1 cols（用于 row/col 反推）", "0"}
        ,
        {"byte_exact_dense_layout_mode", "dense_rowcol_v1 的 layout 解释: row_major|phys_v1（默认 row_major）", "row_major"},
        {"byte_exact_dense_phys_dram_row_bytes", "phys_v1: DRAM row bytes（例如 8192）", "0"}
        ,
        // BCSR merge-read correctness (raw file slice compare; off by default).
        {"byte_exact_verify_file_path", "raw_bcsr_v1: raw bcsr.bin 文件路径", ""},
        {"byte_exact_verify_sample_bytes", "raw_bcsr_v1: 每个 ReadResp 抽样校验的字节数", "64"},
        {"byte_exact_verify_max_resps", "raw_bcsr_v1: 最多校验的 ReadResp 次数（避免性能劣化）", "8"},
        {"byte_exact_verify_owner_node", "raw_bcsr_v1: 仅对指定 node 校验（-1=不限制）", "-1"},
        {"byte_exact_verify_owner_core", "raw_bcsr_v1: 仅对指定 core 校验（-1=不限制）", "-1"}
        ,
        // --- Adaptive control (Phase-1) ---
        {"ctrl_enable", "Enable window-level adaptive control (0/1)", "0"},
        {"ctrl_probe_every_N", "Probe a neighbor config every N windows", "4"},
        {"ctrl_cooldown_N", "Cooldown windows after each probe decision", "4"},
        {"ctrl_eps_reqs", "Adoption threshold on reqs_per_mib improvement (fraction)", "0.02"},
        {"ctrl_eps_burst", "Adoption threshold on avg_burst_bytes improvement (fraction)", "0.05"},
        {"ctrl_lat_tol_ns", "Latency tolerance (ns) for adoption", "1"},
        {"ctrl_k_list", "Candidate k list (bytes, CSV)", "512,1024,2048,4096,8192"},
        {"ctrl_rowwin_list", "Candidate row_window_bytes list (bytes, CSV)", "0,16384,32768,65536"},
        {"ctrl_timeout_list", "Candidate row_window_timeout list (ns, CSV)", "0,300,600"}
    )

    SST_ELI_DOCUMENT_PORTS(
        {"lowlink", "Port to memory hierarchy (shared with downstream standardInterface)", {}}
    )

    SST_ELI_DOCUMENT_STATISTICS(
        {"gas_unique_reads", "Number of unique coalesced reads issued downstream", "reads", 1},
        {"gas_unique_bytes", "Bytes covered by unique coalesced reads", "bytes", 1},
        {"gas_upstream_reads", "Number of upstream read requests received during Gather windows", "reads", 1},
        {"gas_reads_issued", "Number of granule reads issued downstream (diagnostic)", "reads", 1},
        {"gas_evictions", "Number of SRAM evictions (granules)", "evictions", 1},
        {"gas_inflight_peak", "Peak inflight downstream reads during Gather", "reads", 1},
        {"gas_tail_wait_ns", "Tail wait duration between EndGather and Apply (ns)", "ns", 1},
        {"gas_stage_cycles_gather", "Cycles spent in Gather stage (window mode)", "cycles", 1},
        {"gas_stage_cycles_apply", "Cycles spent in Apply stage (window mode)", "cycles", 1},
        {"gas_stage_cycles_scatter", "Cycles spent in Scatter stage (window mode)", "cycles", 1},
        {"gas_req_coalesce_size_bytes", "Granule size distribution (bytes)", "bytes", 1},
        {"gas_buffer_occupancy_bytes", "SRAM buffer occupancy sampled on fills (bytes)", "bytes", 1},
        {"gas_gap_absorbed_bytes", "Gap bytes absorbed by fine-grained merge (sum)", "bytes", 1},
        {"gas_row_window_triggers", "Number of row-window bursts (coarse merge)", "count", 1},
        {"gas_row_window_bytes", "Bytes issued by row-window bursts (sum)", "bytes", 1},
        {"gas_cmd_cost_veto", "Number of absorb attempts vetoed by cmd-cost model", "count", 1},
        {"gas_cmd_cost_veto_fine_gap", "Number of fine-gap absorb attempts vetoed by cmd-cost model", "count", 1},
        {"gas_cmd_cost_veto_row_window", "Number of row-window absorb attempts vetoed by cmd-cost model", "count", 1},
        // Segment diagnostics.
        {"gas_overfetch_bytes", "Overfetch bytes issued by segment merges (issued_bytes - payload_bytes)", "bytes", 1},
        {"gas_unique_line_count", "Approx unique cacheline count touched by staged reads (per window)", "count", 1},
        {"gas_covered_line_count", "Approx covered cacheline count by issued segments (per window)", "count", 1},
        {"gas_apply_bank_credit_effective", "Apply credit diagnostics: effective bank credit per window", "count", 1},
        // Adaptive-k (C3) statistics (registered unconditionally; collection gated by params)
        {"gas_k_dyn_bytes", "Adaptive-k dynamic threshold (bytes)", "bytes", 1},
        {"gas_oeff_ns_avg", "Per-window average fixed overhead O_eff (ns)", "ns", 1},
        {"gas_bw_eff_bytes_per_us", "Effective downstream bandwidth (bytes/us)", "bytes/us", 1},
        // Adaptive control (Phase-1)
        {"gas_ctrl_probes", "Number of control probes issued", "count", 1},
        {"gas_ctrl_adopts", "Number of adopted probe configurations", "count", 1},
        {"gas_ctrl_reverts", "Number of reverted probe configurations", "count", 1}
    )

    // API ctor
    GatherBufferIF(ComponentId_t id, Params& params, TimeConverter* time, HandlerBase* handler);
    // Serialization-only default
    GatherBufferIF() : SST::Interfaces::StandardMem() {}
    ~GatherBufferIF() override;

    // StandardMem virtuals
    void sendUntimedData(Request* req) override;
    Request* recvUntimedData() override;
    void send(Request* req) override;
    Request* poll() override; // unused: push-based
    Addr getLineSize() override;
    void setMemoryMappedAddressRegion(Addr start, Addr size) override;

    // Phases
    void init(unsigned int phase) override;
    void complete(unsigned int phase) override;
    void setup() override;
    void finish() override;

    // Deprecated no-op for legacy manual window drive APIs.
    void manualWindowTick();

    // IGasStepGate: step-level window start (only used when step_gate_enable=1)
    void openStep(uint32_t seq) override;
    // IGasCreditGate: set Apply-stage per-bank credit target for a specific step.
    void setApplyBankCreditTarget(uint32_t seq, uint32_t apply_bank_credit) override;

private:
    // P2: 参数化门控（仅参数，不再回退env）
    bool diag_enable_ = false;
    bool debug_enable_ = false;
    bool sentinel_enable_ = false;
    // Experimental: step-gate progress watchdog (debugging only; disabled by default).
    bool experimental_stepgate_progress_enable_ = false;
    uint64_t experimental_stepgate_progress_period_cycles_ = 0;
    uint32_t experimental_stepgate_progress_max_reports_ = 0;
    uint32_t experimental_stepgate_progress_dump_level_ = 0;
    int experimental_stepgate_progress_owner_node_ = -1;
    int experimental_stepgate_progress_owner_core_ = -1;
    uint32_t experimental_stepgate_progress_reports_ = 0;
    uint64_t experimental_stepgate_progress_tick_ = 0;
    uint64_t experimental_stepgate_apply_finish_poll_period_cycles_ = 1;

	    // Internal types
	    enum class Stage { Idle=0, Gather=1, Apply=2, Scatter=3 };
	    enum class Merge { None=0, Cacheline=1, Row=2, Auto=3 };
	    enum class Sort { Addr=0, Row=1, BankRow=2 };
	    enum class ApplyIssuePolicy { Order=0 };

    struct GranuleKey {
        uint64_t base;
        uint32_t size;
        bool operator==(const GranuleKey& other) const {
            return base == other.base && size == other.size;
        }
    };
    struct GranuleKeyHash {
        size_t operator()(const GranuleKey& key) const noexcept {
            const uint64_t h1 = std::hash<uint64_t>{}(key.base);
            const uint64_t h2 = std::hash<uint32_t>{}(key.size);
            return static_cast<size_t>(h1 ^ (h2 + 0x9e3779b97f4a7c15ULL + (h1 << 6) + (h1 >> 2)));
        }
    };

    struct SubReq {
        Request::id_t up_id;  // upstream Read ID
        uint64_t      offset; // offset within granule base
        uint32_t      size;   // bytes to return
    };
	    struct Granule {
	        uint64_t base; uint32_t size; std::vector<SubReq> subs;
	        bool issued=false; bool ready=false; uint64_t down_id=0;
	        uint64_t issue_ns=0; // adaptive k: time when issued downstream
	        uint64_t window_id=0; // gather/apply window ID for this granule
	        uint64_t payload_bytes = 0; // sum of upstream sub-request sizes (bytes)
	        uint64_t min_arrival_ns = 0; // min arrival time across sub-reads (ns); used for Apply fairness
	        // 下游分片：为兼容 memHierarchy.Cache（尤其 Incoherent L1），避免一次性发起 size>cache_line 的 GetS
	        // 导致 cache 在回包时越界拼 payload（表现为权重读脏/非确定性/发放归零）。
        uint32_t frag_bytes = 0;   // 每片字节数（通常=cache line）
        uint32_t frags_total = 0;  // 总片数
        uint32_t frags_issued = 0; // 已发起片数
        uint32_t frags_done = 0;   // 已完成片数

        // 缓存排序键（优化2：避免重复计算bankRowIndex/rowIndex）
        mutable uint64_t cached_sort_key = 0;
        mutable bool sort_key_valid = false;
    };

    struct DownFrag {
        int buf = 0;
        GranuleKey key{};
        uint32_t off = 0;
        uint32_t size = 0;
    };

    enum class ReadAttachKind : uint8_t {
        OpenStep,
        ManualBeginGather,
        QueuedImport,
        ImmediateSend,
    };

	    // Helpers
	    Merge parseMerge(const std::string& s) const;
	    Sort parseSort(const std::string& s) const;
	    ApplyIssuePolicy parseApplyIssuePolicy(const std::string& s) const;
    uint64_t alignDown(uint64_t addr, uint64_t bytes) const { return (addr/bytes)*bytes; }
    uint64_t granuleSize() const;
    uint64_t rowIndex(uint64_t addr) const { return row_bytes_effective_? (addr / row_bytes_effective_) : 0; }
    uint64_t bankIndex(uint64_t addr) const { return bank_bits_ ? ((addr >> bank_shift_) & ((1ull<<bank_bits_)-1)) : 0; }
    uint64_t bankRowIndex(uint64_t addr) const { return (bankIndex(addr) << 32) | (uint32_t)rowIndex(addr); }
	    GranuleKey makeGranuleKey_(uint64_t base, uint32_t size) const;
	    Granule& ensureGranule_(int buf, const GranuleKey& key);
	    static bool granuleKeyLess_(const GranuleKey& a, const GranuleKey& b);
	    void issueGranuleBuf_(int buf, const GranuleKey& key, Granule& g);
	    void issueGranuleBufBudget_(int buf, const GranuleKey& key, Granule& g, uint32_t max_frags_to_issue);
	    void onDownstreamResp_(Request* r);
    void maybeEnterApply_();
    void emitApplyResponsesBuf_(int buf);
    void doFlushBuf_(int buf);
    bool clockTick(Cycle_t currentCycle);
    // Build dynamic granules with gap/Lmax rules at Apply entry (when deferring issue)
    void buildGranulesWithGapMergeBuf_(int buf);
    void detectBankFieldsHeuristic_();
    void resetWindowMetrics_();
    void resetGatherAutoCounters_();
    void tryAutoEndGather_();
    bool tryAutoEndApply_();
    bool finishApplyWindow_(const char* reason);
    void flushStageCycles_(Stage stage, bool window_boundary);
    int stageIndex_(Stage stage) const;
    void controlStep_();
    void applyCtrlConfig_(uint64_t k, uint64_t rowwin_bytes, uint64_t timeout_ns);
    bool rebuildPendingAsGranules_(int buf);
    static std::vector<uint64_t> parseCsvU64_(const std::string& s);
    std::pair<uint64_t, uint64_t> cmdCostNsForBank_(uint32_t bank_idx) const;
	    uint64_t ensureSortKey_(Granule& g);
	    void rebuildIssueOrder_(int buf);
    void issueMoreUnissuedFromOrder_(int buf);
    void issueUnissuedGranulesDeterministic_(int buf);
    uint64_t countApplyIssuableGranules_(int buf) const;
    bool attachReadToGranule_(int tgt_buf,
                              SST::Interfaces::StandardMem::Read* rd,
                              ReadAttachKind kind,
                              bool issue_now,
                              uint32_t seq,
                              int stage,
                              int buf);
    bool drainQueuedNonGatherReadsToGather_(ReadAttachKind kind, uint32_t seq, int stage);
    bool byteExactVerifyEnabled_() const;
    void verifyByteExactDenseRowcol_(uint64_t addr, const std::vector<uint8_t>& data);
    void verifyByteExactRawBcsr_(uint64_t addr, const std::vector<uint8_t>& data);
    void finishByteExact_();

    // Backend
    SST::Interfaces::StandardMem* backend_ = nullptr; // downstream standardInterface
    TimeConverter* time_ = nullptr;
    HandlerBase* upstream_handler_ = nullptr; // to deliver responses to parent
    Output out_;
    std::string probe_csv_path_;
    bool probe_csv_header_written_ = false;

    // Config
    Merge merge_ = Merge::Cacheline;
    Sort sort_ = Sort::Row;
    uint32_t row_bytes_guess_ = 8192;
    uint32_t row_bytes_effective_ = 8192; // may be overridden by dram_row_bytes when dram-aware is enabled
    uint64_t sram_bytes_ = 256*1024;
    // Fine-grained merge knobs
    bool gap_merge_enable_ = true;
    uint64_t gap_k_bytes_ = 0;      // tolerated hole bytes; 0=disable gap merge
    uint64_t burst_bytes_max_ = 64*1024; // Lmax
    // Experimental: GCSS value-line fusion (no-hole cacheline fusion in staged builder).
    bool vlf_enable_ = false;
    bool vlf_run_enable_ = false;
    uint32_t bank_bits_ = 0;        // bank field width; 0 disables bank_row sort
    uint32_t bank_shift_ = 0;       // bank bit LSB
    bool bank_auto_enable_ = true;  // allow heuristic detection if bits==0
	    uint32_t bank_auto_min_banks_ = 4;
	    uint32_t bank_auto_max_banks_ = 32;
	    bool bank_auto_done_ = false;
	    // Apply-stage issue scheduling.
	    ApplyIssuePolicy apply_issue_policy_ = ApplyIssuePolicy::Order;
    uint32_t apply_frags_per_issue_ = 1; // max frags per scheduling step (0=unlimited)
    uint32_t apply_bank_credit_ = 1;     // max active granules per bank (0=unlimited)
    uint64_t apply_age_fair_ns_ = 2000;  // age fairness threshold (ns), 0=disable
    uint32_t apply_bank_credit_dyn_ = 1;
    // External per-step credit control (disabled until setApplyBankCreditTarget() is called).
    bool apply_credit_external_enable_ = false;
    uint32_t apply_credit_external_pending_seq_ = 0;
    uint32_t apply_credit_external_pending_credit_ = 0;
		    uint32_t sram_access_ns_ = 0;
    uint32_t max_inflight_reads_ = 128;
    uint64_t tail_wait_timeout_ns_ = 0; // 0 = wait all
    bool allow_apply_miss_read_ = false;
    bool flush_after_scatter_ = true;
    bool defer_issue_until_apply_ = false;
    bool strict_mode_ = true; // 非Gather阶段是否严格拦截读（默认开）
    bool double_buffer_enable_ = true; // 允许在Apply阶段在另一SB上并行Gather
    bool window_auto_ = false;
    bool step_gate_enable_ = false; // Step-level gate: pause after EndScatter until openStep()
    uint64_t win_cyc_gather_ = 0, win_cyc_apply_ = 0, win_cyc_scatter_ = 0;
    bool apply_auto_end_enable_ = true;
    bool scatter_immediate_complete_ = false;
    std::string clock_freq_ = "1GHz";
    bool emit_stage_events_ = false; // whether to emit stage change events upstream
    bool emit_lenient_ = false;      // allow EndApply emission even if inflight>0 at window boundary
    std::string stage_cycles_csv_;
    bool stage_cycles_header_written_ = false;
    std::ofstream stage_cycles_stream_; // 实例级文件流，避免跨实例静态流导致的析构竞态
    uint64_t stage_cycles_accum_[3] = {0,0,0};
    uint64_t stage_cycles_last_[3] = {0,0,0};
    bool stage_cycles_export_enable_ = false;
    uint64_t gather_auto_end_bytes_ = 0;
    uint64_t gather_auto_end_reads_ = 0;
    bool clock_tick_logged_ = false;
    uint64_t gather_bytes_accum_ = 0;
    uint64_t gather_reads_accum_ = 0;
    bool gather_auto_triggered_ = false;
    // --- Byte-exact correctness (dense microbench) ---
    bool byte_exact_verify_enable_ = false;
    std::string byte_exact_verify_mode_;
    uint32_t byte_exact_verify_row_scale_ = 1024;
    uint32_t byte_exact_verify_max_mismatch_ = 8;
    uint64_t byte_exact_base_addr_ = 0;
    uint32_t byte_exact_rows_ = 0;
    uint32_t byte_exact_cols_ = 0;
    std::string byte_exact_dense_layout_mode_ = "row_major";
    uint32_t byte_exact_dense_phys_dram_row_bytes_ = 0;
    // raw_bcsr_v1 (optional; byte_exact_* reused to avoid another config namespace)
    std::string byte_exact_file_path_;
    uint64_t byte_exact_file_size_ = 0;
    uint64_t byte_exact_rowptr_offset_ = 0;
    uint64_t byte_exact_colidx_offset_ = 0;
    uint64_t byte_exact_blockdata_offset_ = 0;
    uint32_t byte_exact_sample_bytes_ = 64;
    uint32_t byte_exact_max_resps_ = 8;
    int byte_exact_owner_node_ = -1;
    int byte_exact_owner_core_ = -1;
    uint32_t byte_exact_verified_resps_ = 0;
    uint32_t byte_exact_region_verified_mask_ = 0; // bit0=rowptr bit1=colidx bit2=blockdata
    bool byte_exact_inconclusive_ = false;
    std::string byte_exact_inconclusive_reason_;
    std::ifstream byte_exact_file_;
    mutable std::mutex byte_exact_mu_;
    uint32_t byte_exact_mismatch_count_ = 0;
    uint32_t byte_exact_mismatch_logged_ = 0;
    uint64_t byte_exact_verified_frags_ = 0;
    bool byte_exact_pass_logged_ = false;
    bool byte_exact_skip_logged_ = false;
    // --- Granule export (P1-2) ---
    std::string export_granules_csv_; // CSV path; empty to disable
    bool export_header_written_ = false;
    uint32_t node_id_param_ = 0;      // optional: for req/owner tile (single-PE defaults)
    uint32_t core_id_param_ = (uint32_t)-1; // optional: per-core diagnostics
    void exportGranuleRow_(uint64_t start_ns, uint32_t bytes);
    // --- Window metrics export (buffer/inflight peaks) ---
    std::string export_window_metrics_csv_;
    // 改为每实例独立流，避免静态流跨实例/跨核引发竞态与崩溃
    std::ofstream window_stream_;
    std::ofstream granule_stream_;
    bool window_metrics_header_written_ = false;
    bool window_metrics_written_ = false;
    uint64_t win_buffer_max_bytes_ = 0; // track per-window max buffer occupancy
    void exportWindowMetricsRow_(uint64_t window_id, uint64_t payload_bytes, uint64_t bursts,
                                 uint64_t inflight_peak, uint64_t buffer_max);
    void latchApplyBacklogResiduals_();
    void latchApplyBacklogPeakAfterDue_();
    // Coarse row-window knobs (skeleton; default disabled)
    bool row_window_enable_ = false;
    uint64_t row_window_bytes_ = 0;
    uint64_t row_window_timeout_ns_ = 0;

    // Experimental: DRAM command-cost guided merge decisions during segment build (row-local only).
    bool dram_cmd_cost_merge_enable_ = false;
    uint32_t dram_cmd_t_row_hit_ns_ = 30;
    uint32_t dram_cmd_t_row_miss_ns_ = 120;
    // Double-buffer indices
    int gather_buf_index_ = 0; // 当前接收/构建/发射（下轮）的SB
    int apply_buf_index_  = 1; // 当前用于Apply/回答上游的SB
    // --- Adaptive k (C3) ---
    bool k_adapt_enable_ = false;
    uint32_t k_adapt_window_N_ = 8; // update every N windows
    double k_alpha_bw_ = 0.2; // EMA for B_eff
    double k_alpha_k_ = 0.2;  // EMA for k_dyn
    uint64_t k_min_bytes_ = 512;
    uint64_t k_max_bytes_ = 64*1024;
    uint64_t k_delta_bytes_ = 512; // min change to update
    double bw_eff_bytes_per_ns_ = 0.0; // EMA bandwidth
    uint64_t k_dyn_bytes_ = 0; // EMA dynamic k
    uint64_t k_window_updates_ = 0; // count windows passed
    std::vector<uint64_t> oeff_samples_ns_; // O_eff samples per window (ns)

    // State
    Stage stage_ = Stage::Idle;
    uint64_t current_gather_id_ = 0;
    int diag_granule_build_logged_ = 0;
    // 双缓冲状态
    struct SBState {
        // LRU（RAII）：std::list + 迭代器，杜绝手工new/delete与悬挂指针
        std::list<GranuleKey> lru_list;  // front=最久未用, back=最近使用
        std::unordered_map<GranuleKey, std::list<GranuleKey>::iterator, GranuleKeyHash> lru_map; // key -> it

        std::unordered_map<GranuleKey, Granule, GranuleKeyHash> granules; // key->granule
        std::unordered_map<Request::id_t, SST::Interfaces::StandardMem::Read*> pending_up_reads; // upstream read map
        std::vector<SST::Interfaces::StandardMem::Read*> staging_reads;
        std::unordered_map<Request::id_t, uint64_t> staged_arrival_ns; // arrival time
        std::unordered_set<GranuleKey, GranuleKeyHash> required_set; // required granules
        // Apply阶段的确定性发射序列（避免每次 ReadResp 都对 granules 做全量排序）：
        // - 用于 defer_issue_until_apply=1 时保证“inflight 限流下仍能持续补发未发 granule”，防止卡死。
        // - 也可用于 Apply 阶段 miss-read/late-read 进入后，统一补发。
        std::vector<std::pair<uint64_t, GranuleKey>> issue_order; // (sort_key, key)
        size_t issue_cursor = 0;
        bool issue_order_dirty = true;
	        std::unordered_map<GranuleKey, std::vector<uint8_t>, GranuleKeyHash> sram_blocks; // key->data
	        uint64_t bytes_in_sram = 0;
	        bool end_gather_seen = false;

        // 构造函数：预分配容器空间（优化3）
        SBState() {
            granules.reserve(64);           // 假设每窗口约64个granule
            pending_up_reads.reserve(128);  // 假设约128个待处理读请求
            staging_reads.reserve(128);     // 假设约128个暂存读请求
            staged_arrival_ns.reserve(128); // 与staging_reads对应
            required_set.reserve(64);       // 与granules对应
            issue_order.reserve(64);
            lru_map.reserve(256);           // SRAM缓存块映射
            sram_blocks.reserve(256);       // SRAM数据块存储
        }
        ~SBState() = default;
    };
    SBState sb_[2];
    // 全局下行映射：down_id -> 归属 granule + 片内偏移
    std::unordered_map<Request::id_t, DownFrag> inflight_down_;
    uint64_t inflight_counts_[2] = {0,0};
    uint64_t stage_counter_ = 0; // cycles elapsed in current stage
    bool apply_pending_emit_ = false;
    std::vector<SST::Interfaces::StandardMem::Read*> queued_non_gather_reads_; // 非Gather阶段缓存的上游读

    // Step-gate explicit end handshake (Phase-X):
    // In window_auto=1 && step_gate_enable=1, Gather/Scatter should be ended by upstream workload,
    // not by fixed window_cycles_* caps. We latch EndScatter requests and let clockTick advance.
    bool end_scatter_req_pending_ = false;
    uint32_t end_scatter_req_seq_ = 0;
    uint64_t end_scatter_early_count_ = 0;
    bool warned_end_scatter_early_ = false;
    uint64_t fallback_end_gather_count_ = 0;
    uint64_t fallback_end_apply_count_ = 0;
    uint64_t fallback_end_scatter_count_ = 0;
    bool warned_fallback_end_gather_ = false;
    bool warned_fallback_end_apply_ = false;
    bool warned_fallback_end_scatter_ = false;

    // Utilities for LRU（带buf选择）
    void touchLRU_(int buf, const GranuleKey& key);
    void ensureCapacity_(int buf, uint64_t need);

    // Stats
    Statistic<uint64_t>* stat_unique_reads_ = nullptr;
    Statistic<uint64_t>* stat_unique_bytes_ = nullptr;
    Statistic<uint64_t>* stat_up_reads_ = nullptr;
    Statistic<uint64_t>* stat_evictions_ = nullptr;
    Statistic<uint64_t>* stat_inflight_peak_ = nullptr;
    Statistic<uint64_t>* stat_tail_wait_ns_ = nullptr;
    Statistic<uint64_t>* stat_stage_cycles_g_ = nullptr;
    Statistic<uint64_t>* stat_stage_cycles_a_ = nullptr;
    Statistic<uint64_t>* stat_stage_cycles_s_ = nullptr;
    Statistic<uint64_t>* stat_coalesce_granule_size_ = nullptr; // bytes per granule
    Statistic<uint64_t>* stat_buffer_occupancy_bytes_ = nullptr; // sampled on store
    Statistic<uint64_t>* stat_gap_absorbed_bytes_ = nullptr; // total gap bytes absorbed by gap merge
    Statistic<uint64_t>* stat_row_window_triggers_ = nullptr; // number of row-window bursts
    Statistic<uint64_t>* stat_row_window_bytes_ = nullptr;    // bytes issued due to row-window
    Statistic<uint64_t>* stat_cmd_cost_veto_ = nullptr;       // total cmd-cost veto decisions
    Statistic<uint64_t>* stat_cmd_cost_veto_fine_gap_ = nullptr; // fine-gap veto decisions
    Statistic<uint64_t>* stat_cmd_cost_veto_row_window_ = nullptr; // row-window veto decisions
    // Segment diagnostics.
    Statistic<uint64_t>* stat_overfetch_bytes_ = nullptr;     // issued_bytes - payload_bytes (sum over segments)
    Statistic<uint64_t>* stat_unique_line_count_ = nullptr;   // approx unique lines touched (per window)
    Statistic<uint64_t>* stat_covered_line_count_ = nullptr;  // approx covered lines by issued segments (per window)
    Statistic<uint64_t>* stat_apply_bank_credit_effective_ = nullptr;
	    // 门控诊断：下发到下游的唯一granule读次数
	    Statistic<uint64_t>* stat_reads_issued_ = nullptr;
    // Adaptive k stats
    Statistic<uint64_t>* stat_k_dyn_bytes_ = nullptr;         // current k dynamic (bytes)
    Statistic<uint64_t>* stat_oeff_ns_avg_ = nullptr;         // average O_eff per window (ns)
	    Statistic<uint64_t>* stat_bw_eff_bytes_per_us_ = nullptr; // scaled bandwidth (bytes/us)
	    // Control stats
	    Statistic<uint64_t>* stat_ctrl_probes_ = nullptr;
	    Statistic<uint64_t>* stat_ctrl_adopts_ = nullptr;
	    Statistic<uint64_t>* stat_ctrl_reverts_ = nullptr;

    // Time tracking (ns) for non-window mode
    uint64_t last_stage_change_ns_ = 0;
    uint64_t tail_wait_start_ns_ = 0;

    // --- Window metrics (for adaptive control) ---
    uint64_t win_payload_bytes_ = 0;   // sum of payload bytes across bursts in this window
    uint64_t win_bursts_ = 0;          // number of bursts (granules) issued in this window
    uint64_t win_seg_latency_sum_ns_ = 0; // sum of segment latencies
    uint64_t win_seg_count_ = 0;       // number of segments measured
	    uint64_t win_inflight_peak_ = 0;   // inflight peak within window
	    uint64_t win_row_adj_same_ = 0;    // adjacent pairs mapped to same (row or bank_row)
	    uint64_t win_row_adj_total_ = 0;   // total adjacent pairs considered

    // --- Adaptive control state ---
    bool ctrl_enable_ = false;
    uint32_t ctrl_probe_every_N_ = 4;
    uint32_t ctrl_cooldown_N_ = 4;
    double ctrl_eps_reqs_ = 0.02;   // 2%
    double ctrl_eps_burst_ = 0.05;  // 5%
    uint64_t ctrl_lat_tol_ns_ = 1;
    std::vector<uint64_t> ctrl_k_list_;
    std::vector<uint64_t> ctrl_rowwin_list_;
    std::vector<uint64_t> ctrl_timeout_list_;
    uint64_t ctrl_windows_seen_ = 0;
    uint32_t ctrl_dim_cursor_ = 0; // 0:k,1:rowwin,2:timeout
    uint32_t ctrl_cooldown_left_ = 0;
    bool ctrl_probe_active_ = false;
    struct CtrlCfg { uint64_t k; uint64_t rowwin_bytes; uint64_t timeout_ns; };
    CtrlCfg ctrl_curr_cfg_ {0,0,0}, ctrl_prev_cfg_{0,0,0}, ctrl_probe_cfg_{0,0,0};
    double ctrl_last_score_ = 0.0; // reqs_per_mib of current cfg (lower better)
    double ctrl_last_lat_ = 0.0;   // avg segment latency ns

	    bool warned_auto_custom_req_ = false;
	    bool warned_defer_issue_path_ = false;

    // Apply observability: keep cumulative counters so instant retire does not hide progress.
    uint64_t apply_begin_ns_ = 0;
    uint64_t apply_first_down_issue_ns_ = 0;
    uint64_t apply_first_down_resp_ns_ = 0;
    uint64_t apply_first_granule_done_ns_ = 0;
    uint64_t apply_first_up_resp_ns_ = 0;
    uint64_t apply_down_resp_total_ = 0;
    uint64_t apply_completed_granules_total_ = 0;
    uint64_t apply_emitted_subreads_total_ = 0;
    uint64_t apply_backlog_granules_residual_peak_ = 0;
    uint64_t apply_backlog_pending_up_reads_residual_peak_ = 0;
    uint64_t apply_backlog_inflight_residual_peak_ = 0;
    uint64_t apply_backlog_granules_peak_after_due_ = 0;
    uint64_t apply_backlog_pending_up_reads_peak_after_due_ = 0;
    uint64_t apply_backlog_inflight_peak_after_due_ = 0;
    uint64_t step_gate_wait_cycles_pending_ = 0;
    uint64_t apply_issue_attempt_total_ = 0;
    uint64_t apply_issue_success_total_ = 0;
    uint64_t apply_issue_block_no_ready_total_ = 0;
    uint64_t apply_issue_block_inflight_cap_total_ = 0;
    uint64_t apply_issue_block_bank_credit_total_ = 0;
    uint64_t apply_issue_block_downstream_busy_total_ = 0;
    uint64_t apply_issue_block_retire_guard_total_ = 0;
    uint64_t apply_ready_queue_peak_ = 0;
    uint64_t apply_ready_queue_nonempty_cycles_total_ = 0;

    bool diagEnabled_(int level = 1) const;
};

}} // namespace
