// -*- c++ -*-
//
// WeightLoader.h: 在init阶段通过StandardMem将权重写入内存的组件
//

#ifndef _SNNDL_WEIGHT_LOADER_H
#define _SNNDL_WEIGHT_LOADER_H

#include <sst/core/component.h>
#include <sst/core/link.h>
#include <sst/core/output.h>
#include <sst/core/interfaces/stdMem.h>
#include <sst/core/shared/sharedArray.h>
#include <unordered_map>
#include <unordered_set>
#include <deque>
#include <memory>
#include <vector>

namespace SST {
namespace SnnDL {

class WeightLoader : public SST::Component {
public:
    SST_ELI_REGISTER_COMPONENT(
        WeightLoader,
        "SnnDL",
        "WeightLoader",
        SST_ELI_ELEMENT_VERSION(1,0,0),
        "Init阶段从文件加载权重并写入内存",
        COMPONENT_CATEGORY_UNCATEGORIZED
    )

		    SST_ELI_DOCUMENT_PARAMS(
			        {"verbose", "日志详细级别", "0"},
		        {"node_id", "节点ID（仅用于诊断/loader_done事件标识）", "0"},
		        {"workload_impl", "工作负载实现: snn/stream/...", ""},
		        {"weight_file", "兼容旧参数：单文件路径(若提供将优先生效)", ""},
	        {"base_addr_start", "core0权重矩阵的起始地址", "0"},
	        {"per_core_stride", "相邻核心权重矩阵在内存中的地址跨度(字节)", "0"},
	        {"num_cores", "核心数", "1"},
	        {"neurons_per_core", "每核神经元数(形成 NxN 权重矩阵)", "64"},
        {"rows_per_core", "每核权重矩阵的行数(默认等于neurons_per_core)", "0"},
        {"cols_per_core", "每核权重矩阵的列数(默认等于neurons_per_core)", "0"},
        {"fill_value", "当无文件可用时使用的填充值(float)", "0.5"},
        {"weight_format", "权重文件格式: bin/csv/raw", "bin"},
        {"per_core_files", "是否按核心分文件(1=是,0=否)", "0"},
        {"file_template", "按核心分文件时的模板, 例如 weights_core{core}.bin", ""},
        {"single_file", "单文件路径(覆盖weight_file)", ""},
        {"row_major", "文件是否按行优先(1=是,0=否=列优先)", "1"},
        {"chunk_size_bytes", "每次写入的字节块大小(建议与cacheline一致)", "64"},
        {"validate_length", "是否校验文件长度与期望匹配", "1"},
        // 运行时种子写入：默认关闭；若开启但连接路径经过缓存，建议保持关闭以避免coherence拒绝Write
        {"timed_seed_enable", "是否在运行时第一个周期进行计时写入(1/0)", "1"},
        {"timed_seed_count", "每个核心用于种子写入的块数（行粒度），默认1", "1"},
	        {"timed_seed_allow_cache", "允许通过缓存层进行计时写入(0=默认不允许，避免Write被coherence拒绝)", "0"},
	        {"loader_done_key", "SharedArray键：写完权重后写1通知所有核心", ""}
	        ,
	        // 写后读回校验（调试用）：仅在 init/complete 阶段做 untimed read 并与文件片段比对
	        {"verify_readback_enable", "是否启用写后读回校验(1/0，仅调试)", "0"},
	        {"verify_readback_core", "读回校验目标 core（默认0）", "0"},
	        {"verify_readback_bytes", "每次读回校验的字节数（默认64）", "64"},
	        {"verify_readback_mode", "写后读回校验模式: raw_bcsr|dense_rowcol_v1（默认raw_bcsr）", "raw_bcsr"},
	        {"verify_readback_samples", "写后读回校验抽样点数量（dense 模式有效，默认16）", "16"},
	        {"verify_readback_seed", "写后读回校验抽样随机种子（dense 模式有效，默认314159）", "314159"},
	        {"verify_colidx_start_index", "BCSR colidx 抽样起点（index，默认441，对齐现有diag）", "441"}
	        ,
	        {"strict_loader_done", "若启用：必须通过写后读回校验后才发布 loader_done_key（用于防止权重写入不可见导致读回全0）", "0"},
	        {"min_raw_bcsr_chunk_bytes", "raw+BCSR 大文件的最小 chunk_size_bytes（过小会产生海量 untimed writes 并导致权重不可见/发放归零）", "4096"}
	        ,
	        // 运行期单点读回探针（用于确认“仿真期 timed Read”路径读到的字节是否与文件一致）
	        {"diag_runtime_read_enable", "是否启用运行期单点读回探针(1/0，仅调试)", "0"},
	        {"diag_runtime_read_core", "读回探针目标 core（默认0）", "0"},
	        {"diag_runtime_read_offset", "读回探针的 core 内偏移（默认0，表示 base_addr_start）", "0"},
	        {"diag_runtime_read_bytes", "读回探针字节数（默认64）", "64"}
	        ,
	        // BCSR 支持（可选）：当 weight_format=bcsr 或 bcsr_enable=1 时生效
	        {"bcsr_enable", "启用BCSR权重写入(1/0)", "0"},
	        {"bcsr_block_rows", "BCSR块行数br（需整除rows_per_core）", "16"},
        {"bcsr_block_cols", "BCSR块列数bc（需整除cols_per_core）", "16"},
        {"bcsr_val_bytes", "数值字节数（默认4=FP32）", "4"},
        {"bcsr_idx_bytes", "索引字节数（默认2=uint16）", "2"},
        {"bcsr_pattern", "BCSR生成模式：diag|full（默认diag，仅对fill模式）", "diag"}
        ,
        // Dense microbench correctness: deterministic write pattern for byte-exact validation.
        {"write_pattern_mode", "填充权重写入模式: const|dense_rowcol_v1（默认const）", "const"},
        {"write_pattern_row_scale", "dense_rowcol_v1 的 row_scale（默认1024）", "1024"}
    )

	    SST_ELI_DOCUMENT_SUBCOMPONENT_SLOTS(
	        {"memory", "StandardMem内存接口", "SST::Interfaces::StandardMem"}
	    )

	    SST_ELI_DOCUMENT_PORTS(
	        {"loader_done", "WeightLoader完成事件（可选，桥接跨rank loader_done_key）", {"SnnDL.LoaderDoneEvent"}}
	    )

    // 统计信息文档（Batch‑B: WeightLoader 写入画像）
    SST_ELI_DOCUMENT_STATISTICS(
        {"weight_bytes_written_total", "总写入字节（所有块累计）", "bytes", 1},
        {"weight_write_chunks_total", "写入块总数（所有chunk累计）", "chunks", 1},
        {"weight_write_chunk_bytes", "单次写入字节直方图", "bytes", 1},
        {"weight_write_latency_cycles", "写入端到端时延直方图（仅timed模式）", "cycles", 1},
        {"weight_write_total_cycles", "本次写入总耗时（cycle，仅timed模式，上报一次）", "cycles", 1}
    )

    WeightLoader(SST::ComponentId_t id, SST::Params& params);
    ~WeightLoader() override;

    void init(unsigned int phase) override;
    void setup() override;
    void complete(unsigned int phase) override;
    void finish() override;
    void handleMemoryResponse(SST::Interfaces::StandardMem::Request* req);

private:
    void loadFileOnce();
    void loadFileOnceRuntime();
    void issueWritesFill(float value);
    // Shared row-write implementation; timed=false uses sendUntimedData with posted=true,
    // timed=true uses timed send() with posted=false and tracks pending_writes_.
    void issueWritesForCoreFloatsImpl(int core, const std::vector<float>& wbuf, bool timed);
    void issueWritesForCoreFloats(int core, const std::vector<float>& wbuf);
    void issueWritesForCoreFloatsRuntime(int core, const std::vector<float>& wbuf);
    bool readFileAllFloats(const std::string& path, const std::string& fmt, std::vector<float>& out);
    bool readFileRaw(const std::string& path, std::vector<uint8_t>& out);
    void issueWritesRaw(int core, const std::vector<uint8_t>& data, bool timed);
    bool loadSingleFileAllCores(const std::string& path, const std::string& fmt);
    bool loadPerCoreFiles(const std::string& tmpl, const std::string& fmt);
    bool loadPerCoreFilesRuntime(const std::string& tmpl, const std::string& fmt);

	    SST::Output* output_;
	    SST::Interfaces::StandardMem* memory_;

	    // 若处于非 SNN 的通用 workload（例如 stream），WeightLoader 必须完全静默，
	    // 否则会污染/覆盖通用 workload 的内存测试区域并造成误判。
	    bool enabled_ = true;

	    int verbose_;
	    std::string weight_file_;
	    uint64_t base_addr_start_;
	    uint64_t per_core_stride_;
    int num_cores_;
    uint32_t neurons_per_core_;
    // 新增：显式行列配置，默认退回到neurons_per_core_（保持兼容）
    uint32_t rows_per_core_;
    uint32_t cols_per_core_;
    float fill_value_;
    std::string weight_format_;
    bool raw_mode_ = false;
    bool per_core_files_;
    std::string file_template_;
    std::string single_file_;
    bool row_major_;
    uint32_t chunk_size_bytes_;
    bool validate_length_;
    int file_core_offset_ = 0; // 读取单文件时偏移的核心数

    // Timed seed writes to ensure visibility in timed simulation
    bool timed_seed_enable_ = true;
    uint32_t timed_seed_count_ = 1; // controls max outstanding timed writes
    bool timed_seed_allow_cache_ = false; // 默认不通过缓存执行写入
    bool seed_done_ = false;
    bool clock_registered_ = false;
    SST::Cycle_t current_cycle_ = 0;
    // 写入统计（Batch‑B）
    Statistic<uint64_t>* stat_bytes_total_ = nullptr;
    Statistic<uint64_t>* stat_chunks_total_ = nullptr;
    Statistic<uint64_t>* stat_chunk_bytes_hist_ = nullptr;
    Statistic<uint64_t>* stat_write_latency_cycles_hist_ = nullptr;
    Statistic<uint64_t>* stat_write_total_cycles_ = nullptr;
    // 仅timed模式：记录发起周期与总耗时
    bool write_started_timed_ = false;
    uint64_t write_first_issue_cycle_ = 0;
    std::unordered_map<SST::Interfaces::StandardMem::Request::id_t, uint64_t> write_issue_cycle_;
    struct TimedRawJob {
        int core = 0;
        uint64_t base = 0;
        uint64_t rowptr_off = 0;
        uint64_t colidx_off = 0;
        uint64_t blockdata_off = 0;
        uint64_t blockids_off = 0;
        bool meta_ok = false;
        std::vector<uint8_t> data;
        size_t offset = 0;
    };
    std::deque<std::shared_ptr<TimedRawJob>> timed_raw_jobs_;
    uint32_t timed_write_window_ = 0;
    void driveTimedJobs_();
    int diag_timed_issue_count_ = 0;

    bool onClockTick(SST::Cycle_t cycle);
    // 参数规范化与健壮性检查
	    void normalizeParams_();
	    // 统一的分块写入帮助函数（带统计）
	    inline void sendWrite_(uint64_t addr, const std::vector<uint8_t>& payload, bool timed) {
        const uint64_t line = memory_ ? static_cast<uint64_t>(memory_->getLineSize()) : 0;
        if (line != 0 && payload.size() > static_cast<size_t>(line)) {
            // 强制分片：避免 memHierarchy Incoherent Cache 对“大于 cacheline 的访问”出现堆破坏。
            size_t off = 0;
            while (off < payload.size()) {
                const size_t n = std::min(static_cast<size_t>(line), payload.size() - off);
                std::vector<uint8_t> frag;
                frag.insert(frag.end(), payload.begin() + static_cast<ptrdiff_t>(off),
                            payload.begin() + static_cast<ptrdiff_t>(off + n));
                sendWrite_(addr + static_cast<uint64_t>(off), frag, timed);
                off += n;
            }
            return;
        }

	        auto* w = new SST::Interfaces::StandardMem::Write(addr, payload.size(), payload, !timed);
        // memHierarchy 的 Incoherent Cache 对“大于 cacheline 的 cacheable 写入”不可靠（可能造成堆破坏/非确定性）。
        // 默认策略：除非显式允许，否则一律标记为 non-cacheable；同时对 >line 的写强制 non-cacheable。
        if (w) {
            const bool allow_cache = timed && timed_seed_allow_cache_;
            if (!allow_cache) {
                w->setNoncacheable();
            }
        }
        if (timed) {
            // 记录发起周期（用于时延统计）
            write_issue_cycle_[w->getID()] = current_cycle_;
            memory_->send(w);
            pending_writes_++;
        } else {
            memory_->sendUntimedData(w);
        }
    // 统计：块大小/块数/字节数
    if (stat_chunk_bytes_hist_) stat_chunk_bytes_hist_->addData(static_cast<uint64_t>(payload.size()));
    if (stat_chunks_total_) stat_chunks_total_->addData(1);
    if (stat_bytes_total_) stat_bytes_total_->addData(static_cast<uint64_t>(payload.size()));
  }

  bool loaded_;
  bool runtime_load_needed_ = false;
	    uint32_t pending_writes_ = 0;
	    bool all_writes_completed_ = false;
	    std::string loader_done_key_;
	    uint32_t node_id_ = 0;
	    SST::Link* loader_done_link_ = nullptr;
	    bool loader_done_shared_initialized_ = false;
	    bool loader_done_published_ = false;
	    bool loader_done_event_sent_ = false;
	    SST::Shared::SharedArray<int> loader_done_shared_;
	    void publishLoaderDone_();

    // BCSR 配置
    bool bcsr_enable_ = false;
    uint32_t bcsr_br_ = 16;
    uint32_t bcsr_bc_ = 16;
    uint32_t bcsr_val_bytes_ = 4;
    uint32_t bcsr_idx_bytes_ = 2;
    std::string bcsr_pattern_ = "diag";
    void issueWritesBCSRFill(float value);

	    // 诊断计数（每实例独立）
	    int diag_chunk_count_ = 0;
	    bool diag_meta_logged_ = false;

    // ===== 写后读回校验（调试） =====
    bool verify_readback_enable_ = false;
    int verify_readback_core_ = 0;
    uint32_t verify_readback_bytes_ = 64;
    std::string verify_readback_mode_ = "raw_bcsr";
    uint32_t verify_readback_samples_ = 16;
    uint32_t verify_readback_seed_ = 314159;
	    uint32_t verify_colidx_start_index_ = 441;
	    bool verify_readback_issued_ = false;
    bool verify_readback_done_ = false;
    bool strict_loader_done_ = false;
    bool verify_failed_ = false;
    uint32_t min_raw_bcsr_chunk_bytes_ = 4096;
	    struct VerifyPending {
            int core = 0;
	        uint64_t addr = 0;
            uint8_t region = 0; // 0=rowptr,1=colidx,2=blockdata
	        std::string tag;
	        std::vector<uint8_t> expect;
	    };
    // dense_rowcol_v1: 由于部分 StandardMem 实现的 untimed ReadResp 可能不携带 data，
    // 我们在 setup 后通过 timed Read 完成抽样验证（仅在 verify_readback_enable=1 时启用）。
    std::vector<VerifyPending> verify_todo_{};
    // raw_bcsr multi-core sampling: record the actual cores included in verify_todo_.
    std::vector<int> verify_readback_cores_used_{};
    bool verify_readback_pass_logged_ = false;
    bool verify_readback_inconclusive_ = false;
    std::string verify_readback_inconclusive_reason_;
    uint32_t verify_readback_region_required_mask_ = 0;
    uint32_t verify_readback_region_done_mask_ = 0;
    std::unordered_map<SST::Interfaces::StandardMem::Request::id_t, VerifyPending> verify_pending_;
    void issueVerifyReadbacks_();
    void pollVerifyReadbacks_();
    static std::string hexDump_(const std::vector<uint8_t>& buf, size_t max_bytes);
    static bool readFileSlice_(const std::string& path, uint64_t off, size_t len, std::vector<uint8_t>& out);
    static bool parseMetaU64_(const std::string& meta_text, const char* key, uint64_t& out);
    static bool parseMetaU32_(const std::string& meta_text, const char* key, uint32_t& out);
    std::string resolveCorePath_(int core, bool meta) const;

    // ===== deterministic fill patterns (microbench correctness) =====
    std::string write_pattern_mode_ = "const";
    uint32_t write_pattern_row_scale_ = 1024;

    // ===== 运行期单点读回探针（调试）=====
    bool diag_runtime_read_enable_ = false;
    int diag_runtime_read_core_ = 0;
    uint64_t diag_runtime_read_offset_ = 0;
    uint32_t diag_runtime_read_bytes_ = 64;
    bool diag_runtime_read_issued_ = false;
    SST::Interfaces::StandardMem::Request::id_t diag_runtime_read_id_ = 0;
    uint64_t diag_runtime_read_addr_ = 0;
};

}
}

#endif
