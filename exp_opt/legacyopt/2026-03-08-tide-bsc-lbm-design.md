# TIDE-BSC/LBM：真正可落地的 Memory × NoC 协同 Phase-2 设计

日期：2026-03-08  
状态：设计完成；dest-only bridge 已正式复测，但不进入主线  
依赖主线：`full_system_baseline = STORM + GAS + GCSS-GLIDE`

## 0. 这份设计要解决什么

当前已经验证有效的 `TIDE-L Phase-1` 本质上是一个 **local-band barrier**：

- 它不改变 `GAS` 语义；
- 不改变 `GCSS-GLIDE` 的地址顺序；
- 不改变 `memctrl.req_total`；
- 但它能减少 `unique_line_count_total`，降低 `apply_ns_avg`，并带来端到端时间收益。

这说明当前系统真正缺的，不是更激进的 issue 重排，也不是更细粒度的 token 调度，而是：

- **在 edge 被 materialize 之前，就让进入 memory front-end 的工作集更 band-coherent。**

因此，真正的 `TIDE Phase-2` 不应再是一个“后发制人的 issue policy”，而应是一个：

- `BSC`：block-scoped 的协同控制面
- `LBM`：band-scoped 的 lazy materialization 执行面

一句话定义：

- **`TIDE-BSC/LBM` = 用 block 级 band service 协调 `STORM` 的流量进入时序，再用 per-core lazy materialization 把进入 `WMS` 的工作集收敛成更强的 local-band clustering。**

这和失败路线有本质区别：

- 不是 `CHORD-L` 那样在 edge 已经形成后再改 issue 顺序；
- 不是 `PRISM` 那样把状态做回 token/segment 细粒度平面；
- 不是 `naive TASS` 那样只做 block 级聚合却没有真实的 DRAM-band 语义。

---

## 1. Phase-1 已经告诉了我们什么

### 1.1 已确认的正式事实

基于 `mainexp/experiments/2026-03-08_tide_l_ab_v1` 的正式主口径复测（`20260308-111813`），`TIDE-L Phase-1` 相比 `full_system_baseline` 已确认：

- `model.sim_time_actual_ns`: `257453 -> 226960`，约 `-11.84%`
- `gas.apply_ns_avg`: `239096 -> 211285.688`，约 `-11.63%`
- `memctrl.req_total`: `150907 -> 150907`，不变
- `gas_frontend_staged_reads_total`: `763879 -> 763879`，不变
- `gas_frontend_granules_built_total`: `150907 -> 150907`，不变
- `gas_unique_line_count_total`: `262838 -> 159708`，约 `-39.24%`
- `gas_frontend_line_touch_reuse_ratio`: `0.655917 -> 0.790925`，绝对提升约 `+13.50pct`
- `gas_frontend_staged_reads_per_unique_line_avg`: `2.90627 -> 4.78297`，约 `+64.57%`
- `gas_overfetch_bytes_stat_total`: `13766116 -> 7165796`，约 `-47.95%`

这组事实的含义非常重要：

1. 收益并不是来自“更少的 DRAM 请求数”，因为 `memctrl.req_total` 和 `granules_built_total` 都没有变化。
2. 收益来自 front-end 让同样的 staged reads 落在更少的 unique line 上，也就是更强的 line clustering / temporal reuse。
3. `TIDE-L` 已经证明“band-aware 的 local service 次序”有价值，但它仍然是 materialization 之后的优化。
4. 因此，现阶段最值得继续放大的，正是 `pre token -> edge materialization -> unique line set` 这一层的映射效率，而不是再去做激进的 downstream reorder。

### 1.2 Phase-1 的真正边界

`TIDE-L` 依然有明确局限：

- 它看到的是已经 materialize 完的 edge issue queue。
- 它只能在 `WMS` 的本地地址队列上做 band 边界控制。
- 它无法改变 `STORM` 流量进入 block 的时间结构。
- 它也无法改变 `SnnWorkload` 在收到 `pre_global` 时立刻展开 edge 的行为。

所以，`TIDE-L` 只是：

- **Phase-1：local front-end clustering stabilizer**

而不是最终的 memory × NoC 协同机制。

真正的 Phase-2 必须前移到：

- `pre_global` 还没有变成 edge 的那个时刻。

---

## 2. 设计结论

### 2.1 正的 TIDE-BSC/LBM 应该如何分层

最终建议采用双层结构，而不是单点塞进某一个类里：

### A. `TIDE-BSC`：Block Service Coordinator

职责：

- 维护 `2x2 destination block` 级的 `open_band` / `epoch` / `credit`
- 观察 block 级的 pending demand
- 决定当前优先服务哪个 `band`
- 可选地把 `open_band` 作为 hint 反馈给 `STORM`

它本质上是：

- **跨 core 的 block 级控制面**

所以它不应只存在于某个单 core 的 `WeightMemorySubsystem` 内部。

### B. `TIDE-LBM`：Lazy Band Materializer

职责：

- 接收 `pre_global` 粒度的 pending token
- 在 token 尚未展开为 edge 之前，先按 `band` 暂存
- 只在对应 `band` 被 `BSC` 打开时，才 materialize 成 edge / issue entry
- materialize 之后继续走当前稳定主线：
  - `GCSS-GLIDE`
  - `TIDE-L`
  - strict GAS retire

它本质上是：

- **per-core 的 memory front-end 执行面**

所以它最终必须和 `WeightMemorySubsystem` 紧耦合，但不等于它的 block 级控制状态也应全塞进 `WeightMemorySubsystem`。

### 2.2 最关键的结构判断

因此，真正正确的结构不是二选一，而是：

- **`BSC` 在 block / STORM ingress 侧形成共享控制面**
- **`LBM` 在 per-core / WMS 前形成 lazy materialization 执行面**

这是当前代码边界下唯一既合理又 solid 的组织方式。

---

## 3. 为什么必须这么分，而不是都塞进 WMS

### 3.1 都塞进 WMS 的问题

如果把 `BSC + LBM` 全做成 `WeightMemorySubsystem` 内部机制，会出现三个结构性问题：

1. `WMS` 是 per-core 实例，只天然看得到本 core 的 queue。
2. 它不拥有 `STORM` 的 block multicast 控制路径，无法自然表达 block 级 `open_band`。
3. 若把 block 级状态复制到 4 个 core 的 `WMS` 中，状态同步会变脏，而且概念上错位。

因此：

- `WMS` 很适合承载 `LBM` 的 materialization 与 local issue
- 但不适合单独承载 block-scoped `BSC`

### 3.2 都塞进 NoC 的问题

如果把 `BSC + LBM` 都放到 `SynapseRouteSubsystem / MulticastRouter` 一侧，也不对：

1. NoC 路径并不知道本 core 上 `GCSS-GLIDE` 的 exact local base/len。
2. 真正的 `band_id` 与 `addr` 映射在 `WMS` 最可靠。
3. `recordEdgeWithPreRankCount()`、`prepareGcssVlfIssueQueue_()`、strict retire 都在 `WMS`。

因此：

- NoC 侧适合 block 级 control / hint
- memory 侧适合 exact-band materialization / issue

### 3.3 所以该怎么切

正确切分如下：

- `BSC`：block-shared state + epoch/open_band policy
- `LBM`：per-core pending-pre queue + materialize-to-WMS
- `TIDE-L`：materialize 后的 local-band issue stabilizer

关系是：

- **`BSC` 决定“现在该服务哪个 band”**
- **`LBM` 决定“哪些 pre 现在真正展开”**
- **`TIDE-L` 决定“展开后的 issue 队列如何不跨 band 扰动”**

这样三者是前后衔接，而不是互相替代。

---

## 4. 真实运行时数据流

## 4.1 当前主线数据流

当前主线大体是：

1. `STORM` 把一个 `pre_global` 的 block fanout 送到目标 block / core
2. `SnnWorkload::deliverPacket()` / `expandPreGlobalToWindowEdgesFast_()` 很快把它展开为 edge
3. `WeightMemorySubsystem` 在 `BeginApply` 时把这些 edge 变成 `GCSS-VLF issue queue`
4. `TIDE-L` 只在这最后一步做 local band 边界控制

问题就在第 2 步：

- **展开太早了。**

一旦过早展开，后面只剩 edge 粒度对象，再想恢复更强的 block/band coherence，代价会明显变大。

## 4.2 新的数据流

`TIDE-BSC/LBM` 后的目标数据流应改成：

1. packet 到达 receiver
2. 不立即展开 edge
3. 先生成 `pending_pre_token`
4. `LBM` 基于 local exact band / block band-color，把 token 放入 `pending_pre_by_band`
5. `BSC` 选择 `open_band`
6. 仅 materialize `open_band` 内的 pre
7. materialized edge 再进入当前稳定的 `GCSS-GLIDE + TIDE-L + strict retire`

于是，真正进入 `WMS issue queue` 的对象，已经是被 band 收敛过的一批 pre，对应的 edge issue 自然更 line-coherent。

---

## 5. 关键抽象

## 5.1 `pending_pre_token`

`TIDE-LBM` 处理的基本对象不应是 edge，而应是：

- `pending_pre_token = {pre_global, count, first_arrival_cycle, src_meta(optional)}`

其中：

- `count` 表示当前窗口该 `pre_global` 被触发次数
- 对 `step1` 而言通常为 `1`，但设计上不应假定永远为 `1`

这样可以严格保留语义，同时避免把状态膨胀到 edge 粒度。

## 5.2 `local_exact_band`

每个 core 上，`pre_global` 的 exact local band 不需要单独存大索引：

- 直接用 `GCSS-GLIDE` 已有的 `pre -> base`
- 再由 `addr = base_addr + base * 4`
- 推导 `band_id = floor(addr / band_bytes)`

这意味着：

- `LBM` 的 exact band 判定天然应靠近 `WMS`

## 5.3 `block_band_color`

如果要让 block 内 4 个 core 协同，只靠每个 core 的 local exact band 还不够，需要一个 coarse 的 block-level 共享抽象：

- `block_band_color`

它不是 exact line，也不是 exact local band，而是：

- 一个 block-shared、coarse、可广播的 band 类别

离线 sidecar 存：

- `pre_global -> band_color`
- `pre_global -> span_class`
- `pre_global -> coherent_flag`

这样：

- `BSC` 看的是 block 共享颜色
- `LBM` materialize 时使用本 core 的 exact local band

这两个层次不会打架，反而形成 coarse-to-exact 的配合。

---

## 6. BSC 的正式定义

## 6.1 BSC 应放在哪里

从代码边界和未来硬件映射两方面看，`BSC` 最合适的逻辑位置是：

- **destination block ingress / block multicast control 侧**

也就是与下列路径强关联：

- `SynapseRouteSubsystem`
- `SpikeCommSubsystem`
- `MulticastRouter`

但实现上不应直接塞进其中任意一个大类，而应抽成一个新的 block-side sidecar：

- 建议新目录：`components/tide/` 或 `services/tide/`
- 建议核心对象：`TideBlockCoordinator`

这样做有三个好处：

1. 代码隔离，不污染现有主线类的职责。
2. 结构上符合“block-shared hardware unit”。
3. 后续 Phase-B 做 beacon/hint 时可以自然挂到 NoC 控制链。

## 6.2 BSC 的最小状态

每个 block 只需维护很小一组状态：

- `current_open_band`
- `current_epoch_id`
- `band_pending_tokens[B]`
- `band_pending_payload_est[B]`
- `band_oldest_age[B]`
- `band_open_credit[B]`
- `band_recent_service_debt[B]`

可选：

- `band_hot_hint[B]`
- `open_band_hit_total`
- `open_band_miss_total`

其中 `B` 不应太大，推荐：

- `32` 或 `64`

这在硬件上就是：

- 小 SRAM / register file
- 几个计数器
- 一个选通 FSM

非常可流片。

## 6.3 BSC 的选 band 策略

第一版必须极简而确定性，避免重复历史上过于聪明但不 work 的路线。

建议打分：

- 先比 `pending_payload_est`
- 再比 `oldest_age`
- 再比 `band_id`

配两个硬约束：

- `max_epoch_quota`
- `age_force_switch`

即：

- 能形成局部聚集
- 但不会饿死其他 band
- 完全确定性，可复现实验结果

## 6.4 BSC 输出什么

`BSC` 不直接发 DRAM 请求，它只输出：

- `open_band`
- `epoch_id`
- `credit_class`

这些信号可被两个地方消费：

1. receiver side `LBM`
2. source side `STORM` hint path（Phase-B）

---

## 7. LBM 的正式定义

## 7.1 LBM 不应该直接挂在 SnnWorkload 里做完整逻辑

`SnnWorkload` 负责把 packet 语义转成工作负载行为，这里适合做：

- 接收 packet
- 识别 `pre_global`
- 调用新的 pending-pre 接口

但不适合自己掌握完整 `band -> addr -> exact base` 逻辑，因为：

- 这些真值已经在 `WMS/GCSS-GLIDE` 里；
- 若在 `SnnWorkload` 再复制一套 band 解析，会造成重复、易漂移、难维护。

因此：

- `SnnWorkload` 只负责“别太早展开”
- `LBM` 的真正 band/exact-address 逻辑仍应进入 `WMS`

## 7.2 LBM 的建议实现形态

在 `WeightMemorySubsystem` 中新增一层前置结构：

- `pending_pre_tokens_curr_`
- `pending_pre_tokens_prev_`
- `pending_pre_by_band_`
- `materialized_pre_set_`

核心新增 API：

- `recordPendingPre(pre_global, count)`
- `preparePendingPreBandsForApply()`
- `materializeBandOnce(open_band)`

行为定义：

1. Gather 阶段到来的 `pre_global` 只记为 token
2. BeginApply 时把 `prev_window` token 翻转过来
3. 用 `pre -> base -> addr -> band` 解析 exact local band
4. 将 token 按 band 组织
5. 只有 `open_band` 对应的 token 会被真正展开成 edge
6. edge 一旦 materialize，就走当前稳定 `recordEdgeWithPreRankCount()` + `prepareGcssVlfIssueQueue_()` + `TIDE-L`

## 7.3 LBM 的 materialization 粒度

materialization 粒度必须保持在：

- `pre_global -> posts_local[]`

而不是：

- line 粒度 token
- edge 粒度 token

原因：

1. 这保持了当前 `expandPreGlobalToWindowEdgesFast_()` 的已有语义。
2. 仍然只在 pre 粒度持状态，规模可控。
3. 真正的 edge 只有在 band 打开时才出现，正好把过早展开的问题消掉。

## 7.4 LBM 和 TIDE-L 的关系

`LBM` 不是替代 `TIDE-L`，而是给 `TIDE-L` 喂一个更干净的输入。

链路应是：

- `pending_pre_token`
- `LBM materialize open_band`
- `GCSS-VLF issue queue`
- `TIDE-L local_band_barrier`
- strict retire

因此 `TIDE-L` 在 Phase-2 中应保留，角色升级为：

- **post-materialization local stabilizer**

---

## 8. 真正的 memory × NoC 协同发生在哪里

## 8.1 Phase-A：dest-only BSC/LBM

最稳的第一落地版不需要改包格式：

- sender 还是现有 `STORM`
- receiver 侧自己把到达 token 先按 band 缓存
- `BSC` 完全是 destination-driven

这版已经能验证：

- 更晚 materialize 是否进一步提升 frontend clustering
- 是否能在不改 NoC wire format 的前提下进一步降低 `apply_ns_avg`

这是最适合先落地的 Phase-2a。

## 8.2 Phase-B：open-band hint / beacon

如果 Phase-A 有效，再上真正的 NoC 协同：

- block 侧 `BSC` 在 epoch 切换时产生小 beacon
- sender/route path cache 最近的 `open_band`
- `SpikeCommSubsystem` 在多个待发目标 block 之间优先发命中 `open_band` 的流量

注意这不是改变 fanout 语义，而只是：

- **对 ready packet 的发送顺序做 destination-driven 的 band-aware bias**

因此仍可保持语义不变。

## 8.3 为什么这个协同是新的

这条路线的创新点不是“又做一个 prefetcher”，而是：

- 让 `STORM` block-multicast 的 block 级服务域
- 和 `GCSS-GLIDE` 的真实地址 band 服务域
- 首次在一个统一的 block-local protocol 下对齐

这比 naive block batching 或 global credit 都更物理真实。

---

## 9. 代码落点建议

## 9.1 新增代码应强隔离

建议新增独立目录，而不是把逻辑继续堆进现有大类：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/tide/`

建议文件：

- `TideBlockCoordinator.h/.cc`
- `TideTypes.h`
- `TideStats.h`

## 9.2 现有代码的最小接入点

### Receiver / workload 侧

文件：

- `services/workload/snn/SnnWorkload.cc`

接入点：

- `deliverSpike()`
- `expandPreGlobalToWindowEdgesFast_()`
- `onGasStageEvent(BeginApply)`

改法：

- 在 `TIDE-BSC/LBM` 开启时，不再立即 full expand
- 改成调用 `weight_mem_subsystem_->recordPendingPre(...)`

### Memory front-end 侧

文件：

- `services/synapse/weights/WeightMemorySubsystem.h`
- `services/synapse/weights/WeightMemorySubsystem.cc`

接入点：

- gather/apply window flip
- `issueFromEdgesOnce_()` 前
- `prepareGcssVlfIssueQueue_()` 前

改法：

- 新增 token queue / band queue / materialize path
- `materializeBandOnce()` 产出 edge 后复用现有主线

### NoC / block control 侧

文件：

- `services/synapse/route/SynapseRouteSubsystem.*`
- `services/synapse/route/SpikeCommSubsystem.*`
- `components/noc/MulticastRouter.*`

接入方式：

- Phase-A：只增加与 `TideBlockCoordinator` 的控制连接，不改 wire format
- Phase-B：再加 beacon/hint path

---

## 10. 语义与验证边界

## 10.1 什么不能变

必须保持：

- `GAS` superstep 语义不变
- `BeginGather / BeginApply / BeginScatter` 边界不变
- `orch_.acc_update(post_local, delta)` 的最终结果不变
- strict validation 仍要求 `fail=0 warn=0`

## 10.2 为什么这个设计原则上是安全的

因为该设计只改变：

- **某个 `pre_global` 在 apply 阶段何时被 materialize 成 edge**

而不改变：

- 该 `pre_global` 影响哪些 `post_local`
- 每个 edge 的 `count`
- materialize 后的地址与 weight 真值
- retire / accumulate 的严格顺序

所以它是：

- **前端 admission / materialization 时序优化**

而不是数值语义优化。

---

## 11. 闭环实验设计

## 11.1 Phase-2a：dest-only BSC/LBM

A/B 矩阵：

1. `full_system_baseline`
2. `tide_l_phase1`
3. `tide_bsc_lbm_destonly`

要求：

- 全部使用 `ramulator2`
- 全部 `4x4 bcsr10k step1`
- 全部 strict validation 通过

主指标：

- `sim_time_actual_ns`
- `gas.apply_ns_avg`
- `gas.unique_line_count_total`
- `gas.payload_bytes_per_unique_line_avg`
- `gas.frontend_line_touch_reuse_ratio`
- `gas.frontend_staged_reads_per_unique_line_avg`
- `gas.memctrl_payload_utilization`

判据：

- 若 `memctrl.req_total` 仍近似不变，但 `frontend reuse` 继续提升，且 `apply_ns_avg` 再降，则说明方向正确。

## 11.2 Phase-2b：BSC + beacon/hint

A/B：

1. `tide_bsc_lbm_destonly`
2. `tide_bsc_lbm_beacon`

重点看：

- block 级 open-band hit ratio
- receiver queue depth / wait
- tail latency 是否下降

---

## 12. 必须新增的统计

### BSC 侧

- `gas_tide_bsc_epoch_open_total`
- `gas_tide_bsc_band_switch_total`
- `gas_tide_bsc_open_band_hits_total`
- `gas_tide_bsc_open_band_misses_total`
- `gas_tide_bsc_pending_tokens_peak`
- `gas_tide_bsc_pending_payload_peak`

派生：

- `gas_tide_bsc_open_band_hit_ratio`
- `gas_tide_bsc_avg_tokens_per_epoch`

### LBM 侧

- `gas_tide_lbm_pending_pres_total`
- `gas_tide_lbm_materialized_pres_total`
- `gas_tide_lbm_deferred_pres_total`
- `gas_tide_lbm_fallback_wide_pres_total`
- `gas_tide_lbm_materialized_edges_total`
- `gas_tide_lbm_materialized_payload_bytes_total`

派生：

- `gas_tide_lbm_materialize_ratio`
- `gas_tide_lbm_edges_per_materialized_pre_avg`

### NoC 协同侧（Phase-B）

- `storm_tide_beacon_seen_total`
- `storm_tide_hint_match_total`
- `storm_tide_hint_miss_total`
- `storm_tide_band_biased_send_total`

---

## 13. 实现顺序建议

### P0

- 保留当前 `TIDE-L Phase-1` 作为稳定主线
- 完成 frontend 统计证据链

### P1

- 落地 `dest-only TIDE-BSC/LBM`
- 不改 wire format
- 不做 sender bias

### P2

- 引入 block-side `TideBlockCoordinator`
- 把 `open_band` 真正从 block 层驱动到各 core `LBM`

### P3

- 引入 beacon/hint
- 让 `STORM` 发送顺序和 `open_band` 形成真正闭环

---

## 14. 最终判断

真正的 `TIDE-BSC/LBM` 不应被理解为“更复杂的 TIDE-L”，而应理解为：

- `TIDE-L` 解决的是 **materialize 之后** 的 local band 稳定性
- `TIDE-BSC/LBM` 解决的是 **materialize 之前** 的 block-band admission 与展开时机

所以这条路线真正的精髓是：

- **把优化前移到 pre-token -> edge 的边界，同时把 block multicast 的进入时序和 DRAM address band 的服务时序第一次绑定在一起。**

这正是当前体系里最 solid、最不偏离主线、也最有论文潜力的下一步。

---

## 16. 复测后的主线处置（2026-03-08）

基于正式复测：

- `mainexp/experiments/2026-03-08_tide_bsc_lbm_destonly_ab_v1/snapshot/compare.tsv`
- baseline：`runs/full_system_baseline/20260308-123035`
- dest-only：`runs/tide_bsc_lbm_destonly_8k/20260308-123035`
- 对照 `TIDE-L`：`mainexp/experiments/2026-03-08_tide_l_ab_v1/snapshot/compare.tsv`

当前 `dest-only TIDE-BSC/LBM` 的最终定位已经可以明确：

### 16.1 这条路已经证明了什么

1. `pending pre_rank merge` 修正后，`dest-only` 已不再放大 logical issue。
- `memory_requests = 763879 -> 763879`
- `gas.payload_bytes_total = 3055516 -> 3055516`
- `gas.frontend_staged_reads_total = 763879 -> 763879`
- `memctrl.req_total = 150907 -> 150907`

2. 它是 **语义正确** 的 bridge。
- 两边 `validation.log` 都是 `fail=0 warn=1 strict=0`
- warning 仍然只是 step-limited within-step cascade，不是新回归。

3. `pre-rank -> band -> lazy issue` 这条抽象路径本身是可工作的。
- `sim_time_actual_ns = 257453 -> 227273`
- `gas.apply_ns_avg = 239096 -> 211628.125`
- `gas.unique_line_count_total = 262838 -> 159708`

### 16.2 它为什么不进入主线

关键原因不是“没收益”，而是：

- 它的收益几乎完全追平当前 `TIDE-L 8KB`，但 **没有继续越过它**；
- 它没有把收益推进到更低的 `memctrl.req_total` 或更高的 `payload_bytes_per_memctrl_req_avg`；
- 相反，在控制面额外复杂度下，它的 `HOL / boundary stall` 还略差于 `TIDE-L`：
  - `sim_time_actual_ns = 227273` vs `226960`
  - `gas.apply_ns_avg = 211628.125` vs `211285.688`
  - `gas.tide_band_boundary_stall_total = 646204` vs `645201`
  - `gas.retire_global_hol_cycles_total = 66150450` vs `65459877`

这说明：

- **纯 receiver-side 的 `BSC/LBM dest-only`，本质上仍是在重排/延后“同一批工作集”的进入时序；**
- 它能把 `TIDE-L` 的行为重新走通，却没有改变跨 NoC 传过来的工作 granule；
- 因此它不足以成为新的系统主线，只能作为：
  - `semantic bridge`
  - `feasibility proof`
  - `negative lesson with a positive control`

### 16.3 主线决策

因此本设计文档现在应按如下口径理解：

- `TIDE-BSC/LBM dest-only`：**冻结为实验性桥接路径**
- 不继续扩展 sender/open-band 复杂控制面
- 不作为论文主线正向结果单独引用
- 真正的主线仍回到：
  - `TIDE-L` 作为稳定 memory-side local-band stabilizer
  - `STORM` 作为稳定 NoC multicast data plane
  - 下一跳必须是 **改变跨层工作 granule 的协同机制**，而不是继续在 receiver 末端加控制面

### 16.4 对下一步的约束

如果未来还要重新打开 `BSC` 路线，必须至少满足以下任一条件：

1. 明确降低 `memctrl.req_total`
2. 明确提高 `gas.payload_bytes_per_memctrl_req_avg`
3. 或在不恶化 memory 指标的前提下，显著降低 `HOL / boundary stall` 到优于 `TIDE-L`

在没有满足这些条件之前，这条路径不再继续主线化投入。
