# SnnDL HotSpot Thermal V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `SST-SnnDL` 落地 `HotSpot Thermal V1` 的最小可运行链路，包括热配置导出、离线 `flp/ptrace` 生成与 HotSpot 调用脚手架。

**Architecture:** 采用 `offline-first` 方案：`mesh_template` 负责把热配置写入运行时与 `effective_config.json`，`thermal_export.py` 负责读取 `mesh_stats.csv`/`stdout.log` 生成 `thermal/` 目录、自动构造 `floorplan + ptrace + hotspot config`，并在可用时调用 HotSpot。第一版不改动 SST/SnnDL 主时序，只复用现有统计并为后续在线接口保留统一的数据模型。

**Tech Stack:** Python 3、`unittest`、现有 `mesh_template` runtime/build 配置链、HotSpot CLI、append-only progress logging。

---

### Task 1: Lock runtime thermal config export

**Files:**
- Create: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_thermal_config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/legacy_defaults.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/runtime.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`

**Step 1: Write the failing test**

Add a runtime-config test that expects:

- `MESH_THERMAL_ENABLE=1`
- `MESH_THERMAL_BACKEND=hotspot`
- `MESH_THERMAL_WINDOW_NS=1000`
- `MESH_THERMAL_OUT_DIR=thermal`
- `MESH_THERMAL_TILE_WIDTH_UM=1000`
- `MESH_THERMAL_TILE_HEIGHT_UM=1000`
- `MESH_THERMAL_TILE_GAP_UM=50`

to appear in:

- `rt.mesh_cfg["thermal"]`

and to be copied into:

- `effective_config.json["thermal"]`

with stable normalized defaults for omitted fields.

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest sst_dram_si.mesh_template.test_runtime_thermal_config -v
```

Expected: FAIL because thermal config export does not exist yet.

**Step 3: Write minimal implementation**

- Add default thermal state keys in `legacy_defaults.py`
- Add local-run/env plumbing in `config.py`
- Add `_build_thermal_cfg(...)` and runtime export in `runtime.py`
- Persist `mesh["thermal"]` into `effective_config.json` in `build.py`

**Step 4: Run test to verify it passes**

Run the same unittest command again and expect PASS.

### Task 2: Lock thermal_export CLI with failing tests

**Files:**
- Create: `/home/xgy/remote/sst_dram_si/tools/test_thermal_export.py`
- Create: `/home/xgy/remote/sst_dram_si/tools/thermal_export.py`

**Step 1: Write the failing tests**

Add CLI tests that expect `thermal_export.py` to:

- read `effective_config.json`
- create `<run_dir>/thermal/hotspot/`
- generate:
  - `snndl_mesh.flp`
  - `snndl_mesh.ptrace`
  - `hotspot.config`
  - `thermal_summary.json`
- write block names matching:
  - `tile_00_comp`
  - `tile_00_sram`
  - `tile_00_noc`
- gracefully skip HotSpot execution when the binary is absent, but still emit export artifacts and mark execution state in the summary

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest sst_dram_si.tools.test_thermal_export -v
```

Expected: FAIL because the tool does not exist yet.

**Step 3: Write minimal implementation**

Implement `thermal_export.py` with:

- CLI: `--run-dir`, optional `--hotspot-bin`
- effective thermal config loading
- automatic tile/block floorplan generation
- minimal power-trace generation from available stats:
  - SRAM energy if present
  - NIC packet/byte proxies if present
  - compute fallback placeholder power
- best-effort HotSpot invocation
- JSON summary export

**Step 4: Run test to verify it passes**

Run the same unittest command again and expect PASS.

### Task 3: Hook thermal export into the mesh run workflow

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/run_mesh_with_time.sh`
- Modify: `/home/xgy/remote/sst_dram_si/tools/run_mesh_with_time_ram2.sh`

**Step 1: Write the failing test**

Add or extend a CLI/plumbing test so the run workflow expects:

- thermal export to be attempted only when `thermal_enable=1`
- failure of HotSpot export to be non-fatal to the main SST run

If adding a new automated shell test is too costly, use an existing CLI plumbing test file and lock the command text/guard behavior there.

**Step 2: Run test to verify it fails**

Run the chosen unittest command and expect FAIL because the hook is absent.

**Step 3: Write minimal implementation**

After the existing `compute_essential_summary_mesh.py` step:

- check whether `effective_config.json["thermal"]["enable"] == 1`
- if yes, run:

```bash
python3 "$PROJECT_ROOT/tools/thermal_export.py" --run-dir "$RUN_DIR"
```

with non-fatal failure behavior (`|| true`-equivalent in shell logic without hiding logs).

**Step 4: Run test to verify it passes**

Run the same unittest/plumbing command again and expect PASS.

### Task 4: Verification and progress logging

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run focused test suite**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.mesh_template.test_runtime_thermal_config \
  sst_dram_si.tools.test_thermal_export -v
```

and any additional plumbing test introduced in Task 3.

Expected: PASS.

**Step 2: Append progress entry**

Append to `TECH_PROGRESS.md`:

- changed files
- how to run `thermal_export.py`
- where `thermal/` artifacts are written
- known limitations of V1

**Step 3: Sanity verification**

Run a minimal manual dry-run of `thermal_export.py` against a synthetic temp run-dir created by the tests or a small existing run dir.

Expected:

- `thermal/hotspot/snndl_mesh.flp`
- `thermal/hotspot/snndl_mesh.ptrace`
- `thermal/summary/thermal_summary.json`

present and readable.
