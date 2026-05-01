// -*- c++ -*-
//
// SnnLearningCore: 可替换的学习/梯度累加核心（与动力学/控制层解耦）

#pragma once

#include <cstdint>
#include <cstddef>
#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

#include <sst/core/output.h>
#include <sst/core/params.h>

namespace SST { namespace SnnDL {

// 统一的学习写回回调签名（由控制层提供）
using LearningWritebackFn = std::function<bool(
    const std::unordered_map<uint64_t, float>& grads,
    float learning_rate,
    float weight_decay)>;

struct LearningSynapticEvent {
    uint32_t pre_global = 0;
    uint32_t post_local = 0;
    float v_after = 0.0f; // 触发更新后的膜电位（用于 surrogate grad）
};

class ILearningCore {
public:
    virtual ~ILearningCore() = default;
    virtual void configure(uint32_t core_id,
                           uint32_t node_id,
                           uint32_t num_neurons,
                           uint64_t global_neuron_base,
                           uint32_t weights_cols,
                           bool use_post_row_pre_col,
                           float v_thresh,
                           SST::Output* log,
                           const SST::Params& params,
                           LearningWritebackFn writeback_fn) = 0;
    virtual void onClockTick(uint64_t now_cycle) = 0;
    virtual void onSynapticEvent(const LearningSynapticEvent& ev) = 0;
    virtual void onNeuronFired(uint32_t neuron_idx, uint64_t now_cycle, float v_before) = 0;
    virtual void getStatistics(std::map<std::string, uint64_t>& out) const = 0;
    virtual bool enabled() const = 0;
};

// 默认 superspike 学习核心（复刻旧 SnnPESubComponent 口径）
class DefaultLearningCore final : public ILearningCore {
public:
    void configure(uint32_t core_id,
                   uint32_t node_id,
                   uint32_t num_neurons,
                   uint64_t global_neuron_base,
                   uint32_t weights_cols,
                   bool use_post_row_pre_col,
                   float v_thresh,
                   SST::Output* log,
                   const SST::Params& params,
                   LearningWritebackFn writeback_fn) override;
    void onClockTick(uint64_t now_cycle) override;
    void onSynapticEvent(const LearningSynapticEvent& ev) override;
    void onNeuronFired(uint32_t neuron_idx, uint64_t now_cycle, float v_before) override;
    void getStatistics(std::map<std::string, uint64_t>& out) const override;
    bool enabled() const override { return learning_enabled_; }

private:
    struct SpikeRecord {
        uint32_t neuron_id_global = 0;
        uint64_t timestamp_cycles = 0;
        float v_at_fire = 0.0f;
    };

    void onWindowBoundary_(uint64_t window_idx);
    void loadErrorsForWindow_(uint64_t window_idx);
    float computeSurrogateGrad_(float v_mem) const;
    bool resolveWeightKey_(uint32_t pre_global, uint32_t post_local, uint64_t& key) const;
    std::string replacePlaceholders_(std::string s, uint64_t window_idx) const;

    uint32_t core_id_ = 0;
    uint32_t node_id_ = 0;
    uint32_t num_neurons_ = 0;
    uint64_t global_neuron_base_ = 0;
    uint32_t weights_cols_ = 0;
    bool use_post_row_pre_col_ = false;
    float v_thresh_ = 1.0f;
    SST::Output* output_ = nullptr;
    LearningWritebackFn writeback_fn_;

    bool learning_enabled_ = false;
    uint64_t learn_window_cycles_ = 1000;
    bool record_membrane_ = false;
    bool record_spike_times_ = true;
    std::string surrogate_type_ = "superspike";
    float surrogate_beta_ = 5.0f;
    std::string error_file_template_;
    size_t grad_accum_limit_ = 0;
    bool apply_writeback_ = false;
    uint32_t apply_every_n_windows_ = 1;
    float learning_rate_ = 0.001f;
    float weight_decay_ = 0.0f;

    uint64_t current_window_index_ = 0;
    std::vector<float> error_buffer_;
    std::unordered_map<uint64_t, float> local_grad_;
    std::vector<SpikeRecord> spike_history_;
};

}} // namespace SST::SnnDL

