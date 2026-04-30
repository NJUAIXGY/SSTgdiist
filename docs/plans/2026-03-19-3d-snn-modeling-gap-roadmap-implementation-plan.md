# 3D SNN Modeling Gap Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在已落地的 `Phase-2` baseline/mapping/thermal 闭环之上，继续推进最有论文价值的剩余建模工作：真正的 `3D-native route synthesis`、面向 synapse 语义的 memory flow、`HBM-like` 与 `monolithic-like` 双范式对照、以及 runtime/physical realism 联合建模。

**Architecture:** 本计划不重复 `docs/plans/2026-03-18-3d-snn-modeling-innovation-design.md` 中已经完成的部分，而是先对齐“设计文档 vs 当前代码”的真实状态，再只针对剩余高价值缺口展开。执行顺序保持 `C++ 路由内核 -> memory 业务语义 -> runtime 联合优化 -> physical realism v2 -> workload/methodology`，继续遵守 `SnnDL` 与 `snn3dexp/` 双侧隔离原则。

**Tech Stack:** C++17、SST/SnnDL、Python 3、`unittest`、memHierarchy、ramulator2、`snn3dexp/`

---

## Current Alignment Matrix

| Layer | 当前状态 | 直接证据 | 剩余核心缺口 |
| --- | --- | --- | --- |
| Layer 1: Full 3D Multicast Kernel | 部分完成 | `MulticastRouter3DNative` 已有 volumetric intra/inter forwarding；`SynapseRouteSubsystem3D` 已有 3D target 组织 | source-side fanout synthesis 仍依赖 legacy route map，尚未成为完全 3D-native 内核 |
| Layer 2: Real Synapse-to-Stack Data Path | 部分完成 | `snn3dexp/memory/hbm_stack.py` 已输出 `synapse_sources`，phase2 runtime 已有 `real_synapse_sources` | 仍偏 `traffic_mem`/smoke 口径，缺少 `synapse gather / metadata lookup / sparse window` 的细粒度业务分类 |
| Layer 3: 3D-Aware Mapping and Placement | 第一阶段完成 | `snn3dexp/mapping/policy.py`、`full_3d_mapping`、`full_3d_thermal_guard` 已闭环 | 仍是静态 heuristic，缺少 runtime remap / dynamic homing / adaptive control |
| Layer 4: Thermal and Physical-3D Proxy | 第一阶段完成 | `snn3dexp/thermal/proxy.py` 已输出 `thermal_hotspot_score / vertical_link_pressure / stack_hotspot_penalty` | 仍缺 power-to-thermal RC、vertical budget、TSV/MIV proxy、reliability proxy |
| Layer 5: Unified Evaluation Methodology | 部分完成 | `analyze_ablation.py`、`phase2_case_summary.json`、paper artifacts 已形成统一摘要 | 长窗口 workload、真实拓扑统计、sensitivity sweep 仍不足 |
| Layer 6: Paper-Ready Baseline Suite | 已完成 | `baseline_2d / memory_only_3d / noc_only_3d / full_3d / full_3d_mapping / full_3d_thermal_guard` 均已纳入 phase2 suite | 后续只需扩展新的 baseline，不必重做基础套件 |

## Priority Order

`P0`
- 把 `3D-aware extension` 升级成真正的 `3D-native multicast architecture`
- 把 memory 从“能通路”升级成“有 synapse 业务语义”

`P1`
- 引入 `HBM-like NMC` 与 `monolithic-like tier-local memory proxy` 的双范式对照
- 引入 runtime 级 `mapping + homing + thermal` 联动

`P2`
- 引入 physical realism v2 与更强 workload/methodology
- 为论文主图准备长窗口、敏感性和可重复基线

## Non-Goals

- 不追求 fabrication-accurate 的 monolithic 3D DRAM 仿真
- 不把主线转成 PIM 论文
- 不重写 legacy 2D router / legacy route subsystem
- 不在未完成 `P0` 前提前扩散太多物理细节

### Task 1: 把 `SynapseRouteSubsystem3D` 升级成真正的 3D-native route synthesis

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ISynapseRoute.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
- Test: `snn3dexp/tests/test_route3d_native_fanout_contract.py`
- Test: `snn3dexp/tests/test_cpp_route_decoupling_contract.py`

**Step 1: 强化失败测试**
- 扩展 `test_route3d_native_fanout_contract.py`，锁定：
  - `computeFanout()` 主路径不再依赖 legacy route map
  - 3D target synthesis 直接输出 `block_z / ingress_node / volumetric mask`
  - `4x4x1` 保留 compat fallback

**Step 2: 跑 focused test 确认当前差距**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_cpp_route_decoupling_contract -v`
- Expected: 先出现 contract 缺口，证明当前仍是“3D-aware 扩展层”

**Step 3: 写最小实现**
- 将 `SynapseRouteSubsystem3D` 拆成：
  - legacy compat fanout path
  - native 3D fanout synthesis path
- 在 native path 中直接完成：
  - volumetric block grouping
  - ingress selection
  - vertical subtree-aware replication seed generation

**Step 4: 运行验证**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_cpp_route_decoupling_contract -v`
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Expected: PASS，且 SnnDL 编译通过

### Task 2: 补齐真正的 3D multicast statistics 和 correctness suite

**Files:**
- Create: `snn3dexp/tests/test_route3d_multicast_metrics.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.cc`
- Modify: `snn3dexp/tools/analyze_route_memory_joint.py`
- Modify: `snn3dexp/tools/analyze_ablation.py`
- Modify: `snn3dexp/tests/test_route_memory_joint_analysis.py`

**Step 1: 先写失败测试**
- 锁定新增指标：
  - `inter_die_multicast_fanout`
  - `ingress_replication_cost`
  - `die_local_replication_cost`
  - `average_vertical_subtree_depth`

**Step 2: 跑 test 确认当前统计面板不够**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_multicast_metrics snn3dexp.tests.test_route_memory_joint_analysis -v`
- Expected: FAIL，说明当前 phase2 summary 还缺真正的 3D multicast 指标

**Step 3: 写最小实现**
- 在 router 端记录 inter/intra/vertical replication counters
- 在 joint analysis 中汇总 route-level volumetric statistics
- 在 ablation summary 和 paper artifact 中保留这些字段

**Step 4: 运行验证**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_multicast_metrics snn3dexp.tests.test_route_memory_joint_analysis snn3dexp.tests.test_phase2_baseline_suite -v`
- Expected: PASS

### Task 3: 把 memory path 从 `traffic_mem` 提升到 synapse-semantic 建模

**Files:**
- Create: `snn3dexp/tests/test_synapse_memory_semantics.py`
- Modify: `snn3dexp/memory/hbm_stack.py`
- Modify: `snn3dexp/platform/sst_graph.py`
- Modify: `snn3dexp/tools/analyze_route_memory_joint.py`
- Modify: `snn3dexp/tools/analyze_stack_nmc.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Test: `snn3dexp/tests/test_synapse_home_stack_runtime.py`

**Step 1: 先写失败测试**
- 锁定三类请求统计口径：
  - `tier_local_home_access`
  - `same_xy_cross_tier_access`
  - `remote_home_access`
- 同时区分：
  - `synapse_gather_reads`
  - `metadata_lookup_reads`
  - `sparse_window_streams`

**Step 2: 跑 test 确认当前只有粗粒度内存请求**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_synapse_home_stack_runtime -v`
- Expected: FAIL，说明当前 memory path 还没有业务语义分类

**Step 3: 写最小实现**
- 在 processing/memory summary 中引入请求分类
- 在 `route_memory_joint_summary.json` 中汇总三类 home distance 指标
- 保持 legacy case 的字段兼容，空缺时回退到 `0`

**Step 4: 运行验证**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_synapse_home_stack_runtime snn3dexp.tests.test_route_memory_joint_analysis -v`
- Run: `cd /home/xgy/remote && python3 -m snn3dexp.tools.run_case full_3d --run-tag taskX_synapse_semantics_smoke --sst-smoke --stop-at 250ns`
- Expected: PASS，并在 joint summary 中看到新的 memory semantic fields

### Task 4: 新增 `monolithic-like tier-local memory proxy` 作为对照范式

**Files:**
- Create: `snn3dexp/memory/monolithic_proxy.py`
- Create: `snn3dexp/tests/test_monolithic_memory_proxy.py`
- Create: `snn3dexp/cases/full_3d_monolithic_proxy/case.json`
- Create: `snn3dexp/cases/full_3d_monolithic_proxy/spec.json`
- Modify: `snn3dexp/memory/__init__.py`
- Modify: `snn3dexp/platform/build_system.py`
- Modify: `snn3dexp/platform/sst_graph.py`
- Modify: `snn3dexp/tests/test_case_catalog.py`
- Modify: `snn3dexp/tests/test_phase2_baseline_suite.py`

**Step 1: 先写失败测试**
- 锁定新范式具有：
  - 更低 vertical attach latency proxy
  - 更强 vertical bandwidth ceiling
  - 更敏感的 thermal/stack penalty
- 同时保证它不是 PIM，而是 memory hierarchy proxy

**Step 2: 跑 test 确认当前 case catalog 不支持该范式**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_monolithic_memory_proxy snn3dexp.tests.test_case_catalog -v`
- Expected: FAIL

**Step 3: 写最小实现**
- 在 `memory/` 下新增独立 proxy module，不污染现有 `hbm_stack.py`
- 新 baseline 与现有 `full_3d`、`memory_only_3d` 共存
- 在 platform summary 中明确 `memory_model_family = hbm_like | monolithic_like`

**Step 4: 运行验证**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_monolithic_memory_proxy snn3dexp.tests.test_case_catalog snn3dexp.tests.test_phase2_baseline_suite -v`
- Run: `cd /home/xgy/remote && python3 -m snn3dexp.tools.run_case full_3d_monolithic_proxy --run-tag taskX_monolithic_proxy_compose`
- Expected: PASS，并产出新的 baseline summary

### Task 5: 把 mapping 扩展到 runtime co-design

**Files:**
- Create: `snn3dexp/runtime/__init__.py`
- Create: `snn3dexp/runtime/policy.py`
- Create: `snn3dexp/tests/test_runtime_3d_policy.py`
- Modify: `snn3dexp/mapping/policy.py`
- Modify: `snn3dexp/platform/build_system.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/tools/analyze_ablation.py`
- Create: `snn3dexp/cases/full_3d_runtime_adaptive/case.json`
- Create: `snn3dexp/cases/full_3d_runtime_adaptive/spec.json`

**Step 1: 先写失败测试**
- 锁定 runtime policy 可消费：
  - `route_memory_overlap`
  - `vertical_link_pressure`
  - `stack_hotspot_penalty`
- 并能输出：
  - `remap_epoch`
  - `homeroute_adjustment_count`
  - `thermal_guard_actions`

**Step 2: 跑 test 确认当前只有静态 mapping summary**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_runtime_3d_policy snn3dexp.tests.test_mapping_3d_policy -v`
- Expected: FAIL

**Step 3: 写最小实现**
- 引入 epoch-based runtime policy 接口
- 先用 rule-based runtime policy，不急着上搜索/优化器
- 将 runtime action 记入 summary，而不是直接改动 legacy timing contract

**Step 4: 运行验证**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_runtime_3d_policy snn3dexp.tests.test_mapping_3d_policy snn3dexp.tests.test_thermal_proxy -v`
- Run: `cd /home/xgy/remote && python3 -m snn3dexp.tools.run_case full_3d_runtime_adaptive --run-tag taskX_runtime_adaptive_compose`
- Expected: PASS

### Task 6: 引入 physical realism v2

**Files:**
- Create: `snn3dexp/physical/__init__.py`
- Create: `snn3dexp/physical/proxy.py`
- Create: `snn3dexp/tests/test_physical_proxy_v2.py`
- Modify: `snn3dexp/thermal/proxy.py`
- Modify: `snn3dexp/tools/analyze_ablation.py`
- Modify: `snn3dexp/tools/export_phase2_paper_artifacts.py`
- Modify: `snn3dexp/tests/test_phase2_paper_artifacts.py`

**Step 1: 先写失败测试**
- 锁定新增 proxy：
  - `vertical_bandwidth_budget`
  - `tsv_miv_budget_pressure`
  - `power_density_score`
  - `reliability_penalty`

**Step 2: 跑 test 确认当前 thermal proxy 仍是 v1**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_physical_proxy_v2 snn3dexp.tests.test_thermal_proxy -v`
- Expected: FAIL

**Step 3: 写最小实现**
- 继续保持 `proxy model` 定位
- 让 physical v2 依赖现有 route/memory/mapping summary，而不是另起一套统计链
- 在 paper artifacts 中输出 realism guard 对比字段

**Step 4: 运行验证**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_physical_proxy_v2 snn3dexp.tests.test_thermal_proxy snn3dexp.tests.test_phase2_paper_artifacts -v`
- Expected: PASS

### Task 7: 完成长窗口 workload/methodology 扩展

**Files:**
- Create: `snn3dexp/tests/test_long_window_methodology.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/tools/analyze_ablation.py`
- Modify: `snn3dexp/tools/export_phase2_paper_artifacts.py`
- Modify: `snn3dexp/tests/test_phase2_baseline_suite.py`
- Modify: `snn3dexp/tests/test_phase2_paper_artifacts.py`

**Step 1: 先写失败测试**
- 锁定：
  - 支持 `250ns` 以上的长窗口运行标签
  - 支持 workload sweep / scale sweep / sparsity sweep 的统一摘要
  - baseline 报告保留 `saturation point` 与趋势字段

**Step 2: 跑 test 确认当前 methodology 偏短窗 smoke**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_long_window_methodology snn3dexp.tests.test_phase2_baseline_suite snn3dexp.tests.test_phase2_paper_artifacts -v`
- Expected: FAIL

**Step 3: 写最小实现**
- 保留现有 short smoke 用于回归
- 额外增加 long-window suite 和 sensitivity summary
- 输出更贴近论文主图的趋势指标，而不是只给单点摘要

**Step 4: 运行验证**
- Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_long_window_methodology snn3dexp.tests.test_phase2_baseline_suite snn3dexp.tests.test_phase2_paper_artifacts -v`
- Run: `cd /home/xgy/remote && python3 -m snn3dexp.tools.run_case --phase2-suite --run-tag taskX_long_window --sst-smoke --stop-at 2us`
- Expected: PASS，长窗口 summary 和 paper artifacts 同步生成

## Deliverable Mapping

`P0`
- Task 1
- Task 2
- Task 3

`P1`
- Task 4
- Task 5

`P2`
- Task 6
- Task 7

## Recommended Paper Angle After This Plan

若只完成 `P0`：
- `3D Native Multicast Semantics for Stacked Neuromorphic Fabrics`

若完成 `P0 + P1`：
- `Co-Design of 3D Routing, Memory Homing, and Runtime Control for Stacked Spiking Neural Network Systems`

若完成 `P0 + P1 + P2`：
- `A Device-Informed Architecture-Level 3D Neuromorphic Modeling Platform`

## Exit Criteria

- `P0` 结束时：我们不再只是“有 3D router”，而是拥有真正 `3D-native multicast architecture`
- `P1` 结束时：我们能定量比较 `HBM-like` 与 `monolithic-like` memory 范式，并展示 runtime co-design 收益
- `P2` 结束时：我们具备论文主图、附录和 realism guard 所需的完整方法学
