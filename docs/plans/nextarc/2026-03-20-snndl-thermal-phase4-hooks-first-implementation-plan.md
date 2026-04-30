# SnnDL Thermal Phase 4 Hooks-First Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不引入真实 runtime 热行为闭环的前提下，为 `snn3dexp` 落地统一的 `ThermalConsumerHooks + thermal signals + online_rc_estimator mock + runtime summary read-only bridge`。

**Architecture:** 继续保持 `Phase3` 冻结好的热 contract 不变，在 `snn3dexp/thermal/` 新增三层只读桥：`signals.py` 负责从 `ThermalStateCache` 提取统一热信号，`consumer.py` 负责组装 consumer snapshot，`estimator.py` 负责把 `WindowPowerSample` 转成 `online_rc_estimator` 来源的 `ThermalStateCache`。随后让 `runtime.policy` 和 `platform.build_system` 优先消费统一 thermal signals，但保留对现有 `thermal_summary` 字段的 fallback。

**Tech Stack:** Python 3、`unittest`、现有 `snn3dexp/thermal` 数据模型、`snn3dexp/runtime/policy.py`、`snn3dexp/platform/build_system.py`、append-only progress logging。

---

### Task 1: Thermal Signals And Consumer Snapshot

**Files:**
- Create: `/home/xgy/remote/snn3dexp/thermal/signals.py`
- Create: `/home/xgy/remote/snn3dexp/thermal/consumer.py`
- Modify: `/home/xgy/remote/snn3dexp/thermal/__init__.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_thermal_consumer.py`

**Step 1: Write the failing test**

在 `/home/xgy/remote/snn3dexp/tests/test_thermal_consumer.py` 写红灯测试，锁定：

- `get_runtime_thermal_signals(thermal_state)` 能从 `ThermalStateCache` 导出：
  - `peak_temperature_c`
  - `avg_temperature_c`
  - `hotspot_block_count`
  - `hotspot_layer_count`
  - `vertical_gradient_c`
  - `top_layer_peak_c`
  - `bottom_layer_peak_c`
- `build_thermal_consumer_snapshot(thermal_state)` 会返回：
  - `sample_id`
  - `source`
  - `block_temperatures`
  - `layer_temperatures`
  - `signals`

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_thermal_consumer -v
```

Expected:

- FAIL，因为 `consumer.py` / `signals.py` 和导出接口还不存在。

**Step 3: Write minimal implementation**

最小实现：

- 在 `signals.py` 中新增：
  - `get_runtime_thermal_signals(thermal_state, *, hotspot_threshold_c=0.0)`
- 在 `consumer.py` 中新增：
  - `build_thermal_consumer_snapshot(thermal_state, *, hotspot_threshold_c=0.0)`
- 在 `__init__.py` 中导出这些接口。

第一版只使用已有 `ThermalStateCache.layers/blocks` 计算聚合值，不引入任何行为决策逻辑。

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_thermal_consumer -v
```

Expected:

- PASS

### Task 2: Online RC Estimator Mock

**Files:**
- Create: `/home/xgy/remote/snn3dexp/thermal/estimator.py`
- Modify: `/home/xgy/remote/snn3dexp/thermal/__init__.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_thermal_estimator.py`

**Step 1: Write the failing test**

在 `/home/xgy/remote/snn3dexp/tests/test_thermal_estimator.py` 写红灯测试，锁定：

- `estimate_online_rc_state(window_power_sample, ...)` 能从一个最小 `WindowPowerSample` 构造 `ThermalStateCache`
- `source == "online_rc_estimator"`
- `sample_id` 与输入 sample 一致
- block 温度会随着 `power_w` 增大而增大
- layer 温度按 block 聚合出 `avg/peak/min`
- 若给出 `previous_state`，第二窗口温度会带入热惯性

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_thermal_estimator -v
```

Expected:

- FAIL，因为 `estimator.py` 和对应导出接口还不存在。

**Step 3: Write minimal implementation**

最小实现：

- 在 `estimator.py` 中新增：
  - `estimate_online_rc_state(window_power_sample, *, previous_state=None, ambient_c=45.0, alpha=1000.0, beta=0.5)`
- 使用一阶近似：

```text
next_temp = ambient_c + alpha * power_w + beta * previous_delta
```

- 输出结构保持为 `ThermalStateCache`

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_thermal_estimator -v
```

Expected:

- PASS

### Task 3: Runtime Read-Only Thermal Bridge

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/runtime/policy.py`
- Modify: `/home/xgy/remote/snn3dexp/platform/build_system.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`

**Step 1: Write the failing test**

先在：

- `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`
- `/home/xgy/remote/snn3dexp/tests/test_run_case.py`

写红灯测试，锁定：

- `build_runtime_summary(...)` 新增可选 `thermal_state` / `thermal_signals` 参数后，会优先消费 hooks/signals
- 若没传入这些参数，仍保留对旧 `thermal_summary` 字段的 fallback
- `build_platform_summary(...)` 会新增：
  - `thermal_consumer_snapshot`
  - 并把 derived thermal signals 传给 runtime summary
- 现有 `adaptive_3d` 行为断言：
  - `policy`
  - `signal_source`
  - `thermal_guard_actions`
  不应回退或改名

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_runtime_3d_policy snn3dexp.tests.test_run_case -v
```

Expected:

- FAIL，因为 runtime 侧还没有统一 thermal signals / consumer snapshot 接桥。

**Step 3: Write minimal implementation**

最小实现：

- 在 `runtime/policy.py` 中：
  - 新增可选参数 `thermal_state=None, thermal_signals=None`
  - 若传入 `thermal_signals`，优先消费其 `vertical_gradient_c / peak_temperature_c` 等派生值
  - 无 signals 时回退到旧 `thermal_summary`
- 在 `platform/build_system.py` 中：
  - 基于 `thermal_summary` 构造一个最小 replay-style `ThermalStateCache` 或 consumer snapshot
  - 写入 `platform_summary["thermal_consumer_snapshot"]`
  - 把 `get_runtime_thermal_signals(...)` 输出传给 `build_runtime_summary(...)`

第一版只读接桥，不新增执行动作。

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_runtime_3d_policy snn3dexp.tests.test_run_case -v
```

Expected:

- PASS

### Task 4: Verification And Progress Logging

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run focused thermal/runtime regressions**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_thermal_consumer \
  snn3dexp.tests.test_thermal_estimator \
  snn3dexp.tests.test_thermal_state_cache \
  snn3dexp.tests.test_thermal_proxy \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_run_case -v
```

Expected:

- All targeted tests PASS.

**Step 2: Re-run existing thermal tool regressions that must not regress**

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

**Step 3: Optional lightweight smoke through existing runtime-adaptive path**

如果无需真实 SST，可至少验证：

```bash
python3 -m unittest snn3dexp.tests.test_runtime_3d_policy snn3dexp.tests.test_run_case -v
```

并确认：

- `thermal_consumer_snapshot`
- `runtime.signal_source`
- `thermal_guard_actions`

都仍存在。

**Step 4: Append progress log**

只在 `/home/xgy/remote/TECH_PROGRESS.md` 末尾 append：

- 新增 `ThermalConsumerHooks`
- 新增 `thermal signals`
- 新增 `online_rc_estimator`
- 新增 runtime read-only thermal bridge

## Execution Notes

- 严格遵守 `@test-driven-development`
- 严格遵守 `@verification-before-completion`
- 当前用户已经明确要求“开始落地代码”，因此本计划保存后直接在本会话按 `executing-plans` 执行第一批任务，不再额外等待执行方式确认。
