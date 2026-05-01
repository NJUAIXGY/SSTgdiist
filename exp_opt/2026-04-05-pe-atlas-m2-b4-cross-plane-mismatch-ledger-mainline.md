# PE-Atlas M2-B4：Cross-Plane Mismatch Ledger 主线稿（2026-04-05, updated 2026-04-09）

> 日期：2026-04-05  
> 状态：stage-mainline v2  
> 定位：`architecture-first + modeling-first + experiment-isolated`  
> 当前阶段：`M2-B4 config/runtime/object closure -> M2-B4.5 schema/authority freeze -> M2-C`  
> 核心原则：**先把 PE 内机器的跨平面失配台账补齐，再决定要打开哪条对象化分支；暂时不以收益为第一目标。**

---

## 0. 一句话结论

当前 `PE-Atlas` 已经不再缺“更多局部优化想法”，真正缺的是：

- 一张能同时对齐
  - `build/config`
  - `runtime requested/effective`
  - `constructed plane`
  - `storage authority`
  - `control runtime`
  - `sync/commit`
  的统一失配台账。

因此当前主线不应再写成：

- `再找一条 seam 打收益`

而应正式冻结为：

- **`PE-Atlas M2-B4: Cross-Plane Mismatch Ledger`**

它的唯一任务是回答：

1. 今天的 `PE` 机器到底在哪一层断掉？
2. 是 `build_off`，还是 `requested_not_effective`？
3. 是 `effective_not_constructed`，还是 `constructed_without_effective`？
4. 是 `storage authority` 没形成，还是 `control/runtime` 没闭环？
5. `ready` 是否已经可见，但 `commit` 仍然被同步路径卡住？

只有把这张账本做完整，才允许进入 `M2-C branch-transition validation`。

`2026-04-09` 这轮工作的意义，不是拿到收益，而是把 `PULSE rowindex / OSA metadata txn` 这条最关键的 cross-plane 配置链第一次真正修通：

1. `spec_first` 顶层 `pulse` schema 已可解析；
2. `runtime` 已能把 `pulse` 配置落到 mesh config；
3. `build` 过去会把 `osa_metadata_txn/object_mask` 无条件清零，这个根因已修掉；
4. `effective_config` 现在可以真实保留 `pulse.osa_metadata_txn_enable=1` 与 `pulse.osa_metadata_object_mask="rowidx,rowdescriptor"`；
5. `atlas_activation_census / activation_trace` 已能把 `rowindex_requested -> rowindex_constructed -> rowindex_effective` 连成闭环。

因此，这一稿之后的主线判断必须更新为：

- **`M2-B4` 的第一条硬闭环已经建立，但整张 ledger 还没有 freeze 成统一 schema；下一阶段不是追收益，而是把 schema、authority 和 object-plane 口径彻底收紧。**

---

## 1. 当前已冻结的机器事实

基于当前 canonical artifact 与 `2026-04-09` fresh run：

- [essential_summary_mesh.json](/home/xgy/remote/mainexp/runs/atlas_machine_census_v1/20260404-025732/essential_summary_mesh.json)
- [atlas_activation_trace.json](/home/xgy/remote/mainexp/runs/atlas_activation_trace_closure_v2/20260404-030150/atlas_activation_trace.json)
- [rowindex_object_off/20260409-102310/effective_config.json](/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/runs/rowindex_object_off/20260409-102310/effective_config.json)
- [rowindex_object_on/20260409-102357/effective_config.json](/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/runs/rowindex_object_on/20260409-102357/effective_config.json)
- [rowindex_object_on/20260409-102357/essential_summary_mesh.json](/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/runs/rowindex_object_on/20260409-102357/essential_summary_mesh.json)
- [rowindex_object_on/20260409-102357/atlas_activation_trace.json](/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/runs/rowindex_object_on/20260409-102357/atlas_activation_trace.json)

已经可以明确写出 today machine picture：

1. `workload_pure_snn = 16`
2. `machine_chain.build_effective.local_storage = 0`
3. `machine_chain.runtime_requested.* = 0`
4. `machine_chain.runtime_effective.* = 0`
5. `machine_chain.runtime_constructed.* = 0`
6. `control_runtime.dominant_state = fabric_absent`
7. `shared_weight.dominant_state = absent`
8. `shared_weight.dominant_absent_reason = local_storage_gate`

也就是说，canonical 主线今天并不是：

- `已经进入 PE-local shared plane，但收益不足`

而是：

- **还没进入任何正式的 PE-local shared plane**

更准确地说：

- `workload eligible -> local_storage off -> no pod/service/shared-weight plane -> fabric_absent`

这个判断已经不再需要人工口头解释，而应该成为后续所有设计与实验的入口前提。

但 `2026-04-09` 的 fresh run 也同时给出一个非常关键的新事实：

- canonical 主线之外，我们已经修通了一条 **受控 rowindex object seam** 的配置传播链与可观测链。

这一点具体表现为：

1. `rowindex_object_off`
   - `pulse.enable = 0`
   - `pulse.osa_enable = 0`
   - `pulse.osa_metadata_txn_enable = 0`
   - `activation_gate.rowindex_requested.total = 0`
   - `activation_gate.rowindex_constructed.total = 0`
   - `enable_state.rowindex_effective.total = 0`
   - `rowindex_object.coverage_status = runtime_visible_object_dark`

2. `rowindex_object_on`
   - `pulse.enable = 1`
   - `pulse.osa_enable = 1`
   - `pulse.osa_metadata_txn_enable = 1`
   - `pulse.osa_metadata_object_mask = "rowidx,rowdescriptor"`
   - `activation_gate.rowindex_requested.total = 1`
   - `activation_gate.rowindex_constructed.total = 1`
   - `enable_state.rowindex_effective.total = 1`
   - `rowindex_object.coverage_status = object_and_runtime_visible`

这说明我们现在已经不再停留在“只会口头解释哪层断掉”，而是第一次拿到了：

- `spec/runtime/build/effective/object-plane` 五层一致的硬证据。

因此，下一阶段的主问题已经不是“rowindex 能不能亮”，而是：

- **怎么把这条已修通的 rowindex seam，提升成统一的 mismatch ledger schema 和 object authority 口径。**

---

## 2. 为什么下一阶段必须是 M2-B4，而不是继续做收益 sweep

此前围绕 `rowindex / idx2 / preband / frontier / owner-first` 的工作已经证明：

1. `PE` 内局部 seam 是真实存在的；
2. 某些 seam 可以进入局部收益区间；
3. 但这些收益并不能自动说明：
   - `PE` 已经被建模成一台对象化机器。

当前真正缺失的不是新的启发式，而是：

- 缺少一张把 “对象层 / authority 层 / storage 层 / control 层 / sync 层” 同时对齐的 ledger。

换句话说，今天继续扫收益会再次回到老问题：

- 知道某条 seam 在动，
- 但不知道它在整台 PE 机器里到底处在什么层次、
- 也不知道它是不是正式对象，
- 更不知道它为什么没能跨过下一层边界。

所以这轮必须坚持：

- **先做 machine-state classification，再做 branch transition；不先看 speedup。**

---

## 3. 与现有阶段命名的对应关系

结合 [PE-Atlas v2](/home/xgy/remote/exp_opt/2026-03-31-pe-atlas-manycore-object-machine-design-v2.md)，当前阶段应收敛为：

- `M0 / object census`：已完成第一轮
- `M1 / probe plane`：已完成最小链路
- `M1.5 / facet split`：已完成 summary 主链路接线
- `M2-B1/B2/B3`：activation census、shared-weight census、machine-chain 已落地
- **当前正式阶段：`M2-B4 / cross-plane mismatch ledger`**
- 下一入口阶段：`M2-C / branch-transition validation suite`

因此，接下来不再把“再做一个 PE 内优化实验”当作主任务，而是把：

- `M2-B4` 视为唯一主线
- `M2-C` 视为唯一后继入口

`M2-C` 的入口条件不是收益，而是下面四张视图已经同时稳定：

1. `phase contract view`
2. `storage authority view`
3. `control runtime view`
4. `cross-plane mismatch view`

---

## 3.5 当前 fresh closure 暴露出的真正剩余问题

这轮修复并没有把 `M2-B4` 做完，反而把剩余问题压得更清楚了。

### 3.5.1 问题 A：summary reader 口径仍然落后于实际 schema

此前很多分析默认去读：

- `atlas_activation_census.gates.*`

但当前 fresh artifact 的稳定平面已经是：

- `atlas_activation_census.activation_gate.*`
- `atlas_activation_census.enable_state.*`

也就是说，问题不在 artifact 没产出，而在 reader 仍然带着旧 schema 假设。

### 3.5.2 问题 B：`effective_gap` 信息存在，但还没有 freeze 成统一顶层台账

在 `essential_summary_mesh.json` 中，`effective_gap / effective_gap_cause / effective_gap_blocked_gates` 已经作为 ledger entry 出现；
但它们还没有在单一、稳定、统一的 top-level mismatch view 中收口。

结果就是：

1. `summary` 能看到部分 gap 事实；
2. `atlas_activation_trace` 能看到 `surface_coverage` 和 `activation_diff`；
3. 但还缺一张固定 schema 的总账，把这些内容变成统一 machine-state 词表。

### 3.5.3 问题 C：rowindex 已接通，但 idx2 / preband / storage authority 仍未进入 formal object plane

这轮只能证明：

- `rowindex` 在 `pulse_osa metadata txn` 的受控分支下，可以进入 requested/constructed/effective。

但它还不能证明：

1. `idx2`
2. `preband`
3. `shared_weight residency`
4. `WMS internal storage model -> PE local storage object model`

已经被 freeze 成 formal object authority。

因此，我们仍然不能跳到收益导向，更不能把这轮闭环误解为：

- `PE` 内共享机器已经完成。

它真正说明的是：

- **我们终于拿到了一条足够硬的“已接通对象分支”，可以反过来校准 schema、authority 和 storage model。**

## 4. 下一阶段的唯一主线：Cross-Plane Mismatch Ledger

`M2-B4` 的目标不是新增功能，而是把 today 最危险的跨层失配统一收账。

这份 ledger 至少要覆盖五类 surface：

1. `local_storage`
2. `pulse / pulse_osa`
3. `shared_weight owner / shared_weight authority`
4. `pod metadata / pod owner / service table`
5. `control runtime / sync-vs-commit`

对每类 surface，都必须能回答同一组问题：

1. `build_effective` 是否打开？
2. `runtime_requested` 是否发生？
3. `runtime_effective` 是否发生？
4. `constructed` 是否发生？
5. `storage authority` 停在什么状态？
6. `control runtime` 停在什么状态？
7. `sync/commit` 是否还存在额外阻塞？

它的产物不是一个“是否有效”的结论，而是一张更底层的 machine-state ledger：

- `build_off`
- `runtime_not_requested`
- `requested_not_effective`
- `effective_not_constructed`
- `constructed_without_effective`
- `gated_by_local_storage`
- `gated_by_pulse_osa`
- `gated_by_owner_request`
- `mirror_only`
- `actual_owner`
- `fabric_absent`
- `ready_visible_but_commit_blocked`

这些状态必须是 artifact-visible、可测试、可复算的。

在 `2026-04-09` 之后，这个目标需要更具体地改写成两步：

1. **先把 rowindex 这条已接通分支 freeze 成标准 ledger 模板；**
2. **再用同一模板去测 idx2 / preband / shared_weight / storage authority。**

---

## 5. 下一阶段的 concrete task package

### Task 1：冻结 `atlas_contract_mismatch` / `surface_coverage` 统一 schema

在 summary / sidecar 中正式导出一个统一 ledger，至少包含：

1. `dominant`
2. `phase.local_storage`
3. `phase.pulse`
4. `phase.pulse_osa`
5. `phase.shared_weight_owner`
6. `phase.pod_service`
7. `storage_authority.shared_weight`
8. `control_runtime`
9. `sync`

要求：

- 只允许 summary-side derive
- 不改 runtime 行为
- 不改 canonical config
- 统一 reader 首选口径为：
  - `activation_gate.*`
  - `enable_state.*`
  - `surface_coverage.entries.*`
  - `activation_diff.surfaces.*`
  - `config_resolution.*`

这一项的目标不是“再多导出几个字段”，而是彻底消灭：

- 老 reader 读 `gates`
- 新 artifact 写 `activation_gate`
- sidecar 再写一套别名

这种 schema 漂移。

### Task 2：把 `machine_chain` 和 `activation_diff` 统一到同一语义表

今天 `machine_chain` 更偏 summary-first，
`activation_diff` 更偏 human-first。

下一阶段需要让它们共同 obey 一套 surface-state 词表，
避免出现：

- summary 说 `build_off`
- sidecar 说 `disabled`
- 实验记录再说 `fabric_absent`

这种语义漂移。

### Task 3：冻结 `rowindex object closure` 的标准模板

用这轮已经跑通的 `rowindex_object_on/off` 作为 canonical 示例，把下面这些字段固定下来：

1. `requested`
2. `constructed`
3. `effective`
4. `coverage_status`
5. `dark_planes`
6. `machine_reason`
7. `config_resolution`
8. `blocked_gates`
9. `effective_gap`
10. `effective_gap_cause`

这一步的目标是形成一张：

- `object closure template`

后面任何对象族进入 objectization，都必须按这张模板出账。

### Task 4：做 `object-kind census v2`

在 mismatch ledger 稳定后，下一步不再按大类对象，而要按对象族逐项收口：

1. `RowDescriptor`
2. `RowIndex`
3. `PreMphfBase`
4. `PreMphfBand`
5. `PodMetadataObject`
6. `PodOwnerEntry`
7. `PeLocalServiceObject`
8. `SharedWeight residency`

输出一张 today matrix：

- `active`
- `proxied`
- `shadow-only`
- `missing`

### Task 5：做 `storage authority model` 映射闭环

把 `WMS internal storage model` 与 `PE local storage object model` 的映射正式写清楚：

1. namespace 在哪里
2. residency 在哪里
3. owner scope 是谁
4. mirror-only 和 actual-owner 如何分层
5. evict / release / fallback 谁负责

这一步是后续任何 shared-weight / pod objectization 的前置条件。

### Task 6：准备 `M2-C branch-transition validation suite`

`M2-C` 不是收益 A/B，而是受控的 branch-transition 实验。

建议第一批只做三条受控分支：

1. `local_storage-only`
2. `local_storage + pod`
3. `local_storage + pod + shared_weight_mirror_only`

每条分支只回答：

- 机器是否真的进入下一层
- 新 plane 是否真正 constructed
- 新对象是否出现完整 lifecycle

在 `2026-04-09` 之后，建议再加一条更前置的 entry gate：

4. `rowindex_object_template branch`

它的目的不是评估收益，而是验证：

- `M2-B4` 冻结下来的 object closure template
- 是否真的能稳定复用于下一条 object family

---

## 6. 本阶段的非目标

本阶段明确不做：

1. `memory_requests` 导向的 sweep
2. `rowidx / idx2 / preband` 阈值扫描
3. 以 speedup 为主的 A/B 排行
4. 新的 heuristic / rescue / tuning patch
5. 把 `rowindex_object_on` 这次闭环直接包装成“收益已经成立”

如果某项工作不能让机器图景更清楚，
即便它可能带来收益，也不应是当前主任务。

---

这里要特别强调一个阶段纪律：

- 这轮 `rowindex_object_on` 的成功，不代表主线已经变成“去追 rowindex 收益”；
- 它只代表我们终于拿到了一条可以作为 schema/authority 标定样本的对象分支。

也就是说，现在最应该做的不是：

- 把 `rowindex` 参数扫一圈；

而是：

- 用 `rowindex` 这条已接通的支路，把整个 `PE-Atlas` 的对象台账格式固定下来。

## 7. 阶段完成标准

只有当下面条件全部成立时，才算 `M2-B4` 完成：

1. `summary` 和 `sidecar` 都能导出统一的 mismatch ledger
2. 关键 surface 都有稳定的状态词表
3. 关键状态都具备测试约束
4. canonical run 的断点能被 artifact 直接解释
5. `object-kind census v2` 已经能指出下一条真正值得 objectize 的对象路径
6. `rowindex object closure template` 已经在 canonical artifact 中稳定复现

达到这些条件后，才允许进入 `M2-C`。

---

## 8. 当前推荐的执行顺序

最稳妥的推进顺序是：

1. 先完成 `atlas_contract_mismatch / surface_coverage` schema freeze
2. 再把 `rowindex object closure` 固化成标准模板
3. 然后统一 `machine_chain / activation_diff` 的状态语义
4. 再做 `object-kind census v2`
5. 最后才打开第一条 `branch-transition validation`

简言之：

- **先把 rowindex 这条已接通分支变成标准台账模板，再把下一条分支打开。**

这就是 `2026-04-05` 之后 `PE-Atlas` 的唯一主线。
