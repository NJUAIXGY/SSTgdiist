# PE 内部 runtime owner -> local object 正式绑定表（2026-03-21）

> 日期：2026-03-21  
> 状态：binding table v1  
> 目标：在已有 baseline model 与 storage mapping review 的基础上，把 today `PE` 内部运行时中的真实 owner，正式绑定到 `PE local storage object model`，并明确每一条绑定的 scope、访问类型、stall 来源、共享语义和当前断层。

---

## 0. 为什么还需要这份文档

我们已经有两份前置文档：

- `PE-internal architecture baseline model`
- `PE-internal storage mapping review`

但它们仍然缺一个对后续设计最直接有用的中间层：

- **today runtime 里，究竟是谁在“拥有并消费”每个 local object？**

如果不把这一层形式化，后续讨论会持续混淆以下几个问题：

1. 某个对象是否只是被注册；
2. 某个对象是否真的被 runtime path 消费；
3. 某个 stall/pressure 究竟归因给哪个 owner；
4. `PerPe` 对象到底是真的共享，还是只是 `PE` 名义上的壳；
5. 某个 future design 到底是在“迁移 owner”，还是只是在“增加 object namespace”。

因此，这份文档只做一件事：

- **为 today runtime 写出一份正式的 `owner -> object` 绑定表。**

---

## 1. 一句话结论

当前 `PE` 内部 runtime owner 到 local object 的绑定应收敛为：

- **`state/compute plane` 已有清晰 owner；**
- **`weight/service plane` 已有真实 owner 但 object scope 与 runtime scope 不一致；**
- **`activation/queue plane`、`acc/rf plane` 仍主要停留在弱绑定或无绑定状态。**

也就是说，today 的绑定不是“完整层级”，而是：

- **部分对象有 owner；**
- **部分对象有语义 owner 但没有统一 contract；**
- **部分对象仍只是为将来预留的名字。**

---

## 2. 绑定维度定义

本文对每条绑定统一记录六个字段：

1. `runtime owner`
   - today 真正执行该对象相关行为的模块
2. `local object`
   - `LocalStorageHierarchyController` 中注册的对象名
3. `runtime structure`
   - owner 内部真正对应的字段/模型/队列
4. `binding strength`
   - `strong / medium / weak / none`
5. `scope relation`
   - `aligned / widened / split / missing`
6. `stall / pressure source`
   - 该对象 today 是否能产生真实时序反压

其中：

- `aligned`
  - object scope 与 runtime scope 基本一致
- `widened`
  - object scope 比 runtime owner 更大，例如 `PerPe object` 对 `per-core runtime proxy`
- `split`
  - 一个 object 语义被多个 runtime structure 分裂承担
- `missing`
  - today 找不到稳定 runtime owner

---

## 3. today runtime owner 总表

从 today 热路径与 provider 装配看，和 local object 真正相关的 runtime owner 只有五类：

1. `DefaultSnnComputeCore`
2. `WeightMemorySubsystem`
3. `PeSharedCoreFabric`
4. `SnnWorkload`
5. `AccumulatorOps`

其中最重要的两类是真正进入 today 主路径的：

- `DefaultSnnComputeCore`
- `WeightMemorySubsystem`

其余三类的绑定明显更弱。

---

## 4. 正式绑定总表

| runtime owner | local object | runtime structure | binding strength | scope relation | stall/pressure source | today verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `DefaultSnnComputeCore` | `state_store.coreX` | `state_sram_model_` + `state_sram_layout_` | strong | aligned | `state_sram_stall_budget_` | today 最完整绑定 |
| `WeightMemorySubsystem` | `weight_idx_store` | `idx_sram_model_` + `sram_layout_.idx*` | medium | widened | `weight_sram_stall_budget_cycles_` | 有真实 owner，但 object 是 `PerPe`、runtime 是 per-core |
| `WeightMemorySubsystem` | `weight_value_store` | `l0_sram_model_` + `sram_layout_.l0*` | medium | widened | `weight_sram_stall_budget_cycles_` | 同上，且与 shared residency 语义分裂 |
| `WeightMemorySubsystem` | `weight_value_store` | `PulseSeededLineResidency` | weak | split | 无 formal bank/port stall | 像 shared value residency，但未进入正式 object contract |
| `PeSharedCoreFabric` | `activation_ingress_store` | `ingress_mirror_` | weak | aligned | 无真实 stall，仅 mirror stats | 命名上接近，但 today 只是 mirror/observe |
| `PeSharedCoreFabric` | `activation_core_queue.coreX` | `core_queue_mirrors_[core]` | weak | aligned | 无真实 stall，仅 mirror occupancy | 仅 queue mirror，不是 core runtime queue 真源 |
| `SnnWorkload` | `activation_core_queue.coreX` | `incoming_spikes_` | weak-to-none | split | 无 local-store stall | 当前 workload 路径未找到稳定 enqueue site |
| `AccumulatorOps` | `accumulator_store.coreX` | `acc_dense_ / acc_delta_ / acc_spill_log_` | weak | aligned | 无 banked stall，仅 HWM/spill逻辑 | 逻辑 accumulator，不是统一 local store |
| none | `register_file.coreX` | none found | none | missing | none | today 仅对象注册 |

---

## 5. State / Compute Plane：唯一真正“对齐”的绑定

### 5.1 owner

- `DefaultSnnComputeCore`

### 5.2 object

- `state_store.coreX`

### 5.3 runtime structure

对应结构是：

- `VirtualSramLayout state_sram_layout_`
- `BankedSramModel state_sram_model_`
- `state_sram_stall_budget_`

真实访问发生在：

- `updateNeuronStates()`
- `applyPendingDeltas_()`
- `fire()`

真实地址空间包括：

- `stateVmemAddr(neuron_idx)`
- `stateRefracAddr(neuron_idx)`
- `stateLastSpikeAddr(neuron_idx)`

### 5.4 为什么这是强绑定

因为这条线同时满足四件事：

1. object scope 是 `PerCore`
2. runtime owner 也是 per-core compute core
3. 访问语义明确且稳定
4. bank conflict 会转成真实的 `stall_budget`

因此 today 若要找一个“已经像 local storage plane 一样工作”的对象，它就是：

- **`state_store.coreX`**

---

## 6. Weight / Service Plane：有真实 owner，但 scope 仍是裂的

### 6.1 owner

- `WeightMemorySubsystem`

### 6.2 object 1：`weight_idx_store`

真实 runtime structure 是：

- `idx_sram_model_`
- `sram_layout_.idxRowBaseAddr()`
- `sram_layout_.idxPilotAddr()`
- `sram_layout_.idxLegacyLookupAddr()`

真实访问来源包括：

- GCSS legacy lookup
- IDX2 lookup
- pre-MPHF lookup
- row metadata read

### 6.3 object 2：`weight_value_store`

真实 runtime structure 是：

- `l0_sram_model_`
- `sram_layout_.l0SlotAddr()`

真实访问来源包括：

- `noteL0SramLookup_`
- `noteL0SramFill_`
- `noteL0SramEvict_`

### 6.4 为什么这里只能算中等绑定

因为它们虽然有真实 owner，也有真实 stall 闭环，但同时存在一个结构性断层：

- local object 被注册为 `PerPe`
- runtime owner 实际上是 **每个 core 各有一份 `WMS`**
- 每个 `WMS` 各自维护自己的 `idx_sram_model_ / l0_sram_model_`

所以 today 真正存在的不是：

- `PE-shared weight idx store`
- `PE-shared weight value store`

而是：

- **`PE-scoped object names` over `per-core private storage-accounting instances`**

### 6.5 这意味着什么

today 还不存在以下能力：

- 跨 core 的统一 bank/port 仲裁
- 跨 core 的统一 resident capacity
- 跨 core 的统一 object occupancy
- object 级的共享时序竞争

也就是说，`weight_idx_store` / `weight_value_store` 现在更像：

- **未来 shared weight storage plane 的命名空间**

而不是已经成立的共享物理平面。

---

## 7. Shared Residency：`weight_value_store` 的第二 owner 还没有并进来

`weight_value_store` today 实际上已经被两个不同层次的东西“共同指向”：

1. `l0_sram_model_`
   - per-core value-side local model
2. `PulseSeededLineResidency`
   - cross-consumer shared seeded residency semantic prototype

这意味着：

- `weight_value_store` today 是一个 **split binding object**

### 7.1 为什么 `PulseSeededLineResidency` 不能算正式 owner

因为它仍缺少正式 local object contract：

- 没有 bank geometry
- 没有 port geometry
- 没有 capacity arbitration
- 没有 refill / eviction lifecycle
- 没有把资源压力回写成 local-store stall

因此它只能算：

- **shared value residency 的语义 owner**

而不是：

- **formal local storage owner**

### 7.2 对未来设计的直接含义

后续如果要把 `weight_value_store` 做成真正的 `PE-shared` 对象，就必须明确回答：

- 它只承接 `l0_sram_model_` 这一层；
- 还是要把 `PulseSeededLineResidency` 一起收编进去。

这会直接决定未来 `weight_value_store` 是：

- `private cache-like proxy`
还是
- `shared residency + private view`

---

## 8. Activation Plane：目前只有 mirror，没有稳定 runtime owner

### 8.1 object：`activation_ingress_store`

当前最接近的 owner 是：

- `PeSharedCoreFabric`

最接近的 runtime structure 是：

- `ingress_mirror_`

它记录：

- ingress occupancy
- ingress peak
- bypass pressure

但 today 这条线仍然只是：

- mirror / observe / stats

而不是：

- 实际驱动 token life-cycle 的 ingress queue

因此：

- `activation_ingress_store` today 只有 **weak binding**

### 8.2 object：`activation_core_queue.coreX`

今天有两个“看起来像 owner”的候选：

1. `PeSharedCoreFabric::core_queue_mirrors_[core]`
   - 只是 queue mirror
2. `SnnWorkload::incoming_spikes_`
   - 只是历史兼容字段

更关键的是：

- 在当前 `workload=snn` 文件中，没有找到稳定的 `incoming_spikes_` enqueue 路径
- 真正的 `incoming_spikes_.push(spike)` 仍出现在 legacy `SnnPESubComponent_spike.cc`

这说明 today 在新 workload 路径里：

- **`activation_core_queue.coreX` 没有稳定、唯一、活跃的 runtime owner**

因此更准确的结论是：

- `activation_core_queue.coreX` = weak-to-none binding

### 8.3 这条线的 today 事实

activation plane 目前最真实的执行语义仍然是：

- packet / spike delivery
- workload direct processing
- fabric mirror / bypass / harbor observe

而不是：

- formalized local activation queue hierarchy

---

## 9. Accumulator Plane：有逻辑 owner，没有 banked local-store owner

### 9.1 object

- `accumulator_store.coreX`

### 9.2 today owner

- `AccumulatorOps`

内部结构包括：

- `acc_dense_`
- `acc_delta_`
- `acc_touched_bitmap_`
- `acc_touched_list_`
- `acc_spill_log_`

### 9.3 为什么这里只是 weak binding

因为 `AccumulatorOps` today 提供的是：

- dense/sparse accumulator logic
- high-watermark spill logic
- deterministic collect/merge behavior

但它不提供：

- bank geometry
- read/write/update port arbitration
- `BankedSramModel` pressure
- local-store stall budget

所以它今天更接近：

- **algorithmic state owner**

而不是：

- **formal local storage owner**

这意味着 `accumulator_store.coreX` today 仍然只是：

- 命名空间先于执行面

---

## 10. Register File Plane：today 找不到 runtime consumer

### 10.1 object

- `register_file.coreX`

### 10.2 search result

在以下 today 主路径相关代码中，没有找到明确 runtime consumer：

- `compute/`
- `services/workload/snn/`
- `services/synapse/weights/`

因此 today 最稳妥的结论只能是：

- **`register_file.coreX` 没有已知稳定 owner**

这条对象当前只适合被视为：

- future microarchitectural placeholder

---

## 11. 正式 owner 视角表

### 11.1 `DefaultSnnComputeCore`

| owner | owned object | access type | real stall? | binding verdict |
| --- | --- | --- | --- | --- |
| `DefaultSnnComputeCore` | `state_store.coreX` | read/write/update neuron state | yes | strong |

### 11.2 `WeightMemorySubsystem`

| owner | owned object | access type | real stall? | binding verdict |
| --- | --- | --- | --- | --- |
| `WeightMemorySubsystem` | `weight_idx_store` | metadata/index read | yes | medium |
| `WeightMemorySubsystem` | `weight_value_store` | l0 lookup/fill/evict | yes | medium |
| `WeightMemorySubsystem` | `weight_value_store` | shared seeded residency | no formal stall | weak |

### 11.3 `PeSharedCoreFabric`

| owner | owned object | access type | real stall? | binding verdict |
| --- | --- | --- | --- | --- |
| `PeSharedCoreFabric` | `activation_ingress_store` | ingress occupancy mirror | no | weak |
| `PeSharedCoreFabric` | `activation_core_queue.coreX` | core queue occupancy mirror | no | weak |

### 11.4 `SnnWorkload`

| owner | owned object | access type | real stall? | binding verdict |
| --- | --- | --- | --- | --- |
| `SnnWorkload` | `activation_core_queue.coreX` | legacy-like spike queue shell | no | weak-to-none |

### 11.5 `AccumulatorOps`

| owner | owned object | access type | real stall? | binding verdict |
| --- | --- | --- | --- | --- |
| `AccumulatorOps` | `accumulator_store.coreX` | logical acc state update/spill | no banked stall | weak |

---

## 12. today binding 的三条核心规则

为了让后续讨论不再语义漂移，建议把 today binding 规则收敛成以下三条：

### 规则 1

- **只有当 object 有稳定 runtime owner，且 owner 的访问会回写为真实 pressure/stall 时，才可称为“runtime-bound local object”。**

按这个标准，today 只有：

- `state_store.coreX`

是完全成立的。

### 规则 2

- **如果 object 是 `PerPe`，但 runtime owner 仍是每 core 一份私有执行实例，则该对象不能被视为已共享。**

按这个标准：

- `weight_idx_store`
- `weight_value_store`

today 都还不是 formal shared object。

### 规则 3

- **mirror / observe / registry / algorithmic state 不应被误写成 formal storage owner。**

按这个标准：

- `PeSharedCoreFabric` mirror
- `PulseSeededLineResidency`
- `AccumulatorOps`
- `incoming_spikes_`

都还只能算弱 owner 或语义 owner。

---

## 13. 对下一阶段设计最直接的指引

### 13.1 若目标是先做最稳的 storage-plane 收敛

最稳的第一跳不是去碰 activation，而是先解决：

- `weight_idx_store`
- `weight_value_store`

的 scope mismatch。

因为这两者已经具备：

- 真实 hot-path owner
- 真实访问
- 真实 stall

只是还没有被提升到 `PerPe shared execution contract`。

### 13.2 若目标是先建立 PE-shared activation/storage 平面

那么必须先补的不是 bank 模型，而是：

- `activation_ingress_store`
- `activation_core_queue.coreX`

的稳定 runtime owner

否则 activation plane 连正式 binding table 都写不稳。

### 13.3 若目标是论文叙事

这份表能支持一个很重要的 today claim：

- 当前仓库中的 `PE local storage hierarchy` 仍是 **partially bound hierarchy**

即：

- object plane 已经被命名；
- runtime owners 只覆盖了一部分；
- 真正 shared 的 weight/value/state/activation/storage contract 还没有统一起来。

---

## 14. 最终结论

today 的 `runtime owner -> local object` 绑定状态，不是完整收敛，而是：

- **`state_store.coreX`：strong, aligned**
- **`weight_idx_store / weight_value_store`：medium, widened**
- **`activation_ingress_store / activation_core_queue.coreX / accumulator_store.coreX`：weak**
- **`register_file.coreX`：none**

因此，当前最准确的结论不是“PE 内 local storage hierarchy 已经存在”，而是：

- **`PE local storage object hierarchy` 已存在；**
- **`runtime owner hierarchy` 只覆盖了其中一部分；**
- **二者之间的正式绑定表现在才第一次被压实。**

这份 binding table 的价值在于，它把后续任何实现路线都变成了一个明确问题：

- 我们到底是要新增 object，
- 还是要迁移 owner，
- 还是要把已有 owner 提升为真正的 `PerPe` shared contract。
