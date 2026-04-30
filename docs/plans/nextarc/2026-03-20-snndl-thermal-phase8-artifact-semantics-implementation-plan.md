# SnnDL Thermal Phase8 Artifact Semantics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 统一 runtime/phase2 热语义，补齐 `case_role/control_mode/runtime_enabled` 标签，增加 calibration 分组统计，并产出独立 thermal input 准备工件。

**Architecture:** 以 `run_case.py` 和 `runtime/policy.py` 统一 artifact 语义，以 `analyze_ablation.py` 汇总语义标签、thermal input provenance 和 grouped calibration，再由 `export_phase2_paper_artifacts.py` 对外导出新的结构和表图。独立 thermal input 准备通过新增轻量工具生成 report/manifest，不改现有 HotSpot sidecar 路径。

**Tech Stack:** Python 3、`unittest`、JSON/CSV/SVG 文本导出、append-only `TECH_PROGRESS.md`。

---

### Task 1: Freeze Phase8 Semantics Scope

**Files:**
- Create: `/home/xgy/remote/docs/plans/nextarc/2026-03-20-snndl-thermal-phase8-artifact-semantics-implementation-plan.md`
- Reference: `/home/xgy/remote/docs/plans/nextarc/2026-03-20-snndl-thermal-phase7-status-review-and-next-direction.md`

**Step 1: Lock the semantics work**

本阶段只做：

- `runtime_summary.json` 与 `phase2_case_summary.json` 语义统一
- `runtime_enabled / control_mode / case_role` 标签补齐
- `thermal_calibration` 分组统计
- 独立 thermal input 准备 report/manifest

**Step 2: Explicitly avoid scope creep**

本阶段不做：

- HotSpot in-loop
- 新物理模型
- RC 参数自动拟合
- C++ 热路径改造

### Task 2: Red Tests For Runtime Artifact Semantics

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`

**Step 1: Write failing tests**

覆盖：

- non-adaptive `build_runtime_summary(...)` 也能输出 observability-only thermal state
- `runtime_summary.json` 与 `phase2_case_summary.json` 在 non-adaptive case 下不再分叉

**Step 2: Run focused tests to verify RED**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_run_case -v
```

### Task 3: Red Tests For Phase8 Labels And Grouped Calibration

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tests/test_ablation_contract.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_phase2_paper_artifacts.py`

**Step 1: Write failing tests**

覆盖：

- `runtime_enabled / control_mode / case_role`
- calibration `groups.control_mode`
- thermal input provenance / shared-input summary
- paper artifacts 导出新增标签字段与 grouped calibration summary

**Step 2: Run focused tests to verify RED**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_ablation_contract \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

### Task 4: Implement Runtime/Phase2 Semantics Hardening

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/runtime/policy.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/run_case.py`

**Step 1: Keep disabled policy but emit read-only observability**

- 保持 `policy = disabled`
- 保留 no-action / no-remap 行为
- 但导出：
  - `thermal_state_source`
  - `thermal_signal_source`
  - `thermal_observability`

**Step 2: Add phase2 semantics labels**

在 `phase2_case_summary` 中补齐：

- `runtime_enabled`
- `control_mode`
- `case_role`
- `thermal_input`

### Task 5: Implement Grouped Calibration And Thermal Input Preparation

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/analyze_ablation.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/export_phase2_paper_artifacts.py`
- Create: `/home/xgy/remote/snn3dexp/tools/prepare_thermal_calibration_inputs.py`

**Step 1: Extend ablation summary**

新增：

- per-case semantics labels
- thermal input provenance
- `thermal_calibration.groups.control_mode`
- `thermal_calibration.groups.case_role`
- `thermal_input_preparation`

**Step 2: Extend paper artifacts**

导出：

- 新标签字段进 summary/CSV
- calibration grouped summary 保留在 `phase2_runtime_summary.json`

**Step 3: Add preparation tool**

最小工具负责：

- 读取 `run_root + run_tag_manifest`
- 生成 per-case thermal input readiness report
- 生成仅包含 independent candidates 的 prepared manifest

### Task 6: Rebuild Phase8 Outputs

**Files:**
- Modify generated outputs under:
  - `/home/xgy/remote/snn3dexp/analysis/hotspot_real_phase6_multicase_20260320_174519_ablation.json`
  - `/home/xgy/remote/snn3dexp/analysis/paper_artifacts/hotspot_real_phase6_multicase_20260320_174519/*`
- Create:
  - `/home/xgy/remote/snn3dexp/analysis/hotspot_real_phase6_multicase_20260320_174519_thermal_input_preparation.json`
  - `/home/xgy/remote/snn3dexp/configs/run_tag_manifests/hotspot_real_phase8_independent_candidates.json`

**Step 1: Re-run analysis/export/preparation**

用真实 `hotspot_real_phase6_multicase_20260320_174519` 数据刷新：

- ablation
- paper artifacts
- thermal input preparation report/manifest

### Task 7: Regression Verification And Progress Log

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run full targeted regression**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_ablation_contract \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

**Step 2: Append progress**

记录：

- Phase8 语义统一
- calibration 分组统计
- thermal input preparation 工件
- 推荐的后续 dataset expansion 工作
