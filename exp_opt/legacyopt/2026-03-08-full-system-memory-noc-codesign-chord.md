# CHORD：面向 full_system_baseline 的 Memory × NoC 协同主方案设计

> 日期：2026-03-08  
> 状态：设计文档（仅设计，不改语义，不落实现）  
> 基线：`mainexp/experiments/2026-03-08_full_system_baseline_ab_v1/full_system_baseline`

## 0. 一句话结论

在当前 `full_system_baseline = STORM + GCSS-GLIDE + GAS` 已经跑通并显著优于单侧 baseline 的前提下，下一步最值得投入、也最有论文价值的方向，不是再做一个孤立的 memory tweak 或 NoC tweak，而是引入一个真正的 **cross-layer coordination mechanism**：

- **CHORD**  
- **Cohort-Harmonized Orchestration of Routed Dissemination and GAS service**

其核心思想是：

- `STORM` 已经把 spike dissemination 组织成 **block-aware multicast traffic**；
- `GCSS-GLIDE` 已经把 synapse access 组织成 **DRAM-friendly pre-major / line-friendly access path**；
- 但两者目前仍然是“各自最优”，**尚未共享同一种运行时控制抽象**。

`CHORD` 要做的，就是把两者通过一个共同的 **row cohort / service cohort** 抽象连起来：

- NoC 侧不再只是“尽快把包送到”；
- Memory 侧不再只是“来了多少 pre 就平铺 issue”；
- 而是让 **STORM 的 block multicast 到达形态** 与 **GAS/GCSS-GLIDE 的 DRAM service 形态** 在同一个 cohort 维度上被协同调度。

如果这个方向成立，它会成为当前系统主线的“画龙点睛”机制：

- `DRAM-based SNN chip`
- `GAS` memory backbone
- `GCSS-GLIDE` memory optimization
- `STORM` NoC optimization
- **`CHORD` cross-layer glue**

---

## 1. 为什么现在正适合做这件事

## 1.1 当前 full_system baseline 已经给出非常清晰的结构性证据

来自 `mainexp/experiments/2026-03-08_full_system_baseline_ab_v1/snapshot/compare.tsv`：

- `memory_baseline = Merlin + GCSS-GLIDE`
- `noc_baseline = STORM + GCSS-idx2`
- `full_system_baseline = STORM + GCSS-GLIDE`

关键结果：

1. `memory_baseline -> full_system_baseline`
- `sim_time_actual_ns`: `1086400 -> 257453`（约 `4.22x` 改善）
- memory 指标几乎不变：
  - `memctrl.req_total`: `150110 -> 150907`
  - `payload_utilization`: `0.317663 -> 0.316370`

说明：
- `GCSS-GLIDE` 已经把 memory side 做对了；
- `STORM` 的主要价值体现在 NoC / tail / drain 上。

2. `noc_baseline -> full_system_baseline`
- `sim_time_actual_ns`: `1383670 -> 257453`（约 `5.37x` 改善）
- NoC 形态接近：
  - `tx_spikekey_packets_total`: 都是 `634533`
  - `rx_spikekey_packets_total`: 都是 `8843654`
- 但 memory 指标差异极大：
  - `memctrl.req_total`: `1684046 -> 150907`
  - `payload_utilization`: `0.02835 -> 0.31637`
  - `payload_bytes_per_memctrl_req_avg`: `1.814 -> 20.248`

说明：
- `STORM` 已经把 NoC 数据面做对了；
- `GCSS-GLIDE` 的 memory path 仍然是不可替代的。

结论：
- 我们已经拥有一对“各自成立”的主线子系统；
- 现在缺的不是更多局部 patch，缺的是 **把这两条主线组织成更强的协同系统**。

## 1.2 当前系统里真正还没被利用的，是“共同控制抽象”

今天的 full system 仍有一个根本缺口：

- `STORM` 的控制粒度是 **destination block / multicast tree / packet wave**；
- `GCSS-GLIDE` 的控制粒度是 **pre-major / cacheline / row-locality / issue order**；
- 它们在 runtime 上还没有通过统一抽象打通。

这会导致一个典型现象：

- NoC 送到接收 PE 的到达顺序，是“网络友好”的；
- 但 Apply 阶段真正发 DRAM 读时，它们会被重新打散成“memory friendly but network-unaware”的 issue 序列；
- 因此仍然存在 **跨层错位**：网络与内存没有围绕同一个局部性维度协同。

`CHORD` 就是要填这块空白。

---

## 2. 设计目标与硬约束

## 2.1 设计目标

新机制必须同时满足四个目标：

1. **足够创新**
- 不能只是“再加一个 prefetch”或“再调一个 issue heuristic”；
- 必须明确体现为 memory × NoC 的联合机制。

2. **足够 solid**
- 不依赖你们当前 synthetic 全 1 权重；
- 不依赖脆弱的超参数运气；
- 必须建立在 `full_system_baseline` 已证实成立的主线上。

3. **足够 work**
- 不应重新走向高风险的大语义重构；
- 不应要求跨 PE 共享权重值或跨 core 共享 partial sum；
- 应尽量复用已有的 `GlobalGasStepController / MultiCorePE / WeightMemorySubsystem / STORM router` 骨架。

4. **论文可讲**
- 要能用一句话讲清楚“系统里新增了什么硬件/控制逻辑”；
- 要能形成机理闭环统计，而不是只拿端到端时间赌运气。

## 2.2 硬约束

新机制必须严格遵守：

- 不改变 `GAS` 的 gather/apply/retire 基本语义；
- 不改变 `full_system_baseline` 的严格验证口径（`fail=0 warn=1` 不得回退成 fail）；
- 不重新引入被证明风险过高的路径：
  - 不做跨 PE/跨 core 的共享 weight value 传输；
  - 不做需要复制/再分发 raw weight line 的 block service；
  - 不做会破坏 commit / retire 顺序 seal 的投机执行。

这几个约束是本设计成立的底线。

---

## 3. 历史路线复盘：哪些坑不能再踩

## 3.1 不能回到“共享权重服务”范式

历史上最接近“联合优化”的路线，是 `TASS-LF` / `naive_tass` 一类 block-shared synapse service 思路：

- 把 `STORM` 的 `2x2 block` 传播域，直接升格为 memory service 域；
- 试图把 block 内多个 PE/core 的 synapse service 合并或共享。

这个方向的问题不是“不聪明”，而是工程与语义风险过高：

- 会引入新的 weight 数据服务路径；
- 容易碰到 partial sum / response fanout / tail latency / barrier drain 的复杂交互；
- 很容易变成“memory gain 有一点，但系统长尾更糟”。

因此，新的主方案必须避免“共享 raw weight / 共享 partial sum”这类重路径。

## 3.2 不能回到“额外 speculative DRAM 流量”范式

`STORM-PIF / STORM-NIP` 的结论已经很清楚：

- 预取链路本身可以工作；
- join / waiter / cache fill 证据可以闭环；
- 但端到端收益不稳定，甚至经常为负。

原因本质上是：

- 它们增加了一条新的 memory 控制流；
- 这条控制流并没有被系统主线真正吸收；
- 所以局部读延迟改善，未必能转化为系统时间收益。

因此，新的主方案不应以“再发一条控制型 DRAM 预取链路”为主。

## 3.3 不能只做 coarse global credit 2.0

此前 `global credit` 类方案的问题在于：

- 它抓住的是“慢 PE”这类 coarse 粒度症状；
- 没有真正抓到 `STORM` 与 `GCSS-GLIDE` 之间共享的局部性对象；
- 因此可解释性和收益稳定性都不够强。

所以新的方案必须比 global credit 更具体：

- 不是“哪个 PE 慢”；
- 而是“哪个 memory cohort / 哪个 block cohort 的协同顺序最该先被服务”。

---

## 4. 相关工作边界：我们和公开方案的真正差异在哪里

这里给出对当前公开工作的一个收敛判断。注意：以下判断是基于公开资料摘要与当前系统现状的 **推断**，不是逐项全文复现。

1. **Loihi 2** 的官方定位仍然是高度片上化、分层互联的 neuromorphic processor，更强调 on-chip programmability / hierarchy，而不是我们这种以真实 DRAM-backed synapse 为中心的 memory system 问题。  
来源：Intel 官方介绍页  
<https://www.intel.com/content/www/us/en/research/neuromorphic-computing-loihi-2-technology-brief.html>

2. **FireFly-S (2025)** 这类近期 SNN accelerator 工作，重点在于利用 neuronal sparsity、skip inactive neurons、降低无效计算与访存，但它们并没有给出“native multicast NoC 与 DRAM-truth synapse service 的联合 runtime control plane”这一层的系统组织。  
来源：arXiv 摘要页  
<https://arxiv.org/abs/2507.12486>

3. 你们当前系统最大的差异点不是“我们也有稀疏/多播/索引压缩”，而是：
- 你们已经有 **真实 Ramulator2 后端**；
- 已经有 **GAS** 这样的 memory backbone；
- 已经有 **GCSS-GLIDE** 这样 DRAM-friendly 的 index/storage；
- 已经有 **STORM** 这样原生 multicast-aware NoC；
- 但仍缺一个把它们连接起来的 **cross-layer runtime abstraction**。

这正是 `CHORD` 的立足点。

因此，论文中的差异化叙事应当是：

- 公开工作通常在单侧优化上很强；
- 我们的空白点是：**在 DRAM-based SNN 芯片里，让 memory backbone 与 native-multicast NoC 围绕同一个 locality object 协同工作。**

---

## 5. 备选方向对比

## 5.1 方案 A：CHORD（推荐）

核心思想：
- 从 `GCSS-GLIDE` 离线布局中抽取一个小而稳定的 **row/service cohort**；
- 在接收 PE 侧按 cohort 对 incoming pre/spike 进行 gather 分桶；
- Apply 时按 cohort 而不是平铺 pre 顺序去组织发射；
- 可选地把 cohort 压力反馈给 `STORM` 的发送/准入，使 network wave 与 memory wave 同步。

优点：
- 真正的 memory × NoC 协同；
- 不新增 raw weight traffic；
- 可以复用已有 GAS/retire seal；
- 有很清晰的统计与机理闭环。

风险：
- 需要在 runtime 新引入 cohort table / ingress queues / cohort scheduler；
- 若 source-side admission 做得太激进，可能引入 gather 内长尾。

结论：
- 最平衡、最有发表潜力、也最可能做出稳定正收益的方案。

## 5.2 方案 B：NIP 2.0 / selective prefetch + NoC-aware gating

核心思想：
- 保留旧的 prefetch/join 思路；
- 用热点筛选、NoC 拥塞门控、tail guard 去减少负收益。

优点：
- 与现有实验代码较近；
- 改动相对局部。

缺点：
- 容易被 reviewer 视为“已有失败方向的修补”；
- 仍然属于控制流加法，而不是统一跨层抽象；
- 论文 novelty 不够强。

结论：
- 可作为备胎或辅助机制，不适合作为新的系统级 headline。

## 5.3 方案 C：重做 block-shared synapse service

核心思想：
- 回到 `TASS-LF`/block-shared service，但做得更稳。

优点：
- 表面上 cross-layer 很强。

缺点：
- 高风险重路径；
- 极容易复现之前的 tail / barrier / semantics 问题；
- 在当前项目节奏下，投入产出比太差。

结论：
- 明确不推荐作为下一主方案。

---

## 6. 推荐主方案：CHORD

## 6.1 核心洞察

当前 full system 最大的问题不是 memory 不够强，也不是 NoC 不够强，而是：

- `STORM` 的“最佳组织对象”是 **destination block / multicast wave**；
- `GCSS-GLIDE + GAS` 的“最佳组织对象”是 **pre-major line / DRAM row-local service wave**；
- 两个 wave 之间没有对齐。

`CHORD` 的核心洞察是：

- 在 destination PE 视角，每个 `pre_global` 对应的 local weight service，并不是完全随机的；
- 它在 `GCSS-GLIDE` 布局和真实 DRAM 几何下，会落入某个相对稳定的 **service cohort**；
- 只要把 incoming SpikeKey/Spike 先在 cohort 上归类，再按 cohort 组织 Apply，那么：
  - memory 侧 row churn 会减轻；
  - apply tail 会下降；
  - 若再让 network admission 参考 cohort/backpressure，NoC 也能少做“无意义地把错 cohort 的流量先送进来”。

换句话说：

- `CHORD` 把 `row cohort` 变成 memory 与 NoC 共用的控制语言。

这就是它相对现有系统最大的结构升级。

## 6.2 CHORD 的两层结构

### 层 A：Destination-side Cohortized GAS（必须做）

这是 `CHORD` 的主体，也是最稳的收益来源。

新增一个 PE-local 的 cohortized gather/apply 路径：

1. **离线 cohort 抽取**
- 从 `GCSS-GLIDE` artifact 中，对每个 `(core, pre_global)` 计算：
  - 主导 bank
  - 主导 row-color / row-cluster
  - line span / burst span
- 再把它们压缩成一个小 cohort id，例如 `3~4 bit`。

2. **运行时 cohort ingress**
- 当 `SpikeKey`/`Spike` 到达接收侧并被映射到 local `pre_global` 时：
  - 不立即把所有 edge 平铺到一个 flat collector；
  - 先做 `pre_global -> cohort_id` 查表；
  - 将该 pre 记入 `CohortIngressQueue[cohort_id]`。
- 仍可复用现有 dedup / window sets；
- 只是把“等价的 pre 集”先在 cohort 维度上分桶。

3. **cohortized apply scheduler**
- BeginApply 后，不再简单地按 flat pre/edge 序 issue；
- 而是从当前 ready cohort 中选择一个 cohort 波次发射；
- 选择原则完全确定性：
  - 优先 queue_len 大、age 老、且与当前 hot row/bank 匹配的 cohort；
  - tie-break 固定按 cohort_id。

4. **retire seal 不变**
- 发射顺序允许 cohortized；
- retire 仍保持当前 `global_inorder` seal；
- 所以不改变严格 GAS 语义边界。

### 层 B：STORM Admission Coupling（推荐做，体现真正协同）

在层 A 成立后，再加入一个轻量的 NoC coupling：

1. **cohort pressure summary**
- 每个 PE 在 step 结束时上报：
  - 各 cohort 的累计服务量
  - 各 cohort 的堵塞周期
  - 各 bank 的冲突/等待 proxy
- 这些统计远比旧的“哪个 PE 慢”更有解释性。

2. **step-level admission plan**
- `GlobalGasStepController` 在下一个 step 的 `START_STEP` 时，广播一个非常小的计划：
  - 每个 PE 的 `preferred cohort epoch`
  - 或更简单：每个 PE/PE-block 的 `cohort admission weight`

3. **source/network side bounded gating**
- 发送侧不需要理解完整 DRAM row；
- 它只需要在对目标 block/PE 发送 `SpikeKey` 时，尊重该目标的 admission weight；
- 若目标当前不在 preferred epoch，可短暂缓冲；超过 bounded delay 直接 fallback 发送。

这样做的好处是：
- 不要求 source-side 完整掌握 destination memory layout；
- 但可以让 NoC wave 尽量不要和 destination memory wave 对着干。

这才是 `CHORD` 的真正 “memory × NoC” 协同部分。

---

## 7. 为什么 CHORD 是“足够 novel + 足够 solid + 足够 work”

## 7.1 Novel：它引入了一个新的 shared abstraction

很多联合优化失败，根因都是“只是把两个 subsystem 放在一起”，但没有共同抽象。

`CHORD` 的 novelty 就在这里：

- 它不把 NoC 和 memory 仅仅看成两个受益点；
- 它提出一个共享抽象：**cohort**；
- 并让这个 cohort 同时驱动：
  - destination-side synapse service order
  - source/network-side admission order

这比“router aware prefetch”“row aware issue policy”“global credit 2.0”都更像一个系统架构想法。

## 7.2 Solid：它不改变主路径数据语义

`CHORD` 不做这些危险事情：

- 不共享 raw weight line
- 不跨 PE 搬运 weight value
- 不重排 retire/commit 语义
- 不引入投机 prefetch response dependence

它做的本质上是：

- **分类（classify）**
- **排队（queue）**
- **准入（admit）**
- **确定性调度（deterministic scheduling）**

这条路线比重新设计 data path 稳得多。

## 7.3 Work：它能直接落到现有代码骨架

最关键的是，`CHORD` 不需要新造一个系统；它能嫁接在现有主线上：

- `SnnWorkload::deliverPacket / expandPreGlobalToWindowEdgesFast_`
  - 负责到达时的 cohort classify
- `WeightMemorySubsystem`
  - 负责 cohort ingress queues + apply scheduler
- `GlobalGasStepController`
  - 负责 step-level cohort admission plan
- `SpikeCommSubsystem / NocSubsystem / STORM path`
  - 负责 bounded admission gating

也就是说，它是一个 **architecture-level extension of the existing full-system baseline**，而不是一条平行宇宙路线。

---

## 8. 具体硬件/软件映射

## 8.1 离线数据结构

在 `GCSS-GLIDE` artifact 基础上新增一个很小的 sidecar：

- `cohort_by_pre.bin`
- 每 core 一份
- 内容：`pre_id -> cohort_id`
- 可选附加字段：`dominant_bank`, `span_class`

约束：
- 新 sidecar 必须仍满足“明显小于 values”，目标是：
  - `cohort sidecar <= index 的 1/4`
  - 最好仅 `0.5~1 bit/edge` 的量级折算

由于它是按 unique pre 存，而不是按 edge 存，这个目标是现实的。

## 8.2 运行时硬件单元

### 1. `PreCohortTable`（SRAM 常驻）
- 输入：`pre_global` / `pre_id`
- 输出：`cohort_id`, `dominant_bank`, `span_class`
- 作用：把 arrival 事件投影到 memory-service cohort

### 2. `CohortIngressQueues[K]`
- 每个 PE 或每个 core 一组小 FIFO
- 只存 `pre_id` / `window-local pre token`
- 与现有 window dedup 机制协同，避免重复入队

### 3. `CohortScoreboard`
- 记录：
  - ready count
  - age
  - bank outstanding
  - optional hot-row match

### 4. `CohortApplyScheduler`
- 在 `issueFromEdges()` 前决定本轮从哪个 cohort 拉取 pre/edge
- 确定性打分函数建议：
  - `score = a*ready + b*age + c*row_match - d*bank_busy`
- 固定参数，不做在线学习

### 5. `AdmissionPlanTable`（可选 P1）
- 由 `GlobalGasStepController` 在每步开始时刷新
- source-side / NoC-side 用它做 bounded gating

## 8.3 运行时数据流

1. 发送侧 neuron fire -> `SpikeCommSubsystem`
2. `STORM` 仍按当前 `SpikeKey / blocked multicast` 主线发送
3. 接收侧 packet 到达后，`SnnWorkload` 不再只 flat-record，而是：
   - 查 `PreCohortTable`
   - 写入 `CohortIngressQueues`
4. BeginApply 时，`CohortApplyScheduler` 选择 cohort 波次
5. `WeightMemorySubsystem` 按 cohort 波次发起现有 DRAM read path
6. retire 仍由原有 seal 完成

P1 时再加：
7. 上一步 cohort pressure -> `GlobalGasStepController`
8. 下一步 start_step 广播 admission plan
9. source/network side 按 plan 做 bounded gating

---

## 9. 语义与验证安全性

`CHORD` 的一个核心卖点是：**它改的是组织方式，不改的是结果边界。**

必须明确坚持以下语义原则：

1. **Gather completeness 不变**
- 同一步应处理的 incoming pre 不能丢；
- bounded gating 只能改变 gather 内部到达顺序，不能跨出当前 step/gather 边界。

2. **Apply semantics 不变**
- `acc_update(post_local, delta)` 的最终集合必须与 baseline 一致；
- `CHORD` 只改变 issue 顺序，不改变 edge membership。

3. **Retire semantics 不变**
- 保持现有 `global_inorder` retire seal；
- 禁止因为 cohort scheduler 而改变 commit 语义。

4. **Fallback 必须存在**
- 若 cohort 元数据缺失、队列溢出、admission plan 异常：
  - 直接 fallback 到 `full_system_baseline` 的 flat path；
- 绝不能让实验性路径破坏主线正确性。

因此，`CHORD` 是一个非常适合作为“主线上的实验性 feature flag”落地的机制。

---

## 10. 论文证据链：必须新增哪些统计

为了让 `CHORD` 成为可写进 ISCA/ASPLOS 的机制，必须从一开始就设计统计链路。

## 10.1 新增 memory×NoC 协同统计

### Destination / memory side
- `gas.cohort_ready_total[k]`
- `gas.cohort_issue_total[k]`
- `gas.cohort_row_match_total[k]`
- `gas.cohort_bank_busy_block_cycles_total[k]`
- `gas.cohort_switches_total`
- `gas.cohort_avg_run_length`
- `gas.cohort_open_row_reuse_total`

### Admission / NoC side
- `storm.chord_admission_hold_packets_total`
- `storm.chord_admission_hold_cycles_total`
- `storm.chord_admission_fallback_send_total`
- `storm.chord_preferred_epoch_hits_total`
- `storm.chord_epoch_mismatch_total`

### Cross-layer summary
- `joint.cohort_alignment_score`
  - 例如：按 cohort 连续 issue 的比例
- `joint.cohort_mismatch_tail_cycles_total`
  - 表示 NoC 已送达但 memory 当前不愿意服务的累计尾部
- `joint.bytes_per_cohort_wave_avg`
- `joint.row_hits_per_cohort_wave_avg`

## 10.2 现有已有统计仍然是主指标

主结果仍应看：
- `sim_time_actual_ns`
- `gas.apply_ns_avg`
- `memctrl.req_total`
- `gas.memctrl_payload_utilization`
- `gas.payload_bytes_per_memctrl_req_avg`
- `ramulator2.row_hit_rate_total`
- `ramulator2.avg_read_latency_0_avg`
- STORM 侧 byte/clone 指标

关键要求是：
- `CHORD` 的新统计必须能解释这些主指标为什么变好，而不是只新增一堆漂亮但无关的 counters。

---

## 11. 实验矩阵（闭环计划）

## 11.1 基线

唯一主基线：
- `full_system_baseline`
- 即：`STORM + GCSS-GLIDE + GAS`

不再用 `memory_baseline` 或 `noc_baseline` 作为主 headline baseline；
它们只作为定位收益来源的对照组。

## 11.2 A/B/C/D 最小矩阵

建议最小做 4 组：

1. **A: full_system_baseline**
- 当前主基线

2. **B: CHORD-L only**
- 只开 destination-side cohort ingress + cohort apply scheduler
- 不开 admission coupling

3. **C: CHORD-A only**
- 只开 admission coupling
- 接收侧仍走 flat path

4. **D: CHORD full**
- 同时开 L + A

这样可以清楚回答：
- 收益到底来自 local service ordering 还是 network admission alignment
- 两者是否存在组合增益

## 11.3 必须保持的统一口径

- `4x4 bcsr10k step1`
- `ramulator2_ddr5`
- `apply_issue_policy=order`（除非 cohort scheduler 作为新 issue policy 显式替代）
- `MESH_GAS_VLF_ENABLE=1`
- `MESH_GAS_VLF_RUN_ENABLE=0`
- `fail=0`

## 11.4 预期现象

如果 `CHORD` 打中真正瓶颈，应该看到：

1. `D` 相比 `A`
- `sim_time_actual_ns` 下降
- `gas.apply_ns_avg` 明显下降
- `row_hit_rate_total` 上升或 `avg_read_latency` 下降

2. `B` 的 memory 指标先改善
- 说明 cohortized apply 本身有效

3. `C` 的 NoC tail 指标先改善
- 说明 admission alignment 本身有效

4. `D` 的收益大于 `B` 或 `C`
- 这才说明真正存在 memory × NoC 协同，而不是两边各做各的。

---

## 12. 为什么这条路线最像一个 architecture paper idea

如果把当前系统写成论文，已有部分已经很强：

- `GAS`：memory backbone
- `GCSS-GLIDE`：DRAM-friendly memory optimization
- `STORM`：native-multicast NoC optimization

但 reviewer 很可能会问一个问题：

- 你们的 memory 和 NoC 现在是“两个很好的 subsystem”，还是“一个真正协同的系统”？

`CHORD` 正是在回答这个问题。

它提供的不是另一个局部优化，而是：

- 一个让 `STORM` 和 `GCSS-GLIDE` 围绕同一局部性对象协同运作的 runtime architecture。

这使得整篇系统论文从：
- “memory 很强 + NoC 很强”

提升为：
- “我们构建了一个 DRAM-based SNN chip，其中 GAS/GCSS-GLIDE 负责 memory，STORM 负责 network，而 CHORD 则把两者在 runtime 上编织成一个协同系统。”

这正是最接近 ISCA/ASPLOS 味道的地方。

---

## 13. 最终建议

下一步不建议再把精力放在：
- 单独的 prefetch 变体
- 单独的 router 小修小补
- 重新激活高风险 shared-synapse 路径

而应把主线明确收敛到：

1. **以 `full_system_baseline` 为唯一主基线**
2. **以 `CHORD` 为新的 memory × NoC 协同主方案**
3. **先做 `CHORD-L`，再做 `CHORD-A`，最后合成 `CHORD full`**

如果这条路线成立，它很有希望成为当前系统里最有“架构闭环”气质的最后一块拼图。
