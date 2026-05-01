# 主线下一阶段：HOL 导向的 Offline Layout / Weight Placement 设计

> 日期：2026-03-16  
> 状态：design-only  
> 作用：在当前主线 `DRAM-based SNN + GAS + GCSS-GLIDE + STORM + MulticastRouter` 中，针对已经确认的前端 `HOL` / `queue burial` 问题，提出一条**不修改 runtime 主闭环、不再增加 online reorder 复杂度**的下一阶段主线方案。

---

## 0. 一句话结论

当前主线已经证明：

- baseline runtime 是稳定可闭环的；
- `HOL` 的主损失来自前端排序几何，而不是 completion/loader/残留工作；
- 继续在 runtime 侧叠加 online reorder，已经出现破坏 closure 的风险。

因此，下一阶段的主推荐不应再是新的 online queue 策略，而应转向：

- **在完全保持 runtime `locality_first + global_inorder` 不变的前提下，重做 GCSS values 的 offline layout / weight placement，使当前 baseline 自身拥有更好的公平性。**

这条路线的核心不是“换一个调度器”，而是：

- **让物理地址顺序更接近 retire/age 顺序；**
- **同时继续保住 `GCSS-GLIDE` 的 cacheline/DRAM locality。**

---

## 1. 背景与问题重述

### 1.1 当前主线的真实状态

当前 frozen mainline 的 memory side 事实已经比较清楚：

- `GAS` 是 memory backbone；
- `GCSS-GLIDE` 的目标是“在不破坏 runtime DRAM behavior 的前提下压缩 metadata，并维持 values/cacheline locality”；
- 当前稳定口径的 values artifact 是：
  - `physical_order_mode=profile_greedy`
  - `index_version=7`
  - `format=gcss_valueonly_dstcore_vlf_premphf_plp_v7_lpbl`

这意味着当前主线天然偏向：

- **先保 locality；**
- 再让 runtime 沿地址顺序去吃这批 values。

### 1.2 当前已经确认的问题不是“发不出去”

正式 MPI32 baseline 已经给出很强的证据：

- `materialization_ratio = 1.0`
- `retire_drain_ratio = 1.0`
- `residual_work_windows_total = 0`
- `begin_apply_loader_not_ready_windows_total = 0`
- `global_steps_done = 2`
- `windows_done = 32`
- `windows_incomplete = 0`

也就是说，当前 baseline 并没有出现：

- loader 没准备好；
- materialization 失败；
- outstanding carry-over 失控；
- Scatter 前 drain 不干净；
- step 结束不了。

因此当前主问题不能再表述为“主线实现坏了”，而应表述为：

- **主线实现是稳定的，但它把一种偏 locality 的离线布局，叠加到 `locality_first issue + global_inorder retire` 这组强顺序契约上，最终在前端产生了严重的 younger-ahead burial。**

### 1.3 当前瓶颈的最强证据

正式 baseline 的关键指标已经把问题指向前端几何：

- `queue_shape.edges_per_prepare_avg = 2432.20`
- `queue_shape.line_groups_per_prepare_avg = 620.64`
- `queue_shape.edges_per_line_group_avg = 3.92`
- `younger_ahead_depth.depth_avg = 575.63`
- `younger_ahead_depth.depth_max = 2532`
- `older_head_wait.wait_cycles_avg = 61101.32`
- `older_head_wait.wait_cycles_max = 296307`
- `gcss_queued_reason_mix.dominant_reason_by_hol_cycles = vlf_younger_ahead`
- `issue_gate.dominant_gate_by_hol_cycles = vlf_front_inflight_full`

这组数据的含义很明确：

1. queue 不是空的，而是很深；
2. line-group 很碎，平均每个 line-group 只承载不到 4 条 edge；
3. 老 head 经常被大量更年轻的 entry 埋在前面；
4. inflight full 只是伴随门控，不是根根本本的第一成因；
5. 真正的主损失是“老 edge 在地址优先 queue 中长期埋得太深”。

---

## 2. 为什么不应该继续沿 online reorder 往前走

### 2.1 不是因为 online reorder 没道理

从问题机理看，online reorder 并不是完全错误的方向。

恰恰相反：

- 既然 `vlf_younger_ahead` 是主因，
- 那么在 queue-build 或 issue-time 做一定公平性修正，
- 从逻辑上本来就是合理候选。

### 2.2 但它已经触碰了主线最敏感的闭环边界

问题在于，当前 runtime 不是普通的 loose scheduler，它和 step closure 深度耦合：

- `beginApplyWindow()` 会重建 `edge_retire_` 与 issue queue；
- `tryRetireEdges_()` 仍按 `global_inorder` 提交；
- `SnnWorkload::shouldDeferScatterCommit_()` 仍以 `pendingSize() + hasDeferredWork()` 为 Scatter 前 gate；
- `hasWork()` 也会把同样的 deferred work 当作 step 是否结束的一部分。

因此，一旦 online reorder 让 queue geometry 发生过强偏移，就不是“收益回归一点”这么简单，而是可能直接：

- 拉长 Apply；
- 推迟 Scatter；
- 让 `PE_DONE(drain)` 出不来；
- 最终把“可优化问题”升级成“主线不能结束”的 completion 风险。

### 2.3 形式 gate 已经给出结论

`P3-B banded_line_fair(band=256)` 的正式单点候选已经失败：

- seq1 进入 `BeginApply` 后长时间不进入 `BeginScatter`；
- 日志推进到 `cyc=540000` 时仍是 `ba=20 ea=0 bs=0 es=0`；
- candidate 被手动停止，没有形成完整 summary/validation。

因此，这条线当前不能再被当作主线优先方向。

正确的结论不是：

- “online reorder 永远不可能成立”；

而是：

- **在当前阶段、当前主线约束下，继续叠加 runtime reorder 的风险已经高于它的工程收益。**

---

## 3. 下一阶段方案应满足的目标

### 3.1 主目标

下一阶段的方案，必须同时满足以下三件事：

1. **不改 runtime 主闭环**
- 不修改 `prepareGcssVlfIssueQueue_()` 的 baseline 行为路径；
- 不修改 `popNextGcssVlfIssueEntry_()`；
- 不修改 `tryRetireEdges_()` 的 `global_inorder` 主契约；
- 不改变 `SnnWorkload::shouldDeferScatterCommit_()` / `hasWork()` 的现有闭环语义。

2. **直接压前端 burial**
- 降低 `younger_ahead_depth.avg / max`
- 降低 `older_head_wait.avg / max`
- 降低 `line_groups_per_prepare_avg`
- 提升 `edges_per_line_group_avg`

3. **不能把 locality 收益换没**
- 不能显著恶化 `memctrl_req_total`
- 不能显著恶化 `payload_utilization`
- 不能显著恶化 `traffic_amplification`
- 不能引入新的 row/bank 明显回归

### 3.2 非目标

这一阶段明确不做：

1. 不做新的 runtime issue-time rescue
2. 不做新的 retire contract 变更
3. 不做 `global_inorder -> per_post` 切换
4. 不做 `step gate` 行为逻辑重写
5. 不做为离线布局而修改核心 `snndl` 接口

也就是说，这不是一次 runtime 架构重构，而是一次：

- **围绕现有 runtime contract 反向设计 values 物理布局**。

---

## 4. 设计约束：哪些东西绝对不能破

下一阶段所有 offline 方案，都必须明确受以下约束：

### 4.1 语义约束

1. `(pre_global, post_local) -> weight` 映射必须完全不变
2. 不能引入 duplicate / missing edge
3. strict validation 必须继续 `fail=0 strict=0`

### 4.2 runtime 契约约束

1. 仍允许 baseline runtime 用 `locality_first`
2. 仍允许 baseline runtime 用 `global_inorder`
3. 仍要求 `BeginApply -> BeginScatter -> PE_DONE` 完整闭环
4. 不应新增 runtime 参数才能让新 artifact 成立

### 4.3 存储与格式约束

1. 优先复用当前 `gcss_valueonly_dstcore_vlf_premphf_plp_v7_lpbl` 家族
2. 若需要新增 manifest 字段，应尽量保持 loader/backward compatibility
3. 若某一离线排布需要新索引表达，应先证明：
   - values locality 收益仍在；
   - index cost 不明显高于当前主线；
   - runtime lookup 不变或只做极小兼容扩展

---

## 5. 设计空间与推荐路线

### 5.1 方案 A：纯 age-first offline layout

思路：

- 直接让物理地址顺序尽量接近 retire/age 顺序；
- 把“窗口里更老的 edge”尽量布得更靠前、更连续。

优点：

- 对 `younger_ahead_depth` 最直接；
- 解释简单。

缺点：

- 极容易破坏现有 `profile_greedy` 累积出的 locality；
- 可能把 `payload_utilization`、`memctrl_req_total` 一起打回去；
- 最终变成“减少 burial，但又重新制造 line 浪费”。

结论：

- **不推荐作为第一版主方案。**

### 5.2 方案 B：继续沿当前 `profile_greedy`，只做弱正则

思路：

- 保留 profile/co-access 目标；
- 只在 physical order 构造时加入轻量的 head-age regularization。

优点：

- 对现有 artifact/generator 侵入最小；
- 风险最低。

缺点：

- 可能太弱；
- 如果只做很轻的 pre-level 排序修正，未必足以明显压低 `depth_avg=575.63` 这一级别的 burial。

结论：

- **适合作为第一版最小实现。**

### 5.3 方案 C：line-block 级的 hybrid packing

思路：

- 不再只按 whole-pre 组织；
- 把 values 看成 line-block/chunk 级 placement 单元；
- 同时考虑 `co-access` 与 `head-age band`，做更细粒度的 line packing。

优点：

- 最有可能同时改善 `line_groups_per_prepare_avg` 与 `younger_ahead_depth`；
- 真正贴近当前问题的“line-group aware”本质；
- 仍是 offline，不碰 runtime 闭环。

缺点：

- 对 generator/index/manifest 的要求更高；
- 若需要新的 rank remap 或 block mapping，设计复杂度会上升。

结论：

- **这是中期主方向，但不应作为第一脚实现。**

### 5.4 推荐收敛

因此，推荐把下一阶段拆成两层：

1. **P3-C0（推荐先做）**
- `profile_greedy` 的 HOL-aware 正则版本
- 尽量只改 offline pre-order / placement scorer
- 不改 runtime，不强依赖新格式

2. **P3-C1（只有 C0 证明方向正确才进入）**
- line-block aware hybrid packing
- 如有必要，再设计更细的 rank/block remap 表达

---

## 6. 推荐方案：P3-C0 HOL-aware Profile-Guided Offline Layout

### 6.1 核心思想

当前 `profile_greedy` 的核心优点是：

- 能把运行时一起出现的 active pre 段压到更少的 cacheline 附近；
- 真实提升 `payload_bytes_per_memctrl_req_avg`；
- 且不改变 GAS 语义。

它的问题不是 locality 错了，而是：

- **它没有把 retire-age geometry 纳入目标函数。**

因此 `P3-C0` 的核心思想是：

- 继续保留 `profile_greedy` 的 locality 驱动力；
- 但在 offline placement 时，为“经常出现在老 head 区域的 edge / pre / line-chunk”增加更强的地址前置与冲突惩罚；
- 让当前 runtime 的 `locality_first` 排序天然更接近 retirement-friendly geometry。

### 6.2 输入数据

`P3-C0` 依赖两类输入：

1. **可信 baseline profiling**
- 只接受正式 baseline runtime 导出的 profile
- 不能使用 closure 已破坏的 candidate run

2. **现有 GCSS/PLP 元数据**
- `pre -> (base, len)`
- `pre_rank`
- 当前 physical layout / manifest

推荐新增一份 offline profiler 导出：

- 对每个窗口，记录参与 edge 的
  - `pre_global`
  - `post_local`
  - `pre_rank`
  - `retire_seq`
  - `local_age_rank`
  - `current_addr/line_id`（可选）

其目标不是替代 runtime summary，而是给 offline generator 一个足够细的训练样本。

### 6.3 placement 单元

`P3-C0` 的最小 placement 单元建议仍然以 **pre segment / pre block** 为主，而不是直接上 fully free-form line-chunk。

原因：

1. 更容易复用当前 generator 与 index family
2. 更容易保持 `pre_rank` 语义稳定
3. 更适合作为不碰 runtime 的第一版

但在评分时，不能只看 whole-pre，而应为每个 pre 计算：

- `touch_mass(pre)`：总体窗口活跃度
- `coaccess_mass(pre_i, pre_j)`：与其他 pre 的窗口共现强度
- `head_mass(pre)`：该 pre 的 edge 出现在窗口前 `K` 个 age slot 的频率
- `head_centroid(pre)`：这些 edge 的平均 age rank
- `head_span(pre)`：头部质量是否集中在很少几个 rank/窗口

其中最关键的是：

- **`head_mass` 不是看一个 pre 是否常出现，而是看它是否经常贡献“老 head 区域”的 edge。**

### 6.4 目标函数

第一版不追求求解器最优，而采用可解释的 greedy score。

对任意 placement 候选顺序，定义：

- `LocalityGain`
  - 估计相邻 pre/segment 在同窗共现时能共享 line 的潜力
- `HeadAlignmentGain`
  - 估计高 `head_mass` 的 pre 是否更容易被排到地址前部
- `BurialPenalty`
  - 估计老 head pre 被大批低 head_mass、但高 locality 的 pre 压在后面的风险
- `FragmentPenalty`
  - 估计布局后 line-group 继续碎裂的风险

总目标可以写成：

- `Score = a * LocalityGain + b * HeadAlignmentGain - c * BurialPenalty - d * FragmentPenalty`

其中：

- `a` 仍然是主权重，防止把 locality 收益打没；
- `b/c` 是这次新增的 HOL-aware 正则；
- `d` 用来抑制“局部看起来公平，整体 line-group 更碎”的坏解。

### 6.5 greedy 构造策略

推荐第一版构造如下：

1. 从 baseline profile 中抽取高频活跃 pre 集合
2. 对每个 pre 计算 `head_mass / head_centroid / coaccess sketch`
3. 先选一个“高活跃且高 head_mass”的 pre 作为起点
4. 每次从未放置集合中选一个下一个 pre，使：
   - 与当前尾部的 `coaccess_gain` 高；
   - 但不会显著拉低前半区的 `head_alignment`
5. 对明显属于“高 head_mass、低 coaccess”的 pre，不允许被无限推迟到地址后部
6. 对明显“极高 coaccess、但总是年轻”的 pre，允许后置，但不能大面积压住头部群

可以把这理解为：

- **从原来的单目标 `profile_greedy`，升级为“locality 主导、HOL 正则”的双目标 greedy。**

### 6.6 为什么这条路线最适合作为第一版

因为它满足三点：

1. 它直接作用于问题根因
- 问题根因是“地址顺序与 retire-age 顺序偏差过大”；
- 它正是在地址顺序构造阶段修这个偏差。

2. 它不碰 runtime 闭环
- 不需要新的 issue-time 判断；
- 不需要新的 retire policy；
- 不会再次踩到 step1 completion 风险。

3. 它与历史 PLP 经验一致
- 之前 `profile_greedy` 已经证明 offline packing 确实有大收益空间；
- 当前只是把目标从“纯 locality”扩展为“locality + HOL fairness”。

---

## 7. P3-C1：更激进的 line-block aware packing（后续候选）

如果 `P3-C0` 方向成立，但收益仍不足，则进入 `P3-C1`。

`P3-C1` 的核心变化是：

- 不再只对 whole-pre 做 placement；
- 而是把 values 进一步切成 line-block / chunk；
- 用更细的 placement 单元同时优化：
  - co-access
  - head-age band
  - line reuse

这一步的好处是：

- 能更直接降低 `line_groups_per_prepare_avg`
- 能让 `edges_per_line_group_avg` 上升
- 能更精准减少“老 head 被多个 line 断开、又被年轻 line 夹住”的现象

但这一步只有在 `P3-C0` 证明“offline 方向有效、runtime 不必继续改”之后才值得投入。

否则过早进入 `P3-C1`，很容易重演之前 `P3-B` 的问题，只是把复杂度从 runtime 挪到 generator/index。

---

## 8. 数据链路与产物设计

### 8.1 新增 profiling 产物

建议新增一个面向 offline generator 的 baseline 导出目录，例如：

- `mainexp/.../baseline_formalenv/.../offline_layout_profile/`

其中每个 core/PE 可导出：

- `window_edges.seq*.jsonl` 或压缩二进制
- `layout_profile.meta.json`

最小字段：

- `window_seq`
- `pre_global`
- `post_local`
- `pre_rank`
- `retire_seq`
- `local_age_rank`

可选字段：

- `addr`
- `line_id`
- `count`

### 8.2 新 artifact 目录

建议新 artifact 采用独立目录，不覆盖当前 frozen baseline：

- `sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_v7_holpg_j8/`

命名原则：

- 明确这是 offline HOL-aware placement；
- 不与当前 `v7_lpbl` baseline 混淆；
- 便于做 baseline vs candidate A/B。

### 8.3 manifest 记录

至少增加：

- `physical_order_mode`
- `hol_profile_source`
- `hol_objective_version`
- `hol_head_k`
- `hol_regularization_weights`

要求：

- manifest 能完整说明该 artifact 是如何生成的；
- 任何后续收益都能追溯到具体 profile 和 scorer 参数。

---

## 9. 实验计划与准入门槛

### 9.1 第一轮只做单点，不扫参

第一轮不要直接大 sweep，避免再次漂移。

固定单点：

- baseline：当前 frozen `v7_lpbl`
- candidate：`P3-C0` 单一 scorer 权重

推荐 gate：

1. **Closure gate**
- 必须完整通过 paper validation
- 必须 `windows_incomplete = 0`
- 必须明确看到 `BeginApply -> BeginScatter -> PE_DONE`

2. **HOL gate**
- `younger_ahead_depth.avg` 必须下降
- `older_head_wait.avg` 必须下降
- `line_groups_per_prepare_avg` 必须下降

3. **Memory gate**
- `memctrl_req_total` 不得显著恶化
- `payload_utilization` 不得显著恶化
- `traffic_amplification` 不得显著恶化

4. **End-to-end gate**
- `sim_time_actual_ns` 至少不回归

### 9.2 推荐对照矩阵

第一轮只保留三类：

1. `baseline_v7_lpbl`
2. `p3c0_hol_profile_greedy`
3. `p3c1_lineblock_hybrid` 仅在 `p3c0` 成功后进入

明确禁止：

1. 再把 `banded_line_fair` 拉回来一起扫
2. 混合 online reorder 与 offline layout 同轮对照
3. 在 closure 还没过 gate 时就讨论 HOL 收益

---

## 10. 风险与回退

### 10.1 最大风险不是 correctness，而是“收益方向错配”

offline layout 的最大风险不一定是 strict 失败，而可能是：

- `younger_ahead_depth` 下降了；
- 但 `payload_utilization` 一起恶化；
- 最终端到端没有净收益。

因此必须把 HOL gate 和 memory gate 绑定来看。

### 10.2 第二个风险是 profile 过拟合

如果 placement 过度贴合某一轮 profiling run，可能出现：

- 在 baseline sample 上很好；
- 在另一个 seed/step mix 上反而回归。

因此 `P3-C0` 第一轮应只证明“方向成立”，第二轮再做稳健性检查。

### 10.3 回退策略

如果 `P3-C0` 失败：

- 保留当前 frozen baseline runtime 与 artifact；
- 不进入新的 runtime reorder；
- 只把失败结论沉淀为：
  - 当前 `profile_greedy` 已接近 locality-optimal；
  - `HOL` 可能需要更激进的 index/layout 表达，或最终需要 contract 层重构。

也就是说，这条路线的失败代价很低，因为：

- **它不污染 runtime 主线。**

---

## 11. 逐步执行任务

### Task 0：固定 baseline profile 口径

目标：

- 只使用可信 MPI32 baseline 导出 offline layout profile；
- 不接受任何 closure 可疑的 run。

产出：

- 一套可复用的 `offline_layout_profile/`

### Task 1：补最小 profile exporter

目标：

- 导出每窗口 `pre_global / pre_rank / retire_seq / local_age_rank`

原则：

- observe-only
- 不改变 runtime queue / retire 行为

### Task 2：实现 `P3-C0` scorer

目标：

- 在 generator 中新增 `physical_order_mode=hol_profile_greedy`

要求：

- 默认参数固定；
- 先 whole-pre 级；
- 不同时引入新 index family。

### Task 3：生成单点 artifact

目标：

- 基于正式 baseline profile 生成 `P3-C0` artifact

要求：

- manifest 记录完整；
- self-check 完整通过。

### Task 4：formal baseline vs candidate 对照

目标：

- 用完全不变的 runtime 主线验证 `P3-C0`

要求：

- 先看 completion；
- completion 通过后再看 HOL / memory / end-to-end。

### Task 5：决定是否进入 `P3-C1`

准入条件：

- `P3-C0` 至少在 HOL gate 上成立；
- 且 memory/end-to-end 没有明显回归。

否则：

- 停止继续扩展复杂度；
- 不进入更细粒度 line-block packing。

---

## 12. 最终推荐

当前最合理、最稳、也最符合主线目标的下一阶段方案是：

- **停止继续增加 runtime online reorder；**
- **把问题正式转写为 offline layout / offline weight placement 问题；**
- **先做 `P3-C0 = HOL-aware profile-guided offline layout`；**
- **只在这个方向证明确有空间后，再进入 `P3-C1`。**

这条路线最重要的价值不是“更保守”，而是：

- 它把问题重新放回了当前证据真正指向的层面；
- 它不会再次把主线拖进 `step1 不结束` 的 closure 风险；
- 它允许我们在完全保留 baseline runtime contract 的前提下，回答一个更根本的问题：

- **是不是当前 values 物理排布，本身就在系统层面制造了我们看到的 HOL。**

如果答案是“是”，那么下一阶段真正该优化的就不是 `WeightMemorySubsystem` 的发射技巧，而是：

- **主线 weights 的物理排布目标函数。**
