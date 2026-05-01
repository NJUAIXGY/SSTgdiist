#pragma once

#include <algorithm>
#include <cstdint>

namespace SST {
namespace SnnDL {

struct ExperimentalNocRowidxPeStats {
    uint64_t prefetch_rows_total = 0;
    uint64_t prefetch_bytes_total = 0;
    uint64_t prefetch_complete_inflight_miss_total = 0;
    uint64_t prefetch_complete_zero_waiters_total = 0;
    uint64_t prefetch_complete_waiters_total = 0;
    uint64_t prefetch_rows_deferred_total = 0;
    uint64_t prefetch_rows_failed_total = 0;
    uint64_t cache_hits_total = 0;
    uint64_t cache_misses_total = 0;
    uint64_t cache_fills_total = 0;
    uint64_t cache_full_drop_total = 0;
    uint64_t cache_entries_final = 0;
    uint64_t bulk_fill_total = 0;
    uint64_t bulk_rows_cached_total = 0;
    uint64_t bulk_waiters_resolved_total = 0;
    uint64_t touch_rows_total = 0;
    uint64_t touch_events_total = 0;
    uint64_t rows_filtered_cold_total = 0;
    uint64_t budget_ticks_total = 0;
    uint64_t budget_effective_total = 0;
    uint64_t budget_adapt_ticks_total = 0;
    uint64_t ready_transition_apply_promote_cached_total = 0;
    uint64_t ready_signal_rowindex_response_total = 0;
    uint64_t ready_transition_rowindex_response_total = 0;
    uint64_t ready_signal_prefetch_response_total = 0;
    uint64_t ready_transition_prefetch_response_total = 0;
    uint64_t ready_signal_rowindex_response_inflight_waiters_total = 0;
    uint64_t ready_transition_rowindex_response_inflight_waiters_total = 0;
    uint64_t ready_signal_rowindex_response_inflight_zero_waiters_total = 0;
    uint64_t ready_transition_rowindex_response_inflight_zero_waiters_total = 0;
    uint64_t ready_signal_rowindex_response_noninflight_prefetch_only_total = 0;
    uint64_t ready_transition_rowindex_response_noninflight_prefetch_only_total = 0;
    uint64_t ready_signal_prefetch_response_inflight_waiters_total = 0;
    uint64_t ready_transition_prefetch_response_inflight_waiters_total = 0;
    uint64_t ready_signal_prefetch_response_inflight_zero_waiters_total = 0;
    uint64_t ready_transition_prefetch_response_inflight_zero_waiters_total = 0;
    uint64_t ready_signal_prefetch_response_noninflight_prefetch_only_total = 0;
    uint64_t ready_transition_prefetch_response_noninflight_prefetch_only_total = 0;
    uint64_t detached_demand_join_total = 0;
    uint64_t detached_demand_waiters_resolved_total = 0;
    uint64_t detached_demand_fallback_zero_total = 0;
    uint64_t detached_demand_ready_signal_total = 0;
    uint64_t detached_demand_ready_transition_total = 0;
    uint64_t ready_bypass_experimental_cache_hit_total = 0;
    uint64_t ready_bypass_rowindex_get_hit_total = 0;
    uint64_t close_attempt_total = 0;
    uint64_t close_attempt_active_owner_total = 0;
    uint64_t close_attempt_already_pending_total = 0;
    uint64_t close_attempt_not_active_total = 0;
    uint64_t close_attempt_not_owner_total = 0;

    void accumulateCore(uint64_t touch_events_total_core,
                        uint64_t touch_rows_total_core,
                        uint64_t rows_filtered_cold_total_core,
                        uint64_t prefetch_rows_total_core,
                        uint64_t prefetch_complete_inflight_miss_total_core,
                        uint64_t prefetch_complete_zero_waiters_total_core,
                        uint64_t prefetch_complete_waiters_total_core,
                        uint64_t prefetch_rows_deferred_total_core,
                        uint64_t prefetch_rows_failed_total_core,
                        uint64_t prefetch_bytes_total_core,
                        uint64_t budget_ticks_total_core,
                        uint64_t budget_effective_total_core,
                        uint64_t budget_adapt_ticks_total_core,
                        uint64_t cache_hits_total_core,
                        uint64_t cache_misses_total_core,
                        uint64_t cache_fills_total_core,
                        uint64_t cache_full_drop_total_core,
                        uint64_t cache_entries_final_core,
                        uint64_t bulk_fill_total_core,
                        uint64_t bulk_rows_cached_total_core,
                        uint64_t bulk_waiters_resolved_total_core,
                        uint64_t ready_transition_apply_promote_cached_total_core,
                        uint64_t ready_signal_rowindex_response_total_core,
                        uint64_t ready_transition_rowindex_response_total_core,
                        uint64_t ready_signal_prefetch_response_total_core,
                        uint64_t ready_transition_prefetch_response_total_core,
                        uint64_t ready_signal_rowindex_response_inflight_waiters_total_core,
                        uint64_t ready_transition_rowindex_response_inflight_waiters_total_core,
                        uint64_t ready_signal_rowindex_response_inflight_zero_waiters_total_core,
                        uint64_t ready_transition_rowindex_response_inflight_zero_waiters_total_core,
                        uint64_t ready_signal_rowindex_response_noninflight_prefetch_only_total_core,
                        uint64_t ready_transition_rowindex_response_noninflight_prefetch_only_total_core,
                        uint64_t ready_signal_prefetch_response_inflight_waiters_total_core,
                        uint64_t ready_transition_prefetch_response_inflight_waiters_total_core,
                        uint64_t ready_signal_prefetch_response_inflight_zero_waiters_total_core,
                        uint64_t ready_transition_prefetch_response_inflight_zero_waiters_total_core,
                        uint64_t ready_signal_prefetch_response_noninflight_prefetch_only_total_core,
                        uint64_t ready_transition_prefetch_response_noninflight_prefetch_only_total_core,
                        uint64_t detached_demand_join_total_core,
                        uint64_t detached_demand_waiters_resolved_total_core,
                        uint64_t detached_demand_fallback_zero_total_core,
                        uint64_t detached_demand_ready_signal_total_core,
                        uint64_t detached_demand_ready_transition_total_core,
                        uint64_t ready_bypass_experimental_cache_hit_total_core,
                        uint64_t ready_bypass_rowindex_get_hit_total_core,
                        uint64_t close_attempt_total_core,
                        uint64_t close_attempt_active_owner_total_core,
                        uint64_t close_attempt_already_pending_total_core,
                        uint64_t close_attempt_not_active_total_core,
                        uint64_t close_attempt_not_owner_total_core) {
        touch_events_total += touch_events_total_core;
        touch_rows_total += touch_rows_total_core;
        rows_filtered_cold_total += rows_filtered_cold_total_core;
        prefetch_rows_total += prefetch_rows_total_core;
        prefetch_complete_inflight_miss_total +=
            prefetch_complete_inflight_miss_total_core;
        prefetch_complete_zero_waiters_total +=
            prefetch_complete_zero_waiters_total_core;
        prefetch_complete_waiters_total += prefetch_complete_waiters_total_core;
        prefetch_rows_deferred_total += prefetch_rows_deferred_total_core;
        prefetch_rows_failed_total += prefetch_rows_failed_total_core;
        prefetch_bytes_total += prefetch_bytes_total_core;
        budget_ticks_total += budget_ticks_total_core;
        budget_effective_total += budget_effective_total_core;
        budget_adapt_ticks_total += budget_adapt_ticks_total_core;
        cache_hits_total += cache_hits_total_core;
        cache_misses_total += cache_misses_total_core;
        cache_fills_total += cache_fills_total_core;
        cache_full_drop_total += cache_full_drop_total_core;
        cache_entries_final += cache_entries_final_core;
        bulk_fill_total += bulk_fill_total_core;
        bulk_rows_cached_total += bulk_rows_cached_total_core;
        bulk_waiters_resolved_total += bulk_waiters_resolved_total_core;
        ready_transition_apply_promote_cached_total +=
            ready_transition_apply_promote_cached_total_core;
        ready_signal_rowindex_response_total +=
            ready_signal_rowindex_response_total_core;
        ready_transition_rowindex_response_total +=
            ready_transition_rowindex_response_total_core;
        ready_signal_prefetch_response_total += ready_signal_prefetch_response_total_core;
        ready_transition_prefetch_response_total +=
            ready_transition_prefetch_response_total_core;
        ready_signal_rowindex_response_inflight_waiters_total +=
            ready_signal_rowindex_response_inflight_waiters_total_core;
        ready_transition_rowindex_response_inflight_waiters_total +=
            ready_transition_rowindex_response_inflight_waiters_total_core;
        ready_signal_rowindex_response_inflight_zero_waiters_total +=
            ready_signal_rowindex_response_inflight_zero_waiters_total_core;
        ready_transition_rowindex_response_inflight_zero_waiters_total +=
            ready_transition_rowindex_response_inflight_zero_waiters_total_core;
        ready_signal_rowindex_response_noninflight_prefetch_only_total +=
            ready_signal_rowindex_response_noninflight_prefetch_only_total_core;
        ready_transition_rowindex_response_noninflight_prefetch_only_total +=
            ready_transition_rowindex_response_noninflight_prefetch_only_total_core;
        ready_signal_prefetch_response_inflight_waiters_total +=
            ready_signal_prefetch_response_inflight_waiters_total_core;
        ready_transition_prefetch_response_inflight_waiters_total +=
            ready_transition_prefetch_response_inflight_waiters_total_core;
        ready_signal_prefetch_response_inflight_zero_waiters_total +=
            ready_signal_prefetch_response_inflight_zero_waiters_total_core;
        ready_transition_prefetch_response_inflight_zero_waiters_total +=
            ready_transition_prefetch_response_inflight_zero_waiters_total_core;
        ready_signal_prefetch_response_noninflight_prefetch_only_total +=
            ready_signal_prefetch_response_noninflight_prefetch_only_total_core;
        ready_transition_prefetch_response_noninflight_prefetch_only_total +=
            ready_transition_prefetch_response_noninflight_prefetch_only_total_core;
        detached_demand_join_total += detached_demand_join_total_core;
        detached_demand_waiters_resolved_total += detached_demand_waiters_resolved_total_core;
        detached_demand_fallback_zero_total += detached_demand_fallback_zero_total_core;
        detached_demand_ready_signal_total += detached_demand_ready_signal_total_core;
        detached_demand_ready_transition_total += detached_demand_ready_transition_total_core;
        ready_bypass_experimental_cache_hit_total +=
            ready_bypass_experimental_cache_hit_total_core;
        ready_bypass_rowindex_get_hit_total += ready_bypass_rowindex_get_hit_total_core;
        close_attempt_total += close_attempt_total_core;
        close_attempt_active_owner_total += close_attempt_active_owner_total_core;
        close_attempt_already_pending_total += close_attempt_already_pending_total_core;
        close_attempt_not_active_total += close_attempt_not_active_total_core;
        close_attempt_not_owner_total += close_attempt_not_owner_total_core;
    }
};

struct ExperimentalIdx2IngressPeStats {
    uint64_t guard_config_enable = 0;
    uint64_t guard_mode_ok = 0;
    uint64_t guard_mem_bound = 0;
    uint64_t touch_gate_feature_disabled_total = 0;
    uint64_t touch_gate_non_idx2_mode_total = 0;
    uint64_t touch_gate_mem_unbound_total = 0;
    uint64_t touch_gate_post_oob_total = 0;
    uint64_t touch_gate_non_gather_window_total = 0;
    uint64_t touch_gate_entered_total = 0;
    uint64_t touch_events_total = 0;
    uint64_t lookup_miss_total = 0;
    uint64_t enqueued_total = 0;
    uint64_t dedup_pending_total = 0;
    uint64_t dedup_inflight_total = 0;
    uint64_t dedup_cache_total = 0;
    uint64_t prefetch_issued_total = 0;
    uint64_t prefetch_bytes_total = 0;
    uint64_t prefetch_deferred_total = 0;
    uint64_t prefetch_blocked_by_cap_total = 0;
    uint64_t prefetch_failed_total = 0;
    uint64_t prefetch_resp_ok_total = 0;
    uint64_t prefetch_resp_short_total = 0;
    uint64_t prefetch_resp_drop_tail_total = 0;
    uint64_t prefetch_complete_inflight_miss_total = 0;
    uint64_t prefetch_complete_zero_waiters_total = 0;
    uint64_t prefetch_complete_waiters_total = 0;
    uint64_t owner_useful_total = 0;
    uint64_t owner_dead_total = 0;
    uint64_t owner_join_before_ready_total = 0;
    uint64_t owner_ready_before_demand_total = 0;
    uint64_t demand_hit_total = 0;
    uint64_t demand_join_total = 0;
    uint64_t demand_join_cb_nonnull_total = 0;
    uint64_t demand_join_cb_null_total = 0;
    uint64_t demand_fallback_total = 0;
    uint64_t waiters_served_total = 0;
    uint64_t cache_fill_total = 0;
    uint64_t cache_evict_total = 0;
    uint64_t cache_entries_final = 0;
    uint64_t pending_dropped_on_begin_apply_total = 0;
    uint64_t pending_dropped_on_begin_apply_frontier_total = 0;
    uint64_t frontier_kept_and_later_useful_total = 0;
    uint64_t frontier_kept_but_zero_waiter_total = 0;
    uint64_t frontier_kept_cross_window_stale_total = 0;
    uint64_t budget_ticks_total = 0;
    uint64_t budget_effective_total = 0;
    uint64_t budget_adapt_ticks_total = 0;
    uint64_t inflight_cap_effective_peak = 0;

    void accumulateCore(uint64_t guard_config_enable_core,
                        uint64_t guard_mode_ok_core,
                        uint64_t guard_mem_bound_core,
                        uint64_t touch_gate_feature_disabled_total_core,
                        uint64_t touch_gate_non_idx2_mode_total_core,
                        uint64_t touch_gate_mem_unbound_total_core,
                        uint64_t touch_gate_post_oob_total_core,
                        uint64_t touch_gate_non_gather_window_total_core,
                        uint64_t touch_gate_entered_total_core,
                        uint64_t touch_events_total_core,
                        uint64_t lookup_miss_total_core,
                        uint64_t enqueued_total_core,
                        uint64_t dedup_pending_total_core,
                        uint64_t dedup_inflight_total_core,
                        uint64_t dedup_cache_total_core,
                        uint64_t prefetch_issued_total_core,
                        uint64_t prefetch_bytes_total_core,
                        uint64_t prefetch_deferred_total_core,
                        uint64_t prefetch_blocked_by_cap_total_core,
                        uint64_t prefetch_failed_total_core,
                        uint64_t prefetch_resp_ok_total_core,
                        uint64_t prefetch_resp_short_total_core,
                        uint64_t prefetch_resp_drop_tail_total_core,
                        uint64_t prefetch_complete_inflight_miss_total_core,
                        uint64_t prefetch_complete_zero_waiters_total_core,
                        uint64_t prefetch_complete_waiters_total_core,
                        uint64_t owner_useful_total_core,
                        uint64_t owner_dead_total_core,
                        uint64_t owner_join_before_ready_total_core,
                        uint64_t owner_ready_before_demand_total_core,
                        uint64_t demand_hit_total_core,
                        uint64_t demand_join_total_core,
                        uint64_t demand_join_cb_nonnull_total_core,
                        uint64_t demand_join_cb_null_total_core,
                        uint64_t demand_fallback_total_core,
                        uint64_t waiters_served_total_core,
                        uint64_t cache_fill_total_core,
                        uint64_t cache_evict_total_core,
                        uint64_t cache_entries_final_core,
                        uint64_t pending_dropped_on_begin_apply_total_core,
                        uint64_t pending_dropped_on_begin_apply_frontier_total_core,
                        uint64_t frontier_kept_and_later_useful_total_core,
                        uint64_t frontier_kept_but_zero_waiter_total_core,
                        uint64_t frontier_kept_cross_window_stale_total_core,
                        uint64_t budget_ticks_total_core,
                        uint64_t budget_effective_total_core,
                        uint64_t budget_adapt_ticks_total_core,
                        uint64_t inflight_cap_effective_peak_core) {
        guard_config_enable += guard_config_enable_core;
        guard_mode_ok += guard_mode_ok_core;
        guard_mem_bound += guard_mem_bound_core;
        touch_gate_feature_disabled_total += touch_gate_feature_disabled_total_core;
        touch_gate_non_idx2_mode_total += touch_gate_non_idx2_mode_total_core;
        touch_gate_mem_unbound_total += touch_gate_mem_unbound_total_core;
        touch_gate_post_oob_total += touch_gate_post_oob_total_core;
        touch_gate_non_gather_window_total += touch_gate_non_gather_window_total_core;
        touch_gate_entered_total += touch_gate_entered_total_core;
        touch_events_total += touch_events_total_core;
        lookup_miss_total += lookup_miss_total_core;
        enqueued_total += enqueued_total_core;
        dedup_pending_total += dedup_pending_total_core;
        dedup_inflight_total += dedup_inflight_total_core;
        dedup_cache_total += dedup_cache_total_core;
        prefetch_issued_total += prefetch_issued_total_core;
        prefetch_bytes_total += prefetch_bytes_total_core;
        prefetch_deferred_total += prefetch_deferred_total_core;
        prefetch_blocked_by_cap_total += prefetch_blocked_by_cap_total_core;
        prefetch_failed_total += prefetch_failed_total_core;
        prefetch_resp_ok_total += prefetch_resp_ok_total_core;
        prefetch_resp_short_total += prefetch_resp_short_total_core;
        prefetch_resp_drop_tail_total += prefetch_resp_drop_tail_total_core;
        prefetch_complete_inflight_miss_total += prefetch_complete_inflight_miss_total_core;
        prefetch_complete_zero_waiters_total += prefetch_complete_zero_waiters_total_core;
        prefetch_complete_waiters_total += prefetch_complete_waiters_total_core;
        owner_useful_total += owner_useful_total_core;
        owner_dead_total += owner_dead_total_core;
        owner_join_before_ready_total += owner_join_before_ready_total_core;
        owner_ready_before_demand_total += owner_ready_before_demand_total_core;
        demand_hit_total += demand_hit_total_core;
        demand_join_total += demand_join_total_core;
        demand_join_cb_nonnull_total += demand_join_cb_nonnull_total_core;
        demand_join_cb_null_total += demand_join_cb_null_total_core;
        demand_fallback_total += demand_fallback_total_core;
        waiters_served_total += waiters_served_total_core;
        cache_fill_total += cache_fill_total_core;
        cache_evict_total += cache_evict_total_core;
        cache_entries_final += cache_entries_final_core;
        pending_dropped_on_begin_apply_total += pending_dropped_on_begin_apply_total_core;
        pending_dropped_on_begin_apply_frontier_total +=
            pending_dropped_on_begin_apply_frontier_total_core;
        frontier_kept_and_later_useful_total += frontier_kept_and_later_useful_total_core;
        frontier_kept_but_zero_waiter_total += frontier_kept_but_zero_waiter_total_core;
        frontier_kept_cross_window_stale_total += frontier_kept_cross_window_stale_total_core;
        budget_ticks_total += budget_ticks_total_core;
        budget_effective_total += budget_effective_total_core;
        budget_adapt_ticks_total += budget_adapt_ticks_total_core;
        inflight_cap_effective_peak =
            std::max<uint64_t>(inflight_cap_effective_peak, inflight_cap_effective_peak_core);
    }
};

} // namespace SnnDL
} // namespace SST
