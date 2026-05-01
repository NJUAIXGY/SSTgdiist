# PE RowIdx Prefetch Frontier Gap v1

> 日期：2026-04-03  
> 状态：code-backed analysis + fresh mainexp closure  
> 目标：冻结一个关键判断：当前 `rowidx prefetch` 已经进入 `inflight_zero_waiters`，但还没有进入真正的 `noninflight frontier`；这不是简单 workload 没调好，而是 today machine 仍停在 `inflight-owned completion`。

---

## 1. 一句话结论

当前 `rowindex_object_on` 的 fresh run 已经证明：

- `prefetch` 的确可以先于 demand 完成一部分工作；
- 但这些 completion 仍然全部附着在 `inflight_colidx_` 这个 demand-visible inflight object 上；
- 因此 today 的 rowidx 路径最多只能到：
  - `inflight_waiters`
  - `inflight_zero_waiters`
- 还到不了：
  - `noninflight_prefetch_only`

换句话说：

- **我们现在看到的是 `prefetch-before-demand`，还不是 `prefetch-decoupled frontier object`.**

---

## 2. fresh evidence

实验目录：

- [mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1](/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1)

fresh run：

- [rowindex_object_on/20260403-115724](/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/runs/rowindex_object_on/20260403-115724)

关键统计：

- `memctrl.req_total = 1886`
- `rowidx_prefetch_rows_total = 142`
- `rowidx_prefetch_complete_inflight_miss_total = 0`
- `rowidx_prefetch_complete_zero_waiters_total = 142`
- `rowidx_prefetch_complete_waiters_total = 87`
- `rowidx_ready_signal_rowindex_response_inflight_waiters_total = 87`
- `rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total = 142`
- `rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total = 0`

这组数据的含义非常直接：

1. `142` 个 prefetch completion 在响应返回时仍然能找到 inflight entry，但 entry 上没有 waiter；
2. `87` 个 prefetch completion 在响应返回时能找到 inflight entry，且 waiter 已经挂上；
3. `0` 个 prefetch completion 在响应返回时找不到 inflight entry。

因此：

- current rowidx prefetch completion **100% still lands in inflight-owned response handling**。

---

## 3. today control flow

### 3.1 prefetch issue path

核心代码在：

- [WeightMemorySubsystem.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc)

相关函数：

- `noteExperimentalNocRowidxTouch_`
- `drainExperimentalNocRowidxPrefetch_`

today 流程是：

1. `touch` 把 `block_row` 放入 `experimental_noc_rowidx_pending_rows_`
2. `drainExperimentalNocRowidxPrefetch_` 对该 row 发出 colidx read
3. 发请求前就先建立：
   - `inflight_colidx_[makeInflightKey_(window_seq_, block_row)]`
4. 这个 inflight entry 带着：
   - `window_seq`
   - `block_row`
   - `row_start/row_end`
   - `waiters`
   - `experimental_noc_rowidx = true`

这里最关键的一点是：

- **prefetch 不是发往一个独立 frontier object，而是复用了 demand path 的 inflight_colidx_ object model。**

### 3.2 demand join path

需求侧入口在：

- `requestBCSR_`

当 demand 访问同一个 `block_row` 且 `rowIndexGet` miss 时：

1. 查 `inflight_colidx_`
2. 找到就直接把 waiter 挂到这个 inflight entry 上
3. 如果 inflight 已经 issued，则不再发新的 rowindex request

这说明：

- today 的 prefetch / demand 统一收敛到同一个 inflight rowidx object；
- prefetch 不是独立存在的一条 owner-less completion plane。

### 3.3 response path

关键分类代码在：

- `WeightMemorySubsystem.cc:3901`
- `WeightMemorySubsystem.cc:4170`

`rowindex_prefetch_only` 的判断是：

- `!meta.has_single_cb`
- `meta.bcsr_target_block_col == UINT32_MAX`
- `!meta.bcsr_prefetch_all`
- `!meta.bcsr_colidx_bulk_all_rows`

但即便满足这个条件，response 仍然先查：

- `inflight_colidx_.find(inflight_key)`

只有两类主结果：

1. 找到 inflight：
   - `waiters.empty() -> InflightZeroWaiters`
   - `!waiters.empty() -> InflightWaiters`
2. 找不到 inflight：
   - `NonInflightPrefetchOnly`

fresh run 的新 probe 证明：

- today 实际只走到了前两类。

---

## 4. 为什么 noninflight 现在没有被打出来

### 4.1 不是“prefetch 不够早”

如果 prefetch 不够早，我们只会看到：

- `inflight_waiters`

但现在我们已经看到：

- `prefetch_complete_zero_waiters_total = 142`

这说明 prefetch 已经足够早到能在 response 时没有 waiter。

### 4.2 真正缺的是“completion authority decoupling”

当前设计里，prefetch completion 的 authority 仍被绑在：

- `inflight_colidx_`

于是即便 response 到来时没有 waiter：

- 它也只是 `InflightZeroWaiters`

而不是：

- 一个已经脱离 inflight owner 的 frontier-ready object。

`NonInflightPrefetchOnly` 只有在 response 到来时：

- inflight object 已不存在

才会被记账。

但 today 的 rowidx prefetch path 不会主动把 completion 升格成：

- `frontier resident rowindex object`
- `owner-decoupled ready object`
- `cache-only / service-only retained object`

所以这个 bucket 在 current machine 下接近结构性不可达。

### 4.3 object-plane 证据也支持同一结论

fresh run 中：

- `atlas_service_owner_form_total = 256`
- `atlas_service_join_live_total = 162`
- `atlas_service_ready_transition_total = 20`
- `atlas_service_release_deferred_total = 256`
- `atlas_service_release_pending_active_total = 236`

这说明当前 rowindex object-plane 的主语仍然是：

- owner / join / ready / release

而不是：

- resident frontier object

ready 只发生 `20` 次，远小于 `142` 个 zero-waiter prefetch completion，这进一步说明：

- completion 和 object-plane residency 之间还没有建立更深的 decoupled contract。

---

## 5. 对下一阶段的具体要求

下一阶段不要再继续做“更猛 workload 看看 noninflight 会不会自己出来”。

正确方向是：

### B1. 显式分离两类 rowidx object

把 today 的单一 inflight rowidx object 拆成两类：

1. `response-owned inflight object`
2. `frontier-retained rowidx object`

后者需要具备：

- window-scoped residency
- ready-before-demand visibility
- later-demand attach/hit
- release / stale / cross-window eviction

### B2. 在 response 时支持 frontier promotion

当 prefetch response 返回且 `waiters.empty()` 时，不应只记：

- `InflightZeroWaiters`

而应允许：

1. inflight object 退场
2. rowidx frontier object 入驻
3. 后续 demand 在不依赖 inflight key 的情况下命中这个 frontier object

只有这样，`NonInflightPrefetchOnly` 才是真正的 machine state，而不是 today 统计表里的一个未接通 bucket。

### B3. 下一批必须新增的 probe

最低优先级 probe：

1. `rowidx_frontier_promote_total`
2. `rowidx_frontier_resident_peak`
3. `rowidx_frontier_late_demand_hit_total`
4. `rowidx_frontier_stale_evict_total`
5. `rowidx_frontier_cross_window_drop_total`

如果没有这组 probe，我们仍然只能看到：

- response 时有没有 waiter

但看不到：

- prefetch completion 之后，它是否真的在 PE 内部留下了一个可消费对象。

---

## 6. 本轮实现完成了什么

本轮已经把 rowidx completion probe 从代码接到实验链路：

代码：

- [ExperimentalNocPrefetchPeStats.h](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/ExperimentalNocPrefetchPeStats.h)
- [WeightMemorySubsystem.h](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h)
- [WeightMemorySubsystem.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc)
- [SnnPESubComponent.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc)
- [MultiCorePE.h](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h)
- [MultiCorePE.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc)
- [compute_essential_summary_mesh.py](/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py)
- [make_snapshot.py](/home/xgy/remote/mainexp/experiments/2026-03-31_atlas_service_rowindex_object_ab_v1/make_snapshot.py)

验证：

- header/unit test 已通过
- summary unit test 已通过
- fresh `mainexp` run 已产出新 probe

因此下一阶段已经可以明确转向：

- **不是继续追求“让 zero_waiters 更大”，而是实现 `frontier-retained rowidx object`。**
