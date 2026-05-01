# PULSE-OSA：面向 PE 内部 core-level 的 Owner-Scoped Shared Architecture 设计稿（2026-03-21）

> 日期：2026-03-21  
> 状态：design draft v1  
> 设计取向：`paper-first`  
> 工作名：`PULSE-OSA` = `PE-internal Owner-Scoped Shared Architecture`  
> 一句话主题：**把 `PE` 内部的 local object、runtime owner、service scope 三者第一次严格对齐，形成一个 retire-safe 的 shared activation / metadata / value service plane。**

---

## 0. 一句话结论

基于当前代码、baseline model、storage mapping review 与 runtime owner binding table，浮浮酱认为下一阶段最值得收成主架构的方案，不是继续做局部 heuristic，也不是只做一段 `PE` 内 shared line，而是：

- **把 `PE` 从“per-core 私有执行 + shared helpers”升级成一个 `owner-scoped shared object plane`。**

也就是：

1. `PerPe` 的对象必须有 `PerPe` 的 runtime owner；
2. shared service 必须落在真实的 shared object 上，而不是停留在 registry 语义；
3. commit/exactness 仍坚持 per-core exact retire，不让共享直接侵入 architectural visibility point。

因此，这版推荐的 canonical 主线是：

- **`shared activation owner -> shared metadata owner -> shared value owner -> exact core-private commit`**

对应的正式体系结构命名为：

- **`PULSE-OSA: A Retire-Safe Owner-Scoped Shared Architecture for PE-Internal SNN Acceleration`**

---

## 1. 为什么我们现在必须换一种架构问题定义

前面的几轮研究已经把问题定义得足够清楚：

### 1.1 当前 baseline `B0` 的本质

当前 `PE` 内部的真实形态是：

- `B0 = per-core private execution + PE-scoped shared helpers/providers + WMS-internal shared service semantics`

它的问题不在于“没有共享”，而在于：

- **共享出现了，但没有 object owner、scope contract 和统一 storage/service plane。**

### 1.2 为什么此前局部优化很难持续赢钱

此前的 shared ingress、late idx2、preband、gather-preband 探索已经说明：

1. 只在 ingress 做共享，不会改变真正的 memory/service cardinality；
2. 只在 late issue 附近做 seed，很容易退化成 join-only；
3. `WMS` 内部 shared-line service 虽然有效，但仍然只是语义塌缩，不是一个 `PE-shared microarchitecture`；
4. `LocalStorageHierarchyController` 已经有对象，但 runtime owners 只覆盖了一部分，且最关键的 weight plane 仍存在 `PerPe object` vs `per-core runtime proxy` 的 scope 断裂。

### 1.3 这意味着什么

下一阶段真正该解决的问题，不应再写成：

- “能不能再让几个 core 多共享一点 line”

而应写成：

- **“能不能在 `PE` 内建立一个 object-owned、scope-aligned、retire-safe 的 shared service architecture？”**

这就是 `PULSE-OSA` 的出发点。

---

## 2. 设计空间比较

### 2.1 方案 A：继续沿 `B0` 做局部 patch

思路：

- 保持 `per-core WMS`
- 继续在 ingress/frontier/seed/join 上增加 heuristic
- 不重构 local object owner

优点：

- 工程最稳
- 不会打破 today 路径

缺点：

- 无法解决 `PerPe object` vs `per-core runtime owner` 的根矛盾
- 很难形成顶会级新微结构主张
- 很容易继续落回“做了共享现象，但没有共享架构”

结论：

- 适合作为 baseline，不适合作为新主架构

### 2.2 方案 B：只做 weight plane shared store

思路：

- 只把 `weight_idx_store / weight_value_store` 真正 shared 化
- activation 和 control plane 仍相对保守

优点：

- 直接命中当前最强的 hot path
- scope mismatch 最容易先被解决

缺点：

- activation/object owner 问题仍然悬空
- 论文叙事容易被理解成“shared cache / shared SRAM”而不是完整新架构

结论：

- 适合 first-step 实现，不适合作为 paper-first 的完整主架构

### 2.3 方案 C：`PULSE-OSA`，统一 object owner / service scope / storage plane

思路：

- 给 `activation_ingress_store / weight_idx_store / weight_value_store` 都赋予真实 `PerPe` owner
- 让 shared metadata/value service 真正落在 shared object 上
- per-core 只保留 state/acc/compute/commit

优点：

- novelty 边界清晰
- 与我们当前代码现状高度对齐，属于“把已存在碎片收敛成统一架构”
- correctness story 可以非常干净

缺点：

- 设计工作量最大
- 需要明确 compiler/runtime interface 与 object contract

结论：

- **推荐作为 paper-first canonical architecture**

---

## 3. `PULSE-OSA` 的核心主张

`PULSE-OSA` 的核心不是“做更大共享”，而是三条 contract：

### 3.1 Owner Contract

- **每个 `PerPe` 对象必须有且只有一个稳定的 `PerPe runtime owner`。**

这条 contract 直接解决 today 最大的问题：

- object 已经注册了，但 owner 还在 per-core 私有壳里

### 3.2 Scope Contract

- **object scope、arbitration scope、residency scope、issue scope 必须一致。**

这意味着：

- 如果对象叫 `weight_idx_store` 且 scope=`PerPe`
- 那么它不能再由每个 core 各自维护一份私有 banked model

### 3.3 Commit Contract

- **shared service completion != architectural commit**
- **shared ready fanout 可以跨 core**
- **最终 state visibility 仍按 core-private exact retire 发生**

这条 contract 让我们可以大胆共享 activation / metadata / value service，
同时把 correctness 风险收在 commit plane 外面。

---

## 4. 顶层架构图

`PULSE-OSA` 把 `PE` 内部正式拆成五个层：

1. `Activation Object Plane`
2. `Metadata Object Plane`
3. `Value Residency Plane`
4. `PE Shared Issue / Control Plane`
5. `Core-Private Compute / Commit Plane`

顶层结构可写成：

- `AIO` = `Activation Ingress Owner`
- `CDQ` = `Core Delivery Queues`
- `MOO` = `Metadata Object Owner`
- `VRO` = `Value Residency Owner`
- `SIC` = `Shared Issue Controller`
- `RSM` = `Ready Synchronization Matrix`
- `CPC` = `Core-Private Commit`

一句话数据流：

- **`packet/spike ingress -> activation object ownership -> metadata shared service -> value shared residency -> ready fanout -> core-private state update + exact commit`**

---

## 5. Object 模型重定义

`PULSE-OSA` 不引入全新的对象名字，而是优先把 today `LocalStorageHierarchyController` 已经命名的对象真正变成一等公民。

### 5.1 保持 `PerCore` 的对象

这些对象继续保持 per-core：

- `state_store.coreX`
- `accumulator_store.coreX`
- `register_file.coreX`

原因：

- 它们与最终 architectural ownership 强耦合；
- 其中 `state_store.coreX` 已经是 today 唯一强绑定对象；
- 强行共享它们会直接把风险推进 commit plane。

### 5.2 升级为真正 `PerPe` owner-backed object 的对象

这些对象是 `PULSE-OSA` 的核心：

- `activation_ingress_store`
- `weight_idx_store`
- `weight_value_store`

要求是：

1. 它们不再只是 object registry；
2. 它们有真实 runtime owner；
3. 它们的 bank/port/capacity/queue 不再只是配置字段，而是参与 runtime arbitration；
4. 它们的 stall/pressure 可被正式归因。

### 5.3 `activation_core_queue.coreX`

这个对象在 `PULSE-OSA` 中保留，但重定义为：

- **`PerCore delivery sink`, not the source of truth**

也就是说：

- 真正 owner 是 `AIO`
- `activation_core_queue.coreX` 只是 shared activation object plane 到 per-core consumer 的正式边界

这样可以把 today 的弱绑定彻底收紧。

---

## 6. 微结构细节

## 6.1 Activation Object Plane

### 6.1.1 `AIO`：Activation Ingress Owner

`AIO` 是 `activation_ingress_store` 的真正 runtime owner。

职责：

- 接收所有进入 `PE` 的 spike / packet
- 维护真实 ingress occupancy 与 pressure
- 进行 step/window 粒度的 gather harbor / bucketize
- 形成 activation object，而不是立即散落到各 core 私有路径

它继承 today `PeSharedCoreFabric` 里的三类能力：

- `ingress_mirror_`
- `harbor_buckets_`
- `descriptor_observe_buckets_`

但把它们从：

- observe/mirror/统计对象

提升为：

- **真实 activation object owner**

### 6.1.2 `CDQ`：Core Delivery Queue

`activation_core_queue.coreX` 被重新定义为：

- `AIO -> core X` 的正式 delivery sink

它负责：

- 接收 ready activation token / descriptor
- 保持 per-core delivery ordering
- 与 core-private compute 接口解耦

关键点：

- `CDQ` 不再是历史遗留 `incoming_spikes_` 的影子；
- 它是 activation plane 和 core-private plane 之间唯一正式边界。

---

## 6.2 Metadata Object Plane

### 6.2.1 `MOO`：Metadata Object Owner

`MOO` 是 `weight_idx_store` 的真正 runtime owner。

它统一接管 today 分散在各 `WMS` 私有路径中的：

- row metadata read
- GCSS legacy lookup
- idx2 lookup
- pre-MPHF `pre_base / pre_len`
- base/band/frontier 级 metadata issue

### 6.2.2 为什么 metadata 必须先共享

因为当前所有实验证据都在说明：

- 更早、更共享、更稳定的机会首先出现在 metadata frontier

因此 `PULSE-OSA` 不把 value line 当成第一共享对象，而是把 metadata plane 作为：

- **第一共享服务平面**

### 6.2.3 `weight_idx_store` 的正式语义

在 `PULSE-OSA` 中，`weight_idx_store` 不再只是：

- 一个 `PerPe` 的名字

而是：

- 一个真正的 shared metadata store
- 有真实 bank/port 几何
- 有统一 arbitration
- 有真实 owner

这一步直接修复 today 最重要的 scope mismatch 之一。

---

## 6.3 Value Residency Plane

### 6.3.1 `VRO`：Value Residency Owner

`VRO` 是 `weight_value_store` 的真正 runtime owner。

它统一接管 two-layer value semantics：

1. today 的 `l0_sram_model_`
2. today 的 `PulseSeededLineResidency`

### 6.3.2 设计核心：`private namespace over shared residency`

这版价值平面不应再写成“逻辑私有 / 物理共享”的口语化描述，而应正式写成：

- **private namespace over shared residency**

即：

1. core 侧仍用自己的逻辑地址/descriptor/consumer view 工作；
2. 物理 line residency、bank allocation、refill、fanout 在 `VRO` 中统一处理；
3. 同一 residency line 可被多个 consumer domain 引用，但最终 commit ownership 不变化。

### 6.3.3 `weight_value_store` 的对象收敛

未来 `weight_value_store` 应显式包含三类子对象：

- `value_banked_array`
- `shared_residency_directory`
- `ready_fanout_buffer`

这样 `PulseSeededLineResidency` 才能真正从 today 的 static registry 变成：

- formal storage object component

---

## 6.4 Shared Issue / Control Plane

### 6.4.1 `SIC`：Shared Issue Controller

`SIC` 统一接管对 off-chip / memHierarchy 的读 issue。

它的核心作用是把 today 还没进入热路径的：

- `PeDmaScheduler`
- `DmaMemAccessProxy`

正式拉进主线。

### 6.4.2 为什么它必须存在

如果没有 `SIC`，即使 activation / metadata / value object 都做 shared 了，我们仍然会卡在：

- 各 core 私自 issue
- 各自竞争 inflight / channel / budget

那样 object 虽然 shared 了，issue 仍然不是 shared。

### 6.4.3 `SIC` 的调度目标函数

`SIC` 不应只是 heuristic 堆叠，而应明确优化：

- **`SharedGain - RetireRisk - BankConflictCost - QueuePressureCost`**

其中：

- `SharedGain`
  - request elision / fanout amplification / residency reuse
- `RetireRisk`
  - ready but blocked / head pressure / cross-domain blockage
- `BankConflictCost`
  - idx/value plane 的内部冲突
- `QueuePressureCost`
  - ingress/CDQ/object occupancy 风险

这会让整个调度器从“若干 if 条件”上升成：

- 一个有优化方向的共享 issue policy

---

## 6.5 Ready / Commit Plane

### 6.5.1 `RSM`：Ready Synchronization Matrix

`RSM` 不是一个 centralized commit engine，而是一个：

- bounded active service scoreboard

只跟踪：

- cohort / service object 的 consumer bitmap
- ready state
- outstanding reference count
- retire-domain compatibility

### 6.5.2 `CPC`：Core-Private Commit

真正的 commit 仍保留在 per-core：

- state update
- accumulator application
- exact retire sequence

### 6.5.3 正确性合同

这版合同必须在正文里明确写三条：

1. shared service completion 不等于 architectural commit
2. ready broadcast 只改变 service visibility，不改变最终 state ownership
3. 最终 commit order 仍由 core-private retire engine 决定

这条 correctness story 是 `PULSE-OSA` 最强的防失控锚点。

---

## 7. Internal Communication 设计

`PULSE-OSA` 不需要重新发明一张网络，但必须让 today 的 `OptimizedInternalRing` 真正承担：

- **packet plane + control plane**

具体地，内部消息应显式分成四类：

1. `ACT_INGRESS`
2. `META_JOIN / META_READY`
3. `VALUE_JOIN / VALUE_READY / VALUE_RELEASE`
4. `CONTROL_HINT`

这意味着 `RingMessageType` 中已有但 today 不活跃的：

- `MEMORY_REQUEST`
- `MEMORY_RESPONSE`
- `CONTROL_MESSAGE`

应被正式激活为 `PE` 内部 shared-service protocol 的承载层。

这样做的好处是：

- 不需要再虚构一个完全新网络
- 直接把 existing ring 从 packet-only 后端升级成 shared-service substrate

---

## 8. Compiler / Runtime 接口

`PULSE-OSA` 不是纯 runtime 方案，必须要求 offline/runtime interface 成熟下来。

### 8.1 编译期提供

至少提供：

- `weight_region_id`
- `post_block_id`
- `retire_domain_id`
- `pre_base`
- `pre_band`
- `bank_color`
- `region_safe`
- `cohort_safe`

### 8.2 runtime 动态补全

runtime 再补：

- active consumer bitmap
- current window/step seq
- queue pressure
- active residency state
- actual join set
- readiness

### 8.3 边界原则

必须保持：

- 静态负责“哪些对象可能共享”
- 动态负责“这次窗口里哪些对象真的值得共享”

只有这条边界收紧，方案才不会退化成：

- 全靠离线猜
或
- 全靠 runtime 临时碰运气

---

## 9. 论文主张为什么站得住

`PULSE-OSA` 的 novelty 不应写成：

- “我们做了 PE 内共享”

而应写成：

- **我们首次把 `PE` 内 local object namespace、runtime owner、shared service scope 三者统一成一个 retire-safe 的 shared architecture。**

它和我们当前已有工作的差异在于：

1. 不是只做 shared ingress；
2. 不是只做 metadata observe；
3. 不是只做 `WMS` 内部 shared-line semantic collapse；
4. 不是只做 Phase A local storage registry；
5. 而是第一次把这些碎片收敛成：
   - activation owner
   - metadata owner
   - value owner
   - shared issue controller
   - exact core-private commit

这比“再做一个更大 shared line”更 solid，也更像一篇顶会微结构论文真正该有的边界。

---

## 10. 风险与防失控设计

### 10.1 风险一：中心化控制器过大

风险：

- `AIO + MOO + VRO + SIC + RSM` 看起来容易过大

防失控：

- 每个 plane 只维护 bounded active objects
- 以 window/step 为边界
- `RSM` 不跟踪全局依赖，只跟踪 active cohorts

### 10.2 风险二：shared value residency 过度复杂

风险：

- `PulseSeededLineResidency` 一旦资源化，容易变成复杂 cache

防失控：

- 不把它设计成通用 cache
- 只支持 service-cohort-aware residency
- 生命周期严格限定为：
  - allocate
  - refill
  - ready fanout
  - refcount drain
  - evict

### 10.3 风险三：commit 正确性被共享路径污染

风险：

- ready 太早、join 太多，可能影响 retire

防失控：

- `CPC` 保持 core-private exact commit
- `RSM` 只标记 ready，不写 architectural state
- 任何 shared object 都不得直接越过 core-private commit interface

---

## 11. 评估上要怎么证明它赢

`PULSE-OSA` 的评估必须直接围绕 object-owner-scope 对齐来做，而不是只看 memory_requests。

### 11.1 必须新增的主指标

- `owner_alignment_ratio`
  - 真正 runtime-bound 的 local object 占比
- `shared_object_issue_elision`
  - 因 shared owner 而省掉的 issue 数
- `shared_residency_usefulness`
  - shared residency 的 first-useful ratio
- `per_object_bank_conflict`
  - idx/value plane 的冲突分布
- `ready_without_commit_cycles`
  - ready 已满足但 commit 仍被 exactness 卡住的周期
- `queue_pressure_rescue_total`
  - activation/CDQ/object plane 的背压救援事件

### 11.2 必须给审稿人看的对照面

至少要有：

1. `B0 baseline`
2. `weight-plane-only shared`
3. `activation-plane-only shared`
4. `PULSE-OSA full`

这样才能证明：

- 我们不是仅靠某个局部 patch 赢
- 而是靠 owner-scoped shared architecture 真正进入收益空间

---

## 12. 从今天代码到 `PULSE-OSA` 的实现切片

虽然这版是 `paper-first`，但仍建议保留一条能落地的 staged path：

### Stage 1：`weight_idx_store` shared owner 化

目标：

- 先把 `weight_idx_store` 从 `PerPe object / per-core proxy` 收成真实 `PerPe owner`

原因：

- metadata plane 最早、最共享、最稳

### Stage 2：`weight_value_store` 收编 shared residency

目标：

- 把 `l0_sram_model_ + PulseSeededLineResidency` 收成同一 value owner

### Stage 3：`SIC` 正式接入热路径

目标：

- 把 `PeDmaScheduler + DmaMemAccessProxy` 变成真正主 issue plane

### Stage 4：`AIO + CDQ` 取代 activation 弱绑定

目标：

- 为 `activation_ingress_store / activation_core_queue.coreX` 建立稳定 runtime owner

### Stage 5：`RSM + CPC` 收完整 correctness story

目标：

- 把 shared ready / exact commit 的边界彻底形式化

这条路线保证：

- 论文主张足够完整
- 工程切片仍然现实

---

## 13. 最终推荐

如果我们要从当前所有知识出发，收一版最 solid、最 novel、同时又不是空中楼阁的 `PE` 内部体系结构方案，浮浮酱的结论是：

- **推荐正式以 `PULSE-OSA` 作为 canonical architecture。**

它最关键的价值不只是“多做共享”，而是：

- 首次让 `PE` 内部的 **local object、runtime owner、shared service、exact commit** 四件事同时进入同一架构合同；
- 直接命中了当前代码里最核心也最结构性的缺口；
- 能自然继承今天仓库已经存在的碎片，而不是完全脱离现实重写一套幻想机器。

如果用一句论文式的话来收：

- **`PULSE-OSA` turns a PE from a container of private cores with shared helpers into a retire-safe owner-scoped shared architecture, where activation, metadata, and value service become first-class PE objects while architectural commit remains core-private and exact.**
