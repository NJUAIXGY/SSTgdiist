# PULSE-OSA Phase-1.5 Metadata Transaction Plane Design

> 日期：2026-03-30  
> 状态：design v1  
> 目标：把当前 `owner-first + metadata frontier + rowdescriptor join` 从“局部共享 patch”收敛成一个真正可实现、可验证、可论文化的 `P-scope shared metadata architecture`。  
> 工作名：`PULSE-OSA-MTP` = `Pod-scoped Metadata Transaction Plane`

---

## 0. 一句话结论

下一阶段最值得正式推进的，不是继续调 `shared ingress`、也不是直接重写整个 `value plane`，而是：

- **先把 `idx2 / rowidx / pre-band / rowdescriptor` 收成一个 `pod-scoped metadata transaction plane`，用 `ready-lease join` 把今天大量的 `late_join` 转化成真正可消费的 shared service。**

这条路线的核心价值不是“又做一个共享结构”，而是第一次把以下三件事统一起来：

1. `PE local storage object model`
2. `WMS internal metadata hot path`
3. `shared service completion != core-private exact commit`

因此，这份设计推荐的 canonical 主线是：

- **`metadata frontier export -> pod owner transaction -> ready-lease join -> contracted value envelope -> core-private exact commit`**

---

## 1. 为什么现在必须换主问题定义

截至 2026-03-30，当前代码与实验已经给出三个非常硬的事实。

### 1.1 `shared ingress` 已经被证明不是主收益通道

[2026-03-16-pe-core-pulse-design.md](/home/xgy/remote/exp_opt/2026-03-16-pe-core-pulse-design.md) 已经明确否定了“继续围绕 ingress 调参数”这条路。  
最新 owner-first frontier 路径中，`pulse_ingress_actual_participation_ratio = 0`，说明今天真正发生 shared behavior 的位置，已经不在 ingress，而在 metadata/service seam。

### 1.2 共享机会大量存在，但大多到达得太晚

在最新闭环 run：

- `/home/xgy/remote/mainexp/experiments/2026-03-27_pulse_owner_first_frontier_combo_ab_v1/runs/pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top32_observe_band128_preband_band96_budget6/20260330-091923`

我们观察到：

- `pulse_metadata_frontier_base_overlap_ratio = 0.93837890625`
- `pulse_metadata_frontier_band_overlap_ratio = 0.95`
- `pulse_pod_rowdescriptor_owner_first_issue_deferred_total = 1426`
- `pulse_pod_rowdescriptor_join_live_total = 194`
- `pulse_pod_rowdescriptor_join_ready_total = 0`
- `pulse_pod_rowdescriptor_late_join_total = 1232`

这说明：

- overlap 已经非常强；
- owner-first transaction 也真实存在；
- 但绝大多数 consumer 仍然在 owner transaction 生命周期之后才赶到。

换句话说，问题不再是“有没有共享机会”，而是：

- **共享对象没有形成足够明确、足够稳定、可等待的生命周期。**

### 1.3 现有 shared behavior 仍然停留在 `per-core WMS` 外围

[2026-03-21-pe-internal-architecture-baseline-model.md](/home/xgy/remote/exp_opt/2026-03-21-pe-internal-architecture-baseline-model.md) 和
[2026-03-21-pe-internal-storage-mapping-review.md](/home/xgy/remote/exp_opt/2026-03-21-pe-internal-storage-mapping-review.md)
已经证明 today baseline 的真实形态仍是：

- `B0 = per-core private execution + PE-scoped shared helpers/providers + WMS-internal shared service semantics`

最关键的断层是：

- 对象层已经有 `PerPe` / `PerCore` 命名；
- 但 runtime owner 与真正的 `WMS` 执行热路径还没有对齐。

因此，下一阶段的关键不是继续补 patch，而是：

- **先把 metadata plane 变成一个真正 owner-scoped 的 shared object plane。**

---

## 2. 设计空间比较

### 2.1 方案 A：继续沿当前 owner-first patch 细调

思路：

- 保持现有 `rowdescriptor owner-first`
- 继续调 `frontier top-H / band slots / budget / register trigger`
- 不改 shared object 生命周期

优点：

- 风险最低；
- 改动最小；
- 对当前实验链友好。

缺点：

- `late_join` 很难根治；
- 仍然没有正式的 object transaction；
- 论文主张容易继续停留在 “a better heuristic”。

结论：

- 适合作为对照，不适合作为 canonical next step。

### 2.2 方案 B：直接做 shared value plane

思路：

- 让 `weight_idx_store / weight_value_store` 直接 owner-scoped shared
- metadata 仍只做辅助

优点：

- 理论上更接近 memory-side 真收益；
- 更容易击中 `memctrl.req_total`。

缺点：

- 一步跨太大；
- 容易把 correctness、retire、shared residency 生命周期一起搅在同一阶段；
- 在当前 `ready_join = 0` 的情况下，value plane 很可能继续变成 late-join patch。

结论：

- 是后续 Phase-V 的方向，但不适合当下首阶段主线。

### 2.3 方案 C：`PULSE-OSA-MTP`

思路：

- 把 `idx2 / rowidx / pre-band / rowdescriptor` 收成 `P-scope metadata transaction`
- 显式引入 `owner -> ready lease -> join -> release`
- 输出 `contracted value envelope`
- 保持 `C-scope exact commit` 完全不动

优点：

- 与当前实验事实最一致；
- 可以直接瞄准 `late_join` 这个主损失项；
- 既能形成顶会叙事，也能保持工程隔离。

结论：

- **推荐作为下一阶段唯一主线。**

---

## 3. 核心主张

`PULSE-OSA-MTP` 的核心主张不是 “共享 metadata”，而是以下四条 contract：

### 3.1 Object Contract

任何进入 shared path 的 metadata 对象，必须被正式表示为：

- `object key`
- `scope id`
- `owner transaction id`
- `service stage`
- `ready lease state`
- `consumer bitmap`

没有 transaction 的共享，只能算 patch，不算 architecture。

### 3.2 Scope Contract

metadata object 的：

- object scope
- owner scope
- join scope
- ready fanout scope
- lease scope

必须统一落在同一个 `P-scope` 内。

### 3.3 Value Envelope Contract

metadata transaction 本阶段不直接产出 architectural value，而是产出：

- `idx2 decoded span`
- `rowidx span`
- `pre-band candidate line set`
- `rowdescriptor candidate line/block envelope`

也就是：

- **先共享“能把 exact demand 收得更早更窄的 envelope”，而不是立刻共享最终 weight line。**

### 3.4 Commit Contract

必须保持：

- shared service completion != architectural commit
- shared ready fanout 只改变 local ready
- 最终 state visibility 仍由 `C-scope core-private retire` 决定

这条 contract 是整条设计能继续 paper-safe 的根本。

---

## 4. 顶层结构

`PULSE-OSA-MTP` 把当前 PE 内部路径正式分成四层：

1. `C-scope core-private compute/commit plane`
2. `P-scope metadata transaction plane`
3. `P-scope ready lease / join plane`
4. `E-scope transport / directory / admission plane`

推荐的数据流是：

- `per-core frontier export`
- `pod metadata object collect`
- `owner-first transaction launch`
- `exact join or reject`
- `ready lease retention`
- `contracted value envelope emit`
- `core-private exact demand / compute / commit`

其中真正的新结构只有 `P-scope` 两层，避免把整个 PE 一口气重构。

---

## 5. 共享对象定义

### 5.1 第一批对象

第一批必须进入 transaction plane 的对象：

1. `idx2`
2. `rowidx`
3. `pre-band`
4. `rowdescriptor`

选择理由：

- 它们比 value line 更早；
- overlap 已经在 observe-only 实验中被证明很强；
- 它们本身更轻，更容易形成 owner transaction 与 ready lease。

### 5.2 暂不进入第一批的对象

这一阶段不直接共享：

1. `weight value line residency`
2. `state_store`
3. `accumulator_store`
4. `register_file`
5. `retire_queue`

原因：

- 这些对象要么直接进入 commit plane，要么生命周期和 correctness 更重；
- 现在强推只会扩大不确定性。

---

## 6. Metadata Transaction Plane 结构

### 6.1 核心结构

推荐新增三个 `P-scope` 结构：

1. `PodMetadataObjectPlane`
2. `PodOwnerTxnTable`
3. `PodReadyLeaseTable`

它们的职责分别是：

- `PodMetadataObjectPlane`
  - 承接各 core export 的 metadata object；
  - 建立 object key 到 transaction key 的绑定；
  - 管理 object-level residency / pressure / bank accounting。

- `PodOwnerTxnTable`
  - 决定谁成为 owner；
  - 记录 consumer bitmap；
  - 记录当前 transaction stage；
  - 给 later consumer 提供 join / reject 决策。

- `PodReadyLeaseTable`
  - 在 owner service 完成后保留一个 bounded ready window；
  - 让晚到但仍在 lease 内的 consumer 不必退回 private owner launch；
  - 把今天的 `late_join` 转换成 `ready_join`。

### 6.2 关键状态机

推荐 transaction 状态机如下：

- `Collect`
- `OwnerLaunched`
- `ReadyLease`
- `Joined`
- `Released`
- `FallbackClosed`

其中最关键的新态是：

- `ReadyLease`

因为今天的共享损失，不是 owner 没发出去，而是 owner 发完后对象立即消失，later consumer 只能记成 `late_join`。

---

## 7. 与 WMS 的绑定方式

### 7.1 不重写 WMS，只加一个 shim

这一阶段不直接推翻 `per-core WMS`。  
建议引入一个窄接口：

- `WmsMetadataTxnShim`

它的职责只有三件事：

1. 在 `WMS` 进入 exact metadata demand 之前，先向 `PodMetadataObjectPlane` 查询；
2. 返回 `owner-launch / join-live / join-ready / reject-private` 四种结果；
3. 若命中 transaction，则返回 `contracted value envelope` 给 `WMS` 后续路径消费。

### 7.2 绑定点

建议绑定在以下已有热点上：

- `prepareGcssVlfIssueQueue_()`
- `lookupGcssPreBaseLen_()` 之后的 metadata frontier 形成点
- `rowdescriptor owner-first` 现有 seam

也就是：

- 不从 packet 层切；
- 不从最终 value fill 层切；
- 直接从 `WMS` 已有 metadata hot path 切进去。

### 7.3 为什么这是最稳的

这样做的好处是：

- 不改变 `core -> WMS -> exact value issue` 的基线 ownership；
- 只在 metadata stage 前插入一个可关闭的共享事务层；
- 一旦发现不成立，直接全局 feature-flag 关闭即可回退。

---

## 8. Ready-Lease 机制

### 8.1 为什么必须引入 lease

当前最大问题不是 owner-first 没工作，而是：

- owner 命中后，later consumer 大量落成 `late_join`

因此必须把 ready 从“瞬时事件”升级成“短寿命对象状态”。

### 8.2 机制定义

每个 transaction 在进入 ready 后，不立即 release，而是保留：

- `lease_start_cycle`
- `lease_ttl_cycles`
- `lease_consumer_budget`

只要 later consumer 在 lease 内到达，就可以：

- 不再单独 owner-launch；
- 不再退回 private metadata issue；
- 直接计入 `ready_join`。

### 8.3 边界

lease 只服务于：

- metadata object
- contracted value envelope

lease 不直接跨入：

- final value writeback
- final architectural retire

这样能把 correctness 风险控制在最小范围。

---

## 9. Contracted Value Envelope

这是这份设计最重要的新接口定义。

### 9.1 为什么需要 envelope

如果 metadata plane 只负责 “观察 overlap”，它仍然是 observe-only；
如果它直接返回 final value，它又会过早进入 value plane/commit plane。

因此中间必须有一层正式对象：

- `contracted value envelope`

### 9.2 envelope 的内容

推荐最小字段：

- `object_key`
- `window_seq`
- `owner_txn_id`
- `candidate_kind`
- `candidate_begin`
- `candidate_count`
- `line_or_block_span_bound`
- `consumer_bitmap`

### 9.3 envelope 的作用

它告诉后续 `WMS`：

- 这个 core 的 exact demand 不必从零开始解码；
- 哪些 line/block/span 已被 pod 级 metadata transaction 收缩过；
- 当前 exact demand 只需在 bounded candidate set 内继续推进。

这让下一阶段从 metadata plane 过渡到 value plane 时，有一个干净的接口。

---

## 10. 与 local storage object model 的关系

这份设计必须与 [2026-03-21-pe-internal-storage-mapping-review.md](/home/xgy/remote/exp_opt/2026-03-21-pe-internal-storage-mapping-review.md) 对齐。

今天的真实问题是：

- `LocalStorageHierarchyController` 已经注册了对象；
- `WMS internal storage model` 也已经真实存在；
- 但两者之间缺少 runtime owner binding。

`PULSE-OSA-MTP` 的作用，就是先给 metadata plane 建立这层绑定。

推荐映射：

- `weight_idx_store`
  - 先成为 `PodMetadataObjectPlane` 的 primary backing object
- `weight_value_store`
  - 暂时只作为 envelope 的下一阶段目标，不在 Phase-1.5 actual化
- `activation_ingress_store`
  - 继续维持当前角色，不再作为主创新点

---

## 11. 正确性与隔离策略

### 11.1 正确性

必须冻结以下规则：

1. transaction 只能改变 metadata owner / join / ready，不改变 final commit order
2. `ready_join` 只能替代 private metadata launch，不能直接跳过 core-private exact demand validation
3. envelope 只提供 bounded candidate set，不提供 architectural visibility
4. `C-scope` retire queue 完全不受本阶段行为改写

### 11.2 隔离

所有新能力必须受独立开关控制，建议包括：

- `pulse_osa_enable`
- `pulse_osa_metadata_txn_enable`
- `pulse_osa_metadata_ready_lease_enable`
- `pulse_osa_metadata_ready_lease_ttl`
- `pulse_osa_metadata_txn_object_mask`

默认全部关闭，确保 baseline 无漂移。

---

## 12. 评价指标

下一阶段必须增加的指标，不再只是 overlap/owner-first 的静态观测，而是完整 funnel：

1. `metadata_txn_export_total`
2. `metadata_txn_owner_launch_total`
3. `metadata_txn_join_live_total`
4. `metadata_txn_join_ready_total`
5. `metadata_txn_late_join_total`
6. `metadata_txn_reject_total`
7. `metadata_txn_ready_lease_hit_total`
8. `metadata_txn_ready_lease_expired_total`
9. `metadata_txn_envelope_size_sum_total`
10. `metadata_txn_envelope_to_exact_issue_ratio`

同时要补 runtime overhead：

1. `metadata_txn_table_occupancy_peak`
2. `metadata_txn_ready_lease_occupancy_peak`
3. `metadata_txn_bank_conflict_cycles_total`
4. `metadata_txn_callback_hold_cycles_total`
5. `metadata_txn_private_fallback_due_to_pressure_total`

---

## 13. 成功标准

`Phase-1.5` 的成功，不要求立刻大幅降 `memctrl.req_total`，但必须满足：

1. `ready_join_total > 0`
2. `late_join_share` 相比当前显著下降
3. `owner_first_service_elide / issue_deferred` 明显高于当前约 `0.136`
4. baseline 关闭时完全零漂移
5. correctness 统计不恶化

更理想的加分项是：

1. `memory_requests` 首次出现可见下降
2. `pulse_osa_shared_weight_*` 开始从全零进入 shadow-active 状态

---

## 14. 风险与应对

### 14.1 风险：transaction plane 自己变成新的中心化热点

应对：

- 只做 `pod-scoped`
- 不直接做 whole-PE global table
- 加 occupancy/bank-pressure 统计

### 14.2 风险：lease 把 correctness 搅进 commit plane

应对：

- lease 只保 metadata ready，不保最终 architectural value visibility
- 所有 final commit 仍由 core-private 路径决定

### 14.3 风险：又退化成 fancy late-join patch

应对：

- 强制新增 `ready_join_total` 与 `lease_hit_total`
- 若这两个长期接近零，则这条路线判定为 `NO-GO`

---

## 15. 最终推荐

下一阶段最佳方案应正式冻结为：

- **`PULSE-OSA Phase-1.5: Pod-Scoped Metadata Transaction Plane with Ready-Lease Join`**

它是当前所有候选里最平衡的一条：

- 比继续调 patch 更像 architecture；
- 比直接推 value plane 更稳；
- 比继续围绕 ingress 打转更接近真正的 PE 内共享结构。

一句话收口：

- **先把 metadata 对象做成真正的共享事务层，再让它去牵引 value plane 和后续 domain-local retire。**
