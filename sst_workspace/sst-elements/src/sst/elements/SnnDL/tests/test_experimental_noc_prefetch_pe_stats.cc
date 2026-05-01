#include <cassert>
#include <cstdint>

#include "components/ExperimentalNocPrefetchPeStats.h"

using SST::SnnDL::ExperimentalIdx2IngressPeStats;
using SST::SnnDL::ExperimentalNocRowidxPeStats;

int main() {
    ExperimentalNocRowidxPeStats rowidx{};
    rowidx.accumulateCore(
        /*touch_events_total_core=*/3u,
        /*touch_rows_total_core=*/2u,
        /*rows_filtered_cold_total_core=*/1u,
        /*prefetch_rows_total_core=*/5u,
        /*prefetch_complete_inflight_miss_total_core=*/6u,
        /*prefetch_complete_zero_waiters_total_core=*/7u,
        /*prefetch_complete_waiters_total_core=*/8u,
        /*prefetch_rows_deferred_total_core=*/1u,
        /*prefetch_rows_failed_total_core=*/0u,
        /*prefetch_bytes_total_core=*/320u,
        /*budget_ticks_total_core=*/4u,
        /*budget_effective_total_core=*/7u,
        /*budget_adapt_ticks_total_core=*/2u,
        /*cache_hits_total_core=*/8u,
        /*cache_misses_total_core=*/6u,
        /*cache_fills_total_core=*/5u,
        /*cache_full_drop_total_core=*/1u,
        /*cache_entries_final_core=*/9u,
        /*bulk_fill_total_core=*/2u,
        /*bulk_rows_cached_total_core=*/11u,
        /*bulk_waiters_resolved_total_core=*/12u,
        /*ready_transition_apply_promote_cached_total_core=*/15u,
        /*ready_signal_rowindex_response_total_core=*/14u,
        /*ready_transition_rowindex_response_total_core=*/13u,
        /*ready_signal_prefetch_response_total_core=*/16u,
        /*ready_transition_prefetch_response_total_core=*/17u,
        /*ready_signal_rowindex_response_inflight_waiters_total_core=*/31u,
        /*ready_transition_rowindex_response_inflight_waiters_total_core=*/32u,
        /*ready_signal_rowindex_response_inflight_zero_waiters_total_core=*/33u,
        /*ready_transition_rowindex_response_inflight_zero_waiters_total_core=*/34u,
        /*ready_signal_rowindex_response_noninflight_prefetch_only_total_core=*/35u,
        /*ready_transition_rowindex_response_noninflight_prefetch_only_total_core=*/36u,
        /*ready_signal_prefetch_response_inflight_waiters_total_core=*/37u,
        /*ready_transition_prefetch_response_inflight_waiters_total_core=*/38u,
        /*ready_signal_prefetch_response_inflight_zero_waiters_total_core=*/39u,
        /*ready_transition_prefetch_response_inflight_zero_waiters_total_core=*/40u,
        /*ready_signal_prefetch_response_noninflight_prefetch_only_total_core=*/41u,
        /*ready_transition_prefetch_response_noninflight_prefetch_only_total_core=*/42u,
        /*ready_bypass_experimental_cache_hit_total_core=*/18u,
        /*ready_bypass_rowindex_get_hit_total_core=*/19u,
        /*close_attempt_total_core=*/20u,
        /*close_attempt_active_owner_total_core=*/21u,
        /*close_attempt_already_pending_total_core=*/22u,
        /*close_attempt_not_active_total_core=*/23u,
        /*close_attempt_not_owner_total_core=*/24u);
    rowidx.accumulateCore(
        1u, 1u, 0u, 2u, 9u, 10u, 11u, 3u, 4u, 128u, 2u, 3u, 1u, 10u, 11u, 12u, 13u, 14u, 3u, 4u,
        5u, 25u, 24u, 23u, 26u, 27u, 43u, 44u, 45u, 46u, 47u, 48u, 49u, 50u,
        51u, 52u, 53u, 54u, 28u, 29u, 30u, 31u, 32u, 33u, 34u);

    assert(rowidx.touch_events_total == 4u);
    assert(rowidx.touch_rows_total == 3u);
    assert(rowidx.rows_filtered_cold_total == 1u);
    assert(rowidx.prefetch_rows_total == 7u);
    assert(rowidx.prefetch_complete_inflight_miss_total == 15u);
    assert(rowidx.prefetch_complete_zero_waiters_total == 17u);
    assert(rowidx.prefetch_complete_waiters_total == 19u);
    assert(rowidx.prefetch_rows_deferred_total == 4u);
    assert(rowidx.prefetch_rows_failed_total == 4u);
    assert(rowidx.prefetch_bytes_total == 448u);
    assert(rowidx.budget_ticks_total == 6u);
    assert(rowidx.budget_effective_total == 10u);
    assert(rowidx.budget_adapt_ticks_total == 3u);
    assert(rowidx.cache_hits_total == 18u);
    assert(rowidx.cache_misses_total == 17u);
    assert(rowidx.cache_fills_total == 17u);
    assert(rowidx.cache_full_drop_total == 14u);
    assert(rowidx.cache_entries_final == 23u);
    assert(rowidx.bulk_fill_total == 5u);
    assert(rowidx.bulk_rows_cached_total == 15u);
    assert(rowidx.bulk_waiters_resolved_total == 17u);
    assert(rowidx.ready_transition_apply_promote_cached_total == 40u);
    assert(rowidx.ready_signal_rowindex_response_total == 38u);
    assert(rowidx.ready_transition_rowindex_response_total == 36u);
    assert(rowidx.ready_signal_prefetch_response_total == 42u);
    assert(rowidx.ready_transition_prefetch_response_total == 44u);
    assert(rowidx.ready_signal_rowindex_response_inflight_waiters_total == 74u);
    assert(rowidx.ready_transition_rowindex_response_inflight_waiters_total == 76u);
    assert(rowidx.ready_signal_rowindex_response_inflight_zero_waiters_total == 78u);
    assert(rowidx.ready_transition_rowindex_response_inflight_zero_waiters_total == 80u);
    assert(rowidx.ready_signal_rowindex_response_noninflight_prefetch_only_total == 82u);
    assert(rowidx.ready_transition_rowindex_response_noninflight_prefetch_only_total == 84u);
    assert(rowidx.ready_signal_prefetch_response_inflight_waiters_total == 86u);
    assert(rowidx.ready_transition_prefetch_response_inflight_waiters_total == 88u);
    assert(rowidx.ready_signal_prefetch_response_inflight_zero_waiters_total == 90u);
    assert(rowidx.ready_transition_prefetch_response_inflight_zero_waiters_total == 92u);
    assert(rowidx.ready_signal_prefetch_response_noninflight_prefetch_only_total == 94u);
    assert(rowidx.ready_transition_prefetch_response_noninflight_prefetch_only_total == 96u);
    assert(rowidx.ready_bypass_experimental_cache_hit_total == 46u);
    assert(rowidx.ready_bypass_rowindex_get_hit_total == 48u);
    assert(rowidx.close_attempt_total == 50u);
    assert(rowidx.close_attempt_active_owner_total == 52u);
    assert(rowidx.close_attempt_already_pending_total == 54u);
    assert(rowidx.close_attempt_not_active_total == 56u);
    assert(rowidx.close_attempt_not_owner_total == 58u);

    ExperimentalIdx2IngressPeStats idx2{};
    idx2.accumulateCore(
        /*guard_config_enable_core=*/1u,
        /*guard_mode_ok_core=*/1u,
        /*guard_mem_bound_core=*/1u,
        /*touch_gate_feature_disabled_total_core=*/0u,
        /*touch_gate_non_idx2_mode_total_core=*/0u,
        /*touch_gate_mem_unbound_total_core=*/0u,
        /*touch_gate_post_oob_total_core=*/1u,
        /*touch_gate_non_gather_window_total_core=*/2u,
        /*touch_gate_entered_total_core=*/3u,
        /*touch_events_total_core=*/4u,
        /*lookup_miss_total_core=*/5u,
        /*enqueued_total_core=*/6u,
        /*dedup_pending_total_core=*/7u,
        /*dedup_inflight_total_core=*/8u,
        /*dedup_cache_total_core=*/9u,
        /*prefetch_issued_total_core=*/10u,
        /*prefetch_bytes_total_core=*/64u,
        /*prefetch_deferred_total_core=*/11u,
        /*prefetch_blocked_by_cap_total_core=*/12u,
        /*prefetch_failed_total_core=*/13u,
        /*prefetch_resp_ok_total_core=*/14u,
        /*prefetch_resp_short_total_core=*/15u,
        /*prefetch_resp_drop_tail_total_core=*/16u,
        /*prefetch_complete_inflight_miss_total_core=*/17u,
        /*prefetch_complete_zero_waiters_total_core=*/18u,
        /*prefetch_complete_waiters_total_core=*/19u,
        /*owner_useful_total_core=*/20u,
        /*owner_dead_total_core=*/21u,
        /*owner_join_before_ready_total_core=*/22u,
        /*owner_ready_before_demand_total_core=*/23u,
        /*demand_hit_total_core=*/24u,
        /*demand_join_total_core=*/25u,
        /*demand_join_cb_nonnull_total_core=*/26u,
        /*demand_join_cb_null_total_core=*/27u,
        /*demand_fallback_total_core=*/28u,
        /*waiters_served_total_core=*/29u,
        /*cache_fill_total_core=*/30u,
        /*cache_evict_total_core=*/31u,
        /*cache_entries_final_core=*/32u,
        /*pending_dropped_on_begin_apply_total_core=*/33u,
        /*pending_dropped_on_begin_apply_frontier_total_core=*/34u,
        /*frontier_kept_and_later_useful_total_core=*/35u,
        /*frontier_kept_but_zero_waiter_total_core=*/36u,
        /*frontier_kept_cross_window_stale_total_core=*/37u,
        /*budget_ticks_total_core=*/38u,
        /*budget_effective_total_core=*/39u,
        /*budget_adapt_ticks_total_core=*/40u,
        /*inflight_cap_effective_peak_core=*/41u);
    idx2.accumulateCore(
        /*guard_config_enable_core=*/0u,
        /*guard_mode_ok_core=*/1u,
        /*guard_mem_bound_core=*/0u,
        /*touch_gate_feature_disabled_total_core=*/2u,
        /*touch_gate_non_idx2_mode_total_core=*/3u,
        /*touch_gate_mem_unbound_total_core=*/4u,
        /*touch_gate_post_oob_total_core=*/5u,
        /*touch_gate_non_gather_window_total_core=*/6u,
        /*touch_gate_entered_total_core=*/7u,
        /*touch_events_total_core=*/8u,
        /*lookup_miss_total_core=*/9u,
        /*enqueued_total_core=*/10u,
        /*dedup_pending_total_core=*/11u,
        /*dedup_inflight_total_core=*/12u,
        /*dedup_cache_total_core=*/13u,
        /*prefetch_issued_total_core=*/14u,
        /*prefetch_bytes_total_core=*/128u,
        /*prefetch_deferred_total_core=*/15u,
        /*prefetch_blocked_by_cap_total_core=*/16u,
        /*prefetch_failed_total_core=*/17u,
        /*prefetch_resp_ok_total_core=*/18u,
        /*prefetch_resp_short_total_core=*/19u,
        /*prefetch_resp_drop_tail_total_core=*/20u,
        /*prefetch_complete_inflight_miss_total_core=*/21u,
        /*prefetch_complete_zero_waiters_total_core=*/22u,
        /*prefetch_complete_waiters_total_core=*/23u,
        /*owner_useful_total_core=*/24u,
        /*owner_dead_total_core=*/25u,
        /*owner_join_before_ready_total_core=*/26u,
        /*owner_ready_before_demand_total_core=*/27u,
        /*demand_hit_total_core=*/28u,
        /*demand_join_total_core=*/29u,
        /*demand_join_cb_nonnull_total_core=*/30u,
        /*demand_join_cb_null_total_core=*/31u,
        /*demand_fallback_total_core=*/32u,
        /*waiters_served_total_core=*/33u,
        /*cache_fill_total_core=*/34u,
        /*cache_evict_total_core=*/35u,
        /*cache_entries_final_core=*/36u,
        /*pending_dropped_on_begin_apply_total_core=*/37u,
        /*pending_dropped_on_begin_apply_frontier_total_core=*/38u,
        /*frontier_kept_and_later_useful_total_core=*/39u,
        /*frontier_kept_but_zero_waiter_total_core=*/40u,
        /*frontier_kept_cross_window_stale_total_core=*/41u,
        /*budget_ticks_total_core=*/42u,
        /*budget_effective_total_core=*/43u,
        /*budget_adapt_ticks_total_core=*/44u,
        /*inflight_cap_effective_peak_core=*/45u);

    assert(idx2.guard_config_enable == 1u);
    assert(idx2.guard_mode_ok == 2u);
    assert(idx2.guard_mem_bound == 1u);
    assert(idx2.touch_gate_feature_disabled_total == 2u);
    assert(idx2.touch_gate_non_idx2_mode_total == 3u);
    assert(idx2.touch_gate_mem_unbound_total == 4u);
    assert(idx2.touch_gate_post_oob_total == 6u);
    assert(idx2.touch_gate_non_gather_window_total == 8u);
    assert(idx2.touch_gate_entered_total == 10u);
    assert(idx2.touch_events_total == 12u);
    assert(idx2.lookup_miss_total == 14u);
    assert(idx2.enqueued_total == 16u);
    assert(idx2.dedup_pending_total == 18u);
    assert(idx2.dedup_inflight_total == 20u);
    assert(idx2.dedup_cache_total == 22u);
    assert(idx2.prefetch_issued_total == 24u);
    assert(idx2.prefetch_bytes_total == 192u);
    assert(idx2.prefetch_deferred_total == 26u);
    assert(idx2.prefetch_blocked_by_cap_total == 28u);
    assert(idx2.prefetch_failed_total == 30u);
    assert(idx2.prefetch_resp_ok_total == 32u);
    assert(idx2.prefetch_resp_short_total == 34u);
    assert(idx2.prefetch_resp_drop_tail_total == 36u);
    assert(idx2.prefetch_complete_inflight_miss_total == 38u);
    assert(idx2.prefetch_complete_zero_waiters_total == 40u);
    assert(idx2.prefetch_complete_waiters_total == 42u);
    assert(idx2.owner_useful_total == 44u);
    assert(idx2.owner_dead_total == 46u);
    assert(idx2.owner_join_before_ready_total == 48u);
    assert(idx2.owner_ready_before_demand_total == 50u);
    assert(idx2.demand_hit_total == 52u);
    assert(idx2.demand_join_total == 54u);
    assert(idx2.demand_join_cb_nonnull_total == 56u);
    assert(idx2.demand_join_cb_null_total == 58u);
    assert(idx2.demand_fallback_total == 60u);
    assert(idx2.waiters_served_total == 62u);
    assert(idx2.cache_fill_total == 64u);
    assert(idx2.cache_evict_total == 66u);
    assert(idx2.cache_entries_final == 68u);
    assert(idx2.pending_dropped_on_begin_apply_total == 70u);
    assert(idx2.pending_dropped_on_begin_apply_frontier_total == 72u);
    assert(idx2.frontier_kept_and_later_useful_total == 74u);
    assert(idx2.frontier_kept_but_zero_waiter_total == 76u);
    assert(idx2.frontier_kept_cross_window_stale_total == 78u);
    assert(idx2.budget_ticks_total == 80u);
    assert(idx2.budget_effective_total == 82u);
    assert(idx2.budget_adapt_ticks_total == 84u);
    assert(idx2.inflight_cap_effective_peak == 45u);

    return 0;
}
