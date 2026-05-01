# PE-Atlas RowIndex Prefetch-Only Frontier：下一阶段架构与实验推进稿（2026-04-03）

> 日期：2026-04-03
> 状态：design v1
> 定位：`architecture-first + experiment-isolated + evidence-driven`
> 目标：不再围绕“为什么没收益”兜圈子，而是把当前 fresh runtime 结论压成一个更清楚的下一阶段主线：
> **先把 `PE` 内 `rowindex/object/service/storage/control` 机器的因果链画清楚，再设计能真实进入 `noninflight_prefetch_only` 的实验口径。**

---

## 0. 一句话结论

当前 fresh A/B 已经证明两件事：

1. `rowindex prefetch` 机制已经真实生效，不再是“统计链路或数据集缺失导致的假象”；
2. 但当前实验还停留在：
   - `inflight_waiters -> inflight_zero_waiters`
   的改进，
   还没有进入：
   - `noninflight_prefetch_only`
   这一更强的解耦区间。

因此下一阶段不应继续盲目调阈值，而应正式收敛为一条新主线：

- **`PE-internal RowIndex Decoupled Frontier`**

一句话结构：

- **`earlier rowindex-only object issuance -> stable PE-local residency/ownership -> later exact consumer join/use -> exact core-private commit`**

它的重点不是再做一层 late join，而是让 `rowindex` 真正从“被 inflight demand 挟持的附属响应”变成一个更早、可独立、可复用、可闭环的 `PE` 内对象。

---

## 1. 当前 fresh 结论已经压实了什么

基于 fresh run：

- `off`: [20260403-113150](/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/runs/rowindex_object_off/20260403-113150)
- `on`: [20260403-113559](/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/runs/rowindex_object_on/20260403-113559)

关键结果是：

- `memctrl.req_total: 6212 -> 1886`
- `rowidx_ready_signal_rowindex_response_total: 690 -> 229`
- `rowidx_ready_signal_rowindex_response_inflight_waiters_total: 690 -> 87`
- `rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total: 0 -> 142`
- `rowidx_ready_signal_prefetch_response_total: 0 -> 142`
- `rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total: 0 -> 0`

这组数据说明：

1. 当前 on-case 已经进入收益空间，不是“完全没生效”；
2. 收益来自：
   - 一部分 demand 还没挂 waiter 时，prefetch-only 响应已经先返回；
3. 但这些返回仍然属于：
   - `InflightZeroWaiters`
   而不是
   - `NonInflightPrefetchOnly`
4. 也就是说，`rowindex` 目前还是一个：
   - **被 inflight owner/entry 挟持的对象**
   而不是一个：
   - **真正先于 demand 生命周期存在的独立对象**

---

## 2. 为什么当前还打不出 `noninflight_prefetch_only`

### 2.1 代码层的硬条件

从 [WeightMemorySubsystem.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc) 可见：

- `rowindex_prefetch_only` 条件是：
  - `!meta.has_single_cb`
  - `meta.bcsr_target_block_col == UINT32_MAX`
  - `!meta.bcsr_prefetch_all`
  - `!meta.bcsr_colidx_bulk_all_rows`

但 `NonInflightPrefetchOnly` 只有在 prefetch-only 响应不再落回 inflight waiter/owner 路径时才记账。

当前 fresh on-case 的 `142` 次都落在：

- `InflightZeroWaiters`

这说明：

- prefetch 请求虽然先回来了，
- 但它们仍然附着在 `inflight_colidx_` / owner-tracked 路径上；
- 只是“回包时 waiter 已空”，而不是“回包时对象已脱离 inflight 生命周期”。

### 2.2 当前实验口径为什么天然偏向 inflight

当前实验配置有三个重要特征：

1. `max_steps=2`
2. `gather/apply/scatter = 64/32/16`
3. `activation_fraction=0.02, fanout=8`

这意味着：

- 运行很短；
- row touch 形成后，真正消费者很快就跟上；
- prefetch 虽然能抢在 waiter 前回包，但大多仍处在同一小窗口内；
- 还来不及形成“独立 rowindex object 已常驻，而 exact consumer 稍后才出现”的状态。

### 2.3 当前对象生命周期也说明窗口不够深

在 fresh on-case 中：

- `atlas_service_atlas_obj_materialize_total = 256`
- `atlas_service_atlas_obj_ready_total = 20`
- `atlas_service_release_deferred_total = 256`
- `atlas_service_release_pending_active_total = 236`
- `rowidx_cache_fills_total = 128`
- `rowidx_cache_full_drop_total = 101`

这说明：

1. 物化了不少对象；
2. 真正进入 ready/release 闭环的很少；
3. 很多对象只是“被创建/挂起”，没有稳定跨过 ready/use/reuse；
4. cache/drop 也提示当前 residency 很不稳定。

所以今天的问题已经不是“有没有 object”，而是：

- **object 出现了，但它还没被放进一个足够早、足够久、足够可复用的 PE-local 生命周期里。**

---

## 3. 下一阶段正式主线：RowIndex Decoupled Frontier

下一阶段不再把 rowindex 视为：

- demand path 的副产物；

而是把它提升成：

- **PE 内更早 metadata frontier 上的正式对象。**

这条主线分三层。

### 3.1 第一层：把 `rowindex` 从 inflight 附属物提升为 object

需要回答四个问题：

1. 谁发起 rowindex-only issuance？
2. 对象何时 materialize？
3. residency 在哪一层持有？
4. 后续 consumer 是 join、hit，还是 fallback？

也就是说，下一阶段最重要的不是再加 bucket，而是把今天这条链写清楚：

- `touch -> issue -> inflight -> response -> ready -> residency -> later demand`

### 3.2 第二层：把 `service plane` 和 `commit plane` 继续切开

当前设计最稳的边界依然成立：

- shared service completion != logical commit

所以新的 rowindex frontier 也必须继续遵守：

1. rowindex/prefetch 可以更早、更独立；
2. consumer exact weight issue 仍保持原 contract；
3. architectural visibility 仍由 core-private 路径最终提交。

### 3.3 第三层：把实验问题收窄成“如何制造 decoupling”

下一阶段实验不再问：

- “开了 prefetch 后总收益多少”

而是优先问：

- “什么条件下 rowindex-only object 可以在没有 inflight waiter 的情况下独立完成，并在后续 exact consumer 出现时被使用？”

这就是 `noninflight_prefetch_only` 真正代表的架构命题。

---

## 4. 下一阶段必须补齐的 probe/metric

这轮需要补的 probe 分三类。

### 4.1 A 类：rowindex decoupling probe

目标：证明对象是否真的脱离 inflight 生命周期。

建议新增：

1. `rowidx_prefetch_only_issue_total`
2. `rowidx_prefetch_only_response_total`
3. `rowidx_prefetch_only_resident_hit_total`
4. `rowidx_prefetch_only_later_demand_join_total`
5. `rowidx_prefetch_only_later_demand_fallback_total`
6. `rowidx_prefetch_only_resident_cycles_total`

这些 probe 回答的是：

- prefetch-only 对象到底有没有先独立存在；
- 后续 demand 到来时到底是在 join/use，还是根本没吃到。

### 4.2 B 类：PE object lifecycle gap probe

目标：把 object plane 的缺口画完整。

建议新增：

1. `rowindex.owner_to_ready_cycles_total`
2. `rowindex.ready_to_first_consumer_cycles_total`
3. `rowindex.ready_to_release_cycles_total`
4. `rowindex.release_without_consumer_total`
5. `rowindex.release_after_consumer_total`
6. `rowindex.evicted_before_consumer_total`

这些 probe 回答的是：

- 现在 object 为什么 materialize 了却没进入 use/reuse；
- 是 ready 太晚、驻留太短，还是消费者根本没赶上。

### 4.3 C 类：PE local storage / control plane probe

目标：把 core 间通信与 local storage object model 连起来。

建议新增：

1. `pod_owner_lookup_hit_total`
2. `pod_owner_lookup_miss_total`
3. `pod_owner_lookup_ready_hit_total`
4. `pod_owner_lookup_live_owner_total`
5. `control_ready_fanout_consumer_distance_sum`
6. `storage_rowindex_resident_peak`
7. `storage_rowindex_reuse_distance_sum`
8. `storage_rowindex_evict_reason_capacity_total`
9. `storage_rowindex_evict_reason_window_end_total`

这些 probe 回答的是：

- core 间共享到底主要发生在 owner table、service object table，还是 cache/residency；
- 对象是被容量打掉，还是被窗口边界提早清走。

---

## 5. 新实验口径：专门拉开 request/ready separation

下一轮实验不建议继续只跑当前 `2026-03-31_atlas_service_rowindex_object_ab_v1` 这组短窗口 smoke。

建议新增一个隔离实验：

- `2026-04-03_rowindex_prefetch_only_windowsep_ab_v1`

核心思想不是改 correctness，而是刻意拉大：

- `row touch / prefetch issue`
  与
- `exact consumer arrival`

之间的时间分离。

### 5.1 推荐参数方向

1. 增加步数：`max_steps: 2 -> 8`
2. 拉长 gather：`64 -> 256`
3. 保持 apply/scatter 相对短：例如 `16/16`
4. 提高激活压力：`activation_fraction: 0.02 -> 0.08`
5. 提高 fanout：`8 -> 32`
6. 提高 rowidx budget：`2 -> 8`
7. 扩大 cache rows：`64 -> 256`

这个方向的逻辑是：

- gather 更长，会让 metadata/touch/frontier 更早积累；
- apply/scatter 更短，会减少后段拖尾；
- 更多 step 会增加跨窗口对象复用机会；
- 更大 prefetch budget 和 cache 则避免刚有苗头就被容量和速率打掉。

### 5.2 设计目标

这组实验不以 headline 性能为第一目标，而是优先看：

1. `noninflight_prefetch_only` 是否首次非零；
2. `ready_to_first_consumer` gap 是否可见；
3. `resident_hit` / `later_demand_join` 是否出现；
4. `cache_full_drop_rate` 是否下降。

只要这四条里有两条成立，这条主线就真正从“late inflight optimization”跨进了“earlier PE object optimization”。

---

## 6. 实现顺序

下一阶段建议严格分成三个小阶段。

### Stage P1：probe closure

先补 probes，不改行为。

目标：

- 把 `rowindex object` 的 issue/ready/residency/use/release 因果链补齐。

### Stage P2：window-separation experiment

只改 `mainexp` 隔离实验配置，不碰主线默认行为。

目标：

- 证明现有机制在更有利的口径下能否打出 `noninflight_prefetch_only`。

### Stage P3：frontier-issued rowindex object

若 P2 仍然无法打出该 bucket，再进入机制升级：

- 让更早 frontier 直接发起独立 rowindex-only object issuance，
- 而不是继续依附当前 inflight path。

---

## 7. 当前阶段的正式判断

当前我们不再处于“方案失效”的状态，而处于：

- **机制已生效，但对象还没有真正从 inflight demand 中独立出来。**

因此下一阶段最正确的推进不是回头去调小 patch，而是：

1. 补清 object/control/storage probes；
2. 用隔离实验主动制造 decoupling；
3. 若仍然打不出 `noninflight_prefetch_only`，就正式升级到更早 frontier-issued object path。

这才是从 `PULSE` 真正过渡到 `PE-Atlas` 的下一步。
