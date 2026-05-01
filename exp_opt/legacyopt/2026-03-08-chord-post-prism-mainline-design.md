# CHORD：Post-PRISM 的主线级 Memory × NoC 协同方案

> 日期：2026-03-08  
> 状态：设计收敛版  
> 目标：在 `full_system_baseline = STORM + GAS + GCSS-GLIDE` 之上，提出一个真正可落地、可闭环、可投稿的 memory × NoC 协同机制。  
> 结论：`PRISM` 不进入主线；下一条应认真推进的路线是 **`CHORD`**，而且必须是 **不新增第二条高频 exact-service 数据面** 的版本。

---

## 0. 一句话结论

`PRISM` 给我们的最重要经验，不是“receiver-side token bridge 没价值”，而是：

- **表示层桥接可以有**；
- **但不能把它升级成一条新的高频 exact-service 执行平面**。

当前真正值得做的主线，不该再围绕“token 如何直接驱动 line service”打转，而应该围绕一个更稳定、更低频、更贴近现有主线的共享抽象：

- **`CHORD` = 用同一个 `service cohort` 同时组织 `STORM` 的 multicast wave 与 `GAS/GCSS-GLIDE` 的 DRAM service wave。**

它的关键点不是“再发明一套新 packet / 新 value plane”，而是：

- 复用当前 `SpikeKey/SpikeTileKey` 到达路径；
- 复用当前 `GCSS-GLIDE` exact value path；
- 仅在两者之间加一个 **cohort-locality contract**；
- 让接收侧的 gather/apply 组织方式，与发送侧的 block multicast 波次，围绕同一个对象协同起来。

这条路相比 `PRISM-SEG / PRISM-WAVE` 更稳、更像主线，也更像一篇体系结构论文里的“统一抽象”。

---

## 1. 先把 PRISM 的经验说透

### 1.1 `PRISM-RX` 的价值是真实存在的，但它只是桥

根据 `TECH_PROGRESS.md` 当前记录：

- `PRISM-RX` 正式 run：
  - `validation.log: fail=0 warn=1`
  - `model.sim_time_actual_ns = 257453`
  - `memhierarchy.memctrl.req_total = 150907`
  - `gas.payload_bytes_per_memctrl_req_avg = 20.2477`
  - `gas.memctrl_payload_utilization = 0.31637`
  - 与 `full_system_baseline` 完全一致
- 但它把接收侧 key 包成功搬到了 token bridge：
  - `snn_rx.prism_packets_total = 8,843,654`
  - `snn_rx.prism_materialized_edges_total = 19,426,479`
  - `snn_rx.prism_local_spike_expansion_avoided_total = 40,610,304`

这说明：

- `receiver-side pre token bridge` 本身是语义安全的；
- 它能消掉 fallback 本地 spike 展开；
- 但它**没有**直接打到 payload plane，因此单独不会带来性能收益。

### 1.2 `PRISM-SEG` 失败不是偶然，而是结构性失败

`TECH_PROGRESS.md` 里的负证据已经非常清楚：

- `PRISM-SEG` 在正式 full-system run 中，超过 `32` 分钟 wall time 仍未完成，被人工中止；
- 缩小到 `step_activation_fraction=0.001` 的 smoke 仍显著慢于 baseline；
- 当前最可信的根因是：
  - `PRISM-SEG` 按 token 粒度驱动 pre-major / line service；
  - `prism_pres_total = 8,843,654`；
  - 但 baseline 的 `memctrl.req_total = 150,907`；
  - 两者量级比约为 `58.6x`。

这说明一个非常关键的事实：

- `GAS + GCSS-GLIDE` 当前主线，已经把原始神经事件压成了一个更低频的 memory service 平面；
- `PRISM-SEG` 又把它重新膨胀成接近 token 粒度的执行平面；
- 这不是“小优化没调好”，而是**抽象层级选错了**。

### 1.3 `PRISM-WAVE` 也提醒了我们一个边界

`PRISM-WAVE` 的修正方向是对的：

- 做 `window-unique pre` 聚合；
- 做 `window-unique line` service 去重；
- 防止同一窗口内重复 materialize / 重复 line read。

但它仍然有一个主线风险：

- 它还是在围绕 `receiver token -> exact line service` 这条新平面构造 runtime 状态机；
- 即使能比 `PRISM-SEG` 好，也很容易继续走向：
  - 大量窗口级 hash/table 状态；
  - 复杂 attach/resident bookkeeping；
  - SST 事件和真实硬件控制都变重。

所以我们现在要收敛出的经验是：

1. **不要新增第二条高频 exact-service 数据面。**
2. **任何新状态都必须跟 `window-unique pre` 或 `cohort` 同量级，而不是跟 token 同量级。**
3. **新机制必须建立在当前 `full_system_baseline` 已成立的主线上，而不是替换它。**
4. **新机制必须优先改变“组织方式”，而不是新造一条 value 传输路径。**

---

## 2. 当前主线真正成立的东西是什么

当前已经被实验钉死的主线是：

- **Memory 主线**：`GAS + GCSS-GLIDE`
- **NoC 主线**：`STORM + MulticastRouter`
- **系统主基线**：`full_system_baseline`

从 `mainexp/experiments/2026-03-08_full_system_baseline_ab_v1/snapshot/compare.tsv` 可以读出三个事实：

1. `GCSS-GLIDE` 的 memory path 是成立的。
- `memory_baseline` 与 `full_system_baseline` 的 `memctrl.req_total` 同量级：
  - `150110 -> 150907`
- `gas.memctrl_payload_utilization` 同量级：
  - `0.317663 -> 0.316370`

2. `STORM` 的 NoC path 也是成立的。
- `noc_baseline -> full_system_baseline`：
  - `sim_time_actual_ns: 1383670 -> 257453`

3. 现在还没有真正成立的，是**两者围绕同一个 locality object 协同工作**。

也就是说，当前系统虽然强，但仍然是：

- `STORM` 在 NoC 侧做 block-aware wave；
- `GCSS-GLIDE` 在 memory 侧做 pre-major / line-friendly service；
- 两边都对，但它们的组织语言还不是同一个东西。

这就是我们下一步体系结构创新的切入口。

---

## 3. 新主方案：CHORD

### 3.1 核心定义

**`CHORD` = Cohort-Harmonized Ordering for Routed Dissemination and DRAM service**

它的核心不是 token，也不是 line table，而是：

- 对每个接收 `core`，从 `GCSS-GLIDE` 离线布局里抽取一个小而稳定的 **`service cohort`**；
- 让同一个 `cohort` 同时驱动：
  - 接收侧 ingress 分桶；
  - Apply 侧 issue wave 选择；
  - 可选的 source-side / NoC-side admission 对齐。

一句更直白的话：

- **NoC 不再只是把 spike 送到目的地；它开始“按 memory 会喜欢的方式”把它们送到目的地。**
- **Memory 不再只是被动接收到达的 pre；它开始“按 NoC 已经组织出的波次”去服务这些 pre。**

### 3.2 为什么 CHORD 比 PRISM 更对路

因为 CHORD 明确避免了 PRISM 的主风险：

- 不引入新的 token->segment exact service 平面；
- 不做每 token 一次 materialize / issue；
- 不做新的 raw value demux pipeline；
- 不改变当前 `GCSS-GLIDE` 的 exact line-truth path；
- 不改变当前 `STORM` 的 packet 数据面；
- 只在两者之间增加一个轻量协同层。

因此 CHORD 的复杂度来源是：

- 一个离线 sidecar；
- 一组接收侧 cohort queues / bitmaps；
- 一个 apply wave scheduler；
- 一个可选的 step-level admission plan。

而不是：

- 一个新的 packet kind 主路径；
- 一个新的 values format 主路径；
- 一个新的运行时 line 去重引擎。

---

## 4. CHORD 的共享抽象：service cohort

### 4.1 cohort 到底是什么

在当前系统里：

- `STORM` 最自然的对象是：`destination block / multicast wave`
- `GCSS-GLIDE` 最自然的对象是：`pre-major line / DRAM row-local service wave`

CHORD 要做的，是在两者中间找一个共同对象。

这个对象不应该是：

- 单个 token
- 单个 pre
- 整个 block
- 整个 row

而应该是一个更小、更稳定、可以离线编号的对象：

- **`service cohort(core, pre_global) -> cohort_id`**

它的本质含义是：

- 这个 `pre_global` 在该 `core` 上，最终大概率会落到哪一类 `GCSS-GLIDE` service wave；
- 这类 wave 在 DRAM 几何下，具有相近的：
  - dominant bank
  - dominant row group
  - line span class
  - issue affinity

### 4.2 cohort 如何离线抽取

利用现有 `GCSS-GLIDE` artifact，本质上已经知道：

- `pre_global -> pre_base`
- `pre_len`
- values 物理地址范围

因此可以对每个 `(core, pre_global)` 计算：

- dominant row id / row-group id
- dominant bank id
- line span bucket
- values segment size class

再把这些特征压成一个小 `cohort_id`。

推荐第一版先做非常保守的离线规则：

- `cohort_id = hash(dominant_bank, dominant_row_group, span_class) mod K`
- `K` 很小，例如 `8` 或 `16`

这样得到的 cohort 有三个好处：

1. **小**：sidecar 很小，接近 `pre -> small id` 映射；
2. **稳**：由已有 `GCSS-GLIDE` 物理布局导出，不依赖运行时统计；
3. **可解释**：每个 cohort 都对应某一类 DRAM service 倾向。

### 4.3 cohort sidecar 的大小为什么可控

我们不是再建一个新索引系统，而只是额外给每个 `pre_global` 一个很小的标签。

如果：

- `K <= 16`
- `cohort_id` 用 `4 bit`

那么 sidecar 的规模大致就是：

- `#unique_pre_per_core * 4 bit`

这相比当前 `GCSSIDX2` 已压到 `values/10` 的主索引成本，仍然是很轻的附加成本。

---

## 5. CHORD 的完整机制

## 5.1 CHORD-L：接收侧 cohort ingress + apply scheduler

这是 CHORD 的主体，也是最该先做的版本。

### A. ingress classify

当前接收路径锚点已经很清楚：

- `SnnWorkload::deliverPacket()`
- `SnnWorkload::expandPreGlobalToWindowEdgesFast_()`
- `SnnWorkload::lookupPostsLocalForPre_()`

CHORD-L 不改 packet 格式，只在 `pre_global` 到达后多做一步：

- `pre_global -> cohort_id` 查表；
- 把这个 pre 记入 `cohort_pending_[cohort_id]`；
- 计数而不是立刻触发新的 service。

注意：

- 这里不是 `PRISM` 那种“把 token 变成新执行对象”；
- 这里只是把当前已经会进入窗口的 pre，先按 cohort 做归类。

### B. window-local unique-pre accounting

每个窗口内，CHORD-L 至少维护：

- `cohort -> unique pre set`
- `cohort -> pre touch count`
- `cohort -> age / first_seen_cycle`

这让它能够：

- 知道哪些 cohort 已经足够“成波”；
- 知道哪些 pre 是窗口内反复被访问的；
- 不需要任何 token->line exact attach 结构。

### C. cohortized materialization

到了 `BeginApply`，不再按 flat pre 顺序 materialize，而是：

- 先选择一个 ready cohort；
- 再把该 cohort 里的 pre 批量 materialize 到当前 WMS edge collector；
- materialize 仍然调用现有 exact path：
  - `recordEdgeWithPreRank(...)`
  - 或一个新的 `recordEdgeWithPreRankCount(...)` 批量版本

关键点：

- materialize 粒度是 **window-unique pre**；
- 不是 packet 粒度；
- 更不是 line 粒度。

### D. apply scheduler

当前 WMS 里已有两个关键锚点：

- `WeightMemorySubsystem::prepareGcssVlfIssueQueue_()`
- `WeightMemorySubsystem::issueFromEdgesOnce_()`

CHORD-L 的做法不是新造 issue plane，而是在当前 plane 上加一个 cohort-aware order：

- 第一层：先选 cohort；
- 第二层：cohort 内仍按现有 `addr / pre / seq` 规则排序；
- retire 仍然走当前 seal / in-order retire 路径。

这会让 system wave 更像：

- 一小段时间集中服务某个 memory-affine cohort；
- 再切到下一个 cohort；
- 而不是“arrival 顺序随机打散整个 Apply service”。

### E. 语义边界

CHORD-L 不改变：

- edge membership
- weight value
- `orch_.acc_update(post_local, delta)` 的数学结果
- retire correctness seal

它只改变：

- **哪个 pre 先被 materialize**
- **哪个 cohort 先被 issue**

因此它在语义上是安全的。

---

## 5.2 CHORD-A：step-level admission coupling

这是 CHORD 真正体现 memory × NoC 协同的部分，但应该放在 CHORD-L 跑通后。

### A. 为什么 admission coupling 不能太重

我们已经被 `global credit 2.0`、`PRISM`、`TASS` 类思路教育过：

- 太细粒度的 online feedback 容易把收益吃回控制复杂度；
- 太激进的 source-side hold 容易制造新的长尾。

所以 CHORD-A 必须是：

- **bounded**
- **step-level / epoch-level**
- **best-effort**
- **可随时 fallback**

### B. 复用现有 controller 骨架

当前代码已经有很好的控制面锚点：

- `GlobalGasStepController`
- `IGlobalStepCreditHooks`
- `SnnPESubComponent::onGlobalStepApplyBankCredit()`
- `MultiCorePE` 的 step-start 广播路径

CHORD-A 不需要新建独立控制器，而是可以仿照 `apply_bank_credit`：

- 每个 PE 在 step 结束时，上报自己最热的 `preferred cohort` 与压力摘要；
- `GlobalGasStepController` 汇总后，在下一个 `StartStep` 广播一个很小的 admission plan；
- 发送端 `SpikeCommSubsystem` 只做有界的 hold / priority reorder。

### C. sender 如何执行这个 plan

当前发送链路锚点：

- `SpikeCommSubsystem::emitCommon_()`
- `SynapseRouteSubsystem::computeMulticastTargets()`

发送端其实已经知道：

- `source_global`
- 目标 `block_id`
- 目标 `ingress_node`

因此可以在 packet 发出前查一个小表：

- `dest_block -> preferred cohort epoch / quota`

如果某个包主要命中“当前 preferred cohort”，优先发；
如果不命中，则：

- 最多延后一个很小、可配置的 budget；
- 超时就原样发出；
- 永不丢包，永不无限等待。

这就把 NoC wave 和 memory wave 轻量对齐了。

### D. 为什么这比 PRISM/TASS 稳

因为它不需要：

- receiver-side token attach engine
- block-shared raw value service
- response fanout / demux
- 运行时 exact line dedup

它只是：

- 做更聪明的“何时发、先发谁”。

---

## 6. 为什么 CHORD 是“足够 novel + 足够 solid + 足够 work”

### 6.1 novelty 不在 heuristic，而在共享抽象

如果只是“按 row/addr 排一排 issue”，这很像工程调度。

但 CHORD 的不同点在于：

- 它提出了一个 `service cohort` 抽象；
- 这个抽象同时驱动：
  - 接收侧窗口组织；
  - memory service ordering；
  - NoC admission ordering；
- 它是从 `GCSS-GLIDE` 物理布局里导出的；
- 又能被 `STORM` block multicast 路径消费。

这个点更像 cross-layer architecture contract，而不是小 heuristic。

### 6.2 solid 在于它不改危险路径

CHORD 明确不碰这些高风险项：

- 不共享 raw values
- 不共享 partial sums
- 不新增 exact token-service plane
- 不改变 retire seal
- 不破坏 `validation.log` 严格口径

### 6.3 work 在于它嫁接点都已存在

当前代码里几乎所有必要锚点都已经有了：

- 接收 / fastpath：`SnnWorkload::deliverPacket()`、`expandPreGlobalToWindowEdgesFast_()`
- exact edge record：`WeightMemorySubsystem::recordEdgeWithPreRank(...)`
- apply issue：`prepareGcssVlfIssueQueue_()`、`issueFromEdgesOnce_()`
- NoC send：`SpikeCommSubsystem::emitCommon_()`
- multicast target resolve：`SynapseRouteSubsystem::computeMulticastTargets()`
- 全局控制：`GlobalGasStepController` 与 `apply_bank_credit` 广播骨架

也就是说，CHORD 并不需要“另起炉灶”，而是现主线骨架上的一个新层。

---

## 7. 与其它候选方向的取舍

### 7.1 为什么不是 SURGE 作为第一优先

`SURGE` 的“统一 packet granule 与 memory granule”很有论文味道，但它当前的问题是：

- 需要新的 weight format；
- 需要新的 packet 语义或 payload 编码；
- 需要新的 cohortline demux 硬件路径；
- 风险上更接近 `PRISM/TASS` 的重数据面变更。

所以更合理的主线顺序是：

1. **先做 CHORD**：先证明 shared locality contract 能带来稳定系统收益；
2. **再考虑 SURGE**：把 CHORD 已证明最热、最稳定的 cohort 烧进更激进的数据面统一格式。

### 7.2 为什么不是继续 PRISM-WAVE

`PRISM-WAVE` 是对 `PRISM-SEG` 的正确止损，但它依然过于围绕“token bridge 如何变成 exact service”来构造运行时引擎。

相较之下，CHORD 的优势是：

- 更主线；
- 更轻；
- 更不容易把 SST 事件数炸回来；
- 更贴近真实硬件里的“小队列 + 小调度器 + 小控制平面”。

---

## 8. 建议的落地顺序

## 8.1 P0：离线 oracle 分析

目标：在不改 runtime 的前提下，先验证 cohort locality 是否强到值得做。

做法：

- 从 `GCSS-GLIDE` artifact 离线生成：
  - `core -> pre -> cohort_id`
- 用当前 `full_system_baseline` 的窗口 / pre touch 轨迹离线统计：
  - 每窗口 unique pre 在 cohort 上的集中度
  - cohort run-length 上界
  - 若按 cohort order service，理论 row/bank reuse 提升多少

如果这个上界不明显，CHORD 就不值得进 runtime。

## 8.2 P1：CHORD-L only

只做 destination-side：

- sidecar lookup
- ingress classify
- cohortized materialization
- cohort-aware apply ordering

不做 source-side admission。

目标：

- 看 memory side 是否已有稳定正收益；
- 证明 cohort 本身是对的，而不是 admission 在瞎救。

## 8.3 P2：CHORD-A only

只做 step-level admission coupling：

- sender bounded hold / priority
- receiver仍走 flat baseline 或 minimal cohort collect

目标：

- 单独测 NoC wave alignment 的价值。

## 8.4 P3：CHORD full

将两者合起来：

- destination-side cohort apply
- source-side bounded admission alignment

这才是论文里的完整版本。

---

## 9. 必须补的统计链

为了让 CHORD 能真正形成论文证据链，建议至少补这些统计。

### 9.1 接收侧 / cohort 形成

- `snn_rx.chord_packets_total`
- `snn_rx.chord_window_unique_pres_total`
- `snn_rx.chord_window_unique_cohorts_total`
- `snn_rx.chord_pre_revisits_total`
- `snn_rx.chord_cohort_hotset_ratio`

### 9.2 memory side / apply scheduler

- `gas.chord_cohort_issue_total[k]`
- `gas.chord_cohort_switches_total`
- `gas.chord_avg_wave_len`
- `gas.chord_open_row_reuse_total`
- `gas.chord_bank_match_total`
- `gas.chord_wave_payload_bytes_total`

### 9.3 NoC-side admission

- `storm.chord_hold_packets_total`
- `storm.chord_hold_cycles_total`
- `storm.chord_timeout_fallback_total`
- `storm.chord_preferred_wave_hits_total`

### 9.4 joint 派生指标

- `joint.chord_alignment_score`
- `joint.chord_bytes_per_wave_avg`
- `joint.chord_row_hits_per_wave_avg`
- `joint.chord_wave_req_reduction_vs_flat`

这些统计必须能最终解释：

- 为什么 `sim_time_actual_ns` 变好；
- 为什么 `apply_ns_avg` 变好；
- 为什么 row/bank locality 变好；
- 为什么 NoC 没把 tail 吃回来。

---

## 10. 推荐的正式实验矩阵

统一基线：

- `full_system_baseline`
- `4x4 bcsr10k step1`
- `ramulator2`
- `paper profile`
- 严格验证口径不变

建议矩阵：

1. `A_full_system_baseline`
2. `B_chord_l`
- only destination-side cohort ingress + apply scheduler
3. `C_chord_a`
- only admission coupling
4. `D_chord_full`
- L + A 同时开启

闭环指标：

- `sim_time_actual_ns`
- `memctrl.req_total`
- `gas.payload_bytes_per_memctrl_req_avg`
- `gas.memctrl_payload_utilization`
- `gas.memctrl_traffic_amplification`
- `gas.apply_ns_avg`
- `validation.log: fail=0`

---

## 11. 最终裁决

如果我们认真吸收 `PRISM` 的教训，那么下一条真正该做的 memory × NoC 协同主线，不应再是：

- token-to-segment
- token-to-line
- block-shared raw value service
- 更复杂的 runtime exact join

而应该是：

- **`CHORD`：让 `STORM` 的 multicast wave 与 `GAS/GCSS-GLIDE` 的 DRAM service wave，围绕同一个 `service cohort` 协同组织。**

这是我认为目前最符合下面四条的方案：

- 足够 novel
- 足够 solid
- 足够 work
- 足够贴合当前已经成立的主线

如果只允许选一条真正该投入工程与论文叙事的路线，我建议现在就把它定为：

- **唯一主推协同方案：`CHORD`**
- `PRISM`：保留为负探索与桥接经验，不再作为主线
- `SURGE`：保留为 CHORD 证明成立后的更激进二阶段升级
