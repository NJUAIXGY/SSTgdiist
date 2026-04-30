# SnnDL Thermal Phase 4 Batch 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `snn3dexp` 落地 `WindowPowerSample replay + HotSpot adapter bridge + thermal observability export + recommendation-only thermal guard contract`，同时保持 `Phase4 Batch 1` 的 hooks-first 只读边界不变。

**Architecture:** 在 `snn3dexp/thermal/` 下继续补两层桥：`replay.py` 负责读取真实 `window_power_samples.jsonl` 并重放 `online_rc_estimator`，`hotspot_adapter.py` 负责把 window power + thermal state 组织成稳定的 HotSpot I/O payload。随后在 `mesh3d_template`、`platform/build_system.py`、`runtime/policy.py`、`tools/run_case.py` 以及下游分析导出里扩展 thermal observability 与 recommendation-only action 字段。

**Tech Stack:** Python 3、`unittest`、现有 `snn3dexp/thermal` 数据模型、`sst_dram_si` thermal contract 工件、append-only progress logging。

---

### Task 1: Thermal Replay From Real WindowPowerSample

**Files:**
- Create: `/home/xgy/remote/snn3dexp/thermal/replay.py`
- Modify: `/home/xgy/remote/snn3dexp/thermal/__init__.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_thermal_state_cache.py`

**Step 1: Write the failing test**

在 `/home/xgy/remote/snn3dexp/tests/test_thermal_state_cache.py` 新增红灯测试，锁定：

- 能从 `thermal_summary.json + window_power_samples.jsonl` 读取真实 window samples；
- `replay_online_rc_thermal_trace(...)` 会按 sample 顺序生成多个 `ThermalStateCache`；
- `latest_state.source == "online_rc_estimator"`；
- 第二个窗口会体现热惯性；
- replay meta 会暴露：
  - `sample_count`
  - `block_count`
  - `trace_sources`

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_thermal_state_cache -v
```

Expected:

- FAIL，因为 replay 接口还不存在。

**Step 3: Write minimal implementation**

最小实现：

- 在 `replay.py` 中新增：
  - `load_window_power_samples(summary_path, *, window_power_samples_path=None)`
  - `replay_online_rc_thermal_trace(summary_path, *, window_power_samples_path=None, ambient_c=45.0, alpha=1000.0, beta=0.5)`
- 复用 `estimate_online_rc_state(...)` 顺序重放样本；
- 在 `__init__.py` 导出 replay 接口。

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_thermal_state_cache -v
```

Expected:

- PASS

### Task 2: HotSpot Adapter Bridge And Thermal Config

**Files:**
- Create: `/home/xgy/remote/snn3dexp/thermal/hotspot_adapter.py`
- Modify: `/home/xgy/remote/snn3dexp/thermal/__init__.py`
- Modify: `/home/xgy/remote/snn3dexp/mesh3d_template/spec.py`
- Modify: `/home/xgy/remote/snn3dexp/mesh3d_template/runtime.py`
- Modify: `/home/xgy/remote/snn3dexp/mesh3d_template/build.py`
- Modify: `/home/xgy/remote/snn3dexp/platform/build_system.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`

**Step 1: Write the failing test**

在 `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py` 增加红灯测试，锁定：

- `build_platform_summary(...)` 支持最小 `thermal` 配置段；
- 当 `thermal.mode == "window_power_replay"` 且提供 summary path 时，会新增：
  - `thermal_replay`
  - `thermal_hotspot_adapter`
  - `thermal_state_source == "online_rc_estimator"`
- HotSpot adapter 的 `io_summary.block_count/layer_count/has_power_trace` 正确。

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_runtime_3d_policy -v
```

Expected:

- FAIL，因为 thermal config 与 HotSpot adapter 还没接入。

**Step 3: Write minimal implementation**

最小实现：

- 在 `hotspot_adapter.py` 中新增：
  - `build_hotspot_adapter_payload(...)`
- 在 `spec.py/runtime.py/build.py` 中把 `thermal` 段带进 effective config；
- 在 `platform/build_system.py` 中：
  - 支持 `proxy_only` / `window_power_replay`
  - 生成 `thermal_replay`
  - 生成 `thermal_hotspot_adapter`
  - 写入 `thermal_state_source`

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_runtime_3d_policy -v
```

Expected:

- PASS

### Task 3: Runtime Observability And Recommendation-Only Guard

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/runtime/policy.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`

**Step 1: Write the failing test**

在：

- `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`
- `/home/xgy/remote/snn3dexp/tests/test_run_case.py`

新增红灯测试，锁定：

- `build_runtime_summary(...)` 会新增：
  - `thermal_observability`
  - `thermal_state_source`
  - `recommended_actions`
- `recommended_actions[*].execute` 第一版固定为 `False`
- 现有字段：
  - `policy`
  - `signal_source`
  - `thermal_guard_actions`
  - `recommended_weights`
  不应回退或改名。

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_runtime_3d_policy snn3dexp.tests.test_run_case -v
```

Expected:

- FAIL，因为 observability 与 recommended actions 还不存在。

**Step 3: Write minimal implementation**

最小实现：

- 在 `runtime/policy.py` 中补齐 observability 字段；
- 新增 recommendation-only action 列表，按当前阈值判定生成建议；
- 保持 `action_labels` 与 `thermal_guard_actions` 原语义不变。

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_runtime_3d_policy snn3dexp.tests.test_run_case -v
```

Expected:

- PASS

### Task 4: Phase2 / Ablation / Paper Artifact Thermal Observability Export

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/run_case.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/analyze_ablation.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/export_phase2_paper_artifacts.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_phase2_paper_artifacts.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`

**Step 1: Write the failing test**

新增红灯测试，锁定：

- `phase2_case_summary.json` 会包含：
  - `thermal_state_source`
  - `peak_temperature_c`
  - `avg_temperature_c`
  - `vertical_gradient_c`
  - `hotspot_block_count`
  - `hotspot_layer_count`
  - `thermal_replay_sample_count`
- `analyze_ablation.py` 会保留这些字段；
- `export_phase2_paper_artifacts.py` 导出的 runtime/thermal 行也会包含这些观测量。

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_phase2_paper_artifacts snn3dexp.tests.test_runtime_3d_policy -v
```

Expected:

- FAIL，因为 observability 还未贯通到下游导出。

**Step 3: Write minimal implementation**

最小实现：

- 在 `run_case.py` 中扩展 `phase2_case_summary` thermal/runtime 段；
- 在 `analyze_ablation.py` 与 `export_phase2_paper_artifacts.py` 中保留新增字段；
- 仅做字段透传与摘要，不引入额外执行逻辑。

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_phase2_paper_artifacts snn3dexp.tests.test_runtime_3d_policy -v
```

Expected:

- PASS

### Task 5: Verification And Progress Logging

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run focused regressions**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_thermal_consumer \
  snn3dexp.tests.test_thermal_estimator \
  snn3dexp.tests.test_thermal_state_cache \
  snn3dexp.tests.test_thermal_proxy \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected:

- All targeted tests PASS.

**Step 2: Re-run thermal tool regressions that must not regress**

Run:

```bash
python3 -m unittest \
  sst_dram_si.tools.test_thermal_export \
  sst_dram_si.tools.test_analyze_thermal_runs \
  sst_dram_si.tools.test_summarize_thermal_analysis \
  sst_dram_si.tools.test_export_thermal_sweep_report \
  sst_dram_si.tools.test_generate_thermal_sweep_report \
  sst_dram_si.tools.test_run_thermal_contract_suite -v
```

Expected:

- All thermal tool tests PASS.

**Step 3: Append progress log**

只在 `/home/xgy/remote/TECH_PROGRESS.md` 末尾追加：

- `WindowPowerSample replay`
- `HotSpot adapter bridge`
- `thermal observability export`
- `recommendation-only thermal guard`

## Execution Notes

- 严格遵守 `@test-driven-development`
- 严格遵守 `@verification-before-completion`
- 当前用户已经明确要求“开工”，因此文档写完后直接在本会话继续实现，不再额外等待。
