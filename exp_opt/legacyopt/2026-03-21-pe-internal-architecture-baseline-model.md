# PE 内部 core-level 架构基线模型（2026-03-21）

> 日期：2026-03-21  
> 状态：baseline model v1  
> 目标：把当前 `SnnDL` 中 `PE` 内部 `core` 间架构的真实执行模型，收敛成一份正式、可复用、可对照的基线定义；本文档只描述 **今天实际存在的模型**，不引入新的优化机制。

---

## 0. 文档定位

这份文档服务于一个更底层、也更普适的研究对象：

- **今天的 `PE` 内部 `core-level` 架构，到底是怎样运行的？**

它不是系统主线

- `DRAM-based SNN chip + GAS + GCSS-GLIDE + STORM`

的继续优化稿，也不是新的 `PULSE` 提案稿。  
它的作用是把当前代码现状压缩成一个正式 baseline，方便后续所有 `PE-internal` 方案都基于同一套对象、边界和 contract 讨论。

本文只回答四类问题：

1. 当前真实热路径是什么；
2. 当前 `PE` 内部有哪些共享结构已经在起作用；
3. 哪些结构还只是骨架、provider 或 observe-only 组件；
4. 后续任何新方案必须保留哪些 correctness 与 ownership 边界。

---

## 1. 一句话基线定义

当前 `SnnDL` 的 `PE` 内部架构基线可收敛为：

- **`per-core private execution` on top of `PE-scoped shared helpers`**

也就是：

1. 真正执行 token 展开、metadata/weight issue、ready/retire 推进的主体，仍然是 **每个 core 私有的 `WMS`**；
2. `PE` 级已经存在 ring、DMA、local storage、shared fabric 等结构，但它们大多仍是 **transport / provider / registry / observe** 角色；
3. 当前已经出现的“共享”，主要体现在 **`WMS` 内部 shared-line service semantic collapse**，而不是一个完整的 `PE-shared issue/service/commit` 微结构。

因此，今天的 `PE` 不是一个真正的 shared execution island，而更像：

- **以私有执行为主、以共享辅助结构为辅的多核容器。**

---

## 2. 基线对象与边界

### 2.1 本文档讨论什么

本文把 `PE` 内部架构拆成六个平面：

1. `communication plane`
2. `service plane`
3. `storage plane`
4. `issue/scheduling plane`
5. `retire/commit plane`
6. `provider / observe plane`

### 2.2 本文档不讨论什么

本文显式不把以下内容算作今天的 baseline 能力：

- `PE-shared descriptor agenda`
- `PE-shared control-plane messaging`
- `PE-shared residency object lifecycle`
- `PE-level exact issue queue`
- `PE-level commit / retire scoreboard`
- `WMS SRAM model` 与 `PE local storage object model` 的统一资源映射

这些要么尚未存在，要么尚未进入真实热路径，因此不能被当作当前架构事实。

---

## 3. 顶层层次模型

### 3.1 组件层

从组件装配角度，`MultiCorePE` 已经提供了以下 `PE` 级对象：

- `OptimizedInternalRing`
- `PeDmaScheduler`
- `LocalStorageHierarchyController`
- `PeSharedCoreFabric`

同时也向下暴露了多个 provider：

- `IDmaSchedulerProvider`
- `ILocalStorageProvider`
- `IPeSharedCoreFabricProvider`

这说明从组件接口上看，仓库已经具备“做 `PE-internal` 架构”的挂点。

### 3.2 执行层

但从执行语义看，今天真正的运行单元仍然是：

- `per-core SnnPESubComponent`
- `per-core SnnWorkload`
- `per-core WeightMemorySubsystem`

因此，组件层已经是 `PE-scoped`，执行层却仍然主要是 `core-private`。

### 3.3 基线层次图

可把当前 baseline 抽象为：

- `PE shell`
  - `OptimizedInternalRing`：真实 packet transport
  - `PeDmaScheduler`：可用但未主路径接入的共享 issue backend
  - `LocalStorageHierarchyController`：Phase A object registry
  - `PeSharedCoreFabric`：ingress / harbor / observe / dispatch 辅助平面
- `Core execution island`
  - `SnnPESubComponent`：runtime 装配
  - `SnnWorkload`：token/workload 驱动
  - `WeightMemorySubsystem`：真实 service + retire 内核
  - `StandardMemAccess`：当前默认 memory backend

---

## 4. 真实热路径模型

### 4.1 runtime 绑定

当前 `core` 运行时最关键的绑定是：

- `SnnPESubComponent::bindWorkloadRuntime_()`
- `rt.mem = stdmem_ep_->memoryAccess()`

这说明 workload 看到的 memory access 默认来自：

- `StdMemEndpoint`
- `StandardMemAccess`

而不是：

- `DmaMemAccessProxy`
- `PE` 级统一内存服务对象

### 4.2 workload 到 WMS 的绑定

`SnnWorkload` 在创建或接管 `WeightMemorySubsystem` 后，会执行：

- `wms->bindMemory(rt_.mem)`

因此当前真实主路径可写成：

- **`core -> SnnWorkload -> WeightMemorySubsystem -> StandardMemAccess`**

### 4.3 WMS 是今天的真实执行内核

`WeightMemorySubsystem` 当前实际承担：

- rowptr / rowidx 预取
- `idx2` 预取
- direct read / pending read drain
- shared-line completion
- ready 推进
- retire 推进
- weight SRAM stall 注入

因此基线里真正的 service 与 commit 不应归到 `PE shell`，而应归到：

- **每个 core 私有的 `WMS`**

### 4.4 基线热路径结论

今天的 `PE` 内部并不存在一个独立的：

- `PE-shared issue plane -> PE-shared service plane -> PE-shared retire plane`

真实存在的是：

- **多个 `per-core WMS` 并行推进，`PE` 级结构在外围提供运输、注册、观测和局部共享辅助。**

---

## 5. Communication Plane：有 packet plane，没有 shared-service control plane

### 5.1 已存在能力

当前 `PE` 内 `core` 间通信的真实后端是：

- `OptimizedInternalRing`

`NocSubsystem` 会构造 `RingMessage` 并通过：

- `OptimizedInternalRing::sendMessage(...)`

完成 core 间 packet 路由。  
`OptimizedInternalRing` 已声明的消息类型包括：

- `PACKET_MESSAGE`
- `MEMORY_REQUEST`
- `MEMORY_RESPONSE`
- `CONTROL_MESSAGE`

### 5.2 当前实际用法

虽然消息类型定义较完整，但当前 `NocSubsystem` 的主处理对象仍是：

- `PACKET_MESSAGE`

因此今天真正成形的是：

- `packet transport plane`

而不是：

- `shared-service control plane`

### 5.3 基线限制

当前通信层还不能显式表达以下共享服务动作：

- owner announce
- join request
- ready fanout
- release / drain
- residency invalidation

这意味着：

- **今天 `PE` 内部虽然有 inter-core transport，但没有显式的 inter-core shared-service 协议层。**

---

## 6. Service Plane：共享语义已经出现，但仍停留在 `WMS` 内部

### 6.1 已存在的共享服务语义

当前真正的共享服务对象主要位于 `WeightMemorySubsystem` 内部：

- `PulseSharedLineService`
- `PulseSeededLineResidency`
- `PulseSeededLineTracker`

它们已经能表达：

1. 多 consumer 对同一 line 的 `joinOrRegister`
2. 单 owner 发起一次真实 line service
3. line 返回后统一 `complete(...)` 并 fanout 给 waiters

### 6.2 当前共享的真实性质

这说明当前 baseline 已经具备：

- `shared service semantic collapse`

但它仍然主要以：

- 进程内 static registry
- `(scope_id, window_seq, line_addr)` key
- `WMS` 内部回调/fanout

的方式存在。

### 6.3 为什么它还不是完整微结构

当前共享服务仍缺少下列被资源化的实体：

- 显式 service object queue
- 显式 owner/join 控制消息
- 显式 residency buffer / bank / port
- 独立的 ready fanout transport
- `PE` 级 service arbitration lifecycle

因此今天应把它定义为：

- **`WMS-internal shared service semantics`**

而不是：

- **`PE-shared service microarchitecture`**

---

## 7. Storage Plane：对象层已命名，执行层尚未统一

### 7.1 `WMS` 内部已有真实 SRAM/stall 建模

`WeightMemorySubsystem` 已内置：

- `weight_idx_sram`
- `weight_l0_sram`

并在时钟推进中将 bank/port 竞争映射为 stall 周期。  
这说明权重相关局部存储并非完全空白。

### 7.2 `PE` 级 local storage 也已有对象层

`MultiCorePE` 会通过 `LocalStorageHierarchyController` 注册一组 Phase A 对象：

- `activation_ingress_store`
- `weight_idx_store`
- `weight_value_store`
- `state_store`
- `activation_core_queue`
- `accumulator_store`
- `register_file`

这些对象已经拥有：

- `scope`
- `capacity_bytes`
- `banks`
- `read_ports`
- `write_ports`
- `update_ports`
- `queue_depth`

等配置属性。

### 7.3 当前真正的缺口

今天 storage plane 最大缺口不是“没有命名对象”，而是：

- **对象层与执行层没有打通**

也就是还没有明确回答：

1. `PulseSeededLineResidency` 占用哪一个 `PE` 级对象；
2. `rowidx / idx2 / pre-band / shared line` 分别驻留在哪个物理层；
3. `weight_idx_sram` 与 `weight_idx_store` 的关系是重复、分层还是替代；
4. `activation_ingress_store` 与 shared residency 是否共享预算与仲裁。

因此当前 baseline 更准确的描述是：

- `WMS internal storage model` 与 `PE object namespace` 并存，但尚未形成统一 storage plane。

---

## 8. Issue / Scheduling Plane：共享 DMA 已存在，但尚未接入真实热路径

### 8.1 已存在能力

`PeDmaScheduler` 当前已具备相对完整的共享调度语义，包括：

- per-core / per-priority queue
- overflow queue
- bytes-per-cycle budget
- inflight cap
- read-engine budget
- barrier-cycle service
- stage budget scale

### 8.2 当前未接入事实

仓库中虽然存在：

- `DmaMemAccessProxy`

可把 `read()` 转发给 `PeDmaScheduler`，但当前生产热路径没有把：

- `StdMemEndpoint::memoryAccess()`

替换为该代理。

因此今天的 issue plane 事实是：

- `PE DMA` 已作为能力对象存在；
- **真实 issue 仍由每个 core 私有 `WMS` 直接经 `StandardMemAccess` 发起。**

### 8.3 基线含义

这意味着当前 baseline 还没有：

- `PE` 范围统一 read issue arbitration
- 真正共享的 inflight / channel / fairness 主路径
- service-plane 与 DMA-plane 的统一预算关系

---

## 9. Retire / Commit Plane：contract 已较硬，但仍面向私有 issue 模型

### 9.1 已存在能力

`WeightMemorySubsystem` 当前已有较成熟的 retire/correctness 表面：

- `experimental_retire_policy = global_inorder`
- `per_post deterministic retire`
- `shadow per_post retire`
- `pulse_domain_retire` 的 actual / shadow 变体

同时持续维护 observability：

- `ready_but_blocked_edges_total`
- `crosspost_blocked_edges_total`
- `policy_loss_cycles_total`
- `shadow_per_post_recoverable_edges_total`

### 9.2 当前 contract 的真正对象

虽然 contract 已经较硬，但它今天约束的仍然是：

- `per-core issue`
- `WMS-internal ready`
- `core-side shared-line join`

而不是：

- `PE-level descriptor service queue`
- `PE-level shared residency object`
- `PE-level consumer bitmap / cohort scoreboard`

### 9.3 基线正确性结论

当前基线的 correctness 应定义为：

1. `shared service completion` 不等于 `architectural commit`
2. 最终可见状态更新仍由各 core 自身 retire 逻辑推进
3. 当前 exactness contract 主要由 `WMS` 内部 policy 维护，而不是由 `PE` 级共享控制器维护

这也是今天最重要的安全边界。

---

## 10. Provider / Observe Plane：这些结构存在，但不能被误判为主执行面

### 10.1 `PeSharedCoreFabric`

当前 `PeSharedCoreFabric` 更接近：

- ingress mirror
- queue mirror
- gather harbor
- descriptor observe
- dispatch token buffering

它对 `PULSE` 路线非常重要，但到今天为止：

- fabric-side actual descriptor service 仍未成为真实主路径

### 10.2 `LocalStorageHierarchyController`

当前它主要是：

- object registry
- config namespace
- snapshot/stats collection

尚不是：

- runtime resource allocator
- bank/port arbiter
- refill / eviction / residency lifecycle controller

### 10.3 `PeDmaScheduler`

当前它已足够像一个共享 issue backend，但还不能被当作：

- today 的 real issue plane

因为 `rt.mem` 仍未切换到 DMA proxy。

### 10.4 基线结论

当前 `PE` 级 provider 的正确定位应是：

- **能力已经摆在台面上，但大多尚未接入真实执行闭环。**

---

## 11. Real vs. Skeleton：正式基线判定

### 11.1 已经是真实基线一部分的结构

以下结构已经进入 today baseline：

- `per-core SnnWorkload + WMS + StandardMemAccess`
- `OptimizedInternalRing` 的 packet transport
- `WMS` 内部的 shared-line registry / residency / tracker
- `WMS` 内部的 retire policy 与 observability
- `WMS` 内部的 weight SRAM stall 模型

### 11.2 处于 partial / helper 状态的结构

以下结构当前是部分成立：

- `PeSharedCoreFabric`
- `PeDmaScheduler`
- `LocalStorageHierarchyController`

它们是重要挂点，但还不是完整主执行面。

### 11.3 目前仍不存在的结构

以下能力在今天的 baseline 中应视为不存在：

- `PE-shared control-plane protocol`
- `PE-shared service queue`
- `PE-shared descriptor agenda`
- `PE-shared commit/retire matrix`
- `PE-unified storage residency lifecycle`

---

## 12. 当前 baseline 的形式化收敛

为了让后续讨论避免语义漂移，建议把今天的 `PE` 内部模型记为：

- **`B0 = Private-Execution + Shared-Helpers`**

其形式化描述可写成：

1. **Execution ownership**  
   token 展开、metadata/value issue、ready、retire 的主所有权属于各 `core` 私有 `WMS`。

2. **Communication substrate**  
   `PE` 内部已有 packet 级 ring transport，但没有面向 shared-service 的显式控制协议。

3. **Shared service semantics**  
   共享目前主要体现为 line 级 service collapse，而不是 `PE` 级 service object execution。

4. **Storage organization**  
   `PE` 级对象层与 `WMS` 内部存储执行层并存，但未统一为单一 physical/storage contract。

5. **Correctness anchor**  
   exact retire 由各 core 的 `WMS` policy 保持；共享优化不能改变最终 architectural commit ownership。

只要未来某个方案没有改变以上五点，它就仍然只是在 `B0` 上加 probe / helper，而不是建立了新的 `PE-internal` 微结构。

---

## 13. 后续所有新方案必须面对的基线约束

本文档不提出新优化，但它明确了未来任何方案若要声称“进入 `PE` 内部收益空间”，至少必须满足：

1. **必须进入真实热路径**  
   仅停留在 ingress observe、metadata mirror、registry capture，不足以改变主矛盾。

2. **必须回答共享发生在哪个平面**  
   是 packet、service、storage、issue，还是 commit；不能再用“有共享现象”替代“有共享微结构”。

3. **必须定义资源归属**  
   任何 residency、queue、fanout、buffer、bank，都必须能映射到一个真实对象和生命周期。

4. **必须保留 exactness anchor**  
   `service completion != commit`，共享优化不能直接侵入 architectural retire contract。

5. **必须能解释为什么不是 helper-only**  
   若一个方案没有改变 `core -> WMS -> StandardMemAccess` 这条主路径，它大概率仍是旁路增强，而不是基线迁移。

---

## 14. 代码锚点

这份 baseline model 主要对应以下代码入口：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/noc/NocSubsystem.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/noc/OptimizedInternalRing.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/LocalStorageHierarchyController.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/LocalStorageHierarchyController.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/memory/PeDmaScheduler.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/memory/DmaMemAccessProxy.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/pe_fabric/PeSharedCoreFabric.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/stdmem/StdMemEndpoint.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseSharedLineService.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseSeededLineResidency.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseSeededLineTracker.h`

---

## 15. 最终基线结论

今天的 `PE` 内部不是一个真正的 shared core-cluster microarchitecture。  
它的准确定位是：

- **`B0 = per-core private execution + PE-scoped shared helpers/providers + WMS-internal shared service semantics`**

这份基线之所以重要，不是因为它激进，而是因为它把“今天真正是什么”与“我们以后想做成什么”切开了。  
只有先把这条线压实，后续关于 `PE` 内部 core 间通信、共享服务、共享存储、共享调度、retire-safe 协同的所有新设计，才有明确的起点与对照面。
