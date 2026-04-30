# SnnDL HotSpot Thermal Next-Stage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把当前 `HotSpot Thermal V1` 从“整次 run 平均功率的离线热导出器”升级成“窗口化、来源可追踪、可继续长到温度反馈闭环”的正式热研究平台。

**Architecture:** 当前最该优先补的是时间维度，而不是马上做温度闭环。第一阶段复用仓库里已有但被关闭的 `window_metrics` 通道，让 `mesh_template -> run_dir -> thermal_export.py` 真正形成多窗口功率轨迹；第二阶段补强 `thermal_summary.json` / `analysis export` 的来源和语义；第三阶段再追加最小 `memctrl` 热块，把系统热图从“纯 compute mesh”扩到“compute + on-die memory edge”。在线热反馈接口和 `3D-ICE` 后端保留为下一批设计，不混进当前实现批次。

**Tech Stack:** Python 3、`unittest`、`mesh_template` spec/runtime/build 配置链、`run_mesh_with_time.sh`、`thermal_export.py`、`analyze_thermal_runs.py`、SST/SnnDL 现有 `MultiCorePE` / `SnnNIC` 统计、HotSpot CLI。

---

## Priority Order

- `P0`：窗口化热轨迹基础设施
- `P1`：功耗来源/分析语义硬化
- `P2`：最小 `memctrl` 热块
- `Deferred`：在线温度反馈接口、HotSpot/3D-ICE 双后端

### Task 1: Re-enable Window Trace Plumbing For Thermal Mode (`P0`)

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/spec.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/legacy_defaults.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/runtime.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/paths.py`
- Test: `/home/xgy/remote/sst_dram_si/mesh_template/test_spec_resolver.py`
- Test: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_thermal_config.py`

**Step 1: Write the failing tests**

Add spec/runtime tests for the minimal next-stage thermal trace contract:

- `thermal.window_trace_enable = true|false`
- `thermal.window_trace_max_rows = <int >= 1>`

Expect:

- spec parser accepts and normalizes these fields
- `effective_config.json["thermal"]` preserves them
- when `window_trace_enable=1`, runtime/build path no longer hard-codes `export_window_metrics_csv=""`
- each core gets a deterministic path like:
  - `<run_dir>/pe00/core00_window_metrics.csv`

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.mesh_template.test_spec_resolver \
  sst_dram_si.mesh_template.test_runtime_thermal_config -v
```

Expected: FAIL because the new thermal trace fields and per-core window export plumbing do not exist yet.

**Step 3: Write minimal implementation**

- Extend `spec.py` top-level `thermal` schema with:
  - `window_trace_enable`
  - `window_trace_max_rows`
- Add matching defaults in `legacy_defaults.py`
- Export the normalized values through `config.py` / `runtime.py`
- In `build.py`, when `thermal.enable=1` and `thermal.window_trace_enable=1`:
  - stop forcing `export_window_metrics_csv=""`
  - emit deterministic per-core CSV paths under the existing run dir
- Keep the default path fully backward compatible:
  - if `window_trace_enable=0`, behavior must remain exactly as today

**Step 4: Run tests to verify they pass**

Run the same unittest command again and expect PASS.

**Step 5: Manual sanity verification**

Run one existing thermal smoke spec with:

```bash
cd /home/xgy/remote/sst_dram_si && ./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/tools/specs/mesh_hotspot_thermal_3d_csv_smoke_v1.json"
```

Expected:

- run dir now contains at least one `peXX/coreYY_window_metrics.csv`
- existing `thermal/summary/thermal_summary.json` generation still works

### Task 2: Teach `thermal_export.py` To Emit Multi-Window Ptrace (`P0`)

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/thermal_export.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py`

**Step 1: Write the failing tests**

Add thermal export tests that create synthetic per-core `window_metrics.csv` inputs with at least two windows and expect:

- `snndl_mesh.ptrace` to contain:
  - one header row
  - `N >= 2` power rows
- `thermal_summary.json` to expose:
  - `trace_mode = "windowed"`
  - `window_count = <N>`
  - `window_source = "window_metrics"`
- fallback behavior to remain intact:
  - when no window metrics exist, exporter must keep today’s single-row average-power behavior

Add analysis tests that expect:

- `run_summary.csv` to expose `trace_mode`
- `thermal_analysis.json` to carry `window_count`

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.tools.test_thermal_export \
  sst_dram_si.tools.test_analyze_thermal_runs -v
```

Expected: FAIL because the exporter currently writes a single averaged `ptrace` row.

**Step 3: Write minimal implementation**

- In `thermal_export.py`:
  - discover `pe*/core*_window_metrics.csv`
  - aggregate them into per-tile, per-window power rows
  - emit a real multi-row `ptrace`
  - keep current single-row path as fallback when no window data exists
- Add summary fields:
  - `trace_mode`
  - `window_count`
  - `window_source`
  - optional `window_duration_ns`
- In `analyze_thermal_runs.py`:
  - surface `trace_mode` / `window_count` in exported CSV/JSON

**Step 4: Run tests to verify they pass**

Run the same unittest command again and expect PASS.

**Step 5: Manual verification on formal runs**

Run:

```bash
cd /home/xgy/remote/sst_dram_si && \
MESH_RUN_ROOT="/home/xgy/remote/tmp/hotspot_formal_spec_3d_csv_v2_windowed" \
MESH_THERMAL_HOTSPOT_BIN="/home/xgy/remote/externals/HotSpot-7.0/hotspot" \
./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/tools/specs/mesh_hotspot_thermal_3d_csv_smoke_v1.json"
```

Expected:

- `thermal/hotspot/snndl_mesh.ptrace` has multiple data rows
- `thermal/summary/thermal_summary.json["trace_mode"] == "windowed"`

### Task 3: Harden Power-Source Provenance And Analysis Hygiene (`P1`)

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/thermal_export.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py`

**Step 1: Write the failing tests**

Add tests that expect:

- `thermal_summary.json` to carry explicit provenance:
  - `power_source_contract_version`
  - `cycle_model_applicable`
  - `trace_mode`
- `analyze_thermal_runs.py` to support:
  - `--nonzero-power-only`
  - `--active-layers-only`
- passive TIM layers with `average_power_w == 0` can be filtered out of `top_blocks.csv`

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.tools.test_thermal_export \
  sst_dram_si.tools.test_analyze_thermal_runs -v
```

Expected: FAIL because provenance fields and analysis filters do not exist yet.

**Step 3: Write minimal implementation**

- In `thermal_export.py`, add explicit summary fields:
  - `power_source_contract_version = "v1"`
  - `trace_mode = "average" | "windowed"`
  - `cycle_model_applicable = true|false` per block/layer path where appropriate
- Keep `csv` source semantics explicit:
  - do not backfill cycle-derived fields
- In `analyze_thermal_runs.py`, add filter flags:
  - `--nonzero-power-only`
  - `--active-layers-only`
- Ensure filtered exports still preserve deterministic ordering

**Step 4: Run tests to verify they pass**

Run the same unittest command again and expect PASS.

**Step 5: Manual verification**

Run analysis on the formal runs:

```bash
python3 /home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py \
  --run-dir /home/xgy/remote/tmp/hotspot_formal_spec_3d_stats_prefix_v1/20260319-135209 \
  --run-dir /home/xgy/remote/tmp/hotspot_formal_spec_3d_csv_v1/20260319-135033 \
  --out-dir /home/xgy/remote/tmp/hotspot_thermal_analysis_export_filtered \
  --top-n 12 \
  --nonzero-power-only \
  --active-layers-only
```

Expected:

- passive `tim_mid` rows disappear from hottest-block ranking
- output JSON clearly distinguishes `average` vs `windowed`

### Task 4: Add A Minimal `memctrl` Thermal Block (`P2`)

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/spec.py`
- Test: `/home/xgy/remote/sst_dram_si/mesh_template/test_spec_resolver.py`
- Test: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_thermal_config.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/thermal_export.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/analyze_thermal_runs.py`
- Test: `/home/xgy/remote/sst_dram_si/tools/test_analyze_thermal_runs.py`

**Step 1: Write the failing tests**

Add tests for the smallest useful controller-thermal slice:

- new thermal option:
  - `thermal.include_memctrl = true|false`
- when enabled, exporter adds one edge controller strip block:
  - `mesh_memctrl_east`
- power source uses existing memory summary/proxy data
- analysis export recognizes `block_type = "memctrl"`

This first slice is intentionally YAGNI:

- one global strip block first
- not per-tile controller blocks yet

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.mesh_template.test_spec_resolver \
  sst_dram_si.mesh_template.test_runtime_thermal_config \
  sst_dram_si.tools.test_thermal_export \
  sst_dram_si.tools.test_analyze_thermal_runs -v
```

Expected: FAIL because `include_memctrl` and `mesh_memctrl_east` do not exist.

**Step 3: Write minimal implementation**

- Extend thermal spec/runtime with `include_memctrl`
- In `thermal_export.py`:
  - add one east-edge memctrl block to the floorplan when enabled
  - derive a minimal power proxy from memory summary/statistics
  - include the block in `ptrace`, `tile_temperature_summary.csv` (or a parallel block summary CSV if cleaner), and `thermal_summary.json`
- In `analyze_thermal_runs.py`:
  - surface `memctrl` blocks in exported tables

**Step 4: Run tests to verify they pass**

Run the same unittest command again and expect PASS.

**Step 5: Manual verification**

Run one thermal case with `include_memctrl=1` and expect:

- floorplan contains `mesh_memctrl_east`
- summary and analysis exports include controller temperature/power rows

## Deferred After This Plan

These are important, but should not be mixed into the current execution batch:

1. **Online temperature feedback interface**
   - introduce a runtime temperature snapshot contract
   - let PE/router/mapping policies read temperature without requiring full HotSpot-in-the-loop every cycle

2. **HotSpot / 3D-ICE backend abstraction**
   - keep current spec-level `thermal.backend` future-proof
   - do not implement `3dice` until the multi-window pipeline and provenance model are stable

3. **True stacked 3D thermal system**
   - move from “layered geometry” to “compute + memory + TSV/interposer aware” thermal experiments

## Recommended Execution Order

1. Task 1
2. Task 2
3. Task 3
4. Task 4

Do not start Task 4 before Task 2 is green.  
Do not start online feedback or `3dice` backend work before Task 3 is green.
