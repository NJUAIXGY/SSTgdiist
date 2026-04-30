# SnnDL Thermal Phase 4 Batch 3 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `snn3dexp` 当前的 `thermal_hotspot_adapter` 从结构化 payload 升级成真正的 HotSpot sidecar driver，能够稳定产出 HotSpot 工件、可选运行 HotSpot，并把 sidecar 摘要透传到 `platform_summary`、`phase2_case_summary` 和下游 paper artifact。

**Architecture:** 在 `snn3dexp/thermal/` 新增 `hotspot_driver.py`，输入为 `effective_config + HotSpot adapter payload + window_power_samples`，输出为 HotSpot 兼容工件与 `driver` 摘要。`platform/build_system.py` 负责调用 driver 并把结果挂到 `thermal_hotspot_adapter.driver`；`run_case.py` 与下游导出负责透传 sidecar 指标，不改变 runtime adaptive 仍基于 `online_rc_estimator` 的现有行为。

**Tech Stack:** Python 3、`unittest`、`Path` 文件工件、`snn3dexp/thermal` 数据模型、`sst_dram_si.tools.thermal_export` HotSpot 文件协议 helper、append-only progress logging。

---

### Task 1: Batch 3 Design Docs

**Files:**
- Create: `/home/xgy/remote/docs/plans/nextarc/2026-03-20-snndl-thermal-phase4-batch3-design.md`
- Create: `/home/xgy/remote/docs/plans/nextarc/2026-03-20-snndl-thermal-phase4-batch3-implementation-plan.md`

**Step 1: Write the design and plan**

把下面这些内容冻结成文档：

- sidecar driver 的职责与边界
- 2D block / 3D grid 的默认策略
- sidecar 工件目录
- `thermal_hotspot_adapter.driver` 摘要合同
- `phase2_case_summary` 与下游透传字段

**Step 2: Review against current Batch 2 outputs**

检查文档是否保持：

- hooks-first
- read-only runtime
- 向后兼容已有 `thermal_hotspot_adapter.io_summary`

### Task 2: Red Test For Standalone HotSpot Sidecar Driver

**Files:**
- Create: `/home/xgy/remote/snn3dexp/tests/test_hotspot_driver.py`
- Modify: `/home/xgy/remote/snn3dexp/thermal/__init__.py`

**Step 1: Write the failing tests**

新增红灯测试覆盖：

- 没有 HotSpot binary 时，driver 仍会生成：
  - `snndl_mesh.flp`
  - `snndl_mesh.ptrace`
  - `hotspot.config`
  - `tile_temperature_summary.csv`
  - `thermal_summary.json`
- 存在 fake HotSpot binary 时，driver 会：
  - 真正调用 binary
  - 写出 `steady.temp`
  - 回填 `tile_temperature_summary.csv`
  - 产出 `status == "ran"`

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_hotspot_driver -v
```

Expected:

- FAIL，因为 `hotspot_driver.py` 还不存在。

### Task 3: Minimal Sidecar Driver Implementation

**Files:**
- Create: `/home/xgy/remote/snn3dexp/thermal/hotspot_driver.py`
- Modify: `/home/xgy/remote/snn3dexp/thermal/__init__.py`

**Step 1: Write minimal implementation**

最小实现包含：

- `build_hotspot_sidecar(...)`
- 从 `window_power_samples` 归一化生成 `ptrace`
- 写出 `flp/config/(lcf)` 与 summary 工件
- 缺 binary 时返回 `skipped_missing_binary`
- 有 binary 时解析 `steady.temp` 回填温度

**Step 2: Run focused test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_hotspot_driver -v
```

Expected:

- PASS

### Task 4: Platform Integration And Summary Wiring

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/platform/build_system.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`

**Step 1: Write the failing integration test**

在 `test_runtime_3d_policy.py` 增加红灯测试，锁定：

- `build_platform_summary(...)` 仍保留：
  - `thermal_hotspot_adapter.io_summary`
- 同时新增：
  - `thermal_hotspot_adapter.driver`
- driver 至少透出：
  - `status`
  - `window_count`
  - `artifacts`
  - `temperature_source`

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_runtime_3d_policy -v
```

Expected:

- FAIL，因为 platform summary 还没接线 sidecar。

**Step 3: Implement minimal wiring**

- 在 `build_platform_summary(...)` 中调用 sidecar driver
- 使用 replay samples 作为优先输入
- 把结果挂到 `thermal_hotspot_adapter.driver`

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_runtime_3d_policy -v
```

Expected:

- PASS

### Task 5: Phase2 / Downstream Sidecar Export

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/run_case.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/analyze_ablation.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/export_phase2_paper_artifacts.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_phase2_paper_artifacts.py`

**Step 1: Write the failing tests**

锁定下面这些 sidecar 字段会出现在 phase2 / 下游导出里：

- `hotspot_driver_status`
- `hotspot_model_type`
- `hotspot_temperature_source`
- `hotspot_peak_temperature_c`
- `hotspot_avg_temperature_c`

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected:

- FAIL，因为 sidecar 字段还未透传。

**Step 3: Implement minimal export**

- 在 `build_phase2_case_summary(...)` 中透传 sidecar 摘要
- 在 `analyze_ablation.py` 与 `export_phase2_paper_artifacts.py` 中保留这些字段

**Step 4: Run tests to verify they pass**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected:

- PASS

### Task 6: Fresh Verification And Progress Log

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run fresh regression**

Run:

```bash
python3 -m unittest \
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

在 `/home/xgy/remote/TECH_PROGRESS.md` 末尾追加：

- 本批次改了什么
- 如何运行与验证
- sidecar 工件输出位置
- HotSpot 缺 binary / 有 binary 两条路径
- 下一步 TODO

**Step 3: Re-read requirements before closing**

确认：

- 没有做 git 写操作
- `TECH_PROGRESS.md` 只追加
- 所有改动保持兼容 Batch 2 既有字段
