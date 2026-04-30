# 3D SNN 代码对齐现状总览与 NextArc 刷新

Date: 2026-03-23
Owner: Fufu
Status: Code-aligned refresh after explicit 3D route contract + real home-path explainability chain + refreshed memory/NMC surface

Update:
截至本次实现，`memory/NMC + co-design` 主线已经从“统一分析面”进一步推进到“可执行 canonical matrix”：

- 新增 `snn3dexp/tools/run_fixed_step_multicase_sweep.py`
- 新增 `snn3dexp/tools/run_memory_nmc_codesign_matrix.py`
- `fixed_step` run tag 现在支持带隔离前缀的形式，例如 `matrix23_fixed_step_4_10us`
- 已完成一次真实 `compose-only` 编排验证，产物位于：
  - `snn3dexp/analysis/codesign_matrix/matrix23_compose_smoke/memory_nmc_codesign_matrix_summary.json`
- `run_memory_nmc_codesign_matrix.py` 已进一步支持 richer unified surface 输入：
  - `--baseline-overlay-ablation`
  - `--stop-window-ablation`
  - `--hotspot-runtime-summary`
- `run_memory_nmc_codesign_matrix.py` 现在还可作为 `phase2` canonical main entry：
  - `--export-phase2-artifacts`
  - `--export-route-runtime-diff`
  - `--phase2-mainline`
- 新增 `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- `analyze_fixed_step_sweep.py` 现在会把 runtime-controller / real-home-path / dataflow-alignment 语义下沉到 `window_route` compare row
- 已完成一次真实 `isolated-tag runtime smoke` 编排验证，产物位于：
  - `snn3dexp/analysis/codesign_matrix/matrix23_runtime_smoke/memory_nmc_codesign_matrix_summary.json`
- 已完成一次真实 `phase2-mainline compose-only smoke`，产物位于：
  - `snn3dexp/analysis/codesign_matrix/matrix23_phase2_mainline_smoke/memory_nmc_codesign_matrix_summary.json`
- 已完成一次真实 `phase2-mainline runtime smoke`，产物位于：
  - `snn3dexp/analysis/codesign_matrix/matrix23_phase2_mainline_runtime_smoke/memory_nmc_codesign_matrix_summary.json`
- 上述 runtime smoke 已确认：
  - traffic family 使用独立 tag `matrix23_runtime_smoke_traffic`
  - fixed-step family 使用独立 prefixed tag `matrix23_runtime_fixed_step_4_2us`
  - `codesign_surface.sources` 已正式带出 `baseline_overlay_ablation_paths / stop_window_ablation_paths / hotspot_runtime_summary_path`
  - `matrix_rows` 已形成四类 canonical group：
    - `traffic_route`
    - `traffic_memory`
    - `window_route`
    - `window_memory`

## 1. 文档目的

这份文档用于把当前 `3D SNN` 平台的真实状态重新压回代码事实，并回答三个问题：

1. 现在的 `snn3dexp + SnnDL` 到底已经实现到了哪一层。
2. 哪些能力已经是“平台正式能力”，哪些仍然属于“有实现但仍带 bootstrap/proxy 依赖”。
3. 基于当前代码，而不是基于历史任务记忆，下一阶段最值得投入的体系结构建模方向是什么。

如果这份文档与更早的 `nextarc` 文档在细节上冲突，应优先以：

- 当前代码
- 当前测试
- 当前 fresh artifact

为准。

## 2. 本轮代码证据基线

### 2.1 直接核对的主文件

本轮直接核对了下列主文件：

- `snn3dexp/mesh3d_template/spec.py`
- `snn3dexp/noc/multicast_3d.py`
- `snn3dexp/memory/hbm_stack.py`
- `snn3dexp/memory/monolithic_proxy.py`
- `snn3dexp/platform/build_system.py`
- `snn3dexp/platform/sst_graph.py`
- `snn3dexp/runtime/policy.py`
- `snn3dexp/thermal/hotspot_driver.py`
- `snn3dexp/tools/run_case.py`
- `snn3dexp/tools/analyze_ablation.py`
- `snn3dexp/tools/analyze_fixed_step_sweep.py`
- `snn3dexp/tools/analyze_route_memory_joint.py`
- `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
- `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- `snn3dexp/tools/export_controller_explainability_loss_report.py`
- `snn3dexp/tools/export_phase2_paper_artifacts.py`
- `snn3dexp/tools/route_memory_joint_loader.py`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ISynapseRoute.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`

### 2.2 本轮 fresh 验证

本轮直接跑过并通过的验证：

- `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_memory_nmc_codesign_surface snn3dexp.tests.test_controller_explainability_loss_report -v`
  - `23/23` 通过
- `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_window_stop_multicase_sweep snn3dexp.tests.test_analyze_window_stop_multicase_sweep snn3dexp.tests.test_phase2_paper_artifacts snn3dexp.tests.test_memory_nmc_codesign_surface snn3dexp.tests.test_ablation_contract snn3dexp.tests.test_transfer_kind_mechanism_report snn3dexp.tests.test_controller_explainability_loss_report snn3dexp.tests.test_route_memory_joint_analysis snn3dexp.tests.test_synapse_memory_semantics -v`
  - `55/55` 通过
- `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_fixed_step_multicase_sweep snn3dexp.tests.test_run_memory_nmc_codesign_matrix snn3dexp.tests.test_fixed_step_sweep snn3dexp.tests.test_window_stop_multicase_sweep snn3dexp.tests.test_memory_nmc_codesign_surface snn3dexp.tests.test_phase2_baseline_suite -v`
  - `25/25` 通过
- `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix snn3dexp.tests.test_export_memory_nmc_route_runtime_diff snn3dexp.tests.test_fixed_step_sweep snn3dexp.tests.test_phase2_paper_artifacts snn3dexp.tests.test_memory_nmc_codesign_surface snn3dexp.tests.test_run_fixed_step_multicase_sweep snn3dexp.tests.test_phase2_baseline_suite -v`
  - `36/36` 通过

这说明这份状态判断不是停留在静态读代码，而是基于 fresh regression。

### 2.3 本轮 spot-check 的正式产物

本轮额外 spot-check 了下列 artifact：

- `snn3dexp/analysis/full_3d/task_route3d_structured_runtime_stats_v5/phase2_case_summary.json`
- `snn3dexp/analysis/codesign_surface/codesign_single_20us_20260322_same_tag_path_chain_refresh/memory_nmc_codesign_surface_summary.json`
- `snn3dexp/analysis/controller_explainability_loss/controller_runtime_refresh_20260322_vs_codesign_single_20us_20260322_vs_perf_20us_path_chain_refresh/controller_explainability_loss_report_summary.json`
- `snn3dexp/analysis/codesign_matrix/matrix23_runtime_smoke/memory_nmc_codesign_matrix_summary.json`
- `snn3dexp/analysis/codesign_matrix/matrix23_phase2_mainline_smoke/memory_nmc_codesign_matrix_summary.json`
- `snn3dexp/analysis/codesign_matrix/matrix23_phase2_mainline_runtime_smoke/memory_nmc_codesign_matrix_summary.json`

其中已经确认：

- `route_kernel.actual_activation_source = "sst_stats_route3d_native_runtime"`
- `route_kernel.runtime_activation_total = 512`
- refreshed `memory_nmc_codesign_surface` 中 `full_3d` 的：
  - `real_home_traffic_signal_level = "runtime_controller"`
  - `pe_nic_real_home_path_signature = "metadata_lookup->stream_region->writeback_region"`
  - `synapse_real_home_path_signature = "synapse_gather"`
- refreshed `controller_explainability_loss_report` 中 `full_3d` 的：
  - `explainability_transition = "stable"`
  - `dominant_path_explainability_transition = "stable"`
  - `loss_reasons = []`
- `matrix23_runtime_smoke` 中：
  - `traffic_manifest.run_tag = "matrix23_runtime_smoke_traffic"`
  - `fixed_step_execution.run_tags = ["matrix23_runtime_fixed_step_4_2us"]`
  - `codesign_surface.sources.baseline_overlay_ablation_paths` 非空
  - `codesign_surface.sources.stop_window_ablation_paths` 非空
  - `codesign_surface.sources.hotspot_runtime_summary_path` 已落入统一 summary
  - `matrix_rows` 覆盖：
    - `traffic_route`
    - `traffic_memory`
    - `window_route`
    - `window_memory`
- `matrix23_phase2_mainline_smoke` 中：
  - `phase2_artifacts.available = true`
  - `route_runtime_diff.available = true`
  - 已真实落出：
    - `phase2_artifacts/phase2_runtime_summary.json`
    - `route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`
  - `matrix_rows` 继续保持四类 canonical group：
    - `traffic_route`
    - `traffic_memory`
    - `window_route`
    - `window_memory`
- `matrix23_phase2_mainline_runtime_smoke` 中：
  - `baseline_run_tag = "matrix23_phase2_mainline_runtime_traffic"`
  - `fixed_step_run_tags = ["matrix23_phase2_mainline_runtime_fixed_step_4_2us"]`
  - `phase2_artifacts.available = true`
  - `route_runtime_diff.available = true`
  - `matrix_rows` 继续覆盖四类 canonical group：
    - `traffic_route`
    - `traffic_memory`
    - `window_route`
    - `window_memory`

## 3. 一页结论

当前 `3D SNN` 已经不应再被表述成“3D 功能存在性的原型平台”，而应表述为：

`一个具备真实 3D NoC / memory paradigm / workload runtime / analysis surface / thermal sidecar 的体系结构级建模平台`

它已经正式具备六个能力层：

1. 隔离的 `snn3dexp` 平台层
2. 显式 3D multicast contract 与 3D native router
3. `HBM-like / monolithic-like / legacy_per_pe` 三种 memory 范式
4. `traffic_mem` 与 `windowed SNN` 两条 processing/runtime 主路径
5. `route_memory_joint -> codesign surface -> controller explainability` 的统一分析链
6. `thermal proxy / HotSpot sidecar / runtime adaptive` 的约束与控制侧车

但它仍然存在四个关键边界：

1. route kernel 虽然已经是接口级 3D，但 source semantics 仍主要来自 `edges_csv` 或 legacy-built route tables 的 bootstrap。
2. memory/NMC 目前仍是 near-memory hierarchy / proxy compare，不是带真实近存算子执行的 PIM/NMC 数据通路。
3. `windowed SNN` 已经是真实路径，但平台的主 compare anchor 仍偏 `traffic_mem`，二者的统一机理解释还需要继续推进。
4. thermal/runtime adaptive 已经够做 co-design 约束，但 HotSpot 还不是更广泛 case 的正式 execute-loop 输入。

因此，当前最值得投入的主线已经非常明确：

`从“3D 功能存在性”转向“memory/NMC + co-design 主线”，并在此基础上继续把 route kernel 从 bootstrap 推向 synapse-native source semantics`

## 4. 当前 3D SNN 的全貌

### 4.1 平台层已经完整隔离

`snn3dexp/` 现在不是几个实验脚本，而是一套独立平台：

- `mesh3d_template/` 负责 schema/default/resolve
- `platform/` 负责 effective config、platform summary、SST graph
- `noc/` 负责 3D router/link descriptor
- `memory/` 负责 `hbm_like / monolithic_like / legacy_per_pe`
- `runtime/` 负责 adaptive policy
- `thermal/` 负责 proxy/HotSpot/replay
- `tools/` 负责 run/analyze/export
- `tests/` 负责 contract 和 regression

当前 `snn3dexp/cases/` 下已有 `13` 个显式 case：

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

`run_case.py` 中还固定维护了 `9-case baseline suite`：

- `baseline_2d`
- `memory_only_3d`
- `noc_only_3d`
- `full_3d`
- `full_3d_mapping`
- `full_3d_thermal_guard`
- `full_3d_monolithic_proxy`
- `full_3d_snn_window`
- `full_3d_snn_window_monolithic_proxy`

所以当前平台已经有：

- case catalog
- baseline suite
- smoke/compose/run roots
- analysis roots
- compare/export pipeline

这层已经是正式平台能力，不再是临时预研脚本。

### 4.2 NoC / route 面已经进入“接口级 3D”

当前 route 面最关键的事实有五个：

1. `snn3dexp/noc/multicast_3d.py` 已按 `native_3d_enable && dim_z > 1` 自动选择 `SnnDL.MulticastRouter3DNative`。
2. `ISynapseRoute::BlockTarget` 已显式携带 `block_z / block_d / ingress_node / core_mask`。
3. `ISynapseRoute` 已显式暴露 `multicastBlockD()`。
4. `SpikeCommSubsystem` 已真正消费 `multicastBlockD()` 并在 `block_d > 1` 时发射显式 3D `SpikeKeyV4 / BundleV3`。
5. `MulticastRouter3DNative` 已处理：
   - `up/down`
   - `z-first`
   - intra-stage local delivery
   - `bundle_v3`
   - `block_z_mismatch / ingress_out_of_block / rebuild_fail` 等异常计数

这意味着 `ISynapseRoute -> SpikeCommSubsystem -> MulticastRouter3DNative` 这条链现在已经不是“实现上支持 3D”，而是“接口上就是 3D”。

### 4.3 `SynapseRouteSubsystem3D` 已是 3D-native route kernel，但仍带 bootstrap 依赖

当前 `SynapseRouteSubsystem3D` 的准确定位不是 “legacy wrapper”，也不是“完全独立的新后端”，而是：

`3D-native route kernel with bootstrap dependency`

理由很明确：

- `computeFanout()` 在 `native_route_synthesis_active_` 时会直接走 `computeFanoutNative3D_()`
- `computeMulticastTargets()` 在 native 路径下会走 `computeMulticastTargetsNative3D_()`
- native runtime stats 会通过 `recordNativeRuntimeStats_()` 正式写入 workload/runtime 统计

但与此同时：

- `tryInitNativeRoutes_()` 当前仍主要依赖：
  - `buildNativeRoutesFromEdgesCsv3D_()`
  - `buildNativeRoutesFromLegacyBuiltRoutes3D_()`

所以当前 route 面已经解决的是：

- 3D packet/block contract
- 3D fanout execution
- 3D volumetric target synthesis
- 3D runtime observability

尚未完全解决的是：

- source semantics 默认仍不是 `synapse/BCSR/GAS` 原生生成

### 4.4 memory 范式已经是 builder/runtime/analyzer 的共同自变量

`mesh3d_template/spec.py` 当前正式支持三类 memory kind：

- `hbm_like`
- `monolithic_like`
- `legacy_per_pe`

这三类 memory 已经不是 case label，而是 builder/runtime/analyzer 的共同输入。

#### HBM-like

`snn3dexp/memory/hbm_stack.py` 已建模：

- shared stack
- `xy_quadrant` home policy
- semantic regions：
  - `metadata`
  - `gather`
  - `stream`
  - `writeback`
- `build_node_memory_bindings()`
- `build_synapse_source_descriptors()`
- `memHierarchy.simpleMem / memHierarchy.ramulator2` 两条 backend 路径

当前 canonical `full_3d` / `full_3d_snn_window` / `full_3d_runtime_adaptive` case spec 默认都配置为：

- `memory.kind = "hbm_like"`
- `backend = "ramulator2"`

#### Monolithic-like

`snn3dexp/memory/monolithic_proxy.py` 已建模：

- per-tier local stack
- `xy_quadrant_local_tier`
- `tier_local_stack_attach_latency_ns`
- `vertical_mem_hop_latency_ns = 0`
- `vertical_bandwidth_scale`
- `thermal_coupling_factor`

当前 canonical `full_3d_monolithic_proxy` 默认配置为：

- `memory.kind = "monolithic_like"`
- `backend = "simple"`

所以当前 memory 面的真实结论是：

- 平台已经能比较 `HBM-like shared stack` 与 `monolithic-like near-memory proxy`
- 但这仍然是 hierarchy/proxy compare，不是执行型 PIM/NMC

### 4.5 workload/runtime 已经有两条正式主路径

当前 `processing.workload_impl` 已正式支持两条主路径：

- `traffic_mem`
- `snn`

#### `traffic_mem`

适合作为稳定的 architecture pressure baseline：

- traffic injection
- stream memory traffic
- route/memory overlap
- stack pressure / controller pressure

#### `windowed SNN`

当前已经不是 placeholder，而是真实 runtime path：

- `workload_impl = "snn"`
- `GatherBufferIF`
- `GlobalGasStepController`
- `gas_window_*`
- weight/GAS/apply/scatter counters

`platform/sst_graph.py` 中也已经显式生成：

- `GatherBufferIF` memory subcomponent
- `GlobalGasStepController`
- control-plane links

所以当前 `windowed SNN` 已经不只是“能跑 smoke”，而是已经拥有真实的：

- control plane
- memory path
- fixed-step sweep
- compare/export pipeline

### 4.6 analysis 链已经形成统一 surface，而不是零散 summary

当前分析链已经形成：

`run_case -> phase2_case_summary / stack_nmc / route_memory_joint -> ablation -> fixed-step sweep -> memory_nmc_codesign_surface -> controller explainability / paper artifacts`

关键工具包括：

- `analyze_ablation.py`
- `analyze_fixed_step_sweep.py`
- `analyze_route_memory_joint.py`
- `export_memory_nmc_codesign_surface.py`
- `export_controller_explainability_loss_report.py`
- `export_phase2_paper_artifacts.py`

这意味着平台当前已经能系统回答：

- `direct_v4 vs bundle_v3`
- `HBM-like vs monolithic-like`
- `traffic_mem vs windowed SNN`
- `route pressure -> memory pressure -> controller explainability`

而不是只能查看单个 case 的局部 JSON。

### 4.7 最新增量：home-path explainability chain 已从 proxy 下沉到真实语义

这是相对于更早状态文档最重要的新增量之一。

当前 `analyze_route_memory_joint.py` 已经在：

- `memory.real_controller_pressure`
- `memory.home_stack_controller_proxy`
- `memory.home_stack_dataflow`

之间打通了真实 explainability chain。

其中 `home_stack_dataflow.initiator_groups.{pe_nic_to_home_stack,synapse_source_to_home_stack}` 现在会显式产出：

- `controller_pressure_summary`
- `home_path_summary`

其意义是：

- `PE/NIC -> home stack` 不再只是 dominant stack proxy，而是显式路径
  - `metadata_lookup -> stream_region -> writeback_region`
- `synapse/home-stack` 不再只是 source attribution，而是显式路径
  - `synapse_gather`

并且：

- `export_memory_nmc_codesign_surface.py` 已把这条链投影到 unified surface
- `export_controller_explainability_loss_report.py` 已把它继续消费成：
  - `dominant_path_explainable`
  - `dominant_path_chain_kind`
  - `dominant_path_explainability_transition`
- `route_memory_joint_loader.py` 会把缺少这些新字段的旧 summary 判定为 stale 并自动 refresh

当前 refreshed artifact 已经证明：

- 旧 surface 中出现的 explainability loss，有一部分其实是 stale schema 问题
- 刷新后 `full_3d` 在 controller/path explainability 上是 `stable`

### 4.8 thermal/runtime adaptive 已经够做 co-design 约束层

当前 thermal/runtime 侧的真实状态是：

- `runtime/policy.py` 已能根据：
  - `route_memory_overlap`
  - `vertical_link_pressure`
  - `stack_hotspot_penalty`
  做出 runtime weight adjustment / home-route adjustment
- `thermal/hotspot_driver.py` 已能生成 HotSpot sidecar artifact
- `platform/build_system.py` 已把：
  - thermal replay
  - thermal consumer snapshot
  - hotspot adapter payload
  - runtime summary
  统一接到 platform summary

这说明 thermal/runtime 侧已经不是缺接口，而是：

- 具备 proxy/sidecar/execute-v1
- 但还不是平台主矛盾

## 5. 当前状态分层判断

### 5.1 已经属于“平台正式能力”的部分

- `snn3dexp` 平台隔离
- `13` 个 case 和 `9-case baseline suite`
- 显式 3D route contract
- `MulticastRouter3DNative`
- `HBM-like / monolithic-like / legacy_per_pe`
- `traffic_mem / snn`
- `route3d native runtime stats`
- `route_memory_joint / fixed-step sweep / unified codesign surface`
- real home-path explainability chain
- HotSpot sidecar 和 runtime adaptive v1

### 5.2 已经能用，但仍应视为“带依赖的半正式能力”

- `SynapseRouteSubsystem3D` 的 native route synthesis
  - 因为仍带 `edges_csv / legacy-built routes` bootstrap
- `bundle_v3` 的 3D native forwarding
  - 已进入真实 smoke 与 contract，但仍主要是实验/对照路径
- `windowed SNN` 的长窗口研究方法
  - 已有 fixed-step sweep，但还需要继续扩大真实 compare methodology
- thermal-aware execute
  - 已有 v1，但 HotSpot 还不是更广泛 case 的正式闭环输入

### 5.3 当前还没有的能力

- 默认 synapse-native route source semantics
- 真实 NMC/PIM compute operator path
- 以 HotSpot 为正式硬约束的大范围 runtime execute loop
- 脱离 fresh/refresh tooling 也始终保持 schema 一致的历史 artifact 库

## 6. 当前最关键的四个边界

### 边界 A: route source semantics 仍主要是 bootstrap

route 面今天的主缺口已经不是“没有 3D route kernel”，而是：

- route kernel 已在
  - 接口
  - fanout
  - target synthesis
  - runtime stats
  上成立
- 但 route source 仍主要由
  - `mapping_edges_file`
  - legacy-built route tables
  提供

下一步真正的 route 主线应该是：

- 从 bootstrap route source 推向更真实的 `synapse/BCSR/GAS` source semantics

### 边界 B: memory/NMC 仍是 hierarchy/proxy，不是执行型 NMC

当前平台已经非常适合研究：

- stack locality
- controller pressure
- home-stack skew
- direct vs bundle 对 memory pressure 的影响
- HBM-like vs monolithic-like 的拓扑差异

但它还不适合声称：

- 已经实现真实近存算子执行
- 已经实现真实 PIM microarchitecture

所以当前 memory/NMC 的研究定位应保持在：

`near-memory hierarchy / co-design platform`

### 边界 C: `windowed SNN` 已成立，但机理 compare 仍需继续收敛

当前已经有：

- `windowed SNN` case
- fixed-step sweep
- direct/bundle/monolithic compare

但还需要进一步把：

- `traffic_mem` 的稳定 baseline 能力
- `windowed SNN` 的真实业务语义

统一到同一套更强的机理解释上。

### 边界 D: 历史 artifact freshness 仍不能等同于当前代码能力

当前仓库仍存在真实情况：

- 旧 `route_memory_joint_summary` 可能不含新的 `home_stack_dataflow` 字段
- 旧 `codesign surface` 可能不含新的 initiator-level chain 字段
- 旧 explainability report 可能因此表现为“loss”

但这不应被误解为平台没有能力。

当前正确判断顺序应始终是：

`当前代码 > 当前测试 > fresh refreshed artifact > 历史 artifact`

## 7. 当前最值得投入的 NextArc

### Priority 1: 把重心放到 memory/NMC + co-design

这是当前最值得投入的主线，原因很直接：

- route 面已经足够强，继续堆更多 router feature 的边际收益在下降
- memory/NMC 面现在已经有真正可以回答架构问题的 surface
- 最新的 initiator-level home-path explainability chain 已经把这条主线的数据基础补齐

下一阶段最值得直接做的内容包括：

- `direct_v4 vs bundle_v3` 对：
  - `pe_nic_real_home_path_service_deficit_total`
  - `synapse_real_home_path_service_deficit_total`
  的放大效应
- `HBM-like vs monolithic-like` 在：
  - controller hotspot
  - stack skew
  - home-path deficit
  上的机理对照
- `traffic_mem` 与 `windowed SNN` 的统一 explainability 对齐

### Priority 2: 把 route kernel 从 bootstrap 推向 synapse-native

这是 route 面剩下的最关键一跳。

不是再去优先扩：

- 更多 packet 版本
- 更多 router debug flag
- 更多 isolated transport feature

而是要把 route source 从：

- `edges_csv`
- legacy-built routes

进一步推向：

- 更真实的 `synapse/BCSR/GAS` source semantics

### Priority 3: 在前两者稳定后，再把 HotSpot 真正放进 execute loop

thermal/runtime 不该退出主线，但也不该抢在 memory/NMC 和 source semantics 前面。

原因是：

- thermal 现在已经足够做约束层
- 但如果 route/memory/workload 主语义还在继续原生化，过早重压 thermal execute loop 会放大不稳定性

因此更合理的顺序是：

1. memory/NMC + co-design surface 继续做实
2. synapse-native route source 继续推进
3. HotSpot in loop 扩到更多 canonical case

## 8. 与旧文档的关系

这份文档建议作为当前的主状态入口。

更早文档仍有价值，但应按如下方式理解：

- `2026-03-20-3d-snn-current-status-and-nextarc.md`
  - 仍可作为上一轮大状态快照
- `2026-03-21-snn3d-chip-nextstep-architecture-modeling-design.md`
  - 仍可作为上一轮 next-step 设计判断
- 但从 2026-03-23 起，关于当前平台全貌、当前边界和当前优先级，应优先以本文为准

## 9. 最简结论

当前 `3D SNN` 平台已经完成了从“功能存在性原型”到“体系结构级建模平台”的跃迁。

它现在最强的部分不是：

- 又多了一个 3D feature

而是：

- 3D route contract 已成立
- memory paradigm 已平台化
- workload runtime 已双路径化
- analysis/explainability surface 已系统化

因此，下一阶段最正确的主线不是再问“还能不能做成 3D”，而是更具体地问：

`这套 3D SNN 平台，能否把 route / memory / home-path / controller hotspot 的 co-design 机理真正讲透，并把 bootstrap route source 推向 synapse-native 语义`

## 10. 2026-03-24 补充刷新：phase2 高层导出已接入 route/runtime diff

这轮补强之后，`route_runtime_diff` 已经不再只是 canonical matrix 旁路产物，而是正式接进了更高层的 `phase2/paper` 导出链。

当前新增成立的能力是：

- `export_memory_nmc_route_runtime_diff.py`
  - 不只导出 `traffic_route_diffs / window_route_diffs`
  - 还会额外固化 `window_route_mechanism_summary`
  - markdown 中新增 `Window Route Mechanism Focus`
- `export_phase2_paper_artifacts.py`
  - 在成功导出 `memory_nmc_codesign_surface` 后
  - 会继续导出 `route_runtime_diff`
  - 并把它挂回 `phase2_runtime_summary.json`

因此现在 phase2 高层 summary 已能直接暴露：

- `outputs.route_runtime_diff_summary_json`
- `outputs.route_runtime_diff_csv`
- `outputs.route_runtime_diff_markdown`
- `route_runtime_diff.window_route_mechanism_summary`

这意味着我们终于从“route/runtime diff 已存在”推进到了“高层报告链可以直接消费 diff 与机理摘要”。

另外，`window_route` 的机理摘要也从原来的原始 delta，进一步上抬成了可直接阅读的 summary：

- `alignment_transition_counts`
- `dominant_axis_counts`
- `top_stall_rows`
- `controller_outstanding_delta_total_sum`
- `real_home_path_service_deficit_total_delta_sum`

基于一轮 fresh analysis-only export：

- 输出目录：
  - `/home/xgy/remote/snn3dexp/analysis/phase2_route_runtime_refresh_20260324/matrix23_phase2_mainline_runtime_smoke`
- 当前这组 `2us fixed-step` lane 的 `window_route_mechanism_summary` 显示：
  - `alignment_transition_counts = {"alignment_degraded": 1}`
  - `dominant_axis_counts = {"controller_outstanding": 1}`
  - `stall_on_step_gate_cycles_per_completed_step_delta_sum = 6528.0`
  - `memory_requests_per_completed_step_delta_sum = 678.0`

这给了下一步一个更清晰的研究入口：

- 不是再泛泛地说 `bundle` 更差
- 而是可以继续追问：
  - 为什么在当前 `2us fixed-step` lane 上，主导轴先表现成 `controller_outstanding`
  - 它与 `step-gate stall`、`home-path deficit` 的时序关系是什么
  - 这种主导轴是否会随着 stop-window 或 full-runtime 改变

## 11. 2026-03-24 补充刷新：canonical artifact naming 与下一阶段主指标面

这轮额外收口之后，一个之前容易被忽略、但实际上会直接影响高层报告一致性的问题已经可以明确表述：

`当前 3D SNN / thermal / codesign 导出链，不能再依赖 artifact 路径名本身来代表 run identity。`

原因很简单：

- 下游正式产物已经开始出现：
  - `ablation_summary_balanced_20us_refresh_20260322_015217.json`
  - `same_tag_path_chain_refresh`
  - `*_default_export`
  这类带时间戳、带 refresh 语义、带后处理标签的路径名
- 如果高层 exporter 仍回到 `path.stem` / `parent.name` 取标签
- 同一个 canonical run 就会在：
  - `phase2`
  - `transfer_kind`
  - `controller_explainability`
  三层里重新漂成不同名字

### 11.1 当前应该遵守的 artifact naming contract

对后续 `ablation + runtime_refresh + paper_artifacts` 主线，当前建议把命名 contract 明确为：

1. canonical baseline ablation 的正式名，优先使用：
   - `<canonical_tag>_ablation.json`
2. canonical runtime-refresh overlay 的正式名，优先使用：
   - `<canonical_tag>_ablation_runtime_refresh.json`
3. 当前兼容但不建议继续扩散的 alias：
   - `ablation_summary_<canonical_tag>_runtime_refresh.json`
4. 允许存在带时间戳/刷新后缀的临时或中间产物，例如：
   - `ablation_summary_balanced_20us_refresh_20260322_015217.json`
   但高层导出链必须从 summary 内的 canonical identity 恢复 run tag，而不是把文件名本身当正式身份。

对应地，当前高层 surface/report 的 identity 解析顺序应理解为：

1. `surface_label`
2. `sources.surface_label`
3. `sources.baseline_run_tag`
4. `sources.hotspot_run_tag`
5. summary rows 内唯一稳定的 `run_tag`
6. 最后才允许回退到经过规范化裁剪的路径 stem

这条规则的价值不在“命名好看”，而在于：

- 同一套正式产物在 `codesign_surface / route_runtime_diff / transfer_kind / controller_explainability`
  四层里能保持同一 canonical identity
- sibling auto-discovery 仍可兼容历史命名
- 但高层论文/对比/路线图文档不再被路径别名污染

### 11.2 两组正式产物的当前角色应该区分开

截至当前 fresh artifact：

- `balanced_20us`
  - `phase2_runtime_summary.json` 存在
  - `codesign_surface` 存在
  - 但 `baseline_overlay_ablation_paths` 为空
  - `thermal_input_source_kind` 仍主要是 `runtime_observability_only`
  - `route_runtime_diff.mechanism_progression_summary` 尚未形成可用主导轴
- `codesign_single_20us_20260322`
  - `phase2_runtime_summary.json` / `codesign_surface` / `route_runtime_diff` 全部齐备
  - `baseline_overlay_ablation_paths` 已正式接入
  - `full_3d_thermal_guard` 与 `full_3d_runtime_adaptive` 已具备 `local_hotspot_sidecar`
  - `route_runtime_diff.mechanism_progression_summary.progression_signature`
    已形成：
    - `step_gate_stall -> unavailable -> thermal_guard_actions`

因此，下一阶段不应再把这两组产物视为同等证据层级。

更合理的定位是：

- `balanced_20us`
  - 用作 canonical identity / 命名兼容 / 最小正式导出链回归样本
- `codesign_single_20us_20260322`
  - 用作 2D/3D 热-路由-内存联合比较的主证据面

### 11.3 下一阶段建议固定的主指标面

如果目标是回答“当前 3D SNN 芯片在 route / memory / thermal / runtime control 上，到底哪一层在主导体系结构差异”，那么最值得固定成主 compare 面的不是所有字段，而是下面四组：

#### A. route/home placement 面

这一组用来回答“3D 映射和 home 选择到底有没有把通信留在更好的位置”：

- `same_home_stack_ratio`
- `vertical_target_ratio`
- `vertical_link_pressure`

其中当前 `codesign_single_20us_20260322` 已经给出一个比较完整的阶梯：

- `full_3d`
  - `same_home_stack_ratio = 0.5`
  - `vertical_link_pressure = 0.1882`
- `full_3d_mapping`
  - `same_home_stack_ratio = 0.90625`
  - `vertical_link_pressure = 0.4320`
- `full_3d_thermal_guard`
  - `same_home_stack_ratio = 0.75`
  - `vertical_link_pressure = 0.3382`

这说明它已经足以承载“映射收益 vs 纵向压力回弹”的正式比较。

#### B. memory model / realism 面

这一组用来回答“memory paradigm 切换后，3D 结构收益到底是来自更少 vertical hop，还是来自 home-access pattern 改变”：

- `vertical_hops_ratio`
- `remote_home_ratio`
- `total_service_deficit`
- `reliability_penalty`

当前 `codesign_single_20us_20260322` 的 `hbm_like_vs_monolithic_like` 已形成可直接使用的主差分：

- `vertical_hops_ratio_delta = -0.4213`
- `remote_home_ratio_delta = -0.5`
- `total_service_deficit_delta = -50598`
- `reliability_penalty_delta = 0.0836`

也就是说，下一阶段 memory 对比已经不需要再停留在“HBM-like vs monolithic-like 谁更像真硬件”的口头讨论，而是可以直接落到“hop/home/deficit/reliability”四维联动。

#### C. thermal/runtime control 面

这一组用来回答“热输入是否真的进入了 runtime control，而不是停留在观察态”：

- `thermal_input_source_kind`
- `hotspot_peak_temperature_c`
- `remap_epoch`
- `homeroute_adjustment_count`
- `thermal_guard_actions`

这里当前也已经出现明显分层：

- `balanced_20us`
  - `full_3d_runtime_adaptive` 虽然有 `remap_epoch = 256`
  - 但 `thermal_input_source_kind = runtime_observability_only`
  - `hotspot_peak_temperature_c = 0.0`
- `codesign_single_20us_20260322`
  - `full_3d_thermal_guard` / `full_3d_runtime_adaptive`
    都已是 `local_hotspot_sidecar`
  - `hotspot_peak_temperature_c = 45.03`
  - `full_3d_runtime_adaptive` 还带出：
    - `remap_epoch = 256`
    - `homeroute_adjustment_count = 1`
    - `thermal_guard_actions = 1`

这意味着真正适合作为 runtime thermal-control 主证据面的，是 `codesign_single_20us_20260322`，不是 `balanced_20us`。

#### D. mechanism progression 面

这一组用来回答“从 fixed-step、到 stop-window、到 runtime compare，主导轴到底如何迁移”：

- `window_route_dominant_axis`
- `runtime_compare_dominant_axis`
- `progression_signature`

当前这组指标只在 `codesign_single_20us_20260322` 上形成了完整语义：

- `window_route_dominant_axis = step_gate_stall`
- `runtime_compare_dominant_axis = thermal_guard_actions`
- `progression_signature = step_gate_stall -> unavailable -> thermal_guard_actions`

这正是下一阶段把 `windowed SNN`、`thermal guard` 和 `runtime adaptive` 串进同一条体系结构叙事链的最好入口。

### 11.4 由此导出的下一阶段优先级

基于当前 artifact 完整度与指标可解释性，下一阶段的更具体优先级应当是：

1. 继续以 `codesign_single_20us_20260322` 为主证据面，固化 route/home placement、memory realism、thermal/runtime control、mechanism progression 四组指标。
2. 把 `balanced_20us` 保留为 canonical naming / exporter compatibility / 最小正式链路回归样本，而不是热-路由-内存联合结论的主证据。
3. 后续新增正式产物时，优先保证 summary 内 canonical identity 完整，再考虑路径命名的可读性；也就是说，identity contract 优先于路径美观。

## 12. 下一阶段任务树（可执行版）

这部分把上面的状态判断直接收敛成可执行任务树。

使用原则：

1. 先做 `P0`，把主证据面和主导出链冻结。
2. `P1` 负责补足当前证据短板，尤其是 stop-window 与 balanced runtime thermal evidence。
3. 只有在 `P0/P1` 稳定之后，才进入 `P2` 的更深体系结构原生化。

Execution status snapshot (2026-03-24):

- `P0-1` 已落地：
  - `phase2_runtime_summary.json` 已正式带出 `canonical_mainline`
  - canonical run/surface label 已冻结到 `codesign_single_20us_20260322`
- `P0-2` 已落地：
  - `phase2_runtime_summary.json` 已正式带出 `canonical_metric_planes`
  - 四组固定指标面已收口到稳定字段白名单
- `P1-1` 已落地：
  - stop-window evidence 已能从 fresh `long_window_stability_summary.json -> outputs.stop_window_ablation_paths` 自动桥接进 formal workflow
  - `codesign_single_20us_20260322` 的 `progression_signature` 已从
    - `step_gate_stall -> unavailable -> thermal_guard_actions`
    - 推进为 `step_gate_stall -> controller_outstanding -> thermal_guard_actions`
- `P1-2` 已落地：
  - `balanced_20us` 的 `phase2_runtime_summary.json` 已正式带出 `thermal_evidence_readiness`
  - 已明确 runtime focus 的 `3` 个 case 仍停留在 `runtime_observability_only`
  - 已把阻塞原因从模糊“热证据空白”收束成：
    - `blocking_reason_counts.missing_replay_artifacts = 3`
    - `refresh_probe_status_counts.missing_run_dir = 3`
  - `canonical_metric_planes.thermal_runtime_control.summary` 现在也会同步带出这组弱热证据摘要
- `P1-3` 已落地：
  - `transfer_kind / controller_explainability` 的 CLI 默认输出目录现在会从真实 `paper_artifacts/.../codesign_surface/*.json` 回推到项目级 `snn3dexp/analysis/...`
  - 不再出现错误的双层 `analysis/analysis/...` 输出路径
  - 在不显式传 `--out-dir` 的真实 formal artifact workflow 下，两份 summary 继续稳定带出：
    - `sources.surface_labels = [balanced_20us, codesign_single_20us_20260322]`
- 下一批仍待执行：
  - `P2-1`
  - `P2-2`

### 12.1 P0：冻结当前主证据面

#### Task P0-1：冻结 `codesign_single_20us_20260322` 的 canonical mainline

Goal:
把当前最完整的一组正式产物固定成“主证据面”，避免后续 compare 口径继续漂移。

Code entry:

- `snn3dexp/tools/export_phase2_paper_artifacts.py`
- `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
- `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- `snn3dexp/tools/canonical_run_identity.py`

Primary inputs:

- `/home/xgy/remote/snn3dexp/analysis/codesign_single_20us_20260322_ablation.json`
- `/home/xgy/remote/snn3dexp/analysis/codesign_single_20us_20260322_ablation_runtime_refresh.json`
- `/home/xgy/remote/snn3dexp/analysis/sweeps/fixed_step_window_route_memory/fixed_step_sweep_summary.json`

Run/verify:

```bash
cd /home/xgy/remote && \
python3 -m snn3dexp.tools.export_phase2_paper_artifacts \
  --ablation-json "/home/xgy/remote/snn3dexp/analysis/codesign_single_20us_20260322_ablation.json"
```

完成判据：

- `phase2_runtime_summary.run_tag = codesign_single_20us_20260322`
- `codesign_surface.sources.baseline_overlay_ablation_paths` 非空
- `route_runtime_diff.mechanism_progression_summary` 存在
- 高层 report 使用的 label 仍是 `codesign_single_20us_20260322`

#### Task P0-2：固定四组主指标面的字段口径与输出入口

Goal:
让后续主图、主表、摘要都只围绕已经证明有解释力的四组指标，不再扩散字段。

Code entry:

- `snn3dexp/tools/export_phase2_paper_artifacts.py`
- `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
- `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- `docs/plans/nextarc/2026-03-23-3d-snn-status-refresh-and-nextarc.md`

固定字段：

- route/home placement：
  - `same_home_stack_ratio`
  - `vertical_target_ratio`
  - `vertical_link_pressure`
- memory realism：
  - `vertical_hops_ratio`
  - `remote_home_ratio`
  - `total_service_deficit`
  - `reliability_penalty`
- thermal/runtime control：
  - `thermal_input_source_kind`
  - `hotspot_peak_temperature_c`
  - `remap_epoch`
  - `homeroute_adjustment_count`
  - `thermal_guard_actions`
- mechanism progression：
  - `window_route_dominant_axis`
  - `runtime_compare_dominant_axis`
  - `progression_signature`

Run/verify:

```bash
cd /home/xgy/remote && python3 - <<'PY'
import json
from pathlib import Path
root = Path('/home/xgy/remote/snn3dexp/analysis/paper_artifacts/codesign_single_20us_20260322')
phase2 = json.loads((root/'phase2_runtime_summary.json').read_text(encoding='utf-8'))
route = json.loads((root/'route_runtime_diff'/'memory_nmc_route_runtime_diff_summary.json').read_text(encoding='utf-8'))
print(phase2['focus_metrics'])
print((phase2['memory_model_comparisons']['hbm_like_vs_monolithic_like']['deltas']))
print(route['mechanism_progression_summary'])
PY
```

完成判据：

- 四组字段都能在正式产物中稳定读到
- 不再依赖 ad-hoc 字段去补叙事空洞

### 12.2 P1：补齐当前证据链的缺口

#### Task P1-1：补齐 stop-window 桥，尽量把 `progression_signature` 中间段从 `unavailable` 变成可解释相位

Goal:
把当前 `fixed-step -> runtime compare` 中间缺失的 stop-window 证据补上，减少机制链断层。

Code entry:

- `snn3dexp/tools/analyze_window_stop_multicase_sweep.py`
- `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- `snn3dexp/tools/export_phase2_paper_artifacts.py`

Primary inputs:

- `/home/xgy/remote/snn3dexp/analysis/sweeps/window_stop_multicase/same_tag_stopwindow_fresh_20260323/window_stop_multicase_sweep_summary.json`

Run/verify:

```bash
cd /home/xgy/remote && \
python3 -m snn3dexp.tools.analyze_window_stop_multicase_sweep \
  --sweep-summary "/home/xgy/remote/snn3dexp/analysis/sweeps/window_stop_multicase/same_tag_stopwindow_fresh_20260323/window_stop_multicase_sweep_summary.json" \
  --out-dir "/tmp/same_tag_stopwindow_refresh"
```

完成判据：

- 生成新的 `window_stop_*_ablation.json`
- `long_window_stability_summary.json` 可直接指向 stop-window compare 证据
- 重新导出 `route_runtime_diff` 后，`window_stop_dominant_axis` 不再长期停留在 `unavailable`

#### Task P1-2：把 `balanced_20us` 从“兼容回归样本”推进到“弱热证据样本”

Goal:
不是把 `balanced_20us` 变成主证据面，而是让它至少具备比当前更强的 thermal/runtime evidence，减少与 `codesign_single` 的断档。

Code entry:

- `snn3dexp/tools/refresh_thermal_outputs.py`
- `snn3dexp/tools/export_phase2_paper_artifacts.py`
- `snn3dexp/tools/run_case.py`

Primary inputs:

- `/home/xgy/remote/snn3dexp/configs/run_tag_manifests/balanced_20us_core.json`
- `/home/xgy/remote/snn3dexp/analysis/ablation_summary_balanced_20us_refresh_20260322_015217.json`

Run/verify:

```bash
cd /home/xgy/remote && \
python3 -m snn3dexp.tools.refresh_thermal_outputs \
  --run-root "/home/xgy/remote/snn3dexp/runs" \
  --run-tag-manifest "/home/xgy/remote/snn3dexp/configs/run_tag_manifests/balanced_20us_core.json" \
  --dry-run \
  --out "/tmp/balanced_20us_refresh_probe.json"

cd /home/xgy/remote && \
python3 -m snn3dexp.tools.export_phase2_paper_artifacts \
  --ablation-json "/home/xgy/remote/snn3dexp/analysis/ablation_summary_balanced_20us_refresh_20260322_015217.json"
```

完成判据：

- 至少明确哪些 case 仍是 `runtime_observability_only`
- 若无法提升为 `local_hotspot_sidecar`，则把阻塞原因固化进 summary/doc，而不是继续模糊表述
- `balanced_20us` 的角色仍保持“回归样本”，但不再是热证据完全空白

#### Task P1-3：把高层 report 的 canonical label 再向真实 artifact workflow 固化

Goal:
确保 `transfer_kind / controller_explainability` 在真实 formal artifacts 上一直跟 `phase2/codesign_surface` 保持同一个 canonical label。

Code entry:

- `snn3dexp/tools/export_transfer_kind_mechanism_report.py`
- `snn3dexp/tools/export_controller_explainability_loss_report.py`
- `snn3dexp/tools/canonical_run_identity.py`

Run/verify:

```bash
cd /home/xgy/remote && \
python3 -m snn3dexp.tools.export_transfer_kind_mechanism_report \
  --surface-summary "/home/xgy/remote/snn3dexp/analysis/paper_artifacts/balanced_20us/codesign_surface/memory_nmc_codesign_surface_summary.json" \
  --surface-summary "/home/xgy/remote/snn3dexp/analysis/paper_artifacts/codesign_single_20us_20260322/codesign_surface/memory_nmc_codesign_surface_summary.json" \
  --out-dir "/tmp/transfer_kind_canonical_surface_validation"

cd /home/xgy/remote && \
python3 -m snn3dexp.tools.export_controller_explainability_loss_report \
  --surface-summary "/home/xgy/remote/snn3dexp/analysis/paper_artifacts/balanced_20us/codesign_surface/memory_nmc_codesign_surface_summary.json" \
  --surface-summary "/home/xgy/remote/snn3dexp/analysis/paper_artifacts/codesign_single_20us_20260322/codesign_surface/memory_nmc_codesign_surface_summary.json" \
  --out-dir "/tmp/controller_explainability_canonical_surface_validation"
```

完成判据：

- 两个 summary 的 `sources.surface_labels` 都稳定等于：
  - `balanced_20us`
  - `codesign_single_20us_20260322`

### 12.3 P2：在主证据面稳定后，再推进更深体系结构原生化

#### Task P2-1：把 route kernel 从 bootstrap source 推向 synapse-native semantics

Goal:
让 3D route 的主语义来源逐步摆脱 `edges_csv / legacy-built routes`，转向更真实的 synapse/BCSR/GAS source semantics。

Code entry:

- `snn3dexp/noc/multicast_3d.py`
- `snn3dexp/tools/run_case.py`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.cc`

Run/verify:

```bash
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4

cd /home/xgy/remote && \
python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics \
  snn3dexp.tests.test_route_memory_joint_analysis -v
```

完成判据：

- route3d 的 activation/home-path 解释链更多来自真实 synapse source，而不是 legacy route table 回填
- 不破坏现有 `phase2`/surface/exporter 语义

#### Task P2-2：把 HotSpot 从 sidecar 约束层扩到更广泛 canonical case 的 execute loop

Goal:
在不破坏当前主 compare 面稳定性的前提下，让更多 canonical case 真正带热输入进入 runtime control。

Code entry:

- `snn3dexp/thermal/hotspot_driver.py`
- `snn3dexp/runtime/policy.py`
- `snn3dexp/tools/run_case.py`
- `snn3dexp/tools/refresh_thermal_outputs.py`
- `snn3dexp/tools/prepare_thermal_calibration_inputs.py`

Run/verify:

```bash
cd /home/xgy/remote && \
python3 -m snn3dexp.tools.refresh_thermal_outputs \
  --run-root "/home/xgy/remote/snn3dexp/runs" \
  --run-tag-manifest "/home/xgy/remote/snn3dexp/configs/run_tag_manifests/codesign_single_20us_20260322.json" \
  --out "/tmp/codesign_single_refresh_probe.json"
```

完成判据：

- 更多 canonical case 从 `runtime_observability_only` 提升为 `local_hotspot_sidecar` 或更强热输入模式
- `phase2` 主 summary 可以稳定回答“热输入是否真的驱动 runtime control”

### 12.4 建议执行顺序

推荐顺序：

1. `P0-1`
2. `P0-2`
3. `P1-1`
4. `P1-2`
5. `P1-3`
6. `P2-1`
7. `P2-2`

理由：

- `P0` 先锁主证据面，避免后面边做边漂
- `P1` 先补证据缺口，再决定哪些结论可以升级成正式主图/主表
- `P2` 再做更重的体系结构原生化，能避免在不稳定 compare 面上过早放大复杂度
