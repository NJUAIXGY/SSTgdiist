# SNN3D Architecture Summary Next-Step Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把刚落地的 `phase2_case_summary["architecture"]` 从单 case 摘要推进成下一阶段 3D chip 主分析面，并基于它完成热 / NoC / memory / barrier 的联合比较与 runtime 控制输入升级。

**Architecture:** 继续坚持 `phase2_case_summary["architecture"]` 作为单 case 的统一聚合层，不再让 downstream tools 分散地从 `route_memory_joint`、`runtime_summary`、`thermal_summary` 手工拼字段。下一阶段先做三个收敛动作：先把 `architecture` 下沉到 ablation / codesign surface / matrix；再补齐 tier/stack/layer 热语义；最后让 runtime policy 读取联合 coupling 指标，先 observe-only，再进入 execute。

**Tech Stack:** Python 3, `unittest`, `snn3dexp/tools/run_case.py`, `snn3dexp/tools/analyze_ablation.py`, `snn3dexp/tools/export_memory_nmc_codesign_surface.py`, `snn3dexp/tools/run_memory_nmc_codesign_matrix.py`, `snn3dexp/runtime/policy.py`, `snn3dexp/tools/refresh_thermal_outputs.py`, HotSpot sidecar artifacts

---

## Priority Decision

### Recommended path: `architecture surface -> thermal layering -> runtime coupling`

这是当前最值得押注的主线，原因有三点：

1. `phase2_case_summary["architecture"]` 已经存在，说明“统一分析主语义”不再是设计问题，而是推广问题。
2. 当前仓库最缺的不是新的热点分数，而是把 `route/memory/thermal/barrier` 放到同一比较平面后，稳定解释 case 差异与控制动作。
3. runtime adaptive 如果继续只看 `temperature / vertical_link_pressure / stack_hotspot_penalty`，会忽略我们刚补出来的 controller deficit 与 barrier stall 信号，热控制会继续停留在“只看温度”的窄语义。

### Not recommended as immediate mainline

1. 直接优先做 `synapse-native route source semantics`
   - 重要，但更适合作为本轮计划完成后的下一主线。
   - 当前如果先做这条，会让 `route kernel`、`memory/NMC compare`、`thermal execute loop` 三条线重新并发发散。

2. 直接优先做更细 physical realism
   - 例如 TSV/MIV、电源/时钟、更多 package 细节。
   - 当前缺口不是 realism 选项不够，而是现有热/路由/内存统计还没有形成统一决策语义。

3. 直接做 per-cycle thermal control
   - 当前 runtime 是 window 级控制，继续保持这一层级最合理。
   - 应先把 `architecture` 级别的联合指标用好，再考虑更细时间尺度。

## Wave Boundary

### This wave must finish

1. `architecture` 进入 multicase summary / codesign surface / matrix rows。
2. `architecture.thermal_pressure` 能表达 tier/layer/stack 的热分布摘要，而不是只有全局温度与 hotspot count。
3. runtime policy 支持读取 `architecture.coupling` 风格的联合压力信号。
4. 至少一轮 fresh canonical matrix / fixed-step / thermal refresh 验证走通。

### This wave explicitly defers

1. route kernel 从 bootstrap 走向 `synapse-native source semantics`
2. packet format / router feature 扩写
3. per-cycle thermal feedback
4. 更细工艺/封装 realism

### Task 1: Promote `architecture` Into Ablation / Baseline Payloads

**Files:**
- Modify: `snn3dexp/tools/analyze_ablation.py`
- Modify: `snn3dexp/tests/test_phase2_baseline_suite.py`
- Modify: `snn3dexp/tests/test_run_memory_nmc_codesign_matrix.py`

**Step 1: Write the failing tests**

在 `test_phase2_baseline_suite.py` 新增断言，锁定 `analyze_ablation()` 返回的每个 case payload 都会带出：

```python
self.assertIn("architecture_summary", case)
self.assertIn("observability", case["architecture_summary"])
self.assertIn("coupling", case["architecture_summary"])
self.assertIn("hotspot_readiness", case["architecture_summary"])
```

在 `test_run_memory_nmc_codesign_matrix.py` 新增断言，锁定 mainline/matrix summary 里能透出 `architecture_summary_available` 或同义字段。

**Step 2: Run tests to verify they fail**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_phase2_baseline_suite \
  snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v
```

Expected: FAIL，提示 `architecture_summary` 尚未下沉到 ablation/matrix 层。

**Step 3: Write minimal implementation**

- 在 `analyze_ablation.py` 读取 `phase2_case_summary["architecture"]`
- case payload 显式新增：
  - `architecture_summary`
  - `architecture_summary_available`
- 对无该字段的历史 case 保持兼容：
  - 返回空 dict
  - `architecture_summary_available = False`

**Step 4: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_phase2_baseline_suite \
  snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v
```

Expected: PASS

### Task 2: Add `architecture` Metrics To Codesign Surface / Matrix Rows

**Files:**
- Modify: `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
- Modify: `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- Modify: `snn3dexp/tools/run_memory_nmc_codesign_matrix.py`
- Modify: `snn3dexp/tests/test_memory_nmc_codesign_surface.py`
- Modify: `snn3dexp/tests/test_export_memory_nmc_route_runtime_diff.py`

**Step 1: Write the failing tests**

在 `test_memory_nmc_codesign_surface.py` 锁定新 surface row 直接带出：

```python
self.assertIn("route_thermal_coupling_score", row)
self.assertIn("memory_thermal_coupling_proxy", row)
self.assertIn("memory_barrier_coupling_proxy", row)
self.assertIn("closed_loop_candidate", row)
```

在 `test_export_memory_nmc_route_runtime_diff.py` 锁定 diff summary 对这些字段产出 delta：

```python
self.assertIn("route_thermal_coupling_score_delta", compare_row)
self.assertIn("memory_barrier_coupling_proxy_delta", compare_row)
```

**Step 2: Run tests to verify they fail**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_memory_nmc_codesign_surface \
  snn3dexp.tests.test_export_memory_nmc_route_runtime_diff -v
```

Expected: FAIL，提示新字段尚未进入 surface/diff。

**Step 3: Write minimal implementation**

- `export_memory_nmc_codesign_surface.py`
  - 优先从 `payload["architecture_summary"]` 投影 row 字段
  - 历史 case 缺失时回退到旧字段
- `export_memory_nmc_route_runtime_diff.py`
  - 对新字段进入 delta compare
- `run_memory_nmc_codesign_matrix.py`
  - 把新字段纳入 `matrix_rows` 和 summary provenance

**Step 4: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_memory_nmc_codesign_surface \
  snn3dexp.tests.test_export_memory_nmc_route_runtime_diff \
  snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v
```

Expected: PASS

### Task 3: Enrich `architecture.thermal_pressure` With Tier / Stack / Layer Hotspot Semantics

**Files:**
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/tools/refresh_thermal_outputs.py`
- Modify: `snn3dexp/tests/test_run_case.py`
- Modify: `snn3dexp/tests/test_refresh_thermal_outputs.py`

**Step 1: Write the failing tests**

在 `test_run_case.py` 新增断言，锁定 `architecture["thermal_pressure"]` 不只含全局温度，还至少包含：

```python
self.assertIn("hottest_layer_id", architecture["thermal_pressure"])
self.assertIn("hottest_layer_peak_c", architecture["thermal_pressure"])
self.assertIn("layer_hotspot_distribution", architecture["thermal_pressure"])
self.assertIn("stack_hotspot_hint", architecture["thermal_pressure"])
```

在 `test_refresh_thermal_outputs.py` 锁定 thermal refresh 后，`phase2_case_summary["architecture"]["thermal_pressure"]` 会随着 thermal snapshot 更新。

**Step 2: Run tests to verify they fail**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_refresh_thermal_outputs -v
```

Expected: FAIL，提示新的层级热摘要不存在或 refresh 不更新它。

**Step 3: Write minimal implementation**

- 在 `run_case.py` 的 `_build_phase2_architecture_summary()` 中消费：
  - `platform_summary["thermal_consumer_snapshot"]["layer_temperatures"]`
  - `platform_summary["thermal_consumer_snapshot"]["block_temperatures"]`
- 生成：
  - `hottest_layer_id`
  - `hottest_layer_peak_c`
  - `layer_hotspot_distribution`
  - `stack_hotspot_hint`
  - `has_layer_temperatures`
  - `has_block_temperatures`
- 在 `refresh_thermal_outputs.py` 复用 `build_phase2_case_summary()`，确保 refresh 路径自动重建这些字段。

**Step 4: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_refresh_thermal_outputs -v
```

Expected: PASS

### Task 4: Upgrade Runtime Policy To Read Architecture Coupling Signals In Observe-Only Mode

**Files:**
- Modify: `snn3dexp/runtime/policy.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/tests/test_runtime_3d_policy.py`
- Modify: `snn3dexp/tests/test_run_case.py`

**Step 1: Write the failing tests**

在 `test_runtime_3d_policy.py` 新增测试，锁定当：

- `memory_barrier_coupling_proxy` 高
- `memory_thermal_coupling_proxy` 高
- 但 `observe_only = True`

时，runtime summary 应返回：

```python
self.assertIn("rebalance_home_route", summary["recommended_actions"])
self.assertIn("raise_vertical_penalty", summary["recommended_actions"])
self.assertFalse(summary["executed_control"])
```

同时断言新 threshold 参数被识别，例如：

```python
"runtime_memory_barrier_coupling_threshold"
"runtime_memory_thermal_coupling_threshold"
```

**Step 2: Run tests to verify they fail**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_run_case -v
```

Expected: FAIL，提示 policy 尚未读取联合 coupling 指标。

**Step 3: Write minimal implementation**

- `runtime/policy.py`
  - 新增 coupling threshold 读取
  - 在现有 thermal decision 之外补：
    - `memory_thermal_coupling_proxy`
    - `memory_barrier_coupling_proxy`
    - 可选 `route_thermal_coupling_score`
- `run_case.py`
  - 在 phase2 summary 中把 runtime 使用到的 coupling 决策来源回写到 `runtime.recommended_actions` / `runtime.recommended_weights`

**Step 4: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_run_case -v
```

Expected: PASS

### Task 5: Enable Architecture-Coupled Execute Path For Canonical Runtime Cases

**Files:**
- Modify: `snn3dexp/runtime/policy.py`
- Modify: `snn3dexp/tools/refresh_thermal_outputs.py`
- Modify: `snn3dexp/tests/test_runtime_3d_policy.py`
- Modify: `snn3dexp/tests/test_memory_nmc_codesign_surface.py`
- Modify: `snn3dexp/tests/test_phase2_paper_artifacts.py`

**Step 1: Write the failing tests**

锁定当 execute mode 打开且 coupling 超阈值时：

```python
self.assertTrue(summary["executed_control"])
self.assertGreater(summary["homeroute_adjustment_count"], 0)
self.assertGreater(summary["thermal_guard_actions"], 0)
```

并在 `test_memory_nmc_codesign_surface.py` / `test_phase2_paper_artifacts.py` 锁定：

- `architecture.hotspot_readiness.closed_loop_candidate`
- `runtime_control` 比较项能区分 “温度触发” 与 “coupling 触发”

**Step 2: Run tests to verify they fail**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_memory_nmc_codesign_surface \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected: FAIL

**Step 3: Write minimal implementation**

- 保持 window-level execute，不扩到 per-cycle
- executed path 仅复用现有动作：
  - `raise_vertical_penalty`
  - `rebalance_home_route`
- 新增 action provenance：
  - `decision_source = "architecture_coupling"`
  - `trigger_signals = [...]`

**Step 4: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_memory_nmc_codesign_surface \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected: PASS

### Task 6: Fresh Canonical Validation And Status Refresh

**Files:**
- Modify: `TECH_PROGRESS.md` (append only)
- Update outputs under:
  - `snn3dexp/analysis/codesign_matrix/`
  - `snn3dexp/analysis/full_3d_runtime_adaptive/`
  - `snn3dexp/analysis/full_3d_snn_window_bundle_v3/`

**Step 1: Run focused regressions**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_run_case \
  snn3dexp.tests.test_phase2_baseline_suite \
  snn3dexp.tests.test_memory_nmc_codesign_surface \
  snn3dexp.tests.test_export_memory_nmc_route_runtime_diff \
  snn3dexp.tests.test_run_memory_nmc_codesign_matrix \
  snn3dexp.tests.test_runtime_3d_policy \
  snn3dexp.tests.test_refresh_thermal_outputs -v
```

Expected: PASS

**Step 2: Run fresh compose/runtime probes**

Run:

```bash
cd "/home/xgy/remote" && python3 snn3dexp/tools/run_memory_nmc_codesign_matrix.py \
  --run-root snn3dexp/runs \
  --run-tag archsum_matrix_smoke \
  --phase2-mainline
```

Run:

```bash
cd "/home/xgy/remote" && python3 snn3dexp/tools/refresh_thermal_outputs.py \
  --run-root snn3dexp/runs \
  --run-tag archsum_matrix_smoke
```

Expected: 新产物中的 `phase2_case_summary.json`、surface summary、matrix rows 都带出 `architecture` 相关字段。

**Step 3: Append status**

- 仅追加更新 `TECH_PROGRESS.md`
- 明确记录：
  - `architecture` surface 是否已贯通
  - `tier/stack/layer` 热摘要是否已到位
  - runtime 是否已进入 `architecture-coupled execute`

## After This Wave

当以上 6 个任务完成后，下一主线才切回：

1. `route kernel` 从 `edges_csv / legacy-built` bootstrap 走向 `synapse-native source semantics`
2. 在更真实 source semantics 上重新评估：
   - `route_thermal_coupling_score`
   - `memory_thermal_coupling_proxy`
   - `memory_barrier_coupling_proxy`
3. 再决定是否需要更细粒度的热控制时间尺度

## Repo Policy Note

本计划刻意不包含任何 `git commit/push/branch` 步骤，遵守当前仓库 policy。

## Status Update (2026-03-25)

### Completed In This Wave

1. `architecture_summary` 已下沉到 `analyze_ablation`、baseline payload、matrix provenance。
2. `architecture` 指标已接入 `export_memory_nmc_codesign_surface.py`、`export_memory_nmc_route_runtime_diff.py` 与 mainline matrix rows。
3. `architecture.thermal_pressure` 已补齐 `tier / stack / layer` 热摘要，包括：
   - `hottest_layer_id`
   - `hottest_layer_peak_c`
   - `layer_hotspot_distribution`
   - `tier_hotspot_summary`
   - `stack_hotspot_hint`
4. `runtime/policy.py` 已支持读取联合 coupling 指标，并区分：
   - observe-only 推荐
   - execute-mode action provenance
5. canonical runtime artifacts 已补齐 execute path provenance：
   - `control_decision_source`
   - `control_trigger_signals`
   - `executed_control`
6. `export_phase2_paper_artifacts.py` 已消费这些字段，并把它们写入：
   - `runtime_focus_metrics`
   - `runtime_comparisons`
   - `canonical_metric_planes["thermal_runtime_control"]`

### Fresh Validation Snapshot

- 全量 focused regressions：
  - `python3 -m unittest snn3dexp.tests.test_run_case snn3dexp.tests.test_phase2_baseline_suite snn3dexp.tests.test_memory_nmc_codesign_surface snn3dexp.tests.test_export_memory_nmc_route_runtime_diff snn3dexp.tests.test_run_memory_nmc_codesign_matrix snn3dexp.tests.test_runtime_3d_policy snn3dexp.tests.test_refresh_thermal_outputs -v`
  - `89 tests`, `OK`
- fresh matrix/mainline：
  - `python3 snn3dexp/tools/run_memory_nmc_codesign_matrix.py --matrix-label archsum_matrix_smoke --phase2-mainline`
  - 产物：
    - `snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/memory_nmc_codesign_matrix_summary.json`
    - `snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/codesign_surface/memory_nmc_codesign_surface_summary.json`
    - `snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/phase2_artifacts/phase2_runtime_summary.json`
  - 关键信号：
    - `baseline_ablation.architecture_summary_case_count = 6`
    - `codesign_surface.architecture_signal_row_count = 8`
- fresh canonical runtime smoke：
  - `python3 snn3dexp/tools/run_case.py full_3d_runtime_adaptive --run-tag archsum_matrix_smoke --sst-smoke --stop-at 20us`
  - 产物：
    - `snn3dexp/analysis/full_3d_runtime_adaptive/archsum_matrix_smoke/runtime_summary.json`
    - `snn3dexp/analysis/full_3d_runtime_adaptive/archsum_matrix_smoke/runtime_control_next_window.json`
    - `snn3dexp/analysis/full_3d_runtime_adaptive/archsum_matrix_smoke/phase2_case_summary.json`
  - 当前真实 smoke 结果：
    - `executed_control = true`
    - `control_decision_source = "hybrid"`
    - `control_trigger_signals = ["route_memory_overlap", "stack_hotspot_penalty", "vertical_link_pressure"]`
    - `architecture.hotspot_readiness.closed_loop_candidate = true`
    - `architecture.coupling.route_thermal_coupling_score = 0.221875...`
    - `memory_thermal_coupling_proxy = 0`
    - `memory_barrier_coupling_proxy = 0`
- thermal refresh：
  - `python3 snn3dexp/tools/refresh_thermal_outputs.py --run-root snn3dexp/runs --run-tag archsum_matrix_smoke`
  - 已刷新 case：
    - `baseline_2d`
    - `full_3d`
    - `full_3d_mapping`
    - `full_3d_monolithic_proxy`
    - `full_3d_runtime_adaptive`
    - `full_3d_snn_window`
    - `full_3d_snn_window_monolithic_proxy`
    - `full_3d_thermal_guard`
    - `full_3d_tile_bundle_v3`
    - `memory_only_3d`
    - `noc_only_3d`

### Current Interpretation

- 代码和 artifact 链已经支持 `architecture-coupled execute path`，并且 canonical runtime case 的 `runtime_control_next_window.json` 不再丢 `executed_control`。
- 当前 `archsum_matrix_smoke` 的真实 20us canonical runtime smoke 里，联合 memory/barrier coupling proxy 仍为 `0`，所以真实控制决策还没有被 `architecture_coupling` 主导，而是由既有 `route_memory_overlap + vertical_link_pressure (+ stack_hotspot_penalty)` 触发。
- 这不再是“链路没接上”的问题，而是“当前 canonical smoke 负载尚未把 controller deficit / barrier stall 推到 coupling execute 阈值”。

### Next Direction

1. 为 `full_3d_runtime_adaptive` 设计一条更能拉高 `memory_thermal_coupling_proxy / memory_barrier_coupling_proxy` 的 canonical stress path。
2. 决定是否要把 `full_3d_runtime_adaptive` 正式纳入 matrix mainline 的 baseline/runtime overlay family，而不只是在单 case smoke 中验证。
3. 如果后续仍希望在轻 smoke 中看到 execute 来源从 `hybrid` 转向 `architecture_coupling`，应优先提高 controller deficit / step-gate stall，而不是继续单纯拉高温度。

## Status Refresh (2026-03-25, fresh closure)

### What is now confirmed

1. 六个主任务已经完成闭环，不再停留在“单 case 局部通”：
   - `architecture_summary` 已进入 ablation / surface / matrix。
   - `architecture` coupling 指标已进入 surface 与 matrix rows。
   - `architecture.thermal_pressure` 已带 `tier/layer/stack` 热摘要。
   - `runtime/policy.py` 已读取 `memory_thermal_coupling_proxy`、`memory_barrier_coupling_proxy` 这类联合指标。
   - execute path 已接进 canonical runtime case。
   - fresh canonical validation 已成功走通。
2. `full_3d_runtime_adaptive` 现在已经是 mainline traffic family 成员，而不是单独的临时 smoke case。
3. `full_3d_runtime_adaptive` 的 mainline stop window 已被正式固定为 `2us`，避免继续被 traffic baseline 的 `20us` 拖长。

### Fresh artifacts that should be treated as the current truth

- Matrix summary:
  - `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/memory_nmc_codesign_matrix_summary.json`
- Codesign surface:
  - `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/codesign_surface/memory_nmc_codesign_surface_summary.json`
- Runtime focus summary:
  - `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/phase2_artifacts/phase2_runtime_summary.json`
- Adaptive canonical case:
  - `/home/xgy/remote/snn3dexp/analysis/full_3d_runtime_adaptive/archsum_matrix_smoke/phase2_case_summary.json`

### Fresh validation results

- fresh matrix 命令：

```bash
cd "/home/xgy/remote" && python3 "/home/xgy/remote/snn3dexp/tools/run_memory_nmc_codesign_matrix.py" \
  --matrix-label archsum_matrix_smoke --phase2-mainline
```

- fresh matrix 结果：
  - `traffic_case_ids` 已包含 `full_3d_runtime_adaptive`
  - `traffic_stop_at_by_case.full_3d_runtime_adaptive = "2us"`
  - `baseline_ablation.architecture_summary_case_count = 7`
  - `codesign_surface.architecture_signal_row_count = 8`

- fresh runtime focus 中，`full_3d_runtime_adaptive` 的关键值：
  - `executed_control = true`
  - `control_decision_source = "hybrid"`
  - `control_trigger_signals = ["memory_barrier_coupling_proxy", "memory_thermal_coupling_proxy", "route_memory_overlap", "vertical_link_pressure"]`
  - `route_thermal_coupling_score = 0.20163175207756232`
  - `memory_thermal_coupling_proxy = 0.8756578947368421`
  - `memory_barrier_coupling_proxy = 69704`
  - `closed_loop_candidate = true`

- fresh thermal refresh 命令：

```bash
cd "/home/xgy/remote" && python3 "/home/xgy/remote/snn3dexp/tools/refresh_thermal_outputs.py" \
  --run-root "/home/xgy/remote/snn3dexp/runs" --run-tag archsum_matrix_smoke
```

- refresh 结果：
  - 已刷新 `11` 个当前 mainline 相关 case
  - 缺失 run dir 的 `4` 个 case 属于当前这轮未执行的非主线补充 case：
    - `full_3d_snn_window_bundle_v3`
    - `full_3d_snn_window_gating_event_probe`
    - `full_3d_snn_window_gating_event_synth`
    - `noc_only_3d_bundle_fault_v3`

### Real blocker discovered during fresh validation

- 本轮真正的 fresh 阻塞点不是 architecture 代码链没接上，而是 fixed-step `task_fixed_step_8_20us_sp64` 在运行过程中吃到了一版更老的 `libSnnDL.so`，导致：
  - `attempting to register unknown statistic 'snn_wms_frontier_record_prerank_entry_total'`
- 复核后确认：
  - 当前源码里的 `MultiCorePE` 已经文档化这些 `snn_wms_frontier_*` statistic。
  - 当前 `.libs/libSnnDL.so` 与 `sst-info SnnDL.MultiCorePE` 也能看到这些 statistic。
  - 在对齐后的 workspace 库上，等价 case

```bash
cd "/home/xgy/remote" && python3 "/home/xgy/remote/snn3dexp/tools/run_case.py" \
  full_3d_snn_window --run-tag fixed_step_sp64_reprobe --sst-smoke --stop-at 20us \
  --global-step-max-steps 8 --test-max-spikes 64
```

  已重新通过。

### Updated interpretation of the current state

1. 当前问题已经不再是“architecture summary 没有打通”。
2. 当前也不再是“runtime execute path 没接入 canonical case”。
3. 当前更真实的剩余问题是：
   - runtime focus 已经看得到 adaptive case 的强 memory/barrier coupling，
   - 但 route-runtime diff 还没有把 adaptive case 作为明确 compare row 导出来，
   - 同时 matrix 长跑仍缺少一个更早的 build-freshness preflight，导致 stale `.so` 会在中途才暴露。

### Next-stage task direction

1. 把 `full_3d_runtime_adaptive` 纳入 runtime diff compare set，形成 `full_3d -> full_3d_runtime_adaptive` 的显式 row，而不是只在 `runtime_focus_metrics` 里看到 adaptive case。
2. 给 long-running matrix 增加 library freshness preflight：
   - 在 run 开始前检查 `.libs/libSnnDL.so` 与 `sst-info SnnDL.MultiCorePE` 是否包含最新 `snn_wms_frontier_*` statistic contract。
3. 继续把 canonical adaptive stress 设计得更“memory/barrier dominant”，让 execute 来源逐步从 `hybrid` 过渡到更明确的 architecture-coupling 主导。

## Execution Update: 2026-03-25 late-day closure

### What is now actually complete

1. `architecture_summary` 已经下沉到 ablation / codesign surface / matrix 主链。
2. `route_thermal_coupling_score`、`memory_thermal_coupling_proxy`、`memory_barrier_coupling_proxy`、`closed_loop_candidate` 已经进入 surface / diff / runtime compare 输出。
3. `architecture.thermal_pressure` 的 tier/stack/layer 热摘要已经进入 mainline case summary。
4. runtime policy 已经能读取联合 memory/barrier/thermal coupling 信号，并且 canonical adaptive case 已经触发 execute path。
5. `full_3d_runtime_adaptive` 已经正式进入 `phase2_runtime_summary.runtime_comparisons`，形成：
   - `runtime_adaptive_vs_full_3d`
   - `base_case_id = "full_3d"`
   - `compare_case_id = "full_3d_runtime_adaptive"`
6. `archsum_matrix_smoke --phase2-mainline` 已经 fresh 跑通，`task_fixed_step_16_40us` 的 bundle_v3 老阻塞不再复现。

### Last-mile issue that was discovered and fixed

- fresh matrix 跑通后，真正剩下的不是仿真执行阻塞，而是顶层 route/runtime diff 导出有一个“半空 hotspot summary 提前短路”的问题：
  - top-level codesign surface 自带 `hotspot_runtime_summary`
  - 但其中 `runtime_comparisons = {}`
  - 同时又带了 `thermal_calibration`
  - 旧逻辑把这个 summary 当成“可用 runtime summary”直接返回，导致不会继续回读 `phase2_artifacts/phase2_runtime_summary.json`
- 结果就是：
  - nested `phase2_artifacts/route_runtime_diff/...` 是对的
  - 但 top-level `route_runtime_diff/...` 的 `runtime_compare_diffs` 会是空的

### Fix that landed

- 已在 `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py` 修复读取优先级：
  - 只有当候选 summary 真正带有非空 `runtime_comparisons` 时，才会短路返回
  - 否则继续尝试：
    - surface-provided file path
    - matrix summary provided file path
    - `phase2_artifacts_summary`
    - `phase2_artifacts.path`
  - 如果所有候选都没有 runtime compare rows，才回退到第一个非空 summary
- 同时新增了真实回归测试：
  - `snn3dexp/tests/test_export_memory_nmc_route_runtime_diff.py`
  - 新测试覆盖“surface hotspot summary 非空但 runtime compares 为空”这类 live matrix 场景

### Current verified state

- 顶层产物现状：
  - `memory_nmc_codesign_matrix_summary.runtime_library_preflight.performed = true`
  - `phase2_runtime_summary.runtime_comparisons` 当前有 `1` 条 compare
  - `route_runtime_diff.runtime_compare_summary.row_count = 1`
- 当前唯一 runtime compare row：
  - `compare_kind = runtime_adaptive_vs_full_3d`
  - `vertical_link_pressure_delta = 0.24375`
  - `stack_hotspot_penalty_delta = 0.25`
  - `homeroute_adjustment_count_delta = 2.0`
  - `thermal_guard_actions_delta = 2.0`
  - `dominant_runtime_axis = "thermal_guard_actions"`

### Updated next-stage direction

当前下一阶段已经不再是“把链路接通”，而是“把信号做强、做稳、做可解释”：

1. 先查清为什么 fresh compose/export 里的 `runtime_adaptive_vs_full_3d` 已经保留 execute/action delta，但 `route_thermal_coupling_score_delta`、`memory_thermal_coupling_proxy_delta`、`memory_barrier_coupling_proxy_delta` 仍然是 `0.0`。
2. 如果这不是导出覆盖问题，而是 canonical adaptive stress 还不够强，就回到 case / runtime policy / pressure synthesis，把 adaptive case 再往 memory-barrier dominant 推一段。
3. 评估是否要把 runtime compare row 直接并入 top-level `matrix_rows`，这样 matrix summary 本身就能成为闭环主视图，而不是还需要用户再跳一次 `route_runtime_diff`。

## Validation Closure Update: 2026-03-25 evening

### What was re-verified

1. `full_3d_snn_window_gating_event_synth --run-tag task_fixed_step_16_40us_sp64` 已在当前对齐后的 workspace 库上重新 smoke 通过。
2. `full_3d_snn_window_bundle_v3 --run-tag task_fixed_step_8_20us_sp64` 也已重新 smoke 通过。
3. `archsum_matrix_smoke --phase2-mainline --compose-only` 已成功重组：
   - `memory_nmc_codesign_matrix_summary.json`
   - `phase2_artifacts/phase2_runtime_summary.json`
   - `route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`

### Final state of the six-task chain

1. `architecture_summary` 已经稳定进入：
   - `analyze_ablation.py`
   - baseline/matrix payload
   - `export_memory_nmc_codesign_surface.py`
   - `export_memory_nmc_route_runtime_diff.py`
2. runtime policy 已能读取联合 architecture 信号并驱动 canonical adaptive execute path。
3. `runtime_adaptive_vs_full_3d` compare row 现在已经在顶层 diff 和 phase2 runtime summary 里显式存在。
4. 当前正式可用的关键闭环信号如下：
   - `route_thermal_coupling_score_delta = 0.10163175207756231`
   - `memory_thermal_coupling_proxy_delta = 0.8756578947368421`
   - `memory_barrier_coupling_proxy_delta = 69704.0`
   - `vertical_link_pressure_delta = 0.23782894736842103`
   - `stack_hotspot_penalty_delta = 0.13157894736842102`
   - `homeroute_adjustment_count_delta = 2.0`
   - `thermal_guard_actions_delta = 2.0`
   - `dominant_runtime_axis = "memory_barrier_coupling_proxy"`
5. case 级 architecture coupling 也已经不是“全零占位”：
   - `full_3d`: `route_thermal_coupling_score = 0.1`
   - `full_3d_runtime_adaptive`:
     - `route_thermal_coupling_score = 0.20163175207756232`
     - `memory_thermal_coupling_proxy = 0.8756578947368421`
     - `memory_barrier_coupling_proxy = 69704.0`
   - `full_3d_snn_window/task_fixed_step_16_40us_sp64`:
     - `route_thermal_coupling_score = 0.22187500000000002`
     - `route_barrier_coupling_proxy = 3962.53125`

### Important correction to earlier interpretation

- 之前文档里“fresh compose/export 仍然把 coupling delta 导成 0.0”的判断已经过时。
- 当前真实情况是：
  - top-level `route_runtime_diff` 已恢复非零 coupling delta；
  - `phase2_artifacts/phase2_runtime_summary.json` 里的 `runtime_adaptive_vs_full_3d` 也恢复了同样的非零 delta；
  - 旧的“0.0”判断来自修复前的 compose-only 覆盖问题与 route-runtime fallback 短路问题。

### What is still not fully closed

1. `architecture.thermal_pressure` 的 schema 目前稳定产出的是：
   - `layer_hotspot_distribution`
   - `tier_hotspot_summary`
   - `stack_hotspot_hint`
   而不是此前任务列表里写的显式 `tier_summary / stack_summary / layer_summary` 三件套。
2. 顶层 runtime compare row 已恢复关键 delta，但：
   - `route_barrier_coupling_proxy_delta` 仍为 `null`
   - `closed_loop_candidate_delta` 仍为 `null`
   说明 compare-row contract 还没有完全把布尔/绝对值平面对齐。
3. fixed-step 的 `window_memory_model_breakdown` 行里，大多数 `memory_thermal_coupling_proxy_delta` / `memory_barrier_coupling_proxy_delta` 仍是 `0.0`；
   这说明 window canonical case 对 memory-model/thermal-model 的区分还不够强，或者这些信号还没有被完整地下沉到 window compare plane。

### Updated next-stage direction

1. 收敛 `architecture.thermal_pressure` 命名：
   - 明确把当前 `tier_hotspot_summary` / `stack_hotspot_hint` / `layer_hotspot_distribution` 升级成更直观的 tier/stack/layer summary schema；
   - 同步所有 analyze/export/policy consumer。
2. 补齐 runtime compare row 的绝对值与布尔信号：
   - `base/compare route_barrier_coupling_proxy`
   - `base/compare memory_barrier_coupling_proxy`
   - `base/compare closed_loop_candidate`
   - 对应 delta 字段不再为 `null`
3. 强化 window canonical architecture stress：
   - 让 `full_3d_snn_window` vs `full_3d_snn_window_monolithic_proxy`
   - `full_3d_snn_window` vs `full_3d_snn_window_bundle_v3`
   在 thermal/memory coupling 上出现更稳定的非零差分
4. 把“fresh smoke library preflight”从运行时隐式检查，沉淀成独立 validation artifact：
   - 当前 compose-only 最终 summary 的 `runtime_library_preflight.performed = false` 是合理的；
   - 但这会让最终 summary 看起来像“没做 preflight”，后续最好把 fresh smoke validation 单独落盘。

## 2026-03-26 implementation update

### Newly closed gaps

1. `architecture.thermal_pressure` 已完成显式 schema 收敛，并保持兼容：
   - 新增：
     - `layer_summary`
     - `tier_summary`
     - `stack_summary`
   - 保留：
     - `layer_hotspot_distribution`
     - `tier_hotspot_summary`
     - `stack_hotspot_hint`
2. fixed-step `case_rows` 已补齐 architecture 下沉：
   - `analyze_fixed_step_sweep.py` 现在会读取 `architecture_summary` 或 `phase2_case_summary_path`
   - 输出 raw `architecture_summary`
   - 同时输出投影后的 coupling 字段与 `closed_loop_candidate`
3. 对应 consumer/test 已对齐：
   - `test_run_case.py`
   - `test_refresh_thermal_outputs.py`
   - `test_fixed_step_sweep.py`
   - `test_memory_nmc_codesign_surface.py`

### Fresh verification evidence

1. 单测全部通过：
   - `python3 -m unittest snn3dexp.tests.test_run_case`
   - `python3 -m unittest snn3dexp.tests.test_refresh_thermal_outputs`
   - `python3 -m unittest snn3dexp.tests.test_fixed_step_sweep`
   - `python3 -m unittest snn3dexp.tests.test_memory_nmc_codesign_surface`
2. fresh compose-only 已重跑：
   - `python3 "/home/xgy/remote/snn3dexp/tools/run_memory_nmc_codesign_matrix.py" --matrix-label archsum_matrix_smoke --phase2-mainline --compose-only`
3. fresh artifacts 观察结果：
   - `full_3d_snn_window/task_fixed_step_4_10us/phase2_case_summary.json`
     - `architecture.thermal_pressure` 已包含 `layer_summary / tier_summary / stack_summary`
   - `codesign_surface/memory_nmc_codesign_surface_summary.json`
     - fixed-step `window_memory_model_breakdown` 已不再是“architecture plane 完全缺失”
     - 当前 `step_budget=4, default` 行：
       - `route_thermal_coupling_score_delta = -0.22187500000000002`
       - `route_barrier_coupling_proxy_delta = -15444.166666666666`
       - `closed_loop_candidate_delta = 0`
   - `route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`
     - `runtime_adaptive_vs_full_3d` 保持：
       - `route_thermal_coupling_score_delta = 0.10163175207756231`
       - `memory_thermal_coupling_proxy_delta = 0.8756578947368421`
       - `memory_barrier_coupling_proxy_delta = 69704.0`

### Updated interpretation

1. 之前“fixed-step compare 的 architecture coupling 主要因为 payload 没下沉而变成 0.0”的缺口已经补上。
2. fresh compose-only 下仍看到的 `memory_thermal_coupling_proxy_delta = 0.0` / `memory_barrier_coupling_proxy_delta = 0.0`，在当前 canonical fixed-step 数据里主要来自：
   - `full_3d_snn_window` 与 `full_3d_snn_window_monolithic_proxy`
   - 两边 `most_pressured_controller_service_deficit_proxy` 都是 `0.0`
   - 因而 memory-coupling 按当前语义自然落为 `0.0`
3. 也就是说，当前剩余现象更像“模型值本身为零”，而不是“fixed-step architecture payload 没传下来”。

### Next-stage recommendation

1. 如果下一阶段目标是让 fixed-step memory-model compare 在 memory-thermal / memory-barrier 维度也稳定出现非零差分，优先应改的是：
   - monolithic window case 的 controller pressure / service deficit 建模；
   - 或 architecture coupling 的 memory-pressure fallback 语义。
2. 不建议再把问题归因到 analyze/export carry-through，因为这部分链路已经被 fresh compose-only 和单测共同验证通过。
