# SnnDL Thermal Phase 6 Multi-Case Calibration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有 `phase2 -> analyze_ablation -> export_phase2_paper_artifacts` 链路上补齐多 case 热偏差统计，正式产出可用于 RC vs HotSpot 校准分析的聚合 summary、CSV 和 SVG。

**Architecture:** `analyze_ablation.py` 负责把 case 级 delta 汇总成 `thermal_calibration` 聚合块；`export_phase2_paper_artifacts.py` 负责将该聚合块转成表格、图和 summary JSON；保持 runtime 仍只读 `online_rc_estimator`，HotSpot 继续 sidecar-only。

**Tech Stack:** Python 3、`unittest`、JSON/CSV/SVG 文本导出、append-only `TECH_PROGRESS.md`。

---

### Task 1: Freeze Phase 6 Scope

**Files:**
- Create: `/home/xgy/remote/docs/plans/nextarc/2026-03-20-snndl-thermal-phase6-multicase-calibration-design.md`
- Create: `/home/xgy/remote/docs/plans/nextarc/2026-03-20-snndl-thermal-phase6-multicase-calibration-implementation-plan.md`

**Step 1: Lock the data path**

明确本阶段只扩展：

- `/home/xgy/remote/snn3dexp/tools/analyze_ablation.py`
- `/home/xgy/remote/snn3dexp/tools/export_phase2_paper_artifacts.py`

不新建独立 CLI，不改 runtime 控制逻辑。

**Step 2: Lock the filter**

明确 thermal calibration 的聚合样本必须满足：

- `hotspot_driver_status == "ran"`

### Task 2: Red Tests For Multi-Case Calibration Aggregation

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tests/test_ablation_contract.py`

**Step 1: Write failing tests**

新增红灯测试覆盖：

- `analyze_ablation(...)` 顶层新增 `thermal_calibration`
- 只统计 `hotspot_driver_status == "ran"` 的 case
- `thermal_calibration.metrics["hotspot_peak_delta_c"]` 等字段包含：
  - `count`
  - `mean`
  - `abs_mean`
  - `max_abs`
  - `max_abs_case_id`
- `thermal_calibration.summary` 包含 eligible/excluded case 信息

**Step 2: Run focused test and verify RED**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_ablation_contract -v
```

Expected:

- 新增测试失败，因为当前 ablation summary 还没有 thermal calibration 聚合块。

### Task 3: Red Tests For Paper Calibration Artifacts

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tests/test_phase2_paper_artifacts.py`

**Step 1: Write failing tests**

新增红灯测试覆盖：

- 导出：
  - `phase2_thermal_calibration_table.csv`
  - `phase2_thermal_calibration_compare.svg`
- summary JSON 带有 `thermal_calibration`
- calibration summary 中保留：
  - `eligible_case_count`
  - `hotspot_peak_delta_c.abs_mean`
  - `hotspot_peak_delta_c.max_abs_case_id`

**Step 2: Run focused test and verify RED**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected:

- 新增测试失败，因为当前 export 还没有 calibration CSV/SVG 产物。

### Task 4: Minimal Implementation In `analyze_ablation.py`

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/analyze_ablation.py`

**Step 1: Add aggregation helpers**

最小实现包括：

- 单值 numeric 聚合 helper
- case 过滤 helper
- `thermal_calibration.cases`
- `thermal_calibration.metrics`
- `thermal_calibration.summary`

**Step 2: Keep compatibility**

确认原有顶层字段保持不变，只新增 `thermal_calibration`。

**Step 3: Run focused test and verify GREEN**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_ablation_contract -v
```

Expected:

- PASS

### Task 5: Minimal Implementation In `export_phase2_paper_artifacts.py`

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/export_phase2_paper_artifacts.py`

**Step 1: Extend summary payload**

把 ablation summary 中的 `thermal_calibration` 带进 exported summary。

**Step 2: Add calibration exports**

最小实现包括：

- `phase2_thermal_calibration_table.csv`
- `phase2_thermal_calibration_compare.svg`
- `outputs` 中增加上述路径

**Step 3: Run focused test and verify GREEN**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected:

- PASS

### Task 6: Regression Verification

**Files:**
- No code changes expected

**Step 1: Run targeted regression**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_ablation_contract \
  snn3dexp.tests.test_phase2_paper_artifacts \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_hotspot_driver -v
```

Expected:

- PASS

### Task 7: Append Progress Log

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Append Phase 6 progress**

追加记录：

- 新增 `thermal_calibration` 聚合块
- 新增 calibration CSV/SVG 产物
- 验证命令与结果
- 下一步 RC 标定 TODO

**Step 2: Re-check constraints**

确认：

- 没有改 runtime adaptive 决策源
- 没有删除现有导出产物
- `TECH_PROGRESS.md` 只 append，未覆盖旧内容
