// -*- c++ -*-
//
// StageEventHub: GAS阶段事件调度与统计汇报助手
//
// ⚠️ Legacy reference only (Phase5.2-A1):
// 已被吸收进 `control/SnnPESubComponent_impl.h` 的 `SnnPESubComponent::Impl`。
// 本文件仅为历史对照保留，不参与主链路构建。

#include "StageEventHub.h"
#include "SnnPESubComponent.h"
#include "synapse/gas/GasPhaseController.h"
#include <algorithm>

namespace SST { namespace SnnDL {

void StageEventHub::markBeginGather(uint32_t seq) {
    if (!core) return;
    if (core->gas_ctrl_) core->gas_ctrl_->onBeginGather(seq);
    if (core->use_bcsr_) {
        core->logBcsrWindowStats_("prev");
        core->resetBcsrWindowCounters_();
    }
    uint64_t now = core->getCurrentSimTimeNano();
    core->appendStageEventRow_("BeginGather", now, 0);
    t_begin_gather = now;
    have_begin_gather = true;
    have_begin_apply = false;
    have_begin_scatter = false;
    core->window_spikes_all_ = 0;
}

void StageEventHub::markBeginApply(uint32_t seq) {
    if (!core) return;
    if (core->gas_ctrl_) core->gas_ctrl_->onBeginApply(seq);
    uint64_t now = core->getCurrentSimTimeNano();
    core->appendStageEventRow_("BeginApply", now, 0);
    t_begin_apply = now;
    have_begin_apply = true;
}

void StageEventHub::markBeginScatter(uint32_t seq) {
    if (!core) return;
    if (core->gas_ctrl_) core->gas_ctrl_->onBeginScatter(seq);
    uint64_t now = core->getCurrentSimTimeNano();
    core->appendStageEventRow_("BeginScatter", now, 0);
    t_begin_scatter = now;
    have_begin_scatter = true;
}

void StageEventHub::markEndScatter(uint32_t seq, uint64_t spikes_emitted) {
    if (!core) return;
    if (core->gas_ctrl_) core->gas_ctrl_->onEndScatter(seq, spikes_emitted);
    uint64_t now = core->getCurrentSimTimeNano();
    core->appendStageEventRow_("EndScatter", now, spikes_emitted);
    core->stats_reporter_.reportWindowSpikes(static_cast<uint32_t>(seq), spikes_emitted);
    core->spikes_emitted_window_ = 0;
    core->window_spikes_all_ = 0;
    if (core->stat_gas_superstep_total_cycles_) {
        if (have_begin_gather) {
            uint64_t total = (now >= t_begin_gather) ? (now - t_begin_gather) : 0ULL;
            core->stat_gas_superstep_total_cycles_->addData(total);
        }
        if (have_begin_gather && have_begin_apply && core->stat_gas_superstep_gather_cycles_) {
            uint64_t g = (t_begin_apply >= t_begin_gather) ? (t_begin_apply - t_begin_gather) : 0ULL;
            core->stat_gas_superstep_gather_cycles_->addData(g);
        }
        if (have_begin_apply && core->stat_gas_superstep_apply_cycles_) {
            uint64_t a = (t_begin_scatter >= t_begin_apply) ? (t_begin_scatter - t_begin_apply) : 0ULL;
            core->stat_gas_superstep_apply_cycles_->addData(a);
        }
        if (have_begin_scatter && core->stat_gas_superstep_scatter_cycles_) {
            uint64_t s = (now >= t_begin_scatter) ? (now - t_begin_scatter) : 0ULL;
            core->stat_gas_superstep_scatter_cycles_->addData(s);
        }
    }
    have_begin_gather = have_begin_apply = have_begin_scatter = false;
}

}} // namespace SST::SnnDL
