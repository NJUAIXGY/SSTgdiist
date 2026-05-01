# PE-Atlas M2-B5：Schema Freeze 与 Binding Unresolved Ledger 大阶段执行计划（2026-04-14）

> 日期：2026-04-14  
> 状态：stage-plan v1  
> 定位：`architecture-first + modeling-first + experiment-isolated`  
> 前置阶段：`M2-B4 / cross-plane mismatch ledger`、`M2-B4.5 / schema-authority freeze`  
> 下一入口：`M2-C / branch-transition validation suite`  
> 当前纪律：**先把 PE 内 object / authority / binding / control / snapshot 统一 freeze，再决定是否进入任何 branch-transition；暂时不以收益为第一目标。**

---

## 0. 一句话结论

下一大阶段不再继续“补几个 reader 字段”，而是正式收敛为：

- **`M2-B5 / PE Internal Object-Machine Schema Freeze + Binding Unresolved Ledger`**

它的目标不是新增共享功能，而是把当前已经出现的对象层证据，收敛成一套：

1. 可版本化的 schema；
2. 可交叉引用的 object / authority / binding 关系；
3. 可 machine-readable 解释的 unresolved ownership split；
4. 可在 `summary / trace / snapshot` 三层稳定复现的 canonical artifact。

只有这一步完成，后续 `M2-C` 才有资格回答：

- 哪条 branch 真正进入下一层；
- 哪个对象 family 值得 formal objectize；
- 哪个 split 只是 today runtime 的语义 overlay。

---

## 1. 当前阶段事实

基于当前代码、测试与 artifact，已经冻结下来的事实是：

1. `rowindex / idx2 / preband / shared_weight_residency` 已经进入 reader-level object vocabulary；
2. `storage authority map` 已经能表达：
   - `authority_state`
   - `lifecycle_stage`
   - `formal_object_ref`
   - `closure_ref`
3. `object_closure` 已经能反向指向 authority plane；
4. `WMS storage binding map` 已经能表达：
   - `runtime_owner`
   - `runtime_instance_scope`
   - `physical_model`
   - `binding_state`
   - `semantic_overlay_owner`
   - `fallback_owner`
5. `shared_weight_residency` 已经被正式写成：
   - `semantic_overlay_only`
   - 而不是 `formal local storage owner`
6. `control_commit_view` 已经具备最小 contract 词表：
   - `service_ready_commit_blocked`
   - `service_ready_barrier_wait`
   - `service_commit_aligned`
   - `fabric_absent`

但当前仍然没有完成的关键点是：

1. `summary / trace / snapshot` 三层还没有统一的 schema/version registry；
2. `binding unresolved` 还只是散落在 `reason` 和文字语义里，没有独立台账；
3. `weight_value_store / shared_weight_residency` 的 unresolved edge 还没有显式冻结；
4. `message/control/sync` 对象 family 还没有与 storage family 同等 formalized；
5. `mainexp` 里还没有一套面向 `M2-C` 的 canonical gate artifact。

因此，当前主线必须进入 `M2-B5`，而不能直接跳 `M2-C`。

---

## 2. 阶段目标

`M2-B5` 的唯一目标是把 today `PE` 机器收敛成一个正式、稳定、可验证的局部对象机模型。

本阶段必须同时做到：

1. **Schema Freeze**
   - 同一概念在 `summary / trace / snapshot` 三层不再漂移命名。
2. **Authority Freeze**
   - 每个 formal object family 都能回答 authority 停在哪一层。
3. **Binding Freeze**
   - 每个 WMS/local-storage 相关对象都能回答 runtime owner、scope、physical model、fallback。
4. **Unresolved Freeze**
   - 每个 today 仍未 formalized 的 ownership split 都能被单独 machine-readable 解释。
5. **Artifact Freeze**
   - `mainexp` 能稳定导出 canonical gate artifact，而不依赖人工口头解释。

---

## 3. 本阶段非目标

本阶段明确不做：

1. `speedup / memory_requests` 导向的 sweep；
2. `rowindex / idx2 / preband` 的阈值扫描；
3. 新 heuristic、新 rescue、新调参 patch；
4. 把 `semantic overlay owner` 包装成 `formal local storage owner`；
5. 改写主线 runtime、改变 exact retire contract；
6. 直接以 `M2-C` 名义做 branch A/B。

如果某项工作不能让 `PE` 机器图景更清楚，它就不是当前主任务。

---

## 4. 阶段产物

本阶段结束时，至少应稳定产出下面六类 artifact：

1. `atlas_schema_registry`
2. `atlas_binding_unresolved_ledger`
3. 扩展后的 `atlas_wms_storage_binding_map`
4. 扩展后的 `atlas_control_commit_view`
5. 至少一个 non-storage object family 的 formal schema
6. `mainexp` canonical gate snapshot / trace / summary 套件

这六类产物必须能被测试约束、能在 `summary / trace / snapshot` 里稳定出现、能解释 today 机器的断点。

---

## 5. 工作包设计

### WP1：Schema Canonicalization

目标：把 `summary / trace / snapshot` 三层使用的词表与版本固定下来。

需要解决的问题：

1. 同一对象是否在三层使用同一名字？
2. 同一状态是否在三层使用同一 machine vocabulary？
3. 同一字段的 authority source 是否清楚？
4. 当前 snapshot 是否遗漏了关键 schema 面？

建议落地产物：

1. `atlas_schema_registry`
   - `version`
   - `views`
   - `vocabulary`
   - `authority_source`
   - `artifact_surfaces`
2. 至少覆盖下面视图：
   - `atlas_object_kind_census`
   - `atlas_storage_authority_map`
   - `atlas_object_closure`
   - `atlas_wms_storage_binding_map`
   - `atlas_control_commit_view`
   - `atlas_cross_plane_visibility`

建议修改文件：

- `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- `/home/xgy/remote/sst_dram_si/tools/summarize_atlas_activation_trace.py`
- `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- `/home/xgy/remote/sst_dram_si/tools/test_summarize_atlas_activation_trace.py`
- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/make_snapshot.py`
- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/test_make_snapshot.py`

验收标准：

1. `summary / trace` 都导出同名 registry；
2. snapshot 至少导出 version / vocabulary / key-view registry entry；
3. 回归测试能约束 schema name 与 version 不漂移。

---

### WP2：Binding Unresolved Ledger

目标：把 today 仍未 formalized 的 ownership split 与 contract gap 从“文字说明”提升成独立台账。

这张台账至少要回答：

1. unresolved 的对象是谁？
2. unresolved 的类型是什么？
3. 缺的是 owner、release、evict、physical contract，还是 scope alignment？
4. 当前 fallback 是谁？
5. 为什么它今天不能被视作 formal local object？

第一批必须覆盖：

1. `weight_value_store`
2. `shared_weight_residency`
3. `weight_idx_store` 的 scope widening 事实

建议 machine-readable 字段：

- `binding_state`
- `formalization_state`
- `unresolved_edges`
- `runtime_owner`
- `fallback_owner`
- `reason`
- `evidence_refs`

建议修改文件：

- `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- `/home/xgy/remote/sst_dram_si/tools/summarize_atlas_activation_trace.py`
- `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- `/home/xgy/remote/sst_dram_si/tools/test_summarize_atlas_activation_trace.py`
- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/make_snapshot.py`
- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/test_make_snapshot.py`

验收标准：

1. unresolved 不是埋在自然语言 reason 里，而是有显式字段；
2. `shared_weight_residency` 至少明确：
   - `semantic_overlay_only`
   - `evict_owner unresolved`
   - `release_owner unresolved`
3. snapshot 能导出 unresolved state。

---

### WP3：WMS Storage Contract Expansion

目标：把 `WMS internal storage model -> PE local storage object model` 的映射彻底压实。

本工作包不是新建 shared plane，而是明确 today contract。

必须冻结的对象：

1. `weight_idx_store`
2. `weight_value_store`
3. `shared_weight_residency`

每个对象至少回答：

1. namespace 在哪里？
2. runtime owner 是谁？
3. runtime instance scope 是 `per_core` 还是 `per_pe_overlay`？
4. physical model 是什么？
5. physical scope 是什么？
6. owner/release/evict/fallback 由谁承担？

建议扩展字段：

- `namespace_scope`
- `runtime_instance_scope`
- `physical_model`
- `physical_scope`
- `evict_owner`
- `release_owner`
- `fallback_owner`
- `formalization_state`

建议修改文件：

- `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- `/home/xgy/remote/sst_dram_si/tools/summarize_atlas_activation_trace.py`
- `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- `/home/xgy/remote/sst_dram_si/tools/test_summarize_atlas_activation_trace.py`
- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/make_snapshot.py`
- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/test_make_snapshot.py`

验收标准：

1. 三个对象都能用同一套 binding vocabulary 描述；
2. `weight_value_store` 与 `shared_weight_residency` 的 split binding 能被 artifact 直接解释；
3. 不引入任何伪造 shared physical plane。

---

### WP4：Message / Control / Sync Object Family Freeze

目标：把 storage family 之外的 PE 内部对象也拉进 formal schema。

第一批建议对象：

1. `rowdescriptor`
2. `activation_ingress_store`
3. `sync_barrier` / `retire_sync_object`

需要回答的问题：

1. 它是 object、helper 还是 proxy 宿主？
2. 它是否有 formal owner？
3. 它的 ready/release 是否有独立 contract？
4. 它是 message plane、control plane 还是 sync plane？

建议新增视图：

- `atlas_control_binding_map` 或等价面

但如果实现上不需要新 view，也至少要：

1. 将对象纳入 `object_kind_census`
2. 将 control/sync contract 纳入 `control_commit_view` 或并列视图

建议修改文件：

- `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- `/home/xgy/remote/sst_dram_si/tools/summarize_atlas_activation_trace.py`
- `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- `/home/xgy/remote/sst_dram_si/tools/test_summarize_atlas_activation_trace.py`

验收标准：

1. 至少一个 non-storage object family 被 formalized；
2. `control/runtime` 与 `sync/commit` 的边界更明确；
3. 不把 message/control 对象误建模成 storage plane。

---

### WP5：Canonical Artifact & Gate Suite

目标：把 `M2-C` 的入口条件变成 artifact gate，而不是口头判断。

建议在 `mainexp` 里形成一个小型 canonical gate suite，至少包含：

1. `baseline / fabric_absent`
2. `rowindex_object_template branch`
3. `shared_weight_semantic_overlay_only`
4. `binding_unresolved_present`

每个 case 只回答：

1. 哪个 plane 被 constructed？
2. 哪个 object 被 formalized？
3. 哪个 binding 仍 unresolved？
4. 是否满足 `M2-C` 入口条件？

建议优先复用：

- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1`

必要时再新建独立实验目录，但必须保持隔离，不影响现有主线实验。

验收标准：

1. `compare.tsv` 能直接展示 schema / unresolved / binding 面；
2. 不依赖人工读 JSON 才能判断阶段状态；
3. 这些 case 可以作为后续 `M2-C` 的 gate suite。

---

## 6. 执行顺序

推荐顺序如下：

1. **先做 `WP1 / Schema Canonicalization`**
   - 因为没有统一 schema，后面每加一个视图都会继续漂移。
2. **再做 `WP2 / Binding Unresolved Ledger`**
   - 把 unresolved split 从自然语言里拉出来。
3. **然后做 `WP3 / WMS Storage Contract Expansion`**
   - 彻底压实 storage family。
4. **再做 `WP4 / Message / Control / Sync Object Family Freeze`**
   - 把 non-storage family 接上。
5. **最后做 `WP5 / Canonical Artifact & Gate Suite`**
   - 用 artifact gate 收尾，为 `M2-C` 铺入口。

---

## 7. 第一批并行任务包

第一批推荐直接并行推进下面三个包：

### Batch A：Schema Registry

目标：

- 产出 `atlas_schema_registry`
- 让 `summary / trace / snapshot` 对齐 key-view vocabulary

最小落地文件：

- `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- `/home/xgy/remote/sst_dram_si/tools/summarize_atlas_activation_trace.py`
- `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- `/home/xgy/remote/sst_dram_si/tools/test_summarize_atlas_activation_trace.py`
- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/make_snapshot.py`
- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/test_make_snapshot.py`

### Batch B：Binding Unresolved Ledger

目标：

- 产出 `atlas_binding_unresolved_ledger`
- 首先覆盖 `weight_value_store / shared_weight_residency`

最小落地文件：

- `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- `/home/xgy/remote/sst_dram_si/tools/summarize_atlas_activation_trace.py`
- `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- `/home/xgy/remote/sst_dram_si/tools/test_summarize_atlas_activation_trace.py`

### Batch C：Snapshot Gate Expansion

目标：

- 让 `compare.tsv` 能直接显示：
  - schema version
  - unresolved edge
  - binding state

最小落地文件：

- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/make_snapshot.py`
- `/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/test_make_snapshot.py`

---

## 8. 阶段退出条件

只有当下面条件都成立时，`M2-B5` 才算完成：

1. `summary / trace / snapshot` 三层有统一 schema/version registry；
2. `binding unresolved ledger` 已经存在；
3. `weight_idx_store / weight_value_store / shared_weight_residency` 的 contract 完整可读；
4. 至少一个 non-storage object family 被 formalized；
5. `mainexp` 有一套可复用的 canonical gate artifact；
6. 仅靠 artifact 就能回答：
   - 这台 `PE` 机器当前在哪一层；
   - 哪些对象已 formalized；
   - 哪些 binding 仍 unresolved；
   - 是否满足进入 `M2-C` 的条件。

---

## 9. 这阶段完成后，下一步是什么

`M2-B5` 之后，唯一合理的后继不是收益 sweep，而是：

- **`M2-C / branch-transition validation suite`**

到那时，我们关注的才是：

1. 哪个 branch 真正进入下一层；
2. 哪个对象 family 值得打开 formal branch；
3. 哪个 unresolved split 需要 architecture intervention；
4. 哪些结果才有资格进入收益讨论。

在 `M2-B5` 之前，这些都不应该成为主任务。

