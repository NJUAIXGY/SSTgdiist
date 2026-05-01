# Offline Anti-Burial V2 设计

> 日期：2026-03-16  
> 状态：design-only  
> 适用范围：`snndl` 主线，面向 `GCSS-GLIDE` 的 offline layout 生成器，不改 runtime issue / retire contract。

---

## 0. 一句话结论

在当前 closure-fixed baseline 上，主线问题已经可以重新表述为：

- `completion_state` 是干净的；
- `materialization_ratio=1.0`
- `retire_drain_ratio=1.0`
- `residual_work_windows_total=0`

因此当前主损失已经明确不是 completion / closure，而是：

- `gcss_queued_reason_mix.dominant_reason_by_hol_cycles = vlf_younger_ahead`
- `issue_gate.dominant_gate_by_hol_cycles = vlf_front_inflight_full`

这意味着下一阶段不应再优先改 runtime，而应优先做：

- **offline whole-pre constrained anti-burial v2**

它的目标不是“比 `hol_profile_greedy v1` 更激进地强化 locality”，而是：

- 在保持 `base + pre_rank` 合约不变的前提下，
- 对 high head-risk 的 pre segment 做更保守的 physical 排布，
- 避免它们在 line 边界和短线块里相互挤压，
- 从而压低 younger-ahead burial。

---

## 1. 当前 closure-fixed baseline 重新确认了什么

本轮可信 baseline：

- `/home/xgy/remote/mainexp/experiments/2026-03-16_closure_fixed_baseline_observe/runs/baseline_formalenv_drain200/20260316-160840`

关键事实：

- `global_steps_done=2`
- `windows_done=32`
- `windows_incomplete=0`
- `sim_time_actual_ns=581049`
- `memctrl.req_total=397207`
- `gas.memctrl_payload_utilization=0.2449300679494571`

并且它与旧 formal baseline 主统计完全贴齐：

- `sim_time_actual_ns` 一致
- `memctrl.req_total` 一致
- `gas.memctrl_payload_utilization` 一致
- `spike_activity.neurons_fired_total` 一致
- `memory.memory_requests` 一致

这说明：

- closure fix 没有把主线 baseline 行为带偏；
- 后续我们终于可以在一个可信且不再卡 step 的基线上重做 HOL 分析。

在这个基线上，前端观测为：

- `queue_shape.edges_per_prepare_avg = 2432.20`
- `queue_shape.line_groups_per_prepare_avg = 620.64`
- `queue_shape.edges_per_line_group_avg = 3.92`
- `younger_ahead_depth.depth_avg = 575.63`
- `younger_ahead_depth.depth_max = 2532`
- `issue_gate.vlf_front_inflight_full_cycles_total = 344957`
- `completion_state.materialization_ratio = 1.0`
- `completion_state.retire_drain_ratio = 1.0`

因此，真正该优化的是：

- Apply 内部的 burial / inflight gate，
- 而不是 completion 语义。

---

## 2. 为什么 `hol_profile_greedy v1` 不够

当前 `hol_profile_greedy v1` 的核心做法，本质上是：

- 从 `offline_layout_profile.csv` 统计 `head_hits`
- 把 `head_hits` 用 `bonus` 叠到 `freq`
- 再继续使用原始 `profile_greedy` 链式排序

这个方法能做的事情只有一类：

- 让“更常出现在头部的 pre”更早被全局挑出来

但它做不到两件关键事：

1. **无法显式约束 head-risk pre 之间的共线/相邻挤压**
- 也就是无法防止多个高风险 pre 被连续放在容易共享 line 的位置。

2. **无法显式约束 line fatness**
- 也就是无法防止“line_groups 变少，但 edges_per_line_group 变胖”。

所以它很容易走到这类失败模式：

- memory 指标更好
- locality packing 更强
- 但 younger-ahead 更深
- 最终端到端回归

这不是参数微调能彻底解决的问题，而是 scorer 的目标函数本身不完整。

---

## 3. V2 的设计目标

V2 只做一件事：

- **在 whole-pre contract 下，把“高 head-risk pre 的相邻挤压”显式纳入选择约束。**

必须保持的边界：

1. 不改 runtime
2. 不改 `prepareGcssVlfIssueQueue_()` / `global_inorder retire`
3. 不改 `base + pre_rank` 读取合约
4. 不引入 online reorder

必须达到的目标：

1. `completion gate` 先过
2. `younger_ahead_depth` 不恶化
3. `vlf_front_inflight_full` 不恶化
4. 在此基础上再争取 locality / memory 不回归

---

## 4. 三条可选路线

### 4.1 方案 A：加权版 `hol_profile_greedy` v2

做法：

- 在 `freq + head_bonus` 的基础上继续加更多 penalty / reward

优点：

- 最接近现有实现
- 修改面最小

缺点：

- 需要大量权重调参
- 很容易重新落回“调一个全局分数，结果另一个维度恶化”的老问题

结论：

- 不推荐作为第一优先级。

### 4.2 方案 B：**受约束的局部候选池 greedy**

做法：

- 保留当前 `profile_greedy` 的 locality 候选生成；
- 但最终落位不再只按 locality score；
- 而是在一个小候选池里，优先排除会制造高 head-risk 共线挤压的 candidate。

优点：

- 不需要大量全局权重
- 更容易把“anti-burial”表达成显式约束
- 仍然保留现有 whole-pre contract

缺点：

- 实现略复杂于单一加权分数
- 需要定义局部 line-risk surrogate

结论：

- **推荐作为 V2 主方案。**

### 4.3 方案 C：line-block / line-chunk aware hybrid packing

做法：

- 直接升级 layout / index contract，让一个 pre 不再必须完全整段连续

优点：

- 表达能力最强

缺点：

- 风险最高
- 已经接近 contract 演进
- 不适合作为 closure 刚修稳后的第一步

结论：

- 只作为 V2 失败后的后续路线。

---

## 5. 推荐方案：Constrained Candidate Pool Greedy

### 5.1 核心思想

当前 `profile_greedy` 最大的问题不是 locality 本身，而是：

- 它只关心“谁更应该早出现”
- 不关心“谁和谁挤在一起会把头部压坏”

所以 V2 不去推翻 locality chain，而是：

- 先沿用它生成局部候选；
- 再在这些候选里，优先避开高风险相邻挤压。

### 5.2 输入信号

V2 只使用当前已有离线可得信号：

1. `pre_windows.csv`
- 提供 locality / transition preference

2. `offline_layout_profile.csv`
- 提供 head-risk 证据：
  - `local_age_rank`
  - `younger_ahead_depth`
  - `pre_global`

3. `pre_to_pairs[pre]`
- 提供 segment length

### 5.3 为每个 pre 构建的风险特征

建议最小特征集：

1. `head_hits(pre)`
- `local_age_rank < head_k` 的出现次数

2. `head_depth_sum(pre)`
- 在头部窗口内累计的 `younger_ahead_depth`

3. `head_depth_avg(pre)`
- `head_depth_sum / max(1, head_hits)`

4. `seg_len(pre)`
- 该 pre 的 value segment 长度

### 5.4 局部 line-risk surrogate

whole-pre contract 下，最容易制造 burial 的局部坏情况是：

- 当前 cursor 不在 line 边界；
- 下一个 pre 会和前一个 pre 共享尾 line；
- 且这两个 pre 都是高 head-risk。

因此建议定义：

1. `tail_share_cost(prev, cand, cursor)`
- 若 `cursor % VALUES_PER_LINE == 0`，则为 0
- 否则计算 cand 与 prev 是否共享当前尾 line，以及共享元素数

2. `head_collision_cost(prev, cand)`
- 与 `head_hits(prev) + head_hits(cand)` 或
- `head_depth_avg(prev) + head_depth_avg(cand)` 成正比

3. `projected_shared_line_risk`
- `tail_share_cost * head_collision_cost`

这不是对真实 runtime burial 的精确模拟，
但足够表达：

- “不要把两个高风险 pre 硬塞进同一条尾 line”

---

## 6. 选择规则

### 6.1 候选池来源

每一步不扫描所有剩余 pre，只看一个小候选池：

1. 当前 `profile_greedy` neighbor list 的前 `K1` 个未使用候选
2. fallback order 的前 `K2` 个未使用候选

建议初值：

- `K1 = 8`
- `K2 = 8`

### 6.2 选择优先级

推荐使用 **字典序约束**，而不是单一加权和：

1. 最小 `projected_shared_line_risk`
2. 最小 `head_depth_avg(cand)`
3. 最小 `head_hits(cand)`（或更准确地说，更少额外头部压力）
4. 最优 locality rank

这样做的好处是：

- anti-burial 是显式第一目标；
- locality 仍然保留，但不再凌驾于 head-risk 之上。

### 6.3 为什么不用单一全局分数

因为当前主线已经证明：

- locality 好转并不自动等于端到端好转；
- 单一分数很容易重新把 burial 问题吃掉。

所以 V2 更适合：

- 用“先满足 anti-burial 约束，再在剩余空间内保 locality”的思路。

---

## 7. 最小实现范围

V2 第一轮只改 generator：

- `/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

最小新增内容：

1. 新 order mode
- 例如：`hol_profile_constrained_v2`

2. 新的 head-risk loader
- 从 `offline_layout_profile.csv` 计算：
  - `head_hits`
  - `head_depth_sum`
  - `head_depth_avg`

3. 新 greedy selector
- 保留当前候选生成
- 新增 constrained pool 选择

4. meta/manifest 记录
- 候选池参数
- `head_k`
- line-risk surrogate 参数

不做的事：

1. 不做 sweep
2. 不加 padding
3. 不改 index format
4. 不碰 runtime

---

## 8. 验证计划

### 8.1 Baseline

固定使用：

- closure-fixed observe baseline
- `drain=200`
- `locality_first`
- `global_inorder`

参考 run：

- `/home/xgy/remote/mainexp/experiments/2026-03-16_closure_fixed_baseline_observe/runs/baseline_formalenv_drain200/20260316-160840`

### 8.2 Candidate Gate

第一轮 gate 顺序：

1. `completion gate`
- `global_steps_done=2`
- `windows_incomplete=0`
- `materialization_ratio=1.0`
- `retire_drain_ratio=1.0`

2. `HOL gate`
- `younger_ahead_depth.depth_avg` 不恶化
- `issue_gate.vlf_front_inflight_full_cycles_total` 不恶化
- `dominant_reason_by_hol_cycles` 不得从主问题漂成别的问题

3. `memory gate`
- `memctrl.req_total`
- `payload_utilization`

4. `end-to-end gate`
- `sim_time_actual_ns` 不明显回归

---

## 9. 下一步执行建议

### Task 0

实现 `hol_profile_constrained_v2` 最小 scorer，不改 runtime。

### Task 1

用 closure-fixed baseline profile 生成单点 artifact。

### Task 2

只做一组 baseline vs candidate A/B，不做 sweep。

### Task 3

如果 V2 仍然出现：

- `line_groups` 下降
- 但 `younger_ahead_depth` 恶化

则正式承认：

- whole-pre contract 的表达能力不够，
- 再进入 line-block / contract 升级评估。

---

## 10. 最终建议

V2 不应再追求“把更多东西排得更紧”，而应追求：

- **在不破坏 whole-pre contract 的前提下，尽量减少高 head-risk pre 的相邻共线挤压。**

这是当前主线下：

- 风险最低
- 解释最清晰
- 最容易与 closure-fixed baseline 对齐

的下一步路线。
