#include "SnnPESubComponent.h"
#include "api/ISnnSpikeCommWorkload.h"
#include "synapse/gas/AccumulatorOps.h"
#include <algorithm>
#include <cinttypes>
#include <cstdint>
#include <cmath>

using namespace SST::SnnDL;

uint64_t SnnPESubComponent::applyAccumulatedWindowAndScatter_() {
    uint64_t spikes_emitted = 0;
    auto addScatterStat = [&](uint64_t delta){
        if (delta == 0) return;
        if (stat_gas_scatter_spikes_emitted_total_) stat_gas_scatter_spikes_emitted_total_->addData(delta);
    };

    std::vector<std::pair<uint32_t, float>> pairs;
    if (acc_ops_) {
        acc_ops_->collectSortedPairs(pairs);
    }

    // 诊断：仅在目标核 window_read_debug=1 且 verbose>=2 时输出，避免全网日志爆炸/性能损耗
    if (output_ && output_->getVerboseLevel() >= 2 && window_read_debug_ &&
        scatter_diag_limit_ > 0 && scatter_diag_count_ < scatter_diag_limit_) {
        const uint32_t issued = windowStateIssued_();
        const uint32_t ostd = windowStateOutstanding_();
        double dv_sum = 0.0;
        double dv_abs_sum = 0.0;
        uint32_t dv_nonzero = 0;
        float dv_max = 0.0f;
        if (!pairs.empty()) {
            for (const auto& pr : pairs) {
                const float dv = pr.second;
                dv_sum += static_cast<double>(dv);
                dv_abs_sum += std::fabs(static_cast<double>(dv));
                if (dv != 0.0f) {
                    dv_nonzero++;
                    if (std::fabs(dv) > std::fabs(dv_max)) dv_max = dv;
                }
            }
            output_->verbose(CALL_INFO, 2, 0,
                "[diag-scatter] core=%d seq=%u pairs=%zu dv_sum=%.6f dv_abs_sum=%.6f dv_nonzero=%u dv_max=%.6f acc_updates=%" PRIu64 " posts_touched=%" PRIu64 " WMS(issued=%u ostd=%u) first(post=%u,dv=%.6f) last(post=%u,dv=%.6f)\n",
                core_id_, curr_stage_seq_,
                pairs.size(), dv_sum, dv_abs_sum, dv_nonzero, (double)dv_max,
                (uint64_t)acc_updates_count_, (uint64_t)acc_posts_touched_count_,
                issued, ostd,
                pairs.front().first, pairs.front().second,
                pairs.back().first, pairs.back().second);
        } else {
            output_->verbose(CALL_INFO, 2, 0,
                "[diag-scatter] core=%d seq=%u pairs=0 acc_updates=%" PRIu64 " posts_touched=%" PRIu64 " WMS(issued=%u ostd=%u)\n",
                core_id_, curr_stage_seq_,
                (uint64_t)acc_updates_count_, (uint64_t)acc_posts_touched_count_,
                issued, ostd);
        }
        ++scatter_diag_count_;
    }

    if (!compute_core_) {
        // 理论上不会发生（构造期已配置 DefaultSnnComputeCore），但保持健壮性。
        if (acc_ops_) acc_ops_->reset();
        spikes_emitted_window_ = 0;
        if (acc_ops_ && acc_ops_->denseEnabled()) verifyDenseAccumulator_(curr_stage_seq_);
        return 0;
    }

    for (const auto& pr : pairs) {
        uint32_t post = pr.first;
        float dv = pr.second;
        if (dv == 0.0f) continue;
        applySynapticDelta_(post, dv);
    }
    // 由 compute core 在统一收敛点处理动力学+发放
    compute_core_->endCycle(static_cast<uint64_t>(total_cycles_));
    std::vector<FireEvent> fired;
    compute_core_->drainOutputs(fired, true);
    if (!fired.empty()) {
        std::vector<uint32_t> neuron_indices;
        neuron_indices.reserve(fired.size());
        for (const auto& ev : fired) neuron_indices.push_back(ev.neuron_idx);

        // 统计口径保留在 CoreShell；发送闭环由 workload=snn 负责。
        legacySnnOnNeuronFires(neuron_indices, static_cast<uint64_t>(total_cycles_));
        if (snn_comm_workload_) {
            (void)snn_comm_workload_->emitNeuronFireBatch(neuron_indices, static_cast<uint64_t>(total_cycles_));
        }
        spikes_emitted += neuron_indices.size();
    }

    if (acc_ops_) acc_ops_->reset();
    spikes_emitted_window_ = spikes_emitted;
    if (acc_ops_ && acc_ops_->denseEnabled()) verifyDenseAccumulator_(curr_stage_seq_);
    addScatterStat(spikes_emitted);
    return spikes_emitted;
}
