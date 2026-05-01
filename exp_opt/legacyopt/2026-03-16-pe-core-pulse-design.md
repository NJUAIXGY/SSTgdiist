# PULSE：面向 ISCA/ASPLOS 的 PE 内 core-level 新主线设计草案（v5）

> 日期：2026-03-24  
> 状态：design + shadow-runtime evidence + isolated ready-join dedup v5  
> 工作名：`PULSE-GDR` = `PE-shared Unified Local Service and Execution fabric with Gather-bounded Descriptor service and Retire domains`  
> 目标：把当前 `DRAM-based SNN chip + GAS + GCSS-GLIDE + STORM + MulticastRouter` 主线，向 `PE` 内部推进成一条真正可论文化、可实现、可验证、且在当前代码基线下能产生显著收益的 `core-level` 新主线。  
> v5 修订重点：
> - 保留 `v3` 对 `shared ingress actual v1` 的否定结论，但文档状态不再停留在 `design-only`
> - 明确记录 `C0 + C1` 已在代码中落地为 `shadow service-object skeleton`
> - 明确记录 `rowdescriptor` 真实 `WMS` runtime 已经接通 `owner form -> live join -> ready join -> release -> late join`
> - 明确记录 `ReadyFanout` shadow evidence 已经真实接入 `rowdescriptor` seam 与 `PeSharedCoreFabric`
> - 明确记录第一条 actual optimization 已经以隔离开关形式落地：`experimental_rowdescriptor_ready_join_dedup_enable`
> - 说明我们已经从 `metadata overlap` 进入 `service-object lifecycle evidence`，再进入 `ready-join descriptor-planner dedup`

## 0. 一句话结论

`shared ingress actual path v1` 证明了 `PULSE` 路径可以真实接管数据面，但它也明确证明了一件更重要的事：

- **只做 ingress 共享不会显著提升当前主线。**

原因不是实现粗糙，而是收益通道没打通：

- 它没有减少 `memory requests`
- 没有减少 `memctrl req_total`
- 没有改变 `frontend granule/service` 数量
- 没有触碰当前最重的 `cross-post HOL under PE-wide global retire`

因此，`v3` 把主线收敛成一个更硬的命题：

- **PULSE 的第一性收益必须来自 `packet-first -> descriptor-first shared service`，以及 `PE-wide global retire -> domain-local exact retire`。**

换句话说，`PE` 内最值得共享的，不是“再加一层入口队列”，而是：

- receiver-side activation 在 gather 边界形成的共享 service opportunity；
- 同 `weight region / post block / retire domain` 的 descriptor 级合并与共享 refill；
- 在不破坏 strict correctness 的前提下，释放跨 post/domain 的 retire HOL。

---

## 1. 为什么 v3 必须建立在 fresh 实验结果之上

我们已经完成一轮 fresh A/B：

- baseline run：
  - `mainexp/experiments/2026-03-16_pulse_shared_ingress_actual_ab_v1/runs/baseline_step1_seed_only_frac003/20260316-233622`
- `shared ingress actual path v1` run：
  - `mainexp/experiments/2026-03-16_pulse_shared_ingress_actual_ab_v1/runs/pulse_shared_ingress_actual_step1_seed_only_frac003/20260316-234038`

对比结果非常明确：

- `pulse_ingress_packets_total = 1,206,784`
- `pulse_ingress_bypass_total = 1,205,386`
- `pulse_ingress_entries_peak = 16`
- `pulse_core_queue_entries_peak = 1`
- `model.sim_time_actual_ns: 257,453 -> 257,691`，约 `+0.092%`
- `memory.memory_requests: 763,879 -> 763,879`
- `memhierarchy.memctrl.req_total: 150,907 -> 150,907`

这组结果说明：

1. `PULSE` 真实路径已经被激活，不是死代码。  
2. 绝大多数流量并未真正进入 shared benefit path，而是又回到了原路径。  
3. 即便进入了新路径，当前路径也没有减少真实 memory/service 工作量。  
4. 当前 slowdown 的主要来源是额外 bookkeeping，而不是 shared service 带来的结构性收益。  

因此，`v3` 的职责不是“继续调 ingress watermark”，而是重新定义：

- 什么对象应该进入 shared path；
- shared path 到底共享什么；
- 哪个瓶颈值得首先正面开刀。

---

## 2. v1 的根因诊断：为什么 shared ingress 不会自己赢

### 2.1 根因 A：当前实现共享的是 admission，不是 service

`shared ingress actual path v1` 当前只做了：

- activation 类包先进入 `PE` 级 ingress；
- 再做 endpoint-fair dispatch；
- `agenda` 仍是 observe-only；
- `retire` 仍是 `PE-wide global_inorder`；
- `weight service` 仍是 per-core `WMS` / per-core issue path。

这意味着：

- 包进入 `PE` 后的“入口形态”变了；
- 但真正昂贵的 `descriptor formation -> line service -> refill -> ready -> retire` 全部没变。

所以它天然更像：

- 一个新的 control wrapper；

而不像：

- 一个能减少真实 service 工作量的 execution substrate。

### 2.2 根因 B：当前 bypass 策略把 shared path 钉死在阈值附近

当前 `PeSharedCoreFabric` 的行为是：

1. 包到达时先 `occupancy++`
2. 若 `occupancy >= high_watermark`，则判为 `Bypass`
3. bypass/direct deliver 又会立刻 `drain`

本次配置中：

- `ingress_entries = 32`
- `bypass_high_watermark_pct = 50`
- 实际阈值 = `16`
- `ingress_entries_peak = 16`

这意味着系统长期在 `15/16` 左右震荡：

- 刚到阈值就 bypass
- bypass 后又退回阈值下
- 下一批包继续刚碰阈值就 bypass

于是 shared ingress 永远只吃到很小一部分流量。  
从结果看，真正没被 bypass 的 activation 包只有：

- `1,206,784 - 1,205,386 = 1,398`
- 占比约 `0.116%`

这不是一个“共享服务参与面”，只是一个“入口采样器”。

### 2.3 根因 C：当前最重的瓶颈根本不在 ingress

fresh summary 显示：

- `retire_wait_cycles_due_to_hol_ratio ≈ 0.996`
- `retire_crosspost_blocked_ratio ≈ 0.99895`
- `strict_repro_global_total_order_required = False`
- `strict_repro_same_post_deterministic = True`

这组数据的含义很强：

- 当前 `HOL` 的主因几乎完全来自 **跨 post / 跨 domain 的 global retire 压制**
- 并不是 ingress admission 不够快
- 也不是 bank credit / inflight cap 在卡住 issue

因此，`shared ingress` 如果不继续进入：

- shared descriptor service
- domain-local exact retire

就很难打到主矛盾。

### 2.4 根因 D：我们已经看到 `packet -> granule` 的天然压缩空间，但还没有消费它

同一轮 summary 中还有一个非常关键的信号：

- `snn_rx.spike_packets_total = 1,206,784`
- `gas.apply_completed_granules_total = 150,907`

也就是说：

- `packets_per_granule ≈ 7.997`

这说明从 packet 视角切入是错位的：

- `PE` 内天然存在接近 `8x` 的 packet-to-service 压缩空间
- 但当前实现仍然逐包观察、逐包决定、逐包投递

所以，真正应该共享的对象不是 packet 本身，而是：

- gather 边界上形成的 `activation/service descriptors`

### 2.5 根因 E：gather 足够短，完全值得作为 descriptor formation 的边界

当前同一组数据还告诉我们：

- `gather_ns_avg = 550.75ns`
- `apply_ns_avg = 238,958ns`

即 gather 仅占 apply 的：

- 约 `0.23%`

这意味着：

- 用 gather 作为 `descriptor lift` 的收敛窗口，新增等待成本极小；
- 只要它能换来 descriptor/service 级共享和 retire HOL 释放，收益远大于这点延迟。

---

## 3. v3 的核心判断：要赢，必须把主线改成 PULSE-GDR

`v3` 推荐的真正主线是：

- **`Gather-bounded Descriptor service + Retire domains`**

记为：

- **`PULSE-GDR`**

与 `v1` 的区别不是“共享更多”，而是共享对象和共享边界完全不同。

`v1` 共享的是：

- packet ingress admission

`v3` 要共享的是：

- gather 边界上的 activation descriptors；
- descriptor 对应的 `weight region / granule / refill / fanout service`；
- retire 发生前的 ready/service 状态；
- 在 exactness 不变前提下的 domain-local commit。

`v3` 的一句话结构可写成：

- **`packet-first local dispatch` -> `descriptor-first PE-shared service plane + exact per-domain commit plane`**

这条主线第一次能够同时解释：

1. 为什么 `receiver-side locality` 在当前系统里没有被 PE 内消费；
2. 为什么只做 ingress 共享不会改善 memory-side 指标；
3. 为什么当前最大 stall 来自 cross-post HOL；
4. 为什么 exactness 不需要 PE-wide total retire order。

---

## 4. PULSE-GDR 微结构总览

`PULSE-GDR` 把一个 `PE` 重新组织成 6 个功能块：

| 模块 | 作用 | 默认 scope |
| --- | --- | --- |
| `Gather-Harbor` | 在 gather 窗口内收敛 activation，形成 descriptor 候选 | per_pe |
| `Descriptor Lifter` | 按 `step/window/post_block/weight_region/retire_domain` 提升为 service descriptor | per_pe |
| `Shared Region Agenda` | 以 descriptor 为单位调度 shared refill / line service / fanout | per_pe |
| `Region Service Buffer` | 管理短期 shared residency、fanout、replay、release 生命周期 | per_pe |
| `Core Consume Queues` | 每 core 的逻辑消费队列，只接收已 service 的 operand/ready | per_core logical |
| `Domain-Local Exact Retire` | 对每个 retire domain 独立精确提交，保持 same-post determinism | per_pe |

其中最重要的边界是：

- **共享发生在 service plane，不发生在 architectural commit plane。**

这条边界在 `v2` 是对的，`v3` 继续保留；  
真正改变的是：

- 共享不再停在 ingress，而是推进到 descriptor/service；
- exactness 不再依赖 PE-wide total retire，而是依赖 per-domain exact retire。

---

## 5. Gather-Harbor：从 sticky ingress 改成 gather-bounded collector

### 5.1 基本思想

`Gather-Harbor` 不再把所有 packet 都先吃进去，再靠 watermark 把它们赶出去。  
它只做一件事：

- 在 gather 窗口内，**把可能形成 shared service opportunity 的 activation 收敛成 bucket**

它的 key 不是 `endpoint_id`，而是：

- `(step_id, gather_epoch, post_block_id, weight_region_id, retire_domain_id)`

其中：

- `post_block_id` 决定 semantic accumulation domain
- `weight_region_id` 决定 service / refill 复用机会
- `retire_domain_id` 决定 exact commit domain

### 5.2 为什么这比 v1 强

`v1` 的 shared ingress 实际上是：

- 先把所有流量变成 shared candidate
- 再靠 pressure-bypass 把大多数流量打回原路径

`v3` 反过来做：

- 只有当包有潜在 merge/service 价值时，才进入 harbor
- 单例或无共享价值流量直接 fast-bypass

换句话说：

- **shared path 只吃“值得共享的流量”，而不是“先全吃再回退”。**

### 5.3 Harbor 的三种退出方式

一个 harbor bucket 只允许三种退出：

1. `merge_emit`
   - 满足最小合并条件，提升为 descriptor
2. `singleton_fast_bypass`
   - 直到 gather close 仍只有单消费者/单 region
3. `deadline_bypass`
   - 到达 gather close 或 slack 下限，必须下发，避免拖延 apply

这三种退出方式比 `watermark bypass` 更接近真实优化目标，因为它们区分的是：

- 有共享价值 vs 无共享价值

而不是：

- 队列眼下是不是正好满到某个比例

---

## 6. Descriptor Lifter：从 packet-first 改成 descriptor-first

### 6.1 descriptor 的定义

`Descriptor Lifter` 把 gather harbor 中的 bucket 提升成 `ActivationDescriptor`：

- `step_id`
- `window_id`
- `post_block_id`
- `weight_region_id`
- `retire_domain_id`
- `consumer_core_bitmap`
- `consumer_count`
- `packet_count`
- `payload_count`
- `slack_to_apply_close`
- `region_safe`

这里最关键的是：

- 一个 descriptor 表示的是 **一次可共享的 service 工作单元**

而不是一个 packet。

### 6.2 为什么 descriptor-first 才能产生收益

当前 fresh run 已经证明：

- packet 数量：`1,206,784`
- granule 数量：`150,907`

也就是说系统本身已经在 service 阶段看到更稀疏、更结构化的对象。  
问题只是：

- 当前这个压缩发生在 per-core 私有路径内部；
- PE 并没有把它变成 shared object。

`Descriptor Lifter` 的作用，就是把这层压缩显式前移，让 `PE` 级 fabric 能看见：

- 哪些 packet 最终会服务同一组 line / region / post block

### 6.3 最小 lift 规则

为了让第一版实现稳，`v3` 推荐最小 lift 规则为：

- 同 `step_id`
- 同 `post_block_id`
- 同 `weight_region_id`
- `consumer_count >= 2`
- 或 `packet_count >= P_min`
- 不跨 `retire_domain`
- 不跨 `region_safe` 边界

这组规则天然偏保守，但已经足够在当前主线上吃到真实收益。

---

## 7. Shared Region Agenda：共享的不是发包，而是 service

### 7.1 Agenda 的对象

`Shared Region Agenda` 的对象不再是：

- 哪个 core 的下一个 packet

而是：

- 哪个 `ActivationDescriptor` 的 `weight_region / granule service`

也就是说，agenda 以 **region/granule** 为服务对象。

### 7.2 Agenda 的目标函数

`v2` 中的 agenda 打分主要还是概念化的。  
`v3` 推荐把第一版实际优化目标函数写得更直：

`score(d) = merge_gain + line_reuse_gain + fanout_gain - deadline_risk - domain_span_risk - bank_conflict_risk`

其中：

- `merge_gain`
  - 同 descriptor 聚合的 packet 数 / consumer 数
- `line_reuse_gain`
  - 共享同一 `weight_region` 的 granule 数
- `fanout_gain`
  - 一个 service 完成后可直接 fanout 的 consumer 数
- `deadline_risk`
  - 距 gather close / apply start 的 slack 是否不足
- `domain_span_risk`
  - 是否扩大 retire domain span
- `bank_conflict_risk`
  - 是否把本来可并行的 region 服务挤到同一 bank/path

### 7.3 为什么它比 current per-core WMS 更对症

当前系统里：

- `frontend_line_touch_reuse_ratio ≈ 0.656`
- `frontend_staged_reads_per_unique_line_avg ≈ 2.906`

这说明 memory-side reuse 已经存在。  
但 reuse 目前只在每个 core 自己内部被利用：

- `WMS` 是 per-core
- agenda 是 per-core
- refill 是 per-core

`Shared Region Agenda` 的本质，就是第一次让这种 reuse 在 **PE 内跨 core 可见、可调度、可服务**。

---

## 8. Region Service Buffer：共享 residency，但边界收紧

### 8.1 为什么 v3 不建议一上来做 full shared store

如果直接做完整的 `weight_idx/value` shared residency，很容易在实现上变成：

- 复杂 cache / residency / invalidation 重构

而不是：

- 一条清晰的可验证优化主线。

因此，`v3` 的第一版建议只做一个更窄的结构：

- `Region Service Buffer`

它只负责：

- 当前 active descriptors 对应的短期 shared residency
- refill 完成后的 fanout
- replay / release

### 8.2 生命周期

一个 region service entry 的生命周期定义为：

1. `reserve`
   - descriptor 被 agenda 选中
2. `refill`
   - 对应 granule/line 服务到达
3. `ready_fanout`
   - 对所有关联 consumer 做 ready latch
4. `retire_wait`
   - 等待对应 retire domains 提交
5. `release`
   - 最后 consumer drain 后释放 residency

这比 full shared store 更收敛，因为它天然是：

- bounded active descriptors only

而不是：

- 全局无界共享缓存。

---

## 9. Domain-Local Exact Retire：真正的收益主刀

### 9.1 为什么这里必须动

fresh run 已经非常清楚：

- `retire_wait_cycles_due_to_hol_ratio ≈ 0.996`
- `retire_crosspost_blocked_ratio ≈ 0.99895`
- `strict_repro_global_total_order_required = False`

这意味着：

- 我们并不需要 PE-wide global total retire order；
- 但我们正在为它付出几乎全部 HOL 代价。

所以，`v3` 必须把 exactness contract 改写为：

- **same-post deterministic**
- **exactly-once**
- **drain-before-scatter**
- **domain-local exact retire**

而不是：

- PE-wide global total retire。

### 9.2 retire domain 的定义

第一版推荐把 `retire_domain_id` 定义为：

- `post_block_id`

必要时可细化为：

- `(dst_core_id, post_block_id)`

retire key 为：

- `(step_id, window_id, retire_domain_id, edge_order_in_domain)`

规则是：

- 同一 domain 内顺序稳定
- 不同 domain 之间可独立前推

### 9.3 exactness contract

`v3` 明确将状态划分为 4 个点：

1. `service_issued`
2. `service_complete`
3. `ready_latched`
4. `retire_visible`

其中必须保持：

- `service_complete != retire_visible`
- `ready_latched != retire_visible`
- 只有 `retire_visible` 才算 architectural effect

这样可以把 shared service 和 exact retire 干净分离。

### 9.4 为什么这条线最像顶会主线

因为它不是简单地“加共享”，而是在回答一个更有价值的问题：

- **在 DRAM-backed SNN 中，strict correctness 到底要求什么级别的 determinism？**

`v3` 的回答是：

- exactness 需要的是 `domain-local exact deterministic commit`
- 而不是 `PE-wide global total order`

这条 claim 比“又做了一层 PE 内共享”更强，也更有体系结构味道。

---

## 10. PULSE-GDR 的完整数据流

### 阶段 1：Gather-bound collection

1. `Spike/SpikeKey/SpikeTileKey` 进入 `PE`
2. `Gather-Harbor` 只收集有潜在 merge/service 价值的 activation
3. 单例流量直接走 fast-bypass

### 阶段 2：Descriptor lifting

4. gather close 或 bucket 满足 lift 条件后，生成 `ActivationDescriptor`
5. descriptor 带有 `weight_region_id / post_block_id / retire_domain_id / consumer bitmap`

### 阶段 3：Shared service scheduling

6. `Shared Region Agenda` 按 score 选择 descriptor
7. `Region Service Buffer` 预留 service entry
8. descriptor 驱动 shared refill / granule service

### 阶段 4：Ready fanout

9. service 完成后，不直接提交 architectural effect
10. 只对相应 consumer 做 `ready_latched`
11. 各 core 的 consume queue 拉取 ready operand

### 阶段 5：Domain-local exact retire

12. `Domain-Local Exact Retire` 按 `(step, domain, order)` 逐域提交
13. 已 ready 但未 retire 的 consumer 只算 correctness-overhead
14. 每个 effect 只提交一次

### 阶段 6：Scatter release

15. 相关 retire domains 全部 drain 后，窗口才允许进入 scatter
16. `Region Service Buffer` 释放 shared residency

---

## 11. 为什么这版更可能在我们现有主线上产生显著收益

### 11.1 它直接命中了 packet-to-service 压缩

当前真实数据已经给出：

- `packets_per_granule ≈ 8`

所以 descriptor-first 天然存在接近 `8x` 的 control/service 聚合空间。  
这是当前代码基线上“已经存在但尚未被 PE 内结构消费”的最大机会之一。

### 11.2 它直接命中了 current main bottleneck

当前主 stall 几乎完全是：

- cross-post HOL under global retire

所以只要 retire 仍然是 PE-wide global order，shared ingress 很难显著赢。  
相反，只要释放不同 domain 之间的 commit 独立性，就有机会直接削减：

- `retire_wait_cycles_due_to_hol_total`
- `retire_policy_loss_edges_total`

### 11.3 它没有和当前 mainline 的 memory path 打架

当前 `GCSS-GLIDE` 已经把 memory-side locality 利用到很高水平。  
我们不应该重写它，而应该把它继续推进到 PE 内：

- 让 GCSS 在 DRAM request path 上发现的 locality
- 能够在 PE 内 descriptor/service 层继续被消费

这也是 `PULSE-GDR` 相比“纯 local queue 调度”的真正优势。

### 11.4 gather 足够短，适合成为聚合窗口

因为：

- `gather_ns_avg` 远小于 `apply_ns_avg`

所以把 shared descriptor formation 放在 gather-close 上，几乎不会在 critical path 上增加明显代价。  
这给了我们一个极其适合做 hardware/runtime co-design 的边界。

---

## 12. 与现有代码基线的对接方式

### 12.1 可以保留的东西

`v3` 并不要求推翻当前主线。  
以下结构可以保留：

- `MultiCorePE`
- `NocSubsystem`
- `StepActivationSubsystem`
- `LocalStorageHierarchyController`
- `PeSharedCoreFabric`
- 现有 `WeightMemorySubsystem`

### 12.2 需要重定义边界的地方

真正需要改边界的是：

| 现有对象 | v3 中的新职责 |
| --- | --- |
| `PeSharedCoreFabric` | 从 ingress mirror 提升为 `Gather-Harbor + Descriptor Lifter + Region Agenda + Retire scoreboard host` |
| `MultiCorePE::deliverPacketToEndpoint_()` | 不再把 shared 逻辑定义成 packet buffer，而是把 gather 内 eligible packet 送入 harbor |
| `WeightMemorySubsystem` | 增加 descriptor-level shared service hook，而不是仅有 per-core issue |
| `SnnWorkload` / `SnnPESubComponent` | 从“立即消费 packet”扩展为“消费 ready descriptor / ready operand” |
| retire path | 从 `global_inorder` 增加 `shadow domain` 与 `actual domain` 两阶段 |

### 12.3 强隔离开关

和之前一样，`v3` 必须保持强隔离：

- 默认关闭
- 单独实验目录
- 不影响 baseline
- 所有 actual 特征均有独立 flag

推荐新增的主开关层次为：

- `pulse_enable`
- `pulse_descriptor_enable`
- `pulse_descriptor_actual_enable`
- `pulse_retire_domain_shadow_enable`
- `pulse_retire_domain_actual_enable`

---

## 13. v3 需要守住的五条正确性不变量

### I1. Weight-ready before retire-visible

descriptor 对应的 line/granule service 必须完成后，相关 consumer 才能进入 `retire_visible`。

### I2. Drain-before-scatter

一个窗口只有在所有相关 retire domain 全部 drain 后，才能进入 scatter。

### I3. Same-post deterministic order

命中同一 `post_block / retire_domain` 的 effect 必须保持稳定顺序。

### I4. Exactly-once effect

同一 consumer effect 只能获得一个唯一 retire token，只能提交一次。

### I5. Shared service completion is not commit

`service_complete`、`ready_latched` 只代表物理服务完成，不代表 architectural visibility。

---

## 14. v3 的论文 novelty carve-out

现有工作大致落在三类：

1. local core / neurocore co-location
2. cluster shared SRAM
3. message-driven active routing / message handling

`PULSE-GDR` 的 novelty 边界应当收紧成：

- 现有工作要么把 locality 留在 NoC / router 侧，要么把 cluster 组织停留在 shared SRAM / PE co-location 层，要么只优化消息处理本身；
- **`PULSE-GDR` 的不同点在于：它把 receiver-side locality、descriptor-first shared synapse service、以及 domain-local exact retire，统一进同一个 PE-internal contract。**

这比 `shared ingress` 的论证要强得多，因为它直接回答：

- 在 DRAM-backed SNN 中，PE 内应该共享什么？
- 正确性到底要求什么？
- 如何在不破坏 exactness 的情况下释放 PE 内 memory-level parallelism？

---

## 15. 评估口径：v3 应该怎么证明自己

### 15.1 端到端指标

- `sim_time_actual_ns`
- `gsops_step`
- `memory_requests`
- `memctrl.req_total`
- `memctrl_payload_utilization`

### 15.2 descriptor/service 指标

这些是 `v3` 比 `v1` 新增的主图候选：

- `pulse_descriptor_total`
- `pulse_descriptor_packet_sum`
- `pulse_packets_per_descriptor_avg`
- `pulse_descriptor_consumer_fanout_avg`
- `pulse_shared_service_hits_total`
- `pulse_shared_service_replays_total`
- `pulse_region_service_entries_peak`
- `pulse_region_service_residency_cycles_total`

### 15.3 usefulness breakdown

必须把 shared candidate 分成 4 类：

- `singleton_fast_bypass`
- `deadline_bypass`
- `descriptor_emit_but_no_shared_hit`
- `descriptor_emit_and_shared_hit`

这样才能证明：

- 我们不是“把很多流量送进 shared path”
- 而是“只让值得共享的流量进入 shared path，并且真的复用了 service”

### 15.4 correctness-overhead

继续保留并增强：

- `pulse_correctness_ready_blocked_cycles_total`
- `pulse_correctness_scoreboard_occupancy_peak`
- `pulse_retire_domain_hol_cycles_total`
- `pulse_retire_domain_active_peak`
- `pulse_retire_global_head_blocked_cycles_total`

### 15.5 关键对比组

推荐至少 5 组：

1. frozen baseline：`per-core WMS + global_inorder retire`
2. `shared ingress actual v1`
3. `descriptor lift only`
4. `descriptor service + global retire`
5. `descriptor service + domain-local exact retire`

这样可以清楚回答：

- 收益主要来自 packet-to-descriptor 压缩，还是来自 retire reform；
- 若没有 domain-local retire，descriptor-first 到底能走多远。

---

## 16. 当前代码落地状态（2026-03-24）

### 16.1 已完成的 shadow-only 落地

当前 `PULSE` 线已经不再只是“设计图 + observe-only overlap 统计”，而是进入了一个更硬的阶段：

- `PE` 内部已经新增独立的 `shadow service-object` 容器，用来刻画：
  - `owner form`
  - `live join`
  - `ready join`
  - `release`
  - `late join`
- 这套容器只存在于 shadow/runtime 证据面：
  - 不接管主服务逻辑
  - 不改 `retire contract`
  - 不接入主 `summary` / `mainexp`
- `WMS` 已经把 lane 级 seam 统计收敛到：
  - `seam_owner_form_total`
  - `seam_joiner_hit_total`
  - `seam_joiner_useful_total`
  - `seam_owner_live_join_total`
  - `seam_owner_ready_join_total`
  - `seam_ready_transition_total`
  - `seam_ready_fanout_total`
  - `seam_ready_fanout_consumers_sum`
  - `seam_late_join_total`
  - `seam_potential_private_service_elide_total`

这意味着我们现在追踪的已经不是“某两个 metadata 有没有重叠”，而是：

- 一个真实 service object 在 `PE` 内的生命周期里，究竟有多少 join 发生在 `ready` 之前，多少 join 发生在 `ready` 之后，多少 join 已经晚到无法带来真实 service 消除。

### 16.2 已经拿到的真实 runtime 证据

截至 `2026-03-24`，`rowdescriptor` 已经成为第一条拿到真实 `WMS` runtime lifecycle 证据的 lane：

- `owner form`：真实 `rowdescriptor` service-object 创建
- `live join`：第一个 joiner 在 object ready 前加入
- `ready join`：后续 joiner 在 object ready 后、release 前加入
- `late join`：更晚的 joiner 在 release 后加入，只能命中 overlap，不能消除当前 service
- `release`：真实 replay drain 路径会触发 shadow `release`

这点很关键，因为它说明：

- `PULSE` 当前已经从“推测哪里可能有共享”前进到“证明真实 runtime 中哪一段生命周期存在共享机会”。

更重要的是，我们已经观察到一个非常硬的区分：

- `late join` 仍会点亮旧的 `seam_joiner_useful_total`
- 但新的 `seam_potential_private_service_elide_total` 会保持为 `0`

这正式证明：

- 旧的 `useful overlap` 统计会把“已经错过服务窗口的晚到 join”也算进来；
- 新的 `service-object lifecycle evidence` 更接近真实可消除的 private service 工作量。

同时，`ready` 这一步已经不再只是 service-table 内部状态变化：

- `notePeInternalPodServiceObjectReady_()` 现在会把 `ready transition / ready fanout / fanout consumer sum` 真实投影到 `rowdescriptor` lane 对齐视图；
- 同时也会向 `PeSharedCoreFabric` 发出真实 `ReadyFanout` control message。

### 16.3 为什么 `rowdescriptor` 成为下一条 actual optimization 主线

当前三条 lane 中，`rowdescriptor` 是最稳的第一实现对象，不是因为它名字更高级，而是因为它已经具备三项别的 lane 还没有同时具备的条件：

1. 它已经拿到真实 runtime 中的 `live / ready / late` 生命周期证据。  
2. 它比单纯 `idx2 / rowindex` 更接近真实的 replay / descriptor formation / service work。  
3. 它允许我们在**不先改 retire、也不先改主 memory path**的前提下，先尝试消除 `ready join` 路径上的重复 replay 和重复 descriptor formation。  

这使得 `rowdescriptor` 很适合作为第一条 actual optimization lane：

- 风险边界清楚；
- 隔离性强；
- 直接对应真实服务工作量，而不是抽象重叠率。

### 16.4 当前已经落地的第一条 isolated actual optimization

截至 `2026-03-24`，第一条 actual optimization 已经不是纸面计划，而是一个默认关闭的隔离开关：

- `experimental_rowdescriptor_ready_join_dedup_enable`

它的边界刻意收得很窄：

- 只作用在 `rowdescriptor` lane；
- 只作用在 `joined_ready` 这条 joiner 路径；
- 只跳过本地重复的 `descriptor-planner / registry` 工作；
- 不改 owner，不改 retire，不改主 memory owner，不改主 summary。

换句话说，它当前做的不是“整个 shared service 重写”，而是：

- **当 object 已经 ready 时，后续 joiner 不再重复参与本地 rowdescriptor replay/planner 形成。**

这是一个很好的第一刀，因为它满足三件事：

1. 行为隔离，默认关闭；  
2. 与 `rowdescriptor` 的 lifecycle evidence 直接对齐；  
3. 已经可以通过 `descriptor_elide / lines_elide` 这类 runtime 统计被真实观测。  

### 16.5 当前仍然没有做的事

为了避免文档叙事跑得比代码快，当前必须明确四个“还没有”：

- 还没有把 `shadow service-object` 变成 actual service owner
- 还没有在端到端 workload 上证明 `memory_requests` 或 `memctrl.req_total` 已经下降
- 还没有进入 `domain-local exact retire` 的真实行为改动阶段
- 还没有把 `ready-join dedup` 从“局部 descriptor-planner shortcut”扩展成更大的 shared-service / replay elimination

所以，`v5` 的正确表述不是：

- “PULSE 已经打出收益”

而是：

- “PULSE 已经在 `rowdescriptor` lane 上拿到了足够硬的 lifecycle-aware runtime evidence，并且已经完成第一条隔离的 actual optimization 落地，但还没有进入端到端收益证明阶段。”

---

## 17. 最小落地路径

### Phase A：`shared ingress actual v1` 基线诊断（已完成）

目的：

- 把“真实经过 shared path”与“只经过 pulse 记账”分开
- 为后续 descriptor-first 提供可比基线

至少新增：

- `pulse_ingress_shared_buffered_total`
- `pulse_ingress_direct_bypass_total`
- `pulse_ingress_singleton_bypass_total`
- `pulse_ingress_deadline_bypass_total`
- `pulse_ingress_pressure_bypass_total`

现状：

- 这一阶段已经完成，并且已经给出清晰结论：
  - `shared ingress` 本身不会直接进入收益空间
  - 继续调 watermark / ingress policy 不再是主线优先级

### Phase B0：shadow service-object skeleton（已完成）

目的：

- 先把 `PE` 内共享机会从“抽象 overlap”变成“可追踪的 service object lifecycle”
- 严格保持 shadow-only，不改主行为

成功条件：

- owner/join/ready/release/late 的生命周期可以独立追踪
- lane 级 seam 统计能区分 `live join` 和 `late join`

### Phase B1：`rowdescriptor` runtime ready/release bridge（已完成）

目的：

- 把 shadow service-object 接到真实 `WMS rowdescriptor` 路径
- 证明 `ready join` 与 `late join` 来自真实 runtime，而不是测试替身语义

成功条件：

- `rowdescriptor` lane 在真实 `WMS` flow 中观察到：
  - `owner_live_join`
  - `owner_ready_join`
  - `late_join`
  - `release`

### Phase B2：`ReadyFanout` shadow evidence（已完成）

目的：

- 继续把证据面从 `service object ready` 推进到 `ready fanout`
- 明确 `ready join` 到底能否减少重复 replay/descriptor formation，而不只是减少逻辑等待

优先新增：

- `ready_transition_total`
- `ready_fanout_total`
- `ready_fanout_consumer_sum`
- `ready_fanout_late_consumer_total`

完成状态：

- `rowdescriptor` lane 已经能观察：
  - `ready_transition_total`
  - `ready_fanout_total`
  - `ready_fanout_consumers_sum`
  - `owner_ready_join_total`
  - `late_join_total`
- `PeSharedCoreFabric` 也已经能真实收到 `ReadyFanout` control message。

### Phase C：第一条 actual optimization：`rowdescriptor ready-join` 去重（初版已完成，隔离开关）

目的：

- 不改 retire contract
- 不改主 memory owner
- 仅在 `rowdescriptor ready-join` 路径上消除：
  - 重复 replay
  - 重复 descriptor formation

当前已完成：

- 已经落地一条默认关闭的初版 shortcut：
  - 当 `rowdescriptor` object 已经 `ready` 时，后续 joiner 会跳过本地重复的 replay/planner 形成
- 已有 runtime 统计：
  - `rowdescriptor_ready_join_descriptor_elide_total`
  - `rowdescriptor_ready_join_lines_elide_total`

当前还没完成：

- 还没有把这条 shortcut 证明为端到端收益
- 还没有扩展到更强的 replay elimination / shared-service ownership

### Phase D：扩展到 descriptor/service plane 的更大共享面

目的：

- 仅在 `rowdescriptor` 实证成立后，再评估是否扩展到：
  - `idx2`
  - `rowindex`
  - 更完整的 shared descriptor service / region residency

### Phase E：shadow `domain-local exact retire`

目的：

- 在不改 architectural 行为前提下，重新测量：
  - 如果按 domain retire，会释放多少 HOL

### Phase F：actual `domain-local exact retire`

目的：

- 真正释放 cross-post HOL
- 维持 same-post deterministic / exactly-once / drain-before-scatter

---

## 18. 这版设计最重要的判断

`v4` 最重要的判断有四条：

1. **shared ingress 单独成线不会显著赢，因为它没有减少真实 service 工作量。**
2. **当前主瓶颈是 cross-post HOL，因此必须把 exactness 从 PE-wide total order 收紧为 domain-local exact retire。**
3. **当前 `PE` 内优化线已经不再只是 `metadata overlap` 探测，而是进入了 `service-object lifecycle evidence` 阶段。**
4. **下一阶段不应该回头继续调 ingress，也不应该并行推进三条 lane；应聚焦 `rowdescriptor + ReadyFanout`，然后只在这一条 lane 上做第一条 actual optimization。**

所以，`PULSE` 从现在开始不应再被定义成：

- “PE 内 shared ingress”

而应被定义成：

- **`descriptor-first PE-shared service plane + domain-local exact commit plane`**

同时，在真实代码推进顺序上，它应该先表现为：

- **`rowdescriptor lifecycle-aware shadow evidence -> ReadyFanout evidence -> ready-join dedup actual optimization -> broader descriptor/shared-service expansion -> domain-local retire reform`**

这版才是浮浮酱认为既最 solid、又最符合当前代码与实验现状的一版。

## References

- Tianjic. *Nature* 2019. https://www.nature.com/articles/s41586-019-1424-8
- Loihi 2. arXiv 2021. https://arxiv.org/abs/2103.12393
- Darwin3. *National Science Review* 2024. https://pmc.ncbi.nlm.nih.gov/articles/PMC10704147/
- SpiNNaker2 overview. https://spinnakercsmanchester.github.io/spinnaker2/user_guide/snn-intro.html
- ActiveN. UCLA CRAFT Lab page. https://craft.cs.ucla.edu/activen-a-hardware-accelerated-active-message-framework-for-general-purpose-many-core-neuromorphic-systems/

## 19. 2026-03-25 runtime closure update

这轮代码与实验把 `Phase C` 的真实边界进一步钉住了：

- `rowdescriptor ready-join dedup` 已经完成参数链、运行时开关和 PE 级统计接线：
  - `experimental_rowdescriptor_ready_join_dedup_enable`
  - `pulse_rowdescriptor_ready_join_descriptor_elide_total`
  - `pulse_rowdescriptor_ready_join_lines_elide_total`
- 特性仍保持严格隔离：
  - 默认关闭
  - 仅通过 mesh/runtime env 显式打开
  - 不改 retire contract，不改 owner 基本归属

### 19.1 safe baseline A/B 现状

为避开旧的 `gather-preband` 崩溃，本轮先切到更安全的 workload：

- `descriptor_actual_enable = 1`
- `mfb_gather_preband_enable = 0`
- 对比 `manual_shared_line_baseline_dedup_off/on`

`dedup_off` 已成功闭环：

- run:
  - `/home/xgy/remote/mainexp/experiments/2026-03-24_pulse_rowdescriptor_ready_join_dedup_ab_v1/runs/manual_shared_line_baseline_dedup_off/20260324-204228`
- validation:
  - `fail=0 warn=0 strict=0`
- 关键统计：
  - `pulse_shared_service_hits_total = 612972`
  - `pulse_shared_service_misses_total = 150907`
  - `pulse_ready_fanout_total = 763879`
  - `pulse_actual_gate_taken_total = 763879`
  - `pulse_rowdescriptor_ready_join_descriptor_elide_total = 0`
  - `pulse_rowdescriptor_ready_join_lines_elide_total = 0`
  - `memory.memory_requests = 150907`

这个结果说明：

- 在真实 `actual shared-line` workload 下，`ready fanout` 和 `shared service` 已经大量存在
- 但当前 shortcut 关闭时，`rowdescriptor ready-join dedup` 计数为零，说明 baseline 本身不会天然触发这条 shortcut

### 19.2 当前 blocker：不是 crash，而是 dedup_on 挂起

`dedup_on` 对应安全 workload：

- run:
  - `/home/xgy/remote/mainexp/experiments/2026-03-24_pulse_rowdescriptor_ready_join_dedup_ab_v1/runs/manual_shared_line_baseline_dedup_on/20260324-204841`
- effective config:
  - `pulse.descriptor_actual_enable = 1`
  - `pulse.mfb_gather_preband_enable = 0`
  - `pulse.experimental_rowdescriptor_ready_join_dedup_enable = 1`

但该 run 没有正常收尾：

- 只生成了：
  - `effective_config.json`
  - `mesh_run.log`
  - `mesh_stats.csv`
  - `time.txt`
- 没有生成：
  - `validation.log`
  - `essential_summary_mesh.json`

从 `mesh_run.log` 可见：

- 已进入 `BeginApply`
- 随后持续出现：
  - `progressed=20`
  - `done=0`
  - `ba=20`
  - `ea=0`
  - `es=0`
  - `noc_idle=1`
  - `extq=0`

这说明当前问题不是 front-end 注入，也不是 NoC/backpressure，而是：

- `ready-join dedup` 打开后，某条 `BeginApply -> EndApply / release / retire-ready` 的收敛链被破坏
- 系统进入 `all cores stuck in BeginApply while fabric already idle` 的状态

### 19.3 与 gather-preband blocker 的关系

需要明确分开两类问题：

1. `gather-preband` 旧 blocker：
   - 早先 `pulse_shared_line_actual_mfb_gather_preband_dedup_off` 就会在
     - `PulseGatherPrebandCollector::clear()`
     - `SnnWorkload::enterBeginGather_()`
   - 触发 `free(): invalid pointer`
2. `ready-join dedup` 新 blocker：
   - 在已经关闭 `gather-preband` 的安全 workload 下仍会发生
   - 表现为 step drain 挂起，而不是崩溃

所以，当前不能把 `dedup_on` 回退错误归因到 `gather-preband`。

### 19.4 这轮实验带来的设计修正

当前最重要的修正判断是：

1. `ready-join dedup` 已经不是“有没有 overlap”的问题，而是“join shortcut 是否破坏 apply/release/exactness 收敛”的问题。
2. 下一阶段不应继续追求更大共享面，而应先把 `rowdescriptor` 的 lifecycle contract 补齐到足以解释这次挂起。
3. 调试优先级应从 `service hit` 转向：
   - `ready -> apply -> release`
   - `owner / joiner / late join`
   - `per-core done visibility`

### 19.5 下一步执行顺序

下一步应严格按下面顺序推进：

1. 给 `rowdescriptor ready-join dedup` 增加更细的生命周期统计：
   - `ready_join_shortcut_taken`
   - `ready_join_shortcut_blocked_not_ready`
   - `ready_join_shortcut_blocked_live_owner`
   - `ready_join_shortcut_release_wait`
   - `ready_join_shortcut_apply_complete`
2. 在 `BeginApply / EndApply / release / retire-ready` 之间补 joiner 侧追踪，确认是哪一段没有闭环。
3. 先让 `manual_shared_line_baseline_dedup_on` 能正常收尾，再谈 A/B 收益与更大共享面扩展。

结论：

- `Phase C` 的“开关、统计、实验入口”已经具备
- 但真正缺的不是更多优化点，而是 `ready-join shortcut` 的 correctness/liveness contract
- 只有先修通这条 contract，`PULSE` 才能从“结构上像优化”进入“真实收益空间”

## 20. 2026-03-25 safe-baseline rerun correction

在补完 `shortcut lifecycle` 统计后，重新跑了修正后的 safe baseline A/B：

- `manual_shared_line_baseline_dedup_off`
  - `/home/xgy/remote/mainexp/experiments/2026-03-24_pulse_rowdescriptor_ready_join_dedup_ab_v1/runs/manual_shared_line_baseline_dedup_off/20260325-094550`
- `manual_shared_line_baseline_dedup_on`
  - `/home/xgy/remote/mainexp/experiments/2026-03-24_pulse_rowdescriptor_ready_join_dedup_ab_v1/runs/manual_shared_line_baseline_dedup_on/20260325-095149`

两边都完整收尾，且 `validation` 全通过：

- `fail=0 warn=0 strict=0`

更关键的是，`off/on` 完全一致：

- `memory.memory_requests = 150907`
- `pulse_shared_service_hits_total = 612972`
- `pulse_ready_fanout_total = 763879`
- `pulse_rowdescriptor_ready_join_descriptor_elide_total = 0`
- `pulse_rowdescriptor_ready_join_lines_elide_total = 0`

新增的 lifecycle 统计也全部为 `0`：

- `pulse_rowdescriptor_ready_join_shortcut_candidates_total = 0`
- `pulse_rowdescriptor_ready_join_shortcut_taken_total = 0`
- `pulse_rowdescriptor_ready_join_shortcut_blocked_not_ready_total = 0`
- `pulse_rowdescriptor_ready_join_shortcut_release_deferred_total = 0`

这说明一件非常关键的事：

- 在当前 safe baseline 中，因为 `pulse.mfb_gather_preband_enable = 0`，`rowdescriptor ready-join shortcut` 根本没有进入路径。

因此，之前基于旧 run `20260324-204841` 对 `dedup_on` 的“稳定挂起”解读，需要降级为：

- **那是一个未完成 run，不能再作为“safe baseline 下 dedup flag 造成 liveness 回退”的证据。**

### 20.1 这轮修正后的真实判断

现在更准确的判断应该是：

1. 当前 `Phase C` 代码与隔离开关是通的。
2. 当前 safe baseline workload 并不会触发 `rowdescriptor ready-join shortcut`。
3. 所以 safe baseline A/B 不能用来评估这条优化本身，只能用来验证：
   - 开关默认隔离正确
   - 打开 flag 不会在非命中路径上引入额外开销或回退

### 20.2 下一阶段真正该做什么

下一阶段不应继续在 `gather-preband=0` 的 workload 上期待 `ready-join dedup` 出现收益，而应二选一：

1. 修复 `gather-preband` 旧 blocker，让 `rowdescriptor` preband lane 重新可运行。
2. 把 `ready-join shortcut` 从当前 `gather-preband replay` 的窄入口，扩展到更普遍的 `rowdescriptor` descriptor/replay formation 点。

如果不做这两件事之一，那么：

- 统计永远是 `0`
- A/B 永远等价
- 我们测到的只是“特性隔离正确”，而不是“优化发生了”

## 21. 2026-03-25 N1/N2/N3 closure update

这一轮把之前规划的三个任务收口了一版：

### 21.1 N1: Trigger-Surface Mapping 结论

代码事实已经更明确：

1. `RowDescriptor` 当前在真实 runtime 中并不存在一个“比 gather-preband 更广、而且已经活跃”的公共 formation 面。
2. `Idx2Row` / `RowIndex` 的确有更普遍的 `observePeInternalPodMetadataObject_()` 入口，但 `RowDescriptor` 仍主要挂在：
   - `preparePulseGatherPrebandReplay_()`
   - `notePeInternalPodServiceObjectReady_(RowDescriptor, ...)`
   - `drainPendingPulseGatherPrebandReplay_()` / `notePeInternalPodServiceObjectReleased_(RowDescriptor, ...)`
3. 因而先前“把 shortcut 迁到更通用 rowdescriptor 活跃面”的更准确表述应改成：
   - 先把 **现有 rowdescriptor gather-preband runtime path** 内的重复逻辑收敛成公共 helper；
   - 再通过实验确认真正的 runtime blocker 是 workload/窗口激活条件，而不是 helper 没接通。

这点很关键，因为它直接解释了为什么 safe baseline 与 `1us alt-stop smoke` 都会继续给出全零：

- safe baseline：`pulse_mfb_gather_preband_enable = 0`
- alt-stop smoke：窗口未真正完成，`ready_fanout / join_ready` 根本还没发生

### 21.2 N2: Generic Rowdescriptor Shortcut Placement 落地

本轮已经把 `rowdescriptor ready-join shortcut` 收敛成公共 helper：

- `WeightMemorySubsystem.h`
  - 新增 `maybeTakeRowdescriptorReadyJoinShortcut_(band_id, selected_line_count)`
  - barrier / non-barrier 两条 gather-preband 分支统一调用这一 helper

这样做的直接收益不是“性能立刻变强”，而是：

1. 消除了 barrier / non-barrier 两处重复判断逻辑，避免后续 probe 与行为再次分叉。
2. 让 `RowDescriptor` 的 shortcut 语义在两条 runtime path 上一致：
   - 先 `observe RowDescriptor`
   - 再判断是否已经 `join_ready`
   - 命中则本地直接跳过 replay enqueue
   - 未命中则继续原先 candidate/barrier/replay 流程

### 21.3 N3: Correctness/Liveness Closure

新增了三条 lifecycle probe，并一路接到 PE 统计和 snapshot：

- `pulse_rowdescriptor_ready_join_shortcut_apply_complete_total`
- `pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total`
- `pulse_rowdescriptor_ready_join_shortcut_release_missing_total`

语义约束如下：

1. `apply_complete_total`
   - joiner 命中 shortcut 后，本地 band 直接完成 apply-side 收尾，不再进入 replay pending 队列。
2. `release_forwarded_total`
   - joiner 命中 shortcut 后，release 责任被显式视为前递给 owner/finalizer 路径。
3. `release_missing_total`
   - 只有在 `RowDescriptor` release 阶段找不到活动对象时才累计，用来卡 `service plane` 与 release contract 的脱节。

对应单测也补到了两类真实 seam：

- 非 barrier ready-join shortcut
- barrier 已完成之后的“后到 joiner” shortcut

这两条 seam 现在都能通过，说明：

- shortcut 本身的 correctness/liveness contract 已经比上一版实得多
- barrier path 不能把“触发 finalization 的 core”误当成 ready-join 命中者，这个时序边界也已经被测试锁住

### 21.4 2026-03-25 runtime 新结论

本轮还补了一组 `mainexp` runtime 探测，结论分成两层：

1. `active smoke (alt-stop 1us)` 已经确认：
   - `off/on` 都能稳定产出 summary
   - `validation fail=2` 仅来自 `paper` profile 对 `step-limited` 的要求，不是 correctness/liveness 崩坏
   - 但 `pulse_shared_service_hits_total = 0`
   - `pulse_ready_fanout_total = 0`
   - 全部 `rowdescriptor ready-join` probe 仍为 `0`
2. 这说明：
   - `alt-stop 1us` 太早，窗口还没走到 `ready/join_ready`，所以不适合作为此优化的收益验证入口
3. 另一方面，`step-limited mini case`（把 `activation_fraction` 和 gather budget 下压）在很短时间内依然没有产出 summary，说明当前真正的 runtime blocker 已不只是“入口是否接通”，而是：
   - gather-preband active path 的 walltime / startup cost 依然过高
   - 我们需要单独把“何时真正进入 ready-fanout 区间”做成更轻量的 runtime 探针

### 21.5 下一阶段更准确的方向

现在比之前更清楚的下一步应是：

1. 不再把 `alt-stop smoke` 当作收益验证 case，只把它当作“代码不炸、summary 可写”的 smoke。
2. 新增更早期的 runtime 计数，直接回答：
   - `gather-preband candidate` 有没有形成？
   - `registerGatherBarrierArrival / registerGatherBandCandidate` 有没有真正进入 `replay_bands`
   - `notePeInternalPodServiceObjectReady_(RowDescriptor, ...)` 在大仿真里到底有没有发生
3. 若这些仍长期为零，就该把重点转到：
   - `RowDescriptor` 之外更早的 `idx2 / rowidx / pre-band` metadata 面
   - 或者重新设计一个不依赖 gather-preband finalization 的更早共享入口

换句话说，这轮最大的收获不是“已经进入收益空间”，而是：

- 我们已经把 `rowdescriptor ready-join shortcut` 的实现与 contract 收干净了；
- 现在 runtime 没收益，更多是 **触发面/窗口完成条件** 的问题，而不是 shortcut 自身逻辑还不成立。

### 21.6 2026-03-30 metadata frontier A/B 新结论

本轮把 `OSA metadata transaction` 的 probe 从 `rowdescriptor` 向更早四层 metadata frontier 展开，并在下面这组 `mainexp` fresh runtime 上完成了闭环：

- `mainexp/experiments/2026-03-30_pulse_osa_metadata_txn_ab_v1`
- baseline：
  - `runs/pulse_shared_line_actual_mfb_gather_preband_metadata_txn_off/20260330-123813`
- `rowdescriptor ttl256`：
  - `runs/pulse_shared_line_actual_mfb_gather_preband_metadata_txn_rowdescriptor_ttl256/20260330-135055`
- `rowidx ttl256`：
  - `runs/pulse_shared_line_actual_mfb_gather_preband_metadata_txn_rowidx_ttl256/20260330-153849`
- `idx2 ttl256`：
  - `runs/pulse_shared_line_actual_mfb_gather_preband_metadata_txn_idx2_ttl256/20260330-155034`
- `preband ttl256`：
  - `runs/pulse_shared_line_actual_mfb_gather_preband_metadata_txn_preband_ttl256/20260330-155808`
- `all ttl256`：
  - `runs/pulse_shared_line_actual_mfb_gather_preband_metadata_txn_all_ttl256/20260330-160433`

这组 fresh run 的共同点很干净：

- 全部 `validation fail=0 warn=0 strict=0`
- `model.sim_time_actual_ns = 224,963`
- `memory.memory_requests = 150,907`
- `memhierarchy.memctrl.req_total = 150,907`

也就是说，这轮 A/B 的结论可以不受 correctness / runtime 崩坏干扰，直接看 seam 是否活着。

核心结果如下：

1. `rowdescriptor ttl256` 仍然是唯一活跃的 transaction seam：
   - `pulse_metadata_txn_export_total = 1,584`
   - `pulse_metadata_txn_owner_launch_total = 431`
   - `pulse_metadata_txn_join_live_total = 189`
   - `pulse_metadata_txn_join_ready_total = 964`
2. `rowidx / idx2 / preband` 三个 case 全部为零：
   - `pulse_metadata_txn_export_total = 0`
   - `pulse_metadata_frontier_observed_total = 0`
   - 对应 `owner_form_candidate_total / join_ready_candidate_total = 0`
3. `all ttl256` 与 `rowdescriptor ttl256` 完全同构：
   - `all` 重新得到同样的 `1,584 / 431 / 189 / 964`
   - 但新增的四层 frontier probe 仍然全部为 `0`
4. 新加入的更早四层统计：
   - `premphf_base`
   - `premphf_band`
   - `idx2row`
   - `rowindex`
   在 `all` case 下依然 `observed / reobserve / owner-form / join-ready` 全为 `0`

这说明我们现在可以把一个之前的猜想收得更硬：

- 问题不是“更早 metadata 被看到，但没有成功 join-ready”
- 而是 **当前 mainline runtime 根本没有把这些更早 metadata 物化成可被 `pulse_metadata_txn` 消费的 lifecycle seam**

因此，这轮结果对 `PULSE-GDR` 主线的影响很明确：

1. `RowDescriptor` 仍然是当前代码里唯一真实活跃、且已经接到 `owner -> live join -> ready join` 的 shared service-object seam。
2. 继续在 `rowidx / idx2 / preband` 现有 mask 上调 `TTL / score / threshold` 不会进入收益空间，因为 runtime seam 本身还不存在。
3. 下一阶段如果要真正推进 “PE 内更早、更共享的 metadata service”，重点不应再放在 `mask` 选择，而应放在：
   - `WMS internal storage object model` 到 `PE local storage object model` 的 runtime 映射审计；
   - 找出 `PreMphfBase / PreMphfBand / Idx2Row / RowIndex` 第一次真实 materialize、共享、释放的位置；
   - 如果现有 runtime 中根本没有这个物化点，就必须显式设计新的 `metadata object harbor / table / ready fanout`，而不是期待现有 `rowdescriptor txn` 机制自然外推。

换句话说，这轮 A/B 不是失败，而是把“下一步到底该修什么”明确了：

- 不是继续调 `ready lease`
- 不是继续扫 `metadata mask`
- 而是要把 **更早 metadata seam 本身** 从架构假设变成 runtime 中真实存在的对象化路径
