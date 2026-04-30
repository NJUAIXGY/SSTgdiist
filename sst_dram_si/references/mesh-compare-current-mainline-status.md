# mesh compare current mainline status

- Generated UTC: `2026-04-07T04:26:34.492340+00:00`
- Role: shared readable current-state surface derived from stable compare smoke references

## Stable Surfaces
- stable top-level gate: `/home/xgy/remote/sst_dram_si/references/mesh-compare-sidecar-report.json`
- stable history path: `/home/xgy/remote/sst_dram_si/references/mesh-compare-history.json`
- stable summary markdown: `/home/xgy/remote/sst_dram_si/references/mesh-compare-sidecar-summary.md`
- source matrix summary: `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4_exec_mode_compare/matrix/20260407-114554/summary.json`

## Top-Level Gate
- `gate_ok = True`
- `latest_all_green = True`
- `required_cases = gas, naive_raw, naive_opt`
- `gate_reasons = none`

## Freshness
- `freshness_mode = latest_only`
- `latest_date = 2026-04-07`
- `latest_generated_utc = 2026-04-07T03:48:04.644089+00:00`
- `latest_age_hours = 0.641625`
- `stale_after_hours = 48.0`
- `stale = False`
- `history_entry_count = 1`
- `all_green_history = True`

## Cases
- `gas.gate_ok = True`
- `gas.requested_exec_mode = gas`
- `gas.effective_exec_mode = gas`
- `gas.compare_role = smoke`
- `gas.bounded_validation = True`
- `gas.validator_fail = 0`
- `gas.memory_nonzero = True`
- `gas.gate_reasons = none`
- `naive_opt.gate_ok = True`
- `naive_opt.requested_exec_mode = naive_opt`
- `naive_opt.effective_exec_mode = naive_raw`
- `naive_opt.compare_role = smoke`
- `naive_opt.bounded_validation = True`
- `naive_opt.validator_fail = 0`
- `naive_opt.memory_nonzero = True`
- `naive_opt.gate_reasons = none`
- `naive_raw.gate_ok = True`
- `naive_raw.requested_exec_mode = naive_raw`
- `naive_raw.effective_exec_mode = naive_raw`
- `naive_raw.compare_role = smoke`
- `naive_raw.bounded_validation = True`
- `naive_raw.validator_fail = 0`
- `naive_raw.memory_nonzero = True`
- `naive_raw.gate_reasons = none`

## Refresh
```bash
cd "/home/xgy/remote/sst_dram_si"
python3 "/home/xgy/remote/sst_dram_si/tools/refresh_mesh_compare_surfaces.py" --run-matrix
```
