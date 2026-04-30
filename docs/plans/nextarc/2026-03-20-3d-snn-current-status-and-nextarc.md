# 3D SNN 当前现状与 NextArc 代码对齐总览

Date: 2026-03-22
Owner: Fufu
Status: Refreshed after `arc4_refresh_20260321` + `fixed_step_window_route_memory` + `hotspot_real_phase9_independent_proxy_20260320_224300` + `balanced_20us_overlay_perf20` + `hotspot_real_phase9_independent_proxy_20260320_224300_codesign_refresh` + `codesign_canonical_20us` + `codesign_canonical_20us_default_export` + `codesign_single_20us_20260322` + `controller_runtime_refresh_20260322_windowed_snapshot_stop_overlap` + `controller_runtime_refresh_20260322_windowed_snapshot_real_home_flow`

Note:
`2026-03-23` 的最新代码对齐刷新见 `docs/plans/nextarc/2026-03-23-3d-snn-status-refresh-and-nextarc.md`。
本文保留为 `2026-03-22` 时点的历史快照。

## 1. 文档目的

这份文档用于把当前 `3D SNN` 平台的真实状态重新压回代码事实。

它服务四个目标：

1. 说明 `snn3dexp + SnnDL` 当前到底已经落地了哪些 3D 芯片建模能力。
2. 区分“代码已经有能力”和“历史 artifact 还没全部刷新到最新 schema”这两件事。
3. 给出一份对当前 `3dsnn` 全貌的统一视图，而不是继续按零散 task/tag 回忆上下文。
4. 基于当前代码边界，为下一阶段的 `next arc` 收敛真正值得投入的体系结构方向。

这份文档建议与下列文档配套阅读：

- `docs/plans/nextarc/2026-03-21-snn3d-chip-nextstep-architecture-modeling-design.md`
- `TECH_PROGRESS.md`
- `snn3dexp/tools/run_case.py`
- `snn3dexp/tools/analyze_fixed_step_sweep.py`
- `snn3dexp/tools/export_phase2_paper_artifacts.py`
- `snn3dexp/platform/build_system.py`
- `snn3dexp/platform/sst_graph.py`
- `snn3dexp/memory/hbm_stack.py`
- `snn3dexp/memory/monolithic_proxy.py`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.cc`

## 2. 一页结论

当前 `3D SNN` 已经不是“3D 想法的原型拼装”，而是一个真实的：

`device-informed, architecture-level, 3D neuromorphic co-design platform`

它已经具备 7 个真正落地的能力面：

1. 真实 `WxHxZ` 物理拓扑与 `SST object graph`
2. 真实 `3D native route interface + native fanout path + volumetric block target synthesis`
3. 真实 `legacy_per_pe / hbm_like / monolithic_like` 三种 memory 范式建模
4. 真实 `traffic_mem` 与 `windowed SNN` 两类 processing/runtime 入口，以及 `direct_v4 / bundle_v3 / monolithic_like` 的窗口化对照
5. 真实 `route_memory_joint / stack_nmc / phase2_case_summary / fixed-step sweep / paper artifacts` 分析链
6. 真实 `thermal proxy + RC replay/state + HotSpot sidecar + runtime execute v1` 观测与控制链
7. 独立的 `snn3dexp` case catalog、baseline suite、extended sweep 与 artifact refresh 流程

但它距离“更真实的 3D SNN 芯片模型”还有 6 个明确边界：

1. `route3d` 现在已经是接口级 3D，但 route source semantics 仍主要来自 `edges_csv` 或 legacy-built route tables；它还不是默认由真实 `synapse/BCSR/GAS` source semantics 驱动的内核。
2. `SynapseRouteSubsystem3D` 已具备 native table / native fanout / native target synthesis，但仍保留明显的 legacy bootstrap 结构，因此更准确的定位是“3D-native route kernel with bootstrap dependency”，不是完全脱离 legacy 的全新路由后端。
3. `windowed SNN` 已经不再只是 baseline 存在性问题，fixed-step 4/8/16-step sweep 也已经闭环；当前主缺口转成如何把 `traffic_mem` 基线、`windowed SNN` 固定步 sweep、`bundle/direct/monolithic` 对照合成统一 memory/NMC compare surface。
4. `HBM-like` 与 `monolithic_like` 已是平台原生 memory paradigm，但它们仍然是 near-memory hierarchy / proxy compare，而不是带真实近存算子执行的数据通路级 PIM/NMC 实现。
5. `arc4_hotspot_refresh_20260321` 与 `hotspot_real_phase9_independent_proxy_20260320_224300` 已让真实 HotSpot 进入 canonical thermal evidence；但 runtime control 仍主要由 proxy/joint signals 驱动，HotSpot 还没有成为大规模 case 的正式闭环控制输入。
6. 历史 `analysis/*` 目录中仍有不少产物早于当前 schema，旧 artifact 缺字段不能被误解为代码缺能力；判断平台边界时必须优先看当前代码、当前测试和 fresh artifact。

因此，下一阶段最值得投入的主线已经从“功能存在性补齐”切换为：

`以 memory/NMC + co-design 为主线的统一 compare surface -> 把 route kernel 从 bootstrap 推向更真实 synapse-native source semantics -> 在 HotSpot-enabled canonical artifacts 上扩大 thermal-aware execute loop`

## 3. 当前代码版图

### 3.1 `snn3dexp/` 已经是一套独立平台，而不是几个脚本

当前 `snn3dexp/` 目录已经形成清晰分层：

- `mesh3d_template/`
  - schema/default/spec/runtime 归一化入口
- `platform/`
  - effective config、platform summary、SST graph 生成
- `noc/`
  - 3D router descriptor 与 link descriptor
- `memory/`
  - `hbm_like` / `monolithic_like` / `legacy_per_pe` memory graph 与 binding
- `mapping/`
  - placement/target selection 与 mapping summary
- `runtime/`
  - adaptive summary policy
- `thermal/`
  - proxy thermal、RC replay/state、HotSpot adapter/driver、runtime signals
- `physical/`
  - physical proxy v2
- `tools/`
  - `run_case.py`、`analyze_route_memory_joint.py`、`analyze_stack_nmc.py`
- `tests/`
  - route、mapping、topology、memory、thermal、run_case 等合同测试

这意味着：

- `3dsnn` 现在已经有独立的 schema、builder、runtime、analyzer、tests
- 新能力不是散落在临时脚本，而是持续沉淀为平台层接口

### 3.2 case catalog 已经覆盖多个主问题面

当前 case 目录中已经形成 `13` 个显式 case：

- `baseline_2d`
- `memory_only_3d`
- `noc_only_3d`
- `full_3d`
- `full_3d_mapping`
- `full_3d_runtime_adaptive`
- `full_3d_thermal_guard`
- `full_3d_monolithic_proxy`
- `full_3d_snn_window`
- `full_3d_snn_window_bundle_v3`
- `full_3d_snn_window_monolithic_proxy`
- `full_3d_tile_bundle_v3`
- `noc_only_3d_bundle_fault_v3`

这说明平台当前已经不只是：

- 2D/3D 对照

而是已经具备：

- route-only / memory-only / full-stack 消融
- `HBM-like` / `monolithic-like` memory 范式对照
- `traffic_mem` / `windowed SNN` workload 入口对照
- route packet/bundle 版本对照
- thermal/runtime guard 侧车对照

### 3.3 3D 能力已经深入到 `SnnDL C++` 主体

当前最关键的 C++ 入口包括：

- `api/ISynapseRoute.h`
- `services/synapse/route3d/SynapseRouteSubsystem3D.*`
- `components/noc3d/MulticastRouter3DNative.*`
- `services/workload/traffic/TrafficWorkload.cc`
- `services/workload/snn/SnnWorkload.cc`
- `components/MultiCorePE.h`
- `components/workload_stats/StreamWorkloadStatsModule.h`
- `components/workload_stats/SnnWorkloadStatsModule.h`

这意味着 3D 不是只存在于 Python builder，也不是只存在于 analysis 层，而是已经进入：

- route interface
- source-side fanout path
- packet/block contract
- workload stats export
- real SST smoke runtime

## 4. 已经真正落地的能力

### 4.1 3D topology 与 object graph 已经是正式能力

`snn3dexp/shape3d.py`、`noc/multicast_3d.py` 和 `platform/sst_graph.py` 已经把 `WxHxZ` 拓扑变成统一底座：

- `MeshShape3D`
- `SnnDL.MulticastRouter3DNative` / `SnnDL.MulticastRouter`
- east/south/up 连接关系
- processing nodes
- memory graph
- control plane nodes/links

尤其是 `platform/sst_graph.py` 中：

- `native_3d_enable && dim_z > 1` 时自动使用 `SnnDL.MulticastRouter3DNative`
- `workload_impl=snn` 且 windowed SNN 条件成立时，会生成：
  - `GatherBufferIF`
  - `GlobalGasStepController`
  - `global_step` 控制链路

所以当前平台不能再被描述成“只有 3D router，没有真实 object graph”。

### 4.2 route kernel 已经不是只有 3D transport

当前 route 面最重要的真实事实有 5 个：

1. `ISynapseRoute::BlockTarget` 已显式携带：
   - `block_z`
   - `block_d`
   - `ingress_node`
   - `core_mask`
2. `SynapseRouteSubsystem3D::tryInitNativeRoutes_()` 会在：
   - `routing_weight_driven`
   - `route3d_native_targets`
   - `mesh_dim_z > 1`
   时启用 native 3D route synthesis。
3. 当前已有两条 native bootstrap 路径：
   - `buildNativeRoutesFromEdgesCsv3D_()`
   - `buildNativeRoutesFromLegacyBuiltRoutes3D_()`
4. `computeFanoutNative3D_()` 在 native 路径上直接使用本地 native route table 与 gating cache，不再回退 `fanout_provider_.computeFanout(...)` 主路径。
5. `computeMulticastTargetsNative3D_()` 已按真实 `WxHxD` volumetric block 生成 3D multicast target，而不是只做 2D compat block。

这说明当前 route 面最准确的判断是：

- `3D transport substrate`: 已完成
- `3D packet/block contract`: 已完成
- `native source-side fanout path`: 已落地
- `native volumetric target synthesis`: 已落地
- 但 native path 仍是 `edges_csv` bootstrap，不是默认真实 synapse source kernel

### 4.3 route3d structured runtime stats 已正式产出

这是最近一轮最重要的收口点之一。

当前链路已经打通为：

`SynapseRouteSubsystem3D native runtime counters -> Workload raw stats -> MultiCorePE keyed stats -> sst_stats.csv -> phase2_case_summary.route_kernel`

代码层面包括：

- `ISynapseRoute::RouteRuntimeStatSinks`
- `SynapseRouteSubsystem3D::recordNativeRuntimeStats_()`
- `TrafficWorkload` / `SnnWorkload` 导出：
  - `route3d_native_activation_total`
  - `route3d_native_gating_activation_total`
  - `route3d_native_direct_activation_total`
  - `route3d_native_unique_sources_total`
- `MultiCorePE` 统计声明与 keyed counter stats module
- `run_case.py` 优先从 `sst_stats.csv` 聚合 structured route3d runtime stats

最新 fresh smoke：

- case: `full_3d`
- run tag: `task_route3d_structured_runtime_stats_v5`

已经确认：

- `phase2_case_summary.route_kernel.actual_activation_observed = true`
- `actual_activation_source = "sst_stats_route3d_native_runtime"`
- `runtime_activation_total = 512`
- `runtime_activation_direct_total = 512`
- `runtime_activation_gating_total = 0`
- `runtime_unique_sources_total = 109`

这意味着 `route3d-native-runtime` 已经从 debug marker 升级为正式统计输入。

### 4.4 memory 范式已经是 builder/runtime/analyzer 三层共享的一等对象

`mesh3d_template/spec.py` 当前已经把以下 memory kind 作为正式 schema：

- `legacy_per_pe`
- `hbm_like`
- `monolithic_like`

它们不再只是 compare case 标签，而是 builder/runtime/analyzer 的原生维度。

`memory/hbm_stack.py` 已经正式建模：

- shared stack
- `xy_quadrant` home policy
- `stack_attach_latency_ns`
- `vertical_mem_hop_latency_ns`
- semantic regions:
  - `metadata`
  - `gather`
  - `stream`
  - `writeback`
- `build_node_memory_bindings()`
- `build_synapse_source_descriptors()`

`memory/monolithic_proxy.py` 已经正式建模：

- per-tier local stack
- `num_stacks_per_tier`
- `xy_quadrant_local_tier`
- `tier_local_stack_attach_latency_ns`
- `vertical_mem_hop_latency_ns = 0`
- 与 shared stack 兼容的 semantic binding fields

因此当前最准确的说法是：

- `HBM-like` 与 `monolithic-like` 已经是平台原生 memory paradigm
- 它们不是一次性的 side experiment

### 4.5 processing/workload 已经不是“只有 traffic_mem”

当前 processing path 可以分成两条真实主线：

#### A. `traffic_mem`

这是当前最成熟、最稳定的 canonical baseline。

优势在于：

- case 最完整
- smoke 最稳定
- `route_memory_joint` / `stack_nmc` / `phase2_case_summary` artifact 最完整
- 最适合做 `HBM-like vs monolithic-like`、`direct_v4 vs bundle_v3` 等对照

#### B. `windowed SNN`

这条路径已经真实存在，不应该再被描述成“还没有”：

- `cases/full_3d_snn_window/spec.json`
- `cases/full_3d_snn_window_monolithic_proxy/spec.json`
- `workload_impl = "snn"`
- `enable_weight_fetch = 1`
- `gas_enable = 1`
- `gas_window_mode = 1`
- `apply_acc_enable = 1`
- `window_read_enable = 1`

同时：

- `platform/sst_graph.py` 能为它生成 `GatherBufferIF`
- 条件满足时能生成 `GlobalGasStepController`
- `SnnWorkload.cc` 已导出：
  - weight read counters
  - GAS runtime counters
  - semantic memory counters
  - route3d runtime counters

更准确的现状应该写成：

- `traffic_mem` 仍是最成熟的 compare anchor
- `windowed SNN` 已经完成 fresh `arc4_refresh_20260321` smoke，并以 `HBM-like` / `monolithic-like` 两个 case 正式进入 `arc4_baseline_compose_20260321` 的 9-case baseline suite
- `windowed SNN` 的 extended compare 面也已经真实存在：
  - `full_3d_snn_window_bundle_v3`
  - `task_fixed_step_{4,8,16}_{10,20,40}us`
  - `task_fixed_step_{4,8,16}_{10,20,40}us_sp64`
- 当前剩余 gap 是统一 compare methodology 与 memory/NMC 解释面，而不是继续证明 `windowed SNN` baseline 是否存在

### 4.6 analysis/summaries 已经形成统一链路

当前平台已经形成统一输出面：

- `platform_summary.json`
- `runtime_summary.json`
- `stack_nmc_summary.json`
- `route_memory_joint_summary.json`
- `phase2_case_summary.json`
- `phase2_runtime_summary.json`
- `fixed_step_sweep_summary.json`

其中最关键的是：

- `analyze_stack_nmc.py`
  - `issue_efficiency`
  - `backlog_ratio`
  - `service_deficit`
  - `most_pressured_stack_id`
  - `most_pressured_region`
- `analyze_route_memory_joint.py`
  - `route_memory_overlap`
  - route multicast metrics
  - home access semantics
  - synapse request semantics
- `run_case.py`
  - 把 route kernel、runtime、thermal、hotspot sidecar、phase2 case summary 统一装配
- `export_phase2_paper_artifacts.py`
  - 把 baseline / route-memory / memory-model / thermal-calibration 输出成 `csv/md/tex/svg/json`
- `analyze_fixed_step_sweep.py`
  - 把 `4/8/16-step × baseline/sp64 × direct/bundle/monolithic` 收敛成：
    - `case_rows`
    - `bundle_breakdown`
    - `spike_sensitivity`
    - `*_amplification_ratio`
    - `*_delta_ratio`

这一步的重要性在于：

- 当前平台不只是能跑
- 还能把 route/memory/runtime/thermal 统一投影到同一 summary surface
- 并且已经开始具备可直接写论文表格和图的 artifact surface，而不是停留在 ad-hoc json

### 4.7 thermal / physical / runtime 观测链已经是真实存在的 co-design layer

`thermal/` 当前已经具备：

- proxy thermal synthesis
- RC online estimator
- window power replay
- thermal state cache
- runtime thermal signals
- HotSpot adapter payload
- HotSpot sidecar driver

`physical/proxy.py` 当前已经输出：

- `vertical_bandwidth_budget`
- `tsv_miv_budget_pressure`
- `power_density_score`
- `reliability_penalty`

`runtime/policy.py` 当前已经基于：

- `route_memory_overlap`
- `vertical_link_pressure`
- `stack_hotspot_penalty`

输出：

- `rebalance_home_route`
- `raise_vertical_penalty`
- `diffuse_stack_hotspot`

但必须诚实写明：

- 当前已经不是 `execute = False` 的 observe-only 状态
- `runtime/policy.py` + `run_case.py` 已经支持第一版 `window/global-step batch` 级 executable control
- `full_3d_runtime_adaptive/arc4_refresh_20260321` 已确认：
  - `control_decision = executed_control`
  - `executed_control = true`
  - 下一窗口已应用：
    - `mapping_route_weight = 1.25`
    - `mapping_stack_home_weight = 1.7625000000000002`
    - `mapping_vertical_penalty = 1.125`
- `hotspot_real_phase9_independent_proxy_20260320_224300` 已把 threshold provenance 带到：
  - `ablation.json`
  - `phase2_runtime_summary.json`
  - `phase2_runtime_focus_metrics.svg`
  - `phase2_thermal_calibration_compare.svg`
- 当前剩余边界变成：
  - execute loop 主要仍在 `full_3d_runtime_adaptive` 上闭环
  - HotSpot evidence 已进入 canonical thermal artifact，但尚未成为更广泛 case 的正式控制输入
  - thermal-aware control 还没有与 fixed-step `windowed SNN` memory/NMC compare surface 完整合流

## 5. 当前证据面与 artifact 新鲜度

### 5.1 当前最强证据来自“代码 + 合同测试 + fresh artifact”

当前最可信的现状依据不是单一旧 artifact，而是三类证据叠加：

1. 当前代码
2. 当前测试
3. 最新 fresh smoke

其中最近最关键的 fresh evidence 包括：

- `PHASE2_BASELINE_CASES = 9`
  - `baseline_2d`
  - `memory_only_3d`
  - `noc_only_3d`
  - `full_3d`
  - `full_3d_mapping`
  - `full_3d_thermal_guard`
  - `full_3d_monolithic_proxy`
  - `full_3d_snn_window`
  - `full_3d_snn_window_monolithic_proxy`
- `fixed_step_window_route_memory` sweep 已闭环：
  - `4/8/16-step`
  - `baseline/sp64`
  - `direct/bundle/monolithic`
  - summary/csv/json 全部落地在 `snn3dexp/analysis/sweeps/fixed_step_window_route_memory/`
- `phase2 paper artifacts` 已覆盖：
  - baseline route-memory compare
  - snn-window route-memory compare
  - memory-model compare
  - thermal calibration compare
- `codesign_single_20us_20260322`
  - 已把 `10` 个 canonical traffic/memory case 刷到同一个 fresh run tag：
    - `baseline_2d`
    - `memory_only_3d`
    - `noc_only_3d`
    - `full_3d`
    - `full_3d_monolithic_proxy`
    - `full_3d_mapping`
    - `full_3d_thermal_guard`
    - `full_3d_runtime_adaptive`
    - `full_3d_tile_bundle_v3`
    - `noc_only_3d_bundle_fault_v3`
  - `memory_only_3d`、`noc_only_3d`、`noc_only_3d_bundle_fault_v3` 现在不再只是旧 compose / mixed-tag 证据，而是同 tag `smoke_passed` fresh runtime artifact
- `hotspot_real_phase9_independent_proxy_20260320_224300`
  - 已把真实 HotSpot steady-state compare 与 threshold provenance 收敛到 paper artifact surface

因此当前“是否存在能力”的判断，优先级应该是：

`当前代码 > 当前合同测试 > fresh artifact > 历史 artifact`

### 5.2 历史 artifact 缺字段，不等于功能不存在

当前必须明确一个很容易混淆的问题：

- `analysis/*` 下很多历史目录早于当前 `phase2_case_summary` / `runtime_summary` schema
- 因此老目录里出现 `None`、缺字段、缺 structured stats，不应被解释成“代码没有这个能力”

更准确的解释是：

- 代码能力已经前进
- 但不是所有历史 run 都被重新刷新到了当前 schema

这也是为什么当前判断平台边界时，应优先参考：

- 当前 case spec
- 当前实现
- 当前测试
- fresh smoke

而不是只看旧 analysis 目录里的字段是否齐全。

### 5.3 `snn_window` / `runtime_adaptive` / `thermal_guard` 的现状应分开写

当前更准确的判断是：

- `full_3d`
  - 最新 smoke 与 summary 最完整
  - 当前最强证据面
- `full_3d_snn_window`
  - `arc4_refresh_20260321` 已 fresh `smoke_passed`
  - `route_memory_overlap = 0.75`
  - `stack_nmc_summary.totals.memory_requests_total = 234`
  - 已正式进入 9-case baseline suite
- `full_3d_snn_window_monolithic_proxy`
  - `arc4_refresh_20260321` 已 fresh `smoke_passed`
  - `stack_nmc_summary.totals.memory_requests_total = 416`
  - `stream_region_bytes_written_total = 8192`
  - `writeback_region_bytes_written_total = 3072`
  - 已正式进入 9-case baseline suite
- `full_3d_runtime_adaptive`
  - `arc4_refresh_20260321` 已确认 `executed_control = true`
  - `runtime_control_next_window.json` 已落地下一窗口参数
  - 当前是第一版 `window` 级 executable control，不再只是 action labels
  - 当前仍属于 extended control lane，而不是 9-case baseline suite 成员
  - `arc4_hotspot_refresh_20260321` 已 fresh `smoke_passed`
  - `platform/runtime/phase2` 三层摘要均已记录 `hotspot_driver_status = ran`
- `full_3d_thermal_guard`
  - `arc4_refresh_20260321` 已 fresh `smoke_passed`
  - thermal proxy / guard summary 已统一到当前 schema
  - `arc4_hotspot_refresh_20260321` 已 fresh `smoke_passed`
  - `platform/runtime/phase2` 三层摘要均已记录 `hotspot_driver_status = ran`
- `full_3d_snn_window`
  - `arc4_hotspot_refresh_20260321` 已 fresh `smoke_passed`
  - `platform/runtime/phase2` 三层摘要均已记录 `hotspot_driver_status = ran`
- `full_3d_snn_window_monolithic_proxy`
  - `arc4_hotspot_refresh_20260321` 已 fresh `smoke_passed`
  - `platform/runtime/phase2` 三层摘要均已记录 `hotspot_driver_status = ran`

### 5.4 `fixed-step windowed SNN` 已把 memory/NMC 讨论从“存在性”推进到“机理量化”

这是当前 3D SNN 全貌里最需要补进来的新结论。

当前 `snn3dexp/tools/analyze_fixed_step_sweep.py` 已经把：

- `full_3d_snn_window`
- `full_3d_snn_window_bundle_v3`
- `full_3d_snn_window_monolithic_proxy`

在：

- `4/8/16-step`
- `baseline/sp64`

两个维度上做成统一对照，并导出：

- `bundle_breakdown`
- `spike_sensitivity`
- `*_amplification_ratio`
- `*_delta_ratio`

这轮得到的最重要结论有 3 个：

1. `direct / monolithic_like` 在 `sp64` 下 `memory_requests_total` 仍不增长。
   - 这说明当前 plateau 不是 `GlobalGasStepController` 把步数卡死，而是 windowed SNN workload 本身先耗尽了可推进的计算窗口。
2. `bundle_v3` 在固定 step budget 下仍然稳定放大 memory pressure。
   - baseline `4-step`：
     - `memory_requests_total_delta = +604`
     - `memory_requests_total_amplification_ratio = 2.4519`
   - `sp64 4-step`：
     - `memory_requests_total_delta = +864`
     - `memory_requests_total_amplification_ratio = 3.0769`
   - `baseline -> sp64` 的 bundle sensitivity：
     - `4-step: +260`
     - `8-step: +284`
     - `16-step: +284`
     - `router_bundle_v3_rx_total_delta = +1285`
3. `monolithic_like` 的主要收益依然是 stall 下降，而不是 request 数下降。
   - 当前最准确的解释仍是：
     - `near-layer latency`
     - `vertical hop elimination`
     - `controller gate wait` 缓解
   - 而不是“monolithic 自动减少 memory request count”

这意味着：

- 现在最值钱的主线已经不是“route 面还能不能跑”
- 而是“bundle/direct/monolithic 为什么在 memory/NMC 面产生这些差异”

## 6. 当前成熟度分层

### Layer A: 基础设施与平台边界

状态：`已完成`

包括：

- `snn3dexp/` 隔离平台
- case catalog
- build/run/analyze/test 链路
- real SST smoke

这是当前最稳定的一层。

### Layer B: 3D topology / NoC / packet contract

状态：`大体完成`

包括：

- 3D mesh object graph
- `MulticastRouter3DNative`
- 3D packet/block contract
- explicit `block_z/block_d`

这层已经足够支撑架构研究。

### Layer C: route kernel

状态：`大体完成，但仍有一个关键边界`

已完成部分：

- native route table bootstrap
- native source-side fanout path
- native volumetric target synthesis
- structured runtime stats

剩余边界：

- 仍主要依赖 `edges_csv` 做 source route bootstrap
- 还没有把 native route kernel 推到真实 `synapse/BCSR/GAS` source semantics 的默认主路径

### Layer D: memory/NMC 建模

状态：`当前最成熟、且已经进入量化对照的一层`

包括：

- `HBM-like`
- `monolithic-like`
- semantic regions
- home access classes
- service deficit / stack pressure analysis

这是当前平台最强的研究面，而且已经不是抽象 builder 能力，而是有 fixed-step sweep / paper artifact / route-memory compare 支撑的量化研究面。

### Layer E: windowed SNN / GAS 路径

状态：`已完成第一阶段，并进入 canonical baseline + extended sweep`

包括：

- windowed SNN case
- `GatherBufferIF`
- `GlobalGasStepController`
- weight/GAS counters

当前主要问题已经不是“缺最新 canonical artifact”，而是：

- 如何把 `traffic_mem` / `windowed SNN` 的 compare surface 做成统一入口
- 如何把 `direct_v4 / bundle_v3 / monolithic_like` 的差异解释到 memory/NMC 机理层

### Layer F: runtime / thermal / physical co-design

状态：`runtime execute v1 已完成，HotSpot canonicalization 已落地，thermal-aware control 仍待扩大`

包括：

- thermal proxy / RC replay / HotSpot sidecar
- runtime recommendation
- physical proxy v2

当前边界在于：

- runtime 执行链已经在 `full_3d_runtime_adaptive` 上闭环
- HotSpot sidecar 已进入 fresh canonical thermal artifacts
- 但热约束还没有成为更广泛 case 的正式 execute-loop 输入

## 7. 当前平台“是什么”，以及“还不是什么”

### 7.1 当前它是什么

当前平台可以被准确地称为：

`面向 3D neuromorphic chip architecture co-design 的架构级研究平台`

它能支持的问题包括：

- 3D multicast contract 应如何定义
- 3D route kernel 如何组织 block/ingress/volumetric forwarding
- 不同 memory paradigm 如何改变 home access / stack pressure / service deficit
- route compression / packet style 如何影响 memory/NMC 压力分布
- runtime/thermal/physical proxy 如何作为架构约束进入 co-design

### 7.2 当前它还不是什么

当前平台还不能被写成：

- fabrication-accurate 3D chip simulator
- full-stack production neuromorphic runtime
- silicon-faithful thermal/power/reliability simulator
- 已 fully-online 的 adaptive runtime controller

这不是缺点，而是定位边界。

## 8. 下一阶段最值得投入的方向

### P0: 已完成的收口

这一轮已经完成：

1. `arc4_refresh_20260321`
   - 刷新 `full_3d_runtime_adaptive`
   - 刷新 `full_3d_snn_window`
   - 刷新 `full_3d_snn_window_monolithic_proxy`
   - 刷新 `full_3d_thermal_guard`
2. `arc4_baseline_compose_20260321`
   - 把 `full_3d_snn_window`
   - `full_3d_snn_window_monolithic_proxy`
   正式纳入 9-case baseline suite
3. `runtime_adaptive`
   - 从 `recommend-only` 升级为第一版 executable `window` control
4. `route3d`
   - native bootstrap 不再只由 `edges_csv` 单一路径 gating
5. `fixed_step_window_route_memory`
   - `4/8/16-step × baseline/sp64 × direct/bundle/monolithic` sweep 已闭环
   - ratio export 已落地
6. `hotspot_real_phase9_independent_proxy_20260320_224300`
   - HotSpot threshold provenance 已进入 summary 与图表

这意味着当前主线不再是“把四优先级补出来”，而是要把这批 fresh evidence 用成真正的架构建模基线。

### P1: 统一 `9-case baseline + fixed-step windowed SNN` compare surface

当前平台最大的研究收益点不是再证明一次 route feature，而是回答：

`traffic_mem` 上看到的 `home_access / service_deficit` 规律，能否迁移到真实 SNN 业务窗口。

因此下一步最有价值的是：

- 把 `traffic_mem` / `windowed SNN` 放进统一批处理 compare 入口
- 让 `HBM-like vs monolithic-like` 在 `windowed SNN` 路径上形成稳定表格和图层
- 让 `direct_v4 vs bundle_v3` 的 fixed-step 对照与 `phase2 paper artifact` 输出接轨
- 让 `stack_nmc_summary` / `route_memory_joint_summary` / `phase2_case_summary` / `fixed_step_sweep_summary` 的关键字段能被统一消费

2026-03-22 刷新后，这一项已经有了直接落地的统一入口：

- 已新增 `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
- 已把 `traffic_mem baseline + fixed-step windowed SNN + HotSpot runtime summary` 合成到同一导出面
- fresh artifact 已落在 `snn3dexp/analysis/codesign_surface/balanced_20us/`

因此 P1 当前的状态更准确地说是：

- “统一 compare/export entry” 已基本完成
- 剩余重点转为：
  - 补齐 `traffic_mem` baseline row 的指标丰富度
  - 把 unified surface 接到更正式的 paper/doc/export 链
  - 在这张 surface 上继续把 `bundle/direct/monolithic` 讲到 memory/NMC 机理层

2026-03-22 继续刷新后，这里的状态还需要再精确一点：

- unified surface 已支持 `baseline_overlay_ablation`
  - 可以用 richer `traffic_mem` ablation 为缺失 `route_memory_joint_summary` 的 baseline case 回填
    `metadata_lookup / synapse_gather / stream / writeback / home_access_class`
- `export_phase2_paper_artifacts.py` 已可选挂接 unified surface
  - 新生成的 `phase2_runtime_summary.json` 能直接引用
    `codesign_surface/memory_nmc_codesign_surface_*`
- overlay-rich fresh artifact 已经真实落地在：
  - `snn3dexp/analysis/codesign_surface/balanced_20us_overlay_perf20/`
  - 其中 `memory_nmc_codesign_surface_summary.json` 已包含：
    - `10` 条 `traffic_mem_baseline_rows`
    - `2` 条 `traffic_mem_compare_rows`
    - `9` 条 `window_baseline_rows`
    - `6` 条 `window_bundle_breakdown_rows`
    - `6` 条 `window_memory_model_breakdown_rows`
    - `9` 条 `window_spike_sensitivity_rows`
- richer baseline overlay 的关键信号已经不是“理论支持”，而是 fresh row 里直接可见：
  - `full_3d`
    - `route_semantic_overlay_applied = true`
    - `route_semantic_overlay_run_tag = perf_20us_route_refresh_v2`
    - `metadata_lookup_demands = 20000`
    - `synapse_gather_demands = 40000`
    - `stream_region_demands = 40000`
    - `writeback_region_demands = 20000`
    - `dominant_home_access_class = remote_home`
    - `remote_home_access_ratio = 0.5`
- `traffic_mem_bundle_vs_direct` 的 overlay compare row 也已经能直接支撑 memory/NMC 机理判断：
  - `memory_requests_total_delta = 0`
  - `total_service_deficit_delta = 207522`
  - 这说明当前 `bundle vs direct` 在这组 richer baseline 上最主要放大的不是 request count，而是 service deficit / pressure 面
- paper artifact refresh 也已经有真实一体化产物：
  - `snn3dexp/analysis/paper_artifacts/hotspot_real_phase9_independent_proxy_20260320_224300_codesign_refresh/phase2_runtime_summary.json`
  - 其中：
    - `memory_nmc_codesign_surface.available = true`
    - `traffic_mem_baseline_row_count = 4`
    - `traffic_mem_compare_row_count = 2`
    - `window_baseline_row_count = 9`
    - `window_bundle_breakdown_row_count = 6`
    - `window_memory_model_breakdown_row_count = 6`
    - `window_spike_sensitivity_row_count = 9`
- 2026-03-22 继续推进后，P1 已经不再只剩 overlay 路：
  - 已新增 canonical run-tag manifest：
    - `snn3dexp/configs/run_tag_manifests/codesign_canonical_20us.json`
  - 已基于该 manifest 生成更 canonical 的 mixed-tag baseline ablation：
    - `snn3dexp/analysis/codesign_canonical_20us_ablation.json`
  - 这份 ablation 现在直接把 richer route/memory 语义写进 baseline source，而不是等 unified surface 再 overlay：
    - `full_3d.run_tag = perf_20us_route_refresh_v2`
    - `full_3d.route_memory_joint_available = true`
    - `full_3d.route_memory_joint.metadata_lookup_demands = 20000`
    - `full_3d.route_memory_joint.dominant_home_access_class = remote_home`
    - `full_3d_tile_bundle_v3.run_tag = perf_20us`
    - `full_3d_monolithic_proxy.run_tag = perf_20us`
  - 已基于这份 canonical ablation 导出不依赖 overlay 的 fresh unified surface：
    - `snn3dexp/analysis/codesign_surface/codesign_canonical_20us/`
    - 其中：
      - `traffic_mem_baseline_rows = 10`
      - `traffic_mem_compare_rows = 2`
      - `window_baseline_rows = 9`
      - `window_bundle_breakdown_rows = 6`
      - `window_memory_model_breakdown_rows = 6`
      - `window_spike_sensitivity_rows = 9`
    - `full_3d` row 已确认：
      - `route_semantic_overlay_applied = false`
      - `metadata_lookup_demands = 20000`
      - `synapse_gather_demands = 40000`
      - `stream_region_demands = 40000`
      - `writeback_region_demands = 20000`
      - `dominant_home_access_class = remote_home`
      - `remote_home_access_ratio = 0.5`
    - `traffic_mem_bundle_vs_direct` compare row 也已直接来自 canonical ablation：
      - `memory_requests_total_delta = 0`
      - `total_service_deficit_delta = 207522`
      - `compare_source_run_tag = codesign_canonical_20us`
- `export_phase2_paper_artifacts.py` 现在也已经更接近默认链：
  - 若 `ablation_json` 位于 canonical `analysis/` 目录下，且存在
    `analysis/sweeps/fixed_step_window_route_memory/fixed_step_sweep_summary.json`
    就会自动推断 fixed-step summary 并导出 unified surface
  - 真实 fresh 产物：
    - `snn3dexp/analysis/paper_artifacts/codesign_canonical_20us_default_export/phase2_runtime_summary.json`
  - 其中：
    - `memory_nmc_codesign_surface.available = true`
    - `traffic_mem_baseline_row_count = 10`
    - `traffic_mem_compare_row_count = 2`
    - `window_baseline_row_count = 9`
    - `window_bundle_breakdown_row_count = 6`
    - `window_memory_model_breakdown_row_count = 6`
    - `window_spike_sensitivity_row_count = 9`
    - `memory_nmc_codesign_surface.sources.fixed_step_summary_path = analysis/sweeps/fixed_step_window_route_memory/fixed_step_sweep_summary.json`
- 2026-03-22 这轮又进一步把 canonical baseline 从 mixed-tag 推进成 single-tag fresh run：
  - 已新增 single-tag manifest：
    - `snn3dexp/configs/run_tag_manifests/codesign_single_20us_20260322.json`
  - 已跑通 `10` 个 canonical traffic/memory case 的同 tag fresh smoke：
    - tag: `codesign_single_20us_20260322`
    - 所有 case `status = smoke_passed`
  - `platform/sst_graph.py` 已修正 `noc_only_3d` 的 volumetric smoke bundle v1 entry 编码：
    - 3D volumetric block 现在在 v1 bundle wrapper 内使用 `WireSpikeKeyV4` route payload，而不再错误退化成 2D `WireSpikeKeyV2`
    - 这直接修复了 `noc_only_3d` single-tag fresh smoke 的 sink miss 问题
  - 已生成 fresh ablation：
    - `snn3dexp/analysis/codesign_single_20us_20260322_ablation.json`
  - 已生成 fresh unified surface：
    - `snn3dexp/analysis/codesign_surface/codesign_single_20us_20260322/`
    - 其中：
      - `traffic_mem_baseline_rows = 10`
      - `traffic_mem_compare_rows = 2`
      - `window_baseline_rows = 9`
      - `window_bundle_breakdown_rows = 6`
      - `window_memory_model_breakdown_rows = 6`
      - `window_spike_sensitivity_rows = 9`
    - `memory_only_3d` row 已确认：
      - `route_memory_joint_available = true`
      - `memory_requests_total = 58560`
      - `metadata_lookup_demands = 20000`
      - `dominant_home_access_class = remote_home`
      - `remote_home_access_ratio = 0.5`
    - `noc_only_3d` 与 `noc_only_3d_bundle_fault_v3` row 已确认：
      - `route_memory_joint_available = true`
      - `status = smoke_passed`
    - `traffic_mem_monolithic_vs_hbm` compare row 已直接来自 same-tag baseline：
      - `memory_requests_total_delta = 101184`
      - `total_service_deficit_delta = -50598`
      - `vertical_link_pressure_delta = -0.03820184426229509`
  - 已生成 default-path paper export：
    - `snn3dexp/analysis/paper_artifacts/codesign_single_20us_20260322_default_export/phase2_runtime_summary.json`
    - 其中：
      - `memory_nmc_codesign_surface.available = true`
      - `traffic_mem_baseline_row_count = 10`
      - `traffic_mem_compare_row_count = 2`
      - `window_baseline_row_count = 9`
      - `window_bundle_breakdown_row_count = 6`
      - `window_memory_model_breakdown_row_count = 6`
      - `window_spike_sensitivity_row_count = 9`
      - `memory_nmc_codesign_surface.hotspot_runtime_run_tag = codesign_single_20us_20260322`
  - `thermal_input_preparation.prepared_manifest` 也已不再混 tag：
    - `full_3d`
    - `full_3d_runtime_adaptive`
    - `full_3d_thermal_guard`
    都统一指向 `codesign_single_20us_20260322`

所以 P1 现在更接近：

- “统一 compare/export entry + mixed-tag canonical baseline + single-tag fresh canonical baseline + default-path paper integration” 已完成
- 剩余重点主要是：
  - 把 `bundle vs direct` 的 `service_deficit` 放大量继续拆到 `router_bundle_v3_rx / tx_bundle_v3 / semantic region backlog`
  - 把 `monolithic vs hbm` 的 `memory_requests_total_delta = 101184` 与 `total_service_deficit_delta = -50598` 解释成 locality / vertical-hop / controller-pressure 机理
  - 继续扩大 `export_phase2_paper_artifacts.py` 的默认链覆盖面，减少对显式路径参数的依赖

### P2: 深挖 memory/NMC 机理，而不是停留在 route feature 存在性

当前最应该优先回答的不是“还能再发明什么 router feature”，而是：

- bundle 的放大究竟沿哪条链展开：
  - `router_bundle_v3_rx_total`
  - `tx_bundle_v3_packets_total`
  - `gas_scatter_spikes_emitted_total`
  - `synapse_gather / stream / writeback`
- `HBM-like vs monolithic_like` 的 stall 优势究竟来自：
  - `home-stack locality`
  - `vertical hop elimination`
  - `controller gate wait`
- 哪些 memory/NMC 规律能从 `traffic_mem` 迁移到 `windowed SNN`

这一步做完，route/memory/workload 三者的 co-design 结论才会真正站稳。

### P3: 跑出第一份非 `edges_csv` 的 fresh route evidence

route 面接下来最值得补的不是更多 packet 变种，而是一个非常具体的缺口：

- [2026-03-24 status] 首个 canonical fresh 证据已拿到：
  - `full_3d_snn_window`
  - run tag: `p2_native_dense_smoke_20260324`
  - `mapping_mode = dense`
  - `phase2_case_summary.route_kernel.native_bootstrap_source = "legacy_route_tables"`
  - `phase2_case_summary.route_kernel.actual_activation_source = "sst_stats_route3d_native_runtime"`
  - `route_memory_joint_summary.route.source_semantics.primary_source_kind = "legacy_route_tables_with_real_synapse_inputs"`
  - `route_memory_joint_summary.route.source_semantics.native_synapse_source_candidate = true`
- 接下来要把这条 fresh evidence 从单个 direct-v4 canonical case 扩展到 bundle / monolithic / gating-heavy 变体
- 在 fresh artifact 里看到 `native_bootstrap_source != edges_csv`
- 再在此基础上继续逼近真实 `synapse/weight/BCSR/GAS` source semantics

同时建议补齐两类可解释性增强：

- `die_local / inter_die / vertical_subtree` 原生 runtime metrics
- 非 direct-dominant 场景下的 gating-heavy case，打亮 `route3d_native_gating_activation_total`

### P4: 把 HotSpot evidence 变成 thermal-aware execute loop 的正式输入

当前不缺“有没有 HotSpot”，缺的是：

- 把 HotSpot steady-state 结果与 proxy thermal 信号放进同一控制证据面
- 决定哪些 case 继续用 proxy 驱动、哪些 case 需要 HotSpot 参与决策
- 让 `runtime_adaptive` 从单 case 闭环扩展到更多 thermal-enabled canonical cases

### P5: 在以上主语义站稳后，再深化 topology/thermal/physical

热、物理和 topology 侧当前最正确的定位仍然是：

`co-design constraints over route/memory/runtime`

因此下一步不是先把 HotSpot 塞进 SST 主循环，而是：

- 基于真实 runtime counters 建立 block-level power trace
- 让 thermal/physical 更强地约束 route/memory/runtime 行为
- 再决定是否进入更细的 in-loop 热控制

## 9. 最终建议

如果要用一句话概括当前 `3dsnn` 的全貌：

`3D topology、3D route interface、memory paradigm、windowed SNN runtime、HotSpot artifact 和统一分析链都已经成型；下一阶段最该押注的，是用 memory/NMC + co-design 视角把这套 3D substrate 的机理讲透。`

## 10. 2026-03-22 基于当前代码的补充修正

这一节只根据当前代码和当前 fresh artifact 做补充，不再沿用早期口述结论。

### 10.1 `SnnDL` 侧的 3D multicast 现在已经是接口级语义

当前不应再把 3D multicast 描述成“实现层偷偷支持 3D、接口仍是 2D”。

代码复核显示：

- `api/ISynapseRoute.h`
  - `BlockTarget` 已正式携带：
    - `block_z`
    - `block_d`
    - `ingress_node`
    - `core_mask`
  - `RouteRuntimeStatSinks` 已把 `route3d_native_*` 统计做成正式接口合同
- `services/workload/snn/SnnWorkload.cc`
  - 在 `mesh_shape` 为多层、`synapse_route_impl = native_3d`、`multicast_block_d > 1` 时，会默认启用
    `route3d_native_targets`
  - 会把 `RouteRuntimeStatSinks` 绑定到 `synapse_route_`
- `services/synapse/route/SpikeCommSubsystem.cc`
  - `emitCommon_()` 已直接消费 `computeMulticastTargets(...)`
  - 会显式读取：
    - `multicastBlockW()`
    - `multicastBlockH()`
    - `multicastBlockD()`
  - 当 `target_block_d > 1` 时，已进入：
    - `BundleEntryV3`
    - 或 `WireSpikeKeyV4`
    的 3D block 编码路径

因此今天更准确的结论是：

- `ISynapseRoute -> SpikeCommSubsystem -> MulticastRouter3DNative`
  这条链已经能承载 3D block 语义
- 当前还没彻底完成的不是“接口 3D 化”，而是：
  - route source semantics 仍主要来自
    `edges_csv`
    或 legacy built route tables

### 10.2 `SynapseRouteSubsystem3D` 的准确定位是“3D-native kernel with bootstrap dependency”

`services/synapse/route3d/SynapseRouteSubsystem3D.cc` 当前已经明确具备：

1. `tryInitNativeRoutes_()`
   - 在 `routing_weight_driven`
   - `route3d_native_targets`
   - `mesh_shape.dim_z > 1`
   成立时启用 native 3D 路线
2. 两条 native bootstrap 路径：
   - `buildNativeRoutesFromEdgesCsv3D_()`
   - `buildNativeRoutesFromLegacyBuiltRoutes3D_()`
3. `computeMulticastTargetsNative3D_()`
   - 已通过 `synthesizeMulticastTargetsForBlockDepth_()` 按真实 `WxHxD` block 聚合 fanout
4. 真实 structured route runtime evidence
   - `snn3dexp/analysis/full_3d/task_route3d_structured_runtime_stats_v5/phase2_case_summary.json`
   - 已确认：
     - `actual_activation_observed = true`
     - `actual_activation_source = sst_stats_route3d_native_runtime`
     - `runtime_activation_total = 512`
     - `runtime_activation_direct_total = 512`
     - `runtime_unique_sources_total = 109`

所以今天最准确的表述已经不是：

- “3D route 还主要停留在 transport 层”

而是：

- native 3D route kernel 已经能工作并产出正式 runtime 统计
- 真正剩下的关键缺口是把 source semantics 从 bootstrap 输入继续前推到真实
  `synapse/BCSR/GAS` 主语义

### 10.3 `snn3dexp` 当前是完整平台，而不是若干分析脚本

当前代码复核确认：

- `mesh3d_template/spec.py`
  - `dim_z > 1` 时默认：
    - `native_3d_enable = true`
    - `synapse_route_impl = native_3d`
  - `memory.kind` 正式支持：
    - `hbm_like`
    - `monolithic_like`
    - `legacy_per_pe`
- `platform/sst_graph.py`
  - 在 `native_3d_enable && dim_z > 1` 时使用 `SnnDL.MulticastRouter3DNative`
  - `workload_impl = snn` 且窗口条件满足时生成：
    - `SnnDL.GatherBufferIF`
    - `SnnDL.GlobalGasStepController`
- `snn3dexp/cases/`
  - 当前实际存在 `13` 个 case
- `run_case.py`
  - `PHASE2_BASELINE_CASES` 当前为 `9` 个 case

此外，canonical traffic/memory fresh baseline 已不是 mixed-tag 假象，而是同 tag 真实闭环：

- `snn3dexp/analysis/codesign_single_20us_20260322_ablation.json`
  - 当前包含 `10` 个 case
  - 覆盖：
    - `baseline_2d`
    - `memory_only_3d`
    - `noc_only_3d`
    - `full_3d`
    - `full_3d_mapping`
    - `full_3d_monolithic_proxy`
    - `full_3d_runtime_adaptive`
    - `full_3d_thermal_guard`
    - `full_3d_tile_bundle_v3`
    - `noc_only_3d_bundle_fault_v3`

所以当前平台已经同时具备：

- 独立 schema
- 真实 SST graph
- case catalog
- baseline suite
- canonical same-tag artifact
- paper/export chain

### 10.4 memory/NMC 现在已经是最成熟的研究面

这轮复核后，memory/NMC 面的成熟度需要更明确地写高。

#### A. `HBM-like` 与 `monolithic-like` 已是平台原生 memory paradigm

- `memory/hbm_stack.py`
  - 已建 shared stack
  - `xy_quadrant` home policy
  - semantic region binding
  - `build_synapse_source_descriptors()`
- `memory/monolithic_proxy.py`
  - 已建 tier-local stack graph
  - `xy_quadrant_local_tier`
  - `vertical_mem_hop_latency_ns = 0`
  - monolithic proxy metrics

#### B. 当前 compare 已经直接落到 home-access / stack-pressure

`codesign_single_20us_20260322_ablation.json` 当前已直接给出：

- `direct_v4_vs_bundle_v3`
  - `remote_home_total_demands_delta = -19544`
  - `same_xy_cross_tier_total_demands_delta = 123302`
  - `most_pressured_stack_service_deficit_delta = 52014`
- `hbm_like_vs_monolithic_like`
  - `remote_home_total_demands_delta = -32500`
  - `active_stack_utilization_delta = 0.0`
  - `most_pressured_stack_service_deficit_delta = -17807`

这说明当前 memory/NMC 讨论已经正式进入：

- home-access 类别迁移
- hot-stack service deficit
- stack skew
- locality / vertical pressure tradeoff

#### C. `memory_nmc_codesign_surface` 现在是真正的统一 compare surface

`snn3dexp/analysis/codesign_surface/codesign_single_20us_20260322/memory_nmc_codesign_surface_summary.json`
当前已确认包含：

- `traffic_mem_baseline_rows = 10`
- `traffic_mem_compare_rows = 2`
- `traffic_mem_mechanism_rows = 47`
- `window_baseline_rows = 9`
- `window_bundle_breakdown_rows = 6`
- `window_memory_model_breakdown_rows = 6`
- `window_spike_sensitivity_rows = 9`
- `combined_rows = 92`

这里需要明确修正一个旧口径：

- raw 的 `fixed_step_window_route_memory/fixed_step_sweep_summary.json`
  当前直接导出的是：
  - `case_rows = 18`
  - `bundle_breakdown = 6`
  - `spike_sensitivity = 9`
- `window_memory_model_breakdown_rows = 6`
  是 `export_memory_nmc_codesign_surface.py` 统一投影后的结果，不是 raw fixed-step summary 自带的独立根块

这个区别意味着：

- raw sweep 负责保存原始实验面
- unified surface 负责把 traffic baseline、windowed SNN 和 paper export 串成同一建模入口

### 10.5 `phase2 paper artifacts` 已经把 memory/home-stack co-design 正式拉平

`phase2_runtime_summary.json` 当前不仅包含：

- `route_memory_comparisons`
- `memory_model_comparisons`

还额外包含：

- `memory_nmc_codesign_surface.available = true`
- `memory_home_stack_codesign.available = true`
- `memory_home_stack_codesign.case_count = 2`

并且已经正式导出：

- `phase2_memory_home_stack_codesign.csv`
- `phase2_memory_home_stack_codesign.md`
- `phase2_memory_home_stack_codesign.tex`

这组三件套当前已经能直接承载：

- `tier_local_home_total_demands`
- `same_xy_cross_tier_total_demands`
- `remote_home_total_demands`
- `most_pressured_stack_service_deficit`
- `stack_memory_request_skew`
- `stack_service_deficit_skew`

所以 paper/export 面现在已经不只是“展示性能差异”，而是开始能正式表达：

- `home-access / stack-pressure / route-style`

### 10.6 热与 runtime 的准确口径需要更保守

`full_3d_runtime_adaptive/arc4_hotspot_refresh_20260321` 当前已确认：

- `runtime_summary.json`
  - `control_decision = executed_control`
  - `executed_control = true`
- `runtime_control_next_window.json`
  - `signal_source = joint_runtime`
  - `thermal_signal_source = thermal_hooks`
  - 下一窗口参数已应用：
    - `mapping_route_weight = 1.25`
    - `mapping_stack_home_weight = 1.7625`
    - `mapping_vertical_penalty = 1.125`

因此最准确的说法应该是：

- runtime execute v1 已经存在
- 当前控制主信号仍主要来自：
  - `joint_runtime`
  - `thermal_hooks`
- HotSpot 当前更多是 canonical thermal evidence / sidecar contract
- 它还没有成为更广泛 case 的直接 execute-loop 输入

### 10.7 下一阶段最值得投入的主线

如果只看当前代码而不带历史预期，下一阶段最值得投入的已经不是“继续证明 3D 功能存在”，而是：

1. `controller/home-stack` 归因
   - 把 `home_access_class -> stack_id -> service_deficit -> controller pressure`
     真正打通
2. 真实 `PE/NIC -> home stack` 数据路径归因
   - 尤其是：
     - `HBM-like shared stack`
     - `bundle vs direct`
     - `monolithic-like proxy`
     三者对 pressure 传导的差异
3. 把 `traffic_mem` 与 `windowed SNN` 做成统一 methodology
   - 不只把结果放在一张表里，还要形成统一机理解释
4. 只在完成前三项后，再扩大 HotSpot-in-loop 控制覆盖面

换句话说，当前平台的重心已经明确从：

- `3D capability existence`

转向：

- `memory/NMC + home-stack/controller co-design`

### 10.8 2026-03-22 晚间刷新：统一 surface 已经能表达三层 overlap，而不只是 request/deficit

这一轮最重要的代码对齐变化，发生在：

- `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
- `snn3dexp/tests/test_memory_nmc_codesign_surface.py`
- fresh artifact:
  - `snn3dexp/analysis/codesign_surface/controller_runtime_refresh_20260322_windowed_snapshot_stop_overlap/`
  - `snn3dexp/analysis/codesign_surface/controller_runtime_refresh_20260322_windowed_snapshot_real_home_flow/`

当前 unified surface 已经不再只是：

- `memory_requests_total`
- `total_service_deficit`
- `steps_completed`

而是已经能显式表达：

- `same_stack_overlap`
- `same_controller_overlap`
- `same_class_overlap`
- `runtime_controller_home_access_class`
- `home_region_joint_attribution`
- `window_stop_baseline_rows`
- `window_stop_compare_rows`

这意味着当前平台对 `3D SNN` 的 memory/NMC 讨论，已经从：

- “bundle/direct/monolithic 的数值差了多少”

推进到：

- “dominant home traffic 与 runtime hottest controller 到底在 stack/controller/class 哪一层重叠”
- “这种重叠是否会随着 stop window 增长发生收敛”

就当前 `controller_runtime_refresh_20260322` fresh surface 而言：

- `traffic_mem` baseline 的 `3` 个主 case
  - `full_3d`
  - `full_3d_tile_bundle_v3`
  - `full_3d_monolithic_proxy`
  都是：
  - `same_stack_overlap = false`
  - `same_controller_overlap = false`
  - `same_class_overlap = false`

这说明在 `traffic_mem` 同 tag fresh 口径下，dominant home class 对应的 stack/controller/class 还没有自然对齐到 runtime hottest pressure。

但 `window_stop_compare_rows` 给出了更强的动态结论：

- `window_stop_bundle_vs_direct`
  - `2us`
    - `same_stack_overlap_delta = 0`
    - `same_controller_overlap_delta = 0`
    - `same_class_overlap_delta = 0`
  - `10us`
    - `same_stack_overlap_delta = +1`
    - `same_controller_overlap_delta = +1`
    - `same_class_overlap_delta = +1`
  - `20us`
    - 与 `10us` 相同，趋势未反转

这说明当前平台已经能够正式支持这样一种更细粒度的问题：

- `bundle` 的收益，究竟只是 step progress 提升
- 还是它会在更长窗口下把 home-traffic 热点真正压到同一 stack/controller/class 上

答案现在已经不是猜测，而是 fresh artifact 可见：

- `bundle` 在 `10us/20us` 开始表现出明确的三层对齐收敛
- `direct` 则没有自然出现同样的对齐

### 10.9 2026-03-22 晚间刷新：当前平台已经具备 `real home-traffic -> runtime controller` 证据面

这一轮另一个关键变化是：

- 当前 unified surface 已经不再只是“home-stack proxy compare”
- 而是开始显式标注：
  - `real_synapse_source_count`
  - `semantic_addressing_enabled`
  - `traffic_runtime_enabled`
  - `home_access_pressure_enabled`
  - `home_stack_controller_proxy_available`
  - `real_controller_pressure_available_from_summary`
  - `processing_runtime_mode`
  - `real_home_traffic_signal_level`
  - `runtime_alignment_evaluable`
  - `runtime_pressure_transfer_kind`

这组字段非常关键，因为它把当前平台从：

- “我们看到某些 stack/home 指标”

推进到了：

- “我们能明确判断这些 stack/home/controller 指标是来自真实 synapse/home-stack 流量链，还是只停在 proxy 层”

就 `controller_runtime_refresh_20260322_windowed_snapshot_real_home_flow` 这组 fresh surface 而言：

- `traffic_mem` 三个主 case 的 `real_home_traffic_signal_level` 都已经是：
  - `runtime_controller`
- 即：
  - `full_3d`
  - `full_3d_tile_bundle_v3`
  - `full_3d_monolithic_proxy`
  都已经不是 proxy-only 口径，而是到达了 `runtime hottest controller` 级别的真实证据面

这件事会直接改变我们对当前 3D SNN 平台成熟度的判断。

今天平台真正的 open question 已经不是：

- “有没有真实 home-traffic 信号”

而是：

- “真实 home-traffic 信号已经到 runtime-controller 级时，为什么不同 route/memory 范式会呈现不同的 transfer kind”

### 10.10 `runtime_pressure_transfer_kind` 让当前 3D SNN 的主缺口从“有无信号”转成“热点迁移机理”

这轮代码中新增的 `runtime_pressure_transfer_kind`，当前已支持区分：

- `aligned_same_controller`
- `same_stack_controller_split`
- `same_class_cross_stack`
- `cross_class_transfer`
- `runtime_class_unresolved`
- `unevaluable`

它的重要性在于：

- 我们现在终于能把 `home_access_class -> runtime hottest controller` 的偏移写成可落表、可比较、可 sweep 的架构现象

在 fresh artifact 上，当前已经形成三种非常不同的模式：

1. `traffic_mem/full_3d`
   - `real_home_traffic_signal_level = runtime_controller`
   - `runtime_pressure_transfer_kind = runtime_class_unresolved`
2. `traffic_mem/full_3d_monolithic_proxy`
   - `real_home_traffic_signal_level = runtime_controller`
   - `runtime_pressure_transfer_kind = cross_class_transfer`
3. `window_stop_bundle_vs_direct`
   - `2us`
     - base/direct: `cross_class_transfer`
     - compare/bundle: `runtime_class_unresolved`
   - `10us/20us`
     - base/direct: `cross_class_transfer`
     - compare/bundle: `aligned_same_controller`

这三种模式合在一起，给出一个比“bundle/direct/monolithic 谁更好”更准确的全貌：

- `full_3d` / `bundle_v3` / `monolithic_like` 已经不是单纯的功能选项
- 它们正在改变：
  - home-traffic 的主导 class
  - runtime hottest controller 的落点
  - 热点从 class 到 stack/controller 的迁移方式

因此，当前 3D SNN 平台的全貌可以更准确地概括为：

1. `3D topology/object graph` 已经稳定
2. `3D native route interface + router` 已经稳定
3. `HBM-like / monolithic-like / legacy_per_pe` memory paradigm 已经稳定
4. `traffic_mem + windowed SNN + fixed-step + stop-window` workload/runtime 观察面已经稳定
5. `route_memory_joint + stack_nmc + phase2 artifact + unified codesign surface` 分析链已经稳定
6. 当前真正还在演进的，不再是“功能存在性”，而是：
   - `real home-traffic -> controller hotspot transfer mechanism`
   - `memory/NMC + route-style + home-stack/controller` 的 co-design 机理

### 10.11 基于当前代码的下一步任务，需要比旧文档再进一步收敛

如果只看今天的代码、测试和 fresh artifact，下一步任务不宜再泛泛写成“继续做 memory/NMC”。

更准确的优先级应当是：

1. 把同一套 `overlap + provenance + transfer-kind` 字段带入更高负载 surface
   - 尤其是：
     - `perf_20us_route_refresh_v2`
     - `codesign_single_20us_20260322`
   - 目标是确认：
     - 高压条件下 `bundle` 是否仍会在长窗口收敛到 `aligned_same_controller`
     - `monolithic_like` 是否稳定保持 `cross_class_transfer`
2. 直接深挖 `direct` 为何长期停在：
   - `cross_class_transfer`
   - `runtime_class_unresolved`
   也就是把：
   - `home_access_class`
   - `dominant_pressure_region`
   - `runtime hottest stack/controller`
   - `region backlog / service deficit`
   放在同一解释链里
3. 只有在前两项稳定之后，再继续推进：
   - 真实 `synapse-native` route source semantics
   - 更广泛的 HotSpot-in-loop control widening

换句话说，这轮代码对齐后，当前 `3D SNN` 主线已经可以写得更明确：

- 平台已经有真实 3D route、真实 3D memory paradigm、真实 SNN workload、真实 thermal evidence
- 当前最值得投入的，不是再扩功能存在性
- 而是把：
  - `real home-traffic`
  - `controller hotspot`
  - `transfer kind`
  - `bundle/direct/monolithic`
  这四件事讲成同一条 memory/NMC co-design 机理链

### 10.12 高负载 `runtime-controller` refresh 与 stale-artifact root cause 已闭环

在当前代码基线下，“把同一套 provenance/transfer-kind/controller-runtime 字段推进到高负载 surface” 这件事已经完成，而且结论和之前口头判断不同。

这轮真正闭环的是两件事：

1. 高负载 unified surface 已经刷新到当前语义：
   - `snn3dexp/analysis/codesign_surface/codesign_single_20us_20260322_runtime_evidence_refresh/`
   - `snn3dexp/analysis/codesign_surface/perf_20us_route_nmc_compare_runtime_evidence_refresh/`
2. stale artifact 的根因已经定位并通过共享 loader 修复：
   - `snn3dexp/tools/route_memory_joint_loader.py`
   - `snn3dexp/tools/analyze_ablation.py`
   - `snn3dexp/tools/export_memory_nmc_codesign_surface.py`

root cause 很明确：

- 被消费的旧 `route_memory_joint_summary.json` 缺少：
  - `home_stack_controller_proxy`
  - `real_controller_pressure`
  - `processing_runtime_mode`
- 被消费的旧 `memory_summary.json` 缺少：
  - `controller_reports`
  - `controller_summary`
- 因此旧 surface / old report 才会错误地把 high-load 主 case 写成：
  - `real_home_traffic_signal_level = home_pressure`
  - `runtime_pressure_transfer_kind = unevaluable`

而在当前代码与 refreshed artifact 上，真实状态已经变成：

1. low-load `controller_runtime_refresh_20260322`
   - `full_3d/full_3d_tile_bundle_v3/full_3d_monolithic_proxy`
   - 都处于 `real_home_traffic_signal_level = runtime_controller`
2. high-load `codesign_single_20us_20260322_runtime_evidence_refresh`
   - `full_3d`
     - `real_home_traffic_signal_level = runtime_controller`
     - `real_controller_pressure_available_from_summary = true`
     - `processing_runtime_mode = traffic_semantic`
     - `active_controller_count = 16`
   - `full_3d_tile_bundle_v3`
     - 同样保留 `runtime_controller`
   - `full_3d_monolithic_proxy`
     - 同样保留 `runtime_controller`
     - 并继续稳定表现为 `runtime_pressure_transfer_kind = cross_class_transfer`
3. high-load `perf_20us_route_nmc_compare_runtime_evidence_refresh`
   - 上述三个主 case 也都保留：
     - `real_home_traffic_signal_level = runtime_controller`
     - `real_controller_pressure_available_from_summary = true`
     - `processing_runtime_mode = traffic_semantic`
     - `active_controller_count = 16`

因此，今天之后已经不能再把平台状态写成“高负载只能退化到 home-pressure”。更准确的表述是：

- high-load controller runtime 语义本来就能恢复
- 旧结论来自 stale `route_memory_joint_summary.json + memory_summary.json` 被重复消费
- 当前分析主线已经进入“真实 runtime-controller 证据下的 memory/NMC 机理解释”，而不是“补字段救证据”

配套的 cross-surface 机理报告也已经刷新：

- `snn3dexp/tools/export_transfer_kind_mechanism_report.py`
- `snn3dexp/analysis/transfer_kind_mechanism/controller_runtime_refresh_20260322_vs_codesign_single_20us_runtime_evidence_refresh_vs_perf_20us_runtime_evidence_refresh/`

这条报告现在给出的不是“退化”，而是“稳定迁移”：

- `full_3d`
  - `runtime_controller -> runtime_controller`
  - `runtime_class_unresolved -> runtime_class_unresolved`
  - `transition_kind = stable`
  - 但高负载下：
    - `memory_requests_total_delta = +55492`
    - `total_service_deficit_delta = +89189`
- `full_3d_tile_bundle_v3`
  - 同样保持 `runtime_controller`
  - `transition_kind = stable`
  - `codesign_single` 下 `total_service_deficit_delta = +291436`
- `full_3d_monolithic_proxy`
  - `runtime_controller -> runtime_controller`
  - `cross_class_transfer -> cross_class_transfer`
  - `transition_kind = stable`

同时，low-load stop-window 的 bundle 收敛结论也继续成立：

- `controller_runtime_refresh_20260322`
  - `window_stop_bundle_vs_direct`
  - 最早在 `10us` 收敛到 `aligned_same_controller`
- 两组 refreshed high-load surface
  - 当前仍没有 stop-window row
  - 所以“高压下 bundle 是否也会收敛到同 controller”依然是待补实验，而不是已知退化结论

这会直接改变下一步任务的表述：

1. 不再问“为什么 high-load 只能到 home-pressure”
2. 改为问“在已经恢复到 runtime-controller 的 high-load 证据面上，direct/bundle/monolithic 怎样改变 controller hotspot 与 service deficit”
3. 补一条高负载 stop-window / long-window 线，专门验证：
   - bundle 是否仍会收敛到 `aligned_same_controller`
   - monolithic proxy 的 `cross_class_transfer` 在更长窗口下是否仍稳定

### 10.13 controller explainability loss 报告现在更像 regression guard，而不是主问题诊断

在 10.12 的 refreshed evidence 之上，这条链也需要改写。

仍然保留的隔离工具链：

- `snn3dexp/tools/export_controller_explainability_loss_report.py`
- `snn3dexp/analysis/controller_explainability_loss/controller_runtime_refresh_20260322_vs_codesign_single_20us_runtime_evidence_refresh_vs_perf_20us_runtime_evidence_refresh/`

但它现在给出的主结论已经不再是“high-load explainability 掉光”，而是：

1. low-load `controller_runtime_refresh_20260322`
   - `full_3d/full_3d_tile_bundle_v3/full_3d_monolithic_proxy`
   - 都是：
     - `explainability_level = runtime_controller`
     - `controller_explainable = true`
2. refreshed high-load `codesign_single_20us_20260322`
   - 相同主 case 仍然是：
     - `explainability_level = runtime_controller`
     - `controller_explainable = true`
3. refreshed high-load `perf_20us_route_refresh_v2`
   - 相同主 case 也仍然是：
     - `explainability_level = runtime_controller`
     - `controller_explainable = true`

这份新报告最关键的结果是：

- `explainability_loss_rows = 0`
- `loss_reason_rows = 0`
- 三个主 case 在 `low-load -> refreshed high-load` 之间全部是：
  - `explainability_transition = stable`

因此，旧的 explainability-loss 结论现在应被归类为：

- 历史阶段的 stale-artifact snapshot
- 不是当前 3D SNN 平台的真实 runtime 状态

这也意味着 explainability 报告链在当前阶段的职责发生了变化：

- 之前：诊断 high-load 为什么掉到 `home_pressure_only`
- 现在：作为 regression guard，持续检测后续 surface / paper artifact 是否又把旧 summary 链接回来了

今天之后更准确的下一步任务是：

1. 在 `runtime_controller` 已稳定保留的前提下，深化 `runtime_class_unresolved` 的机理拆解
2. 把 refreshed runtime evidence 继续下沉到 paper/export/default surface，避免旧 artifact 再次污染结论
3. 把 high-load long-window / stop-window 做出来，真正回答 memory/NMC + co-design 的高压收敛问题

### 10.14 `phase2 paper artifacts` 默认导出链现在会自动桥接 refreshed overlay / stop-window

这一步之前，`export_phase2_paper_artifacts.py` 虽然已经能挂 unified surface，但默认链仍然偏“手工参数驱动”：

- 如果用户直接拿 legacy `*_ablation.json` 导出 paper artifact
- 就必须手工再补：
  - refreshed `*_ablation_runtime_refresh.json`
  - stop-window `windowed_<run_tag>_ablation.json`
  - 否则 default export 很容易停在旧 summary 语义上

这轮之后，默认导出链已经补齐两条自动发现：

1. sibling refreshed overlay
   - 自动发现同目录下的 `*_ablation_runtime_refresh.json`
2. sibling stop-window ablation
   - 自动发现：
     - `windowed_<run_tag>_ablation.json`
     - `<run_tag>_windowed_ablation.json`

并且这些输入现在会直接写回 `phase2_runtime_summary.json` 的 `memory_nmc_codesign_surface` 摘要：

- `sources.baseline_overlay_ablation_paths`
- `sources.stop_window_ablation_paths`
- `window_stop_baseline_row_count`
- `window_stop_compare_row_count`

这意味着 paper/export/default 链现在已经开始承担两层职责：

- 不只是“导出图表/表格”
- 还负责对 refreshed runtime evidence 做默认对齐与回归守护

当前已经落好的 fresh artifact：

- low-load default refresh：
  - `snn3dexp/analysis/paper_artifacts/controller_runtime_refresh_20260322_windowed_snapshot_default_refresh/`
  - 对应 `codesign_surface` 已自动带入：
    - `stop_window_ablation_paths = [windowed_controller_runtime_refresh_20260322_ablation.json]`
    - `window_stop_baseline_row_count = 3`
    - `window_stop_compare_row_count = 2`
- high-load default bridge：
  - `snn3dexp/analysis/paper_artifacts/codesign_single_20us_20260322_default_export_runtime_refresh_bridge/`
  - `snn3dexp/analysis/paper_artifacts/perf_20us_route_nmc_compare_default_export_runtime_refresh_bridge/`
  - 两者的 `codesign_surface` 都已经自动指向：
    - `baseline_overlay_ablation_paths = [*_ablation_runtime_refresh.json]`
  - 并且主 case 都保持：
    - `real_home_traffic_signal_level = runtime_controller`
    - `real_controller_pressure_available_from_summary = true`
    - `processing_runtime_mode = traffic_semantic`

所以现在“继续把 refreshed surface/default export/paper artifact 统一到同一条消费链”这件事，已经不再只是计划项，而是已有默认桥接落地的已完成项。

### 10.15 2026-03-23 补充刷新：high-load long-window / stop-window bridge 已闭环到 unified surface

这一步之后，当前 3D SNN 平台在 `memory/NMC + co-design` 主线上又前进了一层：

它已经不只是有 `fixed-step windowed SNN` 的统一对照面，而是把真实 high-load `long-window / stop-window` 证据也重新接回了统一消费链。

这轮落地了两个关键代码点：

1. 新增 multicase stop-window runner
   - `snn3dexp/tools/run_window_stop_multicase_sweep.py`
   - `snn3dexp/tests/test_window_stop_multicase_sweep.py`
   - 它会对：
     - `full_3d_snn_window`
     - `full_3d_snn_window_bundle_v3`
     - `full_3d_snn_window_monolithic_proxy`
   - 在多 `stop_at` 上统一执行，并为每个 `stop_at` 输出可直接喂给 `analyze_ablation --run-tag-manifest` 的 `run_tags_by_case` manifest。
2. `phase2 paper artifacts` 的 stop-window 发现能力继续下沉
   - `snn3dexp/tools/export_phase2_paper_artifacts.py`
   - 现在除了 sibling `windowed_<run_tag>_ablation.json` 外，也能识别：
     - `long_window_ablation_<run_tag>/window_stop_*_ablation.json`

同时，已有真实 high-load stop-window 证据也已经明确对齐到代码链上：

- `snn3dexp/analysis/long_window_ablation_controller_runtime_refresh_20260322/window_stop_2us_ablation.json`
- `snn3dexp/analysis/long_window_ablation_controller_runtime_refresh_20260322/window_stop_10us_ablation.json`
- `snn3dexp/analysis/long_window_ablation_controller_runtime_refresh_20260322/window_stop_20us_ablation.json`

在这些 stop-window ablation 明确接回之后，两个 high-load bridge artifact 已重新导出：

1. `codesign_single_20us_20260322_default_export_runtime_refresh_bridge`
   - `window_stop_baseline_row_count = 9`
   - `window_stop_compare_row_count = 6`
2. `perf_20us_route_nmc_compare_default_export_runtime_refresh_bridge`
   - `window_stop_baseline_row_count = 9`
   - `window_stop_compare_row_count = 6`

这意味着 high-load bridge 不再停留在：

- `window_stop_baseline_rows = 0`
- `window_stop_compare_rows = 0`

而是已经真正消费了：

- `2us / 10us / 20us`
- `direct / bundle / monolithic`

三类 stop-window 真实运行证据。

更重要的是，新的 cross-surface mechanism 报告已经把 high-load 收敛行为讲清楚了一步：

- `snn3dexp/analysis/transfer_kind_mechanism/controller_runtime_refresh_20260322_vs_codesign_single_20us_stopwindow_bridge_vs_perf_20us_stopwindow_bridge_20260323/`

这份 fresh 报告给出的主结论是：

1. `codesign_single_20us_20260322`
   - `bundle_convergence.convergence_detected = true`
   - `earliest_aligned_stop_at = 10us`
2. `perf_20us`
   - `bundle_convergence.convergence_detected = true`
   - `earliest_aligned_stop_at = 10us`
3. 二者都表现出一致的窗口级机制转移：
   - `2us`: `window_stop_bundle_vs_direct.compare_transfer_kind = runtime_class_unresolved`
   - `10us / 20us`: `window_stop_bundle_vs_direct.compare_transfer_kind = aligned_same_controller`

因此，当前平台对 high-load `memory/NMC + co-design` 的判断已经应当更新为：

- long-window / stop-window 不再是“待补的存在性链路”
- 它已经是可进入 unified surface 和 cross-surface mechanism report 的正式证据面

这也把下一步任务进一步压实成三个更具体的方向：

1. 用新的 `run_window_stop_multicase_sweep.py` 生成 future fresh same-tag stop-window family
   - 逐步替代当前 `direct/bundle/monolithic` 各自独立命名的 legacy stop-sweep tag
2. 把重心继续从“stop-window 是否存在”左移到：
   - `PE/NIC -> home stack`
   - `synapse/home-stack`
   - `HBM-like NMC` 真实数据通路
3. 如果未来希望 default export bridge 在高压 case 上自动带入 controller-runtime stop-window evidence
   - 需要把这种 linkage 提升成显式 contract
   - 而不是长期依赖手工 CLI 传参

### 10.16 2026-03-23 补充刷新：first fresh same-tag stop-window family 已真实跑通

10.15 节把 high-load stop-window bridge 接回了 unified surface，但那一层仍主要复用了：

- `controller_runtime_refresh_20260322_direct_stop_sweep_*`
- `controller_runtime_refresh_20260322_bundle_stop_sweep_*`
- `controller_runtime_refresh_20260322_monolithic_stop_sweep_*`

这类“每个 case 一套历史 tag”的 stop-window 证据。

这一步之后，平台已经向前跨过了下一道门槛：

- 第一批 `fresh same-tag stop-window family`
- 已经由新的标准 runner 真实跑出，并形成独立的 fresh artifact 族

真实产物如下：

1. multicase sweep summary
   - `snn3dexp/analysis/sweeps/window_stop_multicase/same_tag_stopwindow_fresh_20260323/window_stop_multicase_sweep_summary.json`
   - 共 `9` 个真实 SST smoke 运行：
     - `direct / bundle / monolithic`
     - `2us / 10us / 20us`
   - `9/9` 全部 `smoke_passed`
2. fresh long-window ablation family
   - `snn3dexp/analysis/long_window_ablation_same_tag_stopwindow_fresh_20260323/`
   - 包含：
     - `window_stop_2us_ablation.json`
     - `window_stop_10us_ablation.json`
     - `window_stop_20us_ablation.json`
     - `long_window_stability_summary.json`
3. fresh unified surface
   - `snn3dexp/analysis/codesign_surface/same_tag_stopwindow_fresh_20260323/`
   - 现在明确带有：
     - `surface_label = same_tag_stopwindow_fresh_20260323`
     - `window_stop_baseline_rows = 9`
     - `window_stop_compare_rows = 6`
4. fresh reference-vs-same-tag mechanism report
   - `snn3dexp/analysis/transfer_kind_mechanism/controller_runtime_refresh_20260322_vs_same_tag_stopwindow_fresh_20260323/`

这里最关键的不是“又多跑了一批 case”，而是：

1. `same-tag` 终于成为真实运行事实，而不只是分析命名上的想法
2. `run_window_stop_multicase_sweep.py + analyze_window_stop_multicase_sweep.py`
   - 已经形成从 run 到 ablation family 的标准闭环
3. unified surface / transfer-kind report 现在可以消费这批 fresh family，而不再依赖历史 stop-sweep tag

fresh same-tag family 给出的核心结果，与 bridge 阶段结论一致：

1. `tail_clear`
   - `direct_tail_clear_stop_at = 2us`
   - `bundle_tail_clear_stop_at = 10us`
   - `monolithic_tail_clear_stop_at = 2us`
   - `bundle_minus_direct_gap_ns = 8000`
2. fresh same-tag mechanism report
   - `surface_label = same_tag_stopwindow_fresh_20260323`
   - `bundle_convergence.convergence_detected = true`
   - `earliest_aligned_stop_at = 10us`
   - `final_compare_transfer_kind = aligned_same_controller`
3. 换句话说：
   - `2us`: bundle 仍处于 `runtime_class_unresolved`
   - `10us / 20us`: bundle 已和 direct 收敛到 `aligned_same_controller`

同时，这一步还顺手压实了另一个小但重要的 contract：

- `export_memory_nmc_codesign_surface.py`
  - 现在支持显式 `surface_label`
- `export_transfer_kind_mechanism_report.py`
  - 现在优先消费这个 label

所以 future fresh same-tag family 不会再在 cross-surface report 中被 baseline run tag 混名。

这把下一步进一步收敛成：

1. 把 fresh same-tag stop-window family 作为默认 high-load 生成范式固定下来
2. 把分析重心从“same-tag 是否能跑通”转向：
   - `PE/NIC -> home stack`
   - `synapse/home-stack`
   - `controller hotspot / stack skew`
3. 再往后才是把 default export bridge 自动接到这条 fresh same-tag family 上

### 10.17 2026-03-23 补充刷新：`home_stack_dataflow` contract 已进入真实 route-memory surface

10.16 节把 fresh same-tag stop-window family 跑通之后，平台的下一个最小缺口已经非常明确：

- 现有 `route_memory_joint_summary`
  - 已经有 `home_access_pressure`
  - 已经有 `home_stack_controller_proxy`
  - 已经有 `real_controller_pressure`
- 但还缺一层更直接的 contract，能够不再靠人工拼读多个 section，而是直接回答：
  - 哪些 demand 主要属于 `PE/NIC -> home stack`
  - 哪些 demand 主要属于 `synapse_source -> home stack`
  - 当前 runtime hotspot 与 dominant home path 是否对齐

这一步现在已经真实落地为：

1. `route_memory_joint_summary.memory.home_stack_dataflow`
   - 代码位置：
     - `snn3dexp/tools/analyze_route_memory_joint.py`
   - 新增内容：
     - `initiator_groups.pe_nic_to_home_stack`
     - `initiator_groups.synapse_source_to_home_stack`
     - `dominant_initiator_kind`
     - `dominant_initiator_region`
     - `runtime_hotspot_alignment.controller_alignment_kind`
2. unified surface 投影
   - 代码位置：
     - `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - 新增 row fields：
     - `pe_nic_home_stack_demands_total`
     - `synapse_home_stack_demands_total`
     - `dominant_dataflow_initiator_kind`
     - `dominant_dataflow_region`
     - `dataflow_controller_alignment_kind`
     - `dataflow_runtime_home_access_class`
3. fresh surface 刷新
   - `snn3dexp/analysis/codesign_surface/same_tag_stopwindow_fresh_20260323_home_stack_dataflow_refresh/`

这一步最重要的不是“多了几个字段”，而是平台现在第一次可以在同一张表里，把：

- `home-stack path demand split`
- `runtime controller alignment kind`
- `direct / bundle / monolithic`

放在一起讨论。

fresh same-tag stop-window 的真实结果已经显示出清晰差异：

1. `windowed direct`
   - `2us / 10us / 20us`
   - `dominant_dataflow_initiator_kind = pe_nic_to_home_stack`
   - `dominant_dataflow_region = stream_region`
   - `dataflow_controller_alignment_kind = cross_class_transfer`
2. `windowed bundle_v3`
   - `2us`
     - `bundle_pe_nic_ratio = 4.0`
     - `bundle_synapse_ratio = 4.3125`
     - `dataflow_controller_alignment_kind = runtime_class_unresolved`
   - `10us / 20us`
     - `bundle_pe_nic_ratio = 2.1136`
     - `bundle_synapse_ratio = 4.3125`
     - `dataflow_controller_alignment_kind = aligned_same_controller`
3. `windowed monolithic_proxy`
   - `2us`
     - `mono_pe_nic_ratio = 2.0`
     - `mono_synapse_ratio = 1.0`
   - `10us / 20us`
     - `mono_pe_nic_ratio = 1.0`
     - `mono_synapse_ratio = 1.0`
   - 但 `dataflow_controller_alignment_kind` 仍保持 `cross_class_transfer`

换句话说，当前平台已经能明确区分两类现象：

1. `bundle` 的问题不只是 tail-clear 慢
   - 它还会同时放大 `PE/NIC` 与 `synapse/home-stack` 两路 demand
   - 且这种放大在 `synapse/home-stack` 上更顽固
2. `monolithic_proxy` 不一定放大 request volume
   - 但可能把 runtime hotspot 留在 `cross_class_transfer`
   - 也就是“请求量没变，但 controller/home-path 对齐关系仍没改善”

因此，从当前代码事实看，下一步最值得继续投入的主线已经进一步收敛成：

1. 让 `home_stack_dataflow` 从 summary contract 继续走向 compare-row delta contract
2. 用这条 contract 深挖：
   - `bundle` 到底在 `PE/NIC` 侧还是 `synapse/home-stack` 侧引入了更强放大
   - `monolithic_like` 为什么在 volume 不变时仍出现 `cross_class_transfer`
3. 再把这些结果接回：
   - `HBM-like NMC vs monolithic near-memory`
   - `route compression vs controller pressure migration`

### 10.18 2026-03-23 补充刷新：`home_stack_dataflow` 已进入 compare-row delta

10.17 节把 `home_stack_dataflow` 作为 row-level contract 接进了 unified surface。

这一步之后，它又往前推进了半层：

- 不再只是 baseline row 上“能看到两路 demand”
- 而是 compare row 上已经能直接表达：
  - `path amplification`
  - `hotspot migration`

当前新增的 compare-row contract 已覆盖：

1. `traffic_mem_compare_rows`
2. `window_stop_compare_rows`

新增字段主要分三类：

1. dataflow path volume
   - `base_pe_nic_home_stack_demands_total`
   - `compare_pe_nic_home_stack_demands_total`
   - `pe_nic_home_stack_demands_delta`
   - `pe_nic_home_stack_demands_amplification_ratio`
   - `base_synapse_home_stack_demands_total`
   - `compare_synapse_home_stack_demands_total`
   - `synapse_home_stack_demands_delta`
   - `synapse_home_stack_demands_amplification_ratio`
2. path semantics
   - `base_dominant_dataflow_initiator_kind`
   - `compare_dominant_dataflow_initiator_kind`
   - `base_dominant_dataflow_region`
   - `compare_dominant_dataflow_region`
3. hotspot migration
   - `base_dataflow_controller_alignment_kind`
   - `compare_dataflow_controller_alignment_kind`
   - `dataflow_controller_alignment_rank_delta`
   - `dataflow_controller_alignment_transition`

新的 fresh compare surface 已导出到：

- `snn3dexp/analysis/codesign_surface/same_tag_stopwindow_fresh_20260323_compare_delta_refresh/`

这张表现在已经能直接读出三类关键结论：

1. `traffic_mem_bundle_vs_direct`
   - `pe_nic_delta = 138348`
   - `pe_nic_ratio = 2.72935`
   - `synapse_delta = 69174`
   - `synapse_ratio = 2.72935`
   - alignment 仍是 `stable @ runtime_class_unresolved`
   - 也就是 bundle 已经明显放大量，但 controller 对齐状态并没有同步改善
2. `window_stop_bundle_vs_direct`
   - `2us`
     - `pe_nic_ratio = 4.0`
     - `synapse_ratio = 4.3125`
     - `alignment_transition = alignment_degraded`
   - `10us / 20us`
     - `pe_nic_ratio = 2.1136`
     - `synapse_ratio = 4.3125`
     - `alignment_transition = alignment_improved`
   - 这说明 bundle 的 tail-clear 收敛，并不意味着两路 demand 放大一起消失；`synapse/home-stack` 的 amplification 更顽固
3. `window_stop_monolithic_vs_direct`
   - `10us / 20us`
     - `pe_nic_ratio = 1.0`
     - `synapse_ratio = 1.0`
     - `alignment_transition = stable`
   - 也就是 monolithic-like 在 volume 贴平后，controller/home-path 对齐并没有自动改善

所以现在平台已经具备一个新的能力：

- 不只是在 row 上看 “现在谁更热”
- 而是能在 compare row 上看：
  - 哪条 path 被放大
  - 放大是否来自 `PE/NIC`、`synapse/home-stack`，还是两者同时发生
  - hotspot 对齐是在改善、退化，还是只是 volume 变了但对齐关系不变

这把下一步进一步收敛成：

1. 把 compare-row delta 从全局 totals 下沉到 per-stack / per-controller attribution
2. 深挖：
   - 为什么 `window_stop_bundle_vs_direct` 在 `10us/20us` 已 alignment improved，但 `synapse/home-stack` amplification 仍维持 `4.3125`
   - 为什么 `monolithic_like` 在 volume 贴平后仍停在 `cross_class_transfer`
3. 再把这组 compare-delta contract 接入：
   - `transfer_kind`
   - `controller explainability`
   - 更后续的 NMC co-design export

### 10.19 2026-03-23 补充刷新：`home_stack_dataflow` 已完成 per-stack / per-controller attribution

10.18 节结束时，平台已经能在 compare row 上表达：

- `PE/NIC` 与 `synapse/home-stack` 两路 volume amplification
- `controller_alignment_kind` 的改善/退化

这一轮之后，`P1-B1a path amplification attribution` 也已经完成第一版落地，重点不是再加一层 totals，而是把 `home_stack_dataflow` 直接压到：

- initiator-group 级 `dominant_stack_id`
- initiator-group 级 `dominant_controller_ids`
- `stack_rows`
- `controller_rows`

当前代码面的真实落点有三处：

1. `snn3dexp/tools/analyze_route_memory_joint.py`
   - `memory.home_stack_dataflow.initiator_groups.*`
   - 新增：
     - `dominant_stack_id`
     - `dominant_stack_demand_share`
     - `dominant_controller_ids`
     - `stack_rows`
     - `controller_rows`
2. `snn3dexp/tools/route_memory_joint_loader.py`
   - 现在会把缺少上述字段的旧 `route_memory_joint_summary.json` 视作 stale
   - 所以 unified surface 在消费历史 run root 时，会自动重建到 attribution-aware schema
3. `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - baseline / stop-window rows 新增：
     - `pe_nic_dominant_stack_id`
     - `pe_nic_dominant_controller_ids`
     - `pe_nic_dominant_stack_demand_share`
     - `pe_nic_runtime_hotspot_stack_overlap`
     - `synapse_dominant_stack_id`
     - `synapse_dominant_controller_ids`
     - `synapse_dominant_stack_demand_share`
     - `synapse_runtime_hotspot_stack_overlap`
   - compare rows 新增：
     - `base_/compare_*_dominant_stack_id`
     - `*_dominant_stack_changed`
     - `base_/compare_*_dominant_controller_ids`
     - `*_dominant_controller_ids_changed`
     - `*_dominant_stack_demand_share_delta`
     - `*_runtime_hotspot_stack_overlap_delta`

新的 fresh surface 已真实导出到：

- `snn3dexp/analysis/codesign_surface/same_tag_stopwindow_fresh_20260323_stack_controller_attribution_refresh/`

这批 fresh 结果把当前 memory/NMC + co-design 的判断继续推进了一层：

1. `traffic_mem_bundle_vs_direct`
   - `pe_nic_dominant_stack_id: 0 -> 3`
   - `pe_nic_dominant_controller_ids: 0,1,2,3 -> 12,13,14,15`
   - `pe_nic_dominant_stack_demand_share_delta = +0.06247486537436525`
   - `synapse_dominant_stack_id` 仍保持 `0`
   - `dataflow_controller_alignment_transition = stable`
   - 这说明 traffic-mem bundle 的新变化，不只是 volume 放大，而是 dominant `PE/NIC -> home-stack` path 已经迁到另一组 stack/controller
2. `window_stop_bundle_vs_direct`
   - `2us / 10us / 20us`
     - `pe_nic_dominant_stack_id` 都保持 `3`
     - `synapse_dominant_stack_id` 也都保持 `3`
   - 但：
     - `pe_nic_runtime_hotspot_stack_overlap_delta = -1`
     - `synapse_runtime_hotspot_stack_overlap_delta = -1`
     - `10us / 20us` 同时又出现 `alignment_transition = alignment_improved`
   - 这说明 bundle 在 windowed 路径上已经出现更复杂的现象：
     - dominant path 没迁走
     - runtime hotspot 却离开了 dominant stack
     - controller alignment 仍可能继续改善
3. `window_stop_monolithic_vs_direct`
   - `20us`
     - `pe_nic_dominant_stack_id` 保持 `3`
     - `synapse_dominant_stack_id` 也保持 `3`
     - `pe_nic_dominant_controller_ids: 12,13,14,15 -> 6,7`
     - `synapse_dominant_controller_ids: 12,13,14,15 -> 6,7`
     - `pe_nic_dominant_stack_demand_share_delta = -0.01785714285714285`
     - `synapse_dominant_stack_demand_share_delta = -0.15625`
     - `alignment_transition = stable`
   - 这给出一个更清晰的 monolithic-like 解释：
     - 它确实能把 volume 贴平
     - 但 dominant path 仍留在同一 stack class
     - controller set 发生了重排
     - 这不是自动“把热点拉回 home path”的等价命题

因此，当前平台对 `memory/NMC + home-stack/controller co-design` 的状态，应更新成：

- 已经不只是 `row-level path existence`
- 也不只是 `compare-row amplification`
- 而是已经进入：
  - `dominant stack migration`
  - `dominant controller set migration`
  - `runtime-hotspot overlap delta`
  三者联合解释的阶段

这会把下一步任务进一步收窄成：

1. 继续把 `service_deficit_proxy` 与真实 `controller queue / reject` 指标接起来，形成更强的 explainability guard
2. 把 `PE/NIC -> home stack` 与 `synapse/home-stack` 两路 dominant path 继续压到真实 home-stack memory path，而不是只停在 proxy attribution
3. 在相同 dominant stack/controller 语义下，再系统比较 `HBM-like` 与 `monolithic-like` 的 controller 重排差异

### 10.20 2026-03-24 补充刷新：windowed SNN canonical non-edges 路径已在 direct/bundle/monolithic 三路正式转正

这一轮不是再做新的抽象层，而是把此前只在 `full_3d_snn_window` 上成立的 canonical non-`edges_csv` 路径，真正推广到：

- `full_3d_snn_window_bundle_v3`
- `full_3d_snn_window_monolithic_proxy`

核心落点有三部分：

1. canonical case spec
   - `cases/full_3d_snn_window_bundle_v3/spec.json`
   - `cases/full_3d_snn_window_monolithic_proxy/spec.json`
   - 两者的 `processing.params.mapping_mode` 已从 `edges_csv` 切到 `dense`
2. fresh smoke evidence
   - `full_3d_snn_window_bundle_v3 / p2_native_dense_bundle_v3_smoke_20260324`
   - `full_3d_snn_window_monolithic_proxy / p2_native_dense_monolithic_smoke_20260324`
   - 两者都已经真实落出：
     - `effective_config.json`
     - `assets/route_bootstrap_weights_pe_{pe}.bin`
     - `phase2_case_summary.json`
     - `route_memory_joint_summary.json`
3. fresh same-tag fixed-step family
   - 新增：
     - `snn3dexp/analysis/sweeps/native_dense_fixed_step_8_20us_20260324/`
     - `snn3dexp/analysis/codesign_surface/native_dense_fixed_step_8_20us_20260324/`
   - 这让 unified surface 第一次在同一组 fresh `8-step / 20us` window rows 上，正式携带：
     - `route_source_primary_kind`
     - `route_native_bootstrap_source`
     - `route_source_mapping_mode`
     - `route_native_synapse_source_candidate`

这批 fresh 结果把当前结论压实成更明确的代码事实：

1. `direct / bundle_v3 / monolithic_proxy` 三条 windowed SNN row 现在都已经不再是 `edges_csv_bootstrap`
   - 三者统一变成：
     - `route_source_primary_kind = legacy_route_tables_with_real_synapse_inputs`
     - `route_native_bootstrap_source = legacy_route_tables`
     - `route_source_mapping_mode = dense`
     - `route_native_synapse_source_candidate = true`
2. `bundle_v3` 的高压特征在 fresh same-tag surface 上仍然成立，而且比旧 surface 更可信
   - `memory_requests_total: 448 -> 1484`
   - `memory_requests_total_amplification_ratio = 3.3125`
   - `stall_on_step_gate_cycles_total: 126289 -> 203110`
   - `synapse_gather_demands_delta = +436`
   - `dominant_dataflow_initiator_kind_changed = true`
     - `pe_nic_to_home_stack -> synapse_source_to_home_stack`
3. `monolithic_like` 在保持 volume 不变时，已经能在同一 fresh surface 上给出更强的 stall-level 对照
   - 对比 `direct_v4 + HBM-like`
   - `memory_requests_total_delta = 0`
   - `stall_on_step_gate_cycles_total_delta = -113489`
   - `stall_on_step_gate_cycles_total_amplification_ratio = 0.10135482900331778`
   - 这说明当前 monolithic proxy 的优势，至少在这组 fresh 8-step evidence 上，主要体现在 gate stall 清退，而不是 request volume 压缩

因此，当前“回到 SNN 3D 芯片本身”的下一步任务，已经可以进一步收敛成三条更直接的体系结构主线：

1. 把 `native_dense_fixed_step_8_20us` 扩展到 `4-step / 10us`、`16-step / 40us` 和 `sp64`，形成同语义、同 provenance 的 fresh family，而不是继续混用历史 summary
2. 专门构造一条 `gating-heavy` windowed SNN case
   - 当前 fresh runtime 里 `runtime_activation_gating_total` 仍然是 `0`
   - 下一步应围绕：
     - `gating_mode`
     - `gating_ttl_cycles`
     - `gating_scope`
     做真实激活，而不是再靠猜测延长 stop window
3. 再把这条已经转正的 `dense/native` same-tag family 接回 HotSpot sidecar
   - 目标不是论文 artifact
   - 而是让 fixed-step window rows 也能进入 thermal-aware architecture loop：
     - `route provenance`
     - `memory/NMC pressure`
     - `thermal sidecar`
     三者同标签闭环

### 10.21 2026-03-24 补充刷新：windowed dense/native family 已有正式编排入口，gating 也已有 contract probe

这一轮的重点不再是补单点 summary 字段，而是把“怎么稳定地产出 windowed dense/native same-tag 证据”固定成仓内能力。

新增事实有两部分：

1. family orchestration 已正式落地
   - 新入口：
     - `snn3dexp/tools/run_windowed_native_dense_family.py`
   - 它把此前需要手工串起来的四段流程固定成一条命令：
     - `run_fixed_step_multicase_sweep`
     - `analyze_fixed_step_sweep`
     - `analyze_ablation`
     - `export_phase2_paper_artifacts`
   - 新入口的意义不是“再包装一层 CLI”，而是把 window-only family 的三个关键产物一并标准化：
     - 每个 fixed-step tag 独立 `window_ablation/<run_tag>.json`
     - same-tag `phase2_runtime_summary.json`
     - same-tag `codesign_surface/memory_nmc_codesign_surface_summary.json`

2. gating 已从“口头 gap”变成“仓内 probe contract”
   - 新增 case：
     - `snn3dexp/cases/full_3d_snn_window_gating_event_probe/`
   - 这个 case 的设计很刻意：
     - 保持 canonical `windowed SNN + native_3d + dense bootstrap`
     - 只额外打开：
       - `gating_mode = event`
       - `gating_ttl_cycles = 128`
       - `gating_scope = all`
   - 因此它不是 gating-heavy 方案本身，而是一个边界探针：
     - 如果当前系统里没有真正的 gating decision event source
     - 那么它就应该继续给出 `runtime_activation_gating_total = 0`

这轮 fresh 结果把当前状态压得更清楚：

1. `run_windowed_native_dense_family --compose-only` 已在真实仓内跑通
   - fresh family:
     - `snn3dexp/analysis/windowed_native_dense_family/native_dense_family_compose_20260324/`
   - 已确认：
     - `phase2_artifacts.available = true`
     - `codesign_surface.available = true`
     - `codesign_surface.surface_label = native_dense_fixed_step_4_10us`
   - 这说明：
     - window-only family 已经不再依赖人工串命令
     - phase2 runtime summary / codesign surface / route-runtime diff 都可以由统一入口稳定地产出

2. gating probe 的 fresh compose 结果也已经固定下来
   - fresh probe:
     - `full_3d_snn_window_gating_event_probe / gating_event_probe_compose_20260324`
   - `phase2_case_summary.route_kernel` 现在明确给出：
     - `expected_active = true`
     - `actual_activation_observed = false`
     - `runtime_activation_total = 0`
     - `runtime_activation_gating_total = 0`
   - 这把当前结论收紧成一句非常重要的话：
     - `gating_mode/event` 参数面已经接通
     - 但 `snn3dexp` 侧还没有真实 control-plane gating event source 被实例化

因此，下一阶段任务不再需要继续在“是不是接通了 gating 参数”上打转，而应收敛成两条更实的体系结构主线：

1. 先把 family 级 fresh evidence 跑满
   - 用新 orchestrator 覆盖完整 six-tag family：
     - `4-step / 10us`
     - `4-step / 10us / sp64`
     - `8-step / 20us`
     - `8-step / 20us / sp64`
     - `16-step / 40us`
     - `16-step / 40us / sp64`
   - 这样 HotSpot / route provenance / memory-NMC pressure 才能在统一 provenance 下比较

2. 真正进入 gating-heavy control-plane 建模
   - 重点不再是给 case 增加更多 gating 参数
   - 而是研究如何在 `mesh3d_template` 或等价构图层里显式注入 gating decision event source
   - 当前最直接的候选方向仍然是：
     - `GatingPE`
     - 或一个更小、更受控的 synthetic gating controller
   - 只有这一步完成后，`runtime_activation_gating_total > 0` 才会成为真正的体系结构行为，而不是 summary 层的愿望值

### 10.22 2026-03-24 补充刷新：gating-heavy 最小 control-plane 已经转正，windowed dense/native family 也已跑满 fresh 主线

这一轮之后，当前 3D SNN 芯片建模状态有两个关键变化：

1. `windowed native-dense family` 已不再只是 compose-only 验证，而是完成了真实 six-tag fresh run
   - family root:
     - `snn3dexp/analysis/windowed_native_dense_family/native_dense_family_mainline_20260324/`
   - 对 `fixed_step_multicase_sweep_summary.json` 重新统计后，当前结果是：
     - `derived_run_count = 18`
     - `derived_status_counts = {"smoke_passed": 18}`
   - `phase2_artifacts/codesign_surface/memory_nmc_codesign_surface_summary.json` 也已经稳定存在，并给出：
     - `surface_label = native_dense_fixed_step_8_20us`
     - `window_baseline_rows = 9`
     - `window_bundle_breakdown_rows = 6`
     - `window_memory_model_breakdown_rows = 6`
     - `window_spike_sensitivity_rows = 9`
   - 典型 same-tag fresh 指标仍然说明 bundle/native 这条 windowed 路线会明显放大 memory pressure：
     - `native_dense_fixed_step_8_20us`
       - `memory_requests_total_delta = 1036`
       - `memory_requests_total_amplification_ratio = 3.3125`
       - `stall_on_step_gate_cycles_total_delta = 76821`
     - `native_dense_fixed_step_8_20us_sp64`
       - `memory_requests_total_delta = 1344`
       - `memory_requests_total_amplification_ratio = 4.0`
       - `stall_on_step_gate_cycles_total_delta = 19755`

2. `gating-heavy` 不再停留在 probe 合同，而是已经有最小可工作的真实 control-plane 注入路径
   - 新 active case:
     - `snn3dexp/cases/full_3d_snn_window_gating_event_synth/`
   - 这里最重要的架构决策不是“又加了一个 case”，而是 control-plane 介入方式已经定型：
     - 没有采用 `GatingPE -> router.local`
     - 原因是当前 `router_X.local` 已被 `multicore_pe_X.network_interface` 占用
     - 因而最小可行路径改成复用现有：
       - `GlobalGasStepController -> gas_step_ctrl -> MultiCorePE`
   - 这条链路的代码事实现在已经落在：
     - `snn3dexp/platform/sst_graph.py`
       - 当 `gating_mode = event` 且 `synthetic_gating_enable = 1` 时，把 synthetic gating 参数投到 `GlobalGasStepController`
     - `GlobalGasStepController`
       - 在 `broadcastStart_(seq)` 之后沿 `pe_linkX` 广播 `GatingDecisionEvent`
     - `MultiCorePE`
       - 在 `gas_step_ctrl` 端口优先处理 `GatingDecisionEvent`
       - 并把决策下发到 core-level `applyGatingDecision(...)`
   - 也就是说，当前真实生效的是“专用 step/gas 控制面 gating”，而不是“再插一个走普通 NoC local 口的功能 PE”

3. `probe` 与 `synth` 现在形成了一组非常清晰的对照合同
   - `full_3d_snn_window_gating_event_probe`
     - 仍然表示“参数面已接通，但没有事件源”
     - fresh compose:
       - `runtime_activation_total = 0`
       - `runtime_activation_gating_total = 0`
       - `runtime_activation_direct_total = 0`
   - `full_3d_snn_window_gating_event_synth`
     - 表示“最小 synthetic control-plane 已真实发出 gating decisions”
     - fresh smoke:
       - `run_tag = gating_event_synth_smoke_20260324`
       - `status = smoke_passed`
       - `actual_activation_observed = true`
       - `actual_activation_source = sst_stats_route3d_native_runtime`
       - `runtime_activation_total = 256`
       - `runtime_activation_gating_total = 256`
       - `runtime_activation_direct_total = 0`
       - `runtime_unique_sources_total = 32`

到这里为止，当前“回到 SNN 3D 芯片本身”的下一阶段任务，可以从原先的“如何让 gating 活起来”继续收敛成更具体的三条主线：

1. 把 `gating_event_synth` 纳入 family/ablation 主链
   - 目标不是只证明它能触发
   - 而是形成 `direct / bundle / monolithic / gating` 四路同标签比较面
   - 这样才能把 gating-heavy control-plane 放进和 memory/NMC pressure 同 provenance 的体系结构对照里

2. 把 synthetic gating 从“固定 offset/stride 的最小注入器”推进到“可描述 3D 控制面策略的参数化注入器”
   - 优先扩展的不是更多 case 数量
   - 而是更贴近芯片架构语义的三个方向：
     - target policy
     - rows subset / source selection
     - per-step variation
   - 只有这样，后续的 gating hotspot、stack-local pressure、跨 tier 热点迁移才有真实建模基础

3. 把这条已经转正的 gating-heavy runtime 正式接回 thermal loop
   - 当前 thermal 仍然是 HotSpot sidecar / proxy-grid 主线
   - 下一步重点不是马上追论文图，而是让：
     - `route provenance`
     - `memory/home-stack pressure`
     - `runtime gating activity`
     - `thermal sidecar`
     四者先在 same-tag 产物上闭环
   - 当这条 2D/sidecar 证据链稳定以后，再推进到更强的 3D 堆叠热建模才更稳，不会把控制面 gap 和热模型 gap 混在一起

### 10.23 2026-03-24 补充刷新：`gating_event_synth` 已正式纳入 family/ablation/codesign 主链，但 real smoke 还残留 `bundle_v3` 稳定性点

这一轮真正完成的，不再只是“有一个 gating synth case 可以单跑”，而是把它接进了现有 windowed fixed-step family 的正式工具链：

1. family 默认 case 集已经扩成四路
   - 当前 canonical fixed-step family 默认包含：
     - `full_3d_snn_window`
     - `full_3d_snn_window_bundle_v3`
     - `full_3d_snn_window_monolithic_proxy`
     - `full_3d_snn_window_gating_event_synth`
   - 这意味着：
     - `run_fixed_step_multicase_sweep`
     - `analyze_fixed_step_sweep`
     - `run_windowed_native_dense_family`
     现在默认都会把 gating synth 当成 family 一等成员，而不再需要额外手工拼接

2. fixed-step summary 与 codesign surface 现在已经有第四类正式对照行
   - `analyze_fixed_step_sweep` 新增：
     - `gating_breakdown`
     - `fixed_step_gating_breakdown.csv`
   - 这类 row 的语义是：
     - `direct -> gating`
     - 并且不只比较 memory/stall，也显式投影：
       - `runtime_activation_total`
       - `runtime_activation_gating_total`
       - `runtime_activation_direct_total`
       - `runtime_unique_sources_total`
   - `export_memory_nmc_codesign_surface` 也新增：
     - `window_gating_breakdown_rows`
     - Markdown section:
       - `Window Gating vs Direct`
   - `export_phase2_paper_artifacts` 则把它正式纳入 summary count：
     - `window_gating_breakdown_row_count`

3. fresh 证据现在分成两层，必须分开看
   - 第一层是工具链集成证据，已经成立：
     - `python3 -m unittest ...`
       - `128 tests in 5.387s`
       - `OK`
     - fresh compose-only family：
       - `snn3dexp/analysis/windowed_native_dense_family/native_dense_family_gating_compose_20260324/`
       - 已明确给出：
         - `window_case_ids = [direct, bundle, monolithic, gating]`
         - `fixed.gating_breakdown_count = 1`
         - `codesign.window_baseline_count = 4`
         - `codesign.window_gating_breakdown_count = 1`
   - 第二层是 real smoke integration，当前还没有完全转正：
     - fresh single-tag smoke：
       - `native_dense_family_gating_smoke_20260324`
     - 其中：
       - `full_3d_snn_window_bundle_v3 / native_dense_fixed_step_4_10us`
       - `returncode = -11`
       - `status = smoke_failed`
     - 也就是说：
       - 这轮四路 family 的 Python/analysis/codesign integration 已经打通
       - 但要把它宣称为“real smoke family 全部稳定”还不诚实，因为 `bundle_v3` 这条旧 runtime 路线还需要单独排查

因此，当前 next arc 比上一版更具体，也更收敛：

1. 第一优先级不再是“把 gating 接进 family”
   - 这件事已经完成
   - 现在应转向“把四路 family 在 real smoke 上重新压稳”

2. 最直接的未闭环点，就是 `bundle_v3` 的 actual smoke 稳定性
   - 需要确认这是：
     - 旧问题复现
     - 环境/产物污染
     - 还是 fixed-step family 扩成四路后暴露出的执行序列问题
   - 在这个点没重新压稳前，不宜直接把四路 family 当作新的 full-runtime baseline

3. 一旦 `bundle_v3` smoke 恢复稳定，下一步就可以真正进入四路体系结构比较
   - `direct / bundle / monolithic / gating`
   - 同标签对照：
     - route provenance
     - memory/home-stack pressure
     - runtime activation/gating activity
     - HotSpot sidecar thermal response
   - 这会比之前只做三路 memory-style 对照，更接近“3D SNN 芯片控制面 + 数据面 + 热面”的统一建模
