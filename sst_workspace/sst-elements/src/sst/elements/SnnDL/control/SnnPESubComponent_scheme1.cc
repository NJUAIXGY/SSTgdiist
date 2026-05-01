// -*- c++ -*-
//
// Copyright 2025 SST Contributors
//
// SnnPESubComponent_scheme1.cc: scheme1 顺序执行路径拆分
//

#include <sst/core/sst_config.h>

#include "SnnPESubComponent.h"
#include "events/SpikeEvent.h"

#include <algorithm>

using namespace SST;
using namespace SST::SnnDL;

void SnnPESubComponent::scheme1Reset_() {
    // 进入一个新的 superstep（基线方案1：每个superstep仅处理一个slice/块）
    scheme1_stage_ = Scheme1Stage::Gather;
    scheme1_stage_counter_ = 0;
    if (scheme1_first_superstep_) {
        scheme1_current_slice_ = 0;
        scheme1_first_superstep_ = false;
    }
    scheme1_prefetch_issued_ = false;
    scheme1_pending_prefetch_ = 0;
    if (!scheme1_queues_inited_) {
        scheme1_slice_queues_.assign(std::max<uint32_t>(1, scheme1_slices_), {});
        scheme1_queues_inited_ = true;
    }
}

bool SnnPESubComponent::scheme1Tick_() {
    // 初始进入 Gather
    if (scheme1_stage_ == Scheme1Stage::Idle) {
        scheme1Reset_();
    }

    // Gather：收集本 superstep 的所有脉冲（仅缓存，不处理）
    if (scheme1_stage_ == Scheme1Stage::Gather) {
        while (!incoming_spikes_.empty()) {
            auto* sp = incoming_spikes_.front(); incoming_spikes_.pop();
            uint32_t pre_g = sp->getSourceNeuron();
            uint32_t slice = scheme1SliceFromPreGlobal_(pre_g);
            if (slice >= scheme1_slice_queues_.size()) slice = (uint32_t)scheme1_slice_queues_.size() - 1;
            scheme1_slice_queues_[slice].push_back(sp);
        }
        scheme1_stage_counter_++;
        if (scheme1_stage_counter_ >= scheme1_gather_cycles_cfg_) {
            scheme1_stage_ = Scheme1Stage::Apply;
            scheme1_stage_counter_ = 0;
            scheme1_current_slice_ = 0;
            scheme1_prefetch_issued_ = false;
            scheme1_pending_prefetch_ = 0;
        }
        // Gather 阶段暂不进行膜电位演化/发放，返回即可
        return true;
    }

    // Apply：仅处理当前slice（基线方案1：每个superstep只处理一个slice）
    if (scheme1_stage_ == Scheme1Stage::Apply) {
        // 发起预取（按行扫描该 slice 的列区间：基线方案，不做按需优化）
        if (!scheme1_prefetch_issued_) {
            scheme1PrefetchSlice_(scheme1_current_slice_);
            scheme1_prefetch_issued_ = true;
        }
        // 等待预取返回
        if (scheme1_pending_prefetch_ > 0) {
            return true; // 等下一批响应
        }
        // 处理该 slice 的所有事件（其他slice队列保留到后续superstep）
        auto& q = scheme1_slice_queues_[scheme1_current_slice_];
        while (!q.empty()) {
            auto* sp = q.front(); q.pop_front();
            processLocalSpike(sp);
            delete sp;
        }
        // 当前slice处理完毕，清空其队列
        q.clear();
        // slice 间隔
        scheme1_stage_counter_++;
        if (scheme1_stage_counter_ < scheme1_slice_gap_cycles_) return true;
        // 本superstep结束，进入Scatter
        scheme1_stage_counter_ = 0;
        scheme1_prefetch_issued_ = false;
        scheme1_stage_ = Scheme1Stage::Scatter;
        return true;
    }

    // Scatter：统一触发膜电位发放（可配置持续若干周期）
    if (scheme1_stage_ == Scheme1Stage::Scatter) {
        // 更新膜电位并尝试触发发放（compute core 内部完成）
        drainCoreOutputsAndRoute_(static_cast<uint64_t>(total_cycles_));
        scheme1_stage_counter_++;
        if (scheme1_stage_counter_ >= scheme1_scatter_cycles_) {
            // 轮换到下一个slice（块），进入下一superstep的Gather阶段
            scheme1_current_slice_ = (scheme1_current_slice_ + 1) % std::max<uint32_t>(1, scheme1_slices_);
            scheme1_stage_ = Scheme1Stage::Idle; // 下一tick会调用 scheme1Reset_() 进入下个superstep
        }
        return true;
    }

    return true; // 默认不落入旧路径
}
