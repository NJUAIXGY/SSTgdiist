# 完整系统主线：DRAM-based SNN 芯片 + GAS 内存主干 + GCSS-GLIDE + STORM

> 日期：2026-03-06  
> 状态：主线收口文档（按当前论文主线重新组织）

## 0. 一句话结论

截至当前版本，我们的完整系统主线应统一组织为：

- **顶层框架**：`DRAM-based SNN chip`
- **内存访问与执行主干**：`GAS`
- **内存系统关键优化**：`GCSS-GLIDE`
- **NoC 子系统关键优化**：`STORM`
- **NoC 主线硬件后端**：`MulticastRouter`

如果需要一个完整的系统级论文口径，推荐使用：

- **`A DRAM-based SNN chip with a GAS memory backbone, GCSS-GLIDE memory optimization, and STORM native-multicast NoC`**

这里最重要的层级关系是：

- `DRAM-based SNN chip` 是整套系统的顶层架构；
- `GAS` 不是一个与 `GCSS-GLIDE` 并列的小机制，而是整个芯片的 **内存访问与执行主干**；
- `GCSS-GLIDE` 是建立在 `GAS` 之上的 **memory hierarchy / synapse storage 优化**；
- `STORM` 是芯片 NoC 层面的关键创新，而 **`MulticastRouter` 不再只是实验后端，而是主线架构的一部分**。

因此，当前最合适的理解方式不是“多个优化并列”，而是：

- 一个面向大规模 SNN 的 `DRAM-based` 芯片架构；
- 其中 `GAS` 负责把 synapse access 组织成稳定主干；
- `GCSS-GLIDE` 负责让这条内存主干在 DRAM 后端下成立得更稳；
- `STORM + MulticastRouter` 负责从 NoC 侧削减 spike dissemination 的复制与传输放大。

---

## 1. 正确的主线层级

### 1.1 顶层：DRAM-based SNN chip

当前论文最合理的总框架，不应写成“我们做了 memory 优化 + NoC 优化”，而应写成：

- **我们设计了一种面向大规模 SNN 的 DRAM-based chip architecture**。

原因很直接：

- 目标规模是 `10M-100M` 神经元量级；
- 到这个规模以后，权重集不可能全部依赖片上小容量存储；
- 系统必须围绕真实 DRAM 后端来组织 synapse storage、访存行为与执行节奏。

因此，“DRAM-based” 不是一个实现细节，而是整篇系统工作的起点与约束条件。

### 1.2 中层：GAS 是内存系统主干

在这个框架下，`GAS` 的定位应明确为：

- **芯片的 memory-access and execution backbone**；
- 或中文：**芯片的内存访问与执行主干**。

`GAS` 的价值不是“又一个优化”，而是：

- 它规定了 synapse gather/apply 如何组织；
- 它规定了发射、回包、退役如何受控；
- 它规定了后续 memory / NoC 机制如何接入而不破坏语义。

所以，`GAS` 与 `GCSS-GLIDE` 不是同级关系。正确关系应是：

- `GAS` 是主干；
- `GCSS-GLIDE` 是长在这条主干上的 memory optimization。

### 1.3 并列子系统：Memory 与 NoC

在 `DRAM-based SNN chip` 这个顶层框架下，可以把体系结构分成两条关键子系统：

1. **Memory side**
- 主干：`GAS`
- 优化：`GCSS-GLIDE`

2. **NoC side**
- 主线：`STORM`
- 主线 router backend：`MulticastRouter`

这才是当前最自然、最稳的系统组织方式。

---

## 2. 为什么这才是更合理的论文组织

### 2.1 它更符合因果关系

之前如果把：

- `GAS`
- `GCSS-GLIDE`
- `STORM`

近似并列摆放，会给人一种“三个贡献模块平行堆叠”的感觉。

但从真实机制上看，并不是这样：

- `GAS` 决定 synapse access 的组织方式；
- `GCSS-GLIDE` 决定在这种组织方式下，metadata 如何被压缩且不伤 locality；
- `STORM` 决定 spike dissemination 如何在 NoC 中更接近硬件友好的传播形态。

所以更准确的关系是：

- `GAS` 是 memory system backbone；
- `GCSS-GLIDE` 是 memory-side optimization；
- `STORM` 是 NoC-side optimization。

### 2.2 它更突出系统性，而不是工程拼装

这种层级关系有一个很大的好处：

- 它把整篇工作从“很多优化点”提升为“一个架构 + 两条关键子系统协同”。

这非常重要，因为体系结构论文真正想表达的不是：

- 我们做了很多 tweak；

而是：

- 我们围绕一个核心系统瓶颈，重构了 memory path 与 network path。

在你们这里，这个核心瓶颈就是：

- **大规模 SNN 的数据移动放大效应**。

### 2.3 它让 MulticastRouter 的地位变得正确

如果继续把 `MulticastRouter` 只当“实验后端”，那 `STORM` 会显得像：

- 一个有趣的 multicast 想法；
- 但不一定是主系统真正采用的网络架构。

这会削弱论文力度。

更合理的做法是明确：

- **专用 `MulticastRouter` 后端就是主线 NoC 架构的一部分**；
- `STORM` 不是在通用 NoC 上做的小修补，而是建立在这条原生 multicast-aware NoC 上的数据面创新。

这会让 `STORM` 从“通信优化”升级为：

- **芯片 NoC 架构创新的一部分**。

---

## 3. 顶层框架：DRAM-based SNN chip

### 3.1 为什么必须从 DRAM-based 出发

你们当前系统最有分量的基础，不是某个局部机制，而是：

- **你们从一开始就把问题放在真实 DRAM-backed 的 SNN 芯片上来讨论。**

这带来几个和传统片上小存储 SNN 很不一样的挑战：

1. **synapse values 必须大规模常驻 DRAM**
- 不能假设全部权重常驻片上 SRAM。

2. **memory access 成为一等问题**
- 不是“顺手优化一下 DRAM”，而是整个系统能否扩展的决定因素。

3. **NoC 与 memory 不能分开看**
- 上游 spike fanout 会直接决定下游 synapse access 的压力形态；
- 因此网络传播和内存访问是耦合的。

### 3.2 芯片主线的真正命题

因此，当前完整系统的真正命题应收敛为：

- **如何在一个 DRAM-based SNN 芯片中，同时控制 spike dissemination 和 synapse access 的数据移动放大。**

这就自然导向两条主线：

- Memory path：`GAS + GCSS-GLIDE`
- NoC path：`STORM + MulticastRouter`

---

## 4. Memory 主线：GAS 是主干，GCSS-GLIDE 是优化

### 4.1 GAS 的正确定位

`GAS` 当前应被严格定义为：

- **memory-access and execution backbone**

它做的事情不是一个孤立优化，而是：

- 规定 Gather 如何记录本轮 window 需要处理的 synapse edges；
- 规定 Apply 如何发起权重读取与累加；
- 规定 retire 如何受控，以避免乱序回包破坏语义与验证结果。

因此，`GAS` 是整条 memory system 的主干。

### 4.2 为什么 GAS 必须被放到 memory 主线中心

如果没有 `GAS`，后续 memory-side 优化很容易变成零散 patch：

- 某个预取；
- 某个调度；
- 某个数据结构；
- 某个缓存。

但有了 `GAS`，这些优化就有了清晰边界：

- 优化可以改变访存形态；
- 但不能破坏 gather/apply 的语义框架；
- 也不能破坏严格验证结果。

这让 `GAS` 具备了很强的论文价值：

- 它是 memory system 的组织原则，而不是 memory tweak。

### 4.3 GCSS-GLIDE 的正确定位

在这个层级下，`GCSS-GLIDE` 应被明确写成：

- **`GAS` memory system 的关键优化**；
- 或更具体地说：**一种 locality-preserving synapse index/storage optimization for the GAS memory backbone**。

它不是单独一套 memory system；
它的职责是：

- 让 `GAS` 在 DRAM-backed synapse storage 下更可扩展；
- 压低 metadata footprint；
- 同时守住 values/cacheline locality 与 runtime DRAM 行为。

### 4.4 GCSS-GLIDE 为什么必须嵌在 GAS 下面写

因为它的全部价值都建立在这几个前提上：

- `GAS` 已经定义了受控的 synapse access 路径；
- `profile_greedy` 已经提供了当前 values locality 的基础；
- 系统目标不是任意压缩，而是 **不破坏 DRAM behavior 的压缩**。

因此正确的叙事顺序应是：

1. 先有 `GAS` 这条 memory backbone；
2. 再有 `GCSS-GLIDE` 去优化这条 backbone 的 synapse metadata/path。

### 4.5 GCSS-GLIDE 当前主线事实

当前唯一稳定、冻结的 memory 优化口径为：

- `physical_order_mode=profile_greedy`
- `index_version=7`
- `format=gcss_valueonly_dstcore_vlf_premphf_plp_v7_lpbl`

对应 artifact：

- `sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_v7_lpblp_j8/`

对应 A/B：

- `memop/experiments/2026-03-06_gcss_plp_v7_lpbl_ab_v1/`

当前关键静态结果：

- `index_to_values_ratio = 0.09757175`
- `index_bits_per_edge = 3.12229609`

相对 `v6 OKSR`：

- `index_to_values_ratio: 0.11285300 -> 0.09757175`
- `index_bits_per_edge: 3.61129609 -> 3.12229609`

当前关键 runtime 闭环：

- `sim_time_actual_ns = 1086400 -> 1086400`
- `memctrl_req_total = 150110 -> 150110`
- `memctrl_bytes_est_total = 9607040 -> 9607040`
- `gas_memctrl_payload_utilization = 0.317663 -> 0.317663`
- `gas_memctrl_traffic_amplification = 3.14799 -> 3.14799`

这说明：

- `GCSS-GLIDE` 已经把索引压到 `values` 的 `1/10` 以下；
- 但没有破坏 `GAS` 的 runtime memory behavior。

### 4.6 当前 memory 主线结论

所以当前 memory 主线最准确的写法不是：

- `GAS + GCSS-GLIDE` 两者并列贡献

而是：

- **`GAS` 是 memory backbone**
- **`GCSS-GLIDE` 是该 backbone 的主线优化**

---

## 5. NoC 主线：STORM + MulticastRouter

### 5.1 STORM 的正确定位

`STORM` 当前应被定义为：

- **芯片 NoC 子系统的关键优化体系**

更重要的是，既然当前我们决定把专用 `MulticastRouter` 后端纳入主线，那么必须明确：

- **`MulticastRouter` 不再只是实验后端，而是主线 NoC 架构的一部分。**

这意味着当前 NoC 主线应统一写成：

- `STORM` 机制栈
- 运行在主线 `MulticastRouter` backend 上

### 5.2 为什么这样更合理

因为 `STORM` 的创新不只是编码技巧，而是建立在一个原生支持 multicast-aware dissemination 的 NoC 上：

- 复制点后移到 router / endpoint；
- 路径共享发生在网络中；
- block 内尽量本地投递而不是复制后再入网；
- payload 缩短通过 byte-aware router service 在 tail latency 上真实体现。

如果没有 `MulticastRouter` 这条主线硬件后端，上述很多收益只能被理解成“模拟中的 side experiment”。

而把它纳入主线后，`STORM` 的地位就提升为：

- **NoC architecture innovation**，而不是普通软件/协议优化。

### 5.3 当前应进入主线的 STORM 内容

当前应进入论文主收益叙事的，主要是 `STORM-DataPlane`：

1. `SpikeKey / SpikeTileKey`
2. blocked multicast
3. tile aggregation
4. `InterBundle V2`
5. compact mask + byte-aware serialization
6. local-endpoint multicast
7. Rx fastpath

这些机制共同定义了你们的 NoC 数据面主线。

### 5.4 当前证据与主线要求

既然现在我们把 `MulticastRouter` 作为主线，那么后续主图、主表、主结果应尽量遵守一个原则：

- **headline 结果尽量在 `STORM + MulticastRouter` 这条统一后端上闭环。**

这样论文叙事才不会出现：

- 架构主线是一套；
- 关键证据却是另一套后端。

这点对后续论文收口非常重要。

### 5.5 当前不应进入 NoC 主收益叙事的内容

即使把 `MulticastRouter` 提升为主线，也仍然要严格区分：

- `STORM-DataPlane`：当前主贡献
- `STORM-Control`：当前探索项

当前不应进入主收益叙事的内容包括：

- `global credit (p0/p0b/p0c)`
- NoC-only adaptive routing 微调
- 仅靠局部 route selection 的小幅策略变体

原因不变：

- 当前没有稳定正收益；
- 文档已显示这些路径更适合放 future work 或附录。

---

## 6. 统一系统图应该怎么理解

### 6.1 正确的数据流

从系统图角度，当前最合理的主线数据流应是：

1. neuron 发放 `pre spike`
2. `STORM` 在发送侧进行聚合与编码
3. `MulticastRouter` 在 NoC 中完成共享路径传播与按阶段复制
4. endpoint / 本地 ring 完成尽量多的局部投递
5. 接收侧通过 `Rx fastpath` 直接把触达导入 `GAS` gather 路径
6. `GAS` 组织待处理 synapse edges 的 apply 执行
7. `GCSS-GLIDE` 为 `GAS` 提供 DRAM-friendly 的 synapse index/storage 路径
8. `GAS` 完成受控累加与 retire

### 6.2 统一系统问题

这样一来，整套系统解决的就不再是几个局部问题，而是一个统一命题：

- **如何在 DRAM-based SNN 芯片中跨 NoC 与 memory path 同时抑制数据移动放大。**

这其中：

- `STORM + MulticastRouter` 抑制 network-side amplification
- `GAS + GCSS-GLIDE` 抑制 memory-side amplification

这就是完整系统最强的统一叙事。

---

## 7. 当前哪些内容属于主线，哪些不属于

### 7.1 当前主线

当前主线应固定为：

1. **顶层框架**：`DRAM-based SNN chip`
2. **Memory backbone**：`GAS`
3. **Memory optimization**：`GCSS-GLIDE`
4. **NoC architecture + optimization**：`STORM + MulticastRouter`

### 7.2 当前不进入主收益叙事的内容

以下内容当前不应再与主线并列：

1. `STORM-Control / global credit`
2. NoC-only adaptive routing 微调
3. 历史 memory codec 迭代版本
4. `STORM-PIF`、`STORM-NIP` 等联合探索机制

这些路径仍然有价值，但价值在于：

- 作为探索证据；
- 作为 future work；
- 或作为“我们尝试过但不进入主线”的边界说明。

而不是当前主系统的一部分。

---

## 8. 从 arch 论文角度，这样组织后的创新性在哪里

### 8.1 创新点不再是“几个优化”，而是一个芯片架构

按新的层级组织后，创新性会变得更清晰：

1. **`DRAM-based SNN chip`**
- 解决的是大规模 SNN 必须面向真实 DRAM 后端这一根本问题。

2. **`GAS` 作为 memory-access backbone**
- 给出了面向 DRAM-backed synapse access 的稳定执行与访存主干。

3. **`GCSS-GLIDE` 作为 GAS memory optimization**
- 让 metadata 压缩与 locality 保持兼容，而不是顾此失彼。

4. **`STORM + MulticastRouter` 作为 NoC architecture innovation**
- 把 spike dissemination 从 sender-side replication 改造成 network-native multicast dissemination。

### 8.2 为什么这比之前的组织方式更强

因为它明确了：

- 什么是骨架；
- 什么是骨架上的优化；
- 什么是芯片级子系统创新；
- 什么是暂时不进入主贡献的探索项。

这会让 reviewer 更容易接受这是一条 **系统架构主线**，而不是“很多优化项凑成的拼盘”。

### 8.3 当前最合适的总定位

当前最合适的总定位是：

- **一篇围绕 DRAM-based SNN chip 的体系结构论文**；
- 其中：
  - `GAS` 是 memory system backbone；
  - `GCSS-GLIDE` 是 memory optimization；
  - `STORM + MulticastRouter` 是 NoC innovation。

这比把 `GCSS-GLIDE`、`GAS`、`STORM` 平行摆放要合理得多。

---

## 9. 当前应遵守的文档与实验纪律

为了保证后续主线不再发散，建议严格遵守以下原则：

1. **系统层级固定**
- `DRAM-based SNN chip`
- `GAS` 作为 memory backbone
- `GCSS-GLIDE` 作为 memory optimization
- `STORM + MulticastRouter` 作为 NoC 主线

2. **NoC 主线 backend 固定**
- 后续主图、主表、headline 结果尽量在 `MulticastRouter` 后端统一闭环；
- 不再把它仅仅当成旁证平台。

3. **memory 主线不再打散 locality**
- 继续坚持：只压 index codec；
- 不再扰动 `profile_greedy` values locality。

4. **探索项不再与主线并列**
- `global credit`
- NoC-only routing 微调
- `PIF/NIP`
- 历史 codec 版本

5. **主线始终维持语义与验证口径**
- 不破坏 `GAS` 语义；
- 不破坏严格验证结果。

---

## 10. 当前最终结论

截至当前版本，完整系统主线应统一收口为：

- **顶层框架**：`DRAM-based SNN chip`
- **内存主干**：`GAS`
- **内存优化**：`GCSS-GLIDE`
- **NoC 主线**：`STORM + MulticastRouter`

其中：

- `GAS` 负责把 synapse gather/apply 组织成稳定的 memory-access backbone；
- `GCSS-GLIDE` 负责在不破坏 locality 的前提下压缩 synapse metadata，守住 DRAM-based memory hierarchy 的成立条件；
- `STORM + MulticastRouter` 负责把 spike dissemination 变成原生 multicast-aware 的 NoC 数据面，降低复制与字节放大。

因此，当前最合理的论文理解方式是：

- 这不是若干优化项的并列组合；
- 而是一套 **以 DRAM-based SNN chip 为顶层框架、以 GAS 为内存主干、再由 GCSS-GLIDE 与 STORM 分别强化 memory 与 NoC 子系统的完整架构主线**。

从体系结构论文角度看，这种组织方式比此前更合理，因为它：

- 强化了 `GAS` 的 backbone 地位；
- 把 `GCSS-GLIDE` 放回了正确的 memory 子层级；
- 把 `MulticastRouter` 明确提升为 `STORM` 主线硬件的一部分；
- 让整篇工作更像一个完整的芯片体系结构，而不是若干优化的集合。

---

## 11. 建议引用与关联文档

NoC 主线与机制细节：
- `exp_opt/2026-02-26-noc-multicast-and-global-credit.md`

Memory 主线与当前冻结口径：
- `exp_opt/2026-02-27-gas-memory-optimizations.md`

NoC×memory 联合探索归档：
- `exp_opt/2026-02-28-noc-memory-joint-optimization-storm-pif.md`

技术进展总表：
- `TECH_PROGRESS.md`
