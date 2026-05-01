# PE-Atlas v2：面向 SnnDL 风格多核 PE 的对象化众核机器正式设计稿（2026-03-31）

> 日期：2026-03-31  
> 状态：architecture design v2  
> 设计定位：`architecture-first + machine-model-first + paper-first`  
> 继承关系：在 [2026-03-30-pe-atlas-manycore-object-machine-design.md](./2026-03-30-pe-atlas-manycore-object-machine-design.md) 基础上重写并扩展，吸收近期 `PULSE` / `metadata frontier` / `rowdescriptor` runtime 证据，以及神经形态芯片与通用众核架构启发。  
> 工作名：`PE-Atlas` = `PE-internal Object-Scoped Manycore Machine`

---

## 0. 一句话结论

下一阶段不再把 `PE` 内部研究写成：

- 针对既有 baseline 的收益 patch；

而是正式改写成：

- **先定义 `PE` 这台局部机器，再从已经具备完整生命周期的对象中选择优化对象。**

`PE-Atlas v2` 的核心主张是：

1. 当前代码中的 `PE` 还不是一台真正的 shared execution machine；
2. 它本质上仍是：
   - `per-core private execution + PE-scoped shared helpers/providers`
3. 继续围绕 `TTL / mask / threshold / ready-lease` 这类参数做收益扫描，只会在局部 seam 上反复试错；
4. 正确的下一步，是先把 `PE` 的：
   - 对象图
   - 消息图
   - 存储图
   - 生命周期图
   - 统计图
   统一冻结成一台正式机器。

这份设计稿的目的不是立刻拿到正收益，而是：

- **第一次把 `PE` 内部 core 间通信、局部存储、共享对象、控制同步、exact commit 边界，统一建模成一个可实现、可观测、可验证的局部众核机器。**

---

## 1. 为什么必须彻底换轨

### 1.1 旧路线并不是错误，而是阶段完成

此前围绕下面几条线的探索：

- `shared ingress`
- `idx2`
- `apply-stage preband`
- `gather-preband`
- `rowdescriptor ready-join`
- `metadata txn`

已经完成了它们应有的历史任务：

1. 证明 `PE` 内 overlap 真实存在；
2. 证明 `exact retire` 不是唯一障碍；
3. 证明很多“直觉上可能有效”的 seam，在当前 runtime 下根本不是正式对象；
4. 把一批错误方向排得很干净。

因此现在路线切换，不是因为旧路线“没有价值”，而是因为：

- **它已经足够完成“负结果筛选器”的职责。**

### 1.2 旧路线为什么会反复兜圈

核心原因不在实现细节，而在研究对象定义本身：

1. 我们一直在问：
   - 哪个 seam 更可能先出收益？
2. 但没有先问：
   - 这条 seam 在 today runtime 中是不是正式对象？
   - 它有没有 owner？
   - 有没有 ready？
   - 有没有 release？
   - 有没有作用域一致的存储与控制路径？

结果就是：

- 统计越来越多；
- `rowdescriptor` 越来越清楚；
- 但 `PE` 本身的机器模型没有变清楚；
- 所以收益实验只能围着局部 seam 打转。

### 1.3 这次换轨后的研究问题

从这一稿开始，我们不再把问题写成：

- “还能不能在 baseline 上找到一个更早、更共享、更有效的收益 seam？”

而是改写为：

- **“一个 SnnDL 风格多核 `PE` 的内部机器模型，到底应当如何被正式建模？”**

这意味着下一阶段第一优先级是：

1. 建模；
2. 观测；
3. 对象化；
4. 然后才是优化。

---

## 2. 当前基线：today 的 PE 到底是什么

本节只描述 **今天代码中真实存在且已进入热路径的模型**，不混入目标态。

### 2.1 today 的一句话定义

today 的 `PE` 内部基线可以收敛为：

- **`per-core private execution` on top of `PE-scoped shared helpers`**

也就是：

1. 真正推进 `issue -> service -> ready -> retire` 的主体，仍是每个 core 私有的 `WeightMemorySubsystem`；
2. `PE` 级结构如：
   - `OptimizedInternalRing`
   - `PeDmaScheduler`
   - `LocalStorageHierarchyController`
   - `PeSharedCoreFabric`
   已经存在；
3. 但这些结构今天大多还处于：
   - transport
   - provider
   - registry
   - observe
   这些角色。

### 2.2 today 的真实热路径

当前热路径更准确地写成：

- `core -> SnnWorkload -> WeightMemorySubsystem -> StandardMemAccess`

也就是：

1. `SnnPESubComponent` 负责 runtime 绑定；
2. `SnnWorkload` 驱动 per-core execution；
3. `WeightMemorySubsystem` 是今天真正的 service kernel；
4. memory backend 默认还是 `StandardMemAccess`；
5. `PE` 级 DMA / shared issue backend 还没有接管主 issue authority。

### 2.3 today 的对象-运行时断层

代码层已经能看到不少“名义上共享”的对象或对象名：

- `activation_ingress_store`
- `weight_idx_store`
- `weight_value_store`
- `PreMphfBase`
- `PreMphfBand`
- `Idx2Row`
- `RowIndex`
- `RowDescriptor`

但真实 runtime 中，只有很少一部分对象具备完整 lifecycle。

截至目前，我们能最硬地确认的事实是：

1. `rowdescriptor` 是唯一已接通 `owner -> join_live -> join_ready -> ready/release` 生命周期的活跃 seam；
2. `PreMphfBase / PreMphfBand / Idx2Row / RowIndex` 目前只有：
   - 对象名
   - 某些观测入口
   - 某些实验性触发点
   但还不是 today mainline 中活跃的 shared object lifecycle。

### 2.4 当前 fresh runtime 结论

最近一轮 fresh `mainexp` 已经把这个事实压得很实：

- `rowdescriptor-only` 与 `all-mask` 结果完全同构；
- `rowidx / idx2 / preband` 全部为零；
- 更早四层 metadata frontier：
  - `premphf_base`
  - `premphf_band`
  - `idx2row`
  - `rowindex`
  的 `observed / owner-form / join-ready` 也全部为零。

这说明：

- 问题不是“更早 metadata 被观察到了，但没成功 join-ready”；
- 而是 **today mainline runtime 根本没有把这些对象物化成 active shared lifecycle seam。**

### 2.5 A0 实测修正：today 不是“很多对象没 ready”，而是“很多对象还不是对象”

第一轮 `PE-Atlas object census` 把今天的候选对象更准确地压成了四类：

- `registered-but-proxied`
- `shadow-only`
- `missing`
- `active`（本轮没有发现真正意义上的 formal active object family）

冻结后的 today 结论是：

- `ActivationBucket`：`registered-but-proxied`
- `PreMphfBase`：`registered-but-proxied`
- `PreMphfBand`：`missing`
- `Idx2Row`：`registered-but-proxied`
- `RowIndex`：`shadow-only`
- `RowDescriptor`：`registered-but-proxied`
- `ValueRegion`：`registered-but-proxied`
- `RetireTicket`：`registered-but-proxied`
- `SyncBarrier`：`registered-but-proxied`

这组结论把路线判断明显改写了：

1. today 的主问题不是“对象 ready 不起来”；
2. 而是“对象 authority 还没有从 proxy/helper/private contract 中分离出来”；
3. 所以第一阶段的核心任务必须是：
   - census
   - proxy mapping
   - probe plane
   而不是继续做收益 sweep。

这不是一组“按概念猜”的分类，而是按 today runtime call-site 压出来的结论：

- 真正能看到 `materialize/owner/ready/release` 热路径的对象，今天大多仍然挂在 proxy/helper 宿主上；
- `RowIndex` 虽然已经有 shadow table 和 helper machinery，但热路径 authority 还不在 formal object-plane；
- `PreMphfBand` 则连可持续的对象入口都还没有。

下面 6.4 节把这组 `A0 census` 的具体 runtime 依据冻结成表，作为后续 `A1/A2` probe 设计的事实基线。

---

## 3. 外部架构启发：为什么 `PE` 必须被当作一台机器来建模

这一节不做 related-work survey，只提炼对 `PE-internal machine model` 真正有约束力的架构原则。

### 3.1 原则 A：`message passing first`，不要默认隐式共享

来自 Intel SCC、Kalray MPPA、Epiphany 这类 manycore 的最强启发是：

- 多核局部机器不应假定隐式全局共享是一等公民；
- 真正可扩展、可验证的组织方式往往是：
  - 本地存储
  - 显式消息
  - 局部目录
  - 分层仲裁

对我们意味着：

- `PE` 内共享对象不能依赖“大家都知道它在那儿”；
- 它必须依赖：
  - 显式 `owner`
  - 显式 `announce/join/ready/release`
  - 显式作用域。

### 3.2 原则 B：必须有 `cluster/pod` 中间层

从 MPPA、manycore cluster、以及神经形态芯片的 router hierarchy 都能看到同一个事实：

- 不能只有 `per-core` 和 `per-chip` 两层；
- 必须有一个中间层来承载：
  - 局部对象共享
  - 局部同步
  - 局部仲裁
  - 局部存储驻留

对我们来说，这个中间层就是：

- **`P-scope` = pod/cluster scope**

没有这一层，设计会在两种坏结果之间摆动：

1. 退化回 per-core private proxy；
2. 爆炸成全 PE 中心化 scoreboard。

### 3.3 原则 C：`router / interface / control path` 本身就是微结构主角

SNN 与 manycore 都给出了一致信号：

- 真正的瓶颈不只在计算，不只在 SRAM；
- `router`
- `arbiter`
- `control queue`
- `routing memory`
- `directory`
- `synchronization interface`
  本身就是正式微结构。

这对我们是一个关键提醒：

- 不能再把 `PE` 内部控制面当作“实现细节”；
- 它必须被写成正式 plane。

### 3.4 原则 D：`data fabric` 与 `control/sync fabric` 必须分离

Loihi 2、MPPA、SCC、很多 tile-based manycore 都在不同程度上体现出同一个方向：

- 数据传输与控制/同步传输不应完全混在同一条逻辑网中；
- 否则：
  - 可观测性变差
  - 仲裁压力难隔离
  - 延迟与拥塞来源混杂
  - 对象生命周期事件无法独立分析

所以 `PE-Atlas v2` 明确要求：

- `event/data fabric`
- `control/sync fabric`

至少在逻辑上是两张网。

### 3.5 原则 E：对象边界必须和数据流边界对齐

Tianjic、TrueNorth、Loihi 一类架构给我们的真正启发不是“规模”，而是：

- 功能块划分必须和数据流边界对齐；
- 否则对象名义作用域与运行时 owner 会断裂。

对我们来说，这意味着：

- `Activation`
- `Metadata`
- `Value`
- `Sync`
- `Commit`

必须是不同 object family，而不是都塞进一条 `WMS hot path` 里靠代码分支暗中维持。

### 3.6 原则 F：先有 hierarchy，再谈优化

这是本稿最重要的外部启发：

- 架构层次必须先于优化目标冻结；
- 否则优化对象会漂浮，实验就会永远围着 seam 打转。

也就是说：

- `PE-Atlas` 不是“新的 patch 框架”；
- 它首先是一份 **hierarchy contract**。

---

## 4. `PE-Atlas v2` 的顶层定义

`PE-Atlas v2` 把一个 `PE` 正式定义为：

- **一台局部对象化众核机器**

这台机器由：

1. 四层 scope
2. 六个 plane
3. 一套正式对象谱系
4. 一套正式消息谱系
5. 一套统一 lifecycle contract
6. 一套 machine-visibility-first observability contract

共同构成。

### 4.1 四层 scope

#### `C-scope`：core-private scope

职责：

- compute
- state update
- accumulator
- register file
- exact retire
- wake/consume queue

原则：

- 只在这里发生 architectural visibility；
- shared service 不能直接改写其 commit 顺序。

#### `P-scope`：pod / cluster scope

职责：

- metadata object lifecycle
- owner / join / ready / release
- pod-local value residency
- pod-local control arbitration

原则：

- 是 shared object/service 的第一责任平面；
- 是下一阶段最重要的创新落点。

#### `E-scope`：PE-global scope

职责：

- cross-pod routing
- coarse directory
- admission / fairness
- local sync coordination
- ingress demux

原则：

- 不承担高频细粒度对象服务；
- 只负责准入、重定向、边界同步和运输。

#### `N-scope`：system / network scope

职责：

- NoC
- memory controller
- DRAM / off-chip bridge
- chip-to-chip

原则：

- 作为 `PE` 的外边界，不与 `PE-internal contract` 混写。

### 4.2 六个 plane

1. `Event/Data Fabric`
2. `Control/Sync Fabric`
3. `Metadata Object Plane`
4. `Value Residency Plane`
5. `Compute/Commit Plane`
6. `Observability Plane`

### 4.3 顶层机器图

```text
PE-Atlas Machine
|
|-- E-scope
|   |-- Activation Ingress / Directory / Admission / Cross-Pod Routing
|   |-- Event/Data Fabric
|   `-- Control/Sync Fabric
|
|-- P-scope (Pod 0..K-1)
|   |-- Metadata Object Plane
|   |-- Owner / Join / Ready / Release Tables
|   |-- Pod Value Residency Plane
|   `-- Pod Local Service Controller
|
`-- C-scope (Core 0..M-1)
    |-- Compute Pipe
    |-- State / Acc / RF
    |-- Wake Queue
    `-- Exact Retire Queue
```

---

## 5. 代码映射：today 组件与 `PE-Atlas` 目标态的关系

这一节是本稿和旧稿最不同的部分：不只讲理想结构，也明确今天代码里每个组件在机器中的位置。

| today 组件 | today 角色 | `PE-Atlas` 角色定位 | 问题 |
| --- | --- | --- | --- |
| `MultiCorePE` | PE shell | `E-scope shell + topology root` | today 更多是装配器，不是 authority holder |
| `SnnPESubComponent` | per-core runtime binder | `C-scope runtime front-end` | 仍以 per-core execution 为主 |
| `SnnWorkload` | per-core execution driver | `C-scope issue driver` | 仍默认绑定私有 memory path |
| `WeightMemorySubsystem` | today 热路径核心 | 暂时兼任 `C-scope service kernel` + 局部 object hooks | today 权限过重，混合了 issue/service/retire/experiment |
| `OptimizedInternalRing` | packet transport | `Event/Data Fabric` 雏形 | today 主用 packet plane，控制语义未正式化 |
| `PeSharedCoreFabric` | ingress / harbor / observe | `Control/Sync Fabric` 雏形 | control messages 有萌芽，但仍非正式中心 |
| `LocalStorageHierarchyController` | object namespace / registry | storage namespace root | 名义对象很多，运行时映射不闭合 |
| `PeLocalServiceObjectTable` | 局部 lifecycle shadow table | `P-scope owner/join/ready/release table` 雏形 | 已有重要骨架，但还只活在局部 seam |
| `PeDmaScheduler` | shared backend skeleton | 未来 `E/P-scope` data movement backend | 还未接管主路径 issue |

从这个映射可以直接看出：

- today 的问题不是“没有这些结构”；
- 而是 **这些结构还没有在同一台机器里拥有清晰 authority。**

---

## 6. 对象谱系：哪些东西必须被正式对象化

从 v2 开始，任何后续优化对象都必须先进入这张对象谱系表，否则不允许把它称作“架构对象”。

### 6.1 对象族总表

| 对象族 | 目标 scope | today 状态 | today 证据 | v2 定位 |
| --- | --- | --- | --- | --- |
| `ActivationBucket` | `P/E` | `registered-but-proxied` | today 实体是 `GatherHarborBucket`，由 harbor / shared-core fabric 代理 materialize 与 release | activation 聚合与导出对象 |
| `PreMphfBase` | `P` | `registered-but-proxied` | today 主活路径是 shared pre-base lookup registry，不是 formal metadata object lifecycle | 最早 metadata 基础对象 |
| `PreMphfBand` | `P` | `missing` | 目前只停在 enum/mask/tests，主热路径没有 materialize / owner / ready | metadata band 对象，仍是第一优先级候选 |
| `Idx2Row` | `P` | `registered-but-proxied` | today 实体是本地 `gcss_idx2_index_` lookup registry，而非正式 shared object | row lookup 对象 |
| `RowIndex` | `P` | `shadow-only` | observe/materialize helper 已有，但 mainline owner/ready/release 未真正接通 | row boundary / rowptr 对象 |
| `RowDescriptor` | `P` | `registered-but-proxied` | 活跃 seam 实际落在 `PulseActivationDescriptor` / harbor descriptor proxy，不是 formal `MetadataKind::RowDescriptor` authority | descriptor service 对象 |
| `ValueRegion` | `P/E` | `registered-but-proxied` | today 由 `PulseSharedLineService + PulseSeededLineResidency` 代理 shared line/value residency | value residency 对象 |
| `RetireTicket` | `C` | `registered-but-proxied` | today 由 `edge_retire_ + seq + next_retire_seq_` 隐式承载 exact retire token | exact commit token |
| `SyncBarrier` | `P/E` | `registered-but-proxied` | today 由 `GasStepBarrierEvent + GlobalGasStepController` 代理 barrier object | 局部同步与节流对象 |

### 6.2 每个对象必须具备的正式字段

从 v2 开始，一个对象要被承认为正式 shared object，至少需要具备下面字段：

- `object_key`
- `object_kind`
- `scope`
- `owner_id`
- `window_seq`
- `producer_id`
- `consumer_bitmap`
- `materialize_ts`
- `publicize_ts`
- `owner_form_ts`
- `service_begin_ts`
- `ready_ts`
- `release_ts`
- `reclaim_ts`
- `storage_residency_id`
- `fallback_reason`

如果缺失这些字段中的大多数，那么它更准确的身份应当是：

- probe artifact
- private proxy
- helper-local temporary

而不是正式对象。

### 6.3 三种 today 常见假对象

本稿特别要排除三类“看起来像对象，实际上不是”的情况：

#### 假对象 A：只有统计名，没有 lifecycle

这类对象可以被看见，但：

- 没 owner
- 没 ready
- 没 release

所以仍不是架构对象。

#### 假对象 B：只有 registry 名，没有 runtime authority

例如：

- 名义上注册为 `PerPe`
- 实际上仍由每个 core 的 `WMS` 私有代理在使用

这种情况必须被标成：

- `registered-but-proxied`

#### 假对象 C：只有 shadow table，没有 active mainline call site

如果 table 在，但主路径永远不调用它，那仍不是 today machine 的一部分，只能算：

- `shadow-only machinery`

### 6.4 A0 `object census` 第一轮收口（2026-03-31）

截至本稿，`PE-Atlas object census` 的第一轮判定已经可以冻结成下面这张 today matrix：

| object | A0 判定 | today 真实载体 | 关键结论 |
| --- | --- | --- | --- |
| `ActivationBucket` | `registered-but-proxied` | `GatherHarborBucket` | activation 入口已经有共享聚合影子，但还不是正式 object authority |
| `PreMphfBase` | `registered-but-proxied` | pre-base lookup registry | 处于“注册存在、生命周期未对象化”的典型状态 |
| `PreMphfBand` | `missing` | 无 | 今天没有可落地的 active object path，不能直接拿去做收益实验 |
| `Idx2Row` | `registered-but-proxied` | `gcss_idx2_index_` | lookup 有，但不是 shared lifecycle |
| `RowIndex` | `shadow-only` | row-index helper / shadow table | 是最典型的“有结构、无热路径 authority”对象 |
| `RowDescriptor` | `registered-but-proxied` | `PulseActivationDescriptor` proxy | today 唯一接近完整 lifecycle 的 seam 仍然是 descriptor proxy，而不是 formal object kind |
| `ValueRegion` | `registered-but-proxied` | `PulseSharedLineService + PulseSeededLineResidency` | shared residency 已经出现，但还停留在代理层 |
| `RetireTicket` | `registered-but-proxied` | `edge_retire_ + seq` | exactness token 真实存在，但仍隐式埋在 per-core retire contract 中 |
| `SyncBarrier` | `registered-but-proxied` | `GasStepBarrierEvent + GlobalGasStepController` | barrier 有 authority holder，但不是以 object-plane 形式出现 |

这张表带来三个直接结论：

1. `today PE` 中几乎没有“已经正式对象化”的 shared object；
2. `rowdescriptor` 虽然是最活跃 seam，但本质上仍是 proxy-lifecycle，而不是 object-plane authority；
3. 下一阶段真正该做的不是继续扫 `preband / idx2 / rowidx` 参数，而是把这些对象先从 `registered-but-proxied / shadow-only / missing` 推进到 formal lifecycle。

这同时给出了 today 的 proxy mapping：

- `ActivationBucket -> GatherHarborBucket`
- `PreMphfBase -> shared pre-base lookup registry`
- `Idx2Row -> gcss_idx2_index_`
- `RowDescriptor -> PulseActivationDescriptor / harbor descriptor proxy`
- `ValueRegion -> PulseSharedLineService + PulseSeededLineResidency`
- `RetireTicket -> edge_retire_ + seq + next_retire_seq_`
- `SyncBarrier -> GasStepBarrierEvent + GlobalGasStepController`

#### 6.4.1 today runtime evidence table

下面这张表把第一轮 `A0 census` 的判定和 today 代码热路径一一对齐。重点不是“哪里有一个结构体名字”，而是：

- 是否真有 `materialize / owner / ready / release` 的热路径；
- 这些热路径到底落在 formal object-plane，还是落在 proxy/helper/private contract；
- 因而它应该被算作 `registered-but-proxied`、`shadow-only` 还是 `missing`。

| object | today runtime evidence | 为什么不是 `active` |
| --- | --- | --- |
| `ActivationBucket` | `components/MultiCorePE.cc:5464` 与 `services/pe_fabric/PeSharedCoreFabric.cc:371-372` 能看到 bucket materialize/owner；`components/MultiCorePE.cc:4705` 与 `services/pe_fabric/PeSharedCoreFabric.cc:164` 能看到 release | 生命周期挂在 `GatherHarborBucket` 上，shared ingress 已存在，但还不是 formal object authority |
| `PreMphfBase` | `services/synapse/weights/WeightMemorySubsystem.cc:1513`、`PulseMetadataLookupRegistry.h:87` 建 registry；`WeightMemorySubsystem.cc:2457`、`PulseMetadataLookupRegistry.h:110` 做 release | 这是注册表/lookup contract，不是统一 object lifecycle plane |
| `PreMphfBand` | `WeightMemorySubsystem.cc:2583`、`WeightMemorySubsystem.cc:2591` 仍是空路径/未接通入口 | 连稳定的 object materialize seam 都没有，所以只能判 `missing` |
| `Idx2Row` | `WeightMemorySubsystem.cc:1407`、`:1424` 有 materialize/observe；`:1447` 有 ready helper | 仍是 lookup/helper seam，不是可 join/release 的 shared object |
| `RowIndex` | `WeightMemorySubsystem.cc:730`、`:2019`、`:2050`、`:2056` 显示 shadow table 与 owner/observe helper；`:2248`、`:2308` 只有 helper-ready/release | 结构存在，但 authority 不在热路径 object-plane，只能算 `shadow-only` |
| `RowDescriptor` | `components/MultiCorePE.cc:5464` 与 `services/pe_fabric/PeSharedCoreFabric.cc:135` materialize；`:181`、`:349` ready；`:189` release | 是 today 最活跃的 seam，但本质仍是 descriptor proxy，不是 formal object kind |
| `ValueRegion` | `WeightMemorySubsystem.cc:1595`、`:2371`、`:2378`、`:2383` 与 `:3952`、`:3966` 显示 shared line service + seeded residency 的全套代理路径 | `residency/service` 已经共享，但 namespace/authority 仍埋在代理层 |
| `RetireTicket` | `WeightMemorySubsystem.cc:2615`，以及 `WeightMemorySubsystem.h:2867`、`:2917`、`:3120`、`:3354` 暴露 `edge_retire_ + seq + next_retire_seq_` contract | exactness token 存在，但仍隐含在 per-core retire contract 中，没有独立 object-plane |
| `SyncBarrier` | `components/MultiCorePE.cc:1160` 与 `components/gas/GlobalGasStepController.cc:223`、`:226`、`:296`、`:305`、`:315`、`:358` 构成 barrier announce/observe/release 路径 | 有 authority holder，但 today 仍是 controller/event contract，而不是 PE-local object family |

这张 evidence table 的意义，是把之前“看起来像对象”的候选，进一步压成三种不同工程状态：

- `registered-but-proxied`
  说明热路径已经存在，但 authority 还寄生在 proxy 或 registry 上；
- `shadow-only`
  说明结构和 helper 已经有了，但 mainline service/commit 热路径还没有真正穿过去；
- `missing`
  说明今天不该直接拿它做收益 sweep，因为连最基本的 object seam 都还没成立。

所以接下来的 `A1/A2` 工作不该再问“哪个参数更赚钱”，而该先问：

1. 哪些 proxy activity 值得被晋升成 formal object lifecycle；
2. 哪些 shadow table 需要补 owner/ready/release probe；
3. 哪些候选对象今天其实只是命名上的 object，而不是机器里的 object。

---

## 7. 生命周期合同：先闭合，再优化

### 7.1 统一状态机

所有 `P-scope` / `E-scope` 对象统一走下面的生命周期：

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

同时允许一条显式私有回退支路：

- `Materialized -> PrivateOnly -> LocalRetired`

### 7.2 三条硬合同

#### `Owner Contract`

- 同一时刻同一对象至多一个 active owner；
- consumer 只能 join 已有 owner，不能静默复制同一 shared work；
- owner 必须是可观测、可释放的正式身份。

#### `Scope Contract`

- `object scope = owner scope = service scope = residency scope`

如果 scope 不一致，就说明这个对象还只是 private proxy，不是正式 shared object。

#### `Commit Contract`

- `shared service completion != architectural commit`
- shared plane 只能推进 `ready`
- `architectural visibility` 只在 `C-scope` 发生

这是 v2 明确保留的 correctness 锚点。

### 7.3 这三条合同为什么重要

它们分别切开了过去最容易混淆的三件事：

1. “谁真正拥有 authority”
2. “这个对象到底属于哪一层”
3. “共享服务与精确提交的边界”

只要这三件事不写成合同，后续任何局部优化最终都会再次漂浮。

---

## 8. 消息谱系：PE 内必须存在两张逻辑网络

### 8.1 `Event/Data Fabric`

职责：

- spike / activation event 运输
- bulk metadata/value movement
- refill / DMA-like data transport
- object payload redirect

典型消息：

- `ACT_EVENT`
- `META_FETCH`
- `VALUE_REFILL`
- `PAYLOAD_REDIRECT`
- `DATA_EVICT`

### 8.2 `Control/Sync Fabric`

职责：

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

### 8.3 为什么必须分成两张逻辑网

因为 today 的 shared semantics 最大的问题之一，就是：

- event/data
- owner/join
- ready/release
- barrier/sync

这些动作全都挤在热路径里，缺乏逻辑分面。

其后果是：

1. 无法独立统计控制开销；
2. 无法区分数据拥塞和控制拥塞；
3. 无法把 router/interface 视为正式瓶颈；
4. 无法回答对象到底死在哪个 plane。

### 8.4 v2 对 today 代码的直接要求

即便短期内不引入两套真实物理网络，至少也要做到：

1. 在逻辑统计与消息类型上区分两张网；
2. 控制消息必须有正式 message kind；
3. control queue / control latency / control drops 必须有单独统计。

---

## 9. 存储模型：从私有 bank 混合体到正式对象层次

### 9.1 新的四层局部存储层次

`PE-Atlas v2` 建议把 `PE` 内部局部存储正式冻结为四层：

#### L0：`C-local state/compute storage`

- `state_store.coreX`
- `accumulator_store.coreX`
- `register_file.coreX`
- `wake_queue.coreX`
- `retire_queue.coreX`

#### L1：`P-scope metadata object storage`

- `metadata_object_table`
- `owner_table`
- `join_table`
- `ready_table`
- `release_table`

#### L2：`P/E-scope value residency storage`

- `value_residency_buffer`
- `refill_queue`
- `evict_queue`
- `value_directory`

#### L3：`E-scope directory/admission/sync storage`

- `object_directory`
- `admission_budget_table`
- `sync_state_table`
- `redirect_table`

### 9.2 当前最需要回答的映射问题

下一阶段不应继续猜 seam，而应直接回答：

- `WMS internal storage model -> PE local storage object model`

具体要回答：

1. `WMS::idx_sram_model_` 今天到底对应哪一层？
2. `WMS::l0_sram_model_` 今天到底对应哪一层？
3. `PreMphfBase / PreMphfBand / Idx2Row / RowIndex / RowDescriptor` 各自驻留在哪个层次？
4. 哪些 today `PerPe` 对象只是在命名空间中是共享的，运行时仍是 per-core proxy？

### 9.3 v2 的一个关键判断

在这个问题没有澄清之前：

- shared storage optimization
- shared residency optimization
- value plane optimization

都不应被当作主线，因为我们还不知道优化对象是否真的存在于正确层次。

---

## 10. 仲裁模型：从“谁先命中”转向“谁拥有 authority”

### 10.1 v2 的调度目标

这次调度器的第一目标不是性能，而是：

- **authority consistency**

也就是回答：

1. 谁能 materialize object；
2. 谁能 publicize object；
3. 谁能 owner-form；
4. 谁能发 ready；
5. 谁能 release；
6. 谁能 redirect / throttle。

### 10.2 三层仲裁

#### `C-scope local issue gate`

职责：

- 判断本 core 是否走 private path
- 判断是否具备 join 请求条件

不承担：

- shared owner 决策

#### `P-scope owner arbiter`

职责：

- object owner 分配
- join window 管理
- ready/release 合同维护

这是 v2 的第一个真实创新落点。

#### `E-scope admission arbiter`

职责：

- cross-pod redirect
- coarse fairness
- congestion / throttle
- local sync governance

不碰：

- `C-scope` commit 顺序

### 10.3 这比“共享更多”更重要

今后 shared 机制的成败不再由：

- 多形成几个 cohort
- 多缓存几个 lease
- 多少几次 request

来定义第一结论，而由：

- owner 是否唯一
- lifecycle 是否闭合
- scope 是否一致
- private duplicate work 是否真正被 authority 取代

来定义。

---

## 11. `PE-Atlas` 的 observability contract

### 11.1 为什么旧统计体系不够

此前统计更像：

- overlap statistics
- usefulness statistics
- speedup / regression statistics

这些统计并没有直接回答：

- 对象有没有形成？
- 生命周期闭合了没有？
- 死在哪个 plane？
- 死在 private proxy 还是 shared authority 之前？

### 11.2 新统计的设计目标

从 v2 开始，统计的第一目标不是收益，而是：

- **让这台机器变得可见。**

### 11.3 统计分层

#### A. Object Census 统计

回答“对象有没有存在过”：

- `atlas_obj_materialize_total`
- `atlas_obj_publicize_total`
- `atlas_obj_private_only_total`
- `atlas_obj_reclaim_total`

#### B. Authority 统计

回答“shared authority 有没有真正形成”：

- `atlas_owner_lookup_total`
- `atlas_owner_form_total`
- `atlas_owner_hit_total`
- `atlas_owner_reject_total`
- `atlas_join_req_total`
- `atlas_join_grant_total`
- `atlas_join_reject_total`

#### C. Lifecycle 统计

回答“闭环到哪一步”：

- `atlas_service_begin_total`
- `atlas_ready_transition_total`
- `atlas_release_total`
- `atlas_reclaim_total`
- `atlas_ready_to_release_cycles`

#### D. Storage 统计

回答“对象到底住在哪儿、卡在哪儿”：

- `atlas_store_alloc_total`
- `atlas_store_hit_total`
- `atlas_store_evict_total`
- `atlas_store_bank_conflict_total`
- `atlas_store_queue_occ_peak`

#### E. Fabric 统计

回答“event/data 与 control/sync 分别怎么拥塞”：

- `atlas_event_flits_total`
- `atlas_control_msgs_total`
- `atlas_control_queue_occ_peak`
- `atlas_control_latency_cycles`
- `atlas_redirect_total`

#### F. Commit/Sync 统计

回答“是不是 commit 或 sync 在卡”：

- `atlas_sync_barrier_enter_total`
- `atlas_sync_barrier_hold_cycles`
- `atlas_commit_block_cycles`
- `atlas_ready_visible_but_commit_blocked_total`

### 11.4 v2 的命名规则

建议所有新统计统一前缀：

- `atlas_*`

并在对象维度上展开：

- `atlas_obj_premphf_band_materialize_total`
- `atlas_obj_idx2row_owner_form_total`
- `atlas_obj_rowdescriptor_ready_total`

这样可以直接把这套统计与旧 `pulse_*` 统计区别开来。

进一步地，v2 需要把命名分层写清楚：

- `atlas_service_*`：`PeLocalServiceObjectTable` / service-table boundary probe
- `atlas_proxy_*`：today runtime proxy census
- `atlas_object_*`：未来真正 object-machine lifecycle
- `atlas_storage_*`：residency / refill / reclaim / evict
- `atlas_fabric_*`：event/data 与 control/sync plane
- `atlas_sync_*`：barrier / commit / exactness interaction

只有这样，正文中的抽象对象、当前代码里已经落地的统计、以及未来真正的 machine contract 才不会混成一层。

### 11.5 A1 最小 observability 落地：先把 `atlas_service_*` 走通

本轮实现不去修改任何 runtime 行为，只做一条最小、隔离的 machine-visibility 链路：

1. 在 `PeLocalServiceObjectTable` 中把 today 已经存在的局部 service/object census 统计上抛；
2. 在 `MultiCorePE` 顶层注册并导出 `atlas_service_*`；
3. 采用 `finish()` 一次性精确导出的方式，避免周期采样把最终对象 census 重复累计；
4. 在 `compute_essential_summary_mesh.py` 中增加独立的 `atlas_service` summary section，而不是把它混进旧 `pulse` summary。

当前已经稳定落地的最小统计面包括：

- `atlas_service_owner_form_total`
- `atlas_service_join_live_total`
- `atlas_service_join_ready_total`
- `atlas_service_ready_transition_total`
- `atlas_service_ready_fanout_total`
- `atlas_service_ready_fanout_consumers_sum`
- `atlas_service_released_total`
- `atlas_service_atlas_obj_materialize_total`
- `atlas_service_atlas_obj_publicize_total`
- `atlas_service_atlas_obj_owner_form_total`
- `atlas_service_atlas_obj_ready_total`
- `atlas_service_atlas_obj_release_total`
- `atlas_service_atlas_obj_private_only_total`

offline summary 侧还补了两个第一批派生指标：

- `atlas_service_ready_fanout_avg`
- `atlas_service_private_only_share`

这一步的意义不是证明“已经有收益”，而是第一次把：

- object census
- shared service shadow lifecycle
- private-only 占比

放到了主 summary 链路里，让 `PE-Atlas` 从设计稿进入可观测状态。

### 11.6 A1b 分面可见化：`atlas_proxy / atlas_fabric / atlas_storage / atlas_sync`

在 `A1` 最小链路稳定后，下一步不是继续把所有东西都塞回旧 `pulse` 叙事，而是把 today 机器拆成四个更接近体系结构语义的分面。

本轮已经落地的最小分面如下：

- `atlas_proxy`
  - 由 `WeightMemorySubsystem::experimentalPeAtlasRowIndexLifecycleLedger()` 驱动
  - 先冻结 `RowIndex` 的 today ledger：
    - `materialize`
    - `publicize`
    - `owner_form`
    - `join_live / join_ready`
    - `ready`
    - `release`
    - `release_missing`
    - `fallback`
- `atlas_fabric`
  - 由已有 `pulse_ingress_*` 与 `pulse_control_*` 统计在 summary 侧重命名得到
  - 重点回答 ingress/data 路与 control queue 在 today 到底发生了什么
- `atlas_storage`
  - 由已有 `pulse_osa_shared_weight_*` 统计在 summary 侧汇总得到
  - 重点回答 shared weight residency、idx/L0 压力与 refill/evict 事实
- `atlas_sync`
  - 由 `gas_retire_*` 与 `pe_step_perf_db.csv` 中的 retire/block/barrier wait 字段收口得到
  - 重点回答 ready-visible 之后，exact commit / barrier / HOL 还在怎样限制系统

这一层的关键意义是：

1. 不再只知道“family 有没有证据”；
2. 而是能直接回答“证据落在哪个 machine plane”；
3. 并且第一次把 `RowIndex` 的 today lifecycle 从概念描述，压成 code-visible ledger。

---

## 12. 第一阶段的真正目标：不是优化，而是完成“机器可见化”

### 12.0 当前阶段判定（2026-03-31）

截至本稿，`PE-Atlas` 的阶段位置可以明确写成：

- `M0 / object census`：第一轮已完成，today 候选对象已被压成 `active? / registered-but-proxied / shadow-only / missing` 矩阵；
- `M1 / probe plane`：最小链路已完成，`atlas_service_*` 已接入 `PE -> mesh_stats.csv -> essential_summary_mesh.json`；
- `M1.5 / facet split`：`atlas_proxy / atlas_fabric / atlas_storage / atlas_sync` 已进入 summary 主链路，其中 `rowindex` 的 today lifecycle ledger 已冻结成只读 probe；
- 下一阶段真正应该推进的是：
  - 更细的 object-kind census
  - `control/data` plane split visibility
  - 然后才是第一条正式 objectization。

### 12.1 Phase M0：Atlas Machine Census

目标：

- 为每个对象族回答：
  - `materialize point`
  - `publicize point`
  - `owner point`
  - `ready point`
  - `release point`
  - `fallback point`

输出：

- 一张 object census matrix
- 一张 scope consistency matrix
- 一张 call-site matrix

本轮状态：

- 已完成第一轮 matrix 冻结；
- 但还没有做到 object-kind 粒度的逐对象 `materialize/publicize/ready/release` 全 call-site ledger。

### 12.2 Phase M1：Atlas Probe Plane

目标：

- 在不改变行为的前提下，把 object lifecycle probe 补齐

要求：

- 零行为改变
- 零 contract 改变
- 只做 machine visibility

本轮状态：

- 已完成最小 `atlas_service_*` 链路；
- 但 storage/fabric/commit domain 仍未独立成面。

### 12.3 Phase M2：Control/Data Plane Split Visibility

目标：

- 把 control 与 data 的逻辑统计分开
- 让 router/interface/queue 首次成为一等可见对象

### 12.4 Phase M3：First True Objectization

这一步不是随便挑一个 seam，而是要选：

- 第一个真正适合被 objectize 的对象

post-census 之后，first objectization 候选需要拆成两条线：

近程、最贴近 today runtime 的候选：

1. `RowIndex`
2. `ValueRegion`
3. `PreMphfBase`
4. `Idx2Row`

中程、论文形态最理想的候选：

1. `PreMphfBand`
2. `PreMphfBase`
3. `Idx2Row`

调整原因：

1. `PreMphfBand` 在 today mainline 里仍是 `missing`，直接 objectize 风险最高；
2. `RowIndex` 虽然只是 `shadow-only`，但已经最接近“从现有结构推进成 authority-bearing object”的真实工程路径；
3. `ValueRegion` 是 today 共享 residency 代理最清楚的对象，适合作为 storage/object coupling 的第一条验证线；
4. `PreMphfBase / Idx2Row` 虽然还是 proxy，但 registry / lookup reality 最稳定，适合作为 metadata object plane 的稳健推进对象；
5. 论文叙事上仍然可以把 `PreMphfBand` 保留为 medium-term 理想对象，但不再把它写成 immediate next object。

### 12.5 Phase M4：Value Residency Plane

只有当 metadata authority 稳定后，才把：

- `ValueRegion`
- refill
- residency
- evict

正式对象化。

### 12.6 Phase M5：Commit/Domain Interaction

只有在前两层都稳定后，才讨论：

- domain-local retire
- commit-domain interaction
- cross-core exactness optimization

在此之前，不再把 retire 当作当前主任务。

---

## 13. 第一批实现任务建议

### Task A：做 `object census`，不要再做收益 sweep

立即要做的不是新的 A/B，而是：

- 找到所有对象的 today active / shadow / missing 状态

建议输出格式：

| object | materialize | owner | ready | release | active? | note |
| --- | --- | --- | --- | --- | --- | --- |

### Task B：补 `atlas_*` 统计骨架

优先实现：

- object census
- authority
- lifecycle
- control/data split

不要先实现：

- speedup-oriented heuristics
- threshold sweeps
- lease tuning

### Task C：做“架构认知实验”

新的 `mainexp` 第一目标不是：

- `memory_requests` 下降

而是回答：

1. 哪些对象真实存在完整 lifecycle？
2. 哪些对象只在 private path 中存在？
3. 哪些对象具备跨 core authority？
4. 哪些 queue/router/table 才是 today bottleneck？

### Task D：挑一个真实对象做第一条 objectization

在 machine census 完成之前，不再继续扫：

- `rowidx / idx2 / preband`

参数。

完成 census 后，再以：

- lifecycle 完整度
- 作用域稳定性
- 粒度可控性

选择第一个 objectization 对象。

---

## 14. 论文主张与创新边界

`PE-Atlas v2` 的论文主张不应再是：

- “我们发现了一条更早的 seam”

而应收敛为：

- **我们提出了一种面向 `PE` 内部的 object-scoped manycore machine，把对象边界、互连层、局部存储层、控制/同步层与 exact commit 边界统一到一个正式架构模型中。**

它的创新边界在于：

1. 把 `PE` 内部正式建模成局部众核机器，而不是 shared helper 的堆叠；
2. 把 shared object 从“语义现象”提升为“生命周期闭合的架构对象”；
3. 把 event/data 与 control/sync 分成正式 plane；
4. 把 observability 从收益指标扩展到 machine visibility；
5. 给出一条从 today codebase 可渐进落地的路径，而不是纯概念蓝图。

---

## 15. 非目标与边界

本稿明确 **不** 立刻做下面这些事：

1. 不承诺短期内一定获得性能正收益；
2. 不立刻重写 `per-core exact retire`；
3. 不假定所有 today `PerPe` 对象都已经是活跃对象；
4. 不继续围绕 `TTL / mask / threshold` 做参数扫；
5. 不把 `rowdescriptor` 等同于整个 `PE` 内部机器；
6. 不把 `PULSE` 继续当成主叙事；
7. 不在缺少 machine census 的情况下推进 value/retire 优化。

---

## 16. 与旧路线的关系

从现在开始：

- `PULSE`
- `rowdescriptor ready-join`
- `metadata txn`
- `shared ingress`

这些工作不作废，但统一降级为：

- **`PE-Atlas` 之下的局部历史分支与局部对象实验。**

它们仍有两个重要价值：

1. 提供负结果与约束；
2. 提供第一条已活跃 lifecycle 的 `rowdescriptor` 基线。

但它们不再继续作为：

- `PE` 内部架构主叙事

来主导下一阶段工作。

---

## 17. 立即执行的三件事

### 17.1 先完成 `PE-Atlas object census`

目标：

- 把 today codebase 中所有候选对象标成：
  - `active`
  - `shadow-only`
  - `registered-but-proxied`
  - `missing`

### 17.2 补齐 machine-visibility 统计

目标：

- 不再只回答“有没有收益”
- 而是回答“机器今天到底怎么跑”

本轮闭环：

- `atlas_service_*` 已经完成第一条观测链路；
- 下一步不该扩成更多启发式，而该补：
  - object-kind 维度统计
  - `control/data` 分面统计
  - storage residency / reclaim 统计

### 17.3 只在 census 之后选择第一条 objectization 路线

建议默认优先级：

近程工程优先级：

1. `RowIndex`
2. `ValueRegion`
3. `PreMphfBase`
4. `Idx2Row`

中程论文优先级：

1. `PreMphfBand`
2. `PreMphfBase`
3. `Idx2Row`

### 17.4 并行三任务执行版（2026-04-04 reset：machine-model-first）

从 `2026-04-04` 开始，这一节正式覆盖此前任何隐含的 `rowindex-first` 推进顺序。

下一大阶段只有一个唯一目标：

- **先完成 `PE` internal machine 的 formal model，再决定第一条真正值得 objectize 的对象线。**

因此，本阶段的第一验收不再是：

- `memctrl.req_total`
- `speedup`
- `noninflight_prefetch_only`

而改成四个更底层的问题：

1. `PE` 内一等对象到底有哪些；
2. 这些对象分别落在哪个 scope / storage / fabric / phase；
3. owner / ready / release / reclaim 的 authority 是否闭合；
4. Gather / Apply / Scatter / Retire / Drain 这些阶段边界是否稳定。

`rowindex / idx2 / prebase / pre-band / rowdescriptor` 从现在开始统一降格为：

- `PE-Atlas machine` 之下的对象家族实例与架构证据；

而不再作为“下一大阶段主线本身”。

#### 任务一：冻结四张必须存在的机器图

这一条是整个大阶段的中心，不接受用收益数字替代。

必须冻结的四张图是：

1. `Object Graph`
   - 每个对象族的 `materialize / publicize / owner / ready / release / reclaim / fallback`
   - 明确是 `active`、`registered-but-proxied`、`shadow-only` 还是 `missing`
2. `Storage / Scope Graph`
   - 把 `WMS internal storage model -> PE local storage object model` 一一映射清楚
   - 明确 `idx_sram_model_ / l0_sram_model_ / metadata tables / residency buffers / directory tables` 分别属于哪一层
3. `Phase / Lifecycle Graph`
   - 把 `Gather / Apply / Scatter / Retire / Drain` 各阶段允许的对象流动、owner 迁移、ready 可见性写成正式图
4. `Communication / Control Graph`
   - 把 `event/data fabric` 与 `control/sync fabric` 的消息、队列、目录、redirect 路径单独成图

这条任务线的验收标准是：

- 任意一个对象，都能回答“它在什么阶段被创建、在什么 scope 持有 authority、在什么 storage 驻留、通过哪张 fabric 广播 ready/release”。

#### 任务二：冻结四条底层 contract，而不是继续调 seam

近期实验已经给出了足够强的反证：

1. `rowindex detached carry probe` 中，`touch` 非零但 `carry_pending=0`、`prefetch_rows=0`
2. `rowindex prefetch-only frontier` 中，prefetch 响应虽然出现，但仍主要附着在 inflight/owner 路径上

这两类现象说明的不是“rowindex 不重要”，而是：

- today 机器的 `phase-open / owner / residency / control visibility` 合同还没有冻结。

所以下一阶段必须先冻结四条 contract：

1. `Owner Contract`
   - 同一对象在同一时刻只能有一个 active owner
   - join/redirect/fallback 必须可见
2. `Scope Contract`
   - `object scope = owner scope = residency scope = service scope`
   - 一旦不一致，就应明确判成 proxy/shadow，而不是偷算 shared object
3. `Phase-Open Contract`
   - 每个 core 的 `beginGatherWindow()` / `beginApplyWindow()` / `beginScatterWindow()` 打开与关闭条件必须可见
   - 禁止对象在 phase 尚未正式 open 的 core 上被“早触发、后清空”
4. `Commit / Exactness Contract`
   - `shared ready != architectural commit`
   - `C-scope` exact retire 顺序保持不变

这一条任务的交付物不是新优化逻辑，而是：

- code-anchored contract table
- phase ordering ledger
- owner/residency mismatch ledger
- ready-visible-but-commit-blocked ledger

#### 任务三：实验体系改成 architecture validation，而不是 benefit chase

`mainexp` 下一阶段要跑的实验，不再以 headline gain 为第一目的，而是专门回答机器是否闭合。

新的实验问题应该收敛成：

1. 这个对象家族是否真的存在 `materialize -> owner -> ready -> release` 链；
2. 它是否跨过了 proxy/shadow，进入了 formal authority；
3. 它的 ready/release 走的是哪张 fabric；
4. 它在 phase 边界上是稳定的，还是会被 window reset / per-core skew 打断；
5. 它的 residency 是真实对象驻留，还是 inflight 附属物。

在这个口径下：

- `rowindex / idx2 / prebase / pre-band`
  只是用来验证 object family 是否存在、合同是否闭合的四个实例；
- `rowdescriptor`
  是 today 最活跃的 proxy baseline；
- 它们都不是“下一大阶段唯一主角”。

新的阶段验收也要改写成：

- 不先问“收益多少”
- 先问“对象是否存在、生命周期是否闭合、authority 是否一致、阶段边界是否稳定、control/data 是否已分面可见”

### 17.5 下一大阶段的正式阶段划分

为避免再次滑回 seam-first / benefit-first，接下来把大阶段明确拆成四步。

#### Stage M2-A：Atlas Machine Freeze

目标：

- 完成 `Object Graph / Storage-Scope Graph / Phase-Lifecycle Graph / Communication-Control Graph`

第一交付物：

- `object census v2`
- `WMS -> PE local storage object map`
- `phase-open/close ledger`
- `control/data message map`

#### Stage M2-B：Contract Closure Probe Plane

目标：

- 只补 probe，不改行为
- 把 `owner / scope / phase-open / commit` 四条合同全部导出成可验证统计

第一交付物：

- `atlas_object_*`
- `atlas_storage_*`
- `atlas_fabric_*`
- `atlas_sync_*`
- `atlas_phase_*`

#### Stage M2-C：Architecture Validation Suite

目标：

- 在隔离实验中验证对象家族是否真的进入 formal machine

验证口径：

- existence
- lifecycle closure
- authority consistency
- phase stability
- residency stability

只有当 `M2-C` 完成后，才允许进入下一步。

#### Stage M3：First True Objectization Selection

这一阶段不预设 `rowindex` 必然优先。

候选对象的选择标准只看：

1. lifecycle 完整度；
2. scope / storage 稳定度；
3. control/data 路径清晰度；
4. 与 `exact commit` 的隔离难度。

也就是说，`rowindex / value region / prebase / idx2 / pre-band` 都只是候选，不再预先钦定主线。

### 17.6 M2-A 首轮代码冻结结果（2026-04-04）

下面这一节不是新的理想图，而是基于 today 代码热路径收出来的第一批 `code-anchored machine freeze`。

这一轮冻结后，`PE` internal machine 可以先压成三个结论：

1. `LocalStorageHierarchyController` 今天首先是 `namespace/registration root`，还不是 runtime data mover；
2. `P-scope` 真正有 authority 的只是一小部分：
   - `PodOwnerServiceTable`
   - `PeLocalServiceObjectTable` 的 service-lifecycle boundary
3. `control/data split` 在逻辑上已经成形，但控制面 today 仍明显偏 observe/queue，尚未进入完整的 runtime consumption loop。

#### 17.6.1 Storage / Scope / Object Map：today 的正式映射

| machine object | today 代码载体 | scope | today 判定 | 说明 |
| --- | --- | --- | --- | --- |
| `activation_ingress_store` | `LocalStorageHierarchyController` 注册的 `PerPe` queue object；实际热路径在 `PeSharedCoreFabric` ingress queue/harbor | `E-scope` | `mixed-proxy` | 名义上有 `PerPe` ingress store，但真正运行时入口由 `pulse_fabric` 维护 |
| `weight_idx_store` | `LocalStorageHierarchyController` 的 `PerPe` object + `WeightMemorySubsystem::idx_sram_model_` + `PeWeightObjectPlane::idxModel()` | `E-scope` | `mixed` | today 同时存在 per-core mirror 和 PE-shared mirror；是否真有 shared residency authority 取决于 `actual_owner_enable` |
| `weight_value_store` | `LocalStorageHierarchyController` 的 `PerPe` object + `WeightMemorySubsystem::l0_sram_model_` + `PeWeightObjectPlane::l0Model()` | `E/P-scope` | `mixed` | value residency 可被 `PeWeightObjectPlane` 统计承接，但 today 仍大量依赖 WMS mirror 与 line-residency proxy |
| `pod_metadata_store` | `PodMetadataObjectPlane` | `P-scope` | `shadow` | 有 `observe/unique/overlap`，但没有 owner/ready/release |
| `pod_owner_table` | `PodOwnerServiceTable` | `P-scope` | `formal` | today 最接近正式 authority 的表：`lookupOrAllocate + join` |
| `pod_join_table` | 命名空间在 `LocalStorageHierarchyController`，运行时主要折叠进 `PodOwnerServiceTable::join()` | `P-scope` | `mixed` | 配置上独立，执行上尚未分离成独立 runtime object |
| `pod_ready_table` | 命名空间在 `LocalStorageHierarchyController`，运行时主要折叠进 `PeLocalServiceObjectTable` | `P-scope` | `mixed-shadow` | ready/release/lease 已存在，但仍是 service shadow plane，不是 commit plane |
| `state_store` / `activation_core_queue` / `accumulator_store` / `register_file` | `PerCore` local storage objects | `C-scope` | `formal` | 这是 today 最稳定的局部机器层次 |
| `RetireTicket` / exact commit token | `WeightMemorySubsystem::edge_retire_ + next_retire_seq_ + per_post_retire_seq_` | `C-scope` | `formal` | 它不在 `LocalStorageHierarchyController` 中，但却是 today 最硬的 architectural object |

这张表对应的第一批硬锚点是：

1. `PerPe / PerPod / PerCore` 对象名由 `MultiCorePE` 装配并注册
   - `components/MultiCorePE.cc:472-578`
   - `services/local_storage/LocalStorageHierarchyController.cc:98-120`
2. `PodMetadataObjectPlane` 承接 `metadata observe / overlap census`
   - `services/local_storage/PodMetadataObjectPlane.h:101-159`
3. `PodOwnerServiceTable` 承接 `lookupOrAllocate + join`
   - `services/local_storage/PodOwnerServiceTable.h:113-231`
4. `PeLocalServiceObjectTable` 承接 `owner_form -> join_live/join_ready -> ready -> release`
   - `services/local_storage/PeLocalServiceObjectTable.h:190-470`
5. `PeWeightObjectPlane` 承接 `PerPe idx/l0 owner-scope mirror`
   - `services/local_storage/PeWeightObjectPlane.h:59-166`

更准确地说，today 的 `WMS internal storage model -> PE local storage object model` 应当这样理解：

1. `idx_sram_model_`
   - 对应逻辑上的 `weight_idx_store`
   - 但 today 仍由每个 core 的 `WMS` 在 issue/lookup 热路径上直接驱动
   - `PeWeightObjectPlane::idxModel()` 目前更像 `PerPe mirror + observability plane`
2. `l0_sram_model_`
   - 对应逻辑上的 `weight_value_store`
   - 但 today 的 fill/evict/read 仍主要由 per-core `WMS` 热路径与 line-residency proxy 驱动
   - `PeWeightObjectPlane::l0Model()` 只有在 `actual_owner_enable` 时才开始逼近真正的 shared residency authority
3. `PodMetadataObjectPlane`
   - 是 `pod_metadata_store` 的 runtime 实体
   - 但它只完成 `observe/overlap census`，没有 service authority
4. `PodOwnerServiceTable`
   - 是 `pod_owner_table` 的 runtime authority holder
   - 这是 today `P-scope` 中最 formal 的对象
5. `PeLocalServiceObjectTable`
   - 实际承接了 `owner_form -> join_live/join_ready -> ready -> release`
   - 但它的注释已经写得很清楚：这是 `shadow table`，且显式隔离于 architectural commit path

绑定路径上，这几层 today 是通过：

- `control/SnnPESubComponent.cc:1391-1415`

统一接进 `WeightMemorySubsystem` 的，而不是由 `WMS` 自己构造一套独立的 `PE` 内 authority plane。

这进一步说明，today 还没有把下面三件事收成一层：

- `storage namespace`
- `storage residency authority`
- `storage access hot path`

因此 `M2-A` 对 storage model 的目标不是“先加更多共享 bank”，而是先把这三者的映射冻结。

这组映射同时改写了一个很关键的判断：

- `LocalStorageHierarchyController` today 是 `object namespace root`
- 不是 `runtime object authority root`

所以 `ls_*` 对象名、`atlas_*` object-plane、以及 `WMS` 热路径 authority，今天仍然是三层，而不是一层。

#### 17.6.2 Phase / Lifecycle Graph：today 的阶段图不是集中式，而是分布式 contract

`PE` internal phase graph 的 today 热路径可以先冻结为：

1. `Global step open`
   - `MultiCorePE::beginGlobalStep_` 先对所有 core 调用 `onGlobalStepStart(seq)`，再注入 step stimulus
   - 这是 today 唯一明确试图先打开 phase、再注入 traffic 的顶层 contract
2. `Core-shell stage mirror`
   - `SnnPESubComponent::onGasStageEvent` 维护 `gas_stage_` 的镜像，并把 stage event 转发给 `SnnWorkload`
3. `Gather open`
   - `SnnWorkload::enterBeginGather_` 调 `WeightMemorySubsystem::beginGatherWindow()`
   - 这一步会 reset：
     - `posts_seen_window_`
     - `posts_list_window_`
     - `active_pre_window_`
     - `pre_touch_order_window_`
     - `experimental_noc_rowidx_pending_rows_`
   - 硬锚点：
     - `services/workload/snn/SnnWorkload.cc:1204-1218`
     - `services/synapse/weights/WeightMemorySubsystem.h:2062-2077`
4. `Touch ingress`
   - `SnnPESubComponent_spike.cc` 和 `SnnWorkload.cc` 都会在 stage 允许时调用 `noteWindowTouch()`
   - 但 `WeightMemorySubsystem::noteWindowTouch()` 自己不检查 stage，只做：
     - `notePostLocal`
     - `notePreGlobal`
     - `noteExperimentalNocRowidxTouch_`
   - 更关键的是：
     - gather 阶段这时 `window_seq_` 通常还没有在 `WMS` 内被设置成 apply-window authority
     - 所以 `noteExperimentalNocRowidxTouch_()` 可以累计 `touched_rows/pending_rows`
     - 却未必会把 `rowindex` 正式 publicize 到 pod object/service plane
   - 硬锚点：
     - `services/workload/snn/SnnWorkload.cc:1718-1728`
     - `control/SnnPESubComponent_spike.cc:110-132`
     - `services/synapse/weights/WeightMemorySubsystem.h:2097-2102`
5. `Apply open`
   - `SnnWorkload::onGasStageEvent(BeginApply)` 调 `WeightMemorySubsystem::beginApplyWindow(seq)`
   - 这一阶段会：
     - 设置 `window_seq_`
     - `flipEdgesForApply`
     - 可选 carry `experimental_noc_rowidx_pending_rows_`
     - `maybePromoteExperimentalNocRowidxTouchesToApplyWindow()`
     - reset retire / issue queue skeleton
   - 硬锚点：
     - `services/workload/snn/SnnWorkload.cc:2536-2543`
     - `services/synapse/weights/WeightMemorySubsystem.h:2170-2234`
6. `Scatter close`
   - `SnnWorkload::completeEndScatter_` 调 `WeightMemorySubsystem::endScatterWindow(seq)`
   - 这一步负责：
     - `maybeReleaseExperimentalNocRowidxServiceObjects_`
     - finalize pulse/shared window bookkeeping
     - 把 `window_seq_` 清零
   - 硬锚点：
     - `services/workload/snn/SnnWorkload.cc:1192-1201`
     - `services/synapse/weights/WeightMemorySubsystem.h:2239-2303`
7. `PE-level phase glue`
   - `MultiCorePE::notifyStageEvent()` 在 `BeginApply` 时执行 `pulse_fabric_->closeGatherHarborStep(seq)`，
     在 `EndScatter` 时汇聚 per-core 完成态并决定 PE 级 reset / barrier
   - 硬锚点：
     - `components/MultiCorePE.cc:5590-5695`

因此，today 最准确的阶段判断不是：

- “phase 已经是一张统一的中央状态机”

而是：

- **phase today 是一套分布在 `MultiCorePE / CoreShell / Workload / WMS` 上的分布式 contract。**

这正好解释了最近的关键现象：

- `touch > 0`
- 但 `carry_pending = 0`
- 且 `prefetch_rows = 0`

这组现象最像的不是“rowindex seam 无收益”，而是：

- **`Phase-Open Contract` 还没有被局部机器正式冻结。**

更具体地说，today 的 contract hole 很可能是：

1. caller 侧已经认为 core 进入了 `Gather`
2. 因而 `noteWindowTouch()` 可以被调用
3. 但该 core 本地的 `WeightMemorySubsystem::beginGatherWindow()` 可能尚未完成这轮 window reset/open
4. 后续 reset 把刚刚积累的 `touched_rows/pending_rows` 又清掉

换句话说，`touch` 的发生 today 不等于：

- 对应对象已经处于一个“本地 Gather-open、允许 carry 到 Apply”的稳定 phase contract 中
- 也不等于该对象已经获得了 apply-window 下的 formal `window_seq / owner / ready` authority

这就是为什么下一阶段必须把：

- `beginGatherWindow()`
- `first noteWindowTouch()`
- `beginApplyWindow()`
- `endScatterWindow()`

的先后顺序单独冻结成 `atlas_phase_* ledger`。

还有一个必须一并冻结的辅助事实是：

- 仓库已经显式加入了 “只要仍有 core 停留在 `BeginGather`，就不能发 `PE_DONE`” 的保护：
  - `components/multicore/GlobalStepDrainDecision.h:96-105`

这说明 `Gather-open skew` 不是凭空猜测，而是 today 机器已经承认存在的 phase-level 问题。

#### 17.6.3 Communication / Control Graph：today 已经分面，但控制面还没被真正消费

today 的 `event/data` 与 `control/sync` 最准确的 code-anchored 图如下。

`event/data path`：

1. `NocPacketEvent`
2. `MultiCorePE::deliverPacketToEndpoint_`
3. `PeSharedCoreFabric::observeIngress`
4. 若 actual ingress 打开，则进入 `pulse_ingress_buffered_packets_ + dispatch token`
5. `MultiCorePE::drainPulseIngress_`
6. `deliverPacketDirectToCore_`
7. core/workload 本地消费

`control/sync path`：

1. `PeInternalPodShadowGate`
   - 发 `FrontierExport`
   - 发 `OwnerAnnounce`
   - 发 `JoinRequest`
   - 发 `JoinReject`
2. `WeightMemorySubsystem::notePeInternalPodServiceObjectReady_`
   - 发 `ReadyFanout`
3. `PeSharedCoreFabric`
   - 维护独立 `control_queue_`
   - 维护独立 `control_entries_peak/backlog/messages_*`
4. `GlobalGasStepController`
   - 负责 `StartStep / PeReady / PeDone`
   - 这是 today 更偏系统级的 sync plane

这说明 `control/data split` 今天已经不只是概念，而是已经具备了：

1. 独立消息类型
2. 独立队列
3. 独立 backlog 统计
4. 独立 frontier/owner/join/ready 计数

但与此同时，today 还有一个必须写进主文档的硬事实：

- `PeSharedCoreFabric::collectControlBatch()` 在主运行时里还没有被接进实际消费闭环；
- runtime today 只会周期性调用 `observeControlBacklogCycle()` 做 backlog 统计。

所以 today 的控制面状态更准确地写成：

- **`logically split, physically queued, but runtime-consumption still incomplete`**

这也是为什么 `pulse_control_*` today 更像：

- 机器可见化证据

而不是：

- 已经 fully-operational 的 inter-core control network

同理，`OptimizedInternalRing` 虽然类型上支持：

- `PACKET_MESSAGE`
- `MEMORY_REQUEST`
- `MEMORY_RESPONSE`
- `CONTROL_MESSAGE`

但 `PE-Atlas / PULSE` 当前实际主路径里，真正成形的还是：

- packet/event transport
- 以及 `PeSharedCoreFabric` 内部的逻辑控制队列

因此 `Communication-Control Graph` 的第一轮冻结结论应当是：

1. `OptimizedInternalRing`
   - today 代表 `E-scope data transport substrate`
2. `PeSharedCoreFabric`
   - today 代表 `PE-local ingress + control queue + harbor/descriptor observability`
3. `PeInternalPodShadowGate + PodOwnerServiceTable + PeLocalServiceObjectTable`
   - today 代表 `P-scope owner/join/ready/release producer side`
4. `GlobalGasStepController`
   - today 代表 `N/E-scope barrier/sync authority`

#### 17.6.4 对 M2-B 的直接约束

基于这轮代码冻结，`M2-B` 不该再泛泛地“补更多 probe”，而应当直接补下面四类缺口：

1. `atlas_phase_*`
   - 每个 core 的 `beginGatherWindow/open`
   - `first noteWindowTouch`
   - `beginApplyWindow`
   - `endScatterWindow`
   - 以及 reset 发生点
2. `atlas_storage_map_*`
   - `idx_sram_model_` 与 `PeWeightObjectPlane::idxModel()` 的 authority 差异
   - `l0_sram_model_` 与 `PeWeightObjectPlane::l0Model()` 的 authority 差异
3. `atlas_control_runtime_*`
   - 区分 `control message produced`
   - `control message queued`
   - `control message actually consumed`
4. `atlas_contract_mismatch_*`
   - `object scope != owner scope`
   - `owner scope != residency scope`
   - `touch occurred before local gather-open`
   - `ready visible but commit still blocked`

这四类 probe 一旦补齐，下一阶段我们问的就不再是：

- “哪个 seam 先出收益”

而是：

- “这台 `PE` internal machine 到底在哪个 contract 上还没有闭合”

### 17.7 下一大阶段目标更新（2026-04-04，回读文档与代码后的执行版）

这一节用于覆盖任何再次滑向 `benefit-first / seam-first` 的隐含推进。

基于本轮重新对齐设计稿、`TECH_PROGRESS.md`、测试与代码热路径，下一大阶段现在应当明确写成：

- **不是进入 `M3`，也不是继续找收益 seam，而是把 `M2-B` 真正做成一套闭合的 `contract closure probe plane`。**

当前不能跳过 `M2-B` 的原因已经足够硬：

1. `atlas_phase_*` 今天在 `MultiCorePE` 中还没有任何注册/声明；
2. `test_multicore_pe_stats_contract.py` 的 fresh 红灯表明：
   - 失败点不是“实现后收益回退”
   - 而是“`phase ledger` 这一列 probe 还根本不存在”
3. `PeSharedCoreFabric` 虽然已经有：
   - `enqueueControlMessage()`
   - `collectControlBatch()`
   - `observeControlBacklogCycle()`
   但主运行时 today 只消费 backlog 观测，不消费 control batch；
4. `weight_idx_store / weight_value_store` 也还没有被拆成：
   - `WMS private mirror`
   - `PE shared mirror`
   - `actual residency authority`
   三者分离可见的正式统计面。

因此，下一大阶段唯一正确的总目标是：

- **先把 `phase / storage / control / mismatch` 四类机器合同显式导出，再决定哪一条对象家族值得进入第一次真正的 objectization。**

#### 17.7.1 当前大阶段正式定义：`M2-B = Probe Plane Closure`

`M2-B` 从现在开始不再是“补一些探针”的松散说法，而是一个有明确入口、退出、禁止事项的正式阶段。

入口条件（today 已满足）：

1. `M2-A machine freeze` 已经给出 code-anchored 结论；
2. `atlas_phase_*` 缺失、`control consume gap`、`storage authority split` 都已有明确代码证据；
3. 当前最缺的不是新收益路径，而是 formal machine observability。

本阶段禁止事项：

1. 不做新的 `rowindex / idx2 / preband / descriptor` 收益调参；
2. 不以 `memctrl.req_total / speedup / headline gain` 作为验收门槛；
3. 不在 `M2-B` 中引入新的共享行为语义；
4. 试验性代码必须继续保持隔离，只允许增加观测面与显式账本，不改 exactness contract。

#### 17.7.2 `M2-B1`：`atlas_phase_*` 垂直切片

第一优先级必须是 `phase-open contract`，因为当前最强的负结果已经指向这里：

- `touch > 0`
- `carry_pending = 0`
- `prefetch_rows = 0`

`M2-B1` 的交付物必须包括：

1. `WeightMemorySubsystem` 内正式 `phase ledger`
   - `beginGatherWindow()`
   - `first noteWindowTouch()`
   - `beginApplyWindow()`
   - `endScatterWindow()`
2. `SnnPESubComponent -> MultiCorePE` 的统计导出与 PE 聚合；
3. `atlas_phase_*` 在：
   - statistic registration
   - `SST_ELI_DOCUMENT_STATISTICS`
   - map export / finish flush
   三处同时闭合；
4. 最小红绿灯验证：
   - `test_multicore_pe_stats_contract.py`
   - `test_pe_internal_pod_shadow_wms_seam.cc` 中 phase ledger 两个新测试

`M2-B1` 的退出条件不是“收益变好”，而是：

- 我们终于能直接回答：
  - `touch` 是否发生在 local gather-open 之前；
  - `touch` 是否被后续 local reset 清空；
  - `apply-open` 是否真正看到了 gather 侧累计状态。

#### 17.7.3 `M2-B2`：`atlas_storage_map_*` authority map

第二优先级是把 `WMS internal storage model` 与 `PE local storage object model` 的 authority 差异显式化。

`M2-B2` 的目标不是新增 shared bank，而是把今天已经存在但混叠在一起的三层拆开：

1. `WMS private mirror`
2. `PE shared mirror`
3. `actual residency authority`

最小交付物应当围绕两条 today 最真实的路径：

1. `weight_idx_store`
   - `WeightMemorySubsystem::idx_sram_model_`
   - `PeWeightObjectPlane::idxModel()`
2. `weight_value_store`
   - `WeightMemorySubsystem::l0_sram_model_`
   - `PeWeightObjectPlane::l0Model()`

需要导出的不是“总读写次数”本身，而是：

- 谁在记账；
- 谁在驻留；
- `actual_owner_enable` 是否真的改变了 authority；
- 今天哪些只是 mirror/stats plane，哪些已经接近 formal residency plane。

`M2-B2` 结束时，必须能把 `weight_idx_store / weight_value_store` 判成下面三类之一：

1. `private-authority`
2. `shared-mirror-only`
3. `shared-authority-active`

#### 17.7.4 `M2-B3`：`atlas_control_runtime_*` consume gap

第三优先级是把 today 控制面的真实状态定量化。

当前最关键的冻结事实是：

- control message 已经会 `produced`、会 `queued`、会形成 backlog；
- 但主运行时 today 还没有一个完整的 `collectControlBatch() -> consume/apply` 闭环。

因此 `M2-B3` 的目标必须写成：

- **不是先实现控制面消费，而是先把 `produced / queued / consumed / backlog` 四者分开导出。**

最小交付物：

1. `atlas_control_runtime_produced_*`
2. `atlas_control_runtime_queued_*`
3. `atlas_control_runtime_consumed_*`
4. `atlas_control_runtime_backlog_*`

这样 `M2-B3` 结束后，控制面的 today 状态才能被严格描述为：

1. `observe-only control plane`
2. `queued-but-unconsumed control plane`
3. `partially consumed control plane`

只有这一步做完，后面才有资格讨论要不要把 control path 从“机器可见化”推进到“真正 runtime loop”。

#### 17.7.5 `M2-B4`：`atlas_contract_mismatch_*` 失配台账

前三个子阶段补的是分面统计，第四个子阶段补的是跨平面失配。

这一块必须显式回答四类 today 最危险的问题：

1. `object scope != owner scope`
2. `owner scope != residency scope`
3. `touch occurred before local gather-open`
4. `ready visible but commit still blocked`

也就是说，`M2-B4` 不是新增功能，而是把此前分散在：

- rowindex 负结果
- control backlog
- ready-but-blocked retire
- shared mirror / actual owner enable

这些证据，收成统一的 mismatch ledger。

`M2-B4` 结束后，`PE-Atlas` 才算真正拥有：

- phase contract view
- storage authority view
- control runtime view
- cross-plane mismatch view

四张可同时对齐的 probe 面。

#### 17.7.6 `M2-C` 的唯一入口条件

只有当下面四件事全部成立时，才允许进入 `M2-C Architecture Validation Suite`：

1. `atlas_phase_* / atlas_storage_map_* / atlas_control_runtime_* / atlas_contract_mismatch_*`
   四类统计都已经：
   - 注册
   - 声明
   - 导出
   - PE 聚合
2. 至少一组 `mainexp` 隔离实验可以稳定导出这四类统计；
3. 至少一个 phase anomaly、一个 control consume gap、一个 storage authority split
   能被直接观察而不是靠日志猜测；
4. 在此之前，不允许把性能 gain 重新抬回第一验收门槛。

换句话说，下一大阶段结束时要交出的不是：

- “我们终于又找到一个可能有收益的 seam”

而是：

- **“我们终于把 `PE` internal machine 的 probe plane 做成了一台可以被验证的正式机器。”**

---

## 18. 参考启发

这些参考不是要直接复制其实现，而是为 `PE-Atlas` 的层次、对象、消息、存储和接口设计提供约束。

1. Intel Labs. *Single-chip Cloud Computer Overview Paper*.  
   https://www.intel.com/content/dam/www/public/us/en/documents/technology-briefs/intel-labs-single-chip-cloud-overview-paper.pdf
2. Intel Labs. *Taking Neuromorphic Computing to the Next Level with Loihi 2 Technology Brief*.  
   https://download.intel.com/newsroom/2021/new-technologies/neuromorphic-computing-loihi-2-brief.pdf
3. Merolla et al. *A million spiking-neuron integrated circuit with a scalable communication network and interface*. Science / IBM Research.  
   https://research.ibm.com/publications/a-million-spiking-neuron-integrated-circuit-with-a-scalable-communication-network-and-interface
4. Pei et al. *Towards artificial general intelligence with hybrid Tianjic chip architecture*. Nature 2019.  
   https://www.nature.com/articles/s41586-019-1424-8
5. Zhang et al. *A system hierarchy for brain-inspired computing*. Nature 2020.  
   https://www.nature.com/articles/s41586-020-2782-y
6. Bell et al. *TILE64 Processor: A 64-Core SoC with Mesh Interconnect*. ISSCC 2008.  
   https://www.princeton.edu/~wentzlaf/documents/Bell.2008.ISSCC.Tilera.pdf
7. Adapteva. *Epiphany Architecture Reference*.  
   https://www.adapteva.com/docs/epiphany_arch_ref.pdf
8. Kalray. *MPPA Technology Overview*.  
   https://www.kalrayinc.com/products/mppa-technology/
9. De Dinechin et al. *A Distributed Run-Time Environment for the Kalray MPPA-256 Integrated Manycore Processor*. 2013.  
   https://www.sciencedirect.com/science/article/pii/S1877050913004766
10. Su et al. *Core interface optimization for multi-core neuromorphic processors*. 2023.  
   https://arxiv.org/abs/2308.04171
11. Höppner et al. *The SpiNNaker 2 Processing Element Architecture for Hybrid Digital Neuromorphic Computing*.  
   https://arxiv.org/abs/2408.17017
