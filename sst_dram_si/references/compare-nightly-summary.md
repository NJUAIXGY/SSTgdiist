# compare experimental nightly sidecar

- Generated UTC: `2026-04-07T05:02:10.469983+00:00`
- Gate: `PASS`
- Gate name: `mesh_exec_mode_compare_acceptance`
- Gate version: `1.0`
- Artifact role: `stable_top_level_gate`
- Authority scope: `experimental_gate_authority`
- Latest nightly date: `2026-04-07`
- Required cases (3): `gas, naive_raw, naive_opt`
- Missing cases: `none`

## Authority

- stable top-level gate: `/home/xgy/remote/sst_dram_si/references/compare-nightly-report.json`
- stable observer summary: `/home/xgy/remote/sst_dram_si/references/compare-nightly-observer-summary.json`
- shared current-state rollup: `/home/xgy/remote/sst_dram_si/references/compare-current-status.md`
- current_mainline_status_path: `/home/xgy/remote/sst_dram_si/references/compare-current-status.md`
- stable surface refresh UTC: `2026-04-07T05:02:10.469983+00:00`
- dated history authority: `/home/xgy/remote/sst_dram_si/references/compare-smoke-history.json`

## Freshness

- `latest_date = 2026-04-07`
- `stale = False`
- `latest_age_days = 0`
- `max_age_days = 2`
- `all_dates_ok = True`
- `latest_recovered_date = none`
- `freshness_mode = since_latest_recovery`
- `effective_all_dates_ok = True`

## Cases

| case | requested | effective | role | bounded | fail | warn | strict | memory.nonzero | ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gas | gas | gas | smoke | True | 0 | 0 | 0 | True | True |
| naive_raw | naive_raw | naive_raw | smoke | True | 0 | 0 | 0 | True | True |
| naive_opt | naive_opt | naive_raw | smoke | True | 0 | 0 | 0 | True | True |

## Reasons

- `none`
