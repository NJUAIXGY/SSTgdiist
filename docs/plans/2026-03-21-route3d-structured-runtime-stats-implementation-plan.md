# Route3D Structured Runtime Stats Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `route3d-native-runtime` 从 stdout marker 提升为正式的 `sst_stats.csv` 结构化统计链，并让 `phase2_case_summary.route_kernel` 优先消费这些 runtime stats。

**Architecture:** 本轮采用“最小接口扩展 + PE 统计注册 + run_case 解析优先级提升”的方式推进。`SnnPESubComponent` 负责注册 route3d native runtime stats，`ICoreWorkload/SynapseRoute` 只增加一个窄接口把统计 sink 传给 route 子系统，`SynapseRouteSubsystem3D` 在 native fanout 真实命中时更新统计。Python 侧则扩展 `sst_stats.csv` 解析与 `route_kernel` 摘要，优先使用结构化统计，stdout marker 仅作为 fallback。

**Tech Stack:** C++17、Python 3、`unittest`、SST/SnnDL、append-only progress logging

---

### Task 1: 先把 structured runtime stats 缺口锁成失败测试

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_cpp_route_decoupling_contract.py`

**Step 1: Write the failing tests**

- 在 `test_run_case.py` 中新增断言：
  - `_parse_processing_stats(...)` 能保留：
    - `route3d_native_activation_total`
    - `route3d_native_gating_activation_total`
    - `route3d_native_direct_activation_total`
    - `route3d_native_unique_sources_total`
  - `build_phase2_case_summary(...)` 在存在 `sst_stats.csv` 时，`route_kernel` 应优先输出：
    - `actual_activation_observed = true`
    - `actual_activation_source = "sst_stats_route3d_native_runtime"`
    - `runtime_activation_total`
    - `runtime_activation_gating_total`
    - `runtime_activation_direct_total`
    - `runtime_unique_sources_total`
- 在 `test_cpp_route_decoupling_contract.py` 中新增 contract：
  - `ISynapseRoute` 暴露 route runtime stats sink binding
  - `SnnWorkload` / `TrafficWorkload` 会把该 sink 绑定给 route 子系统

**Step 2: Run test to verify it fails**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_case.RunCaseTests.test_parse_processing_stats_keeps_route3d_native_runtime_counters snn3dexp.tests.test_run_case.RunCaseTests.test_build_phase2_case_summary_prefers_structured_route3d_runtime_stats_from_sst_stats snn3dexp.tests.test_cpp_route_decoupling_contract.CppRouteDecouplingContractTests.test_isynapseroute_exposes_route_runtime_stats_binding snn3dexp.tests.test_cpp_route_decoupling_contract.CppRouteDecouplingContractTests.test_workloads_bind_route_runtime_stats_sinks -v`

Expected:
FAIL，暴露当前缺少结构化 runtime stats 的注册、绑定与解析。

### Task 2: 最小实现 route runtime stats 接口与 C++ 统计更新

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ICoreWorkload.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ISynapseRoute.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`

**Step 1: Write minimal implementation**

- 在 `ICoreWorkload::Sinks` 中增加 4 个统计 sink：
  - `stat_route3d_native_activation_total`
  - `stat_route3d_native_gating_activation_total`
  - `stat_route3d_native_direct_activation_total`
  - `stat_route3d_native_unique_sources_total`
- 在 `ISynapseRoute` 中新增一个窄接口，例如：
  - `RouteRuntimeStatSinks`
  - `bindRouteRuntimeStats(...)`
- `SynapseRouteSubsystem` 保持 no-op / 兼容实现。
- `SynapseRouteSubsystem3D` 在 native fanout 成功时更新：
  - activation total
  - gating vs direct total
  - per-PE unique source total
- `SnnPESubComponent` 注册同名 SST stats，并通过 runtime sinks 传给 workload。
- `SnnWorkload` / `TrafficWorkload` 在 bind route 时把 route runtime stat sinks 传入 route 子系统。

**Step 2: Run focused tests to verify green**

Run the same unittest command again and expect PASS.

### Task 3: 扩展 run_case 解析并让 phase2 summary 优先使用结构化统计

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tools/run_case.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`

**Step 1: Write minimal implementation**

- 在 `_parse_processing_stats(...)` 的 `interesting` 集合里加入上述 4 个统计名。
- 增加 helper，从 `ctx.run_root / "sst_stats.csv"` 聚合 route3d runtime stats。
- `route_kernel` 摘要逻辑优先级改为：
  1. 先看 `sst_stats.csv` 的 structured runtime stats
  2. 若没有，再 fallback 到 stdout marker
- 输出字段：
  - `runtime_activation_total`
  - `runtime_activation_gating_total`
  - `runtime_activation_direct_total`
  - `runtime_unique_sources_total`
  - `actual_activation_source`

**Step 2: Run focused tests to verify green**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_case.RunCaseTests.test_parse_processing_stats_keeps_route3d_native_runtime_counters snn3dexp.tests.test_run_case.RunCaseTests.test_build_phase2_case_summary_prefers_structured_route3d_runtime_stats_from_sst_stats snn3dexp.tests.test_run_case.RunCaseTests.test_build_phase2_case_summary_reports_route3d_actual_runtime_activation_from_sst_stdout snn3dexp.tests.test_run_case.RunCaseTests.test_build_phase2_case_summary_keeps_expected_route_kernel_when_runtime_marker_missing -v`

Expected:
PASS

### Task 4: 回归、编译、真实 smoke 与进度记录

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run regression**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_cpp_route_decoupling_contract snn3dexp.tests.test_run_case -v`

Expected:
PASS

**Step 2: Run C++ build**

Run:
`cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`

Expected:
exit code `0`

**Step 3: Run one real smoke**

Run:
`cd /home/xgy/remote && python3 -m snn3dexp.tools.run_case full_3d --run-tag task_route3d_structured_runtime_stats --sst-smoke --stop-at 250ns`

Expected:
- `phase2_case_summary.route_kernel.actual_activation_source == "sst_stats_route3d_native_runtime"`
- `runtime_activation_total > 0`
- `runtime_unique_sources_total > 0`

**Step 4: Append progress**

- 只追加 `TECH_PROGRESS.md`
- 记录结构化 stats 名称、验证命令、真实 smoke 结果和下一步方向

## Out of Scope For This Batch

- 不移除现有 stdout marker
- 不改 HotSpot 主路径
- 不进入 runtime execute loop
- 不扩展 bundle/direct 更细 transport 成本模型

## Done Definition

当以下条件同时满足时，可以认为这一步完成：

1. `route3d` native runtime 统计正式进入 `sst_stats.csv`
2. `phase2_case_summary.route_kernel` 优先消费 structured runtime stats
3. stdout marker 只作为 fallback，不再是主证据来源
4. Python 回归通过
5. `SnnDL` 编译通过
6. `TECH_PROGRESS.md` 已 append 记录
