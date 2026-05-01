# GAS Retire HOL 系统处理方案（双轨收口）

> 日期：2026-03-13  
> 状态：design-only  
> 作用：为当前主线 `DRAM-based SNN + GAS + GCSS-GLIDE + STORM + MulticastRouter` 中已经确认的 `retire HOL` 瓶颈，建立一套**不污染 frozen baseline、可解释、可验证、可演进**的系统处理框架。

---

## 0. 一句话结论

当前主线中的 `retire HOL`：

- 不是离线 summary 误报；
- 不是 `MultiCorePE / SnnPESubComponent` 这类外围工程 plumbing 偶发引起的假象；
- 也不是 `GAS` 抽象语义天然要求的必然瓶颈；

它是一个**当前主线真实存在的微结构瓶颈**，其根因是：

- 前端 `GCSS-GLIDE` 路径为了 locality，已经做了地址优先/line 优先的发射重排；
- 后端 `WeightMemorySubsystem` 为了严格确定性/历史兼容，又采用了更强的 `global in-order retire`；
- 两者组合后，形成了大量“后继 edge 已 ready，但被全局 head 卡住”的 `HOL closure`。

因此，本问题的正确处理方式，不是直接“把 retire 改掉”，而是先把：

1. `GAS` 必需语义；
2. 严格复现实验 contract；
3. 当前实现使用的 retire contract；

三者彻底拆开，再用**双轨收口 + 分层观测 + 归因实验 + 候选准入**的方式推进。

---

## 1. 当前现状与问题重述

### 1.1 当前主线口径

当前 frozen full-system baseline 的主线定义，应继续以：

- `DRAM-based SNN chip`
- `GAS`
- `GCSS-GLIDE`
- `STORM`
- `MulticastRouter`

为唯一根基，详见：

- `exp_opt/2026-03-06-system-mainline-dram-snn-gas-storm-gcss-glide.md`

本轮用于定位瓶颈的真实 run 为：

- `mainexp/experiments/2026-03-08_full_system_baseline_ab_v1/runs/full_system_baseline/20260313-111235`

该 run 的关键配置包括：

- `synapse_weight_mode = gcss_valueonly_dstcore_vlf_premphf_plp`
- `apply_issue_policy = order`
- `experimental_retire_policy = global_inorder`
- `num_cores_per_pe = 20`

### 1.2 当前已经确认的关键观测

来自 `essential_summary_mesh.json` 的关键事实：

- `sim_time_actual_ns = 257453`
- `memctrl.req_total = 150907`
- `gas.memctrl_payload_utilization = 0.3163699331`
- `critical_path.stage = retire_closure`
- `apply_issue_attempt_total = 150907`
- `apply_issue_success_total = 150907`
- `apply_issue_block_bank_credit_total = 0`
- `apply_issue_block_downstream_busy_total = 0`
- `retire_global_hol_cycles_total = 73832198`
- `retire_ready_but_blocked_edges_total = 100124332070`
- `retire_wait_cycles_due_to_hol_total = 73832198`
- `retire_wait_cycles_due_to_not_ready_total = 306010`
- `step_barrier_wait_ns_total = 3200`

这组数据已经足以说明：

- 当前不是“发不出去”；
- 不是 `bank-credit` 卡住；
- 不是 `downstream busy` 卡住；
- 也不是 `step barrier` 卡住；

而是：

- edge 已经大量发出并返回；
- 但 commit/closure 端被 `global in-order retire` 机制卡住；
- 从而在 `Apply` 后半段形成大规模 `HOL`。

### 1.3 当前问题的准确表述

本问题不应再被表述为：

- “为什么当前内存系统慢”
- “为什么 DRAM 没收益”
- “为什么 summary 看起来像 retire 卡住”

而应该被准确表述为：

- **在当前 `GCSS-GLIDE` 地址重排发射路径下，`global in-order retire` 是否比 `GAS` 最小语义要求更强，从而人为放大了 head-of-line closure？**

只有这样表述，后续的设计与实验才不会继续混淆：

- 抽象语义边界；
- 严格实验 contract；
- 当前实现策略；
- 统计口径。

---

## 2. 问题归因：三层 Contract

后续所有设计、实验、是否可合入主线，都必须围绕以下三层 contract 来判断。

### 2.1 Layer A：GAS 必需语义 Contract

这是最底层、绝对不能破坏的语义边界。

#### A1. edge 只能在 weight ready 后 commit

不能在 weight 未返回时提交，否则会把错误值或空值写入 accumulator。

代码位置：

- `WeightMemorySubsystem.h` 中 `setEdgeRetireReady_()`
- `WeightMemorySubsystem.h` 中 `commitRetireEntry_()`

#### A2. Scatter 前必须完成本轮 Apply 的全部 edge 提交

当前 `SnnWorkload::shouldDeferScatterCommit_()` 已明确要求：

- 只要 memory pending 未清零；
- 或 `WeightMemorySubsystem::hasDeferredWork()` 仍为 true；

就不能进入最终 Scatter commit。

这条是当前 `GAS window` 正确性的核心约束之一。

代码位置：

- `services/workload/snn/SnnWorkload.cc`

#### A3. Apply 阶段不允许出现跨 post 的可观察副作用

当前 `acc_update(post, dv)` 的效果仅限于：

- 把该 `post_local` 的 `dv` 累加到局部 accumulator；
- 并不会在 Apply 阶段直接触发发放、early-exit、跨 post 副作用。

真正把 `dv` 应用到神经元状态、进行 `endCycle/drainOutputs` 的动作，是在 Scatter commit。

代码位置：

- `services/synapse/gas/AccumulatorOps.cc`
- `services/workload/snn/SnnWorkload.cc`
- `control/SnnPEApplyScatter.cc`

#### A4. 每条 edge 必须 exactly-once 生效

不能漏退役，也不能重复退役。这是所有 retire 设计的底线。

---

### 2.2 Layer B：严格复现实验 Contract

这层不是 `GAS` 抽象本体，但服务于当前“严格验证 / 严格复测 / strict semseal”的实验要求。

#### B1. 同一个 `post_local` 上的 float 累加顺序必须确定

由于 float 加法不结合，如果同一 `post` 上多条 edge 的 commit 顺序改变，位级结果可能改变，并在阈值边界场景放大为：

- 发放/不发放差异；
- 时序差异；
- 最终统计差异。

因此，在 strict 口径下：

- `same-post` 内的提交顺序必须确定。

#### B2. edge 枚举顺序必须稳定

当前 `GasEdgeCollector::flipForApply()` 已把 `curr` 拷贝到 `prev` 后显式排序，以保证多线程/MPI 环境下遍历顺序稳定。

代码位置：

- `services/synapse/gas/GasEdgeCollector.cc`

#### B3. 结论

严格实验口径真正需要守住的，不是“全局 edge 总序”，而更像是：

- `same-post deterministic`
- `stable edge enumeration`
- `drain-before-scatter`

也就是说：

- **严格复现需要的是局部顺序确定性；**
- **并不自动推出必须使用全局总序 retire。**

---

### 2.3 Layer C：当前实现 Contract

这是当前 run 中真正产生大 `HOL` 的实现策略。

#### C1. 每条 edge 注册一个全局 `retire_seq`

当前 `WeightMemorySubsystem` 为每条 edge 建立统一的 `edge_retire_` 队列，并分配全局 `seq`。

#### C2. 回包只标 ready，不立即 commit

当前回调到达后，只会：

- `setEdgeRetireReady_(seq, ...)`

而不是立即执行 `acc_update`。

#### C3. 默认 policy 为 `global_inorder`

当前默认策略明确是：

- `RetirePolicy::GlobalInOrder`

其设计初衷是：

- 避免 StandardMem 回调顺序抖动，破坏 float 累加顺序与历史行为。

#### C4. 提交必须从全局 head 连续前推

当前 `tryRetireEdges_()` 在 `global_inorder` 下只允许：

- 从 `next_retire_seq_` 开始；
- 连续提交 ready 条目；
- head 不 ready 时，后面的 ready edge 也不能 retire。

#### C5. 结论

因此，当前大 `HOL` 并不是 `GAS` 本体的抽象宿命，而是：

- **当前实现把“同一 post 的顺序确定”扩大成了“所有 post 共享一个全局总序”。**

---

## 3. 当前瓶颈的准确分类

### 3.1 它不是这些问题

当前 `retire HOL` 已可以排除以下几类解释：

1. **不是 summary 误报**
- 统计在 runtime 内部真实计数，离线脚本只是聚合。

2. **不是外围 step barrier 问题**
- `step_barrier_wait_ns_total = 3200ns`，远小于 `apply_ns_avg = 239096ns`。

3. **不是发射侧 bank-credit / downstream-busy**
- 当前 run 中两项都为 0。

4. **不是单一 PE/单一 core 的异常死锁**
- 16 个 PE 上 `HOL` 分布同量级，不符合单点工程异常模式。

### 3.2 它属于哪一类问题

当前 `retire HOL` 应被归类为：

- **当前微结构 contract 引入的真实瓶颈**

更准确地说：

- 它不是抽象语义假瓶颈；
- 不是统计虚假现象；
- 也不是纯实现 bug；
- 而是当前主线选择的 retire contract 与地址优先 issue contract 之间的结构性冲突。

### 3.3 当前冲突的本质

当前主线同时做了两件事：

1. 在 `GCSS-GLIDE` 路径中，通过地址/line 优先发射来提升 locality；
2. 在 retire 端维持 `global in-order` 提交。

这导致：

- “前端越努力让回包按 locality 友好返回”；
- “后端越容易因为全局 head 还没 ready 而堵住后继 ready edge”。

因此，当前 `HOL` 不应被视为局部 bug，而应视为：

- **当前主线 memory contract 的一阶矛盾。**

---

## 4. 系统处理总策略：双轨收口

本问题的处理必须采用“双轨收口”。

### 4.1 轨道 S：Strict Frozen Mainline

这条轨道保持当前主线完全不变，只负责：

1. 冻结 baseline contract；
2. 补齐最小可观测性；
3. 做归因，不做行为改变。

这条轨道禁止：

- 修改 `global_inorder` retire 语义；
- 修改 `apply_issue_policy=order`；
- 修改 `Scatter` 收口行为；
- 修改 strict validation 口径。

这条轨道的作用是：

- 作为论文/系统主线的稳定基线；
- 作为后续所有实验分支的唯一参照。

### 4.2 轨道 X：Experimental Retire Contract

这条轨道专门处理：

- 当前 `HOL` 中，哪些是不可避免的；
- 哪些是 `global retire` 策略放大的。

原则：

- 强隔离；
- 不污染 frozen baseline；
- 新机制只作为实验性 contract 候选；
- 只有通过四层验证后，才允许成为下一代主线候选。

### 4.3 双轨的价值

双轨策略能同时避免两个常见错误：

1. **为了优化而破坏主线可复现性**
2. **因为怕破坏主线，就永远无法回答当前 contract 是否过强**

---

## 5. 分阶段处理方案

### 5.1 P0：Contract Freeze

目标：

- 把当前问题从“现象讨论”升级为“contract 管理”。

产出：

1. 当前主线 contract 清单
2. `GAS semantic / strict reproducibility / current implementation` 三层边界表
3. 明确哪些变化属于：
- 禁止变更；
- 需要实验性验证；
- 可以作为实现重构。

P0 的验收标准：

- 后续任何讨论 retire 优化时，都必须先指出自己修改的是 A/B/C 哪一层；
- 不再允许把 `global_inorder` 误称为 `GAS 必需语义`。

### 5.2 P1：Observability Separation

目标：

- 把当前 `HOL` 拆成“不可避免部分”和“策略放大部分”。

建议新增统计项：

1. `retire_samepost_blocked_edges_total`
2. `retire_crosspost_blocked_edges_total`
3. `retire_head_post_local`
4. `retire_head_ready_late_resp_cycles_total`
5. `retire_policy_loss_cycles_total`
6. `retire_policy_loss_edges_total`

其中最关键的是：

- `crosspost blocked`

因为一旦它很大，就可以直接证明：

- 当前大 `HOL` 的主体不是 `same-post` 顺序必需，而是跨 post 被全局总序额外绑死。

### 5.3 P2：Attribution A/B

目标：

- 在不立刻修改主线行为的前提下，先回答“值得不值得做 retire contract 演进”。

建议三组对照：

1. `strict_baseline_global_retire`
2. `shadow_per_post_attribution`
3. `candidate_per_post_retire`

其中：

- `shadow_per_post_attribution` 不真正改变 commit，只在后台模拟“若按 per-post retire，会有多少 edge 能提前提交”

它的价值很大，因为它能在不碰 strict 结果的前提下先回答：

- 当前 `HOL` 中，有多少是真正可回收的？

### 5.4 P3：Candidate Promotion

只有当实验性 retire contract 同时满足以下条件，才允许进入下一代主线候选：

1. strict 验证不破；
2. 关键 SNN 结果不漂；
3. `HOL` 指标显著下降；
4. 端到端 `sim_time_actual_ns` 至少不回归；
5. 不引入新的解释困难或统计口径混乱。

---

## 6. 推荐的微结构治理方式

### 6.1 不建议继续在 `WeightMemorySubsystem` 中堆条件分支

当前 retire 逻辑、edge 队列、统计逻辑、实验分支都集中在 `WeightMemorySubsystem` 内，后续若继续直接堆条件分支，会带来：

- 语义与策略继续纠缠；
- 回归定位越来越困难；
- 失败实验路径更难彻底清理。

### 6.2 建议抽象出独立的 retire contract 层

推荐结构：

- `services/synapse/weights/retire/IRetireContract.h`
- `services/synapse/weights/retire/GlobalInOrderRetire.h`
- `services/synapse/weights/retire/PerPostDeterministicRetire.h`
- `services/synapse/weights/retire/RetireObservability.h`

由 `WeightMemorySubsystem` 只负责：

- edge 注册；
- ready 通知；
- Scatter 前 drain；
- 调用 retire contract 做 commit。

这样做的好处：

1. frozen baseline 的 `global_inorder` 可以完全保留；
2. experimental contract 可以强隔离；
3. observability 可以在不同 contract 上共用；
4. 失败候选更容易整体回退，不污染主线。

### 6.3 推荐的 contract 抽象接口

建议最小接口包括：

- `register_edge(post, pre, count, src) -> seq_or_token`
- `mark_ready(token, weight)`
- `try_commit()`
- `has_uncommitted_work()`
- `export_observability()`
- `reset_window(seq)`

这样可以把：

- 全局总序；
- 按 post 局部序；
- shadow 模拟；

都放在 contract 层实现，而不是继续把 policy 写死在 `WeightMemorySubsystem` 主体中。

---

## 7. 严格验证与闭环要求

后续所有围绕 retire contract 的设计，都必须通过四层验证。

### 7.1 L0：Structural Seal

检查：

- edge 注册数
- ready 数
- commit 数
- 未提交残留数
- Scatter 前 residual work 是否归零

### 7.2 L1：Numerical Seal

检查：

- 每个 `post_local` 的最终累计 `dv`
- touched-post 集合
- fired-neuron 集合

### 7.3 L2：Strict / SemSeal

检查：

- `validation.log`
- strict 结果是否一致
- 关键 SNN/GAS 汇总是否与基线同口径可对齐

### 7.4 L3：Performance Seal

检查：

- `retire_global_hol_cycles_total`
- `retire_crosspost_blocked_edges_total`
- `retire_policy_loss_cycles_total`
- `sim_time_actual_ns`
- `memctrl.req_total`
- `payload_utilization`

只有四层同时通过，candidate 才有继续推进价值。

---

## 8. 推荐的实验组织方式

### 8.1 目录建议

建议新增专门的 retire contract 实验目录，避免与普通 memory A/B 混杂：

- `mainexp/experiments/2026-03-xx_retire_contract_ab_v1/`

### 8.2 case 建议

至少包含：

1. `full_system_baseline_global_retire`
2. `shadow_per_post_attribution`
3. `per_post_retire_candidate`
4. `candidate_plus_same_stats`

其中：

- case 1 作为 frozen 主线参照；
- case 2 用于回答“可回收空间有多大”；
- case 3 用于验证实际微结构替换是否成立；
- case 4 用于确认收益不是统计误判。

### 8.3 当前阶段不建议的动作

在完成 P0/P1/P2 之前，不建议：

1. 直接把 `per_post retire` 合入主线；
2. 为了追求速度而放松 strict 验证；
3. 再引入新的 NoC 协同优化去掩盖 retire 问题；
4. 用端到端时间单指标替代归因实验。

---

## 9. 风险与注意事项

### 9.1 不能把“当前实现策略”误写成“GAS 语义”

这是当前最容易导致设计跑偏的地方。

错误写法：

- “GAS 必须 global in-order retire”

更准确的写法：

- “当前主线为了 strict determinism，采用了 global in-order retire”

### 9.2 多步统计存在重复记账风险

当前 retire counters 是 run-scope 累加，若后续做多 step 归因实验，需要注意：

- 每 step 落盘时是否在重复记 run total；
- 是否要改成 step-scope 增量落盘。

这对当前 `step=1` 不构成结论风险，但对后续多 step 设计必须显式处理。

### 9.3 不要把 shadow attribution 当成真实性能收益

`shadow_per_post_attribution` 的价值在于：

- 证明当前 `HOL` 中有哪些部分是策略可回收的；

但它不是最终性能结果，不能直接拿来替代真实 candidate A/B。

### 9.4 不要跳过 contract formalization 直接做实现

如果不先 formalize：

- 语义边界；
- 实验边界；
- 候选边界；

那么后续实现即使出现“看起来收益很好”，也很难判断：

- 到底是优化了策略；
- 还是偷偷改变了语义。

---

## 10. 最终建议与下一步

### 10.1 当前最合理的推进顺序

推荐顺序必须是：

1. `P0`：冻结 contract
2. `P1`：补齐 `same-post / cross-post` 归因统计
3. `P2`：先做 shadow attribution
4. `P3`：只有确认值得后，再实现实验性 retire contract

### 10.2 当前阶段的推荐判断

截至本设计文档完成时，推荐判断为：

- 当前 `retire HOL` 是主线真实瓶颈；
- 但其主体更可能来自当前 `global retire` contract 过强；
- 因此下一步最值得做的，不是再去追新的 memory/noC tweak，而是先把 retire contract 从语义层面治理清楚。

### 10.3 最终一句话

后续应统一以如下表述作为主线问题定义：

- **当前主线瓶颈不是“GAS 语义天然导致的 HOL”，而是“为满足 strict determinism，当前实现采用了 global in-order retire；在 GCSS-GLIDE 地址重排 issue 下，这个比最小语义更强的 contract 被系统性放大”。**

这句话将作为后续所有 retire 设计、实验和是否可合入主线的总前提。
