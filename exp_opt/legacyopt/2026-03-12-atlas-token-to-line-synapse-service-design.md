# ATLAS：Token-to-Line Synapse Service 设计方案

> 日期：2026-03-12  
> 状态：design-only  
> 定位：`DRAM-based SNN + GAS + GCSS-GLIDE + STORM + MulticastRouter` 主线上的下一步 memory × NoC 协同机制  
> 推荐名称：**ATLAS** = **A**ctivation-**T**oken to **L**ine **A**dmission **S**ervice

---

## 0. 一句话结论

当前主线已经证明：

- `STORM + MulticastRouter` 已把前向 spike dissemination 压成了原生 multicast-aware 的 token/data plane；
- `GAS + GCSS-GLIDE` 已把后向权重服务压成了 DRAM-friendly 的 line-aware memory plane；
- 但两者之间仍缺一层真正的硬件桥，当前 receiver 侧依然存在：
  - `token -> local edge/object inflation -> addr rebuild -> line service`

**ATLAS 的目标，就是把这段隐式、松散、容易膨胀的中间路径，变成一个显式的、可调度的、可观测的 `token-to-line service layer`。**

ATLAS 不改变 GAS 语义，不改变 `Scatter` 才允许发放的严格时序，只改变：

- 接收端如何保存输入对象；
- Apply 前如何把对象提升为 line/segment 级服务描述符；
- DRAM 返回后如何按确定性顺序分发与退役。

---

## 1. 为什么现在必须往这一步走

### 1.1 当前主线已经吃掉了大部分低垂果实

当前正式主线：

- 顶层框架：`DRAM-based SNN chip`
- memory backbone：`GAS`
- memory optimization：`GCSS-GLIDE`
- NoC optimization：`STORM`
- NoC backend：`MulticastRouter`

正式 `full_system_baseline` 已给出强证据：

- `sim_time_actual_ns = 257,453`
- `memctrl.req_total = 150,907`
- `gas.memctrl_payload_utilization = 0.316370`
- `gas.payload_bytes_per_memctrl_req_avg = 20.2477B`

对应记录见：

- [`TECH_PROGRESS.md#L5906`](/home/xgy/remote/TECH_PROGRESS.md#L5906)

更关键的是，当前文档与统计已经明确指出：

- 在 `dstcore + GCSS-GLIDE` 主线口径下，`WeightMemorySubsystem` 看到的 DRAM requests 已基本贴住 **line-level lower bound**；
- 因此继续在 `WeightMemorySubsystem` 的本地 issue/reorder/guardrail 上深抠，更像是在下界附近做小修补，而不是在改真正的系统对象。

对应记录见：

- [`TECH_PROGRESS.md#L7072`](/home/xgy/remote/TECH_PROGRESS.md#L7072)

### 1.2 现在真正浪费的，不再只是“请求数”，而是“服务对象定义”

当前主路径本质上仍然是：

1. `STORM` 发送 `SpikeKey / SpikeTileKey`
2. `NocSubsystem` 严格走 `MulticastRouter` 外部 mesh
3. receiver 端 `deliverPacket()`
4. `SnnWorkload` 根据 `pre_global` 展开 `posts_local`
5. `WeightMemorySubsystem` 记录 `(post_local, pre_global, pre_rank)`
6. Apply 期再把这些 edge 映射为 `addr`
7. `GCSS-GLIDE` 按 line-friendly 顺序发射

也就是说：

- 前向对象是 `token`
- 后向对象是 `line`
- 中间对象却退化成了大量 `edge / core-local intent`

ATLAS 的基本判断是：

> **下一步最值得做的，不是再优化 line service 本身，而是重新定义 token 与 line 之间的服务对象。**

---

## 2. 近三年顶会给我们的真正启发

### 2.1 共同趋势

近三年四大顶会里，与我们最相关的 SNN/neuromorphic 架构工作，反复在强调四件事：

1. `event/token` 要成为一等硬件对象
2. `queue/admission` 要显式建模
3. `state / index / weight` 要做分层存储
4. 服务尽量在靠近数据的位置完成，而不是过早膨胀成细粒度操作

对我们最有启发的代表包括：

- `ActiveN`（MICRO 2024）：强调 event runtime、queueing、hierarchical memory、latency-hiding
- `NeuroLobe`（MICRO 2024）：强调 localized synaptic processing
- `Prosperity`（HPCA 2025）：强调 task scheduling 与 runtime storage management
- `Bishop`（ISCA 2025）：强调 event-driven/data-driven contract 的架构化表达
- `GustavSNN`（HPCA 2026）：体现“动态状态近端、静态权重远端”的分层趋势

### 2.2 对我们主线的直接映射

这些论文给我们的启发并不是“复用某个现成模块”，而是：

- 不要继续把优化点理解成“再做一种格式”；
- 而要把 `event/token + queue/admission + hierarchy + localized service` 作为同一个系统对象来设计。

这正好对应我们当前主线最缺的那一层：

- `STORM` 已经有了 token plane
- `GCSS-GLIDE` 已经有了 line plane
- **ATLAS 要做的是两者之间的 service plane**

---

## 3. 方案对比与推荐

### 3.1 方案 A：Core-local Token Aggregation

做法：

- receiver 端只按 `pre_global` 聚合 token；
- `BeginApply` 前再展开到现有 `dstcore` 路径；
- 不改存储格式，不改 service domain。

优点：

- 实现最稳；
- 语义风险最低；
- 适合做 proof-only。

缺点：

- 只能减少 receiver 对象膨胀；
- 很难继续压低真实 `memctrl.req_total`；
- 无法跨 core 共享 line service。

结论：

- 适合作为 **P0 证明层**；
- 不适合作为论文主方案。

### 3.2 方案 B：PE-shared Token-to-Line Service（推荐）

做法：

- 在 PE 内引入新的 `ATLAS` 单元；
- receiver 先存 token/descriptor，不立即展开为 edge；
- `BeginApply` 前由 ATLAS 用 **PE-shared index/layout** 把 token 提升成 line/segment 级服务描述符；
- DRAM 返回后在 PE 内按目标 core/post 分发；
- 最终仍走每 core 的确定性 retire。

优点：

- 真正命中 memory × NoC 协同交界面；
- 有机会在不破坏 row locality 的前提下，继续压低 `memctrl.req_total`；
- 和 `STORM` 的 block/PE 粒度天然可对齐；
- 比纯 index/issue tweak 更像体系结构创新。

缺点：

- 需要新的 `dstpe` 格式；
- 需要新增 PE-shared 硬件单元与分发路径；
- 观测/验证工作量较大。

结论：

- **推荐作为主方案。**

### 3.3 方案 C：Block-shared Full Service（2x2 destination block）

做法：

- 直接把 service domain 提升到 `STORM` 的 blocked multicast 域；
- 一个 block 共享 token admission、descriptor、line service。

优点：

- 理论共享范围最大；
- 叙事上最“统一”。

缺点：

- 实现侵入和验证风险都明显更高；
- 容易过早碰到复杂的一致性/流量/回写问题；
- 不适合做当前第一跳。

结论：

- 适合作为 **ATLAS 后续扩展**；
- 不建议作为第一版落地点。

---

## 4. 推荐主方案：ATLAS-PE

### 4.1 核心思想

ATLAS-PE 把 receiver 端的处理分成两个阶段：

1. **token 阶段**
   - 来自 `STORM` 的 `pre token` 先进入 PE-shared 的 token queue / descriptor table
   - 不立即展开为 `post_local` 级 edge

2. **line-service 阶段**
   - 到 `BeginApply` 或 Apply window 准备好时
   - ATLAS 根据 `dstpe` 索引把 token 提升为 `line/segment descriptors`
   - 由 line-aware service queue 统一向 DRAM 发射

这样做的本质变化是：

- 之前：`packet -> edge -> addr -> line`
- ATLAS 后：`packet -> token -> descriptor -> line`

也就是说，**我们不再把 token 过早膨胀成 edge，而是把它保留到足够接近真实 service domain 的地方再展开。**

### 4.2 推荐部署位置

ATLAS-PE 推荐作为 **PE-shared subcomponent** 挂在：

- `packet-first receiver path` 与 `SnnWorkload::expandPreGlobalToWindowEdgesFast_()` 之间；
- `WeightMemorySubsystem` 之前，但复用其下游 DRAM 发射与严格 retire 合同。

代码上的自然插入点是：

- receiver 输入：
  - [`NocSubsystem.cc`](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/noc/NocSubsystem.cc)
  - [`SnnPESubComponent.cc`](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc)
- workload 展开：
  - [`SnnWorkload.cc`](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc)
- memory service：
  - [`WeightMemorySubsystem.cc`](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc)

---

## 5. ATLAS-PE 的硬件组成

### 5.1 ATQ：Activation Token Queue

作用：

- 保存当前 step/window 内到达本 PE 的 `pre token`
- 以 `(step_seq, pre_global, src_tag)` 为主键做去重/合并
- 记录 first-touch 顺序、arrival count、来源 core/block hint

要求：

- 不做神经动力学语义判断；
- 只做接收、归并、预算与统计；
- 允许在 `Gather` 持续累积，在 `Apply` 前冻结当前快照。

### 5.2 TDT：Token Descriptor Table

作用：

- 维护 token 到 service descriptor 的桥接状态
- 为每个 `pre_global` 记录：
  - `arrival_count`
  - `first_touch_order`
  - `active_consumer_mask`
  - `descriptor_state`

它是 ATLAS 的关键语义对象：

- token 不是“收到一个包就立刻展开”
- 而是“进入一个可调度、可冻结、可追踪的 descriptor”

### 5.3 LAP：Line Admission Planner

作用：

- 在 `BeginApply` 或 Apply 准备阶段，读取 `dstpe` 索引
- 把 `pre token` 提升为一组 `line/segment descriptors`
- 做 admission、预算控制、line grouping、row-safe 排序

输入：

- token descriptors
- `dstpe` 索引
- 当前 Apply window 参数

输出：

- `line descriptors`

### 5.4 LSQ：Line Service Queue

作用：

- 维护等待发射的 line/segment 级请求
- 以 `line_addr` / `row_band` / `age` 为主排序键
- 对接现有 `WeightMemorySubsystem` 下游发射路径，避免重造 DRAM service 轮子

ATLAS 不应绕过现有 DRAM backend，而应复用：

- 真实 `ramulator2`
- 现有 line-size/cacheline 语义
- 现有严格 response/retire 统计链路

### 5.5 RDB：Response Distribution Buffer

作用：

- 当 line 返回后，把 payload 分发到对应 core/post accumulator
- 但不直接触发 spike，不改变 `Scatter` 收敛点
- 只负责把 line payload 变成“可退役的局部更新项”

---

## 6. 数据格式：`gcss_valueonly_dstpe_atlas_v1`

### 6.1 为什么必须引入新格式

如果继续沿用 `dstcore` 物理存储，那么：

- 即使 token 在 receiver 端先做了聚合；
- 一旦落回各个 core 各自独立的 values/index；
- ATLAS 也只能减少对象膨胀，难以继续减少真实 line service。

因此，ATLAS-PE 的主收益必须建立在：

- **PE-shared storage domain**

之上。

### 6.2 推荐布局

新增实验性格式：

- `synapse_weight_mode = gcss_valueonly_dstpe_atlas_v1`

输出文件（每 PE 一套）：

- `peXX/atlas.values.bin`
- `peXX/atlas.idx.bin`
- `peXX/atlas.meta.json`

基本布局：

1. `values`
   - 以 `pre_global` 为第一维
   - 在 PE 域内收集所有目标 core/post
   - 按 line/segment 紧凑布局

2. `idx`
   - `pre-MPHF -> seg_base / seg_count`
   - 每个 segment descriptor 描述：
     - `line_addr_or_value_base`
     - `segment_len`
     - `consumer_range_or_mask`
     - 可选 `row_band`

### 6.3 设计原则

1. 保留 `GCSS-GLIDE` 的核心优点
   - pre-major
   - locality-preserving
   - line-friendly

2. 只把共享域从 `dstcore` 提升到 `dstpe`
   - 不一步跳到全 block/global

3. index 仍需受约束
   - 新格式不能把 metadata 做到压过 values
   - 目标仍应守住：
     - `index_to_values_ratio <= 0.1~0.15` 的工程可控区间

---

## 7. 运行时数据流

### 7.1 当前主线

当前是：

1. `SpikeKey/SpikeTileKey`
2. `deliverPacket`
3. `lookupPostsLocalForPre_`
4. `recordEdgeWithPreRank`
5. `prepareGcssVlfIssueQueue_`
6. `issue line-aligned reads`
7. `setEdgeRetireReady_ / tryRetireEdges_`

### 7.2 引入 ATLAS 后

推荐路径改为：

1. `STORM` 仍生成 `SpikeKey/SpikeTileKey`
2. `NocSubsystem` 仍强制走 `MulticastRouter`
3. receiver 不立即调用 `expandPreGlobalToWindowEdgesFast_()`，而是：
   - `atlas_->acceptToken(pre_global, step_seq, src_meta, consumer_hint)`
4. `Gather` 期间，ATLAS 累积 token descriptors
5. `BeginApply` 时：
   - `atlas_->freezeWindow(step_seq)`
   - `atlas_->planLineDescriptors()`
6. `atlas_->issueLineDescriptors()` 通过 WMS/StdMem 发射真实 line 请求
7. line 返回后：
   - `atlas_->distributeLinePayload()`
   - 形成 per-core 的 ready update entries
8. 仍由每 core 的 deterministic retire 统一退役
9. `Scatter` 语义完全不变

---

## 8. 语义与严格性

### 8.1 不改变 GAS 的什么

ATLAS 必须明确 **不改变** 以下语义：

1. `Apply` 期只做局部累加，不触发 spike
2. 真实发放仍只允许在 `Scatter` 阶段发生
3. 同一 core 内的更新仍按确定性顺序退役
4. `validation.log` 的 `fail/warn/strict` 口径必须保持可对齐

### 8.2 为什么这是安全的

当前实现中：

- `WeightMemorySubsystem` 的 `acc_update(post_local, delta)` 只是局部状态累加；
- 输出发放仍由 `Scatter` 路径统一触发；
- 因此只要 ATLAS 保证：
  - 不改最终 `(post_local, delta)` 集合
  - 不改每 core 的 retire 顺序
  - 不提前跨越 `Scatter`

那么它只是改变：

- “权重如何被服务”

而不改变：

- “神经动力学何时生效、何时发放”

### 8.3 严格护栏

ATLAS 应默认具备：

1. `strict lookup miss => fatal`
2. `line descriptor decode mismatch => fatal`
3. `distribution target mismatch => fatal`
4. `retire ledger gap => fatal`

也就是说：

- 不允许 silent fallback
- 不允许 debug-only 自动修正

---

## 9. 推荐统计证据链

ATLAS 要想成为论文点，必须从第一版就把统计证据链设计好。

### 9.1 新增 runtime 统计

建议新增：

1. token 层
   - `atlas_rx_tokens_total`
   - `atlas_merged_tokens_total`
   - `atlas_first_touch_pres_total`
   - `atlas_active_descriptor_peak`

2. descriptor 层
   - `atlas_line_desc_total`
   - `atlas_line_desc_per_pre_avg`
   - `atlas_consumer_per_line_avg`
   - `atlas_desc_admission_block_total`

3. issue/service 层
   - `atlas_line_issue_total`
   - `atlas_line_issue_row_preserve_ratio`
   - `atlas_shared_line_uses_total`
   - `atlas_resp_fanout_total`

4. retire/distribution 层
   - `atlas_ready_updates_total`
   - `atlas_retire_wait_cycles_total`
   - `atlas_distribution_buffer_peak`

### 9.2 必须继续看的主线指标

仍必须看：

- `sim_time_actual_ns`
- `memhierarchy.memctrl.req_total`
- `memhierarchy.memctrl.bytes_est_total`
- `gas.memctrl_payload_utilization`
- `gas.memctrl_traffic_amplification`
- `gas.payload_bytes_per_memctrl_req_avg`
- `ramulator2.row_hit_rate_total`
- `ramulator2.avg_read_latency_0_avg`

### 9.3 机理闭环预期

如果 ATLAS 起效，最合理的证据链不是只看一个指标，而是：

1. receiver 对象膨胀下降
   - `atlas_merged_tokens_total / atlas_rx_tokens_total`

2. line 服务共享度上升
   - `atlas_shared_line_uses_total`
   - `atlas_consumer_per_line_avg`

3. 真实 DRAM 请求下降，且 locality 不崩
   - `memctrl.req_total` 下降
   - `row_hit_rate_total` 基本守住

4. payload plane 改善
   - `payload_bytes_per_memctrl_req_avg` 上升
   - `gas.memctrl_payload_utilization` 上升

5. 端到端时间下降
   - `sim_time_actual_ns` 下降

---

## 10. 实验计划

### 10.1 实验目录

推荐放在：

- `mainexp/experiments/2026-03-xx_atlas_pe_ab_v1/`

原因：

- 这是系统主线级机制，不是单纯 memory 微调；
- 应与 `full_system_baseline` 在同一口径下闭环。

### 10.2 A/B 矩阵

#### P0：proof-only

1. `full_system_baseline`
2. `atlas_core_token_only`

目的：

- 证明 receiver-side inflation 被压下来了；
- 但不强求 `memctrl.req_total` 立刻下降。

#### P1：主收益层

1. `full_system_baseline`
2. `atlas_pe_storage_only`
3. `atlas_pe_full`

目的：

- 验证 `dstpe` 布局本身的贡献；
- 验证 token-to-line service 层是否带来真实系统收益。

### 10.3 推荐口径

建议两条口径都跑：

1. **主口径**
   - `4x4`
   - `full_system_baseline`
   - `step=1`
   - `ramulator2`
   - `validation paper profile`

2. **压力口径**
   - `seed_only`
   - `steps=2`
   - 用于观察多 step 下 token/service 层是否稳定

### 10.4 成功判据

ATLAS 作为主线候选，至少应满足：

1. `validation.log`: `fail=0`
2. `row_hit_rate_total` 不发生灾难性回退
3. `memctrl.req_total` 有可重复下降
4. `payload_utilization` 有可解释改善
5. `sim_time_actual_ns` 有稳定收益

---

## 11. 推荐落地顺序

### 11.1 Phase A：ATLAS-Core Proof

目标：

- 不改 `dstcore` 存储格式；
- 先把 token queue / descriptor / observability 做出来；
- 建立“token 不必立即膨胀成 edge”的正确 contract。

产出：

- `atlas_*` 基础统计
- proof-only A/B

### 11.2 Phase B：ATLAS-PE Main

目标：

- 新增 `gcss_valueonly_dstpe_atlas_v1`
- 做 PE-shared line service
- 形成真实 memory × NoC 协同收益

产出：

- 正式主线 A/B
- 论文主图候选

### 11.3 Phase C：ATLAS-Block Future

目标：

- 与 `STORM` 的 blocked multicast 域完全对齐
- 把共享域从 PE 提升到 destination block

结论：

- 只作为后续研究扩展，不作为第一跳。

---

## 12. 这条线为什么比之前的失败路线更有希望

之前失败的路线有一个共同问题：

- 它们大多在既有 `dstcore + edge-local` 服务对象上做再调度；
- 要么不进入关键路径；
- 要么为了协同而破坏已经建立的 locality；
- 要么只是“换了一个节流器”，没有改变真实 service domain。

ATLAS 与它们的根本区别是：

1. 它改的是 **服务对象**
2. 它不打散 `GCSS-GLIDE` 已建立的 row/line 友好性
3. 它把 `STORM` 的 token 语义延续到了 receiver-side service plane
4. 它天然支持“显式队列 + admission + observability”，更符合近三年顶会的系统叙事

---

## 13. 最终定位

如果论文主线已经固定为：

- `DRAM-based SNN chip`
- `GAS` as memory backbone
- `GCSS-GLIDE` as memory optimization
- `STORM + MulticastRouter` as NoC innovation

那么 **ATLAS** 最适合作为：

- 下一步补上的 **memory × NoC 协同层**

它的目标不是替代上述主线，而是把它们真正接成一个统一的数据面：

- `STORM` 提供共享的前向 token
- `ATLAS` 把 token 提升为 line service descriptors
- `GCSS-GLIDE` 提供 DRAM-friendly 的 values/index/layout
- `GAS` 提供严格 apply/retire/scatter 语义主干

从论文叙事角度，这比“再加一个优化点”更像一个完整系统：

> **A DRAM-based SNN chip with a GAS memory backbone, GCSS-GLIDE memory hierarchy, STORM multicast NoC, and ATLAS token-to-line synapse service plane.**

