# SNN 3D Chip Next-Step Architecture Modeling Design

Date: 2026-03-22
Owner: Fufu
Status: Code-aligned refresh after `fixed_step_window_route_memory` / `hotspot_real_phase9_independent_proxy_20260320_224300` / overlay-rich unified surface / `codesign_refresh` paper export / `codesign_canonical_20us` / default inferred paper export / `codesign_single_20us_20260322` / `controller_runtime_refresh_20260322_windowed_snapshot_stop_overlap` / `controller_runtime_refresh_20260322_windowed_snapshot_real_home_flow`

Note:
`2026-03-23` 的最新代码对齐刷新见 `docs/plans/nextarc/2026-03-23-3d-snn-status-refresh-and-nextarc.md`。
本文保留为 `2026-03-22` 时点的历史快照。

## 1. 文档目的

这份文档不是重复描述“当前平台已经有什么”，而是回答：

1. 在当前代码真实状态下，下一阶段最值得投入的体系结构主线是什么。
2. 哪些方向虽然重要，但当前不应抢占主线。
3. 为什么新的优先级顺序应当是：
   - `以 memory/NMC + co-design 为主线统一 compare surface`
   - `route kernel 从 edges_csv / legacy bootstrap 走向 synapse-native`
   - `把 HotSpot evidence 推进到 thermal-aware execute loop`

## 2. 一页结论

当前平台已经具备：

- 真实 `3D SST object graph`
- 真实 `native route interface + native fanout path + volumetric block targets`
- 真实 `HBM-like / monolithic-like / legacy_per_pe` memory 建模
- 真实 `traffic_mem` 与 `windowed SNN` 两类 processing path
- 真实 `route_memory_joint / stack_nmc / phase2_case_summary / fixed-step sweep`
- 真实 `thermal proxy + RC replay/state + HotSpot sidecar + runtime execute v1`

这轮已经完成五个关键转折：

1. `windowed SNN` 与 `full_3d_snn_window_monolithic_proxy` 的 fresh smoke 已刷新到 `arc4_refresh_20260321`，并正式进入 `arc4_baseline_compose_20260321` 的 9-case baseline suite。
2. `runtime_adaptive` 已落地第一版 `window` 级 executable control，`runtime_control_next_window.json` 会产出 applied weights 与 next-window params。
3. `route3d` native bootstrap 已不再只依赖 `edges_csv` gating，额外支持从 legacy route tables bootstrap native 3D routes。
4. `fixed_step_window_route_memory` sweep 已闭环，`4/8/16-step × baseline/sp64 × direct/bundle/monolithic` 的对照已进入统一 summary/csv/artifact surface。
5. canonical traffic/memory baseline 已经从 `manifest-driven mixed-tag` 前进到 `single-tag fresh run`，`codesign_single_20us_20260322` 下的 `10` 个 case 全部 `smoke_passed`，`memory_only_3d` / `noc_only_3d` / `noc_only_3d_bundle_fault_v3` 也首次进入同 tag fresh runtime evidence。

因此，下一阶段已经不该继续写成“把这几个功能做出来”，而应收敛成三个新的明确目标：

1. 用 `9-case baseline suite + fixed-step windowed SNN sweep` 统一 memory/NMC compare surface。
2. 跑出第一份非 `edges_csv` 的 fresh route evidence，把 route kernel 继续推向更真实的 `synapse/BCSR/GAS` source semantics。
3. 让 HotSpot-enabled canonical evidence 成为 runtime execute loop 的正式热约束输入，而不是只停在 artifact 层。

当前不建议优先押注的方向包括：

- 继续优先扩论文 artifact
- 直接做 per-cycle thermal-aware control
- 过早做更细的工艺/封装 realism
- 在 route 面继续扩很多 packet/router feature，而不先补 memory/NMC 与 source semantics 主语义缺口

## 3. 当前代码对齐后的基线判断

### 3.1 route 面已经不是“只有 3D transport”

当前必须明确：

- `SynapseRouteSubsystem3D` 已有 native route bootstrap
- `computeFanoutNative3D_()` 已使用本地 native route table，而不是再回到 legacy provider 主路径
- `computeMulticastTargetsNative3D_()` 已按真实 `WxHxD` volumetric block 输出 target
- `route3d_native_*` structured runtime stats 已能正式进入：
  - `sst_stats.csv`
  - `phase2_case_summary.route_kernel`

所以 route 面的剩余缺口，不再是“把 computeFanout 从 legacy provider 解耦出来”，而是：

- 把 native route kernel 从 `edges_csv` 预物化 source routes 推进到更真实的 `synapse-native` source semantics

### 3.2 memory paradigm 已经是平台原生自变量

当前 `mesh3d_template/spec.py` 已正式支持：

- `legacy_per_pe`
- `hbm_like`
- `monolithic_like`

并且：

- builder
- SST graph
- analyzers
- phase2 summary

都已消费这组 memory paradigm。

这意味着下一阶段讨论 memory/NMC 时，不需要再把它当作 side experiment，而可以直接把它当作平台原生建模维度。

### 3.3 `windowed SNN` 已经进入 canonical baseline suite，并具备 fixed-step quantification

当前 `windowed SNN` 路径已经有：

- case spec
- `workload_impl = "snn"`
- `GatherBufferIF`
- `GlobalGasStepController`
- weight/GAS/semantic counters

而且当前已经有：

- `full_3d_snn_window/arc4_refresh_20260321`
- `full_3d_snn_window_monolithic_proxy/arc4_refresh_20260321`
- `full_3d_snn_window_bundle_v3`
- `PHASE2_BASELINE_CASES = 9`
- `task_fixed_step_{4,8,16}_{10,20,40}us`
- `task_fixed_step_{4,8,16}_{10,20,40}us_sp64`

但当前平台最成熟的 compare anchor 仍是 `traffic_mem`，而 `windowed SNN` 已开始拥有自己的定量 compare surface。

因此真正的 gap 不再是“没有 SNN path”或“没有 fresh artifact”，而是：

- 缺把 `traffic_mem`、`windowed SNN baseline`、`windowed SNN fixed-step sweep` 放进同一批处理入口的稳定 methodology
- 缺把 `direct_v4 / bundle_v3 / monolithic_like` 差异解释到 memory/NMC 机理层

### 3.4 runtime/thermal/physical 已经够做约束层，但主缺口转向 HotSpot-in-loop

当前已经有：

- runtime executable control v1
- thermal proxy / RC state / HotSpot sidecar
- physical proxy v2

它们已经足以作为：

`co-design constraints`

但当前还不适合作为第一主线的原因已经变成：

- route/memory/workload 主语义仍在继续原生化
- HotSpot sidecar 已经进入 canonical artifacts，但尚未成为更广泛 execute loop 的正式输入

## 4. 当前最关键的三个缺口

### Gap A: native route kernel 仍主要依赖 `edges_csv` fresh evidence

今天的 route gap 已经应当被重新表述为：

- native 3D route path 已存在
- `legacy route tables -> native route3d` bootstrap 也已具备合同级支持
- 但当前 fresh artifact 仍主要从 `mapping_edges_file` 读入预物化 source routes
- 还没有成为真实 `synapse/weight/BCSR/GAS` source semantics 的默认内核

这个缺口之所以关键，不是因为 route feature 本身还不够多，而是因为：

- 后续所有 `route-memory overlap`
- `die_local / inter_die`
- `vertical subtree cost`
- `home-route co-design`

都希望建立在更真实的 source semantics 上。

### Gap B: memory/NMC compare methodology 已统一到主 surface，但机理解释仍不够深入

当前 `windowed SNN` 的代码路径、fresh artifact、fixed-step sweep 与 `traffic_mem` canonical baseline 已经真实合流到同一个导出面；但 methodology 上仍有三个待深化缺口：

- `traffic_mem` 与 `windowed SNN` 还缺统一的“机理解释层”，而不只是同表落数
- `HBM-like vs monolithic-like` 还需要从 `memory_requests_total / service_deficit / vertical_link_pressure` 一起解释
- `direct_v4 vs bundle_v3` 的 fixed-step结果已经落表，但 `traffic_mem` same-tag fresh baseline 还需要继续拆到 bundle/router/semantic backlog 链路

这个缺口的重要性甚至高于 route feature 继续扩写，因为它直接决定：

- 当前 3D substrate 的研究结论能否迁移到真实 SNN 业务窗口
- 当前 memory/NMC 解释能否从“现象”推进到“机理”

### Gap C: 热侧已经不缺 canonical artifacts，缺的是 control integration

当前 fresh canonical cases 已经能根据：

- `route_memory_overlap`
- `vertical_link_pressure`
- `stack_hotspot_penalty`

导出：

- `thermal_hotspot_score`
- `vertical_link_pressure`
- `stack_hotspot_penalty`

并且 `runtime_adaptive` 已经能把：

- `rebalance_home_route`
- `raise_vertical_penalty`

执行到下一窗口行为。

但当前缺口变成：

- 真实 steady-state temperature outputs 虽然已经进入 canonical compare surface
- 但 runtime execute loop 目前仍主要依赖 proxy/joint thermal signals
- HotSpot 还没有成为更广泛 case 的正式控制输入

## 5. 下一阶段的推荐目标

### Goal 1: Unified memory/NMC compare surface

把已经落地的 `9-case baseline suite + fixed-step windowed SNN sweep` 真正变成统一 compare surface。

这一步要实现的不是更多 case，而是更强的 compare 叙事：

- `traffic_mem` 负责稳定对照和压力扫描
- `windowed SNN` 负责真实 synapse/GAS 语义验证
- `fixed-step windowed SNN` 负责 direct/bundle/monolithic 的 memory/NMC 机理拆解
- 三者共享尽可能一致的 compare surface

完成后，平台才能更可信地回答：

- `home_access_class -> service_deficit`
- `HBM-like vs monolithic-like`
- `route compression -> memory pressure shift`
- `bundle replay / re-materialization -> memory amplification`

这些结论是否能迁移到真实 SNN 业务路径。

#### 2026-03-22 进展刷新

这一目标的“统一入口”已经不是待做项，而是已经在 `snn3dexp` 内形成了可复用导出面：

- 已新增 `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
- 输入面已经统一到三类真实 artifact：
  - `ablation_summary_balanced_20us.json`
  - `fixed_step_sweep_summary.json`
  - 可选 `phase2_runtime_summary.json`
- 输出面已经统一到：
  - `memory_nmc_codesign_surface_summary.json`
  - `memory_nmc_codesign_surface.csv`
  - `memory_nmc_codesign_surface.md`
- fresh 实际产物已经生成在：
  - `snn3dexp/analysis/codesign_surface/balanced_20us/`

这意味着 P1 当前已经从“缺统一 compare/export entry”前进到“已有统一 compare/export entry，但还需要继续充实指标和机理解释”。

当前这张 unified surface 已经能同时落表：

- `10` 条 `traffic_mem` baseline rows
- `2` 条 `traffic_mem` compare rows
- `9` 条 `windowed SNN default fixed-step rows`
- `6` 条 `bundle vs direct` fixed-step rows
- `6` 条 `monolithic vs HBM` fixed-step rows
- `9` 条 `spike sensitivity` rows
- `HotSpot threshold profile + runtime adaptive deltas`

并且 P1 在 2026-03-22 这轮已经进一步前进了半步：

- unified surface 现在支持 `baseline_overlay_ablation`
  - 可以用 richer `traffic_mem` ablation 为缺少 `route_memory_joint_summary` 的 baseline case 回填
    `traffic_driven_runtime / home_access_pressure / access_semantics`
- `phase2 paper artifacts` 导出链现在也可以可选挂接 unified surface
  - 使 `phase2_runtime_summary.json` 直接带出
    `memory_nmc_codesign_surface_summary/csv/md`
- overlay-rich fresh surface 已经真实导出在：
  - `snn3dexp/analysis/codesign_surface/balanced_20us_overlay_perf20/`
  - 当前 row 规模已经稳定到：
    - `traffic_mem_baseline_rows = 10`
    - `traffic_mem_compare_rows = 2`
    - `window_baseline_rows = 9`
    - `window_bundle_breakdown_rows = 6`
    - `window_memory_model_breakdown_rows = 6`
    - `window_spike_sensitivity_rows = 9`
- richer baseline 的关键语义已经直接落到真实 `traffic_mem` baseline row：
  - `full_3d`
    - `route_semantic_overlay_applied = true`
    - `route_semantic_overlay_run_tag = perf_20us_route_refresh_v2`
    - `metadata_lookup_demands = 20000`
    - `synapse_gather_demands = 40000`
    - `stream_region_demands = 40000`
    - `writeback_region_demands = 20000`
    - `dominant_home_access_class = remote_home`
    - `remote_home_access_ratio = 0.5`
- `traffic_mem_bundle_vs_direct` 在 overlay compare row 上也已经出现新的机理信号：
  - `memory_requests_total_delta = 0`
  - `total_service_deficit_delta = 207522`
  - 这说明 richer baseline 下更需要追问的是 `bundle` 如何放大 service deficit，而不是只盯着 request amplification
- `codesign_refresh` paper artifact 已形成可复用的一体化导出：
  - `memory_nmc_codesign_surface.available = true`
  - `traffic_mem_baseline_row_count = 4`
  - `traffic_mem_compare_row_count = 2`
  - `window_baseline_row_count = 9`
  - `window_bundle_breakdown_row_count = 6`
  - `window_memory_model_breakdown_row_count = 6`
  - `window_spike_sensitivity_row_count = 9`
- 2026-03-22 这轮又前进了一步：
  - 已新增 canonical manifest：
    - `snn3dexp/configs/run_tag_manifests/codesign_canonical_20us.json`
  - 已生成 canonical mixed-tag baseline ablation：
    - `snn3dexp/analysis/codesign_canonical_20us_ablation.json`
  - 已生成不依赖 overlay 的 unified surface：
    - `snn3dexp/analysis/codesign_surface/codesign_canonical_20us/`
  - 这张 fresh surface 已确认：
    - `traffic_mem_baseline_rows = 10`
    - `traffic_mem_compare_rows = 2`
    - `window_baseline_rows = 9`
    - `window_bundle_breakdown_rows = 6`
    - `window_memory_model_breakdown_rows = 6`
    - `window_spike_sensitivity_rows = 9`
    - `full_3d.route_semantic_overlay_applied = false`
    - `full_3d.metadata_lookup_demands = 20000`
    - `full_3d.synapse_gather_demands = 40000`
    - `full_3d.stream_region_demands = 40000`
    - `full_3d.writeback_region_demands = 20000`
    - `full_3d.dominant_home_access_class = remote_home`
    - `full_3d.remote_home_access_ratio = 0.5`
    - `traffic_mem_bundle_vs_direct.memory_requests_total_delta = 0`
    - `traffic_mem_bundle_vs_direct.total_service_deficit_delta = 207522`
  - `export_phase2_paper_artifacts.py` 也已支持默认推断 fixed-step summary 路径：
    - 当 `ablation_json` 位于 canonical `analysis/` 目录下时，会自动探测
      `analysis/sweeps/fixed_step_window_route_memory/fixed_step_sweep_summary.json`
    - fresh 真实导出：
      - `snn3dexp/analysis/paper_artifacts/codesign_canonical_20us_default_export/phase2_runtime_summary.json`
    - 其中：
      - `memory_nmc_codesign_surface.available = true`
      - `traffic_mem_baseline_row_count = 10`
      - `traffic_mem_compare_row_count = 2`
      - `window_baseline_row_count = 9`
      - `window_bundle_breakdown_row_count = 6`
      - `window_memory_model_breakdown_row_count = 6`
      - `window_spike_sensitivity_row_count = 9`
- 2026-03-22 这轮最终又把 canonical baseline 真正推到了 fresh same-tag 口径：
  - 已新增 single-tag manifest：
    - `snn3dexp/configs/run_tag_manifests/codesign_single_20us_20260322.json`
  - 已跑通 `10` 个 same-tag fresh smoke case：
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
  - `platform/sst_graph.py` 也已补齐 `noc_only_3d` smoke 的真实 3D route payload 语义：
    - volumetric block 的 bundle v1 wrapper 现在承载 `WireSpikeKeyV4`
    - 不再把 3D block 错误编码成 2D `WireSpikeKeyV2`
  - 已生成 fresh same-tag ablation：
    - `snn3dexp/analysis/codesign_single_20us_20260322_ablation.json`
  - 已生成 fresh same-tag unified surface：
    - `snn3dexp/analysis/codesign_surface/codesign_single_20us_20260322/`
    - 其中：
      - `traffic_mem_baseline_rows = 10`
      - `traffic_mem_compare_rows = 2`
      - `window_baseline_rows = 9`
      - `window_bundle_breakdown_rows = 6`
      - `window_memory_model_breakdown_rows = 6`
      - `window_spike_sensitivity_rows = 9`
    - `traffic_mem_bundle_vs_direct` compare row 仍然给出：
      - `memory_requests_total_delta = 0`
      - `total_service_deficit_delta = 207522`
    - `traffic_mem_monolithic_vs_hbm` compare row 则新增了更可信的 same-tag 机理差异：
      - `memory_requests_total_delta = 101184`
      - `total_service_deficit_delta = -50598`
      - `vertical_link_pressure_delta = -0.03820184426229509`
  - same-tag paper export 也已 fresh 导出：
    - `snn3dexp/analysis/paper_artifacts/codesign_single_20us_20260322_default_export/phase2_runtime_summary.json`
    - 其中：
      - `memory_nmc_codesign_surface.available = true`
      - `traffic_mem_baseline_row_count = 10`
      - `traffic_mem_compare_row_count = 2`
      - `window_baseline_row_count = 9`
      - `window_bundle_breakdown_row_count = 6`
      - `window_memory_model_breakdown_row_count = 6`
      - `window_spike_sensitivity_row_count = 9`
      - `hotspot_runtime_run_tag = codesign_single_20us_20260322`
  - thermal input 准备链也第一次完全 same-tag 化：
    - `prepared_manifest.case_ids = [full_3d, full_3d_runtime_adaptive, full_3d_thermal_guard]`
    - 三者的 `run_tags_by_case` 都统一为 `codesign_single_20us_20260322`

其中最关键的几个 fresh 结论已经直接体现在 unified surface 上：

- `bundle vs direct` 在 `4-step/default` 下的 `memory_requests_total_amplification_ratio = 2.451923076923077`
- `bundle vs direct` 在 `4-step/sp64` 下放大到 `3.076923076923077`
- `monolithic vs HBM` 在 `4-step/default` 下 `memory_requests_total_delta = 0`，但 `stall_on_step_gate_cycles_per_completed_step_delta = -23686.5`
- `HotSpot` 侧已经能在同一导出面上看到 `runtime_adaptive_vs_thermal_guard.vertical_link_pressure_delta = 0.09375`

因此 Goal 1 的剩余工作不再是“有没有 unified surface”，而是：

- 继续补齐 `traffic_mem` 行的 route/memory demand richness
- 把 `bundle vs direct` 的 `service_deficit` 放大继续拆到 router/bundle/semantic backlog 链
- 把 `monolithic vs hbm` 的 same-tag 差异继续拆到 locality / vertical-hop / controller-pressure
- 继续把 unified surface 的默认导出链从“canonical 路径自动推断”扩展到更广的 paper/doc export 场景
- 把 surface 上的现象解释进一步推进成 memory/NMC 机理叙事

### Goal 2: Route kernel proof beyond `edges_csv` / legacy bootstrap

当前不是从零做 route kernel，而是在已存在 native 路径之上继续推进：

- 从 `edges_csv` / legacy route-table bootstrap
- 推进到更真实的 `synapse/weight/BCSR/GAS` source semantics

同时建议新增更原生的 runtime observability：

- `die_local_replication`
- `inter_die_replication`
- `vertical_subtree_depth`
- `ingress_replication_cost`
- gating-dominant runtime counters

### Goal 3: Thermal-aware execute loop on top of canonical HotSpot evidence

当前最需要补的不是“有没有 HotSpot”，而是把 execute loop 放到更真实的热语义地面上。

建议路线不是 per-cycle，而是：

- `epoch`
- `window`
- `global-step batch`

在这个粒度上，建议逐步完成：

- 让 execute loop 同时记录 proxy thermal 与 HotSpot thermal evidence
- 再把 `raise_vertical_penalty` / `rebalance_home_route` 推广到更多 case
- 决定哪些 case 继续用 proxy 驱动，哪些 case 需要 HotSpot 参与决策

并记录：

- 本窗口是否执行
- 执行前后的 mapping/home/route 参数
- 下一窗口的 overlap/deficit/stall/thermal 变化

## 6. 当前明确的非目标

当前阶段不建议优先做：

- HotSpot 直接嵌入 SST 主循环
- per-cycle thermal-aware control
- fabrication-accurate TSV/MIV/封装仿真
- 为论文 artifact 单独拉出主线
- route 面继续横向扩很多 packet/router feature

这些方向都不是没价值，而是不应抢占当前最关键的主语义建模资源。

## 7. 推荐的推进顺序

### Batch 1: Canonical Artifact Refresh

状态：`已完成`

结果：

- `arc4_refresh_20260321`
  - `full_3d_runtime_adaptive`
  - `full_3d_snn_window`
  - `full_3d_snn_window_monolithic_proxy`
  - `full_3d_thermal_guard`
- `arc4_baseline_compose_20260321`
  - 9-case baseline suite

### Batch 2: Unified Compare Surface

状态：`已完成第二版，并已进入 controller/home-stack/provenance 机理层`

目标：

- 让 `traffic_mem` / `windowed SNN` / `fixed-step windowed SNN` 共用 compare/export entry
- 让 memory/NMC 结论能在 baseline suite 与 sweep surface 上稳定落表

截至当前代码，Batch 2 已经不只是“统一导出入口”，而是新增了三层新的可解释性：

1. `controller/home-stack overlap tiering`
   - `same_stack_overlap`
   - `same_controller_overlap`
   - `same_class_overlap`
   - `runtime_controller_home_access_class`
   - `home_region_joint_attribution`
2. `long stop-window surface`
   - `window_stop_baseline_rows`
   - `window_stop_compare_rows`
   - 可以直接对比 `2us / 10us / 20us`
3. `real home-traffic provenance + transfer kind`
   - `real_synapse_source_count`
   - `real_home_traffic_signal_level`
   - `runtime_alignment_evaluable`
   - `runtime_pressure_transfer_kind`

这意味着 Batch 2 的成功标准已经可以从：

- “有没有 unified compare surface”

升级为：

- “这张 surface 能不能解释 dominant home traffic 与 runtime hottest controller 到底如何迁移”

最新 fresh 证据已经给出两个非常关键的 next-step 信号：

- `traffic_mem`
  - 三个主 case 都已到 `real_home_traffic_signal_level = runtime_controller`
  - 说明当前平台已经不是 proxy-only compare，而是进入真实 `home-traffic -> runtime controller` 证据面
- `window_stop_bundle_vs_direct`
  - `2us`: bundle 仍未对齐
  - `10us/20us`: bundle 转为 `aligned_same_controller`
  - direct 仍停在 `cross_class_transfer`

所以从现在开始，Batch 2 的真正下一步不是“继续加 row”，而是：

- 把 `bundle/direct/monolithic` 的差异统一解释为：
  - `traffic amplification`
  - `step progress`
  - `controller hotspot transfer kind`
  三者之间的关系

### Batch 3: Route Kernel Proof Beyond `edges_csv`

目标：

- 跑出第一份 `native_bootstrap_source != edges_csv` 的 fresh runtime artifact
- 再继续推进更真实 source semantics 与 richer runtime route metrics

### Batch 4: Memory/NMC Mechanism Decomposition

目标：

- 把 `bundle_v3` 的 amplification 沿
  - `router_bundle_v3_rx`
  - `tx_bundle_v3`
  - `gas_scatter`
  - `gather/stream/writeback`
  做成统一链路分解
- 把 `HBM-like vs monolithic_like` 的差异继续拆到 locality / vertical-hop / gate-wait 归因

在当前代码基线下，Batch 4 的主问题还需要进一步收窄成两条更具体的主线：

1. 为什么 `direct` 在 fresh surface 上长期表现为：
   - `cross_class_transfer`
   - `runtime_class_unresolved`
2. 为什么 `bundle` 会在 `2us -> 10us` 之间从：
   - `runtime_class_unresolved`
   跃迁到：
   - `aligned_same_controller`

这意味着 Batch 4 不应再写成泛泛的“深挖 memory/NMC 机理”，而应明确聚焦：

- `home_access_class`
- `dominant_pressure_region`
- `runtime hottest stack/controller`
- `step progress`
- `memory amplification`

这五个变量之间的因果关系

### Batch 5: Runtime Control Widening

目标：

- 在 thermal-enabled cases 上扩大 execute loop 覆盖面
- 让 HotSpot evidence 逐步进入 runtime control decision surface

## 8. Done Definition

当下面三件事同时成立时，可以认为当前 next arc 的主任务基本完成：

1. `arc4_baseline_compose_*` 与 fixed-step sweep 已能稳定产出 `traffic_mem / windowed SNN / bundle/direct/monolithic` 的统一 compare surface。
2. 至少有一个 fresh case 跑出 `native_bootstrap_source != edges_csv` 的真实 runtime artifact。
3. 至少有一个 fresh canonical thermal-enabled case 把真实 HotSpot 结果与 execute loop 放在同一证据面上。

到那时，平台才真正从：

`3D-aware co-design platform`

进一步推进到：

`more realistic 3D SNN chip architecture model`

## 9. 最终建议

下一阶段最该押注的一句话是：

`先把 unified compare surface 推到 real home-traffic provenance + transfer-kind 层，讲透 direct/bundle/monolithic 为何把热点迁移到不同 controller，再跑出非 edges_csv 的真实 route evidence，最后让 HotSpot 正式进入 thermal-aware execute loop。`

## 10. 2026-03-22 补充刷新：高负载 surface 与 cross-surface 机理报告

上面的表述在今天之前是成立的，但按当前代码与 fresh artifact 再对齐一次后，Batch 2 / Batch 4 的状态还需要再前进一步。

因为“把 unified compare surface 推到 real home-traffic provenance + transfer-kind + controller-runtime 层”这一步，现在不只是补到了高负载，而且已经完成了 stale artifact root-cause 修复。

新的高负载 surface 应该以 refreshed 版本为准：

- `snn3dexp/analysis/codesign_surface/codesign_single_20us_20260322_runtime_evidence_refresh/`
- `snn3dexp/analysis/codesign_surface/perf_20us_route_nmc_compare_runtime_evidence_refresh/`

背后的关键支撑是共享刷新链：

- `snn3dexp/tools/route_memory_joint_loader.py`
- `snn3dexp/tools/analyze_ablation.py`
- `snn3dexp/tools/export_memory_nmc_codesign_surface.py`

它修复了两类 legacy artifact 被重复消费的问题：

1. 旧 `route_memory_joint_summary.json`
   - 缺 `home_stack_controller_proxy`
   - 缺 `real_controller_pressure`
   - 缺 `processing_runtime_mode`
2. 旧 `memory_summary.json`
   - 缺 `controller_reports/controller_summary`

所以今天之后，Batch 2 的事实基础已经改变了：

1. 低负载 surface
   - `full_3d/full_3d_tile_bundle_v3/full_3d_monolithic_proxy`
   - 仍然是 `real_home_traffic_signal_level = runtime_controller`
2. refreshed 高负载 `codesign_single_20us_20260322`
   - 相同主 case 也都是 `real_home_traffic_signal_level = runtime_controller`
   - `real_controller_pressure_available_from_summary = true`
   - `processing_runtime_mode = traffic_semantic`
   - `active_controller_count = 16`
3. refreshed 高负载 `perf_20us_route_refresh_v2`
   - 相同主 case 同样保持 `runtime_controller`
   - 没有出现此前文档里写过的 `home_pressure` 退化

同步新增的 cross-surface 机理报告链：

- `snn3dexp/tools/export_transfer_kind_mechanism_report.py`
- `snn3dexp/analysis/transfer_kind_mechanism/controller_runtime_refresh_20260322_vs_codesign_single_20us_runtime_evidence_refresh_vs_perf_20us_runtime_evidence_refresh/`

它现在给出的不是“退化”，而是“稳定保持 runtime-controller，同时压力规模上升”：

1. `full_3d`
   - `runtime_controller -> runtime_controller`
   - `runtime_class_unresolved -> runtime_class_unresolved`
   - `memory_requests_total_delta = +55492`
   - `total_service_deficit_delta = +89189`
2. `full_3d_tile_bundle_v3`
   - `runtime_controller -> runtime_controller`
   - `transition_kind = stable`
   - `codesign_single` 下 `total_service_deficit_delta = +291436`
3. `full_3d_monolithic_proxy`
   - `runtime_controller -> runtime_controller`
   - `cross_class_transfer -> cross_class_transfer`
   - `transition_kind = stable`

因此，Batch 2 不该再定义成：

- “继续把 provenance/transfer-kind 带到高负载”
- 也不该定义成“解释为什么 high-load 会退回到 home-pressure”

更准确的升级版定义应该是：

- `Batch-Mechanism-Closure`
  - 目标：在 high-load 也已经稳定保留 `runtime_controller` 的前提下，讲清 direct/bundle/monolithic 如何改变 controller hotspot、home-access class 与 service deficit

对应地，Batch 4 的重心也应从“恢复 controller evidence”切到两个更真实的问题：

1. `runtime_class_unresolved` 为什么在 direct / bundle 路线上仍未被机理拆穿
2. `cross_class_transfer` 为什么在 monolithic proxy 上跨 low-load 与 high-load 都保持稳定

这也意味着下一阶段的最优投入点已经更明确了：

- 一条是高负载 long-window / stop-window 线
  - 用来验证 bundle 在高压下是否也会收敛到 `aligned_same_controller`
- 一条是 memory/NMC mechanism 线
  - 目标不是再救 proxy 字段
  - 而是把 controller hotspot、dominant home class、region backlog、transfer kind 讲成同一条 co-design 机理链

## 11. 2026-03-22 补充刷新：controller explainability loss 现已成为独立 Batch

在 10 节的 high-load refresh 之后，当前 nextstep 设计可以再明确一步：

- 我们已经不再需要把 high-load 主问题定义成 `runtime_controller -> home_pressure_only`
- explainability 报告链现在更适合作为 regression guard，而不是主诊断 Batch

新增工具与产物：

- `snn3dexp/tools/export_controller_explainability_loss_report.py`
- `snn3dexp/tests/test_controller_explainability_loss_report.py`
- `snn3dexp/analysis/controller_explainability_loss/controller_runtime_refresh_20260322_vs_codesign_single_20us_runtime_evidence_refresh_vs_perf_20us_runtime_evidence_refresh/`

这条链给出的结论，比 10 节里的 transfer-kind 机理报告更细一层：

1. low-load reference
   - `full_3d/full_3d_tile_bundle_v3/full_3d_monolithic_proxy`
   - 都是 `explainability_level = runtime_controller`
2. refreshed `codesign_single_20us_20260322`
   - 同一批 case 仍然保持：
     - `explainability_level = runtime_controller`
     - `controller_explainable = true`
3. refreshed `perf_20us_route_refresh_v2`
   - 同一批 case 也保持：
     - `explainability_level = runtime_controller`
     - `controller_explainable = true`
4. 整体 transition 结果
   - `explainability_loss_rows = 0`
   - `loss_reason_rows = 0`
   - 主 case 全部是 `explainability_transition = stable`

因此，Batch 2/Batch 4 现在最合适的合并表述已经不是：

- “恢复 high-load explainability”

而是：

- `Batch-Explainability-Guard`
  - 目标：把 refreshed surface 的 `runtime_controller` explainability 稳定性固化成默认分析基线，防止旧 artifact 再次污染结论

这个 Batch 的第一优先级，现在可以拆成三个很具体的子任务：

1. `default-surface hygiene`
   - 确保 paper/export/default summary 链优先消费 refreshed surface，而不是旧 artifact
2. `stale-artifact regression test`
   - 继续把 legacy `route_memory_joint_summary.json + memory_summary.json` 的刷新覆盖写进测试与默认加载器
3. `explainability CI`
   - 把 `explainability_loss_rows = 0` 固化成主 case 的预期，而不是只人工检查 markdown

这会直接改变下一阶段的架构建模优先级：

- 第一优先级不再是“多扩几个 compare surface”
- 而是把 `controller explainability guard + runtime-controller mechanism closure` 视作 memory/NMC co-design 进入论文级架构模型前的最后一层 runtime closure

## 12. 2026-03-22 补充刷新：default export bridge 现在也站到 refreshed runtime evidence 上

在 10/11 两节把 refreshed surface 和 explainability guard 补齐之后，默认 paper/export 链这一步也已经从“待统一”推进到了“已桥接”。

新增的默认发现能力现在在：

- `snn3dexp/tools/export_phase2_paper_artifacts.py`

它会在导出 `phase2 paper artifacts` 时自动补两类输入：

1. refreshed baseline overlay
   - 自动发现 sibling `*_ablation_runtime_refresh.json`
2. stop-window ablation
   - 自动发现：
     - `windowed_<run_tag>_ablation.json`
     - `<run_tag>_windowed_ablation.json`

同时，这些默认发现的输入现在会正式落进 `phase2_runtime_summary.json`：

- `memory_nmc_codesign_surface.sources.baseline_overlay_ablation_paths`
- `memory_nmc_codesign_surface.sources.stop_window_ablation_paths`
- `memory_nmc_codesign_surface.window_stop_baseline_row_count`
- `memory_nmc_codesign_surface.window_stop_compare_row_count`

这条桥接现在已经有三组真实 artifact：

1. low-load default refresh
   - `snn3dexp/analysis/paper_artifacts/controller_runtime_refresh_20260322_windowed_snapshot_default_refresh/`
   - 已自动带入：
     - `stop_window_ablation_paths = [windowed_controller_runtime_refresh_20260322_ablation.json]`
     - `window_stop_baseline_row_count = 3`
     - `window_stop_compare_row_count = 2`
2. high-load default bridge: `codesign_single`
   - `snn3dexp/analysis/paper_artifacts/codesign_single_20us_20260322_default_export_runtime_refresh_bridge/`
   - 已自动带入：
     - `baseline_overlay_ablation_paths = [codesign_single_20us_20260322_ablation_runtime_refresh.json]`
   - 主 case 仍保持：
     - `real_home_traffic_signal_level = runtime_controller`
     - `real_controller_pressure_available_from_summary = true`
3. high-load default bridge: `perf_20us`
   - `snn3dexp/analysis/paper_artifacts/perf_20us_route_nmc_compare_default_export_runtime_refresh_bridge/`
   - 已自动带入：
     - `baseline_overlay_ablation_paths = [perf_20us_route_nmc_compare_ablation_runtime_refresh.json]`
   - 主 case 同样保持：
     - `real_home_traffic_signal_level = runtime_controller`
     - `real_controller_pressure_available_from_summary = true`

这会把 Batch 的边界进一步压实：

- `Batch-Explainability-Guard`
  - 已经不只守住 `surface/report`
  - 还开始守住 `phase2 paper/default export`

因此下一阶段不该再把主要精力花在“默认导出链会不会读到旧 artifact”。

更值得继续投入的是：

1. high-load long-window / stop-window 真正跑起来
2. 在已稳定的 `runtime_controller` 证据面上，解释：
   - direct / bundle / monolithic 为什么把热点压到不同 controller/class
   - 以及为什么 service deficit 的放大量级差异这么大

## 13. 2026-03-23 补充刷新：P1 已从 fixed-step unified surface 前进到 high-load stop-window bridge

这一轮之后，`Goal 1: Unified memory/NMC compare surface` 的状态需要明确更新。

它不再只是：

- `traffic_mem + fixed-step windowed SNN`

而是已经推进到：

- `traffic_mem + fixed-step windowed SNN + high-load long-window/stop-window`

三者共同进入统一 surface / export / mechanism report。

新增的代码与 artifact 事实有四个：

1. 新增 multicase stop-window runner
   - `snn3dexp/tools/run_window_stop_multicase_sweep.py`
   - `snn3dexp/tests/test_window_stop_multicase_sweep.py`
   - 它把 `direct / bundle / monolithic` 多 case stop-window sweep 标准化成：
     - 统一 `summary`
     - 每个 `stop_at` 一份 `run_tags_by_case` manifest
2. `export_phase2_paper_artifacts.py` 现在除了 sibling `windowed_*` 文件外，也能识别：
   - `long_window_ablation_<run_tag>/window_stop_*_ablation.json`
3. high-load 真实 stop-window ablation 已经进入 bridge surface：
   - `codesign_single_20us_20260322_default_export_runtime_refresh_bridge`
     - `window_stop_baseline_row_count = 9`
     - `window_stop_compare_row_count = 6`
   - `perf_20us_route_nmc_compare_default_export_runtime_refresh_bridge`
     - `window_stop_baseline_row_count = 9`
     - `window_stop_compare_row_count = 6`
4. fresh cross-surface mechanism 报告已经给出一致结论：
   - `bundle_convergence.convergence_detected = true`
   - `earliest_aligned_stop_at = 10us`
   - `2us` 仍是 `runtime_class_unresolved`
   - `10us / 20us` 已收敛到 `aligned_same_controller`

这会改变 P1 的工作定义。

之前的 P1 还可以写成：

- “把 long-window / stop-window 真正补出来”

现在更准确的表述已经变成：

- “把已有 long-window / stop-window 证据从 bridge 级闭环继续推进成标准化 fresh 生成范式，并把机理解释压到真正的 memory/NMC 数据通路上”

因此，下一阶段的优先级顺序应该进一步收敛为：

1. `P1-A fresh stop-window standardization`
   - 用 `run_window_stop_multicase_sweep.py` 直接生成 future same-tag stop-window family
   - 降低当前对 `direct_stop_sweep_* / bundle_stop_sweep_* / monolithic_stop_sweep_*` 历史命名的依赖
2. `P1-B real HBM-like NMC dataflow`
   - 把分析重点从“surface 上已经能看到 stop-window 收敛”继续下沉到：
     - `PE/NIC -> home stack`
     - `synapse/home-stack`
     - `controller hotspot / stack skew`
   - 也就是把 high-load stop-window 结果和真实 near-memory data path 建得更紧
3. `P1-C explicit bridge contract`
   - 如果 high-load bridge 将长期需要引用 controller-runtime long-window 证据
   - 这层 linkage 最终应提升成显式 contract，而不是长期依赖手工 CLI 注入 stop-window ablation paths

这也意味着当前平台的主阻塞已经不再是：

- route 面功能还不够
- 或 stop-window artifact 还没跑出来

而是已经转成：

- 如何把 `route -> memory -> controller` 的统一机理链下沉到更真实的 NMC 数据通路
- 以及如何把这种 high-load windowed SNN 证据标准化成未来所有 fresh tag 都能复用的默认流程

## 14. 2026-03-23 补充刷新：P1-A 已进入 first fresh same-tag stop-window family 阶段

13 节里把 `P1-A` 定义成：

- `fresh stop-window standardization`

这一步之后，它已经从“设计目标”推进成“第一批真实闭环 artifact 已落地”。

当前 fresh 生成链现在已经完整存在：

1. run 层
   - `snn3dexp/tools/run_window_stop_multicase_sweep.py`
2. analyze 层
   - `snn3dexp/tools/analyze_window_stop_multicase_sweep.py`
3. unified surface 层
   - `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
   - 新增显式 `surface_label` contract
4. cross-surface mechanism 层
   - `snn3dexp/tools/export_transfer_kind_mechanism_report.py`
   - 现在优先消费显式 `surface_label`

第一批 fresh same-tag 实际产物已经是：

- `snn3dexp/analysis/sweeps/window_stop_multicase/same_tag_stopwindow_fresh_20260323/window_stop_multicase_sweep_summary.json`
- `snn3dexp/analysis/long_window_ablation_same_tag_stopwindow_fresh_20260323/`
- `snn3dexp/analysis/codesign_surface/same_tag_stopwindow_fresh_20260323/`
- `snn3dexp/analysis/transfer_kind_mechanism/controller_runtime_refresh_20260322_vs_same_tag_stopwindow_fresh_20260323/`

它们给出的结论，与 bridge 阶段一致，但语义地位更强：

1. `9` 个真实 SST smoke 运行
   - `3 case × 3 stop`
   - 全部 `smoke_passed`
2. tail-clear 结果
   - `direct = 2us`
   - `bundle = 10us`
   - `monolithic = 2us`
   - `bundle_minus_direct_gap_ns = 8000`
3. fresh same-tag 机制报告
   - `surface_label = same_tag_stopwindow_fresh_20260323`
   - `bundle_convergence.convergence_detected = true`
   - `earliest_aligned_stop_at = 10us`
   - `final_compare_transfer_kind = aligned_same_controller`

所以 P1-A 当前已经不再是：

- “先想办法把 same-tag stop-window 跑出来”

而是：

- “same-tag stop-window 已经跑出来了，接下来要把它变成默认 high-load 生成方法，并把研究重心转到更真实的 NMC 数据通路”

因此，P1 后续优先级可以更进一步细化成：

1. `P1-A1 default family adoption`
   - 用 same-tag family 替换 legacy per-case stop-sweep 作为今后 high-load 主 stop-window 入口
2. `P1-B1 home-stack path semantics`
   - 重点看 `PE/NIC -> home stack`
   - `synapse/home-stack`
   - `controller hotspot / stack skew`
3. `P1-C1 bridge automation`
   - 在 same-tag family 稳定后，再把 default export bridge 自动接到这条 fresh family

换句话说，当前最值得投入的“下一步”已经很明确：

- 不是继续证明 stop-window 能不能跑
- 而是用这条 fresh same-tag 生成链，真正逼近 `HBM-like NMC` 的数据通路级建模

## 15. 2026-03-23 补充刷新：`P1-B1` 已完成 first `home_stack_dataflow` implementation slice

14 节把 `P1-B1` 定义成：

- `home-stack path semantics`

这一步现在已经从“分析方向”推进成“代码层 contract + fresh artifact refresh”。

当前实现完成了三件具体事情：

1. `route_memory_joint_summary`
   - 新增 `memory.home_stack_dataflow`
   - 把 `traffic_driven_runtime` 按 initiator 重新组织成：
     - `pe_nic_to_home_stack`
     - `synapse_source_to_home_stack`
   - 同时把 runtime hotspot 对齐关系压成：
     - `runtime_hotspot_alignment.controller_alignment_kind`
2. unified surface
   - baseline/window rows 现在可以直接带出：
     - `pe_nic_home_stack_demands_total`
     - `synapse_home_stack_demands_total`
     - `dominant_dataflow_initiator_kind`
     - `dominant_dataflow_region`
     - `dataflow_controller_alignment_kind`
3. refresh contract
   - `route_memory_joint_loader`
     - 现在会把缺少 `home_stack_dataflow` 的旧 summary 视作 stale
     - 允许 unified surface 在消费历史 run roots 时自动重建到新 schema

第一批 fresh 结果已经导出到：

- `snn3dexp/analysis/codesign_surface/same_tag_stopwindow_fresh_20260323_home_stack_dataflow_refresh/`

这批真实数据给了 `P1-B1` 一个很关键的 early answer：

1. 当前 `windowed` 三种 memory/route 变体里，dominant initiator 都是：
   - `pe_nic_to_home_stack`
   - dominant region 也稳定落在 `stream_region`
2. 但差异不在“主路径名字”，而在：
   - 两路 demand 的放大倍数
   - runtime controller 是否与 dominant home path 对齐
3. fresh same-tag stop-window 结果：
   - direct
     - 长期保持 `cross_class_transfer`
   - bundle
     - `2us`: `runtime_class_unresolved`
     - `10us / 20us`: 收敛到 `aligned_same_controller`
   - monolithic_proxy
     - volume 基本不再放大
     - 但 controller alignment 仍停留在 `cross_class_transfer`

这说明 `P1-B1` 的下一步已经不再是：

- “继续想办法看见 home-stack path”

而是：

1. 把 `home_stack_dataflow` 继续下沉成 compare delta
   - 直接表达 `bundle/direct`
   - `monolithic/direct`
   - 在 `PE/NIC` 和 `synapse/home-stack` 两路上的 amplification / migration
2. 把 `controller_alignment_kind`
   - 从当前 row-level 观察量
   - 进一步提升成 route-memory-NMC co-design 的正式解释量
3. 让下一轮 `P1-B1` 回答更尖锐的问题：
   - `bundle` 的额外压力主要卡在 `synapse gather` 还是 `stream region`
   - `monolithic_like` 为什么在 request volume 贴平后仍然保留 `cross_class_transfer`

## 16. 2026-03-23 补充刷新：`P1-B1` 已完成 compare-row delta slice

15 节里把 `P1-B1` 定义成：

- `home_stack_dataflow` row-level contract

这一步之后，它已经继续推进到：

- `compare-row delta`

当前落地范围很明确：

1. `traffic_mem_compare_rows`
   - `bundle_vs_direct`
   - `monolithic_vs_hbm`
2. `window_stop_compare_rows`
   - `bundle_vs_direct`
   - `monolithic_vs_direct`

这意味着 `P1-B1` 当前已经不只是：

- “让 row 能看见 `PE/NIC` / `synapse/home-stack` 两路”

而是已经变成：

- “让 compare row 直接回答哪一路被放大、放大多少、对齐是在改善还是退化”

fresh same-tag compare-delta 给出的最关键结果有两类：

1. `window_stop_bundle_vs_direct`
   - `2us`
     - `pe_nic_ratio = 4.0`
     - `synapse_ratio = 4.3125`
     - `alignment_transition = alignment_degraded`
   - `10us / 20us`
     - `pe_nic_ratio = 2.1136`
     - `synapse_ratio = 4.3125`
     - `alignment_transition = alignment_improved`
2. `window_stop_monolithic_vs_direct`
   - `10us / 20us`
     - `pe_nic_ratio = 1.0`
     - `synapse_ratio = 1.0`
     - `alignment_transition = stable`

这给 `P1-B1` 一个比 row-level 更尖锐的中间结论：

1. `bundle` 的“收敛”不是单调的
   - controller alignment 可以先改善
   - 但 `synapse/home-stack` amplification 仍可能留得很高
2. `monolithic_like` 的“volume 贴平”也不是终点
   - 它可能只是把 volume 问题消掉
   - 但并没有把 runtime hotspot 拉回 dominant home path

因此，`P1-B1` 的下一步优先级现在可以再缩成两个更精确的子问题：

1. `P1-B1a path amplification attribution`
   - 把 compare-delta 从全局 totals 继续拆到 per-stack / per-controller
2. `P1-B1b alignment-without-volume gap`
   - 专门解释：
     - 为什么 `bundle` 会出现 “alignment improved but synapse amplification persists”
     - 为什么 `monolithic_like` 会出现 “volume flat but alignment still cross-class”

## 17. 2026-03-23 补充刷新：`P1-B1a` 已完成 first stack/controller attribution closure

16 节里把 `P1-B1a` 定义成：

- 把 compare-delta 从全局 totals 继续拆到 per-stack / per-controller

这一轮之后，这件事已经完成 first closure，而且不是停留在测试桩，而是已经进入 fresh unified surface。

当前完成的最小闭环包括三层：

1. summary contract
   - `route_memory_joint_summary.memory.home_stack_dataflow.initiator_groups.*`
   - 新增：
     - `dominant_stack_id`
     - `dominant_stack_demand_share`
     - `dominant_controller_ids`
     - `stack_rows`
     - `controller_rows`
2. refresh contract
   - `route_memory_joint_loader`
   - 现在会把缺少上述 attribution 字段的旧 summary 视作 stale
   - 因此历史 run root 在统一导出时会自动重建，而不是继续把旧 schema 当成新事实
3. surface contract
   - `memory_nmc_codesign_surface`
   - baseline / stop-window rows 可以直接落：
     - dominant stack id
     - dominant controller ids
     - dominant stack demand share
     - runtime-hotspot stack overlap
   - compare rows 可以直接落：
     - `dominant_stack_changed`
     - `dominant_controller_ids_changed`
     - `dominant_stack_demand_share_delta`
     - `runtime_hotspot_stack_overlap_delta`

最新 fresh surface：

- `snn3dexp/analysis/codesign_surface/same_tag_stopwindow_fresh_20260323_stack_controller_attribution_refresh/`

这批 fresh 结果，把 `Goal 1: Unified memory/NMC compare surface` 的状态又往前推了一步。

现在它已经不只是回答：

- 哪一路 demand 被放大
- alignment 在改善还是退化

而是开始回答：

- dominant stack 有没有迁移
- dominant controller set 有没有重排
- runtime hotspot 是不是还留在 dominant stack 上

其中最值得写进下一阶段 design judgment 的三个事实是：

1. `traffic_mem_bundle_vs_direct`
   - `PE/NIC` dominant stack 已从 `0` 迁到 `3`
   - dominant controller set 从 `0,1,2,3` 迁到 `12,13,14,15`
   - `synapse` dominant stack 仍保持 `0`
   - 说明 traffic-mem bundle 的 path change 已经开始分化成：
     - `PE/NIC` 路 dominantly migrated
     - `synapse/home-stack` 路基本未迁
2. `window_stop_bundle_vs_direct`
   - dominant stack / controller set 在 `10us / 20us` 基本保持稳定
   - 但 `runtime_hotspot_stack_overlap_delta = -1`
   - 同时 `alignment_transition = alignment_improved`
   - 这意味着 windowed bundle 现在最值得解释的，已经不是“有没有 dominant path migration”，而是：
     - 为什么 hotspot 会离开 dominant stack
     - 但 controller alignment 却继续改善
3. `window_stop_monolithic_vs_direct`
   - dominant stack 仍保持不变
   - dominant controller set 发生明显重排
   - volume 可以贴平，但 alignment 仍 `stable`
   - 这说明 monolithic-like 的主要收益更像：
     - 改写 controller placement / pressure distribution
     - 而不是自动把热点语义改写成另一类 home-path

因此，`Goal 1` 的下一步优先级需要再次收敛。

它不应再写成泛泛的：

- “继续做更细的 compare surface”

而应明确写成：

1. `P1-B1c stack/controller explainability closure`
   - 把 `dominant_stack_demand_share / service_deficit_proxy`
   - 与真实 controller runtime 指标
     - `requests_received_total`
     - `outstanding_requests_accum`
     - `cycles_attempted_issue_but_rejected`
   - 统一成同一条 explainability chain
2. `P1-B2 real home-path closure`
   - 把 `PE/NIC -> home stack` 与 `synapse/home-stack`
   - 从 proxy attribution 再推进到真实 home-stack memory path
   - 回答当前 dominant stack/controller migration 到底对应哪类真实数据通路变化
3. `P1-B3 HBM-like vs monolithic-like controller remap`
   - 在相同 dominant path 视角下比较：
     - controller set 重排
     - hotspot overlap 保持/丢失
     - volume flat 但 alignment stable 的原因

所以 16 节里给 `P1-B1a` 的判断，今天需要正式更新为：

- `P1-B1a` 已完成
- 当前 `Goal 1` 的前沿不再是 “per-stack / per-controller attribution 有没有”
- 而是 “这组 attribution 怎样与真实 runtime controller pressure 和真实 memory path 合成统一机理解释”
