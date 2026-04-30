# SNN3D Next-Stage Authority-First Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Last updated:** 2026-04-02

**Goal:** 在当前 `3D-native Route + HBM-like NMC + Windowed-SNN Co-Design Mainline` 且 `route source semantics authoritative` 已经落地的基础上，把平台继续推进到“HBM-like home-path authoritative + canonical matrix/source-tier refreshed + high-load/runtime closure authoritative”的下一阶段。

**Architecture:** 下一阶段不新建平行主线，而是沿现有主链继续收口：C++ 侧保持 `ISynapseRoute -> SpikeCommSubsystem -> SynapseRouteSubsystem3D -> MulticastRouter3DNative` 的 authority contract 不再回退，Python 侧继续围绕 `run_case -> codesign surface -> codesign matrix -> route/runtime diff -> phase2 artifacts` 扩展 authority。整个 wave 分三层推进：先做真实 HBM-like home-stack path / controller-path authority，再把 canonical matrix 与 source-tier 口径刷新到新的 native-source semantics，最后把 high-load `windowed SNN` 与 runtime control closure 压成 canonical artifact。

**Tech Stack:** C++17, SST/SnnDL, Python 3, `unittest`, `snn3dexp.tools.*`, `snn3dexp.memory.*`, `snn3dexp.platform.*`, phase2 artifact pipeline

## Latest Status Update

截至 `2026-04-01` 当前最新状态：

1. `Task 1` 已完成：
   - route authority contract 已冻结到 `ISynapseRoute` 接口层
   - `phase2_case_summary["architecture"]["route_pressure"]` 已直接消费 descriptor authority
2. `Task 2` 已完成：
   - source-side fanout authority 已收口到 descriptor dispatch
   - `SpikeCommSubsystem` / `SnnWorkload` 已按 interface contract 认领 native 3D runtime
   - `native_3d + edges_csv + real synapse inputs` 当前已显式导出：
     - `source_semantics_authority = native_3d_route_table`
     - `source_primary_kind = native_3d_route_table_with_real_synapse_inputs`
     - `native_bootstrap_source = edges_csv`
   - `run_case / route_memory_joint / phase2_case_summary` 已统一消费这条新 authority
3. `Task 3` 已完成：
   - `build_synapse_source_descriptors()` / `build_sst_graph_manifest()` 已下沉
     - `controller_endpoint`
     - `path_authority`
     - `semantic_region_layout_version`
   - `home_stack_controller_proxy` / `home_stack_dataflow` 已显式标明 `real_home_stack_binding` vs `proxy_projection` vs `runtime_controller`
   - `codesign surface` row 与 `phase2 architecture.memory_pressure` 已投影：
     - `home_stack_path_authority`
     - `pe_nic_real_home_path_authority`
     - `synapse_real_home_path_authority`
   - 已通过 targeted regression、`full_3d_snn_window` limited SST smoke，以及 `full_3d_runtime_adaptive --run-tag authority_native_source_20260401 --sst-smoke --stop-at 250ns`
4. 当前剩余的主 critical path 已收敛到：
   - `Task 3.5` / canonical matrix 与 source-tier freshness refresh
   - `Task 4` / `HBM-like home-path authoritative + high-load closure third`
   - 即把新的 native-source authority 刷进 canonical matrix，并把 high-load `windowed SNN`、`runtime control closure`、home-path/controller-path authoritative 结果做成下一阶段正式权威读物

---

## Priority Decision

### Recommended path: `authority-first`

推荐主线：

1. `route authority first`
   - 已完成；当前不再把它当作待做项，而是把它当作后续 memory/NMC 主结论的已完成前提
2. `HBM-like home-path authority second`
   - 再把 `HBM-like shared-stack` 从 hierarchy/proxy compare 推进到更明确的 real home-path / controller-path authority
3. `canonical matrix/source-tier refresh third`
   - 把 `native_3d_route_table_with_real_synapse_inputs` 刷进 canonical matrix / route-runtime diff / phase2 artifacts，替换旧的 `bootstrap_bound` 主叙事
4. `high-load closure fourth`
   - 最后把 high-load `windowed SNN`、`stop-window`、`runtime_control_closure` 固化成 canonical mainline

推荐这个顺序的原因：

1. route source authority 虽然已经补齐，但 canonical matrix 等旧 artifact 仍可能保留旧的 `bootstrap_bound` 结果；如果不刷新，主线叙述会出现“代码是新的、总结还是旧的”错位。
2. 如果 home-path authority 不补齐，那么 `HBM-like` 仍然更像“有意义的 proxy”，但还不是可以直接承接论文主结论的 authority。
3. high-load/runtime closure 的价值最大，但它必须建立在 route 与 memory authority 已经更硬、且 artifact 已 fresh 的基础上，否则只是把更多 artifact 叠在旧 provenance 上。

### Alternative A: `memory-first`

优点：

- 更快得到 `HBM-like vs monolithic-like` 的新图表和新结论

问题：

- canonical matrix / source-tier freshness 尚未跟上新的 native-source authority
- 后续论文答辩时，memory 结论容易被追问“主结果表里的 source semantics 是否仍然是旧 bootstrap artifact”

### Alternative B: `experiment-first`

优点：

- 最快扩出更多 matrix / stop-window / high-load 结果

问题：

- 会放大当前 artifact freshness / home-path authority gap
- 结论数量增加，但主线可信度提升有限

### Explicitly Not Recommended Now

当前不推荐优先做：

1. 更细工艺 realism，例如 TSV/MIV、电源网、时钟网
2. 真正的 PIM operator / near-memory execution datapath
3. cycle-level thermal closed loop
4. 更大 mesh 拓扑扩展

这些都重要，但都不应抢在 authority-first 主线前面。

## Wave Boundary

### This wave must finish

1. 把新的 `native_3d_route_table_with_real_synapse_inputs` authority 刷新到 canonical matrix / route-runtime diff / phase2 artifacts。
2. `HBM-like` 的 `synapse/home-stack`、`PE/NIC -> home stack` 路径 authority 继续做实，进入 `run_case` / `route_memory_joint` / `codesign surface` / `matrix`。
3. `runtime_control_closure` 从 exporter 局部能力升级成 canonical mainline 的正式读物之一。
4. 至少完成一轮 fresh：
   - C++ 编译
   - Python targeted regression
   - single-case limited SST smoke
   - canonical matrix compose-only / refresh

### This wave explicitly defers

1. 真正执行型 near-memory compute operator
2. 工艺级 monolithic DRAM realism signoff
3. cycle-level runtime/thermal feedback
4. 大规模 mesh 尺度扩展实验

## Completion Note

下文的 `Task 1 / Task 2` 作为已完成的 authority-first 冻结参考保留，不再是当前待执行项。
当前真正需要继续推进的是：

1. `Task 3` 的 home-path/controller-path authority 深化
2. canonical matrix / route-runtime diff 的 fresh rerun
3. `Task 4` 的 high-load closure

## Task 1: Freeze The Route Authority Contract At The Interface Boundary

**Files:**
- Modify: `snn3dexp/tests/test_route3d_native_fanout_contract.py`
- Modify: `snn3dexp/tests/test_cpp_route_decoupling_contract.py`
- Modify: `snn3dexp/tests/test_run_case.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ISynapseRoute.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Reference: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- Reference: `snn3dexp/tools/run_case.py`

**Step 1: Write the failing tests**

锁定两个下一阶段 contract：

1. `ISynapseRoute` 不只暴露 3D target geometry，还要暴露 route authority descriptor，例如：
   - `describeRouteSemantics() const`
   - `source_semantics_authority`
   - `native_source_fanout_active`
   - `native_target_synthesis_active`
2. `run_case.py` 生成的 `phase2_case_summary["architecture"]["route_pressure"]` 至少带出：
   - `source_semantics_authority`
   - `native_source_fanout_active`
   - `native_target_synthesis_active`

**Step 2: Run tests to verify they fail**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_route3d_native_fanout_contract \
  snn3dexp.tests.test_cpp_route_decoupling_contract \
  snn3dexp.tests.test_run_case -v
```

Expected:

- FAIL，提示接口层还没有 authority descriptor，或 `run_case` 还没有 route authority summary

**Step 3: Write minimal implementation**

实现原则：

1. 在 `ISynapseRoute.h` 内新增一个轻量 `RouteSemanticDescriptor`
2. legacy 2D 与 native 3D 两个实现都必须能返回 descriptor
3. descriptor 必须能区分：
   - `legacy_provider`
   - `legacy_built_routes_3d`
   - `native_3d_route_table`
4. `run_case.py` 只消费 descriptor，不直接猜测 route authority

**Step 4: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_route3d_native_fanout_contract \
  snn3dexp.tests.test_cpp_route_decoupling_contract \
  snn3dexp.tests.test_run_case -v
```

Expected: PASS

## Task 2: Make Source-Side Fanout Semantics Formally 3D-Authoritative

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- Modify: `snn3dexp/tests/test_route3d_native_fanout_contract.py`
- Modify: `snn3dexp/tests/test_route3d_multicast_metrics.py`
- Modify: `snn3dexp/tests/test_cpp_route_decoupling_contract.py`

**Step 1: Write the failing tests**

新增并锁定：

1. 当 `native_route_synthesis_active_` 或等价 authority 成立时，`computeFanout()` 应走本地 native 3D kernel，而不是回落到 provider wrapper
2. native 3D kernel 的 runtime stats 必须能区分：
   - source-side native activation
   - gating-applied activation
   - direct/native fallback activation
3. `SnnWorkload.cc` 需要把 authority 相关 stats 继续带进真实 SST stats 汇总

**Step 2: Run tests to verify they fail**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_route3d_native_fanout_contract \
  snn3dexp.tests.test_route3d_multicast_metrics \
  snn3dexp.tests.test_cpp_route_decoupling_contract -v
```

Expected:

- FAIL，提示 source-side authority 仍未成为统一 entrypoint，或缺失可用统计/contract

**Step 3: Write minimal implementation**

实现原则：

1. `SynapseRouteSubsystem3D::computeFanout()` 自己决定 authority dispatch
2. native 3D kernel 继续复用已有 `activeNativeRouteTable_()` / gating / weight helper
3. `SpikeCommSubsystem` 不新增新的 route type 假设，只继续走 interface contract
4. `SnnWorkload` 只通过 interface descriptor 与 runtime stats 认领 authority

**Step 4: Compile the affected C++ surface**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4
```

Expected: build succeeds

**Step 5: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_route3d_native_fanout_contract \
  snn3dexp.tests.test_route3d_multicast_metrics \
  snn3dexp.tests.test_cpp_route_decoupling_contract -v
```

Expected: PASS

## Task 3: Actualize HBM-Like Home-Path And Controller Authority

**Files:**
- Modify: `snn3dexp/memory/hbm_stack.py`
- Modify: `snn3dexp/platform/sst_graph.py`
- Modify: `snn3dexp/tools/analyze_route_memory_joint.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/tests/test_synapse_home_stack_runtime.py`
- Modify: `snn3dexp/tests/test_nmc_stack_analysis.py`
- Modify: `snn3dexp/tests/test_memory_nmc_codesign_surface.py`

**Step 1: Write the failing tests**

锁定三个 authority 升级点：

1. `build_synapse_source_descriptors()` 与 `build_sst_graph_manifest()` 不只给 `home_stack_id`，还要给更明确的 controller/path authority 元数据，例如：
   - `controller_endpoint`
   - `path_authority`
   - `semantic_region_layout_version`
2. `analyze_route_memory_joint.py` 构出的：
   - `home_stack_controller_proxy`
   - `home_stack_dataflow`
   需要能标明哪些字段来自 real path，而不是 proxy inference
3. `codesign surface` 需要把这些 authority 字段继续投影到 row 上，例如：
   - `home_stack_path_authority`
   - `pe_nic_real_home_path_authority`
   - `synapse_real_home_path_authority`

**Step 2: Run tests to verify they fail**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_synapse_home_stack_runtime \
  snn3dexp.tests.test_nmc_stack_analysis \
  snn3dexp.tests.test_memory_nmc_codesign_surface -v
```

Expected:

- FAIL，提示当前 authority 字段缺失，或 real path 与 proxy path 仍未被明确定义

**Step 3: Write minimal implementation**

实现原则：

1. `HBM-like` 的 authority 提升必须沿现有 object graph 走，不新增平行 memory path
2. `analyze_route_memory_joint.py` 要显式区分：
   - `real_path`
   - `proxy_projection`
3. row 侧的新增 authority 字段必须是可比较的，而不只是 debug 注释

**Step 4: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_synapse_home_stack_runtime \
  snn3dexp.tests.test_nmc_stack_analysis \
  snn3dexp.tests.test_memory_nmc_codesign_surface -v
```

Expected: PASS

## Task 4: Promote High-Load Windowed-SNN And Runtime-Control Closure Into Canonical Mainline

**Files:**
- Modify: `snn3dexp/tools/run_fixed_step_multicase_sweep.py`
- Modify: `snn3dexp/tools/run_window_stop_multicase_sweep.py`
- Modify: `snn3dexp/tools/analyze_window_stop_multicase_sweep.py`
- Modify: `snn3dexp/tools/run_memory_nmc_codesign_matrix.py`
- Modify: `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- Modify: `snn3dexp/tools/export_phase2_paper_artifacts.py`
- Modify: `snn3dexp/tests/test_window_stop_multicase_sweep.py`
- Modify: `snn3dexp/tests/test_analyze_window_stop_multicase_sweep.py`
- Modify: `snn3dexp/tests/test_run_memory_nmc_codesign_matrix.py`
- Modify: `snn3dexp/tests/test_export_memory_nmc_route_runtime_diff.py`
- Modify: `snn3dexp/tests/test_phase2_paper_artifacts.py`

**Step 1: Write the failing tests**

锁定：

1. high-load `default / sp64` 的 `windowed SNN` 与 `stop-window` 不再只是 sweep side artifact，而要进入 canonical matrix 的正式 compare surface
2. `route_runtime_diff` summary 必须把：
   - `mechanism_progression_summary`
   - `route_memory_joint_pressure_summary`
   - `runtime_control_closure_summary`
   都继续透传到 canonical summary / phase2 artifacts
3. `phase2_paper_artifacts` 必须能显示：
   - high-load route-memory mechanism progression
   - runtime closure row count / summary path

**Step 2: Run tests to verify they fail**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_window_stop_multicase_sweep \
  snn3dexp.tests.test_analyze_window_stop_multicase_sweep \
  snn3dexp.tests.test_run_memory_nmc_codesign_matrix \
  snn3dexp.tests.test_export_memory_nmc_route_runtime_diff \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected:

- FAIL，提示 canonical mainline 还未把 high-load/runtime closure 当成一等 artifact

**Step 3: Write minimal implementation**

实现原则：

1. 继续复用现有 `matrix_rows` / `phase2_artifacts` / `route_runtime_diff` 结构
2. 不新增第二个 main entry
3. 优先让 `runtime_control_closure_summary` 成为顶层 summary 可读字段
4. `window_stop` 的高负载行要和现有 `window_route / window_memory` 语义兼容，不破坏旧 row group

**Step 4: Run tests to verify they pass**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_window_stop_multicase_sweep \
  snn3dexp.tests.test_analyze_window_stop_multicase_sweep \
  snn3dexp.tests.test_run_memory_nmc_codesign_matrix \
  snn3dexp.tests.test_export_memory_nmc_route_runtime_diff \
  snn3dexp.tests.test_phase2_paper_artifacts -v
```

Expected: PASS

## Task 5: Fresh Verification, Limited Smoke, And Status Refresh

**Files:**
- Modify: `docs/plans/nextarc/2026-03-30-snn3d-mainline-current-technical-architecture.md`
- Modify: `TECH_PROGRESS.md`

**Step 1: Run targeted regression**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  snn3dexp.tests.test_route3d_native_fanout_contract \
  snn3dexp.tests.test_cpp_route_decoupling_contract \
  snn3dexp.tests.test_route3d_multicast_metrics \
  snn3dexp.tests.test_synapse_home_stack_runtime \
  snn3dexp.tests.test_nmc_stack_analysis \
  snn3dexp.tests.test_memory_nmc_codesign_surface \
  snn3dexp.tests.test_window_stop_multicase_sweep \
  snn3dexp.tests.test_analyze_window_stop_multicase_sweep \
  snn3dexp.tests.test_export_memory_nmc_route_runtime_diff \
  snn3dexp.tests.test_run_memory_nmc_codesign_matrix \
  snn3dexp.tests.test_phase2_paper_artifacts \
  snn3dexp.tests.test_phase2_baseline_suite \
  snn3dexp.tests.test_runtime_3d_policy -v
```

Expected: PASS

**Step 2: Rebuild the C++ surface**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4
```

Expected: build succeeds

**Step 3: Run one limited real SST smoke**

Run:

```bash
cd "/home/xgy/remote" && python3 "snn3dexp/tools/run_case.py" \
  full_3d_snn_window \
  --run-tag "nextstage_authority_smoke" \
  --sst-smoke \
  --stop-at "2us"
```

Expected:

- 生成真实 smoke 产物
- `phase2_case_summary.json` 带出新的 route authority 与 home-path authority 字段

**Step 4: Run one canonical compose-only matrix**

Run:

```bash
cd "/home/xgy/remote" && python3 "snn3dexp/tools/run_memory_nmc_codesign_matrix.py" \
  --matrix-label "nextstage_authority_matrix" \
  --compose-only \
  --phase2-mainline
```

Expected:

- 生成 canonical matrix summary
- 生成 route/runtime diff summary
- 生成 phase2 artifacts
- `runtime_control_closure` 进入主线输出

**Step 5: Refresh docs**

必须更新：

1. `docs/plans/nextarc/2026-03-30-snn3d-mainline-current-technical-architecture.md`
   - 把“当前边界”中的已完成项移除或降级
2. `TECH_PROGRESS.md`
   - append fresh regression / smoke / artifact 路径
   - append 下一阶段剩余 TODO

## Exit Criteria

只有当下面五件事同时成立，这一 wave 才算完成：

1. route authority 已经能在接口层显式说明 source semantics 来自哪里
2. native 3D source-side fanout 成为正式 authority，而不只是 route3d 局部 helper
3. `HBM-like` home-path/controller authority 已进入 canonical row 语义
4. `runtime_control_closure_summary` 进入 canonical mainline artifact
5. 至少一轮 fresh compile + regression + limited smoke + matrix compose-only 全部成功

## Notes

1. 本计划故意不把“真 PIM operator”放进本 wave，避免 scope 爆炸。
2. 本计划故意不新建第二套 main entry，避免主线分裂。
3. 本计划故意把 `windowed SNN` 放在 high-load/runtime closure 的中心位置，后续论文级结果应优先从这条 workload 主线讲，而不是重新退回 `traffic_mem` baseline 叙事。

## 2026-04-01 Progress Refresh

本轮 authority-first 的推进重点，落在 Python artifact 主链的 freshness hardening，而不是继续扩新 case。

### 已完成

1. `route_memory_joint_loader` 已经具备 freshness-aware rebuild
   - 旧 `route_memory_joint_summary.json` 如果缺少新的 route overlap semantics，不再被误判为 current
   - 即使上游 payload 只有 `route_memory_joint_summary_path`，也能自动反推 `runs/<case>/<run_tag>` 进行 rebuild

2. `codesign surface` 已不再被 stale runtime summary 覆盖
   - refreshed `route_memory_overlap_mode / route_native_synapse_overlap_ratio / route_overlap_actionable`
     可以稳定保留到 baseline rows / compare rows

3. fresh artifact 已重新导出
   - `windowed native dense family`
     - `native_dense_family_gating_semantic_final_20260401`
   - `canonical matrix`
     - `archsum_matrix_semantic_final_20260401`

### 这轮最重要的技术结论

1. `windowed SNN` 已经能在真实 artifact 上读到：
   - `full_3d_snn_window = native_synapse_aligned, ratio=1.0`
   - `full_3d_snn_window_bundle_v3 = native_synapse_aligned, ratio=0.0`
   - 这意味着 direct vs bundle 的 route/native overlap 差异已经正式进入主线 artifact

2. `canonical matrix` 目前仍主要显示：
   - `legacy_only`
   - `bootstrap_bound`
   - `runtime_adaptive_vs_full_3d` 还没有出现 `bootstrap_bound -> native_synapse_aligned`

### 对后续步骤的影响

这说明 authority-first 计划里，Python/export freshness 这一层已经足够站稳；下一阶段更值得投入的是：

1. 继续推进 C++ 主链的 source authority，而不是再修 export 末端
2. 让 canonical matrix 不再主要受 `edges_csv bootstrap` 主导
3. 把 `windowed SNN` 上已经可见的 native overlap 语义，继续下沉到更真实的 runtime control / remap 闭环

## 2026-04-02 Execution Update

本轮已经把上面第 2 条真正做完，而且不是 compose-only，而是 fresh real-SST matrix。

### 已完成

1. `canonical matrix` 已经刷新到新的 authority tag 集合
   - fresh label:
     - `authority_native_matrix_refresh_20260402`
   - fresh baseline run tag:
     - `authority_native_source_20260401`

2. `compare/export` 链已经补全 source-primary-kind 透传
   - `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - `traffic compare rows`
   - `runtime compare rows`
   - 现在都显式包含：
     - `base_route_source_primary_kind`
     - `compare_route_source_primary_kind`
     - `route_source_primary_kind_transition`

3. fresh matrix 主结论已经从旧的 bootstrap-bound runtime row 升级
   - `runtime_adaptive_vs_full_3d`
     - `edges_csv_bootstrap -> native_3d_route_table_with_real_synapse_inputs`
     - `bootstrap_bound -> native_synapse_aligned`
     - `bootstrap_manifest -> native_multicast_synapse_home`

4. `window_stop` 高负载辅证也已经刷新
   - 六个 `window_stop_*` row 现在都稳定显示：
     - `legacy_route_tables_with_real_synapse_inputs`
     - `native_synapse_aligned`
     - `native_multicast_synapse_home -> native_multicast_synapse_home`

### 对 Exit Criteria 的影响

当前 five-way exit criteria 可以更新为：

1. route authority 已能在接口层说明 source semantics 来自哪里
   - 已完成
2. native 3D source-side fanout 成为正式 authority
   - 已完成
3. `HBM-like` home-path/controller authority 已进入 canonical row 语义
   - 部分完成
   - runtime controller 数值已经进入
   - 但 authority provenance 仍有一层在 `analyze_ablation` 中被截断
4. `runtime_control_closure_summary` 进入 canonical mainline artifact
   - 已完成
5. 至少一轮 fresh regression + limited/full smoke + matrix mainline 成功
   - 已完成（本轮是 fresh matrix mainline，不再只是 compose-only）

### 当前剩余的最值得做的两件事

1. `home-path authority` 表意拆清
   - 在 `analyze_route_memory_joint.py`
   - 把：
     - `source_binding_authority_kind`
     - `stage_breakdown_authority_kind`
   - 并列保留，避免把“真实 home binding”误写成“整条 path 全部 runtime-real”

2. `controller-path authority provenance` 下沉到 ablation/canonical rows
   - 在 `analyze_ablation.py`
   - 透传：
     - `home_stack_path_authority`
     - `home_stack_controller_pressure_authority`
     - `home_stack_runtime_authority_available`
     - `dominant_home_controller_ids`

### 当前建议

authority-first 这条 wave 的核心目标已经不再是“继续找一个更新 smoke tag”，而是：

1. 固化 `authority_native_matrix_refresh_20260402` 为新的 canonical latest
2. 把 `home-path/controller-path authority provenance` 从 joint summary 稳定投到 canonical rows
3. 然后再进入下一轮 `memory/NMC + runtime remap` 细化，而不是重新回去修 source authority 本身

## 2026-04-02 Execution Update

这轮已经把上面的第 2 点正式做成 fresh canonical artifact。

### 已完成

1. compare/export 链已经补齐 route source semantics
   - `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - compare rows 与 derived runtime rows 现在都会显式输出：
     - `base_route_source_primary_kind`
     - `compare_route_source_primary_kind`
     - `route_source_primary_kind_transition`

2. 已完成 fresh canonical matrix mainline
   - 入口：
     - `python3 -m snn3dexp.tools.run_memory_nmc_codesign_matrix --matrix-label authority_native_matrix_refresh_20260402 --baseline-run-tag authority_native_source_20260401 --fixed-step-run-tag task_fixed_step_4_10us --phase2-mainline`
   - 主产物：
     - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/memory_nmc_codesign_matrix_summary.json`
     - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`
     - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/phase2_artifacts/phase2_runtime_summary.json`

3. authority-first 的关键结论已经进入 canonical latest
   - `runtime_adaptive_vs_full_3d`
     - `edges_csv_bootstrap -> native_3d_route_table_with_real_synapse_inputs`
     - `bootstrap_bound -> native_synapse_aligned`
     - `bootstrap_manifest -> native_multicast_synapse_home`
   - `window_stop_*`
     - 已从旧的 `bootstrap_bound` fresh 到 `native_synapse_aligned`

### 本轮补齐的剩余点

1. `HBM-like home-path/controller authority provenance` 已完成闭环
   - `snn3dexp/tools/analyze_route_memory_joint.py`
     - `home_stack_dataflow`、每个 initiator group、各自的 `home_path_summary`
     - 现在都会并列保留：
       - `source_binding_authority_kind`
       - `stage_breakdown_authority_kind`
       - 兼容保留 `path_authority_kind`
   - `snn3dexp/tools/analyze_ablation.py`
     - 现在会把下列字段稳定透传到 `route_memory_joint` 行：
       - `home_stack_path_authority`
       - `home_stack_controller_pressure_authority`
       - `home_stack_runtime_authority_available`
       - `dominant_home_controller_ids`
   - `authority_native_matrix_refresh_20260402`
     - 已经在最新 contract 下重新 compose-only refresh
     - canonical `traffic_baseline_ablation / fixed_step_analysis / codesign_surface` 产物已重新对齐

2. 剩余事项已经从 authority-first 主体实现转成后续治理项
   - current most trusted real-closure case 仍然是：
     - `full_3d_runtime_adaptive/authority_native_source_20260401`
   - 后续更值得做的是：
     - canonical latest 的 run-tag 清单治理
     - `memory/NMC + runtime remap co-design`
     - 如后续论文表图需要，再考虑把 raw `source_binding_authority_kind` 继续提升到 unified compare surface

### 对 Exit Criteria 的最新判断

1. `route authority 已显式说明 source semantics 来自哪里`
   - 已完成
2. `native 3D source-side fanout 成为正式 authority`
   - 已完成
3. `HBM-like home-path/controller authority 已进入 canonical row 语义`
   - 已完成
   - joint summary 层负责保留 `source binding` vs `stage breakdown`
   - downstream row/surface 层负责导出 `home_stack_* authority` 与 controller CSV
4. `runtime_control_closure_summary 进入 canonical mainline artifact`
   - 已完成
5. `fresh regression + real smoke + canonical refresh`
   - 已完成
   - 本轮额外完成了 compose-only canonical refresh
   - 本轮不是 C++ 变更，因此无新增 compile gate

## 2026-04-02 Authority Provenance Closure Update

上一个 update 里剩下的两个 authority-first 尾项，现在都已经收口：

1. `home-path authority` 表意拆清
   - `snn3dexp/tools/analyze_route_memory_joint.py`
   - 当前已经把：
     - `source_binding_authority_kind`
     - `stage_breakdown_authority_kind`
   - 并列保留在 `home_stack_dataflow` 及其 initiator-group/root summary 中
   - 因而 downstream 不再把 “真实 home binding” 与 “路径阶段拆解” 混成一层 authority

2. `controller-path authority provenance` 已下沉到 ablation/canonical rows
   - `snn3dexp/tools/analyze_ablation.py`
   - `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - 当前已经稳定投影：
     - `home_stack_path_authority`
     - `home_stack_controller_pressure_authority`
     - `home_stack_runtime_authority_available`
     - `dominant_home_controller_ids`
     - `home_stack_source_binding_authority`
     - `home_stack_stage_breakdown_authority`

### Updated Exit Criteria Judgment

截至 `2026-04-02`，authority-first 这一 wave 的 five-way exit criteria 可以判定为全部完成：

1. `route authority 已显式说明 source semantics 来自哪里`
   - 已完成
2. `native 3D source-side fanout 成为正式 authority`
   - 已完成
3. `HBM-like home-path/controller authority 已进入 canonical row 语义`
   - 已完成
4. `runtime_control_closure_summary 进入 canonical mainline artifact`
   - 已完成
5. `fresh regression + real smoke + canonical refresh`
   - 已完成

### What The Plan Should Focus On Next

authority-first 不再是当前主 critical path。下一阶段建议切换到 `memory/NMC + co-design first`，具体优先级如下：

1. `Priority 1: real home-path workload closure`
   - 继续加强 `PE/NIC -> home stack` 与 `synapse -> home stack` 的真实业务流量面
   - 目标不是再加 authority 标签，而是让这些路径直接成为 `HBM-like` 压力解释的主观察量

2. `Priority 2: HBM-like vs monolithic-like paradigm compare`
   - 在已经统一的 authority/canonical row 语义上，进一步对比：
     - controller hotspot
     - home-stack locality
     - runtime pressure transfer
     - direct vs bundle 的 memory pressure 放大效应

3. `Priority 3: runtime policy co-design`
   - 把 `runtime adaptive` 从“authority migration exemplar”进一步推进到：
     - 面向 controller pressure / home-stack skew / vertical penalty 的联动策略观察面

### Fresh Verification Evidence

当前这轮收口的 fresh targeted verification 为：

```bash
cd "/home/xgy/remote"
python3 -m unittest snn3dexp.tests.test_ablation_contract -v
python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics -v
python3 -m unittest snn3dexp.tests.test_memory_nmc_codesign_surface -v
python3 -m unittest snn3dexp.tests.test_export_memory_nmc_route_runtime_diff -v
python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v
python3 -m unittest snn3dexp.tests.test_fixed_step_sweep -v
```

结果：

1. `test_ablation_contract`: 17 tests passed
2. `test_synapse_memory_semantics`: 8 tests passed
3. `test_memory_nmc_codesign_surface`: 20 tests passed
4. `test_export_memory_nmc_route_runtime_diff`: 3 tests passed
5. `test_run_memory_nmc_codesign_matrix`: 14 tests passed
6. `test_fixed_step_sweep`: 5 tests passed
7. 合计：67 tests passed
