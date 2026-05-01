# PE 内部 C/P/E 三层 Scope 架构与 Phase-1 落地设计（2026-03-24）

> 日期：2026-03-24  
> 状态：architecture design v1  
> 目标：把前一份通用研究稿继续收敛成一份可以直接指导实现的正式设计文档，冻结 `C-scope / P-scope / E-scope` 三层 scope 的对象表、消息表、ownership/commit contract，并给出一个强隔离、可渐进落地的 `Phase-1` 实现路径。

---

## 0. 一句话结论

下一阶段我们不再把 `PE` 内部优化写成：

- 在 `per-core WMS` 热路径外围继续添加共享 patch

而是正式把 `PE` 定义为一台三层局部机器：

- **`C-scope` = core-private compute/commit**
- **`P-scope` = pod-shared object/service/control**
- **`E-scope` = PE-global transport/directory/admission**

其中，`Phase-1` 的核心目标不是立刻追求性能收益，而是：

- **第一次让 shared metadata object 在 `private issue` 之前就拥有真实的 `pod-level owner-first launch`。**

---

## 1. 设计目标与范围冻结

### 1.1 这份设计要解决什么

这份设计只解决四个问题：

1. `PE` 内部对象应如何按 scope 分层；
2. scope 之间需要哪些正式消息；
3. shared service 与 exact commit 的边界如何定义；
4. 第一阶段应该先落哪一层，才能避免再次退化成 late join / late carry。

### 1.2 这份设计明确不做什么

`Phase-1` 明确不做以下内容：

1. 不改写现有 `core-private` exact retire 语义；
2. 不把 `weight value` 一步到位改成全 `PE` 统一大共享；
3. 不引入全局全窗口大 scoreboard；
4. 不改变默认 baseline 行为；
5. 不把 `PE` 内部一口气重写成全新调度器。

### 1.3 `Phase-1` 的成功标准

`Phase-1` 的成功标准不是立刻拿到正收益，而是先形成以下结构事实：

1. shared metadata object 有真实 `P-scope owner`；
2. owner launch 发生在 private issue fanout 之前；
3. later consumer 能以 exact join 方式挂到同一个 object transaction；
4. `C-scope` commit 仍保持独立、确定、可验证；
5. 所有新能力都可通过实验开关完全隔离关闭。

---

## 2. 三层 Scope 的正式定义

### 2.1 `C-scope`

`C-scope` 表示：

- 单个 core 私有拥有；
- 与最终 architectural state visibility 强耦合；
- 不允许被 shared service 直接改写顺序。

一句话：

- **`C-scope` 是 compute/retire 的私有岛。**

### 2.2 `P-scope`

`P-scope` 表示：

- 一个 `pod` 内多个 core 共享；
- owner arbitration、object transaction、ready fanout 在这一层发生；
- 是 shared service 的第一责任平面。

一句话：

- **`P-scope` 是 shared object/service/control 的执行平面。**

### 2.3 `E-scope`

`E-scope` 表示：

- 整个 `PE` 范围共享；
- 只保留必须全局化的 transport、directory、admission、粗粒度同步；
- 不直接承担高频细粒度 object service。

一句话：

- **`E-scope` 是路由、目录与准入平面。**

### 2.4 为什么必须引入 `P-scope`

如果只有 `PerCore + PerPe` 两层，shared structure 很容易走向两种坏结果：

1. 继续退化成 `PerCore private proxy`，即今天的状态；
2. 一口气做成整个 `PE` 的大共享结构，导致时序、面积、中心化依赖矩阵都爆炸。

因此，`P-scope` 的引入不是为了复杂化，而是为了：

- **给 shared object/service 一个真正可落地、可控复杂度的宿主层。**

---

## 3. 三层 Scope 对象表

### 3.1 `C-scope` 对象表

| 对象族 | 建议对象名 | owner | 主要职责 | stall/pressure 来源 | 是否可共享 |
| --- | --- | --- | --- | --- | --- |
| State Plane | `state_store.coreX` | `DefaultSnnComputeCore` | 神经元状态读写、膜电位/阈值/last-spike/refrac | state SRAM bank/port stall | 否 |
| Acc Plane | `accumulator_store.coreX` | `AccumulatorOps` / core-local update path | 累加、delta、spill | acc local pressure / spill | 否 |
| RF Plane | `register_file.coreX` | core-private runtime | 临时寄存/descriptor-local working set | RF 端口 | 否 |
| Commit Plane | `retire_queue.coreX` | core-private retire controller | ready-but-uncommitted / exact visibility bookkeeping | retire HOL / exact order | 否 |
| Wake Plane | `wake_queue.coreX` | core-private consumer wakeup path | 接收 `P-scope ready fanout` 后驱动本地恢复 | wake queue backpressure | 否 |

结论：

- `C-scope` 的对象不能被共享 service 直接写成最终 architectural state；
- shared service 最多只能改变它们“何时 ready”，不能改变它们“如何 commit”。

### 3.2 `P-scope` 对象表

| 对象族 | 建议对象名 | owner | 主要职责 | stall/pressure 来源 | `Phase-1` |
| --- | --- | --- | --- | --- | --- |
| Metadata Plane | `pod_metadata_store.podY` | `PodMetadataObjectPlane` | `idx2 / rowidx / pre-band / row descriptor` 的共享对象化 | metadata banks / owner contention | 是 |
| Owner Table | `pod_owner_table.podY` | `PodOwnerServiceTable` | object key 到 owner transaction 的映射 | table occupancy / hash conflict | 是 |
| Join Table | `pod_join_table.podY` | `PodOwnerServiceTable` | consumer bitmap / waiter list / join window | entry occupancy | 是 |
| Ready Plane | `pod_ready_table.podY` | `PodReadyFanoutPlane` | shared completion 到 core-private wakeup 的 fanout | ready queue depth | 是 |
| Replay/Rescue Plane | `pod_replay_queue.podY` | `PodOwnerServiceTable` | late split / abort / replay rescue | replay queue depth | 否 |
| Value Residency Plane | `pod_value_store.podY` | `PodValueResidencyPlane` | shared value line/refill/evict | value banks / refill pressure | 否 |

结论：

- `P-scope` 是第一阶段最重要的落点；
- `Phase-1` 只先做 metadata owner plane，不急着把 value residency 完整搬过来。

### 3.3 `E-scope` 对象表

| 对象族 | 建议对象名 | owner | 主要职责 | stall/pressure 来源 | `Phase-1` |
| --- | --- | --- | --- | --- | --- |
| Activation Ingress | `activation_ingress_store` | `PeSharedCoreFabric` | PE 入口 spike/packet 缓冲与粗筛 | ingress occupancy | 保留 |
| Packet Transport | `pe_packet_transport` | `OptimizedInternalRing` | packet plane 路由 | ring VC/credit | 保留 |
| Control Transport | `pe_control_transport` | `PeSharedCoreFabric` | owner announce / join route / release / local sync transport | control queue pressure | 部分 |
| Directory Plane | `pe_object_directory` | `PeDirectoryPlane` | object 粗粒度定位、pod 归属、redirect | directory occupancy | 否 |
| Admission Plane | `pe_admission_budget` | `PeAdmissionController` | 跨 pod budget / fairness / throttling | admission throttle | 否 |
| Sync Plane | `pe_local_sync` | `PeLocalSyncController` | pod 粒度 bounded local synchronization | sync skew / wait cycles | 观察态 |

结论：

- `E-scope` 不直接提供高频 metadata/value service；
- 它只负责把对象请求引到正确 pod，并限制系统性失控。

---

## 4. 消息表：PE 内部必须出现哪些正式消息

### 4.1 `Phase-1` 必须落地的消息

| 消息名 | 路径 | 生产者 | 消费者 | 负载 | 作用 |
| --- | --- | --- | --- | --- | --- |
| `FRONTIER_EXPORT` | `C -> P` | core-private metadata probe | `PodMetadataObjectPlane` | object key、core id、step/window id、domain id | 在 private issue 前导出候选对象 |
| `OWNER_ANNOUNCE` | `P -> C` | `PodOwnerServiceTable` | pod 内 cores | object key、owner id、transaction id | 宣告某对象已存在 owner-first transaction |
| `JOIN_REQUEST` | `C -> P` | core-private issue gate | `PodOwnerServiceTable` | object key、consumer id、join mode | exact consumer 申请加入已有 transaction |
| `READY_FANOUT` | `P -> C` | `PodReadyFanoutPlane` | pod 内 consumers | transaction id、consumer bitmap、ready token | 通知 core-private wake queue 某 shared object 已 ready |
| `JOIN_REJECT` | `P -> C` | `PodOwnerServiceTable` | core-private issue gate | reject reason | join 失败时转回 private fallback |

### 4.2 后续阶段预留消息

| 消息名 | 路径 | 作用 |
| --- | --- | --- |
| `VALUE_REFILL_ANNOUNCE` | `P -> P/C` | shared value residency refill 可见性 |
| `RELEASE` | `C -> P` | last-consumer drain / transaction release |
| `REPLAY_RESCUE` | `P -> C/P` | late split / abort 后恢复 |
| `POD_REDIRECT` | `E -> C/P` | object key 被目录引导到另一 pod |
| `LOCAL_SYNC_TICK` | `E/P -> P/C` | bounded local synchronization tick |

### 4.3 一个重要约束

这些消息不是把 today packet plane 换名字，而是：

- **第一次把 PE 内部的 control-plane 变成架构一等公民。**

没有这层，shared object/service 仍会继续退化成私有路径旁路 patch。

---

## 5. 核心 Contract

### 5.1 Owner Contract

对任何进入 `P-scope` 的共享对象，必须满足：

1. 同一时刻至多一个 active owner transaction；
2. owner 在 `private issue` fanout 前被建立；
3. later consumer 只能 join 既有 transaction，不能静默复制同一 work。

### 5.2 Scope Contract

对象在哪一层 scope，被谁仲裁、谁维护 residency、谁产生 ready，就必须都在同一层完成。

也就是：

- **object scope = arbitration scope = service scope = residency scope**

这条 contract 直接避免 today 那种：

- 对象名义是 `PerPe`
- 运行时却是 `per-core proxy`

的断层。

### 5.3 Object Transaction Contract

后续调度单位不再是：

- `per-core read request`

而是：

- **`object transaction`**

它至少包含：

1. `object key`
2. `scope id`
3. `owner core`
4. `consumer bitmap`
5. `service stage`
6. `ready state`
7. `fallback / abort state`

### 5.4 Commit Contract

必须显式保持：

1. shared service completion 不等于 architectural commit；
2. shared ready fanout 只改变 local ready，不改变最终 visibility order；
3. 最终 state update 与 retire 仍由 `C-scope` 独立完成。

### 5.5 Local Sync Contract

`Phase-1` 不做全局 barrier，只做 bounded local sync：

1. 只在 pod 内建立有限 skew 窗口；
2. 只约束 owner-first window，不约束整个 PE；
3. 若超出窗口，允许 reject/fallback，而不是拖垮全局推进。

---

## 6. 推荐的数据流

`Phase-1` 推荐的最小可用数据流是：

1. core 在本地形成 metadata frontier；
2. frontier 先通过 `FRONTIER_EXPORT` 送到 `P-scope`；
3. `P-scope` 对 object key 做 owner lookup / allocate；
4. 若当前 core 不是 owner，则等待 `OWNER_ANNOUNCE` 或主动 `JOIN_REQUEST`；
5. owner 在 `P-scope metadata object plane` 上发起真实 transaction；
6. transaction 完成后，`READY_FANOUT` 广播到各 core-private wake queue；
7. core 仅在本地恢复、继续 compute / retire；
8. commit 仍然按原来的 core-private exact 规则发生。

关键变化只有一句话：

- **shared service 的启动点前移到了 `private issue` 之前。**

---

## 7. Phase-1 只做什么

### 7.1 `Phase-1` 主线

`Phase-1` 只落一条主线：

- **`pod-shared metadata object plane + owner-first control plane`**

更具体地说，就是只覆盖：

1. `idx2`
2. `rowidx`
3. `pre-band / pre-base`

这类更早、更轻、跨 core overlap 更强的 metadata 对象。

### 7.2 为什么不先做 shared value plane

因为 value plane 太接近最终消费点，若在架构未定前先做，很容易重新掉回：

- owner 太晚；
- join-only；
- residency capture 冒充 early seed。

所以 `Phase-1` 的正确顺序是：

- **先把 metadata object owner/transaction 做对，再谈 value residency。**

### 7.3 `Phase-1` 的 fallback 策略

所有 `Phase-1` 路径都必须允许以下 fallback：

1. owner table 满时回退 private path；
2. join window 超时回退 private path；
3. `JOIN_REJECT` 后由 core 走原始 private issue；
4. default 参数全部关闭时，行为与 baseline 完全一致。

---

## 8. 与当前代码的映射关系

### 8.1 保持不动的部分

以下对象/类在 `Phase-1` 中原则上保持 today 语义不变：

1. `DefaultSnnComputeCore`
2. `state_sram_model_`
3. `AccumulatorOps`
4. `core-private retire queue / ready bookkeeping`
5. `OptimizedInternalRing` 的 packet 平面

### 8.2 要扩展但不推翻的部分

#### `PeSharedCoreFabric`

today 它更像 ingress/harbor/descriptor 骨架。  
`Phase-1` 要把它向 `E-scope control transport` 推进一层：

1. 保留 packet ingress 与 gather/descriptor 观测能力；
2. 新增 pod/control queue 与正式 control message 类型；
3. 不要求它直接承担 metadata service 执行。

#### `LocalStorageHierarchyController`

today 它是 object namespace。  
`Phase-1` 继续把它当 object 命名源，而不是完整 scheduler。

它需要新增的不是复杂逻辑，而是：

1. 支持 `pod_metadata_store.podY`
2. 支持 `pod_owner_table.podY`
3. 支持 `pod_ready_table.podY`

#### `WeightMemorySubsystem`

today 它是 monolithic per-core service/commit 内核。  
`Phase-1` 不拆掉它，但要在 metadata 路径前端插入一个 `P-scope issue gate`：

1. metadata 对象先问 pod owner plane；
2. 若命中 owner-first transaction，则 core 走 join path；
3. 若无可用 owner，则回退到 today private metadata issue。

### 8.3 要新增的最小结构

建议新增以下最小结构：

1. `PodMetadataObjectPlane`
2. `PodOwnerServiceTable`
3. `PodReadyFanoutPlane`
4. `PeControlMessage` 或等价 control message 类型

这些结构应尽量放在：

- `services/local_storage/`
- `services/pe_fabric/`

下，以保持 today 代码组织的连续性。

---

## 9. `Phase-1` 的参数与隔离策略

### 9.1 总开关

建议增加一组新的强隔离参数，默认全部关闭：

1. `pe_internal_cpe_enable = 0`
2. `pe_internal_pod_enable = 0`
3. `pe_internal_pod_metadata_enable = 0`
4. `pe_internal_pod_owner_actual_enable = 0`
5. `pe_internal_pod_ready_enable = 0`

### 9.2 尺寸参数

建议新增：

1. `pe_internal_pod_count`
2. `pe_internal_pod_size`
3. `pe_internal_pod_owner_entries`
4. `pe_internal_pod_join_entries`
5. `pe_internal_pod_ready_entries`
6. `pe_internal_pod_metadata_banks`

### 9.3 策略参数

建议新增：

1. `pe_internal_owner_window_cycles`
2. `pe_internal_join_window_cycles`
3. `pe_internal_owner_min_consumers`
4. `pe_internal_metadata_object_kind`
5. `pe_internal_fallback_policy`

这些参数的意义不是调收益，而是：

- **先把结构边界与容量边界实验化。**

---

## 10. `Phase-1` 需要的统计

为了避免再掉回“计数器热闹但不知道有没有进到正确边界”，`Phase-1` 需要固定导出以下统计：

### 10.1 Ownership

1. `pe_pod_owner_lookup_total`
2. `pe_pod_owner_alloc_total`
3. `pe_pod_owner_hit_total`
4. `pe_pod_owner_reject_total`

### 10.2 Join

1. `pe_pod_join_request_total`
2. `pe_pod_join_grant_total`
3. `pe_pod_join_reject_total`
4. `pe_pod_join_before_private_issue_total`

### 10.3 Compression

1. `pe_pod_duplicate_metadata_issue_elided_total`
2. `pe_pod_shared_transaction_consumers_avg`
3. `pe_pod_shared_transaction_lifetime_cycles_avg`

### 10.4 Exactness Overhead

1. `pe_pod_ready_fanout_total`
2. `pe_pod_local_sync_wait_cycles_total`
3. `pe_pod_fallback_private_issue_total`
4. `pe_pod_commit_blocked_cycles_total`

只要这组统计不齐，后面就很难判断我们到底是在做真正的 `P-scope owner-first transaction`，还是又在做一个 fancy 的 late join patch。

---

## 11. 第一阶段实现顺序

### Step P1.1：冻结 pod 划分与对象注册

先把 `pod` 作为正式概念接入 `MultiCorePE` 与 `LocalStorageHierarchyController`：

1. 确定 core 到 pod 的映射；
2. 注册 `pod_metadata_store / pod_owner_table / pod_ready_table`；
3. 默认开关全关。

### Step P1.2：定义 control message

在 `PeSharedCoreFabric` 侧定义：

1. `FRONTIER_EXPORT`
2. `OWNER_ANNOUNCE`
3. `JOIN_REQUEST`
4. `READY_FANOUT`
5. `JOIN_REJECT`

先做 observe/shadow path，再做 actual。

### Step P1.3：落 metadata owner gate

在 `WeightMemorySubsystem` metadata issue 前插一层：

1. export frontier；
2. lookup owner table；
3. allocate/join/fallback；
4. shared transaction 完成后 fanout。

### Step P1.4：补齐 probes 与 isolated mainexp

所有新统计进入 `essential_summary_mesh.json`，并用独立 `mainexp` 路径做 smoke/AB。

---

## 12. 最终判断

这份设计稿真正要冻结的核心不是某个细节机制，而是一条新的研究纪律：

- **不要再把 PE 内部优化写成“在现有私有热路径外围拼更多共享 patch”；**
- **而要把 PE 当成一台三层作用域机器，先定义 object、message、owner、sync、commit，再讨论收益。**

如果 `Phase-1` 能把 `pod-shared metadata object owner-first launch` 真正做成，即使性能还没有立即转正，也已经意味着我们第一次离开了旧怪圈。

---

## 13. 与前序文档的关系

这份文档是以下文档的进一步收敛：

- [PE 内部通用体系结构深度研究](./2026-03-24-pe-internal-generic-architecture-research.md)
- [PE 内部优化现状、怪圈根因与下一阶段路线图](./2026-03-24-pe-internal-optimization-loop-rootcause-and-next-stage.md)
- [PE 内部架构基线模型](./2026-03-21-pe-internal-architecture-baseline-model.md)
- [runtime owner -> local object 绑定表](./2026-03-21-pe-internal-runtime-owner-local-object-binding.md)
- [PE 内部存储映射审阅](./2026-03-21-pe-internal-storage-mapping-review.md)

它们的关系是：

1. baseline 文档描述 today 是什么；
2. root-cause 文档解释为什么我们总在怪圈里；
3. research 文档定义 generic PE 应该是什么；
4. **本设计文档把 generic PE 压成可落的第一阶段实现稿。**
