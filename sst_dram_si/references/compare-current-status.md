# compare current mainline status

- Generated UTC: `2026-04-07T05:02:10.469983+00:00`
- Role: shared readable current-state surface derived from stable compare references

## Stable Surfaces
- stable top-level gate: `/home/xgy/remote/sst_dram_si/references/compare-nightly-report.json`
- stable observer summary: `/home/xgy/remote/sst_dram_si/references/compare-nightly-observer-summary.json`
- stable nightly summary: `/home/xgy/remote/sst_dram_si/references/compare-nightly-summary.md`
- stable current mainline: `/home/xgy/remote/sst_dram_si/references/compare-current-status.md`
- latest history date: `2026-04-07`

## Top-Level Gate
- `gate_ok = True`
- `required_cases = gas, naive_raw, naive_opt`
- `gate_reasons = none`

## Freshness
- `latest_date = 2026-04-07`
- `stale = False`
- `freshness_mode = since_latest_recovery`
- `effective_all_dates_ok = True`

## Latest Cases
- `gas.requested_exec_mode = gas`
- `gas.effective_exec_mode = gas`
- `gas.compare_role = smoke`
- `gas.bounded_validation = True`
- `gas.ok = True`
- `naive_raw.requested_exec_mode = naive_raw`
- `naive_raw.effective_exec_mode = naive_raw`
- `naive_raw.compare_role = smoke`
- `naive_raw.bounded_validation = True`
- `naive_raw.ok = True`
- `naive_opt.requested_exec_mode = naive_opt`
- `naive_opt.effective_exec_mode = naive_raw`
- `naive_opt.compare_role = smoke`
- `naive_opt.bounded_validation = True`
- `naive_opt.ok = True`
