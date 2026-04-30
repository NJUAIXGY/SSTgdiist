# SnnDL Thermal Phase 5 Contract/Stack/Calibration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `snn3dexp` 当前已经跑通的 HotSpot sidecar 链路推进到“正式可维护”的下一阶段，完成配置合同硬化、显式 3D stack 语义补全，以及 RC vs HotSpot 偏差导出。

**Architecture:** `mesh3d_template/spec.py` 负责前置校验与合同透传；`thermal/hotspot_driver.py` 负责 layer/package 语义与 sidecar summary 扩展；`run_case.py`、`analyze_ablation.py`、`export_phase2_paper_artifacts.py` 负责偏差字段贯通。保持 runtime 决策仍然只消费 `online_rc_estimator`，HotSpot 继续 sidecar-only。

**Tech Stack:** Python 3、`unittest`、HotSpot sidecar 工件、append-only `TECH_PROGRESS.md`。

---

### Task 1: Phase 5 Design And Plan Docs

**Files:**
- Create: `/home/xgy/remote/docs/plans/nextarc/2026-03-20-snndl-thermal-phase5-contract-stack-calibration-design.md`
- Create: `/home/xgy/remote/docs/plans/nextarc/2026-03-20-snndl-thermal-phase5-contract-stack-calibration-implementation-plan.md`

**Step 1: Freeze the scope**

把下面 3 条主线写清楚并冻结：

- HotSpot grid/config 合同前置校验
- `thermal.layers` / `hotspot_package` 正式合同
- runtime vs HotSpot delta 字段导出

**Step 2: Re-check compatibility**

确认设计保持：

- hooks-first
- runtime read-only
- backward compatibility for existing summary fields

### Task 2: Red Tests For Thermal Contract Hardening

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tests/test_mesh3d_template_contract.py`

**Step 1: Write failing tests**

新增红灯测试覆盖：

- `thermal.model_type=grid` 且 `grid_cols=48` 时，`build_effective_config(...)` 抛 `SpecError`
- `thermal.hotspot_package` 会被完整透传进 `effective_config["thermal"]`

**Step 2: Run focused test and verify RED**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_mesh3d_template_contract -v
```

Expected:

- 新增测试失败，失败原因为当前还没有做 grid power-of-two 校验与 package 透传断言。

### Task 3: Red Tests For Driver Stack Semantics

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tests/test_hotspot_driver.py`

**Step 1: Write failing tests**

新增红灯测试覆盖：

- 显式 `thermal.layers` 包含 passive `tim` 层时，summary 会保留：
  - `layers`
  - `source_layer_index`
  - `normalized_layer_index`
- `tile_temperature_summary.csv` 新增：
  - `source_layer_index`
  - `normalized_layer_index`
- 显式 `thermal.hotspot_package` 时：
  - `hotspot.config` 使用配置值
  - summary `hotspot_package` 与配置一致

**Step 2: Run focused test and verify RED**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_hotspot_driver -v
```

Expected:

- 新增测试失败，当前 driver 还未暴露新 layer/package 合同。

### Task 4: Red Tests For RC vs HotSpot Delta Export

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_phase2_paper_artifacts.py`

**Step 1: Write failing tests**

新增红灯测试覆盖：

- `build_phase2_case_summary(...)` 输出：
  - `hotspot_peak_delta_c`
  - `hotspot_avg_delta_c`
  - `hotspot_block_delta`
  - `hotspot_layer_delta`
- paper runtime focus metrics 透传这些 delta 字段

**Step 2: Run focused tests and verify RED**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected:

- 新增测试失败，因为 delta 字段还未贯通。

### Task 5: Minimal Implementation For Contract Hardening

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/mesh3d_template/spec.py`

**Step 1: Implement thermal validation helper**

最小实现包括：

- `grid_rows/grid_cols` power-of-two 校验
- `hotspot_package` 正值校验
- `hotspot_package` 透传进 `thermal_payload`

**Step 2: Run focused tests and verify GREEN**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_mesh3d_template_contract -v
```

Expected:

- PASS

### Task 6: Minimal Implementation For Driver Stack Semantics

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/thermal/hotspot_driver.py`

**Step 1: Implement minimal layer/package extensions**

最小实现包括：

- 解析 `thermal.hotspot_package`
- summary 暴露 normalized layer metadata
- CSV 暴露 `source_layer_index` / `normalized_layer_index`
- `hotspot.config` 使用 package override

**Step 2: Run focused tests and verify GREEN**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_hotspot_driver -v
```

Expected:

- PASS

### Task 7: Minimal Implementation For Delta Export

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/run_case.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/analyze_ablation.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/export_phase2_paper_artifacts.py`

**Step 1: Implement delta fields**

最小实现包括：

- phase2 summary 增量字段
- ablation summary 透传
- paper runtime focus metrics 透传

**Step 2: Run focused tests and verify GREEN**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected:

- PASS

### Task 8: Fresh Verification And Progress Log

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run fresh regression**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_mesh3d_template_contract \
  snn3dexp.tests.test_hotspot_driver \
  snn3dexp.tests.test_thermal_consumer \
  snn3dexp.tests.test_thermal_estimator \
  snn3dexp.tests.test_thermal_state_cache \
  snn3dexp.tests.test_thermal_proxy \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected:

- PASS

**Step 2: Append technical progress**

在 `TECH_PROGRESS.md` 末尾追加：

- 本轮实现的 3 条主线
- 如何验证
- 新增输出字段与产物语义
- 后续 TODO

**Step 3: Re-check constraints**

确认：

- 没有做任何 git 写操作
- `TECH_PROGRESS.md` 只 append
- runtime 决策源仍然是 `online_rc_estimator`

