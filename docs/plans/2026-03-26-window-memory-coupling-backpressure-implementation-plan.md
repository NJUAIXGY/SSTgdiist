# Window Memory Coupling Backpressure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 fixed-step canonical window memory compare 在 `memory_thermal_coupling_proxy` / `memory_barrier_coupling_proxy` 维度稳定产出非零且可解释的 architecture 差分。

**Architecture:** 当前 `window_memory_model_breakdown` 的 memory-coupling 为零，根因不在 export/analyze carry-through，而在上游 controller-pressure 语义：`most_pressured_controller_service_deficit_proxy` 只吃 stack service deficit，无法表达 monolithic/simpleMem 这类“无 reject 但有明显 queue/backpressure”的真实 controller 压力。推荐路线是保留旧 `service_deficit_proxy` 兼容语义，同时新增显式 `controller_backpressure_proxy` 与 `memory_pressure_proxy`，再让 architecture coupling 与 runtime policy 消费统一的 composite memory-pressure 信号。

**Tech Stack:** Python 3, `snn3dexp/tools/analyze_route_memory_joint.py`, `snn3dexp/tools/run_case.py`, `snn3dexp/runtime/policy.py`, fixed-step / codesign export pipeline, `unittest`

---

## Current State Summary

- 已闭环部分：
  - `architecture.thermal_pressure` 已有显式 `layer_summary / tier_summary / stack_summary`
  - fixed-step `case_rows` 已能携带 `architecture_summary`
  - `window_memory_model_breakdown` 已恢复 route-side coupling，`route_thermal_coupling_score_delta` / `route_barrier_coupling_proxy_delta` 非零
- 当前真实瓶颈：
  - `full_3d_snn_window` 与 `full_3d_snn_window_monolithic_proxy` 的 `memory_thermal_coupling_proxy` / `memory_barrier_coupling_proxy` 仍为 `0.0`
  - 上游原因不是 payload 丢失，而是：
    - `real_controller_pressure.available = True`
    - `controller_reports` 存在，且 monolithic case 的 `max_outstanding_requests_accum` 明显非零
    - 但 `home_stack_controller_proxy.most_pressured_controller_service_deficit_proxy` 只由 `most_pressured_stack_service_deficit / controller_count` 推导
    - monolithic/simpleMem case 的 `most_pressured_stack_service_deficit = 0`
    - 所以下游 architecture memory coupling 天然坍缩到 `0.0`

## Design Decision

### Option A: 直接重定义 `most_pressured_controller_service_deficit_proxy`

优点：
- 改动面最小
- 现有 coupling 公式基本不用动

缺点：
- 字段语义漂移，名字不再准确
- 历史产物不易解释
- export/doc/test 中的 “service_deficit” 含义会变脏

### Option B: 新增显式 backpressure/composite 字段，并让 coupling 消费 composite proxy

优点：
- 语义清晰，可同时保留旧字段兼容
- 能区分 “真实 deficit” 与 “无 deficit 但有排队背压”
- 后续 runtime/policy 阈值调参更可解释

缺点：
- 需要同步更多 consumer/test

### Recommended

采用 **Option B**。

推荐新增三层语义：
- `most_pressured_controller_service_deficit_proxy`
  - 保持现状，继续表达“service deficit / controller”
- `most_pressured_controller_backpressure_proxy`
  - 新增，表达“controller queue/backpressure”
- `most_pressured_controller_memory_pressure_proxy`
  - 新增，作为 composite memory-pressure 信号
  - 推荐规则：
    - 优先使用 `service_deficit_proxy`
    - 当 `service_deficit_proxy == 0` 且 `real_controller_pressure.available = True` 时，退化为 `backpressure_proxy`
    - 可在文档/产物里同时记录 `memory_pressure_proxy_source = service_deficit|backpressure|hybrid`

---

### Task 1: Enrich Real Controller Pressure Semantics

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/analyze_route_memory_joint.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_fixed_step_sweep.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`

**Step 1: Write the failing tests**

为 monolithic-like controller summary 增加测试场景，要求在：
- `cycles_attempted_issue_but_rejected == 0`
- `service_deficit == 0`
- 但 `outstanding_requests_accum > 0`

时，仍能产出非零 backpressure proxy。

建议断言：
- `real_controller_pressure` 输出新增字段：
  - `most_pressured_controller_outstanding_requests_accum`
  - `most_pressured_controller_outstanding_requests_samples`
  - `most_pressured_controller_avg_outstanding_requests`
  - `most_pressured_controller_total_cycles`
- `home_stack_controller_proxy` 输出新增字段：
  - `most_pressured_controller_backpressure_proxy`
  - `most_pressured_controller_memory_pressure_proxy`
  - `memory_pressure_proxy_source`

**Step 2: Run test to verify it fails**

Run:
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_run_case`
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_fixed_step_sweep`

Expected:
- 失败于新增字段缺失或值仍为 `0.0`

**Step 3: Write minimal implementation**

在 `analyze_route_memory_joint.py` 中：
- 扩展 `_build_real_controller_pressure()`，保留并输出 most-pressured controller 的：
  - `outstanding_requests_samples`
  - `max_outstanding_requests`
  - `total_cycles`
  - `avg_outstanding_requests = outstanding_requests_accum / max(1, outstanding_requests_samples)`
- 扩展 `_build_home_stack_controller_proxy()`：
  - 保持旧 `most_pressured_controller_service_deficit_proxy`
  - 新增 `most_pressured_controller_backpressure_proxy`
  - 推荐初版最小公式：
    - `backpressure_proxy = avg_outstanding_requests + (issue_reject_ratio * max_outstanding_requests)`
  - 新增 `most_pressured_controller_memory_pressure_proxy`
  - 新增 `memory_pressure_proxy_source`

**Step 4: Run tests to verify they pass**

Run:
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_run_case`
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_fixed_step_sweep`

Expected:
- PASS
- monolithic synthetic case 现在能输出非零 `backpressure_proxy`

**Done when:**
- 不破坏旧 `service_deficit_proxy`
- monolithic-like synthetic case 有非零 composite memory-pressure proxy

### Task 2: Rebuild Architecture Coupling on Composite Memory Pressure

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/run_case.py`
- Modify: `/home/xgy/remote/snn3dexp/runtime/policy.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`

**Step 1: Write the failing tests**

新增断言：
- `architecture.memory_pressure` 暴露：
  - `most_pressured_controller_backpressure_proxy`
  - `most_pressured_controller_memory_pressure_proxy`
  - `memory_pressure_proxy_source`
- `architecture.coupling.memory_thermal_coupling_proxy`
- `architecture.coupling.memory_barrier_coupling_proxy`

在 `service_deficit_proxy == 0` 且 `backpressure_proxy > 0` 时仍应非零。

`runtime/policy.py` 侧断言：
- `build_runtime_summary()` 在读取 architecture summary 时，能透传新的 memory coupling
- 阈值决策仍基于 `memory_thermal_coupling_proxy` / `memory_barrier_coupling_proxy`

**Step 2: Run test to verify it fails**

Run:
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_run_case`
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_runtime_3d_policy`

Expected:
- FAIL，原因是 architecture memory-pressure / coupling 还没有使用 composite proxy

**Step 3: Write minimal implementation**

在 `run_case.py`：
- `memory_pressure` block 增加新字段
- `coupling.memory_thermal_coupling_proxy` / `memory_barrier_coupling_proxy` 改为基于 `most_pressured_controller_memory_pressure_proxy`

在 `runtime/policy.py`：
- `architecture_summary` 路径保持不变
- fallback `joint_runtime_derived` 路径改用 `most_pressured_controller_memory_pressure_proxy`
- 若新字段不存在，兼容退回旧 `most_pressured_controller_service_deficit_proxy`

**Step 4: Run tests to verify they pass**

Run:
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_run_case`
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_runtime_3d_policy`

Expected:
- PASS
- runtime policy 行为不回退

**Done when:**
- architecture layer 和 runtime layer 对 memory coupling 的语义一致

### Task 3: Align Fixed-Step / Export Surface With New Memory Pressure Semantics

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/analyze_fixed_step_sweep.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/export_memory_nmc_codesign_surface.py`
- Modify: `/home/xgy/remote/snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_fixed_step_sweep.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_memory_nmc_codesign_surface.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_export_memory_nmc_route_runtime_diff.py`

**Step 1: Write the failing tests**

新增断言：
- fixed-step `case_rows` 输出新的 memory-pressure proxy 字段
- `window_memory_model_breakdown_rows` 中：
  - `memory_thermal_coupling_proxy_delta != 0.0`
  - `memory_barrier_coupling_proxy_delta != 0.0`
  - 符号与 base/compare memory pressure 强弱一致
- route-runtime diff 若使用 new architecture summary，也能稳定保留非零 memory coupling

**Step 2: Run test to verify it fails**

Run:
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_fixed_step_sweep`
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_memory_nmc_codesign_surface`
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_export_memory_nmc_route_runtime_diff`

Expected:
- FAIL，原因是 compare rows 还看不到新的 memory-pressure projection

**Step 3: Write minimal implementation**

在 `analyze_fixed_step_sweep.py`：
- 把新的 memory-pressure proxy 一并拍平进 `case_rows`

在 `export_memory_nmc_codesign_surface.py`：
- `_project_architecture_surface_metrics()` 增强，但保持兼容：
  - 优先读 `coupling`
  - 如需附带诊断，也可输出 `memory_pressure_proxy_source`

在 `export_memory_nmc_route_runtime_diff.py`：
- 确保新的 memory-coupling 差分被稳定纳入 compare rows

**Step 4: Run tests to verify they pass**

Run:
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_fixed_step_sweep`
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_memory_nmc_codesign_surface`
- `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_export_memory_nmc_route_runtime_diff`

Expected:
- PASS
- fixed-step compare 行上的 memory coupling delta 稳定非零

**Done when:**
- export plane 不再只显示 route-side 非零，而 memory-side 也能稳定表达

### Task 4: Fresh Canonical Validation

**Files:**
- Read/verify:
  - `/home/xgy/remote/snn3dexp/tools/run_memory_nmc_codesign_matrix.py`
  - `/home/xgy/remote/snn3dexp/analysis/codesign_matrix/archsum_matrix_smoke/...`

**Step 1: Run compose-only validation**

Run:
- `cd "/home/xgy/remote" && python3 "/home/xgy/remote/snn3dexp/tools/run_memory_nmc_codesign_matrix.py" --matrix-label archsum_matrix_smoke --phase2-mainline --compose-only`

Expected checks:
- `window_memory_model_breakdown_rows` 的 4/8/16 step 三组行里：
  - `memory_thermal_coupling_proxy_delta != 0.0`
  - `memory_barrier_coupling_proxy_delta != 0.0`
- `route_runtime_diff` 顶层 row 继续保持非零
- `phase2_case_summary` 中 direct / monolithic window case 都有新 memory-pressure 字段

**Step 2: Run fresh runtime canonical case**

Run:
- 按当前 canonical runtime 执行链，重跑 `full_3d_runtime_adaptive`

Expected checks:
- runtime 控制动作仍然触发
- `dominant_runtime_axis` 不被意外翻坏
- 若新 memory proxy 更敏感，阈值需要重新标定

**Done when:**
- canonical compose-only 和 runtime execute 都能解释新 memory coupling

### Task 5: Threshold Retuning and Documentation Alignment

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/runtime/policy.py`
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-25-snn3d-architecture-summary-nextstep-implementation-plan.md`
- Test: `/home/xgy/remote/snn3dexp/tests/test_runtime_3d_policy.py`

**Step 1: Evaluate threshold drift**

检查：
- `memory_thermal_coupling_threshold`
- `memory_barrier_coupling_threshold`

避免因为 proxy 语义从 deficit-only 变成 composite，而导致 runtime policy 过触发。

**Step 2: Add/adjust tests**

增加阈值边界测试：
- composite proxy 低于阈值时不触发
- 高于阈值时触发
- `closed_loop_candidate` 仍按原 contract 工作

**Step 3: Append docs**

记录：
- 新字段语义
- monolithic/simpleMem 为什么以前会被压成零
- canonical validation 的新数值
- 后续是否需要把 composite proxy 再拆成 queue vs reject 两条独立 axis

**Done when:**
- policy 阈值与新 proxy 量纲匹配
- 文档可以解释所有新数值

---

## Verification Checklist

- `python3 -m unittest snn3dexp.tests.test_run_case`
- `python3 -m unittest snn3dexp.tests.test_fixed_step_sweep`
- `python3 -m unittest snn3dexp.tests.test_memory_nmc_codesign_surface`
- `python3 -m unittest snn3dexp.tests.test_export_memory_nmc_route_runtime_diff`
- `python3 -m unittest snn3dexp.tests.test_runtime_3d_policy`
- `python3 "/home/xgy/remote/snn3dexp/tools/run_memory_nmc_codesign_matrix.py" --matrix-label archsum_matrix_smoke --phase2-mainline --compose-only`

## Success Criteria

- `full_3d_snn_window` 与 `full_3d_snn_window_monolithic_proxy` 的 architecture memory coupling 都是可解释的非零值
- `window_memory_model_breakdown_rows` 的 `memory_thermal_coupling_proxy_delta` / `memory_barrier_coupling_proxy_delta` 在 canonical fixed-step rows 中稳定非零
- runtime policy 仍使用同一套 coupling 信号，不出现 execute path 回退
- 旧 `service_deficit_proxy` 保持兼容，不破坏现有 consumer

## Non-Goals

- 这轮不处理论文图表表达优化
- 这轮不处理 3D stack 新物理热模型扩展
- 这轮不重构 export surface 的整体 schema
- 这轮不改 git/worktree 流程
