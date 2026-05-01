// -*- c++ -*-
//
// StepActivationSubsystem:
// - Step 级随机激活（选择 pre → 生成 fanout spikes → 注入到本 PE / 外部 PE）
// - 可选：基于 BCSR reachability 的路由采样（step_activation_use_bcsr_routes=1）
//
// 目标（Phase3）：
// - 将 Step 注入的“事务逻辑/BCSR 解析/调度状态”从 MultiCorePE 下沉为独立子系统；
// - MultiCorePE 仅作为控制壳：负责把时钟/阶段事件转发给子系统，并提供最小注入回调。

#pragma once

#include <cstdint>
#include <functional>
#include <limits>
#include <string>
#include <unordered_map>
#include <vector>

namespace SST { class Output; }
namespace SST { namespace Statistics { template <typename T> class Statistic; } }

namespace SST { namespace SnnDL {

class SpikeEvent;
class INocTransport;
class GlobalNeuronLayout;

class StepActivationSubsystem final {
public:
    struct Config {
        enum class PrePattern : uint32_t {
            BernoulliUniform = 0,
            Clustered = 1,
        };

        bool enable = false;
        double fraction = 0.0;
        uint32_t fanout = 0;
        uint64_t seed = 0xdecafbadULL;

        // 0=BeginGather 触发；>0=固定周期（cycle）
        uint64_t period_cycles = 0;
        // BeginGather 触发的 leader core（默认 0；-1 表示任意核心）
        int trigger_core = 0;

        bool reset_mem_each_step = false;
        double event_weight = 0.0;  // 预留（当前未参与注入权重；保持兼容）

        // 选择 pre 的模式：
        // - BernoulliUniform：逐神经元伯努利采样（默认；兼容历史行为）
        // - Clustered：每 core 选取若干连续的 pre 段（用于制造空间局部性，便于评估 merge 参数）
        PrePattern pre_pattern = PrePattern::BernoulliUniform;
        // Clustered 模式：每段连续 pre 的长度（单位：neuron）。0 表示自动（默认 64）。
        uint32_t pre_cluster_len = 0;
        // Microbench-only：保持“每 core 选源数量”不变，但将 pre_global 映射为全局范围内均匀采样，
        // 用于制造跨列/跨 bank 访问（验证 Apply 调度策略）。默认关闭以保持历史语义不漂移。
        bool pre_sample_global = false;

        // BCSR reachability 路由采样（仅影响“post 选择”）
        bool use_bcsr_routes = false;
        std::string bcsr_template;
        uint32_t bcsr_rows_per_core = 0;
        uint32_t bcsr_br = 16;
        uint32_t bcsr_bc = 16;
        uint32_t bcsr_idx_bytes = 2;
        uint32_t bcsr_val_bytes = 4;
        uint64_t bcsr_rowptr_offset = 0;
        uint64_t bcsr_colidx_offset = 0;
        uint64_t bcsr_blockdata_offset = 0;
        uint64_t bcsr_blockids_offset = 0;
        double bcsr_weight_epsilon = 0.0;
        bool log_enable = false;
        bool build_local_only = true;
        uint64_t bcsr_align = 64;
    };

    struct Runtime {
        SST::Output* log = nullptr;
        int node_id = 0;
        int total_nodes = 1;
        uint64_t global_neuron_base = 0;
        int num_cores = 1;
        int neurons_per_core = 1;
        // 兼容字段：仅用于诊断校验，实际口径以 layout 为准
        uint32_t neurons_per_pe_cfg = 0;
        bool sentinel_enabled = false;
        long step_diag_cap_cfg = 0;
        int step_diag_enable_cfg = 0;

        // 全局 neuron_id 布局的单一真源（fail-fast：不允许为空）
        const GlobalNeuronLayout* layout = nullptr;

        // NoC 抽象接口（Phase4-A1.3）：优先使用该接口进行注入/外发
        INocTransport* noc = nullptr;
        std::function<void()> reset_membranes;
        std::function<void(uint32_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t)> report_injection_summary;
    };

    struct Stats {
        SST::Statistics::Statistic<uint64_t>* invocations = nullptr;
        SST::Statistics::Statistic<uint64_t>* pre_selected = nullptr;
        SST::Statistics::Statistic<uint64_t>* spike_attempts = nullptr;
        SST::Statistics::Statistic<uint64_t>* spikes_injected = nullptr;
        SST::Statistics::Statistic<uint64_t>* route_hits = nullptr;
        SST::Statistics::Statistic<uint64_t>* route_misses = nullptr;
        SST::Statistics::Statistic<uint64_t>* local_drops = nullptr;
    };

    void configure(const Config& cfg);
    void bindRuntime(const Runtime& rt);
    void bindStats(const Stats& st);

    // 仅当 enable && use_bcsr_routes 时加载；失败会自动降级 use_bcsr_routes=false。
    void initBcsrReachabilityIfEnabled();

    // NIC 完成 init 后置为 true；若存在 pending 注入，将在后续 tick 中执行。
    void setInjectionReady(bool ready) { injection_ready_ = ready; }

    // 由 MultiCorePE 每拍调用：处理 pending 注入与固定周期注入。
    void tick(uint64_t current_cycle, uint64_t now_ns);

    // 由 MultiCorePE 的阶段事件转发：BeginGather（仅当 period_cycles==0 时有效）
    void onBeginGather(uint32_t seq, uint64_t ts_ns, int core_id);

    // 由 MultiCorePE 的全局 Step barrier 转发：START_STEP(seq)
    // 语义：在 GLOBAL_STEP_SYNC_ENABLE=1 下作为“每 step 一次”的首选触发点；
    // 仅当 period_cycles==0 时生效（固定周期注入仍由 tick() 驱动）。
    void onGlobalStepStart(uint32_t seq, uint64_t ts_ns);

    // 由 MultiCorePE 的阶段事件转发：EndScatter（用于 step_reset_mem_each_step）
    void onEndScatter(uint32_t seq);

    bool enabled() const { return cfg_.enable; }
    bool injectedForSeq(uint32_t seq) const;

private:
    int determineTargetUnit_(uint32_t neuron_id) const;
    void injectStepActivations_(uint32_t seq, uint64_t sim_time_ns);

    // BCSR reachability build（委托 synapse/route 实现，Stimulus 不自持解析逻辑）
    bool loadBcsrReachability_();
    void computeRouteRatios_() const;

    Config cfg_{};
    Runtime rt_{};
    Stats st_{};

    bool injection_ready_ = false;
    bool pending_step_inject_ = false;
    uint32_t pending_step_seq_ = 0;
    uint64_t pending_step_ts_ns_ = 0;

    uint64_t next_cycle_ = 0;
    uint32_t fixed_seq_ = 1;
    uint32_t last_injection_seq_ = std::numeric_limits<uint32_t>::max();
    uint32_t last_reset_seq_ = std::numeric_limits<uint32_t>::max();
    uint32_t seq_warn_count_ = 0;

    bool route_diag_done_ = false;
    bool route_ack_logged_ = false;
    bool route_warned_ = false;

    std::unordered_map<uint32_t, std::vector<uint32_t>> step_routes_map_;
    std::vector<uint32_t> pre_with_routes_;
};

}} // namespace SST::SnnDL
