# riscv_snn current mainline status

- Generated UTC: `2026-04-18T12:56:43.969019+00:00`
- Role: shared readable current-state surface derived from stable experimental references

## Stable Surfaces
- stable top-level gate: `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
- stable observer summary: `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-observer-summary.json`
- stable research report: `/home/xgy/remote/riscv_snn_isa_lab/references/riscv-snn-research-report.json`
- stable adequacy validation: `/home/xgy/remote/riscv_snn_isa_lab/references/observer-adequacy-validation.json`
- primary optional group: `completion_overflow_optional`
- active optional group: `completion_overflow_optional`
- stable surface refresh UTC: `2026-04-18T12:56:43.969019+00:00`
- stable surface refresh observer summary: `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-observer-summary.json`
- stable surface refresh current mainline: `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`
- stable supplementary surface history: `/home/xgy/remote/riscv_snn_isa_lab/references/supplementary-surface-history.json`
- supplementary surface authority: `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_supplementary_surface_v1.json`
- stable surface refresh audit: `/home/xgy/remote/riscv_snn_isa_lab/references/stable-surface-refresh-audit.json`
- stable surface refresh optional promotion dossier: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-18-completion-overflow-optional-promotion-dossier.json`
- latest optional admission audit: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-18-completion-overflow-optional-admission-audit.json`
- optional admission audit `queue_optional`: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-18-queue-optional-admission-audit.json`
- runtime gate authority: `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_runtime_gate_v1.json`

## Top-Level Gate
- `gate_ok = True`
- `with_equivalence = True`
- `with_full_equivalence = True`
- `required_families = barrier_wfi_order_ref, external_dyn_desc_bad_policy_ref, external_dyn_desc_fault_overwrite_chain_ref, external_dyn_desc_fault_rearm_ref, external_dyn_desc_fault_ref, external_dyn_desc_ref`

## Observer Closure
- `entry_count = 4`
- `first_fail_date = 2026-03-30`
- `latest_recovered_date = 2026-04-02`
- `all_ok_latest = True`
- `history_contract = observer_sample_sequence_v1`

## Research / Validation
- `observer_adequacy.status = ready_with_fail_recovery_sample`
- `status = pass`
- `mismatch_count = 0`

## Supplementary Surfaces
- `compare.status = pass`
- `compare.healthy = True`
- `compare.freshness_ok = True`
- `compare.present = True`
- `compare.gate_ok = True`
- `compare.latest_date = 2026-04-07`
- `compare.stale = False`
- `compare.freshness_mode = since_latest_recovery`
- `compare.effective_all_dates_ok = True`
- `compare.history_contract = compare_source_history_passthrough_v1`
- `compare.entry_count = 2`
- `compare.latest_recovered_date = none`
- `compare.report_path = /home/xgy/remote/sst_dram_si/references/compare-nightly-report.json`
- `compare.current_mainline_status_path = /home/xgy/remote/sst_dram_si/references/compare-current-status.md`
- `compare.summary_md_path = /home/xgy/remote/sst_dram_si/references/compare-nightly-summary.md`
- `compare.load_error = none`
- `reference_compare.status = pass`
- `reference_compare.healthy = True`
- `reference_compare.freshness_ok = True`
- `reference_compare.present = True`
- `reference_compare.gate_ok = True`
- `reference_compare.latest_date = 2026-04-18`
- `reference_compare.stale = False`
- `reference_compare.freshness_mode = reference_compare_latest_only`
- `reference_compare.effective_all_dates_ok = True`
- `reference_compare.history_contract = reference_compare_source_history_passthrough_v1`
- `reference_compare.entry_count = 1`
- `reference_compare.latest_recovered_date = 2026-04-18`
- `reference_compare.report_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-compare-nightly-report.json`
- `reference_compare.current_mainline_status_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-compare-current-status.md`
- `reference_compare.summary_md_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-compare-nightly-summary.md`
- `reference_compare.load_error = none`
- `reference_program_compare.status = pass`
- `reference_program_compare.healthy = True`
- `reference_program_compare.freshness_ok = True`
- `reference_program_compare.present = True`
- `reference_program_compare.gate_ok = True`
- `reference_program_compare.latest_date = 2026-04-18`
- `reference_program_compare.stale = False`
- `reference_program_compare.freshness_mode = reference_program_compare_latest_only`
- `reference_program_compare.effective_all_dates_ok = True`
- `reference_program_compare.history_contract = reference_program_compare_source_history_passthrough_v1`
- `reference_program_compare.entry_count = 1`
- `reference_program_compare.latest_recovered_date = 2026-04-18`
- `reference_program_compare.report_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-program-compare-nightly-report.json`
- `reference_program_compare.current_mainline_status_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-program-compare-current-status.md`
- `reference_program_compare.summary_md_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-program-compare-nightly-summary.md`
- `reference_program_compare.load_error = none`
- `stat_snapshot_family.status = pass`
- `stat_snapshot_family.healthy = True`
- `stat_snapshot_family.freshness_ok = True`
- `stat_snapshot_family.present = True`
- `stat_snapshot_family.gate_ok = True`
- `stat_snapshot_family.latest_date = 2026-04-18`
- `stat_snapshot_family.stale = False`
- `stat_snapshot_family.freshness_mode = latest_refresh_only`
- `stat_snapshot_family.effective_all_dates_ok = True`
- `stat_snapshot_family.history_contract = stat_snapshot_family_surface_history_v1`
- `stat_snapshot_family.entry_count = 1`
- `stat_snapshot_family.latest_recovered_date = 2026-04-18`
- `stat_snapshot_family.selector_count = 3`
- `stat_snapshot_family.covered_selector_count = 3`
- `stat_snapshot_family.report_path = /home/xgy/remote/riscv_snn_isa_lab/references/stat-snapshot-family-nightly-report.json`
- `stat_snapshot_family.current_mainline_status_path = /home/xgy/remote/riscv_snn_isa_lab/references/stat-snapshot-family-current-status.md`
- `stat_snapshot_family.summary_md_path = /home/xgy/remote/riscv_snn_isa_lab/references/stat-snapshot-family-nightly-summary.md`
- `stat_snapshot_family.load_error = none`

## Optional Freshness
- `queue.latest_date = 2026-04-04`
- `queue.entry_count = 2`
- `queue.all_dates_ok = True`
- `queue.history_contract = canonical_queue_optional_only`
- `queue.freshness_mode = since_latest_recovery`
- `queue.effective_entry_count = 2`
- `queue.effective_all_dates_ok = True`
- `primary_optional_group = completion_overflow_optional`
- `active_optional_group = completion_overflow_optional`
- `active_optional_latest_date = 2026-04-04`
- `active_optional_history_contract = canonical_completion_overflow_optional_only`
- `active_optional_freshness_mode = since_latest_recovery`
- `active_optional_effective_entry_count = 2`
- `active_optional_effective_all_dates_ok = True`
- `completion_overflow_optional.latest_date = 2026-04-04`
- `completion_overflow_optional.entry_count = 2`
- `completion_overflow_optional.all_dates_ok = True`
- `completion_overflow_optional.history_contract = canonical_completion_overflow_optional_only`
- `completion_overflow_optional.freshness_mode = since_latest_recovery`
- `completion_overflow_optional.effective_entry_count = 2`
- `completion_overflow_optional.effective_all_dates_ok = True`
- `queue_optional.latest_date = 2026-04-04`
- `queue_optional.entry_count = 2`
- `queue_optional.all_dates_ok = True`
- `queue_optional.history_contract = canonical_queue_optional_only`
- `queue_optional.freshness_mode = since_latest_recovery`
- `queue_optional.effective_entry_count = 2`
- `queue_optional.effective_all_dates_ok = True`

## Optional Admission
- `primary_optional_group = completion_overflow_optional`
- `active_optional_group = completion_overflow_optional`
- `promotion_ready = True`
- `explicit_review_ok = True`
- `blocking = False`
- `completion_overflow_optional.promotion_ready = True`
- `completion_overflow_optional.explicit_review_ok = True`
- `completion_overflow_optional.blocking = False`
- `queue_optional.promotion_ready = True`
- `queue_optional.explicit_review_ok = True`
- `queue_optional.blocking = False`

## Optional Failure Summary
- `completion_overflow_optional.failing_reason_ids = none`
- `queue_optional.failing_reason_ids = none`

## Runtime Gate Semantics
- `completion_consumed_covers_visible`: `completion consumption should cover every visible completion unless the family intentionally stops earlier`
- `completion_queue_overflow_ref`: `one software-visible completion may remain intentionally unconsumed when cmpq-full fault retires`
- `external_dyn_desc_bad_policy_ref`: `accepted-fault completion progress may satisfy the runtime bridge path even when committed progress is intentionally blocked`
- `external_dyn_desc_fault_overwrite_chain_ref`: `accepted-fault completion progress is allowed while visible fault snapshots are overwritten across retired completions`
- `external_dyn_desc_fault_rearm_ref`: `accepted-fault completion progress is allowed while clear-then-refault lifecycle is visible`
- `external_dyn_desc_fault_ref`: `accepted-fault completion progress counts as forward progress`
- `queue_backpressure_ref`: `command-overdoorbell overflow may fault before software acks the visible completion`
- `stat_snapshot_bad_selector_ref`: `bad-selector StatSnapshot retires through a visible fault snapshot and does not require a successful completion payload`
- `stat_snapshot_family.AcceptedCommands.reference_ready = True`
- `stat_snapshot_family.CompletedCommands.reference_ready = True`
- `stat_snapshot_family.ProviderBound.reference_ready = True`

## Refresh
```bash
cd "/home/xgy/remote/riscv_snn_isa_lab"
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" export-mainline-status
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" mainline-refresh --group completion_overflow_optional
```
