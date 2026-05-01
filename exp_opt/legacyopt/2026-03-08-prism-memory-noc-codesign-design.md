# PRISM：面向 full-system baseline 的 Memory × NoC 主线协同机制设计

> 日期：2026-03-08  
> 状态：设计文档（不落代码）  
> 基线：`full_system_baseline = STORM(multicast_mesh) + GCSS-GLIDE`

## 0. 一句话结论

如果我们后续只允许保留 **一个** 真正值得投入实现、又能自然长在当前主线上的 `memory × NoC` 协同机制，浮浮酱推荐：

- **`PRISM`**：**`P`resynaptic `R`outed `I`ntegrated `S`egment `M`emory**

它的核心不是再做一个局部调度器，而是把当前 `STORM` 已经压缩好的 **`pre/token` 语义**，完整保留到 `GAS + GCSS-GLIDE` 的 apply/memory 服务路径，把现有系统中的一个关键断层补上：

- 现在 `STORM` 在 NoC 中传播的是 `SpikeKey(pre_global + core mask)`；
- 但接收侧大多仍把它重新膨胀为很多本地 `SpikeEvent / edge`；
- 而 `GCSS-GLIDE` 的 values 实际又已经按 **pre-major / pre-rank** 的 segment 组织好了。

所以当前系统的真实问题不是“网络不够 multicast”或“内存不够 line-friendly”，而是：

- **NoC 用的是 `pre token` 抽象，memory 最终却又退化回 `per-edge` 抽象。**

`PRISM` 的目标就是让：

- `SpikeKey` 在接收 PE 不再被过早膨胀成海量局部 spike/edge，
- 而是直接变成 **`pre-segment token`**，
- 再由 `GAS` 在 apply 时按 segment 进行 line-granular 权重服务。

这条路线相比 `naive_tass/TASS-LF` 更保守、比 `global credit/banked admission` 更根本、比 `NIP/PIF` 更确定性，也更适合作为接下来唯一主线的协同创新点。

---

## 1. 为什么 full_system_baseline 是唯一正确出发点

当前主线已经被 `mainexp` 的系统级 A/B 钉死：

- `memory_baseline = Merlin + GCSS-GLIDE`
- `noc_baseline = STORM + GCSS-idx2`
- `full_system_baseline = STORM + GCSS-GLIDE`

关键实验结论：

1. `memory_baseline` 相对 `full_system_baseline`
- `sim_time_actual_ns` 慢 `4.22x`
- 但 `memctrl.req_total` 几乎一样（`150110` vs `150907`）
- 说明差距主要不在 memory side，而在 NoC/transport side

2. `noc_baseline` 相对 `full_system_baseline`
- `sim_time_actual_ns` 慢 `5.37x`
- `memctrl.req_total` 高 `11.16x`
- `gas.memctrl_payload_utilization` 只有 `0.0896x`
- 说明 `STORM` 单独存在时，older memory path 会把 DRAM line 利用率彻底拉坏

因此，当前系统真实成立的形态是：

- **`STORM`** 把 NoC 数据移动放大压下去
- **`GCSS-GLIDE`** 把 DRAM 请求放大压下去
- **`full_system_baseline`** 是两者同时成立后的唯一主基线

所以，下一步绝不能再回到“只在 memory 侧单点 tweak”或“只在 NoC 侧单点 tweak”。

新的体系结构创新必须满足：

- 以 `full_system_baseline` 为唯一比较对象；
- 同时读懂 `STORM` 的 packet 语义和 `GCSS-GLIDE` 的 storage 语义；
- 在两者的接口处动刀，而不是只改单侧局部调度。

---

## 2. 当前 full-system 主线中的关键断层

### 2.1 STORM 已经把 packet 变成了 pre-centric token

当前 `STORM` 主线中：

- 发送侧不再主要发送单个 destination 的 `Spike`；
- 而是使用 `SpikeKey` / blocked multicast，把一个 `pre_global` 连同目标 block/core mask 送到接收侧；
- 这已经是一个 **pre-centric** 的传播语义。

也就是说，NoC 已经完成了一次非常有价值的“抽象提升”：

- 从 `post-edge` 传播，变成了 `pre token` 传播。

### 2.2 GCSS-GLIDE 已经把 weights 变成了 pre-major segment

当前 `GCSS-GLIDE` 主线中：

- values 按 `pre_global` 的局部 posts 顺序组织；
- `pre_rank` 与 `pre_base/len` 能把一个 pre 对应的 values 压成 1 条或少数几条 cacheline；
- summary 已表明当前主线：
  - `payload_bytes_per_memctrl_req_avg ≈ 20.25B`
  - `memctrl_payload_utilization ≈ 0.316`
  - `index_to_values_ratio ≈ 0.0976`

这说明 memory side 也已经在往 **pre-major segment** 形态收敛。

### 2.3 真正的浪费发生在接收侧接口

当前接收侧的核心问题是：

- 虽然收到了 `SpikeKey(pre_global)`；
- 但大多数包仍走 fallback 路径；
- `full_system_baseline` 的 summary 明确显示：
  - `snn_rx.fastpath_packets_total = 0`
  - `snn_rx.fallback_packets_total = 8,843,654`

也就是说，当前 `STORM` 送来的 `pre token`，在进入 `GAS` 前被重新展开成了很多局部 spike / edge，再由 weight subsystem 再次恢复成 line-friendly issue。

于是形成一个不必要的“先压缩、再膨胀、再重整形”的链路：

1. NoC：`pre token`
2. RX：膨胀为 `local spikes / edges`
3. Apply：再重组为 line-friendly memory issue

`PRISM` 的核心价值，就是把中间这次“膨胀”取消掉。

---

## 3. 我们考虑过的 3 条协同路线

### 3.1 方案 A：`PRISM`（推荐）

**核心想法**：

- 保留 `SpikeKey` 的 `pre` 语义到接收 PE 内部；
- 不再在 gather 阶段展开成海量 `SpikeEvent / edge`；
- 改为形成 **`pre-segment token`**；
- apply 阶段直接对 segment 发起 line-granular 权重服务。

**优点**：

- 与当前 `STORM + GCSS-GLIDE` 天然匹配
- 不需要跨 PE 共享 DRAM line
- 不需要 response multicast
- 语义边界清晰，可做严格验证
- 很容易解释为“统一 NoC token 抽象与 memory segment 抽象”

**风险**：

- 需要在 `SnnWorkload` 与 `WeightMemorySubsystem` 之间引入新的 token/service 抽象；
- 需要认真处理 deterministic accumulation / strict 模式。

### 3.2 方案 B：NoC-aware Segment Admission（备选）

**核心想法**：

- 不改变 packet 或 apply 基本抽象；
- 只是使用 `STORM` 的拥塞/背压信息，去调节 `GCSS-GLIDE` 的 segment 发射顺序、credit、窗口 admission。

**优点**：

- 改动较小；
- 可以复用现有 credit/banked admission 思路。

**缺点**：

- 这仍然是“控制面整形”，不是“表示层统一”；
- 历史上 `banked admission / global credit / Tail-Guard` 都没有形成稳定正收益；
- 论文创新度更像 control tweak，不像新的系统 abstraction。

### 3.3 方案 C：TASS-LF v2 / block-shared service（高风险）

**核心想法**：

- 继续沿 `naive_tass/TASS-LF` 的 block 共享 memory service 思路，直接把 `2x2 block` 作为 DRAM 服务域。

**优点**：

- 最激进、最“像一个大点子”。

**缺点**：

- 历史已经踩雷；
- 需要 block 级 response multicast / cross-core join / 更复杂的 drain 与 tail 处理；
- 风险很高，极易重演“局部 traffic 下降但端到端更差”的问题。

### 3.4 推荐结论

- **主推荐：方案 A = `PRISM`**
- 方案 B 作为 `PRISM` 的后续增强控制面
- 方案 C 只保留为 future work / 高风险探索，不进入当前唯一主线

---

## 4. PRISM 的核心思想

### 4.1 统一抽象：从 `SpikeKey` 到 `Pre-Segment Token`

`PRISM` 的第一原则是：

- **把 `pre_global` 变成 end-to-end 的一等执行单元。**

具体来说：

- `STORM` 在 NoC 中传播的是 `SpikeKey(pre_global, block/core mask)`；
- 接收侧不再立即把它变成很多 `(pre, post)` 级对象；
- 而是生成一个 **`PreSegmentToken`**：
  - `window_seq`
  - `pre_global`
  - `multiplicity`（默认 1，可扩展）
  - `target_core/local_core_mask`（来自现有 STORM packet）
  - `arrival_order / deterministic tag`

然后 `GAS` 在 apply 阶段把它解释为：

- “对这个 `pre_global`，在本 core 上存在一个局部 post 集合；
- 这个集合在 `GCSS-GLIDE` values 中对应一个连续或近连续的 `segment`。”

于是 apply 的服务粒度不再是：

- `edge`

而变成：

- `pre-segment`

这是 `PRISM` 与几乎所有历史路线的根本不同点：

- 它不是“更聪明地给 edge 排序”，
- 而是直接把执行/访存的基本服务对象换成更接近当前 NoC 与 memory 共识的那个对象。

### 4.2 这不是 naive_tass

`PRISM` 与 `naive_tass/TASS-LF` 的根本差别是：

- `naive_tass/TASS-LF` 试图建立 **block-shared** 的 memory service domain；
- `PRISM` 只建立 **receiver-local, core-local** 的 `pre-segment` service domain。

也就是说：

- `PRISM` 不假设多个 PE 共享同一条 DRAM line；
- 不做 block 级 response multicast；
- 不新增跨 PE 的 values 共享或统一服务节点；
- 只是在“STORM 把 token 送到目标 PE 之后”，在目标 PE 内部保持 token 语义，不再无脑退化成 edge。

因此它更像是：

- **把当前已经存在的两条主线，在接口处对齐。**

而不是引入一个新的重型共享子系统。

---

## 5. PRISM 的分阶段落地设计

为了让方案既能 work，又不至于一步走太重，`PRISM` 建议按三个阶段推进。

### 5.1 P0：`PRISM-RX`（最低风险，先闭环）

**目标**：取消接收侧 `SpikeKey -> local SpikeEvent` 的早期膨胀。

**做法**：

- 在接收侧 `deliverPacket(kind=SpikeKey)` 路径中：
  - 不再调用 fallback 的 `expandPreGlobalToLocalSpikes_()`；
  - 改为为每个目标 core 记录一个 `PreSegmentToken`。
- 这个 token 暂存在新的 `segment_gather_queue` 中；
- gather 阶段只做 token 聚合与去重，不做 edge materialization；
- 到 `BeginApply` 时，再由一个 `materializeSegmentToEdges()` 的桥接函数，按 deterministic 顺序把 token 转成当前 `WeightMemorySubsystem` 可以接受的 edge 流。

**意义**：

- 这一步还不改变 apply 的真正服务抽象；
- 但它已经把 NoC→GAS 的表示层断层补上了一半；
- 能先证明：
  - 本地 spike 膨胀是可被消除的；
  - token 语义可以安全穿过 gather。

**为什么值得做**：

- 当前代码里其实已经有先例：`expandPreGlobalToWindowEdgesFast_()` 已经证明“`pre_global -> 直接形成窗口输入`”在功能上是可行的；
- 但它仍然会逐 post 记录 edge，离真正的 `segment service` 还差一步。

### 5.2 P1：`PRISM-SEG`（主收益版本）

**目标**：把 apply 的 memory 服务粒度从 `edge` 升格为 `pre-segment`。

**做法**：

- 为 `WeightMemorySubsystem` 新增实验性 `segment issue` 路径：
  - 输入：`PreSegmentToken`
  - 查询：
    - `posts_local_for_pre(pre_global)`
    - `pre_base/len`
  - 生成：
    - 对应 values segment 的 line 覆盖区间
- `issue` 不再按 edge 地址发一个个 read；
- 而是直接按 segment 对应的 line/span 发起请求；
- line 回包后，按 `pre_rank -> post_local` 的 deterministic 顺序，将该 line 中的 weight 流式作用到本 core 的 accumulator。

**关键点**：

- 对同一个 `pre_global` 的多个局部 posts，values 已天然按 rank 连续；
- 这比“edge 全展开后再依赖 VLF-line 临时融合”更直接；
- 目标是进一步提升：
  - `payload_bytes_per_memctrl_req_avg`
  - `memctrl_payload_utilization`
  - 并降低 `memctrl.req_total`

### 5.3 P2：`PRISM-COUNT`（NoC 侧协同增强）

**目标**：让 STORM 传播的不只是 `pre token`，还是 **带 multiplicity 的 pre token**。

**做法**：

- 扩展 `SpikeKey` payload 版本，加入小位宽 `count` 字段；
- 在 sender/router 的受控 epoch 内，若同一个 `(pre_global, dst_block)` 重复出现，可合并为一个 count-carrying token；
- 接收侧 `PreSegmentToken.multiplicity += count`；
- apply 时只读一次 segment，但对每个 weight 乘以 `count`。

**注意**：

- 这一步必须严格限定在**同一 GAS gather window** 内；
- 不允许跨 window 合并；
- 不允许改变 step barrier 语义。

P2 是真正把 `STORM` 和 `PRISM` 在 packet 语义上绑死的一步，但建议放在 P0/P1 之后。

---

## 6. 为什么 PRISM 在语义上是安全的

### 6.1 当前 apply 的性质允许 segment 化

当前系统里，apply 阶段最关键的安全条件已经基本满足：

- `orch_.acc_update(post_local, delta)` 本质是在本地 accumulator / membrane update 上做受控累加；
- apply 过程中不会因为某条 edge 的中途到达，立刻触发跨 post 的副作用；
- 当前主线已经通过 `retire`/`seq` 机制保护 deterministic completion。

因此，`PRISM` 的安全边界可以定义为：

- **不改变“一个 window 内总共对每个 `(pre,post)` 施加了多少次相同权重”的事实；**
- **只改变这些等价贡献如何被聚合、何时 materialize，以及 memory request 如何被组织。**

### 6.2 三条严格护栏

1. **只在同一 gather/apply window 内做 token 合并**
- 不跨 window
- 不跨 step

2. **只对完全相同的 `(pre_global, core, window_seq)` 做 multiplicity 合并**
- 不做近似合并
- 不做“相似 pre” 合并

3. **保持 deterministic token order**
- 以 `(arrival_epoch, pre_global, core_id)` 或现有 packet-order tie-break 固定排序；
- strict 模式下可进一步要求“bridge materialization 顺序与现有 fastpath 词典序一致”。

只要这三条守住，`PRISM` 是一个语义保守的执行重表达，而不是近似计算。

---

## 7. 为什么它比历史路线更 solid

### 7.1 比 `banked admission / global credit / per-post retire` 更根本

这些路线都属于：

- 当前执行对象不变；
- 只是在局部调度器上做 reorder / throttle / retire reshaping。

历史数据已经表明：

- 它们能解释部分局部现象；
- 但很难在当前主线口径下形成稳定的端到端增益。

原因是：

- 它们没有解决 **NoC token 与 memory segment 抽象不一致** 这个根本矛盾。

`PRISM` 解决的是表示层错位，而不是后端排队细节。

### 7.2 比 `NIP/PIF` 更确定性

`STORM-NIP/PIF` 的主要问题是：

- 路径上有 speculative prefetch / join / waiter / cache-fill；
- 局部 memory 指标可能变好；
- 但额外控制流与 tail 会把端到端收益吃掉。

`PRISM` 则完全不同：

- 它不是 speculative；
- 没有 wrong-path prefetch；
- 它不是“猜未来会用到什么”；
- 而是“当前 packet 已经明确说明了哪个 pre 会在本 window 里被处理”。

所以它从一开始就更适合作为主线，而不是 exploratory side-path。

### 7.3 比 `naive_tass/TASS-LF` 更稳

`naive_tass/TASS-LF` 的主要风险来自：

- block-shared memory service
- cross-core/跨 PE 的 response 组织
- drain/tail/同步复杂度急剧上升

`PRISM` 则明确避免：

- 不做 shared responder
- 不做 block 级 values 共享
- 不做 response multicast
- 不改变当前 DRAM ownership

这让它更像一次“接口对齐”，而不是一次重构整个执行域。

---

## 8. 论文级创新性：为什么它不像工程小修补

`PRISM` 的创新性不在于“把 fastpath 再写快一点”，而在于：

- **它提出了一个新的端到端执行抽象：`pre-segment token`。**

这个抽象同时统一了：

1. **NoC 传播对象**
- `STORM` 的 `SpikeKey`

2. **GAS gather 对象**
- 不再是膨胀后的 per-post local spike

3. **GCSS-GLIDE 的 memory service 对象**
- pre-major values segment

也就是说，它解决的是一个 reviewer 很容易听懂的问题：

- **为什么当前系统明明在网络里已经按 `pre` 传播，到了内存又回到 `edge`？**

而 `PRISM` 的回答是：

- 不应该回到 `edge`；
- 应该把 `pre` 变成一直保留到 apply 的一等对象；
- 让 packet abstraction 和 memory abstraction 对齐。

这和许多“优化某个局部统计”的工作不同，它更像一个真正的系统接口重定义。

---

## 9. 与公开工作的边界

### 9.1 与 Loihi 2 / Hala Point 的区别

公开的 Intel 路线强调的是：

- 大规模片上集成 memory + communication；
- 核内可配置状态存储、fanout list compression/shared fanout；
- 芯片间 direct message passing。

但它们并不针对：

- **DRAM-backed synapse values + line-granular external memory service**
- 以及 **NoC multicast token 如何一路保留到 DRAM-side apply**

`PRISM` 的问题设定更偏向：

- 当权重真实常驻 DRAM 时，如何不在接收侧重新膨胀 token 语义。

### 9.2 与 LoAS / SpikeX 的区别

这些工作更偏：

- dataflow / mapping / temporal-parallel / sparse execution scheduling
- on-chip memory movement / local reuse

但它们没有直接回答：

- 在一个 **真实 DRAM 后端**、有 **native multicast NoC** 的 SNN 系统里，
- 如何把网络传播抽象和 memory service 抽象统一起来。

### 9.3 与一般 sparse communication/minimal-memory 工作的区别

类似 SpComm3D 这类工作强调：

- 只通信必要数据
- 尽量减小 sparse communication / storage footprint

但 `PRISM` 关注的是更具体的系统缝合问题：

- 不是“少传什么”，
- 而是“已经压缩好的 token 到了目的端，为什么还要膨胀一次再去访问 DRAM”。

这条边界很重要，因为它让 `PRISM` 的 novelty 不是 generic sparse optimization，而是：

- **DRAM-based SNN 中 NoC × memory interface 的专门重定义。**

---

## 10. 预期收益与主观判断

### 10.1 预期最稳的收益来源

`PRISM` 最稳的收益不应先押在“跨 PE 数据共享”，而应押在三件更确定的事上：

1. **消除接收侧局部 spike/edge 膨胀**
- 降低 gather/front-end bookkeeping
- 降低 queue/tail

2. **把 pre-major segment 直接变成 memory issue 单位**
- 比“先 edge 化，再靠 VLF-line 拼回去”更直接
- 更可能提升 `payload_bytes_per_memctrl_req_avg`

3. **为后续 count-carrying aggregation 打基础**
- 一旦相同 pre 的重复 token 在 window 内出现，收益会同时落在 NoC 与 memory 两侧

### 10.2 为什么它有希望比当前 full_system 继续往前走

当前 `full_system_baseline` 已经说明：

- NoC 侧和 memory 侧各自的 isolated 主线都成立了；
- 现在最大的剩余空间已经不在“再优化一侧”，而在“把两侧真正打通”。

而 `PRISM` 恰好是对这件事最直接、最不绕路的回答。

如果它成立，最可能看到的指标方向是：

- `sim_time_actual_ns` 下降
- `memctrl.req_total` 下降
- `payload_bytes_per_memctrl_req_avg` 上升
- `memctrl_payload_utilization` 上升
- 新增的 `receiver_local_spike_expansion_avoided_total` 显著非零
- `segment_tokens_total << materialized_edges_total`

---

## 11. 必须新增的统计项

为了让 `PRISM` 能形成论文证据链，至少要补下面这组统计。

### 11.1 接收/聚合侧

- `prism.segment_tokens_total`
- `prism.segment_tokens_unique_total`
- `prism.segment_token_merged_total`
- `prism.segment_token_multiplicity_total`
- `prism.local_spike_expansion_avoided_total`
- `prism.token_to_edge_materialization_total`
- `prism.token_to_edge_avg`

### 11.2 apply/memory 侧

- `prism.segment_issue_total`
- `prism.segment_lines_requested_total`
- `prism.segment_values_payload_bytes_total`
- `prism.segment_payload_bytes_per_req_avg`
- `prism.segment_avg_len`
- `prism.segment_avg_line_span`
- `prism.segment_direct_acc_updates_total`

### 11.3 NoC 协同侧（P2）

- `prism.ccsk_packets_total`
- `prism.ccsk_merged_count_total`
- `prism.ccsk_avg_count_per_packet`
- `prism.ccsk_bytes_saved_total`

### 11.4 语义/安全侧

- `prism.strict_order_fallback_total`
- `prism.cross_window_merge_blocked_total`
- `prism.nonlinear_guard_bypass_total`

---

## 12. 闭环实验计划

### 12.1 基线与矩阵

统一使用：

- `mainexp` 口径
- `4x4 bcsr10k step1`
- `ramulator2`
- `MESH_VALIDATE_PROFILE=paper`
- 唯一基线：`full_system_baseline`

建议最小矩阵：

1. `A_full_system_baseline`
- `STORM + GCSS-GLIDE`

2. `B_prism_rx`
- 只启用 `PRISM-RX`
- 先验证“去掉早期 spike 膨胀”本身是否稳定正向

3. `C_prism_seg`
- `PRISM-RX + PRISM-SEG`
- 主收益版本

4. `D_prism_count`
- `PRISM-RX + PRISM-SEG + PRISM-COUNT`
- 可选增强，不作为第一阶段必达项

### 12.2 成功标准

P0（能进下一轮）的最低门槛：

- `validation.log`: `fail=0`
- `windows_done=16`, `windows_incomplete=0`
- `route_miss=0`, `local_drop=0`
- `sim_time_actual_ns <= full_system_baseline`
- `prism.local_spike_expansion_avoided_total > 0`

P1（可写论文主图）的门槛：

- `sim_time_actual_ns` 相对 baseline 稳定下降
- `payload_bytes_per_memctrl_req_avg` 明显上升
- `memctrl.req_total` 下降
- `receiver-side expansion avoided` 与 `segment issue` 证据链闭合

---

## 13. 为什么现在就该做 PRISM

如果继续沿历史路线走：

- `banked admission / credit / retire`：更像局部调参
- `naive_tass/TASS-LF`：风险太高，且已经踩过雷
- `NIP/PIF`：局部 memory 指标好，系统时间不稳

而 `PRISM` 的优势是：

- 它直接建立在当前唯一正确主基线之上；
- 它用的是系统已经有的两个 strongest abstraction：
  - `STORM` 的 `SpikeKey`
  - `GCSS-GLIDE` 的 pre-major segment
- 它不是凭空创造新硬件岛，而是把现有主线真正连通起来。

如果要给下一阶段的唯一主攻方向下一个判断，浮浮酱会给：

- **主线推荐：`PRISM`**
- **理由：它是当前最像“体系结构接口创新”而不是“工程修补”的路线，同时也是最不偏离现有主线、最可能真正 work 的路线。**

