# PRISM-WAVE：窗口级 pre->segment 聚合与 line 去重设计

> 日期：2026-03-08  
> 状态：设计文档（待实现）  
> 基线：`full_system_baseline = STORM(multicast_mesh) + GAS + GCSS-GLIDE`  
> 上一版负探索：`PRISM-SEG` 最小直连版

## 0. 一句话结论

`PRISM-SEG` 当前失败，不是因为 “pre token -> segment service” 这个方向错了，而是因为当前实现把 **segment service 的触发粒度做得过细**。

当前版本虽然把 `PRISM-RX` 接到了 `WeightMemorySubsystem`，但它仍然接近：

- 来一个 token / 一个 apply tick
- 就 materialize 一次
- 就对该次可见的 `(pre_global -> items)` 做一次 segment line service

这会导致：

- 同一窗口里的同一个 `pre_global`
- 在多个 apply tick 上被重复 materialize
- 在 `WeightMemorySubsystem` 中被重复规划 line
- 甚至对同一条 line 反复发起请求

因此，下一步正确方向不是继续给当前 `PRISM-SEG` 做局部调参，而是把它升级为：

- **`PRISM-WAVE`**
- 展开：**`P`RISM `W`indow-`A`ggregated `V`alue `E`ngine**

它的核心思想是：

- 在一个 GAS window 内，把 `pre token` 先聚合成 **window-unique pre service set**；
- 在 `WeightMemorySubsystem` 内把 segment service 的最小实际请求粒度收敛为 **window-unique `(pre_global, line_addr)`**；
- 同时保留现有的 deterministic retire，不改变 `orch_.acc_update(post_local, delta)` 的语义边界。

也就是说：

- **NoC 保持 pre/token 语义**
- **memory 保持 pre-major / line-granular 语义**
- **中间不再按 token 重复触发 line service**

这才是 `PRISM` 路线在当前主线上的正确收敛形态。

## 1. 为什么当前 PRISM-SEG 会失败

### 1.1 已有证据

基于刚完成的正式复测：

- `PRISM-RX` 正式 run：
  - `mainexp/experiments/2026-03-08_prism_rx_ab_v1/runs/prism_rx/20260308-030143`
  - `validation: fail=0 warn=1`
  - `snn_rx.prism_materialized_edges_total = 19,426,479`
  - `snn_rx.prism_token_entries_peak = 1,689,060`
  - `prism_pres_total = 8,843,654`

- `PRISM-SEG` 正式 run：
  - `mainexp/experiments/2026-03-08_prism_rx_ab_v1/runs/prism_seg/20260308-030657`
  - 超过 `32` 分钟 wall time 未完成，被人工中止

- `PRISM-SEG` smoke（`step_activation_fraction=0.001`）也明显异常变慢：
  - baseline smoke wall time：`2:00.84`
  - `prism_seg` smoke 远超这个量级仍未完成，被人工中止

这说明问题不是“只在高负载下偶然爆”，而是当前运行时结构本身存在严重的 request / event 规模放大。

### 1.2 最可信的根因

当前 `PRISM-SEG` 的关键路径是：

1. `SnnWorkload` 在接收侧把 packet 保留为 PRISM token / edge count；
2. 一旦进入 `Apply` 且 `prism_edge_counts_curr_` 非空，就在 `onClockTick()` 里立即：
   - `materializePrismEdgesToWeightSubsystem_()`
   - `weight_mem_subsystem_->issueFromEdges()`
3. `WeightMemorySubsystem` 把本次看到的 `(pre_global, items)` 立即转换成 line request queue；
4. line response 回来后，直接驱动这批 targets retire。

这个路径的最大问题是：

- `prism_edge_counts_curr_` 是“当前时刻可见的增量集合”，不是“整个窗口内关于这个 pre 的最终全集”；
- 因此同一个 `pre_global` 如果在多个 tick 上持续出现，就会被分裂成多个增量 materialization；
- 而当前 `WeightMemorySubsystem` 没有维护“window 级 pre / line 已服务集合”；
- 所以它可能对同一个 `pre_global` 的同一条 line 多次规划、多次请求。

换句话说，当前 `PRISM-SEG` 实际上并没有真正把 request 粒度降到：

- `window-unique pre`
- 或 `window-unique line`

而更接近：

- `tick-local token batch`

这会天然把请求数量向 `prism_pres_total` 那个量级拉，而不是向 baseline 的 `memctrl.req_total` 量级收敛。

## 2. 设计目标

`PRISM-WAVE` 只追求一个核心目标：

- **让一个 GAS window 内，对同一个 `pre_global` 的 segment line service 只发生一次或极少数“增量”次数。**

更具体地说，目标是：

1. **不改语义**
- 不改 `GAS` 的 gather/apply/scatter 逻辑定义；
- 不改 `orch_.acc_update(post_local, delta)` 的局部副作用边界；
- 不引入跨 post 的提交乱序；
- retire 仍保持 deterministic。

2. **不改 DRAM 真值口径**
- 实际请求仍是 line-sized request；
- 仍走当前 `ramulator2` 后端；
- `payload_utilization` 等 summary 口径保持可比。

3. **把请求粒度从 token 降到 window-unique line**
- 同一窗口内：
  - 同一个 `pre_global`
  - 同一条 `line_addr`
- 最多只允许一次真实 DRAM request；
- 后续新到的 targets 只能：
  - 挂到 pending line 上；
  - 或命中窗口内 resident line buffer。

4. **只做窗口内 exact dedup，不做跨窗口 cache**
- 避免把机制变成“缓存论文”；
- 避免额外语义复杂性；
- 让创新点始终聚焦在：
  - `NoC pre token granule`
  - 到
  - `DRAM segment line granule`
  - 的统一。

## 3. 候选路线对比

### 3.1 方案 A：Apply tick 微批聚合

做法：

- 保留现有 `onClockTick()` flush 结构；
- 只是把多个 tick 的 token 累一小段再发。

优点：

- 改动最小；
- 容易落地。

缺点：

- 本质上仍然是“多次 materialize + 多次 line service”；
- 只是在 tick 上做粗粒度 batching；
- 很难给出强的体系结构叙事。

### 3.2 方案 B：Window 级 unique-pre + unique-line service

做法：

- `SnnWorkload` 把整个 window 内看到的 PRISM token 聚合成 unique-pre state；
- `WeightMemorySubsystem` 对每个 `pre_global` 维护 window 级 line service state；
- 只在第一次触及一条 line 时发真实 DRAM request；
- 后续 target 只做 attach 或 resident-hit。

优点：

- 直接打当前根因；
- request 粒度真正下降到 window-unique line；
- 与 `GCSS-GLIDE` 的 pre-major values 布局天然一致；
- 保持语义最干净。

缺点：

- 比方案 A 多一层 state machine 与窗口级 exact buffer。

### 3.3 方案 C：直接走 block-shared 协同（跳到 SURGE/TASS）

做法：

- 不先修 PRISM 单 PE 路线；
- 直接上 block/cohort 级共享 service。

优点：

- 潜在收益更大；
- 更接近最终 memory × NoC 协同故事。

缺点：

- 当前风险太高；
- 在 `PRISM-SEG` 连单 PE 路线都还没收敛前，直接做 block-shared 只会放大不确定性。

### 3.4 推荐结论

**推荐方案是 B：Window 级 unique-pre + unique-line service。**

原因很直接：

- 它刚好修正了当前 `PRISM-SEG` 的根因；
- 它复用 `PRISM-RX` 已经建立的 packet/token 桥接；
- 它复用 `GCSS-GLIDE` 已经建立的 pre-major / pre-rank / line-oriented values 布局；
- 它仍然是一个单 PE 内的 exact service 机制，容易严格验证；
- 它未来还能自然升级成 block-level / cohort-level 协同，而不是推倒重来。

## 4. 推荐方案：PRISM-WAVE

## 4.1 核心原则

`PRISM-WAVE` 的核心原则是：

- **token 可以多次到达**
- **edge 可以多次累加 count**
- **但 line service 在一个窗口里应尽量唯一**

因此它分成两个层次：

1. **Window Aggregate Layer（WAL）**
- 位置：`SnnWorkload`
- 作用：把多个 tick / 多个 packet 到达的 PRISM token 聚合成 window-unique pre state

2. **Window Value Engine（WVE）**
- 位置：`WeightMemorySubsystem`
- 作用：把 unique-pre state 转成 window-unique line service，并对 late-arriving targets 做 attach / resident-hit

这就是 `WAVE` 名字的来源：

- **Window Aggregated Value Engine**

## 4.2 运行时对象

### 4.2.1 `SnnWorkload`：`PrismWindowAggregateTable`

新增一个窗口级聚合表，按 `pre_global` 组织：

```text
pre_global -> {
  items_by_post_pre_rank,
  total_count,
  dirty,
  sealed_epoch,
  exported_epoch
}
```

其中：

- `items_by_post_pre_rank`
  - 仍然保存 `(post_local, pre_rank) -> count`
  - 与当前 `prism_edge_counts_curr_` 相比，不再是“当前 tick 的临时桶”，而是整个 window 的累计状态
- `dirty`
  - 表示该 `pre_global` 自上次导出后又有新增量
- `sealed_epoch`
  - 用来保证窗口内导出顺序稳定
- `exported_epoch`
  - 表示哪些增量已经交给 `WeightMemorySubsystem`

### 4.2.2 `WeightMemorySubsystem`：`PrismWindowServiceTable`

按 `pre_global` 维护 segment 服务态：

```text
pre_global -> {
  base,
  len,
  lines[line_addr] = {
    state: Pending | Resident,
    waiting_targets,
    line_bytes(optional)
  },
  issued_line_count,
  resident_line_count
}
```

这里最关键的是：

- `Pending`
  - 该 line 已经发请求，但还没回包；
  - 新到的 target 只能 append 到 `waiting_targets`
- `Resident`
  - 该 line 已回包，line bytes 暂存在窗口级 buffer；
  - 新到的 target 直接本地命中，不再发 DRAM request

这意味着：

- 同一窗口内的同一 line
- 最多只有第一次会真的打到 DRAM

## 5. 详细数据流

### 5.1 Gather / RX 阶段

`PRISM-RX` 继续保留当前成功部分：

- `SpikeKey / SpikeTileKey`
- 在接收侧保留 `pre token`
- 不回退成 fallback spikes

但在 `SnnWorkload` 中，token 不再进入“tick-local materialize 队列”，而是进入：

- `PrismWindowAggregateTable`

对于每个 `(pre_global, post_local, pre_rank)`：

- 若该 edge 首次出现：插入并记 `count=1`
- 若此前已经出现：只累加 `count`
- 将该 `pre_global` 标为 `dirty`

### 5.2 Apply 阶段：导出策略

当前最危险的逻辑是：

- 每个 tick 只要有 `prism_edge_counts_curr_` 就立刻 materialize

`PRISM-WAVE` 改为：

- 只导出 **window-unique pre 的增量快照**
- 而不是导出整个 pre 的重复副本

具体规则：

1. `BeginApply`
- 扫描所有 `dirty pre_global`
- 为每个 pre 导出一个稳定排序的 `items snapshot`
- 标记 `exported_epoch = current_epoch`
- 交给 `WeightMemorySubsystem::recordPrismWindowDelta(...)`

2. `Apply` 期间若有 late-arriving token
- 只更新 `PrismWindowAggregateTable`
- 不立即对整个 pre 重发 snapshot
- 仅当该 pre 出现“新 edge”或“新 count delta”时，导出一个 **delta snapshot**

这样，运行时对同一个 `pre_global` 的视角变成：

- 有一个长期存在的 window state
- 不再是反复创建新的临时 token batch

### 5.3 `WeightMemorySubsystem`：delta 到 line service

`recordPrismWindowDelta(pre_global, delta_items)` 的工作不是“重新规划整个 pre”，而是：

1. 查询 / 创建该 pre 的 `PrismWindowServiceEntry`
2. 对每个 `delta_item`：
- 计算它落在哪条 `line_addr`
- 查该 line 的状态

3. 三种情况：
- `Absent`
  - 创建新 line entry
  - 把 target 放入 `waiting_targets`
  - 发起一次真实 DRAM request
- `Pending`
  - 不发新请求
  - 只把 target append 到 `waiting_targets`
- `Resident`
  - 不发新请求
  - 直接从 resident `line_bytes` 取值并使 target ready

这就把 “重复 pre” 的问题，降解成 “同一窗口里只服务新的 line 或 attach 到已有 line”。

## 6. 语义与确定性

### 6.1 不改变 acc_update 语义

该设计不改变：

- `orch_.acc_update(post_local, delta)` 只更新该 `post_local` 的局部累加状态
- apply 中不触发 spike / early-exit / STDP / 跨 post 副作用

因此：

- 即使 line response 返回顺序与 target attach 顺序变化
- 最终仍然只需要通过现有 deterministic retire 机制提交即可

### 6.2 retire 不需要变

`PRISM-WAVE` 仍沿用当前已有的：

- `registerEdgeRetire_()`
- `setEdgeRetireReady_()`
- `tryRetireEdges_()`

唯一变化是：

- 一个 line response 现在可能唤醒：
  - 首次请求的 targets
  - 外加后来 attach 的 targets

但它们各自仍持有独立的 `retire_seq`，因此：

- ready 顺序可以变化
- commit 顺序仍由 retire 保证

这与当前 `PRISM-SEG` 的语义边界完全一致，只是把 line service 从“反复发请求”改成了“exact dedup + attach”。

### 6.3 为什么这不会破坏严格验证

因为我们没有改变：

- 一个 edge 应读取的 weight 值
- 一个 edge 的 count
- 一个 edge 最终乘到哪个 `post_local`
- 最终提交到 `acc_update` 的顺序约束

我们只改变：

- 一个窗口内，对同一条 line 的物理请求次数
- line 回来后，哪些 targets 共用这次回包

这属于：

- **memory service 组织变化**
- 不属于：
- **algorithm / semantic 变化**

## 7. 需要新增的统计

为了证明 `PRISM-WAVE` 真正解决了当前问题，需要补 3 组统计。

### 7.1 `SnnWorkload` 侧：window 聚合统计

新增：

- `snn_rx_prism_window_unique_pres_total`
- `snn_rx_prism_window_unique_edges_total`
- `snn_rx_prism_window_delta_exports_total`
- `snn_rx_prism_window_pre_revisits_total`

意义：

- 证明 token 进入窗口后，最终收敛成多少 unique pre / unique edge
- 证明同一 pre 在一个窗口里被 revisit 了多少次

### 7.2 `WeightMemorySubsystem` 侧：line dedup 统计

新增：

- `prism_wave_unique_line_requests_total`
- `prism_wave_pending_attach_total`
- `prism_wave_resident_hits_total`
- `prism_wave_line_reissue_avoided_total`
- `prism_wave_resident_line_peak`

意义：

- 证明一条 line 是否只被请求一次
- 证明 late-arriving target 有多少 attach 到 pending line
- 证明有多少 target 直接命中 resident line

### 7.3 summary 派生指标

在 `compute_essential_summary_mesh.py` 中新增：

- `prism.wave_avg_targets_per_unique_line`
- `prism.wave_line_reuse_hit_rate`
- `prism.wave_req_reduction_vs_naive_est`
- `prism.wave_unique_lines_per_pre_avg`

意义：

- 证明 `PRISM-WAVE` 的 request 粒度已经接近“window-unique line”而非“token batch”

## 8. 闭环实验方案

## 8.1 实验目录

建议新建：

- `mainexp/experiments/2026-03-08_prism_wave_ab_v1/`

cases：

1. `full_system_baseline`
- 主基线

2. `prism_rx_bridge`
- 只有 bridge，不做 memory service 改写

3. `prism_wave`
- 新的 window aggregate + unique-line service

不建议把当前 `prism_seg` 放进正式 compare 表：

- 它已经是负探索原型
- 可以在文档中留作负对照，但不应污染主 compare 表

## 8.2 成功标准

必须同时满足：

1. `validation.log`
- `fail=0`
- `warn` 不增加新的语义告警

2. 相比 `prism_rx_bridge`
- `prism.wave_line_reissue_avoided_total > 0`
- `prism.wave_pending_attach_total + prism.wave_resident_hits_total > 0`

3. 相比 `full_system_baseline`
- 至少一项 memory payload-plane 指标改善：
  - `gas.payload_bytes_per_memctrl_req_avg`
  - `gas.memctrl_payload_utilization`
  - `gas.memctrl_traffic_amplification`
- 并且不能再出现类似 `prism_seg` 那样的 wall-time 爆炸

## 8.3 最关键的 A/B 问题

这一版最重要的不是先看 `sim_time_actual_ns`，而是先看：

- `prism_wave_unique_line_requests_total`
- 相对 `prism_pres_total` 是否已经塌缩到小得多的数量级

因为如果这一步没做到：

- 后面的任何 NoC / DRAM 指标都不可能稳

## 9. 实现建议

## 9.1 最小实现顺序

推荐按 4 步落地：

1. **先做 state，不做 resident bytes**
- 只先支持：
  - `Absent -> Pending`
  - `Pending attach`
- 先证明同一 line 不再重复发请求

2. **再补 resident bytes buffer**
- 让 line 回包后，后来的 targets 能 resident-hit

3. **再补 summary 指标**
- 把 dedup 证据链接到 `essential_summary_mesh.json`

4. **最后再考虑 block/cohort 升级**
- 如果 `PRISM-WAVE` 单 PE 内已经有效，再考虑把它升级到 block service

### 9.2 文件落点

预计主要改动文件：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/workload_stats/SnnWorkloadStatsModule.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- `sst_dram_si/tools/compute_essential_summary_mesh.py`
- `sst_dram_si/tools/validate_essential_summary_mesh.py`
- `mainexp/experiments/2026-03-08_prism_wave_ab_v1/`

## 10. 为什么这条路更像主线而不是一次 patch

`PRISM-WAVE` 比当前 `PRISM-SEG` 更像一个主线架构点，原因是：

1. 它直接修正了当前失败的根因，而不是做表面调参
2. 它把 `STORM` 的 `pre token` 与 `GCSS-GLIDE` 的 `pre-major line service` 真正统一在一个窗口级对象上
3. 它仍然保持 exact / deterministic / line-truthful
4. 它未来可以自然升格为：
- block-shared service
- cohort-major service
- 与 `SURGE` 的更强 memory × NoC 协同

换句话说：

- `PRISM-SEG` 是一次直连原型
- `PRISM-WAVE` 才是能站住脚的正式版本

## 11. 当前推荐结论

如果我们现在继续推进 `PRISM` 路线，最合理的下一步不是：

- 继续跑当前 `prism_seg` 的更多实验
- 或给它做更激进的 issue / credit / scheduler 调参

而是：

- **按 `PRISM-WAVE` 的窗口级聚合与 unique-line service 重新实现这一条路**

这是当前最稳、最符合代码现状、也最可能把 `PRISM` 从“负探索原型”变成“主线可用协同机制”的方案。
