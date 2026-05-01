# PE 内 core-level 代码现状架构审阅（2026-03-21）

> 日期：2026-03-21  
> 状态：code-state review v1  
> 目标：在不预设新方案的前提下，先把当前 `SnnDL` 中 `PE` 内部 `core` 间通信、共享服务、共享存储、提交语义的真实代码现状梳理清楚，为后续独立的 `PE-internal` 架构设计建立基线。

---

## 0. 这份文档解决什么问题

本文档不再把关注点放在系统主线

- `DRAM-based SNN chip + GAS + GCSS-GLIDE + STORM`

的继续优化上，而是把问题下沉到一个更底层、也更普适的对象：

- **`SnnDL` 风格多核 `PE` 内部，`core` 间架构今天到底是怎样实现的？**

这件事必须先澄清，因为我们最近几轮实验已经说明：

1. 单纯围绕现有主线做 `shared ingress`、晚期 `idx2`、旧 `apply-stage preband`，很难进入真正的收益空间。  
2. 现有代码里并不是“没有 `PE` 内部结构”，而是已经存在一些 `PE` 级 provider、共享 registry、local storage 对象、retire contract；只是它们还没有组成一个统一的 `PE-internal microarchitecture`。  
3. 如果后续要做真正有价值的 `PE` 内优化，前提不是继续 patch 某个局部 heuristic，而是先把今天的代码基线准确抽象出来。

因此，这份审阅文档聚焦三个问题：

1. 当前真实热路径是什么？  
2. 现有 `PE` 级结构里，哪些已经在主路径上，哪些只是骨架/观测件？  
3. 今天阻止我们进入收益空间的底层结构缺口到底在哪里？

---

## 1. 总体结论

当前 `SnnDL` 中的 `PE` 内部架构，可概括为一句话：

- **`per-core private execution` 为主，`PE-level shared helpers/providers` 为辅。**

更具体地说：

1. **真实主路径** 仍然是  
   - `core -> workload -> WeightMemorySubsystem (WMS) -> StandardMemAccess`

2. `PE` 级已经存在的结构包括  
   - `OptimizedInternalRing`
   - `PeDmaScheduler`
   - `LocalStorageHierarchyController`
   - `PeSharedCoreFabric`

3. 但这些结构的成熟度不一致：
   - `ring` 已是片上 packet transport 主后端
   - `DMA` 已有较完整调度模型，但还未真正挂上权重服务热路径
   - `local storage` 仍是 object registry / stats snapshot 骨架
   - `PULSE fabric` 仍以 ingress / observe / harbor / descriptor observe 为主，fabric-side actual service 未真正启用

4. 今天真正的“共享服务”已经在发生，但形式是  
   - `WMS` 内部的 shared-line registry / residency / tracker
   - 而不是一个显式建模的 `PE-shared service plane`

因此，现状不是“没有 `PE` 内共享”，而是：

- **共享语义已经出现，但共享微结构尚未成立。**

---

## 2. 当前 `PE` 组件装配是什么样

`MultiCorePE` 当前同时暴露了多个 `PE` 级 provider：

- `IDmaSchedulerProvider`
- `ILocalStorageProvider`
- `IPeSharedCoreFabricProvider`

并提供：

- `dmaScheduler()`
- `localStorageHierarchy()`
- `peSharedCoreFabric()`

代码位置：

- `components/MultiCorePE.h`
- `components/MultiCorePE.cc`

在构造阶段，`MultiCorePE` 会根据参数创建：

1. `PeDmaScheduler`
2. `LocalStorageHierarchyController`
3. `PeSharedCoreFabric`
4. `OptimizedInternalRing`

这说明，**从组件层次上看，仓库已经具备了“做 `PE` 内部架构”的基本挂点。**

但这里必须强调一个关键判断：

- **provider 已存在，不等于热路径已接入。**

当前代码更多体现为：

- `PE` 级结构已被纳入 `MultiCorePE` 生命周期与统计口径

而不是：

- 它们已经成为 `core` 权重服务/提交服务的统一执行底座

这一区别，正是当前代码现状最核心的事实。

---

## 3. 真实热路径：今天谁在真正执行

### 3.1 `core` 侧 runtime 的真实内存后端

`SnnPESubComponent::bindWorkloadRuntime_()` 会给 workload 构造 `ICoreWorkload::Runtime`。

这里最关键的一行是：

- `rt.mem = stdmem_ep_->memoryAccess()`

这意味着 workload 看到的内存访问接口，直接来自 `StdMemEndpoint`。

而 `StdMemEndpoint::bindStdMem()` 内部绑定的是：

- `StandardMemAccess`

因此，当前 `core` 侧 runtime 看到的内存后端，本质上是：

- **`StandardMemAccess`**

而不是：

- `DmaMemAccessProxy`
- `PE` 级统一 memory service object

### 3.2 `SnnWorkload` 如何使用它

`SnnWorkload` 在创建或接管 `WeightMemorySubsystem` 之后，会直接执行：

- `wms->bindMemory(rt_.mem)`

于是今天真正的权重服务链条是：

- `SnnPESubComponent`
- `StdMemEndpoint`
- `StandardMemAccess`
- `SnnWorkload`
- `WeightMemorySubsystem`

即：

- **每个 core 拥有自己的 `WMS`，而每个 `WMS` 直接绑定自己的 runtime memory access。**

这就是今天最真实的主路径。

### 3.3 直接结论

所以，今天的 `PE` 内部执行模型不是：

- `PE-shared issue/service plane` 驱动多个 core

而是：

- **多个 `per-core WMS` 并行执行，`PE` 级结构在旁边做 transport、统计、注册、观察，或提供尚未接线的共享能力。**

---

## 4. 通信层现状：packet transport 已成形，control-plane 还没有

### 4.1 已经存在的片上 core 间通信

`NocSubsystem` 在跨 core 包路由时会：

1. 构造 `RingMessage`
2. 调用 `OptimizedInternalRing::sendMessage()`
3. 在 ring tick 后从 ejection queue 拉回
4. 再投递给目标 endpoint

这说明，今天 `PE` 内 `core` 间 packet transport 已经有明确模型，且其后端唯一主线就是：

- `OptimizedInternalRing`

`OptimizedInternalRing` 自身支持：

- 双向 ring
- VC
- credit
- priority
- shortest-path route select

因此，在“内部互连”这个问题上，代码现状并不空白。

### 4.2 但这层通信目前主要只服务 packet

虽然 `RingMessageType` 里声明了：

- `PACKET_MESSAGE`
- `MEMORY_REQUEST`
- `MEMORY_RESPONSE`
- `CONTROL_MESSAGE`

但 `NocSubsystem` 目前实际认真处理的仍主要是：

- `PACKET_MESSAGE`

对 non-packet message，当前逻辑基本仍是保持 legacy ignore 行为。

### 4.3 这意味着什么

今天 `PE` 内部通信模型已经能表达：

- spike / packet 从一个 core 到另一个 core 的 transport

但还不能很好表达：

- owner announce
- service join
- ready fanout
- wakeup / release
- shared residency invalidation

也就是说，**我们有 packet plane，但没有真正的 shared-service control plane。**

如果后续要做 `PE` 内 core 间更底层的架构优化，这一层是必须独立建模的。

---

## 5. 服务层现状：共享语义已经存在，但共享微结构还没有

### 5.1 真正的执行内核还是 `WMS`

`WeightMemorySubsystem::onClockTick()` 现在承担了大量实际工作：

- `retire` 推进
- rowptr / rowidx 预取
- `idx2` 预取
- pending reads/drirect reads drain
- shared-line actual path completion
- weight SRAM stall 注入

这说明 `WMS` 不只是“一个读权重工具类”，而是：

- **当前 `core` 内 memory/service/retire 的真实执行内核**

### 5.2 当前共享服务是怎么实现的

在 `WMS` 里，exact demand 与 seeded line 都会围绕 line address 进入共享逻辑：

- `PulseSharedLineService`
- `PulseSeededLineResidency`
- `PulseSeededLineTracker`

它们共同实现了三件事：

1. 多个 consumer 可以针对同一 line `joinOrRegister`
2. owner 负责真正发起一次 line read
3. line 返回后统一 `complete()`，对 waiters fanout

这实际上已经非常接近一个 service-plane 共享语义。

### 5.3 但为什么说这还不是完整微结构

因为当前它仍然是：

- 进程内静态 registry
- 基于 `(scope_id, window_seq, line_addr)` 的 hash key
- 没有显式 PE 内消息
- 没有单独 object/buffer/port/bank/arbitration lifecycle

换句话说，它能表达：

- “同一 line 只服务一次，多个 consumer 可 join”

但还不能表达：

- owner/join 是如何通信的
- shared residency 在哪里占资源
- ready fanout 占用什么端口/队列
- line 生命周期如何受 `PE` 级对象约束

因此，这一层更准确的定位是：

- **shared service semantics prototype**

而不是：

- **full PE-internal service microarchitecture**

### 5.4 `PeSharedCoreFabric` 当前角色

`PeSharedCoreFabric` 今天更偏向：

- ingress mirror
- queue mirror
- gather harbor
- descriptor observe
- dispatch token buffering

它在 `PULSE` 中很重要，但到今天为止，fabric-side actual descriptor service 仍然没有真正打开。

因此当前的真实状态是：

- fabric 负责 ingress/observe/bucketize
- actual service 仍由 core-side `WMS` 执行

这就导致：

- `PE` 内共享服务语义已经出现
- 但 `PE` 内共享服务执行面仍未统一

---

## 6. 存储层现状：两套模型并存，但没有统一 storage plane

### 6.1 `WMS` 内部已有 weight SRAM 模型

`WMS` 当前已经内置：

- `weight_idx_sram`
- `weight_l0_sram`

并在 `onClockTick()` 中消耗 predicted extra cycles，将 stall 反馈到 issue 节奏。

这说明：

- 与权重相关的 bank/port/stall 建模，并非完全空白

### 6.2 `PE` 级 local storage 也已经有对象层

`MultiCorePE` 在创建 `LocalStorageHierarchyController` 时，会注册一组 Phase A 对象：

- `activation_ingress_store`
- `weight_idx_store`
- `weight_value_store`
- `state_store`
- `activation_core_queue`
- `accumulator_store`
- `register_file`

这些对象已经具备配置字段：

- `scope`
- `capacity_bytes`
- `banks`
- `read_ports`
- `write_ports`
- `update_ports`
- `queue_depth`

从“架构命名空间”上看，这已经是一个不错的起点。

### 6.3 但关键缺口在于：两层没有统一

当前还没有形成下面这种关系：

- `WMS internal SRAM model` <-> `PE local storage object model`

也就是说，我们还没有统一回答：

1. `PulseSeededLineResidency` 到底映射到哪个本地对象？  
2. `rowidx / metadata frontier / shared line` 到底占用哪个 store？  
3. `weight_idx_sram` 与 `weight_idx_store` 是重复建模、替代建模，还是分层建模？  
4. `activation_ingress`、`core queue`、`shared service residency` 之间是否共享同一片物理资源预算？

因此，**当前 storage plane 最大的问题不是“没有结构”，而是“对象层与执行层脱节”。**

---

## 7. 调度/发射层现状：`PE DMA` 已成型，但不在主路径上

### 7.1 `PeDmaScheduler` 本身能力并不弱

当前 `PeDmaScheduler` 已支持：

- per-core / per-priority queues
- overflow queue
- bytes-per-cycle budget
- read-engine budget
- inflight cap
- stage budget scale
- address channel interleave
- barrier-cycle service

这已经是一个相当像样的 `PE-shared memory issue` 模型。

### 7.2 但它没有真正替代 `rt.mem`

仓库里虽然有：

- `DmaMemAccessProxy`

可把 `read()` 转发给 `PeDmaScheduler`，但当前生产路径没有把 `StdMemEndpoint::memoryAccess()` 包起来交给 workload/WMS。

全局搜索能看到：

- `DmaMemAccessProxy` 主要出现在 tests

这说明现在最真实的现状是：

- **`PE DMA` 已存在，但尚未成为真实权重服务的统一 issue 层。**

### 7.3 这件事为什么重要

因为只要这层没接入，我们就仍然缺少：

- PE 范围的 read issue arbitration
- 多 core 共享 budget / channel / inflight 的真实竞争关系
- core 间公平性与 stage-aware issue 的统一建模

也就是说，今天的 `PE` 内 memory-side 竞争，大部分仍被摊平在各 core 私有 `WMS` 的 issue 行为里。

---

## 8. retire/commit 层现状：contract 已较硬，但仍服务于私有 issue 模型

### 8.1 默认语义仍以 `global_inorder` 为基准

`WMS` 当前默认仍以：

- `experimental_retire_policy = global_inorder`

为主。

同时它支持：

- `per_post deterministic retire`
- `shadow per_post retire`
- `pulse_domain_retire` 的 actual/shadow 变体

### 8.2 这一层已经做得比表面上更深

它不仅能切 policy，还持续维护大量 observability：

- `ready_but_blocked_edges_total`
- `crosspost_blocked_edges_total`
- `policy_loss_cycles_total`
- `shadow_per_post_recoverable_edges_total`

说明今天的 retire 层不是一句口号，而是已经形成了较硬的 correctness/diagnosis surface。

### 8.3 但它仍然没有和真正的 `PE-shared service plane` 耦合

当前 per-post / domain-retire 逻辑，主要仍在 `WMS` 里消化，它所面对的 issue/service 模型，仍然是：

- `per-core issue`
- `core-side shared-line join`

而不是：

- `PE-level descriptor agenda`
- `PE-level residency object`
- `PE-level shared consume queues`

因此今天可以说：

- commit plane 已经比 service plane 更成熟

这也是为什么我们此前的多轮探索里，经常出现：

- correctness contract 已经很硬
- 但 shared service 仍旧停在半共享状态

---

## 9. 为什么此前几条探索线没有进入真正收益空间

这里不讨论未来方案，只用现有实验解释现状。

### 9.1 `shared ingress` 为什么没用

实验：

- `mainexp/experiments/2026-03-16_pulse_shared_ingress_actual_ab_v1`

结果显示：

- `pulse_ingress_packets_total = 1,206,784`
- `pulse_ingress_bypass_total = 1,205,386`
- `memory.memory_requests +0`
- `memctrl.req_total +0`

这说明：

- ingress 只改变了 admission 包装层
- 没减少真实 service 工作量
- 没进入 memory-side 主矛盾

根因是：

- 当前共享发生在 ingress
- 而主路径的 service/issue 仍是 per-core `WMS`

### 9.2 `idx2` 为什么没用

实验：

- `mainexp/experiments/2026-03-21_idx2_ingress_finish_stats_smoke_v1`

结果显示：

- `idx2_owner_total = 122`
- `idx2_owner_useful_total = 42`
- `idx2_owner_dead_total = 80`
- `idx2_owner_dead_ratio = 0.6557`
- `idx2_demand_join_before_ready_ratio = 0.8235`

这说明：

- 它共享得太晚
- 大量 owner 没被需求真正消费
- 多数 join 发生在 ready 之前，属于“跟跑”，不是“超前覆盖”

所以 `idx2` 更像一个过晚、过窄的 line/value 层优化。

### 9.3 `apply-stage preband` 为什么也不值得继续主投

实验：

- `mainexp/experiments/2026-03-18_pulse_mfb_preband_actual_ab_v1`

结果：

- `memory.memory_requests +0`
- `pulse_metadata_seed_usefulness_ratio ≈ 0.061`

这说明：

- 虽然发起了大量 owner
- 但真实 memory-side benefit 没有形成

### 9.4 为什么 `gather-preband` 是唯一真正有价值的信号

实验：

- `mainexp/experiments/2026-03-18_pulse_mfb_gather_preband_actual_ab_v1`
- `mainexp/experiments/2026-03-21_pulse_mfb_gather_tightening_sweep_v1`

信号包括：

- `owner_first_rate` 很高
- `ready_before_demand_ratio` 较高
- tightening 后最优点已把退化收敛到 `+186ns / +28 requests`

这说明真正可能有价值的方向是：

- **更早的 metadata frontier**
- **更强的 volume gate**
- **让共享从 late exact-line，前移到更早的 descriptor/metadata service opportunity**

但它今天仍然只是：

- `WMS` 内部的 line/service 级 seed 与 join

而不是一个完整的 `PE-shared issue/storage/control` 架构。

---

## 10. 现阶段最关键的结构性缺口

基于代码与实验，当前 `PE` 内部最关键的缺口有五个。

### 10.1 没有真正接入热路径的 `PE-shared issue arbiter`

`PeDmaScheduler` 已存在，但 `WMS` 仍直接绑 `StandardMemAccess`。  
这意味着 today 的 memory issue 本质上仍然是 per-core 私有发射。

### 10.2 没有显式建模的 shared-service control plane

今天有 packet ring，但没有：

- announce
- join
- ready fanout
- release

这种 `PE` 内 control-plane message 体系。

### 10.3 没有统一的 storage plane

`WMS` 内部 SRAM model 与 `PE local storage object model` 并存，但没有统一映射与资源关系。

### 10.4 当前共享服务仍是 registry 语义，不是资源化微结构

shared line today 能表达“共享一次服务，多 consumer join”，但还不能表达：

- object residency
- bank/port contention
- lifecycle / eviction / release semantics

### 10.5 correctness 已成熟，但没有和统一 service plane 闭环

retire contract 和 observability 已经很硬，  
但它所约束的还是 today 的私有 issue + 半共享 service 组合，而不是一个真正统一的 `PE-shared execution substrate`。

---

## 11. 当前代码现状的正式结论

截至 2026-03-21，`SnnDL` 中 `PE` 内 core-level 架构的正式判断应写成：

1. **通信层**  
   - 已有 packet-level inter-core ring transport  
   - 尚无 explicit shared-service control plane

2. **服务层**  
   - 已有 core-side shared-line service semantics  
   - 但仍基于 static registry，而非资源化 PE-shared service microarchitecture

3. **存储层**  
   - 已有 `WMS` 内部 SRAM 模型  
   - 已有 `PE` 级 local-storage object registry  
   - 二者尚未合并成统一 storage plane

4. **调度层**  
   - `PE DMA` 已有较成熟 scheduler 模型  
   - 但并未进入真实权重服务热路径

5. **提交层**  
   - retire correctness/observability 已较成熟  
   - 但仍服务于 today 的私有 issue 模式

因此，最准确的总判断是：

- **当前代码已经拥有做 `PE-internal` 架构研究的关键碎片，但还没有形成统一的、可直接论文化的 `PE 内 core-level 微结构模型`。**

这也解释了为什么我们过去一段时间“能看到共享信号，但很难把它稳定转成系统收益”：

- 因为共享发生的位置、资源化程度、通信方式、存储对象和提交边界，今天仍然分散在多个层里，没有真正收口。

---

## 12. 下一步工作边界

在这份审阅基础上，下一阶段不应直接继续 patch 现有 heuristic，而应先做一件更基础的事：

- **把今天的代码现状正式抽象成一个 `PE-internal architecture baseline model`**

在这个 baseline 之上，再讨论新的独立方案，才不会重新掉回：

- ingress patch
- late-line patch
- 只做 observe、不做 resource model

这也是后续设计文档的自然起点。
