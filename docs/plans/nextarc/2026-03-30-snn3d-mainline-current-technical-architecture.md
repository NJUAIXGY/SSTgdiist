# SNN3D 当前主线技术总纲

Date: 2026-03-30
Last updated: 2026-04-02
Owner: Fufu
Status: Current-mainline technical blueprint, code-aligned

## 1. 文档定位

这份文档是当前 `3D SNN` 主线的唯一总纲，只描述仓库里已经落成并正在使用的最新状态，不回顾历史版本，不讨论过时分支。

如果后续文档与它冲突，以当前代码为准，优先级如下：

1. `snn3dexp/` 与 `sst_workspace/sst-elements/src/sst/elements/SnnDL/` 当前实现
2. 当前主入口脚本与当前 artifact schema
3. 本文档

## 2. 一句话定义主线

当前正式主线可以定义为：

`3D-native Route + HBM-like NMC + Windowed-SNN Co-Design Mainline`

它的含义不是“证明 3D 能跑”，而是：

- 在 `SnnDL` 内部把 multicast route 的接口语义提升到 3D 原生层
- 在 `snn3dexp` 中把 `HBM-like shared-stack` 与 `monolithic-like` memory 范式纳入同一 object graph / summary / compare 体系
- 用真实 `windowed SNN` 工作负载，而不只是 traffic toy case，驱动 route / memory / thermal / barrier 的联合分析
- 用统一的 `architecture -> diff -> mechanism progression -> joint pressure -> runtime control` 分析面解释机制迁移

## 3. 当前主线的研究对象

当前平台建模的对象，不是单点 router，也不是单点 memory stack，而是一个完整的 3D SNN chip architecture loop：

1. 神经元映射与 block/multicast 组织
2. 3D NoC 上的 native multicast 传输
3. shared-stack / near-memory hierarchy 下的 home-stack 流量分布
4. windowed SNN 运行时的 barrier / step-gate / thermal 约束
5. runtime adaptive policy 对 route / vertical penalty / home-route 的响应

主线问题也因此被收敛成一句话：

`在真实 windowed SNN 负载下，3D-native multicast route 与 HBM-like NMC 是否能够形成可解释、可比较、可控制的联合体系结构模型。`

## 4. 平台底座

### 4.1 `snn3dexp` 是隔离的 3D 平台层

当前主线不再直接在旧脚本上堆逻辑，而是通过隔离目录 `snn3dexp/` 组织：

- `cases/`: case catalog，承载 `baseline_2d`、`full_3d`、`full_3d_mapping`、`full_3d_thermal_guard`、`full_3d_runtime_adaptive`、`full_3d_snn_window`、`full_3d_snn_window_runtime_adaptive`、`full_3d_snn_window_bundle_v3`、`full_3d_snn_window_monolithic_proxy` 等主线 case
- `mesh3d_template/`: 3D mesh spec/default/resolve
- `platform/`: effective config、platform summary、SST object graph 组装
- `noc/`: 3D multicast router/link 描述
- `memory/`: `legacy_per_pe`、`hbm_like`、`monolithic_like`
- `runtime/`: adaptive policy
- `thermal/`: thermal proxy、HotSpot sidecar、runtime thermal observability
- `tools/`: run/analyze/export 主链
- `tests/`: contract 与 regression

这层隔离的意义不是目录整洁，而是保证：

- `SnnDL` 的 3D 扩展与 Python 侧实验编排解耦
- case / effective config / artifact schema 有稳定边界
- 后续 memory/NMC co-design 不需要继续污染旧 2D 实验链

### 4.2 当前 object graph 是从 effective config 单向生成的

当前平台的 authority 不是临时 Python 拼装对象，而是：

1. case spec
2. resolved effective config
3. platform summary
4. SST graph manifest
5. phase2 case summary

`snn3dexp/tools/run_case.py` 是单 case 主入口，它会把：

- `effective_config.json`
- `platform_summary.json`
- `sst_graph_manifest.json`
- `phase2_case_summary.json`

固定写到对应的 `runs/<case_id>/<run_tag>/` 与 `analysis/<case_id>/<run_tag>/` 路径下。

这意味着当前主线已经不是“脚本临时跑一把”，而是具备了固定 object graph、固定 summary schema、固定 artifact root 的平台结构。

## 5. C++ 主干：3D-native multicast route 接口链

当前 `SnnDL` 内部最关键的主线是：

`ISynapseRoute -> SpikeCommSubsystem -> SynapseRouteSubsystem3D -> MulticastRouter3DNative`

### 5.1 `ISynapseRoute` 已经是接口级 3D

当前 `ISynapseRoute` 的 3D contract 不是外部约定，而是接口本身已经显式表达：

- `BlockTarget` 带有 `ingress_node`
- `BlockTarget` 带有 `block_z`
- `BlockTarget` 带有 `block_d`
- `BlockTarget` 带有 `core_mask`
- 接口提供 `multicastBlockD()`
- 接口提供 `computeMulticastTargets(...)`

这意味着 route 子系统输出的已经不再只是 2D block 或 node list，而是带纵向体块深度、入口节点和块内 core mask 的 3D block target。

### 5.2 `SpikeCommSubsystem` 现在消费 3D target，而不是硬编码 2D 路径

`SpikeCommSubsystem.cc` 当前做的事是 transport façade：

- 从 `synapse_route_` 读取 `multicastBlockW/H/D()`
- 调用 `computeMulticastTargets(...)`
- 把 `BlockTarget` 转成：
  - `SpikeKey V2`
  - `SpikeKey V4`
  - `BundleEntryV1`
  - `BundleEntryV2`
  - `BundleEntryV3`
- 在 volumetric block 下正确携带：
  - `block_z`
  - `block_d`
  - `ingress_node`
  - `core_mask`

因此当前 `SpikeCommSubsystem` 已不再把 2D `SynapseRouteSubsystem/native multicast` 写死成唯一语义，它已经能够把 3D route contract 下沉到真正发包的 transport 层。

### 5.3 `SynapseRouteSubsystem3D` 的新增价值

`SynapseRouteSubsystem3D` 当前的正式职责是：

1. 维持 3D multicast geometry 合法性
2. 决定 `multicastBlockD()`
3. 基于 3D mesh 坐标合成 volumetric `block_id`
4. 生成 `block_z / block_d / ingress_node / core_mask`
5. 输出 3D-native runtime stats

当前实现的关键事实是：

- `computeMulticastTargets()` 已区分 native 3D synthesis 与 compat fallback
- native 路径会按 `block_w / block_h / block_d` 计算 3D volumetric block
- ingress node 的选择已经是 3D-aware
- `core_mask` 是按块内 cell 位置与目标 core 聚合出来的
- `describeRouteSemantics()` 已把 `source_semantics_authority / source_primary_kind / native_bootstrap_source / native_source_fanout_active` 一并显式导出

但它当前仍有一个明确边界：

- source-side fanout authority 现在已经是正式 authority，而不再只是“实现上可跑、分析上说不清”的局部 helper
- 在 `native_3d + edges_csv + real_synapse_inputs_available=true` 的主线 case 下，当前 descriptor 已显式区分：
  - `source_semantics_authority = native_3d_route_table`
  - `source_primary_kind = native_3d_route_table_with_real_synapse_inputs`
  - `native_bootstrap_source = edges_csv`
- `computeFanout()` 的 native 路径仍然建立在已构建 route table 的 source kernel 之上；也就是说，当前边界已经不再是 source authority 表述不清，而是 route-table 生成范式本身仍然不是一个全新独立的 synapse compiler / online remap execution kernel

这正是当前 route 主线已经到达的真实层级。

### 5.4 `MulticastRouter3DNative` 是当前 3D NoC 核心

当前 3D router 内核已经正式承接：

- vertical route order：支持 `zxy` / `zyx`
- `up/down` 方向分发
- 3D volumetric block forwarding
- bundle `V1 / V2 / V3` 解码与重建
- `bundle_v3` 的 3D block-shape / `block_z` / ingress 合法性检查

也就是说，当前 3D router 的职责不只是把 `z` 当额外标签，而是真正理解：

- 纵向 block depth
- 3D block 内入口位置
- 纵向转发与块内重建

这使得 route 主线已经具备“接口 3D + 传输 3D + router 3D”的完整闭环。

## 6. Memory/NMC 主线

### 6.1 当前 memory 范式有三种

当前平台统一支持三种 memory family：

1. `legacy_per_pe`
2. `hbm_like`
3. `monolithic_like`

它们不是并列的“玩具选项”，而是当前 co-design 的三个对照基线。

### 6.2 `hbm_like` 是当前 memory/NMC 主线

当前 memory/NMC 的正式主线是 `hbm_like shared-stack`：

- memory graph 是 shared-stack / shared-controller 组织
- `synapse_sources` 与 processing core `core0.params` 已显式携带：
  - `controller_endpoint`
  - `path_authority`
  - `semantic_region_layout_version`
- 平台 summary 会导出 controller / stack 级压力语义
- `phase2_case_summary["architecture"]["memory_pressure"]` 会聚合：
  - `active_stack_count`
  - `most_pressured_controller_service_deficit_proxy`
  - `most_pressured_controller_backpressure_proxy`
  - `most_pressured_controller_memory_pressure_proxy`
  - `home_stack_path_authority`
  - `home_stack_controller_pressure_authority`
  - `home_stack_runtime_authority_available`
  - `pe_nic_real_home_path_authority`
  - `synapse_real_home_path_authority`
  - `most_pressured_runtime_controller_id`
  - `most_pressured_runtime_stack_id`

这使得当前 memory 主线关注的已经不是“有无 DRAM”，而是：

- home-stack 分布是否偏斜
- controller 是否形成压力热点
- 当前 home-path/controller 结论到底来自真实 binding、真实 runtime controller，还是 proxy projection
- route 行为是否把 memory pressure 放大到 runtime/thermal 问题

### 6.3 `monolithic_like` 的当前定位

`monolithic_like` 当前是正式对照范式，但它的定位必须说清楚：

- 它是 near-memory / monolithic-style 的 proxy compare
- 它与 `hbm_like` 共享同一平台语义与地址语义
- 它可以进入同一 `codesign surface` 与 `matrix`

但它还不是：

- 真实 monolithic 3D DRAM 工艺级时序模型
- 真正带近存算子执行的数据通路

所以当前正确表述应当是：

`monolithic_like` 用于 memory paradigm 对照，不用于宣称已经完成 monolithic 近存计算实现。

### 6.4 后端现状

当前 memory graph 后端支持：

- `memHierarchy.simpleMem`
- `memHierarchy.ramulator2`

两种后端都已经在图构建层有正式入口，但当前主线默认接受的最轻量验证路径仍然应理解为：

- shared-stack object graph 正确
- controller/backend 真实挂图
- memory pressure / home-stack semantics 能进入统一 summary

而不是把 `ramulator2` 视为当前文档主线的唯一验收前提。

## 7. 工作负载主线

### 7.1 当前有两条 workload 主路径

当前主线不只看一个 workload，而是双路径：

1. `traffic_mem` 路径
2. `windowed SNN` 路径

两者的分工很明确：

- `traffic_mem`: 稳定扫描 route/memory 结构差异，适合作为 baseline 交通面
- `windowed SNN`: 表达真实 step/window/barrier/runtime 语义，是当前论文级架构模型真正有价值的主负载

### 7.2 `windowed SNN` 是当前研究主负载

当前 `windowed SNN` 主线对应的 case 家族包括：

- `full_3d_snn_window`
- `full_3d_snn_window_runtime_adaptive`
- `full_3d_snn_window_bundle_v3`
- `full_3d_snn_window_monolithic_proxy`

此外还有：

- `full_3d_runtime_adaptive`
- `full_3d_thermal_guard`
- `full_3d_mapping`

用于把 route、memory、thermal、runtime policy、mapping 影响放到一个统一实验面内比较。

而：

- `full_3d_snn_window_gating_event_probe`
- `full_3d_snn_window_gating_event_synth`

更适合作为 observability / mechanism 辅助 case，不是主结果表的第一证据面。

## 8. 当前统一实验主链

### 8.1 单 case authority

单 case 主入口是：

`snn3dexp/tools/run_case.py`

它负责：

1. resolve case
2. materialize effective config
3. build platform summary / SST graph
4. 可选执行 SST smoke
5. 统一写出 `phase2_case_summary.json`

当执行真实 smoke 时，它还会继续固定写出：

- `stack_nmc_summary.json`
- `route_memory_joint_summary.json`

当前单 case summary 的核心结构已经固定到：

- `observability`
- `route_pressure`
- `memory_pressure`
- `thermal_pressure`
- `barrier_pressure`
- `coupling`
- `hotspot_readiness`

并显式声明：

`analysis_axes = ["route", "memory", "thermal", "barrier"]`

### 8.2 多 case / co-design 主入口

当前 canonical main entry 是：

`snn3dexp/tools/run_memory_nmc_codesign_matrix.py`

它不是普通导出脚本，而是当前主线真正的多 case 汇总入口，负责把：

- traffic baseline
- fixed-step windowed SNN
- auto-orchestrated `window_stop_execution -> window_stop_analysis`
- baseline overlay ablation
- stop-window ablation
- hotspot/runtime summary

汇总进统一 matrix。

当前 `matrix_rows` 已稳定收敛到六类 canonical group：

- `traffic_route`
- `traffic_memory`
- `window_route`
- `window_memory`
- `window_stop`
- `runtime_control`

而且 matrix summary 现在不只给 compare row，还会显式落出：

- `window_stop_execution`
- `window_stop_analysis`

也就是说，high-load `stop-window` 已经不再是 side artifact，而是 canonical main entry 自己负责编排、汇总并投影的主线证据面。

### 8.3 当前完整分析链

当前主线实验链应该理解为：

1. `run_case.py`
2. `analyze_ablation.py`
3. `run_fixed_step_multicase_sweep.py`
4. `analyze_fixed_step_sweep.py`
5. `run_window_stop_multicase_sweep.py`
6. `analyze_window_stop_multicase_sweep.py`
7. `export_memory_nmc_codesign_surface.py`
8. `run_memory_nmc_codesign_matrix.py`
9. `export_memory_nmc_route_runtime_diff.py`
10. `export_phase2_paper_artifacts.py`

这条链的价值在于：

- case 不再只是分散运行
- 比较不再只是单项 metric diff
- route / memory / thermal / runtime 的联合机制可以持续投影到统一 artifact 面

## 9. 统一解释主线

### 9.1 `architecture` 是当前单 case 统一主语义

当前 `phase2_case_summary["architecture"]` 已是正式主语义层，它把 route / memory / thermal / barrier 压成一份单 case 摘要。

其中最关键的是 `coupling`：

- `route_thermal_coupling_score`
- `memory_thermal_coupling_proxy`
- `route_barrier_coupling_proxy`
- `memory_barrier_coupling_proxy`

这组字段的意义是：

- 不再单看 vertical hops
- 不再单看 controller pressure
- 不再单看 barrier stall
- 而是明确表示哪一种 route-memory-thermal-barrier 联动正在主导当前 case

### 9.2 route/runtime diff 已经不是简单 compare

`export_memory_nmc_route_runtime_diff.py` 当前会正式产出：

- `window_route_mechanism_summary`
- `window_stop_mechanism_summary`
- `runtime_compare_summary`
- `mechanism_progression_summary`
- `route_memory_joint_pressure_summary`
- `runtime_control_closure_summary`

并输出独立 CSV：

- `memory_nmc_route_runtime_mechanism_progression.csv`
- `memory_nmc_route_runtime_joint_pressure.csv`
- `memory_nmc_route_runtime_control_closure.csv`

这意味着当前解释主线已经从“看几行 diff”升级为：

1. 先看 route 机制主轴
2. 再看 stop-window 下机制是否迁移
3. 再看 runtime policy 是否跟随 joint pressure 做出可解释动作

并且这组 `runtime_control_closure` 结果已经不是 exporter 局部字段，而是会继续进入：

- `phase2_artifacts/phase2_runtime_summary.json`
- `canonical_mainline.runtime_control_closure_summary_present`
- `canonical_mainline.runtime_control_closure_row_count`

### 9.3 runtime policy 已消费 architecture coupling 与 memory/NMC mechanism

当前 `snn3dexp/runtime/policy.py` 不再只看热信号，还会同时读取：

- `architecture.coupling`
- `route_memory_joint_summary.memory.home_stack_dataflow`
- `route_memory_joint_summary.memory.home_stack_controller_proxy`

并把 raw summary 中的：

- `dominant_initiator_kind`
- `controller_pressure_authority_kind`
- `runtime_authority_available`
- `runtime_hotspot_alignment.controller_alignment_kind`
- `initiator_groups[*].{demand_total,service_deficit_total}`

归一化成 runtime policy 直接消费的 memory/NMC mechanism 信号。

当前已正式支持的 coupling threshold 包括：

- `runtime_memory_thermal_coupling_threshold`
- `runtime_memory_barrier_coupling_threshold`
- `runtime_memory_nmc_mechanism_threshold`

当前已正式支持的动作包括：

- `raise_vertical_penalty`
- `rebalance_home_route`
- `observe_memory_nmc_mechanism`
- `rebalance_memory_nmc_mechanism`

这说明当前平台不是“离线分析平台”而已，而是已经具备：

- 从 architecture summary 提取 joint pressure
- 从 raw route-memory joint summary 提取 home-stack initiator / pressure-transfer 机理
- 让 runtime controller 做 observe-only 或 execute 决策
- 再把决策回投到 summary/artifact

的闭环能力。

## 10. 当前正式能力

截至当前代码状态，可以明确把平台的正式能力定义为：

1. `SnnDL` 的 route 接口已经是 3D-native，而不是 2D-only
2. `SpikeCommSubsystem` 已能把 3D block target 下沉为真实发包语义
3. `MulticastRouter3DNative` 已具备 3D volumetric forwarding 与 bundle v3 处理
4. `snn3dexp` 已是隔离的平台层，而不是一组散落实验脚本
5. `hbm_like / monolithic_like / legacy_per_pe` 已进入同一 graph/summary/compare 体系
6. `windowed SNN` 已进入 canonical matrix，而不是仅作为单独 case 存在
7. `stop-window` 与 `runtime control closure` 已进入 canonical matrix / phase2 mainline，而不是只作为 side artifact 存在
8. `architecture -> route_runtime_diff -> phase2_artifacts` 已形成统一 artifact 面
9. runtime policy 已经能够同时消费 route-memory-thermal-barrier coupling 与 memory/NMC mechanism
10. `run_case -> route_memory_joint -> phase2_case_summary` 已能把 native-source authority 直接投影到真实 artifact，而不再把 `edges_csv bootstrap` 当作唯一 source 主语义

## 11. 当前明确边界

当前主线已经很强，但边界同样需要明确冻结：

1. `SynapseRouteSubsystem3D` 已经把 source-side fanout semantics 提升成正式 3D authority，但其 native source kernel 仍建立在已构建 route table 之上；当前剩余边界是 route-table/compiler 范式，而不是 source authority 本身。
2. `hbm_like` 当前是 `HBM-like shared-stack NMC hierarchy`，不是带真实 near-memory compute operator 的 PIM 执行数据通路。
3. `monolithic_like` 当前是 proxy compare，不应被表述成真实 monolithic 3D DRAM timing signoff 模型。
4. runtime adaptive 当前是 window 级控制，不是 cycle 级 closed-loop control。
5. thermal/HotSpot 已经进入分析与控制输入，但并不是所有 case 默认都跑 full thermal execute loop。
6. 当前主线 topology 实际围绕 `4x4x2` 组织，扩展到更大 3D mesh 时仍要继续验证 route/memory/runtime 的尺度效应。

## 12. 当前唯一主入口与权威产物

如果只保留最少的 authority，可以收敛成下面三层：

### 12.1 单 case authority

- 主入口：`snn3dexp/tools/run_case.py`
- 权威产物：`analysis/<case_id>/<run_tag>/phase2_case_summary.json`

### 12.2 多 case / mainline authority

- 主入口：`snn3dexp/tools/run_memory_nmc_codesign_matrix.py`
- 权威产物：`snn3dexp/analysis/codesign_matrix/<matrix_label>/memory_nmc_codesign_matrix_summary.json`
- 关键内嵌对象：
  - `window_stop_execution`
  - `window_stop_analysis`
  - `matrix_rows[*].matrix_group in {traffic_route, traffic_memory, window_route, window_memory, window_stop, runtime_control}`

### 12.3 解释与论文化 authority

- 主入口：`snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- 主入口：`snn3dexp/tools/export_phase2_paper_artifacts.py`
- 权威产物：
  - `route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`
  - `phase2_artifacts/phase2_runtime_summary.json`
  - 其中 `phase2_runtime_summary.json` 的 `canonical_mainline` 会继续显式声明：
    - `window_stop_compare_row_count`
    - `runtime_control_closure_summary_present`
    - `runtime_control_closure_row_count`

## 13. 最小验收入口

这里只保留最简单、最贴近当前主线的入口，不展开冗长脚本说明。

### 13.1 单 case 配置与 schema 验收

```bash
cd "/home/xgy/remote"
python3 "snn3dexp/tools/run_case.py" full_3d_snn_window --validate-only
```

用途：

- 验证 case spec、3D mesh、memory model、runtime params 的解析链没有断

### 13.2 主线 matrix compose-only 验收

```bash
cd "/home/xgy/remote"
python3 "snn3dexp/tools/run_memory_nmc_codesign_matrix.py" \
  --matrix-label "mainline_blueprint_smoke" \
  --compose-only \
  --phase2-mainline
```

最关键输出：

- `snn3dexp/analysis/codesign_matrix/mainline_blueprint_smoke/memory_nmc_codesign_matrix_summary.json`
- `snn3dexp/analysis/codesign_matrix/mainline_blueprint_smoke/route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`
- `snn3dexp/analysis/codesign_matrix/mainline_blueprint_smoke/phase2_artifacts/phase2_runtime_summary.json`
- `snn3dexp/analysis/codesign_matrix/mainline_blueprint_smoke/window_stop_analysis/long_window_stability_summary.json`

### 13.3 主线 limited real-runtime smoke 验收

```bash
cd "/home/xgy/remote"
python3 "snn3dexp/tools/run_memory_nmc_codesign_matrix.py" \
  --matrix-label "mainline_runtime_smoke" \
  --phase2-mainline \
  --limited-runtime-smoke-profile canonical_runtime_smoke
```

用途：

- 刷新 traffic baseline、window family、window-stop、route/runtime diff、phase2 artifacts 的真实主线产物
- 验证 `full_3d_snn_window_runtime_adaptive` 在 canonical window family 中已进入真实 runtime 行，而不只是 compose-only

关键观察点：

- `codesign_surface.window_baseline_rows[*].case_id == full_3d_snn_window_runtime_adaptive`
- 同一 row 已显式带出：
  - `runtime_enabled`
  - `control_decision`
  - `memory_nmc_mechanism_signal_available`
  - `memory_nmc_mechanism_pressure_proxy`

## 14. 下一阶段应该继续往哪里做

基于当前主线，下一阶段最合理的方向不是回头讨论“3D 有没有”，而是继续把主线向下压实：

1. 把新的 `native_3d_route_table_with_real_synapse_inputs` authority 继续刷新进 canonical matrix / fixed-step sweep / paper artifacts，替换旧的 `bootstrap_bound` 主叙事
2. 在已经具备 `home-stack path authority` 的基础上，把 stack-scope binding 继续压到更细的 controller/region real-path datapath
3. 强化 `windowed SNN` 作为第一 workload 的主证据地位，而不是让 traffic baseline 继续主导叙述
4. 继续扩大 `mechanism progression -> joint pressure -> runtime control closure` 的解释力度，并把 route source authority 与 memory/NMC authority 一起合并成同一结论面

这四点，才是当前代码状态下真正与主线连续、且最有体系结构价值的下一步。

## 15. 2026-04-01 Artifact Freshness Refresh

本轮没有再扩新功能面，而是把 `route_memory_joint -> codesign surface -> codesign matrix -> route/runtime diff` 的 freshness authority 收紧，解决“代码已经支持新语义，但真实 artifact 仍读到旧 provenance”这个主线风险。

### 15.1 修复点

1. `snn3dexp/tools/route_memory_joint_loader.py`
   - freshness gate 不再只检查 memory/home-stack 字段
   - 现在还要求 `route.source_semantics` 带有：
     - `primary_source_kind`
     - `route_memory_overlap_mode`
     - `native_synapse_overlap_ratio`
   - 当上游只提供 `route_memory_joint_summary_path`、没有显式 `run_root` 时，loader 会从
     - `analysis/<case_id>/<run_tag>/route_memory_joint_summary.json`
     - 自动反推到 `runs/<case_id>/<run_tag>/`
     - 然后用当前 `build_route_memory_joint_summary()` 现场重建

2. `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - `_project_runtime_surface_metrics()` 不再让旧 `runtime_summary` 里的空 route overlap 字段覆盖 refreshed provenance
   - 只有当 runtime summary 自己带了有效 `route_memory_overlap_mode` 时，才允许它接管
   - 否则保留 refreshed joint summary 的：
     - `route_memory_overlap_mode`
     - `route_native_synapse_overlap_ratio`
     - `route_overlap_actionable`

### 15.2 最新 fresh artifact 结论

1. `windowed native dense family`
   - fresh 路径：
     - `snn3dexp/analysis/windowed_native_dense_family/native_dense_family_gating_semantic_final_20260401/codesign_surface/memory_nmc_codesign_surface_summary.json`
   - 关键观察：
     - `full_3d_snn_window`
       - `route_memory_overlap_mode = native_synapse_aligned`
       - `route_native_synapse_overlap_ratio = 1.0`
       - `route_overlap_actionable = true`
     - `full_3d_snn_window_bundle_v3`
       - `route_memory_overlap_mode = native_synapse_aligned`
       - `route_native_synapse_overlap_ratio = 0.0`
       - `route_overlap_actionable = false`
     - `full_3d_snn_window_monolithic_proxy`
       - `route_memory_overlap_mode = native_synapse_aligned`
       - `route_native_synapse_overlap_ratio = 1.0`
       - `route_overlap_actionable = true`
   - 含义：
     - `direct vs bundle` 的 route/native overlap 差异，已经能在真实 artifact 上被直接读出
     - 这说明 windowed-SNN high-load 主线已经不仅是 “3D 功能存在”，而是进入了可解释的 route-memory 语义闭环

2. `canonical matrix`
   - 当前盘上的最近一次 canonical matrix artifact 路径（尚未重新套用本轮 native-source authority refresh）：
     - `snn3dexp/analysis/codesign_matrix/archsum_matrix_semantic_final_20260401/memory_nmc_codesign_matrix_summary.json`
     - `snn3dexp/analysis/codesign_matrix/archsum_matrix_semantic_final_20260401/codesign_surface/memory_nmc_codesign_surface_summary.json`
     - `snn3dexp/analysis/codesign_matrix/archsum_matrix_semantic_final_20260401/route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`
   - 关键观察：
     - `baseline_2d / noc_only_3d` 仍然主要是 `legacy_only`
     - `memory_only_3d / full_3d / full_3d_tile_bundle_v3 / full_3d_runtime_adaptive` 当前仍主要是 `bootstrap_bound`
     - `runtime_adaptive_vs_full_3d` 的 route overlap 迁移目前仍是：
       - `bootstrap_bound -> bootstrap_bound`
   - 含义：
     - canonical matrix 的 memory/NMC 主结论现在仍建立在 `edges_csv bootstrap` 主导的 source semantics 上
     - 因此，windowed family 已经能讨论 `native overlap`，而 canonical matrix 还不能把 `runtime adaptive` 解释成真正的 `native_synapse_aligned` 迁移

### 15.3 当前主线应如何表述

截至当前代码状态，主线最准确的技术表述应是：

1. `3D-native route + HBM-like NMC + windowed-SNN` 的 Python artifact freshness 闭环已经站稳
2. `windowed family` 已经能真实区分 `native_synapse_aligned` 与 “same mode but zero overlap ratio”的 direct/bundle 行为
3. `canonical matrix` 仍主要是 bootstrap-bound authority，因此它更适合承载 memory/NMC 基线对照，而不是承载最终的 synapse-native source 结论
4. 下一阶段最该投入的不是再做 export 层修补，而是把新的 native-source authority 刷新进 canonical matrix，并与 memory/NMC home-path authority 继续合流

### 15.4 2026-04-01 Native-Source Authority Closure

本轮最新代码状态已经把上面第 4 点的一部分正式做完：

1. `SynapseRouteSubsystem3D::describeRouteSemantics()` 不再把 `native_3d + edges_csv + real synapse inputs` 统一压成 `edges_csv_bootstrap`
2. 当前主线已经显式解耦：
   - source authority
   - bootstrap provenance
3. 真实 limited smoke：
   - `python3 -m snn3dexp.tools.run_case full_3d_runtime_adaptive --run-tag authority_native_source_20260401 --sst-smoke --stop-at 250ns`
   - 已通过
4. 当前最新 artifact 关键值：
   - `route.source_semantics.source_semantics_authority = native_3d_route_table`
   - `route.source_semantics.primary_source_kind = native_3d_route_table_with_real_synapse_inputs`
   - `route.source_semantics.native_synapse_source_candidate = true`
   - `route.source_semantics.route_memory_overlap_mode = native_synapse_aligned`
   - `route.source_semantics.native_synapse_overlap_ratio = 0.75`
   - `phase2.route_kernel.runtime_activation_total = 256`
5. 因此，当前主线最准确的技术结论应更新为：
   - `windowed family` 与 `full_3d_runtime_adaptive` 已经能以真实 artifact 证明 native-source authority
   - 旧 canonical matrix 上仍显示 `bootstrap_bound` 的部分行，应视为“尚未用新 authority 重新 fresh”的 artifact，而不是当前代码语义本身
   - 下一阶段真正的重点已经从“修 route source authority”转成“把新的 native-source authority 刷新到 canonical matrix，并与 memory/NMC home-path authority 合流”

### 15.5 2026-04-02 Canonical Matrix Refresh Closure

本轮已经把上面最后一条主线真正落到 fresh canonical matrix 上，而不是继续停留在单 case 证明。

#### 15.5.1 本轮最小代码修补

1. `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - `traffic_mem_compare_rows`
   - `runtime_control compare rows`
   - 现在都会显式携带：
     - `base_route_source_primary_kind`
     - `compare_route_source_primary_kind`
     - `route_source_primary_kind_transition`

2. 含义
   - canonical matrix 以前即使吃到 fresh run，也会在 compare/diff 层丢掉 `source primary kind`
   - 导致：
     - `route_runtime_diff`
     - `source_authority_summary`
     - 仍无法把 `runtime_adaptive_vs_full_3d` 解释成真正的 source-tier 迁移
   - 现在这条 compare/export 链已经补全

#### 15.5.2 本轮真实 fresh matrix

1. 命令
   - `python3 -m snn3dexp.tools.run_case full_3d --run-tag authority_native_source_20260401 --sst-smoke --stop-at 20us`
   - `python3 -m snn3dexp.tools.run_case full_3d_tile_bundle_v3 --run-tag authority_native_source_20260401 --sst-smoke --stop-at 20us`
   - `python3 -m snn3dexp.tools.run_case full_3d_runtime_adaptive --run-tag authority_native_source_20260401 --sst-smoke --stop-at 2us`
   - `python3 -m snn3dexp.tools.run_memory_nmc_codesign_matrix --matrix-label authority_native_matrix_refresh_20260402 --baseline-run-tag authority_native_source_20260401 --fixed-step-run-tag task_fixed_step_4_10us --phase2-mainline`

2. 主产物
   - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/memory_nmc_codesign_matrix_summary.json`
   - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/codesign_surface/memory_nmc_codesign_surface_summary.json`
   - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`
   - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/phase2_artifacts/phase2_runtime_summary.json`

#### 15.5.3 这次 fresh matrix 的关键结论

1. `runtime_adaptive_vs_full_3d`
   - 现在已经不再是旧的 `bootstrap_bound -> bootstrap_bound`
   - 当前 fresh row 已经明确变成：
     - `base_route_source_primary_kind = edges_csv_bootstrap`
     - `compare_route_source_primary_kind = native_3d_route_table_with_real_synapse_inputs`
     - `route_source_primary_kind_transition = edges_csv_bootstrap -> native_3d_route_table_with_real_synapse_inputs`
     - `route_memory_overlap_mode_transition = bootstrap_bound -> native_synapse_aligned`
     - `source_authority_tier_transition = bootstrap_manifest -> native_multicast_synapse_home`

2. `traffic_mem_bundle_vs_direct`
   - 仍然是：
     - `edges_csv_bootstrap -> edges_csv_bootstrap`
     - `bootstrap_bound -> bootstrap_bound`
     - `bootstrap_manifest -> bootstrap_manifest`
   - 这说明 `traffic bundle/direct` 这一组当前仍主要承载 memory/NMC/bundle 压力差异，而不是 native-source authority 迁移

3. `window_stop`
   - 这轮 fresh rows 已不再是旧 artifact 上的 `legacy_route_tables_bootstrap / bootstrap_bound`
   - 当前 `window_stop_*` 六行已经稳定表现为：
     - `base_route_source_primary_kind = legacy_route_tables_with_real_synapse_inputs`
     - `compare_route_source_primary_kind = legacy_route_tables_with_real_synapse_inputs`
     - `route_memory_overlap_mode_transition = native_synapse_aligned -> native_synapse_aligned`
     - `source_authority_tier_transition = native_multicast_synapse_home -> native_multicast_synapse_home`
   - 含义：
     - `window-stop` 主线已经可以作为高负载下 route-memory/native overlap 的真实闭环辅证

4. `source_authority_summary`
   - 现在已经正式出现在 canonical matrix summary 中
   - 当前 fresh 统计：
     - `row_count = 11`
     - `source_authority_tier_transition_counts`
       - `bootstrap_manifest -> native_multicast_synapse_home = 1`
       - `native_multicast_synapse_home -> native_multicast_synapse_home = 7`
       - `bootstrap_manifest -> bootstrap_manifest = 2`
       - `legacy_only -> legacy_only = 1`

#### 15.5.4 当前主线应如何更新

截至 `authority_native_matrix_refresh_20260402`，当前最准确的技术表述应更新为：

1. `full_3d_runtime_adaptive` 已经不仅能在单 case 上证明 native-source authority，而且已经进入 canonical matrix 的 runtime-control 主比较行
2. `window-stop` 已经从旧的 bootstrap-bound artifact 刷新成 `native_synapse_aligned` 的真实 high-load 辅证链
3. `traffic bundle/direct` 仍是 memory/NMC 压力与 bundle 机制对照，不应误读成 native-source authority 主展示面
4. canonical mainline 现在已经可以同时承载：
   - `HBM-like NMC` / `bundle` / `monolithic proxy` 的 memory 对照
   - `runtime adaptive` 的 native-source authority 迁移
5. 下一阶段更值得投入的，不再是刷新 canonical matrix 本身，而是继续把 `home-path/controller-path authority provenance`
   - 从 `route_memory_joint_summary`
   - 更完整地下沉到 `ablation / codesign surface / canonical rows`

### 15.5 2026-04-02 Canonical Matrix Refresh Closure

本轮已经把上面的最后一个阻塞点推进到 fresh canonical artifact：

1. `codesign surface / route-runtime diff` 现在会把 compare rows 的 route source semantics 显式带出
   - 代码点：
     - `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - 新增/补齐的关键 compare 字段：
     - `base_route_source_primary_kind`
     - `compare_route_source_primary_kind`
     - `route_source_primary_kind_transition`
   - 影响：
     - `traffic_mem_compare_rows`
     - `derived runtime comparisons`
     - `matrix_rows -> source_authority_summary`
     - `route_runtime_diff`

2. 已完成 fresh real-SST canonical refresh
   - 主命令：
     - `python3 -m snn3dexp.tools.run_memory_nmc_codesign_matrix --matrix-label authority_native_matrix_refresh_20260402 --baseline-run-tag authority_native_source_20260401 --fixed-step-run-tag task_fixed_step_4_10us --phase2-mainline`
   - 新主线产物：
     - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/memory_nmc_codesign_matrix_summary.json`
     - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/codesign_surface/memory_nmc_codesign_surface_summary.json`
     - `snn3dexp/analysis/codesign_matrix/authority_native_matrix_refresh_20260402/route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`

3. 最新 canonical matrix 已经能显式区分 `full_3d` 与 `runtime_adaptive` 的 source authority
   - `runtime_adaptive_vs_full_3d`
     - `base_route_source_primary_kind = edges_csv_bootstrap`
     - `compare_route_source_primary_kind = native_3d_route_table_with_real_synapse_inputs`
     - `route_source_primary_kind_transition = edges_csv_bootstrap -> native_3d_route_table_with_real_synapse_inputs`
     - `route_memory_overlap_mode_transition = bootstrap_bound -> native_synapse_aligned`
     - `source_authority_tier_transition = bootstrap_manifest -> native_multicast_synapse_home`
   - 这说明 canonical matrix 终于不再把 `runtime adaptive` 简化成旧的 bootstrap-bound 行

4. 最新 canonical matrix 同时也证明了 current traffic baseline 与 runtime-adaptive 的职责边界
   - `traffic_mem_bundle_vs_direct`
     - 仍然是 `edges_csv_bootstrap -> edges_csv_bootstrap`
     - 仍然是 `bootstrap_bound -> bootstrap_bound`
   - 含义：
     - `direct vs bundle` 现在主要用于观察 memory/NMC pressure、controller outstanding、home-stack distribution
     - `runtime adaptive` 才是 current canonical 里真正触发 native-source authority 跃迁的 case

5. `window_stop` 新 fresh 行已经不是旧的 `bootstrap_bound`
   - 当前 `window_stop_*` fresh rows：
     - `base/compare_route_source_primary_kind = legacy_route_tables_with_real_synapse_inputs`
     - `base/compare_route_memory_overlap_mode = native_synapse_aligned`
     - `source_authority_tier_transition = native_multicast_synapse_home -> native_multicast_synapse_home`
   - 含义：
     - long-stop/windowed 主线现在也已经进入 native-overlap 语义区间
     - 旧 `archsum_matrix_semantic_final_20260401` 中的 `bootstrap_bound -> bootstrap_bound` 应明确视为 stale artifact

6. 当前最准确的主线技术结论应进一步更新为：
   - canonical traffic baseline 仍然提供 `HBM-like / monolithic / bundle` 的 memory/NMC 对照面
   - canonical runtime-control 行已经提供真正的 `bootstrap_manifest -> native_multicast_synapse_home` authority 迁移
   - `window_stop` 已经站在 native-overlap 语义上
   - `route_memory_joint_summary` 现在会把 `source_binding_authority_kind` 与 `stage_breakdown_authority_kind` 并列保留，避免把真实 home binding 和 proxy stage breakdown 混写
   - `ablation / fixed-step analysis / codesign surface` 已经稳定导出：
     - `home_stack_path_authority`
     - `home_stack_controller_pressure_authority`
     - `home_stack_runtime_authority_available`
     - `dominant_home_controller_ids`
   - `authority_native_matrix_refresh_20260402` 已经用最新 contract 再次 compose-only refresh，主线代码状态与 canonical artifact 状态重新对齐
   - 下一阶段最值得投入的重心可以转到 `memory/NMC + runtime remap co-design`，而不是继续修本轮 authority provenance 缺口

### 15.6 2026-04-02 Authority Provenance Closure

截至当前代码状态，这个“在摘要层混写 authority”的缺口已经被补上，当前主线可以进一步更新为：

1. `home_stack_dataflow` 不再把真实 path binding authority 和 path stage breakdown authority 混成一个字段
   - `snn3dexp/tools/analyze_route_memory_joint.py`
   - 当前会并列保留：
     - `source_binding_authority_kind`
     - `stage_breakdown_authority_kind`
   - `initiator_groups`、根级 `home_stack_dataflow` 与 `home_path_summary` 对“路径来源绑定”的表述已经统一回到 `source_binding_authority_kind`
   - 这意味着 downstream 可以明确区分：
     - 哪些结论来自真实 `home-stack binding`
     - 哪些结论只是对路径阶段的 proxy/projection breakdown

2. `ablation` 层已经不再截断 home-path/controller-path provenance
   - `snn3dexp/tools/analyze_ablation.py`
   - `route_memory_joint` row 当前会稳定透传：
     - `home_stack_path_authority`
     - `home_stack_controller_pressure_authority`
     - `home_stack_runtime_authority_available`
     - `dominant_home_controller_ids`
   - 这让 `analyze_ablation` 不再只是“拿到 runtime controller 数值”，而是正式保留这些数值的 authority 归属

3. `codesign surface` 现在也能保真区分 binding authority 与 projection authority
   - `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - 当前 row 已投影：
     - `home_stack_source_binding_authority`
     - `home_stack_stage_breakdown_authority`
     - `pe_nic_real_home_path_source_binding_authority`
     - `pe_nic_real_home_path_stage_breakdown_authority`
     - `synapse_real_home_path_source_binding_authority`
     - `synapse_real_home_path_stage_breakdown_authority`
   - 含义：
     - `surface / canonical row` 现在已经能同时表达“真实绑定来自哪里”与“阶段拆解如何得到”，不会再把 proxy stage breakdown 误读成 runtime-real full-path authority

4. 当前主线的完成度需要重新表述
   - `authority-first` 这条 wave 到现在为止，已经不只是：
     - route source semantics authoritative
     - canonical matrix/source-tier refreshed
   - 而是已经推进到：
     - `route source authority`
     - `home-path binding authority`
     - `controller-path runtime authority`
     - `surface/canonical row authority projection`
     - 这四层都已进入同一条主线

5. 当前真正的下一阶段重心已经发生转移
   - 后续最值得继续投入的，不再是“证明 3D route 能跑”或者“再刷一轮 authority 标签”
   - 而是进入更实质的 `memory/NMC + co-design`：
     - 让 `PE/NIC -> home stack` 与 `synapse -> home stack` 的真实业务流量路径成为更强的主比较面
     - 细化 `HBM-like shared-stack` 与 `monolithic-like proxy` 的范式对照
     - 把 `direct vs bundle`、`runtime adaptive`、`windowed SNN` 放到 controller pressure / home-stack locality / runtime pressure transfer 的联合框架里分析

6. 当前这层 closure 已有 fresh regression 佐证
   - 已验证的 targeted suites：
     - `python3 -m unittest snn3dexp.tests.test_ablation_contract -v`
     - `python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics -v`
     - `python3 -m unittest snn3dexp.tests.test_memory_nmc_codesign_surface -v`
     - `python3 -m unittest snn3dexp.tests.test_export_memory_nmc_route_runtime_diff -v`
     - `python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v`
     - `python3 -m unittest snn3dexp.tests.test_fixed_step_sweep -v`
   - 当前 fresh 结果：
     - 67 tests passed

### 15.7 2026-04-02 Memory/NMC Mechanism Delta Closure

本轮主线没有再扩展新的 case family，而是把 `HBM-like vs monolithic-like` 的 compare contract 从“base/compare 能看见字段”推进到“delta / phase2 导出 / codesign 解释面也完全一致”。这一步的重要性在于：当前 memory/NMC 主线终于可以稳定表达 `authority + controller pressure + home-stack dataflow + runtime pressure transfer` 这一整条机理链，而不会在 compare 的最后一跳掉字段。

1. `analyze_ablation.py` 的 `hbm_like_vs_monolithic_like` compare 现在已经真正闭环
   - `base` / `compare` / `mechanism_rows` 之外，`deltas` 也正式补齐：
     - `pe_nic_home_stack_demands_total`
     - `pe_nic_home_stack_service_deficit_total`
     - `synapse_home_stack_demands_total`
     - `synapse_home_stack_service_deficit_total`
   - 这意味着 `HBM-like shared-stack` 与 `monolithic-like proxy` 的比较，不再只是：
     - locality / vertical hops / remote-home ratio
   - 而是能继续下沉到：
     - `PE/NIC -> home stack` 的 demand / deficit 变化
     - `synapse -> home stack` 的 demand / deficit 变化

2. 当前 memory-model compare 的语义层级已经比前一轮更完整
   - `home_stack_path_authority`
   - `home_stack_controller_pressure_authority`
   - `home_stack_runtime_authority_available`
   - `dominant_home_controller_ids`
   - `dominant_dataflow_initiator_kind`
   - `runtime_pressure_transfer_kind`
   - 加上本轮补完的四个 numeric deltas，当前 compare 已经能同时回答：
     - 真实 home 路径绑定来自哪里
     - controller pressure 是否来自真实 runtime controller
     - 主导流量是 `PE/NIC` 还是 `synapse`
     - `HBM-like` 与 `monolithic-like` 的压力迁移到底发生在谁身上

3. `phase2` 导出链与 compare contract 现在重新对齐
   - `export_phase2_paper_artifacts.py` 现有导出面已经能稳定保留：
     - `runtime_pressure_transfer_kind`
     - `dominant_dataflow_initiator_kind`
     - `pe_nic_home_stack_demands_total`
     - `pe_nic_home_stack_service_deficit_total`
     - `synapse_home_stack_demands_total`
     - `synapse_home_stack_service_deficit_total`
   - `monolithic_vs_hbm` 子块也能保留：
     - `base_runtime_pressure_transfer_kind`
     - `compare_runtime_pressure_transfer_kind`
     - `runtime_pressure_transfer_kind_transition`
   - 含义：
     - `phase2 summary / csv / markdown` 不再只是“记住 pressure 差异”
     - 而是能正式记住“压力是怎样从某类 initiator/controller/path 转移过去的”

4. 当前主线技术状态应更新为
   - `HBM-like NMC vs monolithic-like proxy` 已经从“stack/home-demand surface 对照”升级成“controller/dataflow/runtime-transfer 机理对照”
   - 这仍然是 Python / artifact 层语义闭环，不应误表述成已经完成新的真实 DRAM timing signoff 或 near-memory operator 数据通路
   - 但它已经足够支撑下一阶段更高质量的问题：
     - `direct vs bundle` 到底把压力转移到哪一类 home-stack initiator
     - `monolithic_like` 改善的是 locality、controller alignment，还是 runtime pressure transfer
     - 哪些 memory/NMC 结论已经具备论文级 mechanism evidence chain

5. 本轮 fresh regression 佐证
   - 已验证：
     - `python3 -m unittest snn3dexp.tests.test_ablation_contract -v`
     - `python3 -m unittest snn3dexp.tests.test_phase2_paper_artifacts -v`
     - `python3 -m unittest snn3dexp.tests.test_memory_nmc_codesign_surface -v`
     - `python3 -m unittest snn3dexp.tests.test_export_memory_nmc_route_runtime_diff -v`
     - `python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v`
     - `python3 -m unittest snn3dexp.tests.test_fixed_step_sweep -v`
   - 当前 fresh 结果：
     - 73 tests passed

6. 最合理的下一步已经更清晰
   - 不是继续修 compare/export 字段存在性
   - 而是把这组新的 controller/dataflow/runtime-transfer 机理字段刷新进 fresh canonical artifacts：
     - `codesign surface`
     - `phase2 artifacts`
     - `codesign matrix`
   - 再往前一步，才是让 `PE/NIC` 与 `synapse/home-stack` 的真实业务流在同一 fresh run 上进入更强的 NMC co-design 讨论面

### 15.8 2026-04-02 Runtime-Window Co-Design Closure

本轮在 `memory/NMC mechanism delta closure` 之后，主线又往前跨了一步：新的 `home-stack/controller/dataflow/runtime-transfer` 机理字段，不再只停在 analysis/export 层，而是第一次真正下沉到了 runtime policy 与 canonical window family。

1. `runtime policy` 已开始消费 `memory/NMC mechanism` 信号
   - `snn3dexp/runtime/policy.py`
   - 当前会从单 case `joint_summary` / `architecture_summary` 提取：
     - `dominant_dataflow_initiator_kind`
     - `runtime_pressure_transfer_kind`
     - `home_stack_runtime_authority_available`
     - `home_stack_controller_pressure_authority`
     - `pe_nic_home_stack_demands_total`
     - `pe_nic_home_stack_service_deficit_total`
     - `synapse_home_stack_demands_total`
     - `synapse_home_stack_service_deficit_total`
   - 并形成新的单-case runtime 指标：
     - `memory_nmc_mechanism_signal_available`
     - `memory_nmc_mechanism_pressure_proxy`
   - runtime action 也已经正式接入：
     - `observe_memory_nmc_mechanism`
     - `rebalance_memory_nmc_mechanism`
   - 含义：
     - runtime adaptive 不再只根据 coarse-grained coupling proxy 作判断
     - 也开始根据 `谁在主导 home-stack 压力`、`pressure transfer 是否 cross-class` 来决定是否做 home-route / stack-home reweight

2. canonical window family 已正式加入 `full_3d_snn_window_runtime_adaptive`
   - 新 case：
     - `snn3dexp/cases/full_3d_snn_window_runtime_adaptive/case.json`
     - `snn3dexp/cases/full_3d_snn_window_runtime_adaptive/spec.json`
   - 它的定位不是替代 `full_3d_runtime_adaptive`
   - 而是把 runtime control 真正带入 windowed native-SNN family，使主线从：
     - `direct / bundle / monolithic / gating`
   - 扩展为：
     - `direct / runtime-adaptive / bundle / monolithic / gating`

3. windowed family 的 canonical tool chain 已同步扩容
   - 已接入：
     - `snn3dexp/tools/analyze_fixed_step_sweep.py`
     - `snn3dexp/tools/run_memory_nmc_codesign_matrix.py`
     - `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
     - `snn3dexp/tools/export_phase2_paper_artifacts.py`
   - 当前结果：
     - fixed-step default case ids 已包含新 case
     - canonical matrix limited runtime smoke profile 也已包含新 case
     - window surface / phase2 case order / runtime focus rows 已能识别新 case

4. 这一步让主线的研究重心真正完成转移
   - 之前更多是：
     - analysis 能不能表达 mechanism
     - compare/export 能不能保留 authority
   - 现在则进入：
     - runtime control 是否能依据 `memory/NMC mechanism` 作出可解释决策
     - windowed native-SNN family 中，`runtime-adaptive` 与 `direct/bundle/monolithic/gating` 的对照是否能站在同一 canonical 面上

5. 当前还没有做的事也需要明确
   - 本轮仍然主要是 Python / summary / runtime-policy 层闭环
   - 还没有把新的 `memory_nmc_mechanism_pressure_proxy` 继续下沉到更深的 SST object-graph runtime datapath
   - 也还没有跑 fresh full matrix artifact，把 `windowed runtime-adaptive` 的真实 canonical JSON/CSV/Markdown 产物刷出来
   - 所以下一步最自然的动作是：
     - 跑 fresh `codesign matrix`
     - 对比 `full_3d_snn_window_runtime_adaptive` 与 `direct/bundle/monolithic`
     - 验证 runtime remap 是否真的改变 `pressure transfer` 与 `home-stack locality`

6. 当前 fresh regression 佐证
   - 已验证：
     - `python3 -m unittest snn3dexp.tests.test_case_catalog -v`
     - `python3 -m unittest snn3dexp.tests.test_run_case.RunCaseTests.test_full_3d_snn_window_runtime_adaptive_case_exists_with_window_runtime_control_config -v`
     - `python3 -m unittest snn3dexp.tests.test_fixed_step_sweep -v`
     - `python3 -m unittest snn3dexp.tests.test_run_fixed_step_multicase_sweep -v`
     - `python3 -m unittest snn3dexp.tests.test_memory_nmc_codesign_surface -v`
     - `python3 -m unittest snn3dexp.tests.test_phase2_paper_artifacts -v`
     - `python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v`
     - `python3 -m unittest snn3dexp.tests.test_runtime_3d_policy.Runtime3DPolicyTests.test_runtime_policy_reads_coupling_proxies_as_observe_only_recommendations snn3dexp.tests.test_runtime_3d_policy.Runtime3DPolicyTests.test_runtime_policy_executes_coupling_proxies_when_enabled snn3dexp.tests.test_runtime_3d_policy.Runtime3DPolicyTests.test_runtime_policy_observes_memory_nmc_mechanism_signal snn3dexp.tests.test_runtime_3d_policy.Runtime3DPolicyTests.test_runtime_policy_executes_memory_nmc_mechanism_signal_when_enabled -v`
   - 当前 fresh 结果：
     - 59 tests passed

### 15.9 2026-04-05 Fresh Runtime Mechanism Propagation Repair

本轮不再只是把 `memory/NMC mechanism` 留在 unit-test 或附录描述层，而是把真实 `route_memory_joint -> runtime_summary -> fixed_step case row -> canonical surface` 这条链补成了 fresh artifact 可见的主线闭环。

1. 根因被确认并修复
   - `snn3dexp/runtime/policy.py`
   - 之前 runtime policy 只认规范化字段：
     - `dominant_dataflow_initiator_kind`
     - `home_stack_controller_pressure_authority`
     - `home_stack_runtime_authority_available`
     - `runtime_pressure_transfer_kind`
   - 但真实 `route_memory_joint_summary.json` 的 raw 字段来自：
     - `dominant_initiator_kind`
     - `controller_pressure_authority_kind`
     - `runtime_authority_available`
     - `runtime_hotspot_alignment.controller_alignment_kind`
     - `initiator_groups[*].demand_total/service_deficit_total`
   - 现在 runtime policy 已能直接读取并归一化这组 raw 字段，不再只在 synthetic unit payload 下成立。

2. fixed-step case row 已把 runtime mechanism 真正抬到 canonical surface
   - `snn3dexp/tools/analyze_fixed_step_sweep.py`
   - 当前 case row / window baseline row 已显式带出：
     - `runtime_enabled`
     - `control_decision`
     - `control_decision_source`
     - `memory_nmc_mechanism_signal_available`
     - `memory_nmc_mechanism_pressure_proxy`
   - 同时恢复了 `runtime_breakdown` 导出，使 `direct -> window_runtime_adaptive` 的 fixed-step 对照重新进入 summary/csv。

3. fresh real-runtime smoke 已验证主线 artifact
   - fresh label：
     - `window_runtime_codesign_refresh_20260405_memory_nmc_fix`
   - 权威产物：
     - `snn3dexp/analysis/codesign_matrix/window_runtime_codesign_refresh_20260405_memory_nmc_fix/memory_nmc_codesign_matrix_summary.json`
     - `snn3dexp/analysis/codesign_matrix/window_runtime_codesign_refresh_20260405_memory_nmc_fix/codesign_surface/memory_nmc_codesign_surface_summary.json`
     - `snn3dexp/analysis/codesign_matrix/window_runtime_codesign_refresh_20260405_memory_nmc_fix/route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`
     - `snn3dexp/analysis/codesign_matrix/window_runtime_codesign_refresh_20260405_memory_nmc_fix/phase2_artifacts/phase2_runtime_summary.json`
   - `full_3d_snn_window_runtime_adaptive` 的 fresh canonical row 当前已明确给出：
     - `runtime_enabled = true`
     - `control_decision = executed_control`
     - `control_decision_source = hybrid`
     - `memory_nmc_mechanism_signal_available = true`
     - `memory_nmc_mechanism_pressure_proxy = 0.25`
     - `dominant_dataflow_initiator_kind = pe_nic_to_home_stack`
     - `runtime_pressure_transfer_kind = runtime_class_unresolved`
     - `steps_completed = 3`
     - `memory_requests_total = 448`

4. 这一步对主线的意义
   - 现在可以更严格地说：
     - `memory/NMC mechanism` 已不只是 policy 单测能力
     - 它已经进入真实 window family 的 fixed-step case row 与 canonical surface
   - 因此下一阶段讨论：
     - `direct vs runtime-adaptive vs bundle vs monolithic`
     - `home-stack initiator` 主导权
     - `pressure transfer` 的可解释性
   - 已经可以站在 fresh runtime artifact 上展开，而不只是依赖静态导出推断。

### 15.9 2026-04-02 Fresh Canonical Artifact Refresh

这一步已经从“schema/compose 支持”推进到“真实 canonical artifact 已落盘”。

1. fresh canonical matrix 已完成
   - 执行：
     - `python3 -m snn3dexp.tools.run_memory_nmc_codesign_matrix --matrix-label window_runtime_codesign_refresh_20260402 --phase2-mainline --limited-runtime-smoke-profile canonical_runtime_smoke`
   - 权威产物：
     - `snn3dexp/analysis/codesign_matrix/window_runtime_codesign_refresh_20260402/memory_nmc_codesign_matrix_summary.json`
     - `snn3dexp/analysis/codesign_matrix/window_runtime_codesign_refresh_20260402/codesign_surface/memory_nmc_codesign_surface_summary.json`
     - `snn3dexp/analysis/codesign_matrix/window_runtime_codesign_refresh_20260402/route_runtime_diff/memory_nmc_route_runtime_diff_summary.json`
     - `snn3dexp/analysis/codesign_matrix/window_runtime_codesign_refresh_20260402/phase2_artifacts/phase2_runtime_summary.json`

2. `windowed runtime-adaptive` 已经真实进入 canonical window baseline
   - `codesign_surface.window_baseline_rows` 当前包含：
     - `full_3d_snn_window`
     - `full_3d_snn_window_runtime_adaptive`
     - `full_3d_snn_window_bundle_v3`
     - `full_3d_snn_window_monolithic_proxy`
     - `full_3d_snn_window_gating_event_synth`
   - 其中 `full_3d_snn_window_runtime_adaptive` 的 fresh 结果显示：
     - `steps_completed = 3`
     - `closed_loop_candidate = true`

3. `phase2 artifacts` 现在也能正式看见这个 window case
   - `export_phase2_paper_artifacts.py` 已补齐 `codesign surface -> phase2 runtime focus` 回灌
   - fresh `phase2_runtime_summary.json` 当前：
     - `runtime_focus_cases = ["full_3d_runtime_adaptive", "full_3d_snn_window_runtime_adaptive"]`
     - `canonical_metric_planes.thermal_runtime_control.rows[*].case_id` 也包含这两个 case
   - 这一步的意义不是宣称 window runtime case 已完成 next-window control execute loop
   - 正确表述应当是：
     - 它已经进入 canonical `phase2` 解释面
     - 但 fresh fixed-step window run 当前主要提供的是 `closed_loop_candidate / coupling / pressure` 证据
     - 还不是 traffic-style `runtime_control_next_window.json` 那种单独 runtime action artifact

4. route/runtime diff 主线继续成立
   - `route_runtime_diff.runtime_control_closure_summary.row_count = 1`
   - `dominant_action_effect_classification = beneficial`
   - 当前 runtime-control 主比较行仍然由：
     - `full_3d` vs `full_3d_runtime_adaptive`
   - 主导 axis 仍然是：
     - `memory_barrier_coupling_proxy`

5. 当前主线边界因此更加清楚
   - `windowed runtime-adaptive` 已经从“能被工具识别”升级为“真实 canonical surface + phase2 summary 都能看见”
   - 但如果要把它进一步升级成和 `full_3d_runtime_adaptive` 同强度的 runtime-control compare row，下一步还要补：
     - windowed runtime case 的真实 control-action artifact
     - windowed family 内 `runtime-adaptive vs direct/bundle/monolithic` 的专门 compare/export 面
