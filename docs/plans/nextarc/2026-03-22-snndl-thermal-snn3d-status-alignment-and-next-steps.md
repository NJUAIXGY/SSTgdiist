# SnnDL Thermal + 3D SNN Status Alignment And Next Steps

Date: 2026-03-22
Owner: Fufu
Status: Code/test/doc aligned review after HotSpot vendoring and runtime-policy test refresh

Note:
`2026-03-23` 的最新 3D SNN 代码对齐刷新见 `docs/plans/nextarc/2026-03-23-3d-snn-status-refresh-and-nextarc.md`。
本文保留为 `2026-03-22` 时点的热分析/3D SNN 联合状态快照。

## 1. 文档目的

这份文档用于把我们当前关于 `SnnDL + snn3dexp` 的两条主线重新压回同一个真实基线：

1. `HotSpot offline-first` 热分析链到底已经落地到什么程度。
2. `3D SNN` 芯片体系结构建模的主线现在应该押在哪个方向。

这份文档不以“历史 task 记忆”或“早期设计预期”为准，而是以：

- 当前代码
- 当前测试
- 当前可见正式产物

为准。

如果它与旧文档在字段级、工件级、阶段优先级上存在冲突，应优先以这份文档和当前代码为准。

## 2. 本轮证据基线

### 2.1 代码审阅范围

本轮直接核对了下列主文件：

- `sst_dram_si/mesh_template/test_runtime_thermal_config.py`
- `sst_dram_si/tools/thermal_export.py`
- `sst_dram_si/tools/analyze_thermal_runs.py`
- `sst_dram_si/tools/summarize_thermal_analysis.py`
- `sst_dram_si/tools/generate_thermal_sweep_report.py`
- `sst_dram_si/tools/run_thermal_contract_suite.py`
- `snn3dexp/platform/build_system.py`
- `snn3dexp/runtime/policy.py`
- `snn3dexp/thermal/hotspot_driver.py`
- `snn3dexp/tools/run_case.py`
- `snn3dexp/tools/analyze_fixed_step_sweep.py`
- `snn3dexp/memory/hbm_stack.py`
- `snn3dexp/memory/monolithic_proxy.py`
- `snn3dexp/mesh3d_template/spec.py`

### 2.2 文档对齐范围

本轮以以下文档为主要对照对象：

- `docs/plans/nextarc/2026-03-20-snndl-thermal-analysis-status-deep-dive.md`
- `docs/plans/nextarc/2026-03-20-snndl-thermal-phase7-status-review-and-next-direction.md`
- `docs/plans/nextarc/2026-03-20-snndl-online-thermal-feedback-interface-design.md`
- `docs/plans/nextarc/2026-03-20-3d-snn-current-status-and-nextarc.md`
- `docs/plans/nextarc/2026-03-21-snn3d-chip-nextstep-architecture-modeling-design.md`

### 2.3 产物 spot-check 范围

本轮抽样核对了下列正式或半正式产物：

- `tmp/thermal_contract_suite_v1/thermal_contract_suite_result.json`
- `tmp/hotspot_formal_spec_3d_stats_prefix_v1/20260319-135209/thermal/summary/thermal_summary.json`
- `tmp/hotspot_memctrl_mixed_analysis_v1/thermal_sweep_overview.json`
- `tmp/hotspot_memctrl_mixed_analysis_v1/thermal_analysis.json`
- `snn3dexp/analysis/full_3d_runtime_adaptive/arc4_hotspot_refresh_20260321/runtime_summary.json`
- `snn3dexp/analysis/full_3d_runtime_adaptive/arc4_hotspot_refresh_20260321/runtime_control_next_window.json`
- `snn3dexp/analysis/full_3d/arc4_baseline_compose_20260321/phase2_case_summary.json`
- `snn3dexp/analysis/sweeps/fixed_step_window_route_memory/fixed_step_sweep_summary.json`

### 2.4 当前验证结果

截至 `2026-03-22`，本轮直接跑过并通过的 targeted tests：

- `30` 个 `sst_dram_si` 热分析相关测试
- `45` 个 `snn3dexp` baseline/sweep/run_case 相关测试
- `9` 个 `snn3dexp` runtime thermal/control 相关测试

合计：

- `84` 个 targeted tests 通过

额外确认到的正式 suite 工件：

- `tmp/thermal_contract_suite_v1/thermal_contract_suite_result.json`
  - `case_count = 5`
  - `passed_case_count = 5`
  - `failed_case_count = 0`

## 3. 当前已经正式成立的结论

### 3.1 我们当前不应把热建模理解为 “SST 自带热仿真”

当前正确口径是：

- `SST` 负责主时序和统计导出
- `SnnDL/snn3dexp` 负责热输入语义整理
- `HotSpot` 作为本仓库集成的 sidecar/offline thermal backend

也就是说，当前平台已经具备正式热分析能力，但这不是 “SST 内建一个 cycle-level thermal loop 已经帮我们做好了”。

我们现在拥有的是：

`SST timing + project-owned thermal contracts + HotSpot sidecar`

这一定义很重要，因为它直接决定了后续工作重点应该放在：

- 热输入接口
- 工件语义
- 运行时热状态接口

而不是误以为下一阶段只要“打开 SST 的某个热选项”。

### 3.2 `HotSpot offline-first` 热分析主链已经正式闭环

当前主链已经稳定存在：

`runtime/spec thermal config -> effective_config.json -> thermal_export.py -> HotSpot -> thermal_summary.json / tile_temperature_summary.csv -> analyze_thermal_runs.py / summarize_thermal_analysis.py / generate_thermal_sweep_report.py`

这条链已经覆盖：

- `2D block` 模型
- `3D grid/layered` 模型
- `windowed ptrace`
- `stats_prefix`
- `csv power source`
- `power_source per-layer routing`
- `memctrl block`
- `layer_stack_validation`
- `batch analysis + sweep report`

当前仓库里已经明确存在：

- vendored HotSpot 源码与二进制：`externals/HotSpot-7.0/`
- canonical thermal suite manifest：`tools/specs/mesh_hotspot_thermal_contract_suite_v1.json`
- thermal sidecar 导出/分析工具链：`sst_dram_si/tools/`

所以“能不能正式产出热数据”这个问题，答案已经不是 open question，而是：

- 可以
- 并且已经形成稳定 contract

### 3.3 当前热分析 contract 的真实中心已经是 `v2`

当前代码里的正式 contract 应理解为：

- `thermal_summary.json`
  - `thermal_contract_version = "v2"`
  - 顶层使用 `temperature_c.{min,max,avg}`
  - 使用 `window_power_sample_count`
  - 使用 `window_power_block_count`
  - 使用 `window_power_trace_sources`
  - 使用 `layer_stack_validation`
- `thermal_analysis.json`
  - `analysis_contract_version = "v2"`
- `thermal_sweep_overview.json`
  - `sweep_summary_contract_version = "v2"`

尤其需要明确：

- 当前正式 summary 不是旧式的顶层 `peak_temperature_c` / `average_temperature_c`
- 当前正式多 run 概览不是旧式临时 JSON，而是：
  - `layer_stack_validation_overview`
  - `layer_stack_validation_all_runs`
  - `window_power_trace_source_counts`

### 3.4 历史产物与当前 contract 已经出现可预期漂移

当前仓库中的一个真实情况是：

- 代码和测试已经以 `v2` 为准
- 但部分历史产物是在 `v2` 落稳之前导出的

因此我们今天能看到这种现象：

- 某些历史 `thermal_summary.json` 中缺少当前 `v2` 字段
- 某些历史 `thermal_analysis.json` / `thermal_sweep_overview.json` 中缺少 `window_power_*` 统计
- 旧文档对字段名的描述与今天代码不完全一致

这不应被解读成“当前代码没有能力”，而应被解读成：

- `artifact freshness` 与 `schema freshness` 不完全一致

因此当前判断平台能力时，优先级必须是：

`当前代码 > 当前测试 > fresh artifacts > 历史 artifacts > 旧文档口述`

### 3.5 `snn3dexp` 已经是一个真实的 3D 芯片架构建模平台

当前 `snn3dexp/cases/` 下已存在 `13` 个显式 case：

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

同时，`run_case.py` 中已经有正式 `9-case baseline suite`：

- `PHASE2_BASELINE_CASES`

这说明现在的平台状态已经不是“零散 prototype”，而是：

- case catalog
- baseline suite
- smoke/compose
- phase2 summary
- fixed-step sweep
- thermal/runtime/control

已经全部进入统一平台语义。

### 3.6 `3D route + memory + workload` 三个主维度都已经站住

当前已经明确落地的三条主维度：

#### A. route 维度

当前 `run_case.py` 和 fresh stats 已经支持：

- `route3d_native_activation_total`
- `route3d_native_gating_activation_total`
- `route3d_native_direct_activation_total`
- `route3d_native_unique_sources_total`
- `actual_activation_source = "sst_stats_route3d_native_runtime"`

这意味着 route3d runtime observability 已经不是 debug 临时项，而是正式 summary 输入。

#### B. memory 维度

当前 `mesh3d_template/spec.py` 与 `memory/*` 已正式支持：

- `legacy_per_pe`
- `hbm_like`
- `monolithic_like`

这组 memory paradigm 已经被 builder/runtime/analyzer 共同消费，不再只是 case label。

#### C. workload 维度

当前 `snn3dexp` 已正式拥有两条 workload 入口：

- `traffic_mem`
- `snn`

并且 `fixed_step_window_route_memory` sweep 已经成形，覆盖：

- `task_fixed_step_4_10us`
- `task_fixed_step_4_10us_sp64`
- `task_fixed_step_8_20us`
- `task_fixed_step_8_20us_sp64`
- `task_fixed_step_16_40us`
- `task_fixed_step_16_40us_sp64`

以及三类 compare case：

- `full_3d_snn_window`
- `full_3d_snn_window_bundle_v3`
- `full_3d_snn_window_monolithic_proxy`

## 4. 当前最关键的边界与缺口

### 4.1 当前热侧的强项是 `offline-first + stable artifact surface`

当前热侧最成熟的部分不是 runtime in-loop，而是：

- 输入 contract 稳定
- 工件链路稳定
- 2D/3D support 稳定
- batch analysis 稳定

这一点必须继续保持，因为它已经是后续所有在线热接口的地基。

### 4.2 当前热侧还不是 “HotSpot 驱动的广义 runtime control”

虽然 `full_3d_runtime_adaptive/arc4_hotspot_refresh_20260321/runtime_control_next_window.json` 已明确出现：

- `control_decision = "executed_control"`
- `recommended_actions = ["rebalance_home_route", "raise_vertical_penalty"]`

但当前真实控制来源仍主要是：

- `thermal_hooks`
- `joint_runtime`
- proxy/joint thermal signals

而不是广义的：

- `HotSpot steady-state outputs directly driving execute loop`

换句话说：

- runtime execute loop v1 已存在
- HotSpot evidence 已进入 canonical artifact surface
- 但 HotSpot 还没有成为更大范围 case 的正式控制输入

### 4.3 route kernel 仍然主要建立在 bootstrap source semantics 上

当前 route3d 路径已经是 native interface + native runtime stats，但 source 语义仍主要来自：

- `edges_csv`
- legacy-built route tables

因此当前 route gap 的准确表述不是：

- “3D route 还没实现”

而是：

- “3D route kernel 已实现，但还没从 bootstrap source semantics 推进到更真实的 synapse/BCSR/GAS native source semantics”

### 4.4 我们当前最缺的不是更多 case，而是统一 compare surface

当前已经有：

- 9-case baseline suite
- 13-case catalog
- fixed-step sweep
- HBM-like / monolithic-like
- traffic_mem / SNN window

但 methodology 上仍然缺：

- 一套统一的 compare surface
- 一套统一的 case_role/control_mode/workload_impl/memory_kind 语义标签
- 一套统一的 export surface，把 baseline + fixed-step + runtime adaptive 串成同一分析面

这比继续增加新 case 更紧迫。

## 5. 文档对齐结论

### 5.1 仍然有效的旧判断

下面这些判断今天仍然成立：

- `2026-03-20-snndl-thermal-analysis-status-deep-dive.md`
  - `offline-first` 主判断正确
- `2026-03-20-snndl-online-thermal-feedback-interface-design.md`
  - 先冻结 interface，再谈 runtime HotSpot，方向正确
- `2026-03-20-3d-snn-current-status-and-nextarc.md`
  - 平台级而不是 feature patch 的判断正确
- `2026-03-21-snn3d-chip-nextstep-architecture-modeling-design.md`
  - 以 `memory/NMC + route source semantics + thermal execute loop` 为主线的排序正确

### 5.2 需要被当前状态覆盖的口径

当前应以新口径覆盖的内容包括：

1. 热 summary 的正式字段语义应按当前 `v2` 代码理解，而不是按旧 artifact 中的缺字段状态理解。
2. 当前 runtime thermal/control 已不再是“只有设计没有执行”，而是已经有 window-level execute artifact。
3. 当前 route kernel 不应再被描述成“还停在 3D transport 之前”，而应描述成“native route kernel 已经站稳，但 source semantics 仍需前推”。
4. 当前的主要瓶颈不是热链路能否跑通，而是：
   - artifact semantics hardening
   - compare surface unification
   - source semantics realism

### 5.3 本轮额外对齐的一点

本轮还确认了一个容易被忽略的现实：

- `snn3dexp/tests/test_runtime_3d_policy.py` 里原先把 “HotSpot binary 缺失” 写死成测试前提
- 但仓库现在已经本地 vendored `externals/HotSpot-7.0/hotspot`

因此当前正确环境口径应当是：

- 测试与文档都应兼容：
  - `skipped_missing_binary`
  - `ran`

两种运行形态

而不应继续把 “没有 HotSpot binary” 当成默认事实。

## 6. 下一阶段推荐优先级

### Priority 0: Thermal Artifact Semantics Hardening + Canonical Refresh

这是最应该先做的事情。

目标不是再发明新 thermal feature，而是把当前已经存在的热链路做成真正稳定的基座。

建议内容：

- 刷新 canonical thermal suite 和关键 `snn3dexp` thermal artifacts 到当前 `v2` contract
- 明确在 summary/export 中统一使用：
  - `thermal_contract_version`
  - `analysis_contract_version`
  - `sweep_summary_contract_version`
  - `window_power_sample_count`
  - `window_power_trace_sources`
  - `temperature_c.{min,max,avg}`
- 增加 freshness/provenance 标记，区分：
  - code-current artifact
  - history artifact

理由：

- 这是所有后续 HotSpot calibration、runtime replay、compare surface 的共同地基
- 当前这里投入最小，但收益最大

### Priority 1: Unified Memory/NMC Compare Surface

把已经存在的三类证据真正统一起来：

- `PHASE2_BASELINE_CASES`
- `fixed_step_window_route_memory`
- `runtime_adaptive / thermal_guard` canonical artifacts

建议统一维度：

- `case_role`
- `control_mode`
- `workload_impl`
- `memory_kind`
- `memory_model_family`
- `route_kernel source`
- `step_budget`
- `spike_budget_label`

目标不是更多图，而是形成统一问题面：

- `HBM-like vs monolithic-like`
- `direct vs bundle`
- `traffic_mem vs windowed SNN`
- `route compression / replay / memory amplification`

### Priority 2: Route Kernel Beyond `edges_csv` / Legacy Bootstrap

下一阶段 route 主线应明确转向：

- `synapse/weight/BCSR/GAS native source semantics`

建议内容：

- 从真实 synapse source descriptors 出发生成 native route source
- 减少对 `edges_csv` 预物化输入的主依赖
- 补充更接近 source semantics 的 runtime counters：
  - `die_local_replication`
  - `inter_die_replication`
  - `vertical_subtree_depth`
  - `ingress_replication_cost`

理由：

- 后续所有 route-memory-home-stack co-design 都会依赖这个地基
- 这是让平台从“可运行 3D router”走向“真实 3D SNN route kernel”的关键一步

### Priority 3: Thermal-Aware Execute Loop V2

当前不要直接跳到 per-cycle。

建议继续坚持：

- `window`
- `epoch`
- `global-step batch`

这一级别的控制粒度。

建议内容：

- runtime 同时记录 proxy thermal 与 HotSpot thermal evidence
- 明确哪些 case：
  - `observe_only`
  - `recommend_only`
  - `adaptive_control`
- 让更多 canonical case 产出：
  - 执行前参数
  - 执行后参数
  - 下一窗口 processing params
  - thermal delta / overlap delta / stall delta

目标不是让 HotSpot 进入 SST 主循环，而是让 HotSpot evidence 真正进入 execute-loop 的正式证据链。

### Priority 4: 3D Thermal Realism Expansion

这部分很重要，但应放在前面三项之后。

建议后置的内容包括：

- 更细的 layer taxonomy
- per-stack/per-tier thermal differentiation
- memctrl / gather / writeback 更细的热层映射
- package / spreader / sink 参数族
- TSV/MIV/interposer realism

这些方向不是不做，而是不应在 compare surface 和 source semantics 仍未站稳时抢占主线。

## 7. 当前明确不建议优先做的事情

当前不建议把主线资源优先投到：

- `HotSpot` 直接嵌入 `SST` 主循环
- per-cycle thermal-aware control
- 继续优先扩论文 artifact
- 在 route 面继续横向扩更多 router/packet feature，但不补 source semantics
- 过早做更细的封装/工艺 realism

原因不是这些方向没价值，而是它们今天都不是最卡主语义闭环的点。

## 8. 建议的直接开工顺序

### Step 1

刷新 thermal canonical artifacts，并补一个统一 freshness/provenance 标记层。

建议入口：

- `sst_dram_si/tools/run_thermal_contract_suite.py`
- `sst_dram_si/tools/generate_thermal_sweep_report.py`
- `snn3dexp/tools/refresh_thermal_outputs.py`

### Step 2

把 baseline suite、fixed-step sweep、runtime adaptive case 的关键维度收敛成统一 compare/export surface。

建议入口：

- `snn3dexp/tools/run_case.py`
- `snn3dexp/tools/analyze_ablation.py`
- `snn3dexp/tools/analyze_fixed_step_sweep.py`

### Step 3

立一个 `route source-native` 小闭环，先从 synapse/BCSR/GAS metadata 生成一版不依赖 `edges_csv` 的 native route source。

建议入口：

- `snn3dexp/memory/`
- `snn3dexp/platform/`
- `SnnDL/services/synapse/route3d/`

### Step 4

在 `window` 粒度扩大 thermal-aware execute loop，把 HotSpot evidence 接入为正式 side evidence，并逐步挑选 case 进入控制链。

建议入口：

- `snn3dexp/runtime/policy.py`
- `snn3dexp/platform/build_system.py`
- `snn3dexp/thermal/`
- `snn3dexp/tools/run_case.py`

## 9. 最终结论

截至 `2026-03-22`，最准确的总判断是：

- `HotSpot thermal` 已经不是概念功能，而是稳定的 `offline-first` 正式能力。
- `snn3dexp` 已经不是 3D 草台原型，而是具备 route/memory/workload/thermal/runtime 五维联动能力的平台。
- 当前最需要投入的，不是继续证明“能不能跑”，而是：
  - 统一 artifact semantics
  - 统一 compare surface
  - 推进 route source semantics realism
  - 让 HotSpot evidence 真正进入更广义的 thermal-aware execute loop

如果下一阶段主线需要压缩成一句话，建议统一表述为：

`先把 thermal artifact semantics 和 memory/NMC compare surface 站稳，再把 route kernel 从 bootstrap 推向 synapse-native source semantics，最后在 window-level execute loop 上扩大 HotSpot-aware thermal control。`

## 10. 2026-03-22 补充刷新：Mechanism Decomposition 与 Windowed Same-Tag Lane

### 10.1 `analyze_ablation.py` 的 compare contract 已经升级成“机理层”输出

当前 `route_memory_comparisons` 与 `memory_model_comparisons` 不再只是 coarse delta：

- 每个 compare block 现在都包含：
  - `mechanism`
  - `mechanism_rows`
- `direct_v4_vs_bundle_v3` 已显式导出：
  - `router_bundle_v3_rx_total`
  - `tx_bundle_v3_packets_total`
  - `tx_spikekey_v4_packets_total`
  - `gas_scatter_spikes_emitted_total`
  - `metadata_lookup_*`
  - `synapse_gather_*`
  - `stream_region_*`
  - `writeback_region_*`
  - `attributed_service_deficit_total`
- `hbm_like_vs_monolithic_like` 已显式导出：
  - `vertical_hops_ratio`
  - `remote_home_ratio`
  - `tier_local_home_access_ratio`
  - `same_xy_cross_tier_access_ratio`
  - `remote_home_access_ratio`
  - `vertical_link_pressure`
  - `reliability_penalty`
  - `memory_requests_per_completed_step`
  - `total_service_deficit_per_completed_step`
  - `stall_on_step_gate_cycles_per_completed_step`

这意味着我们现在讨论 `bundle vs direct`、`HBM-like vs monolithic` 时，已经不需要只盯单一 `delta`，而可以直接回到“route packetization -> semantic backlog -> home pressure -> thermal/reliability”这条机制链。

### 10.2 `export_memory_nmc_codesign_surface.py` 已把机理层正式投影到统一导出面

当前 unified surface 已新增：

- `traffic_mem_mechanism_rows`
- `Traffic-Mem Mechanism Decomposition` markdown section
- 更细粒度 compare 字段：
  - `router_bundle_v3_rx_total_delta`
  - `tx_bundle_v3_packets_total_delta`
  - `tx_spikekey_v4_packets_total_delta`
  - `gas_scatter_spikes_emitted_total_delta`
  - `metadata_lookup_backlog_delta`
  - `remote_home_access_ratio_delta`
  - `tier_local_home_access_ratio_delta`
  - `attributed_service_deficit_total_delta`
  - 以及 base/compare 的 dominant-home class context

刷新后的正式 same-tag surface：

- `snn3dexp/analysis/codesign_surface/codesign_single_20us_20260322/memory_nmc_codesign_surface_summary.json`

现在已经包含：

- `traffic_mem_compare_rows = 2`
- `traffic_mem_mechanism_rows = 27`
- `window_baseline_rows = 9`
- `window_bundle_breakdown_rows = 6`
- `window_memory_model_breakdown_rows = 6`
- `window_spike_sensitivity_rows = 9`

也就是说，当前平台已经从“统一表格”推进到“统一 compare surface + 可追溯机制行”的阶段。

### 10.3 `windowed SNN` 的 same-tag canonical lane 已正式固化

本轮把 `task_fixed_step_8_20us` 固化成 windowed canonical lane，原因是：

- 三个 window case 都存在这组 fresh run
- 它与当前主线 `20us` compare 面时间窗对齐
- 它比 `4-step/10us` 更接近主 baseline 讨论窗口

本轮新增或刷新了以下工件：

- manifest：
  - `snn3dexp/configs/run_tag_manifests/windowed_same_tag_8_20us_20260322.json`
- lane ablation：
  - `snn3dexp/analysis/windowed_same_tag_8_20us_20260322_ablation.json`
- lane fixed-step summary：
  - `snn3dexp/analysis/sweeps/windowed_same_tag_8_20us_20260322/fixed_step_sweep_summary.json`
- lane unified surface：
  - `snn3dexp/analysis/codesign_surface/windowed_same_tag_8_20us_20260322/memory_nmc_codesign_surface_summary.json`

这条 lane 当前已经明确给出：

- direct HBM-like：
  - `memory_requests_total = 416`
  - `memory_requests_per_completed_step = 52.0`
  - `stall_on_step_gate_cycles_per_completed_step = 17328.75`
- bundle v3 HBM-like：
  - `memory_requests_total = 1020`
  - `memory_requests_per_completed_step = 127.5`
  - `stall_on_step_gate_cycles_per_completed_step = 13342.75`
- direct monolithic-like：
  - `memory_requests_total = 416`
  - `memory_requests_per_completed_step = 52.0`
  - `stall_on_step_gate_cycles_per_completed_step = 1803.0`

关键机制对照：

- `window bundle vs direct`
  - `memory_requests_total_delta = 604`
  - `router_bundle_v3_rx_total_delta = 258`
  - `tx_bundle_v3_packets_total_delta = 88`
  - `tx_spikekey_v4_packets_total_delta = -364`
  - `gas_scatter_spikes_emitted_total_delta = 48`
  - `stall_on_step_gate_cycles_per_completed_step_delta = -3986.0`
- `window monolithic vs HBM`
  - `memory_requests_total_delta = 0`
  - `stall_on_step_gate_cycles_per_completed_step_delta = -15525.75`
  - ablation 侧同时给出：
    - `vertical_hops_ratio_delta = -0.5`
    - `remote_home_ratio_delta = -0.5`
    - `vertical_link_pressure_delta = -0.29375000000000007`

这说明在这条 same-tag window lane 上：

- `bundle v3` 主要体现为 packetization / router ingress / gather demand 的放大，而不是更低的 memory pressure
- `monolithic-like` 主要体现为 locality 与 vertical pressure 的改善，在这组 lane 上直接反映成大幅更低的 step-gate stall

### 10.4 对下一阶段主线的影响

经过这轮补强，当前最值得继续押注的重点已经更明确：

1. route compare 的“3D 存在性”阶段基本结束，下一步应该把重心继续压到：
   - 真实 synapse/home-stack path
   - `HBM-like NMC` 下的 home placement / remote-home pressure
2. `windowed SNN` 现在已经拥有正式 same-tag lane，因此后续可以更严肃地问：
   - `traffic_mem` 里看到的 route/memory tradeoff，哪些会迁移到真实 synapse/GAS workload
3. memory/NMC 主线现在最值得投入的是：
   - `HBM-like shared stack` 的真实业务流路径细化
   - `bundle vs direct` 对 memory pressure 的 workload 依赖
   - `monolithic-like proxy` 与 `HBM-like NMC` 的 same-workload methodology 对照

换句话说，下一阶段已经不需要再证明：

- `windowed SNN` 能不能跑
- `same-tag lane` 能不能立
- compare surface 能不能统一导出

当前真正值得深入的是：

`memory/NMC + route packetization + workload semantics` 的三维 co-design 解释面。

## 11. 2026-03-22 再次代码对齐后的 3D SNN 全貌

本节补一版更偏“当前代码版图”的收束结论，避免把 3D SNN 继续写成只靠热文档串起来的支线。

### 11.1 现在的 3D SNN 已经有三层同时成立

#### A. `SnnDL/C++` 接口层

当前 `ISynapseRoute -> SpikeCommSubsystem -> SnnWorkload` 已经把 3D multicast 语义抬到接口层：

- `BlockTarget`
  - `block_z`
  - `block_d`
  - `ingress_node`
  - `core_mask`
- `RouteRuntimeStatSinks`
  - `route3d_native_*`
- `SpikeCommSubsystem`
  - 按 `multicastBlockD()` 和 target 的 `block_d` 选择 3D 编码路径

这意味着当前不是“2D 接口 + 3D 实现细节”，而是接口层本身已经承认 3D block 语义。

#### B. `snn3dexp/Python` 平台层

当前 `snn3dexp` 已经把下列维度做成平台原生自变量：

- topology
  - `WxHxZ`
- route
  - `native_3d`
- memory
  - `hbm_like`
  - `monolithic_like`
  - `legacy_per_pe`
- workload
  - `traffic_mem`
  - `snn`
- runtime/control
  - `windowed SNN`
  - `runtime_adaptive`
  - `thermal_guard`

#### C. artifact / export 层

当前平台已经不是“跑出来看一眼日志”，而是有正式导出面：

- `ablation`
- `codesign_surface`
- `phase2_runtime_summary`
- `memory_home_stack_codesign`

因此今天更准确的定位应该是：

- 平台已经具备论文级 artifact/analysis 能力
- 但底层成熟度仍是分层不均衡：
  - route/native 3D 已站住
  - memory/NMC 已进入 compare surface
  - thermal/runtime 已形成 evidence chain
  - controller/home-stack 的细粒度归因仍未完全站住

### 11.2 当前最关键的研究中心已经转到 memory/NMC

把当前代码、artifact 和统一 surface 合起来看，最值得继续投入的方向已经很清楚：

1. `HBM-like shared stack` 下真实业务流路径
   - `PE/NIC -> home stack -> controller/service deficit`
2. `bundle vs direct` 的压力传导
   - 不只是 packet 数变化，而是：
     - home-access 类别迁移
     - hot-stack deficit
     - semantic backlog
3. `monolithic-like proxy vs HBM-like NMC`
   - 同 workload、同 window、同 summary surface 下的机理对照

也就是说，当前的 3D SNN 主线已经不是：

- “3D 能不能跑”

而是：

- “3D route / memory / workload 三者怎样在 home-stack/controller 层耦合”

### 11.3 热侧的角色现在更像约束层，而不是绝对主线

当前热侧最成熟的是：

- HotSpot sidecar contract
- runtime thermal evidence
- paper/runtime export

但它在 3D SNN 主线里的最佳定位仍然是：

- `co-design constraint layer`

而不是马上提升为：

- “先把 HotSpot 完全拉进 execute loop，再谈 memory/NMC”

更现实的顺序仍然应该是：

1. 先把 memory/home-stack/controller 机理讲透
2. 再让 HotSpot evidence 更广泛参与控制决策

### 11.4 一句话收束

当前 `3dsnn` 的全貌可以压缩成一句话：

`SnnDL 已经有接口级 3D multicast 语义，snn3dexp 已经有 topology/route/memory/workload/runtime 的统一平台骨架，下一阶段最该深挖的是 memory/NMC + home-stack/controller co-design，而不是再回到 3D 功能存在性证明。`
