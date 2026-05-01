# PE 内部存储映射审阅：WMS internal storage model vs. PE local storage object model（2026-03-21）

> 日期：2026-03-21  
> 状态：mapping review v1  
> 目标：把当前代码中 `WMS internal storage model`、`compute-core state SRAM model` 与 `PE local storage object model` 之间的真实对应关系压实，明确哪些是强映射、哪些是弱映射、哪些今天根本没有运行时映射。

---

## 0. 这份文档回答什么问题

上一份 baseline 文档已经把 today 的 `PE` 内部架构收敛成：

- `B0 = per-core private execution + PE-scoped shared helpers/providers + WMS-internal shared service semantics`

但还缺一块很关键的基础工作：

- **`WMS` 里真实在跑的存储模型，和 `LocalStorageHierarchyController` 里注册出来的 `PE` 对象，到底怎么对应？**

这件事必须单独澄清，因为当前仓库同时存在两套“本地存储”叙事：

1. **执行层叙事**  
   `WMS` / `DefaultSnnComputeCore` 已经有真实的 `BankedSramModel + VirtualSramLayout + stall budget` 闭环；

2. **对象层叙事**  
   `LocalStorageHierarchyController` 已经注册了
   - `activation_ingress_store`
   - `weight_idx_store`
   - `weight_value_store`
   - `state_store.coreX`
   - `activation_core_queue.coreX`
   - `accumulator_store.coreX`
   - `register_file.coreX`

如果不把这两层对齐，我们后续讨论“共享存储”“PE 内 local store”“runtime storage plane”时就会反复混淆：

- 对象是否存在；
- 运行时是否真正使用；
- 资源是否真的共享；
- stall 是否真的来自该对象。

---

## 1. 一句话结论

当前代码中的存储映射应收敛为一句话：

- **`state_store` 有强映射，`weight_idx/value_store` 有语义映射但存在 scope 断裂，其余 local storage 对象大多仍停留在命名空间层。**

更具体地说：

1. **`state_store.coreX` ↔ `DefaultSnnComputeCore::state_sram_model_`**
   - 这是今天最强、最干净的一组映射；

2. **`weight_idx_store` ↔ `WMS::idx_sram_model_`**  
   **`weight_value_store` ↔ `WMS::l0_sram_model_`**
   - 语义上能对上；
   - 但对象层声称它们是 `PerPe`，执行层却仍然是 **每个 core 一份私有 `BankedSramModel`**；

3. **`activation_ingress_store` / `activation_core_queue` / `accumulator_store` / `register_file`**
   - 目前仍主要是 object registration；
   - 尚未形成与 today runtime dataflow 一一对应的 `local storage execution contract`。

因此，今天并不存在一个统一的：

- `PE-shared storage plane`

真实存在的是：

- **compute-state 路径已有 per-core 强映射；**
- **weight 路径已有语义映射但仍是 per-core proxy；**
- **其余对象大多还没有 runtime owner。**

---

## 2. 证据来源与代码锚点

本审阅主要基于以下代码：

- `services/local_storage/LocalStorageTypes.h`
- `services/local_storage/LocalStorageHierarchyController.h`
- `services/local_storage/LocalStorageHierarchyController.cc`
- `components/multicore/MultiCorePEConfig.cc`
- `components/MultiCorePE.h`
- `components/MultiCorePE.cc`
- `services/synapse/weights/WeightMemorySubsystem.h`
- `services/synapse/weights/WeightMemorySubsystem.cc`
- `services/memory/sram_sim/layout/VirtualSramLayout.h`
- `services/memory/sram_sim/model/BankedSramModel.h`
- `compute/SnnComputeCore.h`
- `compute/SnnComputeCore.cc`
- `services/workload/snn/SnnWorkload.h`
- `services/workload/snn/SnnWorkload.cc`
- `services/synapse/gas/AccumulatorOps.h`
- `services/synapse/gas/AccumulatorOps.cc`

---

## 3. PE local storage object model：今天到底定义了什么

`LocalStorageHierarchyController` 当前是一个 **Phase A object registry**。  
它定义的是：

- 对象类型：`AddressableStore` / `QueueStore` / `RegisterFile`
- 对象 scope：`PerCore` / `PerPe`
- 对象属性：
  - `capacity_bytes`
  - `banks`
  - `read_ports`
  - `write_ports`
  - `update_ports`
  - `queue_depth`
  - `entries`
  - `entry_bytes`

`MultiCorePE` 当前注册的默认对象为：

- `activation_ingress_store`：`QueueStore`, `PerPe`
- `weight_idx_store`：`AddressableStore`, `PerPe`
- `weight_value_store`：`AddressableStore`, `PerPe`
- `state_store.coreX`：`AddressableStore`, `PerCore`
- `activation_core_queue.coreX`：`QueueStore`, `PerCore`
- `accumulator_store.coreX`：`AddressableStore`, `PerCore`
- `register_file.coreX`：`RegisterFile`, `PerCore`

这套模型今天的真实能力只有两类：

1. **对象注册 / 快照统计**
2. **为未来运行时迁移预留命名空间**

它今天还不负责：

- request scheduling
- bank arbitration
- port allocation
- refill / eviction
- residency lifecycle
- 与 `WMS` / compute core 的真实执行绑定

因此，它首先是一个 **object model**，而不是一个已经生效的 storage controller。

---

## 4. WMS internal storage model：今天真正跑起来的是什么

### 4.1 `idx_sram_model_`

`WeightMemorySubsystem` 在 orchestrator 配置中会创建：

- `VirtualSramLayout sram_layout_`
- `BankedSramModel idx_sram_model_`
- `BankedSramModel l0_sram_model_`

其中 `idx_sram_model_` 负责的是：

- GCSS / IDX2 lookup
- row-base / row-len / bucket-count / seed / bucket-offset 访问
- pre-MPHF `pre_base / pre_len` lookup
- pilot / legacy slot 访问

也就是说，`idx_sram_model_` 表示的是：

- **weight metadata / index-side local storage**

而不是 value data 本身。

### 4.2 `l0_sram_model_`

`l0_sram_model_` 负责：

- `noteL0SramLookup_`
- `noteL0SramFill_`
- `noteL0SramEvict_`

对应的是：

- value-side L0 / ingress value cache 行为
- 哈希 slot 化的 `l0SlotAddr(key)`

它表示的是：

- **weight value-side local residency / cache-like store**

### 4.3 `WMS` 的 stall 闭环

`WMS::onClockTick()` 每拍会：

1. 调用 `idx_sram_model_.onClockTick(now_cycle_)`
2. 调用 `l0_sram_model_.onClockTick(now_cycle_)`
3. 取出 `consumeLastCyclePredictedExtraCycles()`
4. 累加到 `weight_sram_stall_budget_cycles_`
5. 在后续 issue / drain 路径上消耗这个 stall budget

所以 `idx/l0` 两个模型不是纯统计，而是已经能反压 today 热路径。

### 4.4 `WMS` 中不属于 local storage object 的东西

需要特别切开的是，`WMS` 里还有很多“像存储”的对象，但今天不应直接映射为 `LocalStorageHierarchyController` 对象：

- `row_index_prefetch_rows_`
- `experimental_idx2_ingress_pending_addrs_`
- `gcss_vlf_issue_queue_`
- `pending_colidx_reads_`
- `pending_block_reads_`
- `pending_direct_reads_`

这些更准确地说是：

- **issue/deferred/replay queues**

而不是本地存储阵列本身。

---

## 5. compute-core state SRAM model：`state_store` 的真实运行时归属

`state_store` 今天不在 `WMS`，而在：

- `compute/DefaultSnnComputeCore`

`DefaultSnnComputeCore` 会创建：

- `VirtualSramLayout state_sram_layout_`
- `BankedSramModel state_sram_model_`

并对以下地址空间记账：

- `stateVmemAddr(neuron_idx)`
- `stateRefracAddr(neuron_idx)`
- `stateLastSpikeAddr(neuron_idx)`

同时在：

- `updateNeuronStates()`
- `applyPendingDeltas_()`
- `fire()`

这些路径上产生 read/write，并把 bank conflict 折成：

- `state_sram_stall_budget_`

最终影响：

- `endCycle()`
- `endCycleCandidates()`
- `hasWork()`

这说明：

- **`state_store` 的 today runtime owner 是 compute core，而不是 `WMS`。**

这点非常重要，因为它意味着“PE local storage 映射”必须至少分成两张表：

1. `weight/service plane` 映射
2. `state/compute plane` 映射

不能只盯着 `WMS`。

---

## 6. 参数别名与启用条件：对象存在不等于运行时使用

`MultiCorePEConfig` 已经把旧参数映射到新 `ls_*` 命名空间：

- `ls_state_*` 默认兼容 `state_sram_*`
- `ls_weight_idx_*` 默认兼容 `weight_idx_sram_*`
- `ls_weight_value_*` 默认兼容 `weight_l0_sram_*`

但这里存在一个很关键的 today 断层：

### 6.1 `state_store`

- `state_store` 对象能否被注册，取决于 `ls_state_enable` 或 `state_sram_enable/capacity`
- 但 compute core 真正是否产生 state SRAM 访问，还取决于：
  - `state_sram_enable`

也就是说：

- **对象注册成功 != compute core 一定会访问它**

### 6.2 `weight_idx_store` / `weight_value_store`

- `LocalStorage` 对象能否被注册，兼容路径取决于：
  - `weight_sram_model_enable`
  - `weight_idx_sram_enable`
  - `weight_l0_sram_enable`
  - 以及 `ls_weight_*` 显式参数

但 `WMS` 真正是否使用 `idx_sram_model_ / l0_sram_model_`，仍取决于：

- `weight_sram_model_enable`
- `weight_idx_sram_enable`
- `weight_l0_sram_enable`

因此今天同样成立：

- **对象被注册 != WMS 一定在 runtime 中消费该对象**

这个差异解释了为什么今天 `LocalStorageHierarchyController` 更像 object namespace，而不是 runtime storage truth source。

---

## 7. 正式映射表

### 7.1 强映射

| PE local storage object | today runtime owner | today runtime structure | 映射强度 | 备注 |
| --- | --- | --- | --- | --- |
| `state_store.coreX` | `DefaultSnnComputeCore` | `state_sram_model_` + `state_sram_layout_` | 强 | scope 一致，且 stall 闭环真实生效 |

### 7.2 语义映射但存在 scope 断裂

| PE local storage object | today runtime owner | today runtime structure | 映射强度 | 备注 |
| --- | --- | --- | --- | --- |
| `weight_idx_store` | `WeightMemorySubsystem` | `idx_sram_model_` + `sram_layout_.idx*` | 中 | 对象层是 `PerPe`，执行层是每 core 一份私有模型 |
| `weight_value_store` | `WeightMemorySubsystem` | `l0_sram_model_` + `sram_layout_.l0*` | 中 | 同样是 `PerPe object` vs `per-core runtime proxy` |

### 7.3 部分映射 / 暂无正式对象归属

| runtime structure | 最接近的 local storage object | 映射强度 | today 判断 |
| --- | --- | --- | --- |
| `PulseSeededLineResidency` | `weight_value_store` | 弱 | 语义上像共享 value residency，但未计入 `l0_sram_model_`，也未注册成独立 object |
| `PulseSharedLineService` waiters / fanout | 无 | 无 | 属于 service coordination，不是 storage object |
| `pending_direct_reads_` / `pending_block_reads_` / `pending_colidx_reads_` | 无 | 无 | 属于 issue/deferred queue，不是 storage array |
| `gcss_vlf_issue_queue_` | 无 | 无 | 属于 issue agenda，不是 storage object |
| `row_index_prefetch_rows_` / `experimental_idx2_ingress_pending_addrs_` | 无 | 无 | 属于 prefetch work queue，不是 local store |

### 7.4 local storage 对象中 today 没有 WMS 映射的部分

| PE local storage object | today runtime owner | today 真实状态 |
| --- | --- | --- |
| `activation_ingress_store` | `PeSharedCoreFabric` / ingress mirror 语义 | 目前仍是 observe/mirror/queue-depth 命名空间，不是 WMS 对象 |
| `activation_core_queue.coreX` | `SnnWorkload::incoming_spikes_` / fabric-side queue mirror | 目前没有统一 bank/port/stall 模型 |
| `accumulator_store.coreX` | `AccumulatorOps` | 逻辑 dense/sparse/spill 状态，尚非 `BankedSramModel` |
| `register_file.coreX` | 无明确 runtime owner | 目前仅对象层存在 |

---

## 8. 当前映射里最重要的三个结构性问题

### 8.1 `PerPe object` vs `per-core runtime proxy`

这是当前 weight-side 映射里最重要的断层：

- `weight_idx_store`
- `weight_value_store`

在 `LocalStorageHierarchyController` 中被定义成：

- `PerPe`

但 today 真正的执行模型却是：

- 每个 core 各自持有一个 `WMS`
- 每个 `WMS` 各自持有一个 `idx_sram_model_`
- 每个 `WMS` 各自持有一个 `l0_sram_model_`

因此 today 的真实语义不是：

- `PE-shared weight store`

而是：

- **`PE-scoped object name` over `per-core storage accounting instances`**

这会直接导致：

1. 不存在跨 core 的 bank/port 仲裁；
2. 不存在跨 core 的共享容量压力；
3. `PE` 级对象统计不能直接解释真实 runtime contention。

### 8.2 shared residency 没有进入 storage plane

`PulseSeededLineResidency` 已经表现得非常像一个：

- shared value residency

但它今天仍是：

- static registry
- `line_addr -> bytes`
- 无 bank/port/capacity lifecycle

因此它还没有真正进入：

- `weight_value_store`

这意味着“value-side shared service”与“value-side local storage”今天仍然是分裂的。

### 8.3 object existence 与 runtime consumption 脱节

今天 `LocalStorageHierarchyController` 能告诉我们：

- 哪些对象被注册；
- 名义容量/端口/队列深度是多少；

但不能告诉我们：

- 哪个 runtime path 真正落在该对象上；
- 某次 stall 到底来自哪个 local object；
- 哪个 object 的 budget 被跨 core 共享掉了。

所以它今天还不是一个可以驱动实验解释的单一真源。

---

## 9. 对后续设计最有价值的结论

### 9.1 未来若要统一 storage plane，必须分两条线推进

第一条线：

- `compute core state plane`
- 把 `state_sram_model_` 正式接到 `state_store.coreX`

第二条线：

- `WMS weight/service plane`
- 把 `idx_sram_model_ / l0_sram_model_ / shared residency`
- 正式收敛成 `weight_idx_store / weight_value_store`

### 9.2 `weight_value_store` 不应只等价于 `l0_sram_model_`

因为 today 的 value-side 实际上已经分成两部分：

1. `l0_sram_model_`
   - per-core value cache proxy
2. `PulseSeededLineResidency`
   - cross-demand / cross-consumer shared residency semantic prototype

所以未来真正的 `weight_value_store` 若要成立，必须明确：

- 它只承接 per-core value cache；
- 还是同时承接 shared seeded residency。

### 9.3 `LocalStorageHierarchyController` 下一阶段最重要的不是“注册更多对象”

而是：

- 建立 **runtime owner -> local object** 的正式绑定表；
- 建立 **stall source -> local object** 的正式归因；
- 建立 **scope(real execution) vs scope(object namespace)** 的一致性约束。

否则即便对象更多，也仍然只是更大的 registry。

---

## 10. 最终结论

当前 `WMS internal storage model` 与 `PE local storage object model` 的关系，不是“一一对应”，而是：

- **一部分强映射**
- **一部分语义映射但 scope 断裂**
- **一部分根本还没有 runtime object owner**

最关键的 today 事实有三条：

1. `state_store.coreX` 已有清晰运行时映射，owner 是 `DefaultSnnComputeCore`；
2. `weight_idx_store / weight_value_store` 能与 `WMS idx/l0 SRAM` 对上语义，但 today 仍是 `PerPe object` 对 `per-core proxy model`；
3. `PulseSeededLineResidency`、各类 pending queues、accumulator/activation/rf 仍未形成统一 storage-plane contract。

所以今天我们还不能说仓库里已经存在一个统一的 `PE local storage hierarchy`。  
更准确的说法是：

- **仓库已经拥有 local storage object namespace、compute-state local model、WMS weight-side local model，以及 shared residency semantic prototype；**
- **但它们还没有被收敛为同一个 runtime storage plane。**
