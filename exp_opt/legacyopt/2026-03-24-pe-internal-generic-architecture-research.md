# PE 内部通用体系结构深度研究：从收益导向优化转向架构导向设计（2026-03-24）

> 日期：2026-03-24  
> 状态：deep research + architecture framing v1  
> 目标：不再从当前 mainline 的收益 patch 出发，而是回到一个更底层、更普适的问题：**对一个 `SnnDL` 风格多核 `PE` 来说，内部 `core` 间通信、共享存储、共享服务、局部同步和提交边界，究竟应该被建模成什么样的体系结构？**

---

## 0. 一句话结论

我们前一阶段的主要工作，更多是在做：

- **“针对现有 baseline 热路径的 PE 内收益型 patch”**

而不是在做：

- **“PE 内部机器模型本身的重新定义”**

这也是为什么最近几轮会反复进入同一个怪圈：

1. 我们观察到了越来越强的 PE 内共享机会；
2. 也让一些 shared activity 真正跑起来了；
3. 但因为 `PE` 的底层架构仍然是 `per-core private execution + PE-scoped helpers`，
4. 所以这些共享机会没有变成真正的 shared execution authority。

因此，下一阶段最值得做的，不是继续寻找某个更早的 seed、某个更紧的 barrier、某个更优的 threshold，而是：

- **先把 `PE` 定义成一个正确的局部体系结构对象。**

---

## 1. 为什么现在必须从“收益导向”切到“架构导向”

### 1.1 前一阶段并不是没有价值

前一阶段的工作并没有白做，它至少做成了三件事：

1. 证明了 `PE` 内 overlap 真实存在；
2. 证明了 exact retire contract 不是主要障碍；
3. 把一批错误主线排得很干净：
   - late carry
   - late join
   - residency capture 冒充 early seed
   - 只靠 tightening / barrier 期待跨过 baseline

这说明我们已经有了足够扎实的负结果基础。

### 1.2 但这些工作仍然默认了一个旧前提

这些探索几乎都默认了同一个 baseline：

- `core-private WMS/private issue` 不动；
- `PE` 级结构只在外围提供 observe、registry、ingress、barrier、seed、shared residency。

于是它天然更像：

- **优化一台既有机器**

而不是：

- **重新定义这台机器**

如果继续沿这个前提推进，我们即使继续找到更多 overlap，也很可能只是得到：

- 更强的共享证据；
- 更复杂的控制结构；
- 更小的 regression；
- 但仍然没有真正的 request / service cardinality compression。

### 1.3 所以现在的问题已经变了

现在的核心问题不再是：

- “还能不能在 baseline 上再抠出一点 PE 内收益”

而是：

- **“一个通用的、面向 SNN 芯片的 PE-internal microarchitecture，到底应该长什么样？”**

---

## 2. 从当前代码现状出发：今天的 PE 究竟是什么

结合已有文档：

- [2026-03-21-pe-internal-architecture-baseline-model.md](./2026-03-21-pe-internal-architecture-baseline-model.md)
- [2026-03-21-pe-internal-core-architecture-code-state-review.md](./2026-03-21-pe-internal-core-architecture-code-state-review.md)
- [2026-03-21-pe-internal-runtime-owner-local-object-binding.md](./2026-03-21-pe-internal-runtime-owner-local-object-binding.md)
- [2026-03-21-pe-internal-storage-mapping-review.md](./2026-03-21-pe-internal-storage-mapping-review.md)

以及当前代码中的关键类：

- `MultiCorePE`
- `SnnPESubComponent`
- `SnnWorkload`
- `WeightMemorySubsystem`
- `PeSharedCoreFabric`
- `LocalStorageHierarchyController`
- `PeWeightObjectPlane`

可以把 today `PE` 内部基线收敛为一句话：

- **today 的 `PE` 是一个多核容器，不是一个真正的 shared execution island。**

### 2.1 热路径事实

today 的真实热路径仍是：

- `core -> SnnWorkload -> WeightMemorySubsystem -> StandardMemAccess`

也就是说：

1. 真正执行 metadata/value issue 与 retire 的主体仍是 `per-core WMS`；
2. `PE` 级结构虽然已经存在，但更多是 provider / observe / registry / transport。

### 2.2 对象事实

today 的 local object model 里已经注册了：

- `activation_ingress_store` (`PerPe`)
- `weight_idx_store` (`PerPe`)
- `weight_value_store` (`PerPe`)
- `state_store.coreX` (`PerCore`)
- `activation_core_queue.coreX` (`PerCore`)
- `accumulator_store.coreX` (`PerCore`)
- `register_file.coreX` (`PerCore`)

但真正具有强运行时映射的只有：

- `state_store.coreX`

而 `weight_idx_store / weight_value_store` 虽然在对象层被命名成 `PerPe`，实际运行时仍然主要由每个 core 私有的 `WMS::idx_sram_model_ / l0_sram_model_` 代理。

### 2.3 通信事实

today 真正成形的 `PE` 内通信平面是：

- `OptimizedInternalRing` 上的 packet transport

但 owner announce、join request、ready fanout、release/wakeup 这类 shared-service control messages 还没有真正成为一等公民。

### 2.4 一个关键判断

因此，当前最根本的结构性问题不是“共享不够多”，而是：

- **对象层、owner 层、service 层和 commit 层还没有形成统一的 PE 内部机器模型。**

---

## 3. 外部研究给了我们什么启发

这一节不做泛 related-work survey，而是只提炼对 `PE-internal` 架构真正有用的教训。

### 3.1 TrueNorth：强 core-local 封装 + 可扩展通信网络

TrueNorth 的代表性价值，不只是规模，而是它很早就把问题定义成：

- **core 组织**
- **片上通信网络**
- **芯片间接口**

是同一套架构问题，而不是纯计算阵列问题。

IBM 的论文摘要直接强调：

- 4096 个 neurosynaptic cores 通过片上网络互连；
- 架构可以通过芯片间通信接口二维平铺扩展。

这给我们的启发是：

- **neuromorphic 系统里的“通信网络与接口”本来就是主角，不是附属零件。**

但 TrueNorth 的路数更偏向：

- 强 core-local 封装；
- 强全局扩展性；
- 相对保守的 core 内共享。

它非常适合回答“怎么 scale”，不一定适合回答“PE 内多个 core 如何共享 metadata/value service”。

### 3.2 Loihi 2：可编程 core、本地 memory、NoC 与同步加速同等重要

Loihi 2 技术简报里有几个点特别值得注意：

1. 芯片由 `128` 个 neuromorphic cores 构成；
2. cores 通过 packet-switched asynchronous NoC 连接；
3. 每个 core 有本地 synaptic memory，且 memory allocation 更灵活；
4. timestep synchronization 由 NoC routers 加速，而不是完全靠 core 自己处理。

这说明在一个成熟的数字神经形态芯片里：

- **core-local memory 组织**
- **消息网络**
- **时间推进/同步机制**

本来就是一起被设计的。

对我们最关键的启发有两个：

1. **PE 内部不能只有 data plane，没有 sync/control plane；**
2. **“local object + local sync + local communication” 必须作为一体设计。**

但 Loihi 2 的基本单位仍然偏 core-centric，shared service 更少下沉到多 core 的 `PE` 层。

### 3.3 Tianjic：功能分块必须和数据/路由局部性对齐

Tianjic 的 FCore 给了一个很强的结构启发：

- 每个 FCore 显式包含 `axon / synapse / dendrite / soma / router`

而且论文明确强调：

- on-chip weights 被放在靠近 dendrite 的位置；
- intra-FCore 与 inter-FCore 通信都通过 router 组织；
- core 内功能块的划分和数据流分块是一致的。

这件事对我们很重要，因为它说明：

- **SNN 芯片内部结构不能只按“功能模块”拆，还必须按“对象与数据流边界”拆。**

也就是说：

- activation ingress 是一个对象平面；
- metadata lookup 是一个对象平面；
- value residency 是一个对象平面；
- state/acc/commit 又是另一组对象平面。

如果这些对象平面的 owner 和数据流分块不一致，就会持续出现今天这种“名字是共享的，运行时却是私有代理”的断层。

### 3.4 SpiNNaker 2：PE 本身就是架构对象，不只是系统拼块

SpiNNaker 2 的直接价值在于，它不是把研究重点只放在大规模系统，而是显式讨论：

- **processing element architecture**

论文摘要强调：

- 处理以 ARM M4 core 为中心；
- 增加了加速 SNN/DNN 子任务的专用 accelerator；
- PEs 通过 dedicated NoC 通信。

它给我们的架构启发是：

- **PE 不是一个可以略过内部结构、只在系统层抽象的黑盒。**

如果目标是研究更普适的 SNN 芯片内部组织，那么：

- `PE internal memory`
- `PE internal communication`
- `PE internal owner / scheduler`

都必须作为正式架构对象被讨论。

### 3.5 Core Interface Optimization：core interface 本身就是 PPA 瓶颈

2023 年关于 multi-core neuromorphic processors 的 core interface 优化论文，给了一个与我们现状高度一致的判断：

- **inter-core spike communication 的 core interface 是 PPA 瓶颈；**
- 尤其是 arbitration architecture 与 routing memory。

论文不是在优化神经元本身，而是在优化：

- arbiter tree
- routing memory
- asynchronous encoding pipeline

这对我们的意义非常直接：

- `PE` 内 core 间接口不应被当成“后处理 glue logic”；
- 它本身就是微结构主战场。

换句话说，如果我们一直只盯着 `WMS` 内部 shared-line service，却不把 core interface、control messages、owner arbitration、routing memory 当成一等结构，架构就天然是不完整的。

### 3.6 NeuroScale：local synchronization 是一个独立架构维度

NeuroScale 的意义不在于我们要复制它，而在于它把一个常被忽略的问题单独拿出来做了：

- **局部同步(local synchronization)**

论文指出：

- core 之间可以既传 spike message，也传 synchronization message；
- locality 越强，分布式局部同步的收益越大；
- 与依赖更全局同步的系统相比，local synchronization 可以显著改善规模扩展时的效率。

这与我们当前的 exactness 问题非常契合：

- 我们既不想用全局 barrier 扼杀局部共享；
- 也不能完全放任异步推进破坏 deterministic retire。

因此，对我们来说最自然的方向不是：

- 全局 barrier

也不是：

- 完全无同步自由推进

而是：

- **PE 局部范围内、以 owner/service domain 为粒度的 bounded local synchronization。**

---

## 4. 从这些研究里提炼出的共识

如果把上面的外部研究和我们的代码现状一起压缩，浮浮酱认为可以得到四条共识。

### 4.1 共识一：PE 必须被视为一个局部体系结构对象

不能再把 `PE` 理解成：

- 若干 core 的打包容器

而应该理解成：

- **一个局部数据流、局部存储、局部通信、局部同步共同存在的 micro-cluster。**

### 4.2 共识二：对象分层比模块分层更重要

对 SNN 芯片而言，比“模块功能名”更重要的是：

- activation object
- metadata object
- value object
- state object
- commit object

因为这些对象的 scope、owner、访问模式和 stall 来源都不同。

### 4.3 共识三：communication plane 不是只传 spikes

一个成熟的 `PE-internal` communication plane 至少应区分：

1. data / packet plane
2. control / owner plane
3. ready / release plane
4. synchronization plane

我们今天只有第 1 类是主路径。

### 4.4 共识四：共享 service 与 exact commit 必须解耦

神经形态芯片内部完全可以做 aggressive shared service，
但 architectural visibility point 仍然应该被单独保护。

这也是我们前一阶段里少数已经证明正确的东西：

- **共享发生在 service plane；**
- **exactness 保留在 commit plane。**

---

## 5. 推荐的新问题定义：构建一个通用的 PE-Internal Clustered Object-Service Microarchitecture

为了把讨论从当前 mainline 的 patch 里拉出来，建议正式采用一个更底层的问题定义：

- **为 `SnnDL` 风格多核 `PE` 设计一套通用的 `Clustered Object-Service Microarchitecture`。**

这不是某个单一优化点，而是一台机器的定义。

下面先给出推荐的机器模型。

---

## 6. 推荐的通用 PE 内部体系结构模型

### 6.1 先给出总图

推荐把一个 `PE` 正式拆成三层 scope：

1. `C-scope`：`core-private`
2. `P-scope`：`pod-shared`
3. `E-scope`：`PE-global`

这里专门引入 `pod` 层，是因为：

- 如果所有 shared structure 一开始就做成整个 `PE` 级统一大表，
- 很容易重演我们之前担心的中心化 RSM / scoreboard 过大、时序过重、bank contention 过大的问题。

因此，推荐的机器形态不是：

- 单层 `PerCore + PerPe`

而是：

- **`PerCore + PodShared + PeGlobal`**

这个分层也更接近我们从外部系统里学到的经验：

- core-locality 要保留；
- local cluster sharing 要显式存在；
- 全局 PE 只做必要的 transport / directory / admission。

### 6.2 `C-scope`：必须保持 core-private 的对象

以下对象建议明确固定在 `C-scope`：

1. `state_store.coreX`
2. `accumulator_store.coreX`
3. `register_file.coreX`
4. `commit / retire queue.coreX`
5. `exact visibility bookkeeping.coreX`

原因很简单：

- 它们与最终 architectural ownership 强耦合；
- 任何粗暴共享都会直接把风险推进 commit plane。

### 6.3 `P-scope`：最值得共享的对象平面

`P-scope` 是这套架构的核心，建议优先承载三类对象：

1. **Metadata Object Plane**
   - `idx2`
   - `rowidx`
   - `pre-base / pre-band`
   - layout / row-color / object descriptors

2. **Value Residency Plane**
   - shared value lines
   - shared seeded residency
   - refill / evict bookkeeping

3. **Owner/Service Control Plane**
   - owner table
   - join table
   - ready fanout entries
   - bounded replay / rescue entries

为什么这些对象应该先落在 `P-scope` 而不是一口气做成 `E-scope`：

1. metadata/value overlap 往往先在局部邻近 core 里最强；
2. pod 级 bank/port 仲裁更容易实现；
3. bounded owner table / ready table 更容易控时序和面积；
4. 这比“整个 PE 一个大共享表”更像可落地微结构。

### 6.4 `E-scope`：PE 级只保留必须全局的东西

`E-scope` 不应该承担所有共享语义，而应该只承担：

1. **Activation Ingress Plane**
   - `activation_ingress_store`
   - spike / packet admission
   - coarse frontier export

2. **Packet + Control Transport**
   - packet plane
   - owner announce
   - join routing
   - release / wakeup
   - sync messages

3. **Directory / Admission Plane**
   - cross-pod directory
   - coarse-grain shared object location
   - PE 级 budget / fairness / throttling

也就是说，`E-scope` 是：

- **路由与目录**

而不是：

- **所有共享 service 的实际执行者**

---

## 7. 这台机器该如何运行

### 7.1 基本数据流

推荐的 generic 数据流是：

- `packet ingress`
- `frontier / metadata distill`
- `pod-level owner select`
- `shared object service`
- `ready fanout`
- `core-private compute`
- `core-private exact commit`

和我们此前 patch 最大的区别在于：

- **owner select 必须先于 private issue fanout**

否则一切都会退化成 late join。

### 7.2 调度单位要从 request 变成 object transaction

today 更像是：

- per-core request 驱动，再试图 opportunistic merge

而通用 `PE-internal` 架构应更像：

- **object transaction 驱动，再由多个 consumer 精确 join**

这意味着调度器关注的不是：

- 某个 core 是否要发一条读请求

而是：

- 某个 shared metadata/value object 是否已经被 owner 启动；
- 这个 object transaction 是否还允许 join；
- join 后能否避免 duplicate work；
- join 会不会把 exact commit 风险推进到不可控。

### 7.3 control-plane message 要正式化

建议把 `PE` 内 control-plane message 正式定义为以下几类：

1. `OWNER_ANNOUNCE`
2. `JOIN_REQUEST`
3. `READY_FANOUT`
4. `RELEASE`
5. `RESCUE / REPLAY`
6. `LOCAL_SYNC_TICK`

这是对 today packet-only plane 的根本升级。

### 7.4 同步模型：bounded local synchronization

推荐的同步模型不是传统全局 barrier，而是：

- **以 pod / object-domain 为粒度的 bounded local synchronization**

也就是：

1. owner 与 consumers 在局部域内维持有限 skew；
2. ready 可以局部广播；
3. commit 仍由 core-private retire 序控制；
4. 跨 pod / 跨 PE 的推进不被强制绑死。

这能同时兼顾：

- locality
- shared service efficiency
- deterministic retire safety

---

## 8. 这套模型如何映射回我们当前代码

### 8.1 已经存在的“影子”

我们当前仓库并不是毫无基础，恰恰相反，已经有几块非常像这套新架构的早期影子：

1. `LocalStorageHierarchyController`
   - 已有 object namespace

2. `PeSharedCoreFabric`
   - 已有 ingress / harbor / descriptor / dispatch 骨架

3. `PeWeightObjectPlane`
   - 已经明确写成 `Minimal PE-shared owner plane for weight idx/value storage studies`

4. `OptimizedInternalRing`
   - 已有 packet transport 后端

5. `WeightMemorySubsystem`
   - 已经有成熟的 metadata/value service 与 retire 逻辑

所以真正的问题不是“没有东西”，而是：

- **这些东西还没有按统一机器模型重新组织。**

### 8.2 目前最大的三个断层

#### 断层一：object scope 与 runtime owner 断裂

今天 `weight_idx_store / weight_value_store` 在对象层是 `PerPe`，
但实际运行时 owner 仍以 `per-core WMS proxy` 为主。

#### 断层二：communication plane 只有 packet，没有 formal control plane

today 没有真正的一等：

- owner announce
- join
- ready fanout
- local sync

#### 断层三：shared service 未被组织成 pod/PE 级执行平面

today shared semantics 更像：

- `WMS` 内部 collapse / residency / join optimization

而不是：

- 显式的 `pod-shared object service plane`

### 8.3 一个重要的新判断

因此，下一阶段不是“再写一个新的 WMS heuristic”，而是：

- **把 `WMS` 从 today 的 per-core monolith 逐步拆成：**
  - `core-private compute/commit`
  - `pod-shared metadata/value service`
  - `PE-global transport/directory/sync`

这才是从体系结构层真正改写 PE 内部结构。

---

## 9. 对下一阶段研究和实现的具体指引

### 9.1 先把成功标准改掉

下一阶段不应首先以：

- `sim_time`
- `memory_requests`

是否立即变好作为唯一成功标准。

更合理的第一阶段成功标准应是：

1. shared object 是否有真实 owner；
2. owner 是否先于 private issue 被建立；
3. control-plane message 是否真正存在；
4. pod/PE 范围的 bank/port/contention 是否被显式建模；
5. exact commit 是否仍然保持 core-private。

只有这些结构先成立，后面的收益才有意义。

### 9.2 推荐的研究阶段

#### 阶段 G0：formal PE model

先把三层 scope 与对象分类写成正式接口/文档：

- `C-scope`
- `P-scope`
- `E-scope`

#### 阶段 G1：pod-shared metadata object plane

先不要急着做整条 shared value line 主链，而是先把：

- `idx2 / rowidx / pre-band`

这类更轻、更早、更共享的对象正式做成 `P-scope owner-backed object`。

#### 阶段 G2：owner/control plane

把以下控制消息真正做成一等结构：

- `OWNER_ANNOUNCE`
- `JOIN_REQUEST`
- `READY_FANOUT`
- `LOCAL_SYNC_TICK`

#### 阶段 G3：shared value residency

在 metadata plane 成立之后，再把 value residency 接到 `P-scope`。

#### 阶段 G4：exact consumer join + core-private commit

最后才把 shared ready、consumer wakeup、exact retire 完整闭环。

### 9.3 下一阶段必须新增的统计

下一阶段的探针不应再只统计 overlap，而要固定统计：

1. `object_owner_first_total`
2. `object_join_before_private_issue_total`
3. `duplicate_work_elided_total`
4. `pod_bank_conflict_cycles`
5. `control_plane_messages_by_type`
6. `local_sync_wait_cycles`
7. `exact_commit_blocked_cycles`

这套统计比单纯看 shared hits 更接近真正的架构状态。

---

## 10. 最终判断：我们真正缺的不是另一个优化点，而是一台新的 PE

到这里，浮浮酱的判断已经很明确了：

### 10.1 我们之前确实过于收益导向

过去的工作更多是在问：

- “现有 PE 上还能加什么 shared optimization”

而不是问：

- “PE 作为一个局部神经形态 cluster，本来应该长什么样”

### 10.2 现在应该正式转到架构导向

下一阶段最值得推进的，不是下一版 `PULSE` 小补丁，而是：

- **一个通用的 PE-internal object/service/sync microarchitecture**

这条线更底层、更普适，也更接近真正的体系结构研究。

### 10.3 这条线为什么更像顶会问题

因为它回答的不是：

- 某个 heuristic 为什么快一点

而是：

- 在一个多核 SNN `PE` 内部，core-private state、pod-shared metadata/value、PE-global communication/sync 应该如何共同构成一台机器。

这比继续做 baseline 层面的 patch，更接近一个真正能支撑论文主张的架构问题。

---

## 11. 参考文献与输入材料

### 11.1 仓库内输入

- [PE 内部 core-level 架构基线模型](./2026-03-21-pe-internal-architecture-baseline-model.md)
- [PE 内 core-level 代码现状架构审阅](./2026-03-21-pe-internal-core-architecture-code-state-review.md)
- [PE 内 runtime owner -> local object 正式绑定表](./2026-03-21-pe-internal-runtime-owner-local-object-binding.md)
- [PE 内部存储映射审阅](./2026-03-21-pe-internal-storage-mapping-review.md)
- [PE 内部优化现状、怪圈根因与下一阶段路线图](./2026-03-24-pe-internal-optimization-loop-rootcause-and-next-stage.md)

### 11.2 外部一手材料

- IBM Research, *A million spiking-neuron integrated circuit with a scalable communication network and interface*  
  https://research.ibm.com/publications/a-million-spiking-neuron-integrated-circuit-with-a-scalable-communication-network-and-interface

- Intel, *Taking Neuromorphic Computing with Loihi 2 to the Next Level*  
  https://download.intel.com/newsroom/2021/new-technologies/neuromorphic-computing-loihi-2-brief.pdf

- Höppner et al., *The SpiNNaker 2 Processing Element Architecture for Hybrid Digital Neuromorphic Computing*  
  https://arxiv.org/abs/2103.08392

- Su et al., *Core interface optimization for multi-core neuromorphic processors*  
  https://arxiv.org/abs/2308.04171

- Pei et al., *Towards artificial general intelligence with hybrid Tianjic chip architecture*  
  https://aiichironakano.github.io/cs653/Pei-ArtificialGeneralIntelligenceChip-Nature19.pdf

- *A deterministic neuromorphic architecture with scalable time synchronization*  
  https://www.nature.com/articles/s41467-025-65268-z
