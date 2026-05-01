# SnnDL 片上本地存储层级控制器设计（SNN First）

Date: 2026-03-11
Owner: Fufu
Status: Draft

## 1. 背景

当前 `SnnDL` 已经有若干“本地存储相关能力”，但它们仍是分散且不完整的：

- `compute/SnnComputeCore` 有 `state_sram`，但本质是 `BankedSramModel` + `stall budget`；
- `services/synapse/weights/WeightMemorySubsystem` 有 `weight_idx_sram` / `weight_l0_sram`，但仍是 observe-first、无显式 miss/refill/evict；
- `services/synapse/gas/AccumulatorOps` 自己维护 dense/sparse/spill 逻辑，但不是统一的硬件存储对象；
- `services/workload/tensor/TensorWorkload` 已经内置 `UB/ACC/weight pool` 容量、bank、queue、spill 模型，但完全留在 workload 内部，无法被 `snn` 共享；
- `components/GatherBufferIF` 已经有 `sram_blocks`、occupancy、LRU 等局部 scratchpad 行为，但只覆盖 GAS gather buffer，既不统一也不覆盖 state/weight/activation/accumulator/RF；
- `activation` 与 `register file` 目前没有作为显式本地硬件对象存在。

这意味着当前仿真器还没有一个真正的“片上本地存储层级”：

- 没有统一的容量与驻留（residency）真值；
- 没有显式 bank/port/request queue；
- 没有标准化 refill/evict/spill 生命周期；
- 没有把 `weight/state/activation/accumulator/register file` 统一建模为可组合硬件对象。

如果继续在 `BankedSramModel` 上叠加更多参数，只会把“统计器”变成越来越复杂的代理模型，仍然无法成为真正的 local storage hierarchy。

因此，本设计选择引入一层新的 **Local Storage Hierarchy Controller**，将本地存储从“分散的 stall-budget 近似”升级为“显式对象 + 显式队列 + 显式驻留 + 显式 refill/evict/spill”的硬件层。

## 2. 设计目标

本设计的目标是：

1. 把 `weight/state/activation/accumulator/register file` 全部建成显式硬件对象；
2. 对每个对象显式建模：
   - capacity
   - line/granule
   - residency
   - bank
   - read/write/update port
   - request queue depth
   - refill
   - evict / writeback
   - spill
3. 先只服务 `SNN workload`，但抽象从第一天就兼容后续 `tensor UB / tensor ACC / tensor weight pool`；
4. 保持 `services/memory` 的纯字节语义边界，不把权重/突触解释塞回 memory 域；
5. 保持默认兼容性：
   - 新机制默认关闭；
   - 关闭时保持当前行为；
   - 现有 `state_sram_*` / `weight_*_sram_*` 统计口径可兼容迁移。

## 3. 非目标

本设计当前不做以下事情：

- 不在 Phase A 中把 `tensor` workload 迁移到新框架；
- 不把本地存储直接做成新的 SST 元件或独立时钟域组件；
- 不把 `memHierarchy` / `ramulator2` 后端接口重写掉；
- 不做 cache coherence；
- 不引入“自动硬件 cache”语义作为默认行为。

默认语义是 **software-managed scratchpad hierarchy**，而不是 CPU-style cache hierarchy。

## 4. 设计原则

### 4.1 SNN First，但不是 SNN Only

Phase A 只接 `workload_impl=snn`，但接口必须让未来 `tensor_ub / tensor_acc / tensor_weight_pool` 可以直接复用，而不是再写第二套。

### 4.2 逻辑对象与物理阵列分离

必须区分：

- **逻辑对象**：`state_store`、`weight_idx_store`、`weight_value_store`、`activation_store`、`accumulator_store`、`register_file`
- **物理阵列**：真实 banked SRAM / queue SRAM / register file 阵列

逻辑对象是上层语义边界，物理阵列是底层时序与资源边界。

`GatherBufferIF` 可以被视为项目内“局部 scratchpad 行为”的先行样本，但它的职责太窄，不适合作为统一 local storage hierarchy 的直接基类；更合理的做法是把其可复用经验（容量水位、块占用、evict 统计）吸收进新的通用平台层。

### 4.3 Memory 域继续纯字节化

`services/memory` 继续只处理：

- `addr + bytes`
- pending request
- StandardMem callback

本地存储层级不再放进 `services/memory/README.md` 所定义的“纯 memory 语义”边界中，而是新增为独立平台层服务：

- 推荐目录：`services/local_storage/`

它可以依赖 `IMemoryAccess` 做 refill/writeback，但不能把 `weight/synapse/bcsr` 解析逻辑塞进底层。

### 4.4 默认显式管理，非默认替换策略

`state`、`weight`、`activation`、`accumulator` 在 accelerator 上更接近 scratchpad，而不是透明 cache。

因此默认采用：

- region pin / release
- window prefetch
- block refill
- explicit spill

仅在未来 generic/tensor 模式下，才开放 LRU/FIFO 这类通用替换策略作为补充。

### 4.5 默认关闭，老路径保持不变

- `local_storage_enable=0`：继续走现在的 `state_sram stall budget`、`weight_*_sram stall budget`、`AccumulatorOps` 现有逻辑；
- `local_storage_enable=1`：启用新层级控制器；
- 旧参数作为兼容 alias 保留。

## 5. 为什么不是继续扩展 BankedSramModel

`BankedSramModel` 的定位仍应是：

- bank pressure estimator
- compatibility/legacy timing backend
- 统计与快速估算工具

它不适合承担下面这些职责：

- directory / residency truth
- miss queue
- fill replay
- dirty victim writeback
- spill engine
- per-object arbitration
- queue backpressure

因此本设计不让 `BankedSramModel` 继续演化成“大一统控制器”，而是把它保留为：

- `legacy path`
- 或未来 `estimator backend`

真正的控制器由新平台层承担。

## 6. 参考架构与外部依据

本方案参考了三类成熟范式：

1. **SST memHierarchy / StandardMem**
   - 继续把 off-chip refill / writeback 保持为 `StandardMem` 风格的字节请求；
   - 不在 Phase A 引入新的 scratchpad SST component，而是维持 SnnDL 内部微结构对象。
2. **Timeloop 的 storage hierarchy 描述**
   - 明确区分多级 storage、每级容量、带宽、bank、端口、实例数；
   - 本地对象与 backing store 构成树状层级。
3. **NVDLA 的 CBUF / CACC / regfile 风格**
   - weight/activation buffer 与 accumulator 分离；
   - accumulator 具备独立 buffering、吞吐平滑、prefetch/drain 语义；
   - regfile 与大容量 buffer 分工不同。

这些外部体系结构都支持一个共同结论：**把不同职责的数据对象强行揉成一个“泛 SRAM stall 参数”是不合理的**。

## 7. 总体架构

### 7.1 顶层视图

```text
off-chip DRAM / memHierarchy / ramulator2
                ^
                | refill / writeback
                | (IMemoryAccess / StandardMem / PE DMA)
+---------------------------------------------------------------+
| LocalStorageHierarchyController (per PE)                      |
|                                                               |
|  - object scheduler                                           |
|  - bank/port arbitration                                      |
|  - residency directory                                        |
|  - refill/evict engine                                        |
|  - spill engine                                               |
|  - phase-aware priority policy                                |
|                                                               |
|  PE-shared optional objects                                   |
|  - activation_ingress_store                                   |
|  - weight_idx_store / weight_value_store (shared or partition)|
|                                                               |
|  Per-core objects                                             |
|  - state_store[c]                                             |
|  - activation_core_queue[c]                                   |
|  - accumulator_store[c]                                       |
|  - register_file[c]                                           |
+---------------------------------------------------------------+
```

### 7.2 控制平面与数据平面

新层级分成两类接口：

- **控制平面**
  - `reserveRegion`
  - `pinRegion`
  - `prefetchRegion`
  - `releaseRegion`
  - `flushRegion`
  - `setPhase`
- **数据平面**
  - `read`
  - `write`
  - `update`
  - `enqueue`
  - `dequeue`
  - `loadToRf`
  - `storeFromRf`

也就是说，上层模块不再直接维护 occupancy / spill / refill 细节，而是只声明：

- 这个 region 需要驻留；
- 这个对象要访问哪些地址/条目；
- 这个阶段的优先级是什么。

### 7.3 目录建议

建议新增：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/`

建议的最小文件集合：

- `LocalStorageTypes.h`
- `LocalStorageHierarchyController.{h,cc}`
- `LocalStorageObject.{h,cc}`
- `LocalStorageArray.{h,cc}`
- `LocalStorageDirectory.{h,cc}`
- `LocalStorageRefillEngine.{h,cc}`
- `LocalStorageSpillEngine.{h,cc}`
- `LocalStorageStats.h`

语义适配层放在各自业务域中，而不是都塞进 `services/local_storage/`：

- `compute/`：state client
- `services/synapse/weights/`：weight client
- `services/stimulus/`：activation client
- `services/synapse/gas/`：accumulator backend adapter

## 8. 核心对象模型

### 8.1 基础类型

#### `LocalStorageObjectKind`

- `AddressableStore`
- `QueueStore`
- `RegisterFile`

#### `LocalStorageScope`

- `per_core`
- `per_pe`

#### `LocalStorageOp`

- `read`
- `write`
- `update`
- `enqueue`
- `dequeue`
- `refill`
- `evict`
- `spill`
- `load_to_rf`
- `store_from_rf`

### 8.2 关键配置结构

#### `LocalStorageObjectConfig`

每个对象至少包含：

- `name`
- `kind`
- `scope`
- `capacity_bytes`
- `line_bytes`
- `entry_bytes`
- `banks`
- `read_ports_per_bank`
- `write_ports_per_bank`
- `update_ports_per_bank`
- `queue_depth`
- `bank_select_policy`
- `replacement_policy`
- `residency_mode`
- `refill_policy`
- `evict_policy`
- `spill_policy`
- `high_watermark`
- `low_watermark`
- `backend_class`
- `energy_read_pj`
- `energy_write_pj`

### 8.3 请求结构

#### `LocalStorageRequest`

建议字段：

- `req_id`
- `client_id`
- `core_id`
- `object_id`
- `op`
- `addr_or_key`
- `bytes`
- `logical_region_id`
- `phase`
- `priority`
- `submit_cycle`
- `allow_miss`
- `needs_dirty_tracking`
- `completion_cb`

#### `LocalRegionDesc`

用于显式 region 驻留控制：

- `region_id`
- `backing_addr`
- `bytes`
- `granule_bytes`
- `residency_unit`
- `pin_mode`
- `dirty_mode`
- `prefetch_distance`

## 9. 物理对象与推荐默认拓扑

### 9.1 默认对象拓扑

| 对象 | 默认 scope | 默认 kind | 真值持有者 | refill 来源 | evict / spill 去向 | Phase A |
| --- | --- | --- | --- | --- | --- | --- |
| `state_store` | per_core | AddressableStore | 本地 state working set | StandardMem read backend | StandardMem writeback | 完整接入 |
| `weight_idx_store` | per_core logical / per_pe physical optional | AddressableStore | off-chip weights | PE DMA / StandardMem | clean evict | 完整接入 |
| `weight_value_store` | per_core logical / per_pe physical optional | AddressableStore | off-chip weights | PE DMA / StandardMem | clean evict | 完整接入 |
| `activation_ingress_store` | per_pe | QueueStore | stimulus / noc ingress | stimulus / noc | consume / backpressure | 完整接入 |
| `activation_core_queue` | per_core | QueueStore | ingress store copy | ingress transfer | consume | 完整接入 |
| `accumulator_store` | per_core | AddressableStore | local partial sums | local updates | spill store / scatter drain | 完整接入 |
| `register_file` | per_core | RegisterFile | transient operand copy | parent local stores | release / parent writeback | 完整接入 |

### 9.2 为什么这样分

- `state_store` 与 `register_file` 必须 per-core，避免无谓的跨核共享与语义耦合；
- `activation` 最适合做成 “PE ingress + per-core consume queue” 两级结构；
- `weight` 可以逻辑 per-core，但物理上允许 PE 共享 bank fabric，以表达共享 refill 带宽与 bank contention；
- `accumulator` 默认 per-core，后续如需建模跨核合并，再扩展到 `per_pe shared accumulator fabric`。

## 10. 五类对象的详细设计

### 10.1 State Store

#### 10.1.1 职责

存放神经元局部状态：

- `vmem`
- `refrac`
- `last_spike`

这是状态真值所在对象，不再只是统计器。

#### 10.1.2 关键建模

- 访问粒度：单 neuron state field 或小向量 chunk；
- 驻留粒度：**neuron block**，而不是整 PE 或整 cacheline；
- 脏位：需要；
- refill：需要；
- evict/writeback：需要。

#### 10.1.3 推荐策略

- 当 `state_store_capacity >= local_state_bytes` 时：
  - 初始化后长期常驻；
  - 只建模 bank/port/queue/latency。
- 当容量不足时：
  - 以 `neuron block` 为 residency unit；
  - 核心在 block 切换点触发 refill / dirty evict；
  - `SnnComputeCore` 不再把状态访问直接记到 `state_sram_model_`，而是通过 `StateStoreClient` 发请求。

#### 10.1.4 重要设计点

state store 不能按“完全透明随机 miss cache”来做。更合适的方式是：

- **block-managed scratchpad**

原因：

- 当前 SNN 的状态更新天然按 neuron index 扫描；
- block 切换有明确边界；
- 这样可以在不破坏功能语义的前提下实现真实容量限制。

### 10.2 Weight Index Store / Weight Value Store

#### 10.2.1 职责

分成两个逻辑对象：

- `weight_idx_store`
  - `rowptr`
  - `colidx`
  - `idx2`
  - `gcss`
  - `diag`
- `weight_value_store`
  - `blockdata`
  - dense weight payload
  - window payload

#### 10.2.2 为什么不再沿用“idx_sram + l0_sram 只是 stall budget”

当前模型没有：

- 哪些 line 在 L0；
- 哪些 request 命中本地；
- 哪些 request 需要 refill；
- 哪些 region 正被 pin 在当前窗口；
- 当前 queue/backpressure 是否阻塞了 apply/gather。

这正是权重路径最需要显式化的部分。

#### 10.2.3 推荐策略

- `weight_idx_store`：
  - 优先保证 metadata 常驻或长寿命驻留；
  - miss 代价高但 dirty tracking 通常不需要；
  - 支持 window-ahead prefetch。
- `weight_value_store`：
  - 以 window chunk / line 为 refill 粒度；
  - 支持 pin 当前窗口与下一窗口双缓冲；
  - 优先复用前面已经设计好的 `PeDmaScheduler` 作为 read refill backend。

#### 10.2.4 后端策略

- 读 refill：
  - 首选 `PE DMA read backend`
  - 回退 `StandardMem read backend`
- evict：
  - 默认 clean evict
  - 不做 writeback

### 10.3 Activation Store

#### 10.3.1 职责

显式建模激活/脉冲在本地的暂存，而不是让 activation 只以“workload 内的隐式 vector/queue”存在。

#### 10.3.2 推荐拓扑

- `activation_ingress_store`（per-PE ring/FIFO）
- `activation_core_queue`（per-core consume queue）

#### 10.3.3 关键建模

- kind：`QueueStore`
- 容量：bytes 或 entries
- enqueue / dequeue ports
- bank（可选，常用于宽入口）
- queue depth
- backpressure mode

#### 10.3.4 refill/evict 语义

activation 在 Phase A 不从 off-chip 读回，因此不做传统 refill。

它的“refill来源”是：

- `StepActivationSubsystem`
- NoC ingress
- 未来的 event router

它的“evict语义”也不是 writeback，而是：

- `consume`
- `backpressure`
- `fail_fast when overflow`（调试选项）

默认不允许 silent drop。

### 10.4 Accumulator Store

#### 10.4.1 职责

把当前 `AccumulatorOps` 里的 dense/sparse/spill 逻辑改造为显式本地对象：

- partial sum resident bytes
- update queue
- bank/update port contention
- spill threshold
- scatter drain

#### 10.4.2 关键建模

- truth holder：`accumulator_store`
- 操作类型：`update(post_id, dv)` 而不是仅仅 `map[post]+=dv`
- 可选模式：
  - `dense`
  - `sparse`
  - `hybrid`
- update 需要建模 bank 冲突与 RMW 代价。

#### 10.4.3 推荐实现策略

不要让 `AccumulatorOps` 继续同时承担：

- 业务接口
- 容量控制
- spill 管理
- bank timing

而是改成：

- `AccumulatorOps` 只保留窗口语义、drain 时机、排序/校验辅助；
- 真正的容量、occupancy、spill、bank/update 端口放入 `AccumulatorStoreController`。

#### 10.4.4 spill 设计

Phase A 建议先支持：

- `accumulator_store`
- `acc_spill_store`

二级本地结构。

也就是说，acc spill 先在片上解决，而不是一开始就把 partial sums 溢写到 off-chip。

只有在后续 Phase 才开放：

- `acc spill to StandardMem`

这样与当前 `AccumulatorOps` 的语义更一致，也更符合 accelerator 习惯。

### 10.5 Register File

#### 10.5.1 职责

RF 是叶子级本地对象，用于建模内层计算的 operand staging，而不是继续把一切都视为“父 store 直接读写”。

#### 10.5.2 推荐建模方式

RF 作为显式对象，具备：

- entry count
- entry bytes
- read ports
- write ports
- optional banking
- live-entry occupancy
- release on retire

#### 10.5.3 语义边界

RF 中的值是 transient copy，不是长期真值。

Phase A 中最合适的做法是：

- 由 `state_store` / `weight_store` / `activation_store` / `accumulator_store` 向 RF 发起 `load_to_rf`
- 计算结束后通过 `store_from_rf` 写回父对象或直接释放

这允许我们显式建模：

- operand fetch latency
- RF 端口冲突
- live register pressure

而不会把所有中间态都硬塞进 compute loop 的“隐式变量”里。

## 11. 对象生命周期与时序模型

### 11.1 单请求生命周期

`LocalStorageRequest` 的标准流程：

1. frontend 接收请求；
2. object controller 查 directory / occupancy；
3. hit：
   - 入 bank queue
   - 消耗端口
   - 在服务完成后回调；
4. miss：
   - 进入 miss queue；
   - 如需 victim，先安排 evict/writeback；
   - 安排 refill；
   - fill 完成后 replay blocked requests；
5. retire 并更新统计。

### 11.2 每拍调度顺序

每个 cycle 建议顺序如下：

1. 接收来自 compute / weight / activation / acc 的新请求；
2. 刷新对象水位线与 phase 优先级；
3. 先处理 hit queue；
4. 再选择 refill/evict/spill issue；
5. 接收 backend response；
6. replay blocked miss；
7. 完成 retire / callback；
8. 更新统计与峰值。

### 11.3 bank/port 模型

每个 `LocalStorageArray` 显式维护：

- `bank_count`
- `read_ports_per_bank`
- `write_ports_per_bank`
- `update_ports_per_bank`
- `queue_depth_per_bank`
- `busy_until`

支持三类冲突：

- bank conflict
- port conflict
- queue full

对应 stall 原因分别统计。

### 11.4 residency 与 replacement

本设计支持三种 residency mode：

- `pinned`
- `managed_scratchpad`
- `managed_cache`

Phase A 的默认配置：

- state：`managed_scratchpad`
- weight_idx：`managed_scratchpad`
- weight_value：`managed_scratchpad`
- activation：`queue_resident`
- accumulator：`managed_scratchpad`
- register_file：`transient`

也就是说，Phase A 不把 `replacement_policy` 当作主导机制，而把它当作兜底机制。

## 12. Phase-aware 优先级策略

新控制器必须感知 GAS / workload phase，否则会出现“prefetch 抢占关键路径”的错误行为。

### 12.1 Gather

优先级建议：

1. activation dequeue / ingress transfer
2. weight_idx refill / lookup
3. weight_value prefetch
4. state background refill

### 12.2 Apply

优先级建议：

1. weight_value read
2. accumulator update
3. register_file load/store
4. 非关键 prefetch

### 12.3 Scatter

优先级建议：

1. accumulator drain
2. state writeback / commit
3. 下一窗口 metadata prefetch

### 12.4 Idle

- 允许低优先级 background refill
- 允许 dirty drain
- 禁止抢占下一轮关键入口

## 13. 与现有模块的边界重划

### 13.1 MultiCorePE

新增职责：

- 构造一个 `LocalStorageHierarchyController`（per PE）；
- 将 controller handle 分发给 core/workload/weight/stimulus；
- 统一推进 `tick()`；
- 汇聚本地存储统计。

### 13.2 SnnComputeCore

从：

- `state_sram_model_`
- `state_sram_stall_budget_`

迁移为：

- `StateStoreClient`
- `RegisterFileClient`

核心变化：

- 不再用 `noteRead/noteWrite + consumeLastCyclePredictedExtraCycles()` 驱动时序；
- 而是把状态访问变成显式 local access；
- block 切换由 state store residency 管理。

### 13.3 WeightMemorySubsystem

从：

- `weight_idx_sram_model_`
- `weight_l0_sram_model_`
- `weight_sram_stall_budget_cycles_`

迁移为：

- `WeightStoreClient`

核心变化：

- WMS 继续保留权重语义与 BCSR 解析；
- 但“命中哪一级本地存储、何时 refill、何时 evict、何时 replay”由 store controller 负责。

### 13.4 StepActivationSubsystem / SnnWorkload

新增职责：

- activation 不再直接进入隐式队列；
- 先写入 `activation_ingress_store`；
- 再按 phase 和 core 目标搬运到 `activation_core_queue`。

### 13.5 AccumulatorOps

重构方向：

- `AccumulatorOps` 从“拥有存储”改成“拥有语义”

即：

- `AccumulatorOps` 管窗口边界、merge/drain 语义、可选 shadow verify；
- `AccumulatorStoreController` 管容量、bank、spill、occupancy、drain 速率。

### 13.6 services/memory

保持不变：

- 仍只做 off-chip / backend 的 `addr <-> bytes`；
- 继续提供 `StandardMemAccess`；
- 不承载本地对象的语义管理。

## 14. 后端接口设计

### 14.1 `ILocalStorageRefillBackend`

建议抽象：

- `submitRead(backing_addr, bytes, completion_cb)`
- `submitWrite(backing_addr, bytes, completion_cb)`
- `pendingSize()`

实现候选：

- `StandardMemRefillBackend`
- `PeDmaReadRefillBackend`

### 14.2 Phase A 的后端选择

- `weight_idx_store` / `weight_value_store` read refill：
  - 首选 `PeDmaReadRefillBackend`
  - fallback `StandardMemRefillBackend`
- `state_store` writeback：
  - 先用 `StandardMemRefillBackend::submitWrite`
  - 不强依赖 DMA write 已经实现
- `accumulator_store`：
  - Phase A 默认不做 off-chip spill
  - 先在本地二级 spill store 内闭环

这样做的原因是：当前 DMA 只对运行期 SNN weight read 建模最成熟，不应强行把 state/acc 写回耦合进去。

## 15. 参数设计

### 15.1 总开关

- `local_storage_enable`
- `local_storage_mode = legacy|explicit`

### 15.2 通用前缀

每个对象使用：

- `ls_<obj>_enable`
- `ls_<obj>_scope`
- `ls_<obj>_capacity_bytes`
- `ls_<obj>_line_bytes`
- `ls_<obj>_banks`
- `ls_<obj>_read_ports`
- `ls_<obj>_write_ports`
- `ls_<obj>_update_ports`
- `ls_<obj>_queue_depth`
- `ls_<obj>_replacement_policy`
- `ls_<obj>_residency_mode`
- `ls_<obj>_backend`

### 15.3 Phase A 重点对象参数

#### state

- `ls_state_block_neurons`
- `ls_state_writeback_enable`
- `ls_state_dirty_high_watermark`

#### weight

- `ls_weight_idx_prefetch_distance`
- `ls_weight_value_prefetch_distance`
- `ls_weight_value_double_buffer`
- `ls_weight_backend = dma|stdmem`

#### activation

- `ls_activation_ingress_entries`
- `ls_activation_core_entries`
- `ls_activation_backpressure_mode = hard|fail_fast`

#### accumulator

- `ls_acc_mode = dense|sparse|hybrid`
- `ls_acc_spill_store_bytes`
- `ls_acc_scatter_ports`

#### register file

- `ls_rf_entries`
- `ls_rf_entry_bytes`
- `ls_rf_read_ports`
- `ls_rf_write_ports`

### 15.4 兼容映射

旧参数保留为 alias：

- `state_sram_* -> ls_state_*`
- `weight_idx_sram_* -> ls_weight_idx_*`
- `weight_l0_sram_* -> ls_weight_value_*`

`apply_dense_acc_enable` 等现有 accumulator 参数继续保留，但内部映射到 `ls_acc_mode`。

## 16. 统计设计

### 16.1 新统计项

每个对象至少提供：

- `*_reads_total`
- `*_writes_total`
- `*_updates_total`
- `*_hit_total`
- `*_miss_total`
- `*_refill_req_total`
- `*_refill_bytes_total`
- `*_evict_req_total`
- `*_writeback_bytes_total`
- `*_spill_req_total`
- `*_spill_bytes_total`
- `*_bank_conflict_cycles_total`
- `*_port_conflict_cycles_total`
- `*_queue_full_cycles_total`
- `*_occupancy_peak_bytes`
- `*_stall_cycles_total`
- `*_energy_read_pj_total`
- `*_energy_write_pj_total`

### 16.2 兼容统计项

在 Phase A 需要继续导出并对齐：

- `core_state_sram_*`
- `weight_idx_sram_*`
- `weight_l0_sram_*`

这些字段可以由新对象统计映射得到，避免现有脚本立即失效。

### 16.3 新增重点指标

建议新增：

- `activation_backpressure_cycles_total`
- `acc_spill_merge_cycles_total`
- `rf_pressure_stall_cycles_total`
- `state_block_refill_cycles_total`
- `weight_window_prefetch_hit_total`

## 17. 与 tensor 的未来兼容

本设计不是只为 `snn` 做一次性的特化。

后续 `tensor` 迁移时，可以直接映射：

- `tensor_ub -> local object: tensor_ub_store`
- `tensor_acc -> local object: tensor_acc_store`
- `tensor weight pool -> local object: tensor_weight_store`

当前 `TensorWorkload` 已经有的：

- bank count
- port
- queue depth
- spill
- occupancy

都应迁移到同一 `LocalStorageHierarchyController` 之下，而不是继续留在 workload 内部。

因此新框架必须从第一天支持：

- `AddressableStore`
- `QueueStore`
- `RegisterFile`

这三类对象，而不是只做 state/weight 的特例。

## 18. 实现落点（建议）

### 18.1 新增平台层

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/LocalStorageTypes.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/LocalStorageHierarchyController.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/LocalStorageObject.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/LocalStorageArray.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/LocalStorageDirectory.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/LocalStorageRefillEngine.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/LocalStorageSpillEngine.{h,cc}`

### 18.2 修改接入点

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/compute/SnnComputeCore.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/stimulus/StepActivationSubsystem.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.{h,cc}`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/gas/AccumulatorOps.{h,cc}`

### 18.3 保留不删的旧模块

- `services/memory/sram_sim/model/BankedSramModel.{h,cc}`
- `services/memory/sram_sim/layout/VirtualSramLayout.h`

它们保留为 legacy / compatibility 工具，不在 Phase A 删除。

## 19. Phase A 落地顺序

### A0. 平台骨架

- 新增 `services/local_storage/`
- 打通 per-PE controller lifecycle
- 接入基础统计与对象注册

### A1. State + Weight + Activation + RF

先落地：

- `state_store`
- `weight_idx_store`
- `weight_value_store`
- `activation_ingress_store`
- `activation_core_queue`
- `register_file`

这是最值得先真实化的一组，因为它们直接决定：

- gather/apply 的关键路径
- state block residency
- weight refill path
- ingress backpressure

### A2. Accumulator Store

在 A1 稳定后，再把 `AccumulatorOps` 从“内建容器”迁到“语义 front-end + store backend”。

这样可以避免一开始就同时重构：

- weight path
- state path
- accumulator path

降低风险。

### A3. 兼容统计与旧参数别名

保证：

- 旧的 summary/stats 脚本可继续工作；
- 用户可以逐步把 spec 从旧参数迁到 `ls_*` 新参数。

### A4. tensor 迁移

等 `snn` 路径稳定后，再把 `TensorWorkload` 当前内嵌 on-chip model 迁入统一框架。

## 20. 验证计划

按你的要求，测试主落点放在 `snndl-thing-exp`。

### 20.1 测试目录建议

- `snndl-thing-exp/cases/local_storage_phaseA/`
- `snndl-thing-exp/tests/test_local_storage_cases.py`

### 20.2 必做场景

#### Case 1. state 常驻

- `ls_state_capacity_bytes >= local_state_bytes`
- 预期：
  - 无 state refill
  - 有 state bank/port conflict 统计

#### Case 2. state block refill

- `ls_state_capacity_bytes < local_state_bytes`
- 预期：
  - 出现 block refill / dirty writeback
  - 结果正确
  - `state_block_refill_cycles_total > 0`

#### Case 3. weight window refill

- 小 `weight_value_store`
- 开启/关闭 `PeDmaReadRefillBackend`
- 预期：
  - refill 路径改变
  - 统计与 stall 合理变化

#### Case 4. activation backpressure

- 缩小 ingress/core queue
- 增大 stimulus burst
- 预期：
  - backpressure 触发
  - 无 silent drop

#### Case 5. accumulator spill

- 缩小 `accumulator_store`
- 预期：
  - spill to `acc_spill_store`
  - scatter 能正确 drain

#### Case 6. rf pressure

- 缩小 `register_file`
- 预期：
  - `rf_pressure_stall_cycles_total > 0`
  - 功能仍正确

### 20.3 A/B 回归

必须支持三组对照：

1. `local_storage_enable=0`
2. `local_storage_enable=1` 且容量足够大
3. `local_storage_enable=1` 且容量受限

这样可以区分：

- 纯兼容
- 显式对象但无容量压力
- 显式对象且有真实容量压力

## 21. 风险与取舍

### 21.1 State 容量限制会倒逼 compute 改成 block-aware

这是不可避免的，但也是正确的方向。否则 `state capacity` 永远只能是统计值。

### 21.2 Activation 做成显式 store 后，部分“隐式即时可用”路径会消失

这会让仿真器更真实，也会暴露此前被隐藏的 backpressure 问题。

### 21.3 Accumulator 重构风险较高

因此把它放在 A2，而不是 A1。

### 21.4 参数数目会上升

所以必须：

- 提供兼容 alias
- 提供合理默认值
- 默认关闭

### 21.5 不宜过早外部化为 SST 元件

Phase A 先做 SnnDL 内部微结构对象最合适。等对象语义稳定后，再考虑是否外露为 SST 子组件。

## 22. 最终结论

对当前 `SnnDL` 来说，最合适的方案不是继续扩展 `BankedSramModel`，而是新增一层 **SNN-first、本地对象显式化、与 memory 域解耦、同时兼容 future tensor** 的 `LocalStorageHierarchyController`。

这个方案的关键判断是：

1. **本地存储必须成为独立平台层**，不能继续散落在 compute/weights/workload 内；
2. **默认语义必须是 managed scratchpad，而不是透明 cache**；
3. **state/weight/activation/accumulator/register file 都要成为显式对象**；
4. **Phase A 先打通 state + weight + activation + RF，再接 accumulator**；
5. **保留旧路径和旧统计，避免现有实验一次性断裂**。

这会把 `SnnDL` 从“带一些 SRAM stall 参数的 accelerator simulator”，推进到“具备真实片上本地存储层级的体系结构仿真器”。

## 23. 参考链接

- SST memHierarchy intro: https://sst-simulator.org/sst-docs/docs/elements/memHierarchy/intro
- SST StandardMem / scratchpad / MMIO: https://sst-simulator.org/sst-docs/docs/elements/memHierarchy/stdmem
- SST memHierarchy connecting: https://sst-simulator.org/sst-docs/docs/elements/memHierarchy/connecting
- Timeloop architecture hierarchy: https://timeloop.csail.mit.edu/previous_versions/timeloop-accelergy-v3/timeloop/input-formats/design/architecture
- Timeloop storage components: https://timeloop.csail.mit.edu/previous_versions/timeloop-accelergy-v3/timeloop/input-formats/design/architecture/components
- NVDLA hardware architecture: https://nvdla.org/hw/v1/hwarch.html
- NVDLA unit description (CBUF/CACC): https://nvdla.org/hw/v1/ias/unit_description.html
