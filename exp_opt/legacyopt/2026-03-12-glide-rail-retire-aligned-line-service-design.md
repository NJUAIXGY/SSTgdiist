# GLIDE-RAIL: Retire-Aligned Inter-core Line Service 设计方案

> 日期：2026-03-12  
> 状态：design-only  
> 定位：`DRAM-based SNN + GAS + GCSS-GLIDE + STORM + MulticastRouter` 主线上的下一代 memory-response-retire 协同机制  
> 推荐名称：**GLIDE-RAIL** = **G**CSS-**GLIDE** with **R**etire-**A**ligned **I**nter-core **L**ine-service

---

## 0. 一句话结论

`ATLAS-LSS/PE` 已经证明：

- `PE-shared line service` 的 request collapse 机理是真成立的；
- 但在当前 `GCSS-VLF` 地址重排 + `global in-order retire` 的主线下，**共享 line 的收益会被放大的 head-of-line blocking 吞掉**。

因此，下一步不该继续追求“共享更多 line”，而应转向：

> **只对 retire 时序上足够接近的 waiter 做受控共享，并让 issue/release 过程显式保护 head progress。**

这就是 `GLIDE-RAIL` 的核心。

---

## 1. 背景：为什么 `ATLAS-LSS` 失败，但又不应被简单否定

### 1.1 当前主线已经很强

当前唯一系统主基线已经收敛为：

- 芯片框架：`DRAM-based SNN`
- memory backbone：`GAS`
- memory 主线优化：`GCSS-GLIDE`
- NoC 主线优化：`STORM`
- NoC backend：`MulticastRouter`

在这个主线上，`GCSS-GLIDE` 已经把大量逻辑 4B 权重读取压到 line 级服务：

- baseline：`763,879` logical reads -> `150,907` memctrl req
- `gas_payload_bytes_per_memctrl_req_avg = 20.2477B`
- `gas_memctrl_payload_utilization = 0.31637`

这说明当前 baseline 并不是“原始逐边读取”，而是已经非常接近一个强的 line-aware lower bound。

### 1.2 `ATLAS-LSS` 证明了机理，但没有转成系统收益

正式 A/B 结果见：

- `mainexp/experiments/2026-03-12_atlas_pe_lss_ab_v1/snapshot/compare.tsv`
- `TECH_PROGRESS.md`

关键现象：

- baseline：
  - `sim_time_actual_ns = 257453`
  - `memctrl.req_total = 150907`
  - `gas_apply_ns_avg = 239096`
- `atlas_pe_lss`：
  - `sim_time_actual_ns = 572172`
  - `memctrl.req_total = 125739`
  - `gas_apply_ns_avg = 534508.5`

也就是说：

- `memctrl.req_total` 进一步下降了约 `16.8%`
- 但端到端时间恶化了约 `2.22x`

`ATLAS-LSS` 的 PE 聚合统计同样说明它不是“没起作用”：

- `atlas_pe_lss_line_requests_total = 763879`
- `atlas_pe_lss_unique_line_issues_total = 125739`
- `atlas_pe_lss_joined_waiters_total = 630613`
- `atlas_pe_lss_cross_core_shared_lines_total = 91450`

这证明：

- 大量 waiter 的确 join 到了共享 line 上
- 共享 line 的 request collapse 是真的

### 1.3 真正失败的是 response/retire 组织方式

当前实现中的关键冲突链条如下：

1. `WeightMemorySubsystem::prepareGcssVlfIssueQueue_()` 先为 edge 注册全局 `retire_seq`，再按地址全局重排 issue  
   位置：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`

2. `atlas_lss` 路径把多个 waiter 合并到同一条 line 的一次 memory request 上  
   位置：`.../WeightMemorySubsystem.h` 中 `acquireLineWord()` 调用路径  
   以及 `services/synapse/atlas/AtlasPeService.h`

3. line fill 一旦返回，会把该 line 上所有 waiter 一次性变成 ready

4. 但 retire 仍然是 `global in-order`  
   位置：`WeightMemorySubsystem.h` 中 `tryRetireEdges_()`

于是形成最坏组合：

- issue 按地址重排
- response 按 line 成批 ready
- retire 按全局 seq 严格串行

结果就是：

- 晚序 edge 更早 ready
- 头部 head edge 尚未 ready
- `ready_uncommitted_edges_` 持续堆积
- `gas_retire_global_hol_cycles_total` 与 `gas_retire_ready_but_blocked_edges_total` 被系统性放大

正式数据也完全对上：

- `gas_retire_global_hol_cycles_total: 73,832,198 -> 166,732,428`
- `gas_retire_ready_but_blocked_edges_total: 100,124,332,070 -> 193,170,028,794`

因此，`ATLAS-LSS` 的失败不是“共享 line 这个方向错了”，而是：

> **共享 line 的 admission / issue / release 没有和 strict retire 协同设计。**

---

## 2. 设计目标与非目标

### 2.1 目标

`GLIDE-RAIL` 的目标不是做更激进的共享，而是做 **更安全、更可转化为系统收益的共享**。

明确目标如下：

1. 在不改变 `GAS` 严格语义的前提下，保留一部分跨 core 共享 line 的收益
2. 相比 baseline，继续降低 `memctrl.req_total`
3. 相比 `ATLAS-LSS`，显著降低 `retire HOL`
4. 保持 `GCSS-GLIDE` 当前 row locality / payload efficiency 主线
5. 让运行时状态规模有界，具备可建模的硬件形态

### 2.2 非目标

这一版不做以下事情：

1. 不改变 `orch_.acc_update(post_local, delta)` 的提交顺序
2. 不把 `per-post retire` 作为主线依赖
3. 不直接修改 `STORM` 的 packet/noC 语义
4. 不追求“所有可共享 waiter 都 join”
5. 不把当前 `atlas_lss v1` 的重索引格式直接当成最终主线格式

---

## 3. 设计空间对比

### 3.1 方案 A：只做 Head-aware issue

做法：

- 保留现有 `ATLAS-LSS` 的共享行为
- 只对 unique line issue 的顺序做 head-aware 排序

优点：

- 改动最小
- 可以缓解一部分 head starving

缺点：

- 无法阻止“远距离 retire_seq waiter 被绑在同一条 line 上”
- line fill 返回后，ready backlog 仍可能爆炸

结论：

- 可作为小型对照
- 不足以作为主推荐方案

### 3.2 方案 B：直接转向 per-post retire

做法：

- 保留现有 line sharing
- 改 `global retire` 为 `per-post deterministic retire`

优点：

- 逻辑上最直接拆解全局 HOL

缺点：

- 我们已有历史证据：`per-post retire` 在旧口径里能消掉 HOL 统计，但未转成端到端收益
- 语义/论文叙事风险都更高
- 会把系统主线从“保持原语义”拖向“改 retire 语义”

结论：

- 可作为实验性 ablation
- 不宜作为主线候选

### 3.3 方案 C：Retire-aware selective line sharing（推荐）

做法：

- 不再无条件 join 同一条 line 的所有 waiter
- 只对“retire 时序足够接近”的 waiter 做共享
- 并让 issue / release 显式保护 head progress

优点：

- 直接命中 atlas 失败的根因
- 不改提交语义
- 硬件实现更容易有界

结论：

- **推荐作为下一步主方案**

---

## 4. 核心洞察：共享收益取决于 seq 距离，而不是只取决于地址相同

`ATLAS-LSS` 默认把“同一 line”看成 join 的充分条件，但这在 strict retire 系统里并不成立。

对当前系统而言，一个 waiter 是否值得共享，至少取决于三个量：

1. `seq_span`
- `max(retire_seq) - min(retire_seq)`
- 表示同一共享 line 内 waiter 的 retire 距离

2. `head_distance`
- `min(retire_seq) - current_head_seq`
- 表示这条 line 距离真正 head 有多远

3. `fanout`
- 当前 line 已挂 waiter 数
- 表示该 line 的 collapse 收益有多大

经验上：

- `fanout` 大通常是好事
- 但 `seq_span` 太大、`head_distance` 太远通常是坏事

所以新目标函数不应再是：

- 最小化 `req_total`

而应变成：

> **在限制 `HOL` 与 ready backlog 的前提下，尽量降低 `req_total`。**

这就是 `GLIDE-RAIL` 相比 `ATLAS-LSS` 的本质提升。

---

## 5. 推荐方案：GLIDE-RAIL 总体结构

### 5.1 放置位置

`GLIDE-RAIL` 建议作为一个新的 PE 级 sidecar 服务单元，位置在：

- `STORM`/receiver gather 之后
- `WeightMemorySubsystem` 发起真实 memory issue 之前

逻辑上，它位于：

`token/gather outputs -> GLIDE-RAIL -> WMS issue -> DRAM -> GLIDE-RAIL release -> WMS retire`

推荐隔离承载位置：

- 新目录：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/rail/`
- 新服务：`GlideRailService.h`
- 不建议继续把逻辑堆叠进 `AtlasPeService.h`

### 5.2 运行时对象

`GLIDE-RAIL` 的核心对象不是“全窗口 line hash”，而是 **有界 descriptor**。

#### 对象 1：`RailLineDescriptor`

字段建议：

- `descriptor_id`
- `line_addr`
- `consumer_mask`
- `min_seq`
- `max_seq`
- `fanout`
- `issued`
- `ready`
- `valid`
- `released_upto_seq`
- `bytes[64]` 或外部 payload handle
- `waiters[]`

#### 对象 2：`RailWaiter`

字段建议：

- `consumer_core`
- `retire_seq`
- `word_index`
- `post_local`
- `pre_global`
- `released`

#### 对象 3：`HeadTracker`

PE 内每个 core 一个：

- `current_head_seq`
- `ready_but_blocked`
- `head_wait_reason`

#### 对象 4：`ReleaseQueue`

每个 core 一个小 FIFO，用于把“允许释放”的 ready waiter 推给 `WeightMemorySubsystem`。

### 5.3 与当前代码关系

当前 `atlas_lss` 路径中最重要的三段逻辑是：

1. WMS 生成 `retire_seq`
2. service 侧完成 join / issue / fill / ready
3. WMS 仍按 `tryRetireEdges_()` 做严格 commit

`GLIDE-RAIL` 保留 1 和 3，只替换 2。

也就是说：

- `registerEdgeRetire_()` 保持不变
- `tryRetireEdges_()` 保持不变
- 变化点只在：
  - join admission
  - unique issue scheduling
  - ready waiter release

---

## 6. 三个关键机制

## 6.1 机制一：Span-Bounded Join Admission

### 6.1.1 基本规则

一个新 waiter 只有在满足以下条件时，才能 join 到已有 descriptor：

1. `line_addr` 相同
2. `fanout + 1 <= fanout_cap`
3. `new_seq - descriptor.min_seq <= span_cap`
4. `descriptor.max_seq - descriptor.min_seq <= span_cap`
5. `descriptor.min_seq <= head_seq + lookahead_cap`

如果不满足，则：

- 优先尝试为该 line 新开 sibling descriptor
- 若 descriptor table 满，则 deterministic fallback 到 private issue

### 6.1.2 直觉解释

这一步的目标是：

- **保留近距离共享**
- **切断远距离绑定**

也就是：

- 同一 line 上，距离 head 很近、相互 seq 接近的 waiter 值得共享
- 同一 line 上，虽然地址相同但 retire 很远的 waiter，不应被绑在一起

### 6.1.3 推荐初始参数

第一轮建议参数：

- `span_cap = 32` 或 `64`
- `lookahead_cap = 128`
- `fanout_cap = 8` 或 `16`

这些值不应一开始就做复杂自适应，先用固定参数做可解释实验。

---

## 6.2 机制二：Head-Aware Unique-Line Issue

### 6.2.1 问题

现有 `ATLAS-LSS` 即使减少了 unique line issue 数，也会因为“错误的 line 先发”导致 head 长时间拿不到关键 line。

### 6.2.2 新的 issue 优先级

对每个 ready-to-issue descriptor，计算确定性的优先级元组：

1. `unlock_head_class`
- 若该 descriptor 包含当前或近 head 的 waiter，则优先级最高

2. `min_seq`
- 更小者优先

3. `seq_span`
- 更小者优先

4. `row/locality score`
- 在前面三者相近时，再偏向更好的地址局部性

5. `line_addr / descriptor_id`
- 作为最终 tie-break，保证完全确定性

### 6.2.3 关键点

新的 issue scheduler 不是抛弃 locality，而是：

> **只有在不明显伤害 head progress 时，才继续追求 locality。**

这样做的原因是：

- baseline 的 `GCSS-GLIDE` 已经很强
- 新增收益只有最后一段
- 因此不能再用系统前进性去换最后一点请求压缩

---

## 6.3 机制三：Ready Release Gate

### 6.3.1 问题

`ATLAS-LSS` 的另一大问题是：

- line fill 一旦返回，整条 line 的所有 waiter 都会被立即推给对应 core
- 这会把很多“还不能 commit 的远序 waiter”一口气变成 ready

其结果是：

- `ready_uncommitted_edges_` 膨胀
- callback/queue 活跃状态膨胀
- `HOL` 被进一步放大

### 6.3.2 解决思路

line fill 返回后，不再一次性释放全部 waiter，而是进入一个 `release gate`：

- 只释放满足 `retire_seq <= head_seq + release_cap` 的 waiter
- 其余 ready waiter 保留在 descriptor 内
- 每次 head 推进后再尝试继续释放

### 6.3.3 效果

这一步不改变 memory traffic，也不改变 commit 语义，但可以：

- 限制 `ready_but_blocked` 的规模
- 限制大量远序 ready 对 head 的干扰
- 限制 WMS 内部活跃回调规模

它本质上是一个 **response shaping** 机制。

---

## 7. 语义与确定性保证

`GLIDE-RAIL` 必须满足以下不变量：

1. 每条 edge 仍只分配一个唯一 `retire_seq`
2. 每个 `retire_seq` 的权重值只被设置一次
3. `tryRetireEdges_()` 的 commit 顺序不变
4. `orch_.acc_update(post_local, delta)` 的调用顺序不变
5. 任何 table 压力下都能 fallback 到 deterministic private line issue
6. `validation.log` 必须保持 `fail=0 warn=0`

因此：

- `GLIDE-RAIL` 改的是 **service timing**
- 不是 **architectural meaning**

---

## 8. 为什么这个方案比继续推 `ATLAS-LSS` 更有胜算

`ATLAS-LSS` 追求的是“最大共享”。

`GLIDE-RAIL` 追求的是“只保留对 strict retire 友好的共享”。

它更有胜算的原因在于：

1. 当前主线已经不是 request-poor，而是 retire-sensitive
2. `ATLAS-LSS` 带来的新增 request 收益只有约 `16.8%`
3. 因此只要切掉最坏的远距离 join，哪怕损失一部分 sharing，也可能净赚
4. 该方案保留原语义，不依赖更激进的 retire policy
5. 状态有界，硬件叙事更 solid

更直白地说：

> `GLIDE-RAIL` 接受“共享不一定越多越好”这个事实，并把系统优化目标从“最大压缩请求数”重新拉回“最小化端到端关键路径”。`

---

## 9. 硬件形态与可实现性

### 9.1 建议硬件模块

PE 级增加以下轻量结构：

1. `Descriptor Table`
- 存活中的共享 line descriptor

2. `Head Tracker`
- 每个 core 当前等待的最小 `retire_seq`

3. `Issue Selector`
- 选择下一个 unique line issue 的小型优先级器

4. `Release Queue`
- 控制 ready waiter 何时真正注入 WMS

### 9.2 为什么比 `ATLAS-LSS` 更像硬件

当前 `ATLAS-LSS` 更像“软件式窗口哈希表 + 无界 waiter list”。

`GLIDE-RAIL` 从一开始就要求：

- descriptor 有界
- queue 有界
- overflow 可 fallback
- 调度规则 deterministic

因此它更容易映射成：

- 小容量 SRAM + comparators
- 少量 per-core FIFO
- 一个简化优先级器

这比继续扩展 `AtlasPeService` 当前的开放式结构更合理。

---

## 10. 与现有主线的关系

### 10.1 与 `GCSS-GLIDE` 的关系

`GCSS-GLIDE` 仍然负责：

- values layout
- pre-major locality
- payload efficiency

`GLIDE-RAIL` 只负责：

- 多 core 对同一 line 的共享 admission
- shared line 的 issue / release / head protection

也就是说：

- `GCSS-GLIDE` 管“数据怎么摆”
- `GLIDE-RAIL` 管“共享 line 怎么安全地服务”

### 10.2 与 `STORM` 的关系

`STORM` 负责把上游 token 在空间和传播域上聚集起来。

`GLIDE-RAIL` 利用这种聚集结果，但不改变：

- multicast 路由
- packet 格式
- injection 语义

因此它仍然属于 memory subsystem 内部的 response/retire 协同层，不会把 NoC 主线再搅乱。

---

## 11. 统计与可观测性：必须先补的 P0 证据链

在真正实现前，必须先补一组能证明“坏 sharing 来自远距离 seq coupling”的统计。

### 11.1 admission 类统计

- `rail_join_candidate_total`
- `rail_join_accept_total`
- `rail_join_reject_span_total`
- `rail_join_reject_head_distance_total`
- `rail_join_reject_fanout_total`
- `rail_descriptor_alloc_total`
- `rail_descriptor_fallback_private_total`

### 11.2 descriptor 形态统计

- `rail_descriptor_peak`
- `rail_descriptor_span_sum`
- `rail_descriptor_span_max`
- `rail_descriptor_fanout_sum`
- `rail_descriptor_fanout_max`

### 11.3 response / release 统计

- `rail_line_fill_total`
- `rail_ready_waiters_total`
- `rail_release_waiters_total`
- `rail_release_held_waiters_total`
- `rail_ready_seq_gap_sum`
- `rail_ready_seq_gap_max`

### 11.4 head / retire 统计

- `gas_retire_head_waiting_shared_line_cycles_total`
- `gas_retire_head_unissued_cycles_total`
- `gas_retire_head_ready_release_blocked_cycles_total`

### 11.5 派生判断

如果后续实验里看到：

- `rail_join_reject_span_total` 很高
- 同时 `ATLAS-LSS` 的 `HOL` 很高

那就说明我们抓到了真正的坏因子。

---

## 12. 实现建议：分阶段落地，不要一次做满

## 12.1 P0：只加统计，不改行为

目标：

- 在当前 `ATLAS-LSS` 路径上记录 waiter 的 `seq_span / head_distance / fanout`
- 证明坏 sharing 是否真的主要来自远距离 join

这一阶段不做任何功能改变。

## 12.2 P1：只加 Span-Bounded Join

目标：

- 验证“切断远距离 join”是否能明显拉低 `HOL`

这一阶段：

- 不改 issue scheduler
- 不加 release gate
- 只做最小行为变更

## 12.3 P2：加入 Head-Aware Issue

目标：

- 若 `P1` 已经控制住 backlog，但 head 仍饥饿，则进一步保护 head progress

## 12.4 P3：加入 Ready Release Gate

目标：

- 若 `P2` 后仍看到 `ready_but_blocked` 长尾，再做 response shaping

不建议一开始就上 `P3`，否则容易重蹈“机制过厚、难以解释”的老路。

---

## 13. 闭环实验方案

实验统一放在 `mainexp/`，因为这是系统主线口径，不应再放 `memop/`。

建议目录：

- `mainexp/experiments/2026-03-xx_glide_rail_ab_v1/`

### 13.1 基础口径

统一使用：

- `4x4`
- `bcsr10k`
- `step1`
- `seed_only`
- `frac=0.03`
- `ramulator2`
- `full_system_baseline = STORM + GAS + GCSS-GLIDE + MulticastRouter`

### 13.2 case 矩阵

1. `baseline_mainline`
- 当前主线 baseline

2. `atlas_lss_negative_control`
- 当前 `ATLAS-LSS` 负例对照

3. `rail_p0_observe_only`
- 只补统计，不改行为

4. `rail_p1_span_only`
- 仅启用 span-bounded join

5. `rail_p2_span_head_issue`
- `P1 + head-aware issue`

6. `rail_p3_full`
- `P2 + ready release gate`

### 13.3 验收指标

主指标：

- `sim_time_actual_ns`
- `gas_apply_ns_avg`
- `memctrl.req_total`
- `gas_memctrl_payload_utilization`
- `gas_payload_bytes_per_memctrl_req_avg`
- `gas_retire_global_hol_cycles_total`
- `gas_retire_ready_but_blocked_edges_total`

新机制指标：

- `rail_join_accept_total / candidate_total`
- `rail_descriptor_span_max`
- `rail_release_held_waiters_total`
- `gas_retire_head_waiting_shared_line_cycles_total`

### 13.4 成功标准

第一轮的现实目标不该是“比 baseline 大幅更快”，而应是：

1. 保留一部分 atlas 的 request collapse 收益
2. 不再出现 `2x` 级 apply/retire 回退
3. `HOL` 回到接近 baseline

建议目标：

- `memctrl.req_total` 相比 baseline 继续下降 `5%~12%`
- `gas_retire_global_hol_cycles_total <= baseline * 1.2`
- `sim_time_actual_ns <= baseline * 1.05`

如果能做到：

- `sim_time_actual_ns < baseline`

那才说明这条路真正值得继续投入。

---

## 14. 风险与决策门

### 14.1 风险一：join 被切得太狠，收益归零

表现：

- `rail_join_accept_total` 很低
- `memctrl.req_total` 接近 baseline

含义：

- 跨 core shared line 的“安全共享空间”很小
- 这条路价值可能有限

### 14.2 风险二：join 没切够，HOL 仍高

表现：

- `memctrl.req_total` 保持较低
- 但 `HOL` 仍明显高于 baseline

含义：

- 仅 admission 不够
- 需要继续上 `head-aware issue`

### 14.3 风险三：当前 `dstpe atlas` 索引过重

表现：

- 即使 runtime 行为变好，`index_to_values_ratio` 仍高于主线很多

含义：

- `GLIDE-RAIL` 的机制可能成立
- 但其当前离线格式仍不适合主线

应对：

- 先把 runtime 机制证明清楚
- 再单独处理 shared index 压缩，不把两个问题混在一起

---

## 15. 与历史探索的边界

这份方案明确与以下路线区分：

1. 不回到 `ATLAS-LSS` 的“最大共享”思路
2. 不把 `per-post retire` 作为主线依赖
3. 不回到 `PRISM / TIDE / TASS` 那种更重的跨层广播/共享对象设计
4. 不继续做只改 layout、不改 response/retire 的调参

`GLIDE-RAIL` 的定位很清楚：

> 它是从 `ATLAS-LSS` 的负结果中提炼出的、专门修复 shared-line 与 strict retire 冲突的下一代主线候选机制。

---

## 16. 最终建议

当前最值得做的，不是继续推进“全窗口 PE-shared line service”，而是：

1. 先用 `P0` 统计证明坏 sharing 的主要来源确实是大 `seq_span`
2. 再做 `P1` 的 span-bounded join
3. 若仍不足，再上 `P2` 的 head-aware issue
4. 只有在必要时才做 `P3` 的 release gate

也就是说：

> **我们不再追求“更多共享”，而是追求“只保留对 strict GAS 友好的共享”。**

这才是 `ATLAS-LSS` 负结果真正指向的下一步。
