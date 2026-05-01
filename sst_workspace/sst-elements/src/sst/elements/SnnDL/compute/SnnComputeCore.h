#ifndef SST_ELEMENTS_SNNDL_SNNCOMPUTECORE_H
#define SST_ELEMENTS_SNNDL_SNNCOMPUTECORE_H

#include <cstdint>
#include <cstddef>
#include <functional>
#include <list>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include <sst/core/output.h>
#include <sst/core/params.h>

#include "events/SpikeEvent.h"
#include "SnnWeightReader.h"
#include "SnnCoreEngine.h"
#include "SnnLearningCore.h"
#include "IWeightAwareComputeCore.h"
#include "ISnnComputeCore.h"
#include "services/memory/sram_sim/layout/VirtualSramLayout.h"
#include "services/memory/sram_sim/model/BankedSramModel.h"

namespace SST { namespace SnnDL {

// 默认核心实现：封装现有 SnnPESubComponent 内的计算逻辑
class DefaultSnnComputeCore final : public ISnnComputeCore, public IWeightAwareComputeCore {
public:
    DefaultSnnComputeCore() = default;
    ~DefaultSnnComputeCore() override = default;

    ComputeCoreCapabilities getCapabilities() const override;
    void configure(const ComputeCoreContext& ctx, const SST::Params& params) override;
    void onInit(unsigned int phase) override;
    void onSetup() override;
    void onFinish() override;
    void onClockTick(uint64_t now_cycle) override;
    void onStageBeginGather(uint32_t seq) override;
    void onStageBeginApply(uint32_t seq) override;
    void onStageEndApply(uint32_t seq) override;
    void onStageBeginScatter(uint32_t seq) override;
    void onStageEndScatter(uint32_t seq, uint64_t spikes_emitted_hint) override;
    void onSpikeDelivered(SpikeEvent* spike) override;
    bool hasWork() const override;
    double getUtilization() const override;
    void getStatistics(std::map<std::string, uint64_t>& out) const override;
    void resetMembraneState(float v_rest) override;
    void endCycle(uint64_t now_cycle) override;
    void endCycleCandidates(uint64_t now_cycle, const std::vector<uint32_t>& candidates) override;
    void drainOutputs(std::vector<FireEvent>& out, bool clear = true) override;
    bool shouldAcceptSynapticInput(uint32_t post_local, uint64_t now_cycle) const override;
    void applySynapticDelta(uint32_t post_local, float dv) override;
    void onSynapticEvent(const SynapticEvent& ev) override;
    void clearFiredWindow() override;
    void getFiredEvents(std::vector<FireEvent>& out, bool clear = true) override;
    bool readNeuronState(uint32_t idx, NeuronStateSnapshot& out) const override;
    void writeNeuronState(uint32_t idx, const NeuronStateSnapshot& st) override;
    void onLearningEvent(const LearningEvent& ev) override;
    void updateNeuronStates() override;
    bool fire(uint32_t idx, uint64_t now_cycles, INeuronModel* model,
              float& v_before, float& v_after) override;
    bool wasFiredThisWindow(uint32_t idx) const override;
    void markFiredThisWindow(uint32_t idx) override;
    // IWeightAwareComputeCore (可选扩展接口；默认实现转发到 weight_reader)
    bool requestWeight(uint32_t pre, uint32_t post,
                       const std::function<void(float)>& cb) override;
    bool requestWeightBCSR(uint32_t pre, uint32_t post,
                           const std::function<void(float)>& cb) override;
    bool weightCacheTryGet(uint64_t key, float& out) const override;
    void weightCacheStore(uint64_t key, float v) override;
    bool resolveWeightKey(uint32_t pre_global, uint32_t post_local,
                          uint32_t& req_pre, uint32_t& req_post,
                          uint64_t& cache_key) const override;
private:
    // 注入上下文
    ComputeCoreContext ctx_;
    Output* output_ = nullptr;
    IWeightReader* weight_reader_ = nullptr;

    // 动力学核心
    SnnCoreEngine core_engine_;
    std::vector<SnnCoreNeuronState> neuron_states_;
    alignas(64) std::vector<float> soa_v_mem_;
    alignas(64) std::vector<uint32_t> soa_refrac_;
    alignas(64) std::vector<uint64_t> soa_last_spike_;
    bool use_soa_state_ = false;
    bool use_aosoa_state_ = false;
    uint32_t aosoa_block_rows_ = 16;
    bool state_sram_enable_ = false;
    uint64_t state_sram_current_cycle_ = 0;
    uint64_t state_sram_stall_budget_ = 0;
    uint64_t state_sram_stall_cycles_total_ = 0;
    VirtualSramLayout state_sram_layout_{};
    BankedSramModel state_sram_model_{};

    // 阈值/电生理参数
    float v_thresh_ = 1.0f;
    float v_reset_ = 0.0f;
    float v_rest_ = 0.0f;
    float tau_mem_ = 20.0f;
    uint32_t t_ref_ = 2;
    float dt_ms_ = 1.0f;
    std::unique_ptr<INeuronModel> neuron_model_;
    // 累加/窗口
    bool apply_acc_enable_ = false;
    bool gas_window_mode_ = false;
    uint64_t memory_warmup_cycles_ = 1000;
    uint64_t loader_barrier_cycles_ = 0;
    // window-read 相关集合由控制层维护；compute core 不再持有
    bool window_read_debug_ = false;
    uint32_t window_read_budget_ = 1024;
    uint32_t max_outstanding_requests_ = 16;
    uint32_t line_size_bytes_ = 64;
    uint32_t weights_cols_ = 0;
    bool use_post_row_pre_col_ = false;
    uint32_t num_neurons_ = 0;
    uint64_t global_neuron_base_ = 0;
    uint32_t neurons_per_pe_cfg_ = 0;
    // 验证/诊断
    bool verify_weights_ = false;
    bool verify_against_file_ = false;
    bool verify_cluster_enable_ = false;
    bool verify_log_each_sample_ = false;
    float expected_weight_value_ = 0.0f;
    float verify_epsilon_ = 1e-4f;
    uint32_t weight_verify_samples_ = 16;
    float init_default_weight_ = 0.5f;
    bool readresp_zero_fallback_ = false;
    std::string verify_file_template_;
    std::vector<float> verify_file_buf_;
    bool verify_file_loaded_ = false;
    bool verify_started_ = false;
    uint32_t verify_requested_ = 0;
    uint32_t verify_completed_ = 0;
    double verify_sum_ = 0.0;
    uint64_t verify_mismatch_count_ = 0;

    // 可替换学习核心（Phase2）
    std::unique_ptr<ILearningCore> learning_core_;

    // GAS 阶段状态/统计
    enum class GasStage { Idle=0, Gather=1, Apply=2, Scatter=3 };
    GasStage gas_stage_ = GasStage::Idle;
    uint32_t curr_stage_seq_ = 0;
    std::vector<uint8_t> fired_this_window_;
    std::vector<FireEvent> fired_events_window_;
    uint64_t window_spikes_all_ = 0;
    uint64_t spikes_generated_base_ = 0;
    uint64_t acc_updates_count_ = 0;
    uint64_t acc_posts_touched_count_ = 0;
    uint64_t acc_spill_records_count_ = 0;
    uint64_t acc_spilled_bytes_sum_ = 0;
    uint64_t acc_hwm_bytes_max_ = 0;
    // 统计：放在 compute core，控制层可直接查询
    uint64_t spikes_generated_count_ = 0;
    uint64_t neurons_fired_count_ = 0;
    uint64_t cycles_update_neuron_count_ = 0;
    uint64_t synaptic_accesses_count_ = 0;
    uint64_t total_cycles_ = 0;
    uint64_t active_cycles_ = 0;
    bool fire_gate_active_ = false; // 控制层可同步镜像（是否需要窗口内门控）
    uint64_t weight_cache_hits_ = 0;
    uint64_t weight_cache_misses_ = 0;
    uint64_t pending_reqs_peak_ = 0;
    bool diag_fire_log_ = false;

    // Window-scatter ΔV staging:
    // 在严格 GAS window 模式下，控制层会在 Scatter 边界将累计 ΔV 批量下发。
    // 为保持与历史“先泄漏/不应期推进，再整合突触输入，再判定发放”的时序一致，
    // applySynapticDelta() 先暂存 ΔV；endCycle() 内先 updateNeuronStates()，再一次性应用并 fire()。
    std::vector<float> pending_dv_;
    std::vector<uint8_t> pending_dv_touched_;
    std::vector<uint32_t> pending_dv_list_;

    // 辅助方法
    void performWeightVerificationTick_(uint64_t now_cycle);
    void initCoreEngineState_();
    void initVerifyFile_();
    void noteStateSramRead_(uint64_t addr, uint64_t bytes);
    void noteStateSramWrite_(uint64_t addr, uint64_t bytes);
    void applyPendingDeltas_();
    void resetPendingDeltas_();
};

} } // namespace SST::SnnDL

#endif // SST_ELEMENTS_SNNDL_SNNCOMPUTECORE_H
