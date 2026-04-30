# Route3D Native Source Synthesis Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `SynapseRouteSubsystem3D` 的 `source-side fanout synthesis` 从“native 3D transport + legacy fanout provider 代理”升级成真正的 `3D-native source synthesis`，并保持现有 `multicast target` 契约与 `compat fallback` 不破坏。

**Architecture:** 本轮采用“先锁 contract，再在 `SynapseRouteSubsystem3D` 内部本地化 native fanout/gating/weight 解析，最后让 `computeFanout()` 与 `computeMulticastTargets()` 共用同一条 native fanout 输出”的方式推进。范围严格限制在 `route3d` 内核与契约测试，不扩展到 `memory/runtime/thermal`，也不额外改动 `ISynapseRoute`、`SpikeCommSubsystem` 的现有接口语义。

**Tech Stack:** C++17、SST/SnnDL、Python `unittest`

**Current Status (2026-03-21):** 本批实现已完成并通过验证。

- `computeFanoutNative3D_()` 已从 provider wrapper 升级为 route3d local kernel。
- `computeMulticastTargetsNative3D_()` 继续复用同一 native fanout 语义。
- `tryInitNativeRoutes_()` 已进一步支持：
  - `edges_csv` bootstrap
  - `legacy route tables -> native route3d` bootstrap
- 已完成验证：
  - `python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract -v`
  - `python3 -m unittest snn3dexp.tests.test_cpp_route_decoupling_contract -v`
  - `cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`
- 当前剩余缺口：
  - 仍需一份真实非 `edges_csv` 的 fresh smoke，证明新的 bootstrap 不只是合同级支持，而是实跑可用

---

### Task 1: 先把 native source-side 契约缺口锁成失败测试

**Files:**
- Modify: `snn3dexp/tests/test_route3d_native_fanout_contract.py`
- Modify: `snn3dexp/tests/test_cpp_route_decoupling_contract.py`

**Step 1: Write the failing tests**

- 在 `test_route3d_native_fanout_contract.py` 中新增断言，明确要求：
  - `computeFanoutNative3D_()` 不再直接调用 `fanout_provider_.computeFanout(...)`
  - `SynapseRouteSubsystem3D.h` 暴露 native source-side helper，例如：
    - `tryApplyNativeGating_`
    - `resolveNativeWeight_`
    - `appendNativeFanoutEntries_`
  - `computeFanout()` 保留：
    - `native_route_synthesis_active_` 时走 native path
    - 未激活时走 legacy/provider path
- 在 `test_cpp_route_decoupling_contract.py` 中新增断言，锁定：
  - `SnnRouteProvider` 仍只承担 compat/fallback 路径
  - `route3d` native path 的 source-side synthesis 不要求扩展 `ISynapseRoute` 公共接口

**Step 2: Run test to verify it fails**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_cpp_route_decoupling_contract -v`

Expected:
FAIL，明确暴露当前 `computeFanoutNative3D_()` 仍然只是 `fanout_provider_.computeFanout(...)` 的包装层。

### Task 2: 给 `SynapseRouteSubsystem3D` 加上 native source-side helper 骨架

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`

**Step 1: Write minimal declarations**

- 在 `SynapseRouteSubsystem3D.h` 中新增只服务 native path 的私有 helper：
  - `const RouteMap* activeNativeRouteTable_() const;`
  - `bool tryApplyNativeGating_(...) const;`
  - `float resolveNativeWeight_(uint32_t source_global, uint32_t dest_global) const;`
  - `void appendNativeFanoutEntries_(...) const;`
- 约束这些 helper 的职责：
  - route table 选择只看 `native_routes_shared_ / native_routes_local_`
  - gating 语义与当前 provider 保持一致
  - weight 查询只看 `native_route_weights_shared_ / native_route_weights_local_`
  - 不修改 `ISynapseRoute` 与 `SnnRouteProvider` 的公共接口

**Step 2: Run test to verify partial progress**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract -v`

Expected:
新增 helper 相关 contract 变绿，但“native path 仍未真正脱离 provider”的断言仍可能失败。

### Task 3: 实现真正的 native source-side fanout synthesis

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`

**Step 1: Write minimal implementation**

- 在 `computeFanoutNative3D_()` 中改为本地执行：
  - 如果 native route table 不可用，直接清空输出并保持 `applied_gating=false`
  - 先尝试 native gating 路径
  - 若 gating 未命中，则从 native route table 取 `source_global -> dest_globals`
  - 依据 `neurons_per_pe_cfg_` 计算 `dest_node`
  - 用 native route weight map 解析 `weight`
  - 写回 `FanoutEntry {dest_global, dest_node, weight}`
  - native 路径下继续维护 `stat_fanout_per_spike_`
- 保持以下边界不变：
  - fixed/fallback path 仍由 `SnnRouteProvider` 负责
  - `computeFanout()` 的外部行为接口不变
  - `initRoutes()` / `tryInitNativeRoutes_()` 的现有 bootstrap 逻辑不变

**Step 2: Run tests to verify green**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_cpp_route_decoupling_contract -v`

Expected:
PASS，说明 native source-side path 已不再依赖 `fanout_provider_.computeFanout(...)`。

### Task 4: 对齐 native fanout 与 multicast target synthesis 的共用语义

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- Modify: `snn3dexp/tests/test_route3d_native_fanout_contract.py`

**Step 1: Tighten minimal integration**

- 确保 `synthesizeMulticastTargetsForBlockDepth_()` 继续通过 `computeFanout()` 取 fanout，但此时 native 分支已落到新的 source-side kernel
- 增加 contract 断言，锁定：
  - `computeMulticastTargetsNative3D_()` 间接复用 native fanout path
  - `4x4x1`、`dim_z<=1`、未启用 native routes、或无 `mapping_edges_file` 时，仍走 compat/provider path
- 避免在 `multicast target synthesis` 中额外复制一份 source fanout 逻辑，保持单一真源

**Step 2: Run focused test**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract -v`

Expected:
PASS，且 compat/native 两条路径的 contract 都被显式锁住。

### Task 5: 编译验证并记录进度

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Build**

Run:
`cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`

Expected:
exit code `0`

**Step 2: Re-run focused verification**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_cpp_route_decoupling_contract -v`

Expected:
PASS

**Step 3: Record progress**

- 追加 `TECH_PROGRESS.md`
- 记录：
  - native source-side synthesis 已从 provider wrapper 升级为 route3d local kernel
  - 运行过的 focused tests
  - `make -j4` 编译结果
  - 下一步仍待做的真实 smoke / native multicast metrics / memory 语义接续任务

## Out of Scope For This Batch

- 不改 `ISynapseRoute` 公共接口
- 不改 `SpikeCommSubsystem` packet 合同
- 不改 `memory/NMC` 语义分析
- 本批 route3d 任务本身不负责推进 `runtime adaptive` 执行链；不过主线代码已在并行任务中把 `runtime_adaptive` 升级为第一版 executable `window` control
- 不把 `thermal/physical` 接入本轮实现

## Done Definition

当以下条件同时满足时，可以认为 `Batch 1` 的这一步完成：

1. `computeFanoutNative3D_()` 已不再委托 `fanout_provider_.computeFanout(...)`
2. native path 的 `gating / route table / weight lookup / stat_fanout` 在 `SynapseRouteSubsystem3D` 内部闭环
3. `computeMulticastTargetsNative3D_()` 继续复用同一 native fanout 语义
4. focused Python contract tests 通过
5. `SnnDL` 编译通过

当前状态：以上 Done Definition 已满足；后续剩余工作属于下一批 route semantics / fresh evidence 扩展，而不是本计划内的未完成项。
