# PE-Atlas：面向 SnnDL 风格多核 PE 的底层对象化众核架构设计（2026-03-30）

> 日期：2026-03-30  
> 状态：architecture design v1  
> 新主线定位：`paper-first + architecture-first`  
> 工作名：`PE-Atlas` = `PE-internal Object-Scoped Manycore Machine`  
> 目标：把 `PE` 从“per-core private execution + shared helpers”的多核容器，重新定义成一台 **对象边界明确、互连面明确、局部存储明确、生命周期可闭合、统计可验证** 的局部众核机器。

---

## 0. 一句话结论

下一阶段不再继续围绕 `PULSE / rowdescriptor / ready-join` 做收益优先的局部 patch，而是正式切换到一条更底层的新主线：

- **先定义 `PE` 这台机器，再从已经存在完整生命周期的对象里选择优化对象。**

这条主线的核心判断是：

1. 当前代码里最真实的运行模型仍然是：
   - `per-core WMS/private issue + PE-scoped shared helpers`
2. 这不是“共享太少”的问题，而是：
   - **对象层、互连层、存储层、同步层、commit 层没有被统一建模**
3. 因此，下一阶段最重要的工作不是继续追求 `memory_requests` 立刻下降，而是先回答：
   - `PE` 内到底有哪些对象？
   - 它们在哪里 materialize？
   - 谁拥有 owner？
   - 谁负责 ready / release？
   - 哪些对象真的是 shared，哪些只是 private proxy？

---

## 1. 为什么必须从“收益导向”切到“架构导向”

### 1.1 旧路线的真实收获

此前围绕 `shared ingress / idx2 / preband / gather-preband / rowdescriptor` 的多轮实验并非没有价值，它们至少证明了：

1. `PE` 内 overlap 确实存在；
2. `exact retire` 不是唯一硬障碍；
3. 很多直觉上“可能有效”的局部优化其实并没有打到真正的结构矛盾。

也就是说，负结果已经足够多，足够支撑路线切换。

### 1.2 旧路线为什么会反复兜圈

我们反复进入同一个循环的根因，不是实现不够细，而是研究对象一开始就偏了：

1. 我们一直在问：
   - `哪条 seam 更可能带来收益`
2. 但没有先问：
   - `这条 seam 在当前 runtime 中到底是不是正式架构对象`

结果就是：

- 统计越来越多；
- `rowdescriptor` 活动越来越清楚；
- 但 `PE` 仍然没有变成一台共享执行机器。

所以旧路线的问题不是“优化力度不够”，而是：

- **在没有机器模型的前提下，过早追求性能收益。**

### 1.3 新路线的核心目标

`PE-Atlas` 不再把“先拿到收益”作为第一目标，而把下面三件事放到最前面：

1. 画清楚 `PE` 内部完整对象图；
2. 画清楚 `PE` 内部完整消息图；
3. 画清楚 `PE` 内部完整存储与生命周期图。

只有这三张图收干净，后续优化才不会继续漂浮在局部 seam 上。

---

## 2. 当前基线：今天的 PE 到底是什么

这部分只描述 **今天代码中真实存在的模型**，作为 `PE-Atlas` 的起点。

### 2.1 基线定义

当前 `PE` 内部的实际形态可收敛为：

- **`per-core private execution` on top of `PE-scoped shared helpers`**

即：

1. 真正执行 `metadata/weight issue -> ready -> retire` 的主体仍是每个 core 私有的 `WeightMemorySubsystem`；
2. `OptimizedInternalRing / PeDmaScheduler / LocalStorageHierarchyController / PeSharedCoreFabric` 等 `PE` 级结构已经存在；
3. 但它们目前大多仍处于：
   - transport
   - provider
   - registry
   - observe
   这类角色。

### 2.2 旧主线的代码事实

当前代码里，`PreMphfBase / PreMphfBand / Idx2Row / RowIndex` 已经具备了对象名与观测入口：

- `observePulseMetadataFrontier_()` 会把 `PreMphfBase / PreMphfBand` 推到 `observePeInternalPodMetadataObject_()`。
- `experimental rowidx / idx2 ingress` 也会在特定路径上调用 `observePeInternalPodMetadataObject_()`。

但真正进入 `markReady -> ReadyFanout` 活动生命周期的，当前只有：

- `RowDescriptor`

因此今天最接近“shared object lifecycle”的并不是更早 metadata，而是：

- **`rowdescriptor` 这一条局部 seam**

这也是为什么此前 `all mask` 与 `rowdescriptor-only` 的 fresh runtime 结果完全同构。

### 2.3 当前最根本的结构矛盾

今天最大的矛盾不是“共享结构不够多”，而是：

- **对象层、owner 层、service 层、storage 层和 commit 层没有形成同一台机器。**

具体表现为：

1. 名义上的 `PerPe` / `PerPod` 对象很多；
2. 但运行时真实 owner 仍常常落在 `per-core WMS` 里；
3. 因此共享语义多半是“局部 collapse”或“shadow lifecycle”，而不是正式微结构。

---

## 3. 来自众核与神经形态架构的六条一等启发

### 3.1 `message passing first`，不要默认全局共享语义

Intel SCC 的关键启发，不是“48 核”本身，而是：

- 它把芯片看成一个片上 cluster；
- 强调 mesh + message passing；
- 不把跨核共享一致性当默认前提。

对我们最重要的影响是：

- `PE` 内部的 shared object 不应该依赖隐式一致性；
- 它应该依赖 **显式 owner + 显式消息**。

来源：

- Intel SCC overview paper  
  https://www.intel.cn/content/dam/www/public/us/en/documents/technology-briefs/intel-labs-single-chip-cloud-overview-paper.pdf

### 3.2 `clustered hierarchy`，必须有中间层

Kalray MPPA 的启发非常直接：

- compute clusters 是正式架构对象；
- cluster 间通信与同步通过 NoC；
- data/control interconnect 明确区分。

对我们来说，这意味着：

- `PE` 内部不能只有 `per-core` 和 `per-PE` 两层；
- 必须引入一个 **pod/cluster 中间层**。

来源：

- Kalray MPPA manycore overview  
  https://www.kalrayinc.com/products/mppa-technology/
- Distributed runtime for MPPA-256  
  https://www.sciencedirect.com/science/article/pii/S1877050913004766

### 3.3 `router/interface` 本身就是瓶颈

2023 的 neuromorphic core-interface 工作强调：

- inter-core communication 的瓶颈不只在计算；
- 更在 arbitration architecture 与 routing memory。

这正好点中了我们现在忽视的部分：

- `PE` 内部 router、队列、控制面消息、目录、仲裁，不是“实现细节”，而是正式微结构对象。

来源：

- Core interface optimization for multi-core neuromorphic processors  
  https://arxiv.org/abs/2308.04171

### 3.4 `scratchpad + explicit movement` 优于隐式共享

Epiphany 的强启发是：

- 每核本地存储非常明确；
- 数据移动是显式的；
- mesh 与 DMA 是第一公民。

对我们意味着：

- `WMS internal storage model` 不应该继续只是“若干私有 bank + 一些 shared helper”；
- 它应该被提升为：
  - local scratchpad / residency / explicit movement 的正式层次模型。

来源：

- Epiphany Architecture Reference  
  https://www.adapteva.com/docs/epiphany_arch_ref.pdf

### 3.5 `event/data fabric` 与 `control/sync fabric` 必须分开

Loihi 2 与 MPPA 都给了同样的方向：

- 数据消息与控制/同步不应混成一条逻辑通道；
- 异步通信、局部同步、流量调节本身应当硬件化/结构化。

对我们的具体影响是：

- `PE` 内部至少要有逻辑上的两张网：
  - `event/data fabric`
  - `control/sync fabric`

来源：

- Loihi 2 technology brief  
  https://www.intel.com/content/www/us/en/research/neuromorphic-computing-loihi-2-technology-brief.html

### 3.6 hierarchy 必须先于优化

Tianjic 和 `A system hierarchy for brain-inspired computing` 给出的共同启发是：

- 功能块与数据流边界必须对齐；
- 层次定义必须先于实现与优化。

这对 `PE-Atlas` 的影响是决定性的：

- 我们不能再先找收益对象，再倒推层次；
- 必须先把机器的层次和对象图谱冻结。

来源：

- Tianjic (Nature)  
  https://www.nature.com/articles/s41586-019-1424-8
- A system hierarchy for brain-inspired computing  
  https://www.nature.com/articles/s41586-020-2782-y

---

## 4. `PE-Atlas` 的顶层定义

`PE-Atlas` 把一个 `PE` 正式定义成：

- **一台局部对象化众核机器**

这台机器包含四层 scope、六个 plane、九类对象、八类消息和一个统一 observability contract。

### 4.1 四层 scope

#### `C-scope`

- 单个 core 私有
- 承载 compute、state、acc、register、exact retire
- 不允许 shared plane 直接改变 architectural visibility 顺序

#### `P-scope`

- pod/cluster 级共享
- 承载 metadata object、value residency、owner/join/ready/release
- 是 shared service 的第一责任平面

#### `E-scope`

- 整个 `PE` 范围共享
- 承载 directory、admission、跨 pod 路由、局部同步
- 不做高频细粒度对象服务

#### `N-scope`

- `PE` 外系统层
- 包括 NoC / memory controller / DRAM / off-chip bridge
- 只作为局部机器的外部边界

### 4.2 六个 plane

1. `Event/Data Fabric`
2. `Control/Sync Fabric`
3. `Metadata Object Plane`
4. `Value Residency Plane`
5. `Compute/Commit Plane`
6. `Observability Plane`

---

## 5. 对象模型：哪些东西必须被正式对象化

`PE-Atlas` 要求所有后续研究对象都必须先变成正式 object。

### 5.1 对象族

| 对象族 | 作用域 | 当前状态 | `PE-Atlas` 定位 |
| --- | --- | --- | --- |
| `ActivationBucket` | `P/E` | 概念存在，缺正式对象 | gather/window 内 activation 聚合对象 |
| `PreMphfBase` | `P` | 有观测入口，缺活跃 lifecycle | 最早 metadata 基础对象 |
| `PreMphfBand` | `P` | 有观测入口，缺活跃 lifecycle | metadata band 对象 |
| `Idx2Row` | `P` | 在实验路径上被触碰 | row lookup 对象 |
| `RowIndex` | `P` | 在实验路径上被触碰 | row boundary / rowptr 类对象 |
| `RowDescriptor` | `P` | 唯一活跃 lifecycle seam | descriptor service 对象 |
| `ValueRegion` | `P/E` | 缺正式对象化 | shared line/value residency 对象 |
| `RetireTicket` | `C` | 隐式存在 | core-private exact commit token |
| `SyncBarrier` | `P/E` | 多为隐式条件 | 局部同步与节流对象 |

### 5.2 每个对象必须具备的统一字段

每个 object 至少要具备：

- `object_key`
- `object_kind`
- `scope`
- `owner_core_or_pod`
- `window_seq`
- `consumer_bitmap`
- `materialize_ts`
- `publicize_ts`
- `service_begin_ts`
- `ready_ts`
- `release_ts`
- `reclaim_ts`
- `storage_residency_id`
- `fallback_reason`

没有这些字段，就不允许把一个东西称为“共享对象”。

---

## 6. 生命周期 contract：先闭合，再优化

### 6.1 统一状态机

所有 `P-scope` / `E-scope` 共享对象统一走如下状态机：

1. `Dormant`
2. `Materialized`
3. `Publicized`
4. `OwnerFormed`
5. `JoinedLive`
6. `ServiceActive`
7. `Ready`
8. `Consumed`
9. `Released`
10. `Reclaimed`

允许一条显式私有回退：

- `Materialized -> PrivateOnly -> LocalRetired`

### 6.2 三条硬约束

#### Owner Contract

- 同一时刻一个对象最多只有一个 active owner
- owner 形成必须先于 shared ready/release
- consumer 只能 join，不能静默复制同一 shared work

#### Scope Contract

- `object scope = owner scope = service scope = residency scope`

如果 scope 不一致，就说明这个对象还只是 private proxy，不是 shared object。

#### Commit Contract

- `shared service completion != architectural commit`
- `architectural commit` 只发生在 `C-scope`
- `P/E-scope` 只能改变 ready，可共享 service，不得直接改变 state visibility 顺序

---

## 7. 消息模型：PE 内必须有两张逻辑网络

### 7.1 `Event/Data Fabric`

负责：

- spike / activation event
- bulk metadata/value data movement
- refill / DMA-like transfer

典型消息：

- `ACT_EVENT`
- `META_BULK_FETCH`
- `VALUE_REFILL`
- `DATA_REDIRECT`

### 7.2 `Control/Sync Fabric`

负责：

- owner announce
- join request / response
- ready fanout
- release
- throttle
- redirect
- sync tick

典型消息：

- `OWNER_ANNOUNCE`
- `JOIN_REQ`
- `JOIN_GRANT`
- `JOIN_REJECT`
- `READY_FANOUT`
- `RELEASE_REQ`
- `RELEASE_ACK`
- `OBJECT_REDIRECT`
- `SYNC_TICK`
- `ADMISSION_THROTTLE`

### 7.3 为什么必须双 fabric

因为当前 `PE` 的最大问题之一，就是所有共享语义都试图挤在同一套隐式热路径中：

- 既没有正式的数据面
- 也没有正式的控制面

这会导致：

- router/interface 无法被单独统计；
- shared object 的 lifecycle 与 event 流量缠在一起；
- 最终又回到“局部 helper”而不是“正式微结构”。

---

## 8. 存储模型：从 `WMS private banks` 转向分层对象存储

### 8.1 新存储层次

`PE-Atlas` 建议把 `PE` 内局部存储正式建成四层：

1. `C-local state storage`
   - `state_store.coreX`
   - `accumulator_store.coreX`
   - `register_file.coreX`
2. `P-scope metadata storage`
   - `metadata_object_table`
   - `owner_table`
   - `join_table`
   - `ready_table`
3. `P/E-scope value residency storage`
   - `value_residency_buffer`
   - `refill_queue`
   - `evict_queue`
4. `E-scope directory/admission storage`
   - `object_directory`
   - `admission_budget_table`
   - `sync_state_table`

### 8.2 关键映射问题

下一阶段必须深挖下面这条映射，而不是继续猜测 seam：

- `WMS internal storage model -> PE local storage object model`

也就是要明确：

1. `WMS::idx_sram_model_` 对应哪一层？
2. `WMS::l0_sram_model_` 对应哪一层？
3. `PreMphfBase / PreMphfBand / Idx2Row / RowIndex / RowDescriptor` 到底驻留在哪个 store？
4. 哪些 store 今天只是“以 `PerPe` 名义注册”，运行时却仍由 per-core 代理？

这个问题不厘清，任何 shared storage 优化都会再次漂浮。

---

## 9. 调度与仲裁：从“谁先命中”转向“谁拥有 authority”

### 9.1 不再以收益为第一目标

`PE-Atlas` 的调度器第一目标不是性能，而是：

- 把 authority 定义清楚

也就是：

1. 谁可以 materialize object；
2. 谁可以 publicize object；
3. 谁可以成为 owner；
4. 谁可以发 ready；
5. 谁可以释放 object。

### 9.2 三层仲裁

#### `C-scope local issue gate`

- 只决定 core 是否先走 private path
- 不承担 shared object owner 决策

#### `P-scope owner arbiter`

- 决定 pod 内对象 owner
- 维护 join window 与 ready/release contract

#### `E-scope admission arbiter`

- 决定跨 pod、跨窗口的公平与节流
- 不碰 `C-scope` commit 顺序

### 9.3 不再追求“共享更多”，而是追求“authority 一致”

今后的 shared 机制不再用“多形成几个 cohort / 多留几个 ready lease”定义成败，而用：

- owner 是否唯一
- 生命周期是否闭合
- scope 是否一致
- shared object 是否真正减少 private duplicate work

来定义。

---

## 10. `PE-Atlas` 的 observability contract

### 10.1 旧统计为什么不够

此前的统计大多停在：

- overlap
- export
- join
- ready
- memory requests

这些统计能告诉我们“有无现象”，但不能告诉我们：

- 对象从哪里诞生
- 为什么没有 shared authority
- 生命周期断在哪一段

### 10.2 新统计分四层

#### 对象生命周期统计

- `materialize_total`
- `publicize_total`
- `owner_form_total`
- `join_live_total`
- `service_begin_total`
- `ready_total`
- `release_total`
- `reclaim_total`
- `private_only_total`
- `fallback_private_total`

#### fabric 统计

- `event_flits_total`
- `control_msgs_total`
- `avg_hops`
- `arb_wait_cycles`
- `queue_occupancy_peak`
- `backpressure_cycles`
- `multicast_span`

#### 存储统计

- `metadata_bank_conflict_total`
- `value_residency_lifetime_cycles`
- `refill_reason_*`
- `evict_reason_*`
- `local_vs_remote_access_total`

#### 正确性统计

- `ready_without_owner_total`
- `owner_without_release_total`
- `duplicate_owner_total`
- `late_join_after_release_total`
- `materialized_but_zero_consumer_total`
- `ready_but_zero_waiter_total`

### 10.3 三个新的总指标

- `lifecycle_closure_ratio = release_total / materialize_total`
- `publicization_yield = owner_form_total / materialize_total`
- `shared_usefulness = objects_with_consumer_gt_1 / owner_form_total`

后续任何 actual 优化都必须同时报告：

- 性能收益
- 生命周期闭合程度
- correctness overhead

---

## 11. 分阶段实现路线

### Phase A0：架构图谱冻结

只做：

- 对象图
- 消息图
- 存储图
- 生命周期图
- scope 图

不改行为。

### Phase A1：materialize probe

把探针从今天的：

- `txn export / owner / join-ready`

前移到：

- `materialize / publicize`

目标是区分：

1. `never materialized`
2. `materialized but private-only`
3. `materialized and publicized`
4. `publicized and owner-formed`

### Phase A2：shadow object machine

新增 shadow lifecycle table，不改真实行为：

- 后台只维护对象状态机与消息面统计；
- 不触碰现有 service/retire contract。

### Phase B1：第一个 actual object plane

从 `A1/A2` 数据里挑出 **第一个生命周期闭合** 的对象族，优先 actualize：

- 不预设一定是 `rowdescriptor`
- 不预设一定是 `idx2 / rowidx`

### Phase B2：value residency plane

在对象 authority 稳定后，再把 value residency 正式对象化。

### Phase C：commit/domain 级优化

只有当前两层都收干净后，才讨论：

- domain-local retire
- cross-core commit interaction

在此之前，不再把 retire 改造当成当前主任务。

---

## 12. 论文主张与创新边界

`PE-Atlas` 的论文主张不应再是：

- “我们发现了一条更早的 metadata seam”

而应收敛成：

- **我们提出了一种面向 `PE` 内部的 object-scoped manycore machine，把对象边界、局部互连、局部存储、同步控制与 exact commit 边界统一到一个正式架构模型中。**

它的创新不在单一优化点，而在：

1. 把 `PE` 内部正式建模成局部众核机器；
2. 把 shared object 从“语义现象”提升为“生命周期闭合的架构对象”；
3. 把 event/data 与 control/sync 两张逻辑网络显式分离；
4. 把 observability 从收益指标扩展到对象生命周期与 authority contract。

---

## 13. 非目标与边界

这份设计明确 **不** 立即做以下事情：

1. 不承诺短期内一定获得性能正收益；
2. 不立即重写 `per-core exact retire`；
3. 不假定现有所有 `PerPe` 对象都已经具备活跃生命周期；
4. 不继续围绕 `TTL / mask / threshold` 做参数扫描；
5. 不把 `rowdescriptor` 等同于整个 `PE` 内部架构。

---

## 14. 立即执行的三个任务

### Task 1：做 `PE-Atlas object census`

目标：

- 为每个对象族回答：
  - `materialize point`
  - `publicize point`
  - `owner point`
  - `ready point`
  - `release point`
  - `fallback point`

### Task 2：补第一批架构统计

优先加：

- `materialize_total`
- `publicize_total`
- `private_only_total`
- `owner_form_total`
- `ready_total`
- `release_total`
- `control_msgs_total`
- `event_flits_total`

### Task 3：做“架构认知实验”，不是收益实验

新的 `mainexp` 不再以 `memory_requests` 为第一输出，而是回答：

1. 哪些对象真实存在完整生命周期？
2. 哪些对象只在 private path 中存在？
3. 哪些对象具备跨 core shared authority？
4. 哪些互连和队列在当前 `PE` 中才是真 bottleneck？

---

## 15. 与旧路线的关系

`PULSE`、`rowdescriptor ready-join`、`metadata txn` 这些工作不作废，但从现在开始应当统一降级为：

- **`PE-Atlas` 之下的局部历史分支与局部对象实验**

它们仍有两个价值：

1. 提供负结果与约束；
2. 提供第一条已活跃 lifecycle 的 `rowdescriptor` 基线。

但它们不再继续充当 `PE` 内部架构的主叙事。

---

## 16. 参考启发

1. Intel Labs. *Single-chip Cloud Computer Overview Paper*.  
   https://www.intel.cn/content/dam/www/public/us/en/documents/technology-briefs/intel-labs-single-chip-cloud-overview-paper.pdf
2. Intel Labs. *Taking Neuromorphic Computing to the Next Level with Loihi 2 Technology Brief*.  
   https://www.intel.com/content/www/us/en/research/neuromorphic-computing-loihi-2-technology-brief.html
3. Pei et al. *Towards artificial general intelligence with hybrid Tianjic chip architecture*. Nature 2019.  
   https://www.nature.com/articles/s41586-019-1424-8
4. Zhang et al. *A system hierarchy for brain-inspired computing*. Nature 2020.  
   https://www.nature.com/articles/s41586-020-2782-y
5. Bell et al. *TILE64 Processor: A 64-Core SoC with Mesh Interconnect*. ISSCC 2008.  
   https://www.princeton.edu/~wentzlaf/documents/Bell.2008.ISSCC.Tilera.pdf
6. Adapteva. *Epiphany Architecture Reference*.  
   https://www.adapteva.com/docs/epiphany_arch_ref.pdf
7. Kalray. *MPPA Technology Overview*.  
   https://www.kalrayinc.com/products/mppa-technology/
8. De Dinechin et al. *A Distributed Run-Time Environment for the Kalray MPPA-256 Integrated Manycore Processor*. 2013.  
   https://www.sciencedirect.com/science/article/pii/S1877050913004766
9. Su et al. *Core interface optimization for multi-core neuromorphic processors*. 2023.  
   https://arxiv.org/abs/2308.04171
