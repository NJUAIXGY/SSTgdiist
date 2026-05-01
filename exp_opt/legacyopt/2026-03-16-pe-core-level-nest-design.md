# PE 内 Core-Level 新主线设计草案

> Note: 本文档是并行命名草案；当前推荐的 canonical 版本为 `docs/plans/2026-03-16-pe-core-pulse-design.md`。

Date: 2026-03-16
Status: Design Draft
Owner: Codex

## 0. 一句话结论

当前 `SnnDL` 的系统主线已经在 `PE 外部` 建立起了比较强的论文骨架：

- 顶层：`DRAM-based SNN chip`
- Memory backbone：`GAS`
- Memory optimization：`GCSS-GLIDE`
- NoC 主线：`STORM + MulticastRouter`

但 `PE 内部` 仍主要是“多个独立 core + 少量共享 transport/arbiter”的装配形态，还没有形成真正的 `core-cluster execution island`。  
这份草案建议把 `PE` 从“装配容器”升级为一个新的共享执行与共享存储微结构：

- **`NEST` = Neural Execution and Shared-memory Tile**
- 论文口径：
  - **`NEST: A Retire-Safe Core-Cluster Execution Island for DRAM-Based SNN Chips`**

`NEST` 的目标不是粗暴地把更多东西做共享，而是：

- 保留 `GAS` 的严格语义与确定性 retire；
- 把 `STORM` 暴露出来的 receiver-local spike locality 转换成 `PE` 内真实的 shared service opportunity；
- 把 `GCSS-GLIDE` 的 line/locality 优势从 per-core 视角提升到 `PE-shared physical store` 视角；
- 避免历史上“最大化 shared line service”与 `strict retire` 正面冲突的失败路径。

---

## 1. 为什么需要新的 PE 内主线

当前代码中最关键的现实约束是：

- `MultiCorePE` 主要负责装配、barrier、NoC/ring tick、统计聚合，不负责 `PE-shared issue/retire/dataflow`；
- `SnnPESubComponent` 为每个 core 各自构造 `WeightMemorySubsystem`；
- `SnnWorkload` 在每个 core 内独立处理 token、edge、issue 和 retire；
- `PeDmaScheduler` 是少数成熟的 `PE-shared runtime arbiter`，但它只共享带宽，不共享执行语义；
- `LocalStorageHierarchyController` 目前还是 Phase A 的 registry/snapshot 骨架，不是实际运行时本地存储平面。

这意味着：我们今天已经有很强的 `PE 外 memory/NoC` 主线，但缺少一个能把以下三者真正接起来的 `PE 内 core-level` 中介层：

1. `STORM` 暴露的 destination-local token/spike locality
2. `GCSS-GLIDE` 暴露的 line/locality-optimized weight layout
3. `GAS` 需要坚持的 exactness / deterministic retire

如果没有这个中介层，`PE` 内部就永远只是：

- 外面网络很聪明
- 外面内存布局很聪明
- 但进入 `PE` 后又被摊平成“每个 core 私有展开、私有 issue、私有 retire”

这会把真正的 cross-core reuse 和 shared service 空间白白浪费掉。

---

## 2. 与已有和已有外部工作的边界

### 2.1 与仓库现有方向的边界

`NEST` 不是以下路线的简单重命名：

- 不是只改 `GCSS` layout、完全不碰 runtime 的 offline-only 路线
- 不是 `ATLAS-LSS` 那种“尽量做大 shared line”的最大共享路线
- 不是“真实 per-post retire 全面替代当前 retire contract”的高风险语义重写
- 也不是把 `state/weight/activation/accumulator` 继续糊成几个粗粒度 SRAM stall 参数

`NEST` 追求的是一个更稳的中间点：

- **共享发生在 service plane，而不是 commit plane**
- **共享发生在受控 cohort 中，而不是不加约束地全窗口扩散**
- **物理存储可共享，但逻辑视图仍按 core 保持清晰**

### 2.2 与代表性 SNN 芯片的差异

现有代表性工作已经证明了三个方向的重要性，但都没有真正给出我们需要的 `PE 内 shared execution plane`：

- **Tianjic** 强调可统一多种神经范式的 `FCore` 核心抽象与本地路由/处理结构，但核心仍然是 per-core 视角，没有针对 DRAM-backed synapse access 的 `PE-shared` 接收端服务平面。  
  Source: Nature 2019, https://www.nature.com/articles/s41586-019-1424-8
- **SpiNNaker2** 证明了 many-core + event routing + QPE 局部互联 + 外部 LPDDR4 的可扩展性，但 `QPE` 主要还是把处理器和 DMA 放在一个 cluster 内，并没有把 receiver-side token aggregation、descriptor lifting、exact-retire-aware shared service 做成一等微结构。  
  Source: Frontiers in Neuroscience 2020, https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2020.00682/full
- **Loihi 2** 强调可编程神经元动态、稀疏事件驱动、以及更强的 on-chip 学习/配置灵活性，但它仍然以 per-core local memory / routing domain 为主，不是面向 DRAM-backed shared-service 的 core-cluster 数据平面。  
  Source: Intel technical brief / arXiv 2024, https://www.intel.com/content/www/us/en/research/neuromorphic-computing-loihi-2-technology-brief.html and https://arxiv.org/abs/2410.10458
- **Darwin3** 把可编程性、神经动力学表达和片上学习推进得很深，但核心抽象仍是 many-core neuromorphic processors，而不是在 `PE` 内建立共享执行岛。  
  Source: Nature Reviews Electrical Engineering 2024, https://academic.oup.com/nsr/article/11/5/nwad257/7240156
- **ActiveN** 是和我们最接近的 recent prior：它把 many-core、active message、off-chip synapse storage、sparse-data-aware forwarding 放到同一体系结构里，非常强。但它的基本单位仍然是 processor endpoint；它没有把 `STORM` 这类 receiver-local multicast locality 和 `GAS exact retire` 之间的矛盾统一为一个 `PE-shared service fabric`。  
  Source: MICRO 2024, DOI 10.1109/MICRO61859.2024.00085

因此，`NEST` 的 novelty 不应写成“我们也做了个 many-core SNN chip”，而应写成：

- **我们首次把 DRAM-backed SNN 芯片中的 `PE` 提升为一个 retire-safe core-cluster execution island，把 NoC-locality、memory-locality、deterministic retire 三者统一到同一微结构中。**

---

## 3. 设计空间与推荐路径

### 3.1 方案 A：继续维持 per-core 私有路径，只增强 layout

优点：

- 最稳
- 与现有代码兼容最好
- 工程风险最低

缺点：

- 无法把同一 `PE` 内多个 core 的 token/service opportunity 收敛起来
- 只能继续依赖 offline layout 挤最后一点 locality
- 很难形成新的顶会级 microarchitecture 贡献

结论：

- 可作为 baseline，不适合作为新主线

### 3.2 方案 B：`NEST`，建立 retire-safe 的 PE-shared core-cluster 执行岛

优点：

- 真正命中当前系统最空白的层级
- 与 `GAS + GCSS-GLIDE + STORM` 三条主线自然对齐
- 既有体系结构新意，也有清晰可解释的 correctness 边界

缺点：

- 需要新增 `PE-shared` 控制面与数据面
- 需要同步扩展 offline layout/compiler 表示
- 观测与验证体系必须一起补

结论：

- **推荐作为新主线**

### 3.3 方案 C：直接把共享域抬到 `2x2 block` 或更大

优点：

- 理论共享最大
- 叙事上非常激进

缺点：

- 极易重新踩中历史上 shared-line 与 strict retire 冲突的雷
- 设计和验证复杂度都会显著上升
- 难以作为第一版论文主线稳定收口

结论：

- 适合作为 `NEST` 之后的扩展，不适合作为当前主线第一跳

---

## 4. `NEST` 的核心思想

`NEST` 有三个必须同时成立的原则：

1. **ingress-shared**
   - 进入 `PE` 的 token/spike 先进入 `PE-shared` 接收与聚合层，而不是直接落到某个 core 的私有 workload 队列

2. **service-shared**
   - memory service 的最小组织单位不再是“每 core 各自把 token 展开为 edge 再 issue”
   - 而是在 `PE` 内先做 descriptor lifting，再形成受控的 shared service cohort

3. **commit-exact**
   - 共享只发生在接收、描述符形成、物理存储访问与 ready 分发阶段
   - 最终对 `post_local` 的状态更新与 retire exactness 仍保持确定性合同

一句话概括：

- **`NEST` = shared ingress + shared service + exact commit**

这也是它比历史最大共享路线更稳的根本原因。

---

## 5. 微结构总览

### 5.1 顶层结构

在每个 `PE` 内，`NEST` 引入以下共享单元：

- `AH` = `Activation Harbor`
  - PE 级 token/spike 接收、去重、冻结快照
- `DLE` = `Descriptor Lift Engine`
  - 把 token 提升为 line/segment/service descriptors
- `SCQ` = `Service Cohort Queue`
  - 构造并调度 retire-safe shared service cohort
- `RSM` = `Retire Safety Matrix`
  - 跟踪 cohort 的 consumer bitmap、ready 状态、retire span 与 head pressure
- `SWF` = `Shared Weight Fabric`
  - PE-shared physical `weight_idx_store` / `weight_value_store`
- `LSC` = `Local Storage Controller`
  - 从 Phase A registry 演化为实际 bank/port/residency/refill/arbitration 控制器
- `DMA-FE`
  - 复用现有 `PeDmaScheduler` 作为共享 refill backend

每个 core 继续保留：

- `state_store`
- `activation_core_queue`
- `accumulator_store`
- `register_file`
- `compute core`

### 5.2 设计原则

几个对象必须坚持 per-core：

- `state_store`
- `register_file`
- 默认 `accumulator_store`

几个对象应优先升级为 `logical per-core / physical per-PE shared`：

- `weight_idx_store`
- `weight_value_store`

几个对象天然应该是两级结构：

- `activation_ingress_store`：per-PE
- `activation_core_queue`：per-core

这样做的原因很简单：

- 神经元状态和最终提交点不宜轻易共享
- activation ingress 和 weight service 天生有 cross-core 复用机会

---

## 6. 关键机制一：Activation Harbor

### 6.1 职责

`Activation Harbor` 是 `PE` 的真实接收前门：

- 所有来自 `STORM + MulticastRouter` 或其他 ingress 的 token/spike，先进入 `activation_ingress_store`
- 在 `PE` 级做 `pre_global` 粒度的去重、合并、统计和冻结
- 不立即展开成 per-core edge

### 6.2 为什么它必须存在

当前 receiver path 的最大问题是：

- token 一到就快速落入 per-core workload 私有路径
- locality 在“刚进 PE”时最强，结果却在这一层就被摊平

`Activation Harbor` 的作用是把这种 locality 保留下来，让后面的 service plane 仍然看得到：

- 哪些 token 是本窗口第一次触达该 `PE`
- 哪些 token 会被同一 `PE` 内多个 core 同时消费
- 哪些 token 的后续服务可以共享，哪些必须私有

### 6.3 与现有系统的接口

- `NocSubsystem` 的本地投递目标从“直接转给 core 私有 workload”改成“先投给 `AH`”
- `SnnWorkload::deliverSpike()` 不再直接成为第一落点，而是变成 `AH -> activation_core_queue` 之后的消费接口
- `MultiCorePE` 在 phase 切换时负责：
  - `AH` freeze/unfreeze
  - window snapshot
  - backpressure 统计

---

## 7. 关键机制二：Descriptor Lift Engine

### 7.1 基本思想

`DLE` 不是把 token 直接展开为 `(pre, post)` edge 列表，而是先抬升到更接近真实 service domain 的描述符层：

- `token -> segment descriptor -> line descriptor -> cohort`

描述符至少应包含：

- `pre_global`
- `dst_core_bitmap`
- `line_id / line_group`
- `value_bank`
- `format_class`
- `window_seq`
- `retire_seq_min/max`
- `consumer_count`
- `service_bytes`

### 7.2 为什么 descriptor lift 比 edge-first 更合理

因为当前 `PE` 内真正贵的不是“生成 edge 列表”本身，而是：

- 重复 issue 相同或高度重叠的 line/service
- 多个 core 分别命中同一物理服务机会却互相看不见

`DLE` 的贡献不是近似，而是更晚、更接近真实 service domain 地展开。

### 7.3 与 offline layout 的协同

为了让 `DLE` 真正成立，`GCSS-GLIDE` 需要升级出一个 `NEST-aware` 视图：

- 逻辑上仍保持 per-core descriptor
- 物理上允许同一 `PE` 内多个 core 的相关 weight segment 打包进共享 line domain
- 每个共享 line 都要显式导出：
  - `dst_core_bitmap`
  - `bank_color`
  - `offset list`
  - `retire span bound`

这里的关键不是“强行共享更多 value”，而是：

- **只把对 runtime 真正安全的 cross-core overlap 编译成 shared physical service opportunity**

---

## 8. 关键机制三：Retire-Aligned Service Cohorts

### 8.1 这是 `NEST` 的真正论文核心

历史上最危险的点不是“共享会不会带来复杂度”，而是：

- shared service 很容易和 strict retire 冲突
- 一旦 cohort 覆盖过宽，older head 会被 younger-but-local 的 service 一直压住

因此 `NEST` 不能走“最大化共享”的路线，而必须引入：

- **`Retire-Aligned Service Cohort`（RASC）**

### 8.2 cohort 形成规则

只有同时满足以下条件的 descriptor，才允许被合并进同一个 cohort：

- 位于同一 `PE`
- 命中同一 `shared line` 或同一 `line group`
- `format_class` 一致
- `retire_seq_span <= S_max`
- 不跨越 `row-safe / segment-safe` 护栏
- 当前 head-pressure 允许

也就是说：

- shared service 不再是“看起来能共享就共享”
- 而是“只有对 exact retire 友好的共享才允许发生”

### 8.3 调度策略

`SCQ + RSM` 联合完成以下调度：

- `head-aware issue`
  - 如果某 cohort 内含 older head 相关 consumer，则提升 issue 优先级
- `span-bounded join`
  - 不允许把 retire 距离过大的 consumer 压进同一个共享域
- `late split`
  - 若运行中检测到 head pressure 升高，可把 cohort 拆回更小粒度
- `bank-aware arbitration`
  - 在共享有效的前提下，再服从 `SWF` bank/port 约束

### 8.4 exactness contract

`NEST` 的关键安全边界是：

- **共享只改变 fetch/service 组织，不改变最终 commit 语义**

具体来说：

- 一个 shared cohort 的 DRAM 请求返回后，会在 `RSM` 中把对应 consumer 标成 `ready`
- 这些 ready consumer 仍然按既有 deterministic retire contract 逐步提交
- 如果某个 consumer 尚不能提交，它只是在 `RSM` 中保持 ready，不会破坏 exactness

这让 `NEST` 的叙事非常干净：

- **issue can be shared, commit stays exact**

---

## 9. 关键机制四：Shared Weight Fabric

### 9.1 为什么 weight 应该物理共享

`state` 不应轻易共享，但 `weight_idx/value` 是最适合共享物理 bank fabric 的对象：

- 真正的 cross-core overlap 主要发生在 synapse service
- 共享的是物理 line/bank/refill，而不是 neuron state ownership

因此推荐把：

- `weight_idx_store`
- `weight_value_store`

升级为：

- **逻辑 per-core**
- **物理 per-PE shared bank fabric**

### 9.2 `SWF` 的组成

`SWF` 至少应包含：

- shared banked SRAM arrays
- residency directory
- refill state
- cohort replay buffer
- local response multicast crossbar

其中最关键的是：

- 一个物理 line refill 后，可被多个 consumer 直接复用
- 不再让每个 core 都把这次机会重新解释成一次私有 read

### 9.3 与现有 `PeDmaScheduler` 的关系

`PeDmaScheduler` 应继续保留，并升级为 `NEST` 的标准 refill backend：

- `SCQ` 负责决定要发哪个 cohort
- `PeDmaScheduler` 负责在 `PE` 范围内仲裁 off-chip read budget
- `SWF` 负责把返回数据留在本地共享物理域，并 fanout 给多个 core consumer

这意味着现有 per-PE DMA 主线不是被推翻，而是被放进了一个更完整的 `PE-shared service fabric` 中。

---

## 10. 本地存储层级的正式收口

`NEST` 应把现有 `LocalStorageHierarchyController` 从“对象注册骨架”推进为真正的本地存储控制平面。

推荐对象拓扑如下：

| 对象 | scope | 角色 |
| --- | --- | --- |
| `activation_ingress_store` | per_pe | token/spike 接收与冻结 |
| `activation_core_queue` | per_core | 每 core 消费队列 |
| `state_store` | per_core | neuron state 真值持有者 |
| `weight_idx_store` | logical per_core / physical per_pe | shared metadata store |
| `weight_value_store` | logical per_core / physical per_pe | shared value store |
| `accumulator_store` | per_core | 默认 commit 前 partial sum |
| `register_file` | per_core | 瞬态 operand |
| `cohort_table` | per_pe | shared service descriptors |
| `replay_buffer` | per_pe | returning line 暂存与 ready fanout |

这里最重要的 architectural message 是：

- `PE` 内不再只有“多个 core 私有存储”
- 也不再只是“有个可选 shared DMA”
- 而是正式拥有一层 **core-cluster local storage hierarchy**

---

## 11. 与现有代码主线的建议插入点

如果后续要落实现，最自然的插入点如下：

- `MultiCorePE`
  - 构造 `NEST controller`
  - 驱动 phase-aware tick
  - 聚合 `PE-shared` 统计
- `NocSubsystem`
  - 本地 packet 投递先进入 `Activation Harbor`
- `SnnPESubComponent`
  - 不再每 core 独占完整 weight service plane
  - 改为持有 per-core client 视图
- `SnnWorkload`
  - 从 `deliverSpike -> edge record` 改成 `deliverSpike -> harbor attach / queue consume`
- `WeightMemorySubsystem`
  - 逐步收缩为：
    - off-chip refill backend
    - exact retire engine
    - per-core logical client adapter
- `LocalStorageHierarchyController`
  - 从 registry 升级为 bank/port/residency/refill/arbitration 真控制器

最关键的边界是：

- 不要一上来就把 `compute core` 和 `state store` 语义彻底打碎
- 先把 shared 发生的位置严格限制在 ingress/service/weight fabric

---

## 12. 论文级 novelty claim

如果按 `ISCA/ASPLOS` 口径来写，浮浮酱建议把贡献收敛成三条：

### Contribution 1

- **A PE-internal core-cluster execution island for DRAM-based SNNs**
- 首次把 `PE` 提升为显式的 shared ingress + shared service + exact commit 微结构，而不是多个独立 core 的装配容器

### Contribution 2

- **Retire-Aligned Service Cohorts**
- 不是简单做 shared line service，而是把共享的形成条件与 exact retire contract 绑定，避免 shared locality 和 deterministic correctness 互相打架

### Contribution 3

- **A dual-scope local storage hierarchy**
- 对 `state/activation/weight/accumulator` 明确区分 per-core 与 per-PE scope，实现 logical-private / physical-shared 的权重存储与 refill/fanout 统一

这三条一起写，论文就不再是“又一个 SNN optimizer”，而是：

- **从 PE 外主线走向 PE 内微结构闭环**

---

## 13. 评估故事应该怎么搭

### 13.1 Baseline

- 当前主线：`GAS + GCSS-GLIDE + STORM + MulticastRouter`

### 13.2 关键 ablation

- `A0`: current mainline
- `A1`: `Activation Harbor` only
- `A2`: `Activation Harbor + DLE`
- `A3`: `+ shared weight fabric`
- `A4`: `+ retire-aligned cohorts`（完整 `NEST`）
- `A5`: unsafe max-sharing variant（证明“更多共享”不等于更好）

### 13.3 必须新增的统计

- `nest.harbor_unique_tokens_total`
- `nest.harbor_token_merge_elided_total`
- `nest.cohort_issued_total`
- `nest.cohort_fanout_avg`
- `nest.cohort_seq_span_p95/p99`
- `nest.shared_line_req_elided_total`
- `nest.shared_weight_bank_conflict_cycles_total`
- `nest.retire_ready_blocked_cycles_total`
- `nest.head_rescue_issues_total`
- `nest.activation_ingress_backpressure_cycles_total`

### 13.4 论文主指标

- `sim_time_actual_ns`
- `memctrl.req_total`
- `memctrl.bytes_est_total`
- `gas.payload_bytes_per_memctrl_req_avg`
- `ramulator.row_hit_rate`
- `ramulator.row_conflict_rate`
- `NoC bytes / packets / multicast efficiency`

### 13.5 论文要证明的不是“共享更多”

真正要证明的是：

- 在不破坏 exact retire 的前提下，`NEST` 把 receiver-local token locality 转化成了真实的 memory-service 压缩与 end-to-end 加速

---

## 14. 风险与护栏

`NEST` 有三个必须提前写死的护栏：

### 14.1 不改 public exactness contract

- 不把 `per-post retire rewrite` 作为主线前提
- 共享发生在 service plane，不发生在最终 commit plane

### 14.2 不做无边界共享

- 所有共享都必须受 `retire_seq_span`、`head pressure`、`row-safe` 和 `bank-safe` 约束

### 14.3 不一上来就共享 state

- `state_store` 继续 per-core
- `accumulator_store` 先保持 per-core，必要时再探索 `per_pe shared accumulator fabric`

这三个护栏看起来保守，但恰恰是把它从“高风险想法”变成“顶会级 solid design”的关键。

---

## 15. 最小落地顺序

如果后续主人认可这条主线，浮浮酱建议实现顺序严格按下面走：

1. `Phase N0`
   - `Activation Harbor` + ingress statistics
   - 只改 receiver ownership，不改 service/retire
2. `Phase N1`
   - `Descriptor Lift Engine`
   - 只做 observe-only shared opportunity profiling
3. `Phase N2`
   - `Shared Weight Fabric`
   - 先建立 logical-private / physical-shared local weight store
4. `Phase N3`
   - `Retire-Aligned Service Cohorts`
   - 正式开启 shared issue
5. `Phase N4`
   - 根据证据决定是否需要 `head rescue` / `late split` / `shared accumulator` 扩展

这样做的好处是：

- 每一步都能独立 A/B
- 每一步都能保留兼容关闭
- 每一步都能解释“为什么论文收益来自这个机制”

---

## 16. 最终建议

浮浮酱建议正式把 `PE 内 core-level` 新主线定义为：

- **`NEST`: a retire-safe PE-shared core-cluster execution island**

它不是对现有主线的推翻，而是对现有主线的最后一块补齐：

- `STORM` 负责把 locality 带到 `PE`
- `NEST` 负责在 `PE` 内保住并消费这份 locality
- `GCSS-GLIDE` 负责让这份 shared service 真能落到物理 line/bank/refill 上
- `GAS` 继续提供 exactness 与 execution backbone

如果论文要冲 `ISCA/ASPLOS`，这条线最大的价值就在于：

- 它把“PE 外的大系统优化”推进成了“PE 内的可解释微结构创新”
- 而且这份创新既不靠近似，也不靠语义偷换，而是靠 **shared ingress + shared service + exact commit** 的新边界定义成立
