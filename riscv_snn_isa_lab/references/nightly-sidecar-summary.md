# riscv_snn experimental nightly sidecar

- Generated UTC: `2026-04-18T12:56:43.969019+00:00`
- Gate: PASS
- Gate name: `riscv_snn_experimental_nightly`
- Gate version: `1.1`
- Artifact role: `stable_top_level_gate`
- Authority scope: `experimental_gate_authority`
- Latest nightly date: `2026-04-02`
- Required families (6): `barrier_wfi_order_ref, external_dyn_desc_bad_policy_ref, external_dyn_desc_fault_overwrite_chain_ref, external_dyn_desc_fault_rearm_ref, external_dyn_desc_fault_ref, external_dyn_desc_ref`
- Missing families: `none`
- First fail date: `none`
- First drift date: `none`
- Latest recovered date: `none`

## Authority

- stable top-level gate: `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
- stable observer summary: `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-observer-summary.json`
- shared current-state rollup: `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`
- current_mainline_status_path: `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`
- stable surface refresh UTC: `2026-04-18T12:56:43.969019+00:00`
- stable surface refresh observer summary: `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-observer-summary.json`
- stable surface refresh current mainline: `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`
- stable supplementary surface history: `/home/xgy/remote/riscv_snn_isa_lab/references/supplementary-surface-history.json`
- supplementary surface authority: `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_supplementary_surface_v1.json`
- stable surface refresh audit: `/home/xgy/remote/riscv_snn_isa_lab/references/stable-surface-refresh-audit.json`
- stable optional promotion dossier: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-18-completion-overflow-optional-promotion-dossier.json`
- dated family-level equivalence authority: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-02-equiv-matrix-subset-3a01206219b8.json`
- dated family-level equivalence authority surface: `subset`
- dated full-all equivalence snapshot (research-only, non-blocking): `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-02-equiv-matrix.json`
- dated full-all equivalence snapshot surface: `canonical`
- dated queue-optional equivalence matrix (research-only, non-blocking): `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-04-equiv-matrix-queue-optional.json`
- dated queue-optional equivalence surface: `canonical`
- dated nightly index: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-02-nightly-index.json`
- dated nightly index surface: `canonical`
- dated nightly index is not the equivalence authority

- dated optional-group equivalence `completion_overflow_optional` (research-only, non-blocking): `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-04-completion-queue-overflow-ref-equiv.json`
- dated optional-group equivalence surface `completion_overflow_optional`: `canonical`
- supplementary compare smoke gate (research-only, non-blocking): `/home/xgy/remote/sst_dram_si/references/compare-nightly-report.json`
- supplementary compare current-state rollup: `/home/xgy/remote/sst_dram_si/references/compare-current-status.md`
- supplementary reference compare gate (research-only, non-blocking): `/home/xgy/remote/riscv_snn_isa_lab/references/reference-compare-nightly-report.json`
- supplementary reference compare current-state rollup: `/home/xgy/remote/riscv_snn_isa_lab/references/reference-compare-current-status.md`
- supplementary reference program compare gate (research-only, non-blocking): `/home/xgy/remote/riscv_snn_isa_lab/references/reference-program-compare-nightly-report.json`
- supplementary reference program compare current-state rollup: `/home/xgy/remote/riscv_snn_isa_lab/references/reference-program-compare-current-status.md`
- supplementary stat snapshot family surface (research-only, non-blocking): `/home/xgy/remote/riscv_snn_isa_lab/references/stat-snapshot-family-nightly-report.json`
- supplementary stat snapshot family current-state rollup: `/home/xgy/remote/riscv_snn_isa_lab/references/stat-snapshot-family-current-status.md`

## Reasons

- none

## Runtime Cost

- Total elapsed seconds: `1101.129`
- Blocking elapsed seconds: `582.438`
- Non-blocking attachment elapsed seconds: `518.689`

| section | elapsed_seconds |
| --- | --- |
| completion_overflow_optional_equivalence_elapsed_seconds | 47.262 |
| equivalence_elapsed_seconds | 279.832 |
| full_equivalence_elapsed_seconds | 378.403 |
| history_elapsed_seconds | 0.001 |
| nightly_elapsed_seconds | 302.605 |
| optional_group_equivalence_elapsed_seconds | 140.286 |
| queue_equivalence_elapsed_seconds | 93.024 |
| queue_optional_equivalence_elapsed_seconds | 93.024 |

## Families

| family | builder_run_id | toolchain_run_id | manifest_match | audit_ok |
| --- | --- | --- | --- | --- |
| barrier_wfi_order_ref | 20260402-204246 | 20260402-204516 | True | True |
| external_dyn_desc_bad_policy_ref | 20260402-204134 | 20260402-204401 | True | True |
| external_dyn_desc_fault_overwrite_chain_ref | 20260402-204222 | 20260402-204451 | True | True |
| external_dyn_desc_fault_rearm_ref | 20260402-204158 | 20260402-204427 | True | True |
| external_dyn_desc_fault_ref | 20260402-204110 | 20260402-204337 | True | True |
| external_dyn_desc_ref | 20260402-204044 | 20260402-204314 | True | True |

## History

| date | count | all_ok | healthy | drift_families | failed_families |
| --- | --- | --- | --- | --- | --- |
| 2026-04-02 | 6 | True | True | - | - |
| 2026-04-01 | 6 | True | True | - | - |
| 2026-03-30 | 6 | True | True | - | - |
| 2026-03-28 | 6 | True | True | - | - |
| 2026-03-27 | 6 | True | True | - | - |
| 2026-03-25 | 5 | True | True | - | - |

## Equivalence

- Surface: `subset`
- Requested group: `all`
- Gate name: `riscv_snn_equiv_matrix`
- All OK: `True`
- Family count: `6`
- Summary path: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-02-equiv-matrix-subset-3a01206219b8.json`
- Runtime-bridge build preflight (research-only): `enabled=True` `all_ok=True` `family_count=6` `status_counts=ok:6` `contract_keys=riscv_snn.runtime_bridge.runtime_consumers`

| family | status | preflight_status | gate_reasons |
| --- | --- | --- | --- |
| barrier_wfi_order_ref | PASS | ok | none |
| external_dyn_desc_bad_policy_ref | PASS | ok | none |
| external_dyn_desc_fault_overwrite_chain_ref | PASS | ok | none |
| external_dyn_desc_fault_rearm_ref | PASS | ok | none |
| external_dyn_desc_fault_ref | PASS | ok | none |
| external_dyn_desc_ref | PASS | ok | none |

## Full All Equivalence Snapshot (Non-Blocking)

- Surface: `canonical`
- Requested group: `all`
- Gate name: `riscv_snn_equiv_matrix`
- All OK: `True`
- Family count: `8`
- Summary path: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-02-equiv-matrix.json`
- History path: `/home/xgy/remote/riscv_snn_isa_lab/references/full-equivalence-history.json`
- History latest date: `2026-04-02`
- History entry count: `4`
- Runtime-bridge build preflight (research-only): `enabled=True` `all_ok=True` `family_count=8` `status_counts=ok:8` `contract_keys=riscv_snn.runtime_bridge.runtime_consumers`

| family | status | preflight_status | gate_reasons |
| --- | --- | --- | --- |
| barrier_wfi_order_ref | PASS | ok | none |
| completion_queue_overflow_ref | PASS | ok | none |
| external_dyn_desc_bad_policy_ref | PASS | ok | none |
| external_dyn_desc_fault_overwrite_chain_ref | PASS | ok | none |
| external_dyn_desc_fault_rearm_ref | PASS | ok | none |
| external_dyn_desc_fault_ref | PASS | ok | none |
| external_dyn_desc_ref | PASS | ok | none |
| queue_backpressure_ref | PASS | ok | none |

## Queue Optional Equivalence (Non-Blocking)

- Surface: `canonical`
- Requested group: `queue_optional`
- Gate name: `riscv_snn_equiv_matrix`
- All OK: `True`
- Family count: `2`
- Summary path: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-04-equiv-matrix-queue-optional.json`
- Runtime-bridge build preflight (research-only): `enabled=True` `all_ok=True` `family_count=2` `status_counts=ok:2` `contract_keys=riscv_snn.runtime_bridge.runtime_consumers`

| family | status | preflight_status | gate_reasons |
| --- | --- | --- | --- |
| queue_backpressure_ref | PASS | ok | none |
| completion_queue_overflow_ref | PASS | ok | none |

## Optional Group Equivalence (Non-Blocking)

- Group: `completion_overflow_optional`
- Surface: `canonical`
- Requested group: `completion_overflow_optional`
- Gate name: `None`
- All OK: `True`
- Family count: `1`
- Summary path: `/home/xgy/remote/riscv_snn_isa_lab/references/2026-04-04-completion-queue-overflow-ref-equiv.json`

| family | status | preflight_status | gate_reasons |
| --- | --- | --- | --- |
| completion_queue_overflow_ref | PASS | none | none |


## Supplementary Surfaces

- `compare.status = pass`
- `compare.healthy = True`
- `compare.present = True`
- `compare.gate_ok = True`
- `compare.latest_date = 2026-04-07`
- `compare.stale = False`
- `compare.freshness_mode = since_latest_recovery`
- `compare.effective_all_dates_ok = True`
- `compare.report_path = /home/xgy/remote/sst_dram_si/references/compare-nightly-report.json`
- `compare.current_mainline_status_path = /home/xgy/remote/sst_dram_si/references/compare-current-status.md`
- `compare.summary_md_path = /home/xgy/remote/sst_dram_si/references/compare-nightly-summary.md`
- `reference_compare.status = pass`
- `reference_compare.healthy = True`
- `reference_compare.present = True`
- `reference_compare.gate_ok = True`
- `reference_compare.latest_date = 2026-04-18`
- `reference_compare.stale = False`
- `reference_compare.freshness_mode = reference_compare_latest_only`
- `reference_compare.effective_all_dates_ok = True`
- `reference_compare.report_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-compare-nightly-report.json`
- `reference_compare.current_mainline_status_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-compare-current-status.md`
- `reference_compare.summary_md_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-compare-nightly-summary.md`
- `reference_program_compare.status = pass`
- `reference_program_compare.healthy = True`
- `reference_program_compare.present = True`
- `reference_program_compare.gate_ok = True`
- `reference_program_compare.latest_date = 2026-04-18`
- `reference_program_compare.stale = False`
- `reference_program_compare.freshness_mode = reference_program_compare_latest_only`
- `reference_program_compare.effective_all_dates_ok = True`
- `reference_program_compare.report_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-program-compare-nightly-report.json`
- `reference_program_compare.current_mainline_status_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-program-compare-current-status.md`
- `reference_program_compare.summary_md_path = /home/xgy/remote/riscv_snn_isa_lab/references/reference-program-compare-nightly-summary.md`
- `stat_snapshot_family.status = pass`
- `stat_snapshot_family.healthy = True`
- `stat_snapshot_family.present = True`
- `stat_snapshot_family.gate_ok = True`
- `stat_snapshot_family.latest_date = 2026-04-18`
- `stat_snapshot_family.stale = False`
- `stat_snapshot_family.freshness_mode = latest_refresh_only`
- `stat_snapshot_family.effective_all_dates_ok = True`
- `stat_snapshot_family.selector_count = 3`
- `stat_snapshot_family.covered_selector_count = 3`
- `stat_snapshot_family.report_path = /home/xgy/remote/riscv_snn_isa_lab/references/stat-snapshot-family-nightly-report.json`
- `stat_snapshot_family.current_mainline_status_path = /home/xgy/remote/riscv_snn_isa_lab/references/stat-snapshot-family-current-status.md`
- `stat_snapshot_family.summary_md_path = /home/xgy/remote/riscv_snn_isa_lab/references/stat-snapshot-family-nightly-summary.md`
- `stat_snapshot_family.AcceptedCommands.reference_ready = True`
- `stat_snapshot_family.CompletedCommands.reference_ready = True`
- `stat_snapshot_family.ProviderBound.reference_ready = True`
