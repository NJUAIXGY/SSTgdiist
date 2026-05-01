#include "SnnPESubComponent.h"
#include "SnnPESubComponent_impl.h"
#include "IPeAggregation.h"
#include "synapse/weights/WeightAccessor.h"
#include "synapse/weights/WeightMemorySubsystem.h"
#include "synapse/weights/SnnBcsrWeightManager.h"

#include <algorithm>
#include <cstdint>
#include <fstream>

using namespace SST::SnnDL;

// ==== Statistics reporter (Phase5.4: moved into Impl) ====
void SnnPESubComponent::Impl::reportMemoryIssue(size_t bytes, bool count_weight_read) const {
    if (!core) return;
    const uint64_t inflight = static_cast<uint64_t>(core->pendingMemSize_()) + 1ULL;
    if (auto* pe = core->parent_pe_cached_) {
        pe->accumulateIssueStats(static_cast<uint64_t>(bytes), inflight);
    }
    if (core->stat_mem_req_size_bytes_) {
        core->stat_mem_req_size_bytes_->addData(static_cast<uint64_t>(bytes));
    }
    if (core->stat_mem_outstanding_at_issue_) {
        core->stat_mem_outstanding_at_issue_->addData(inflight);
    }
    if (core->stat_memory_requests_) core->stat_memory_requests_->addData(1);
    core->count_memory_requests_++;
    if (count_weight_read && core->stat_weight_read_requests_) {
        core->stat_weight_read_requests_->addData(1);
    }
}

void SnnPESubComponent::Impl::reportApplyScatter(uint64_t acc_updates, uint64_t posts_touched,
                                uint64_t spikes_emitted, uint64_t hwm_bytes,
                                uint64_t spill_records, uint64_t spilled_bytes) const {
    if (!core) return;
    if (auto* pe = core->parent_pe_cached_) {
        pe->accumulateApplyScatterStats(acc_updates, posts_touched, spikes_emitted,
                                        hwm_bytes, spill_records, spilled_bytes);
    }
}

void SnnPESubComponent::Impl::reportWindowSpikes(uint32_t seq, uint64_t spikes_emitted) const {
    if (!core || spikes_emitted == 0) return;
    if (auto* pe = core->parent_pe_cached_) {
        pe->accumulateWindowSpikes(seq, spikes_emitted);
    }
}

void SnnPESubComponent::Impl::reportCacheAccess(bool hit) const {
    if (!core) return;
    if (hit) {
        if (core->stat_weight_cache_hits_) core->stat_weight_cache_hits_->addData(1);
        core->count_cache_hits_++;
    } else {
        if (core->stat_weight_cache_misses_) core->stat_weight_cache_misses_->addData(1);
        core->count_cache_misses_++;
    }
}

void SnnPESubComponent::Impl::updatePendingPeak(uint32_t outstanding) const {
    if (!core) return;
    if (outstanding > core->pending_reqs_peak_) {
        core->pending_reqs_peak_ = outstanding;
        if (core->stat_pending_reqs_peak_) core->stat_pending_reqs_peak_->addData(outstanding);
    }
}

// ==== Window-read issue helpers (control-plane) ====
bool SnnPESubComponent::canIssueMoreReads_() const {
    if (windowStateCanIssue_()) return true;
    if (window_read_debug_ && output_ && output_->getVerboseLevel() >= 2) {
        output_->verbose(CALL_INFO, 2, 0,
            "[diag-edge-loop] core=%d budget/ostd stop issued=%u outstanding=%u budget=%u limit=%u\n",
            core_id_, windowStateIssued_(), windowStateOutstanding_(), window_read_budget_, max_outstanding_requests_);
    }
    return false;
}

void SnnPESubComponent::issueFromEdges_() {
    if (!(apply_acc_enable_ && gas_window_mode_)) return;
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->issueFromEdges();
        return;
    }
}

void SnnPESubComponent::issueFromSets_(
    const std::vector<uint32_t>* posts_to_use,
    const std::unordered_set<uint32_t>* pres_to_use) {
    if (!posts_to_use || !pres_to_use) return;
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->issueFromSets(posts_to_use, pres_to_use);
    }
}

void SnnPESubComponent::issueFallbackReadsIfNeeded_(bool strict_gas_active) {
    if (!window_read_enable_ || !enable_weight_fetch_ || !ensureMemoryReady_()) return;
    if (!weight_mem_subsystem_) return;
    bool need_sets = false;
    if (strict_gas_active) {
        need_sets = weight_mem_subsystem_->edgesPrevEmpty();
    } else {
        need_sets = true;
    }
    if (!need_sets) return;

    bool have_posts_prev = weight_mem_subsystem_->postsPrevSize() > 0;
    bool have_pres_prev  = weight_mem_subsystem_->presPrevSize() > 0;
    bool have_posts_curr = weight_mem_subsystem_->postsCurrSize() > 0;
    bool have_pres_curr  = weight_mem_subsystem_->presCurrSize() > 0;

    bool use_fallback = (!have_posts_prev || !have_pres_prev) && (have_posts_curr && have_pres_curr);
    if (window_read_debug_ && output_ && output_->getVerboseLevel() >= 2) {
        output_->verbose(CALL_INFO, 2, 0,
            "[diag-window-read] BeginApply: core=%u window=%u prev(posts=%u pre=%u) curr(posts=%u pre=%u) budget=%u max_out=%u fallback=%d\n",
            core_id_,
            curr_stage_seq_,
            static_cast<uint32_t>(weight_mem_subsystem_->postsPrevSize()),
            static_cast<uint32_t>(weight_mem_subsystem_->presPrevSize()),
            static_cast<uint32_t>(weight_mem_subsystem_->postsCurrSize()),
            static_cast<uint32_t>(weight_mem_subsystem_->presCurrSize()),
            window_read_budget_,
            max_outstanding_requests_,
            use_fallback ? 1 : 0);
    }

    if ((!have_posts_prev && !have_posts_curr) || (!have_pres_prev && !have_pres_curr)) {
        if (window_read_debug_ && output_ && output_->getVerboseLevel() >= 2) {
            output_->verbose(CALL_INFO, 2, 0,
                "[diag-window-read] BeginApply: core=%u window=%u skip read (both windows empty)\n",
                core_id_, curr_stage_seq_);
        }
        return;
    }

    const std::vector<uint32_t>* posts = use_fallback ? &weight_mem_subsystem_->postsCurr()
                                                      : &weight_mem_subsystem_->postsPrev();
    const std::unordered_set<uint32_t>* pres = use_fallback ? &weight_mem_subsystem_->presCurr()
                                                            : &weight_mem_subsystem_->presPrev();
    if (use_fallback && window_read_debug_ && output_ && output_->getVerboseLevel() >= 2) {
        output_->verbose(CALL_INFO, 2, 0,
            "[diag-window-read] BeginApply: core=%u window=%u FALLBACK to current window (prev empty, curr has data)\n",
            core_id_, curr_stage_seq_);
    }
    windowStateBegin_();
    issueFromSets_(posts, pres);
}

void SnnPESubComponent::issueFromSetsBcsr_(
    const std::vector<uint32_t>* posts_to_use,
    const std::unordered_set<uint32_t>* pres_to_use) {
    if (!posts_to_use || !pres_to_use) return;
    if (weight_mem_subsystem_) {
        weight_mem_subsystem_->issueFromSetsBcsr(posts_to_use, pres_to_use);
    }
}
