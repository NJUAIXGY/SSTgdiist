# 主线下一轮 Offline Scorer 设计：`P3-C1` 基线上的 Dual-Guard Anti-Burial

> 日期：2026-03-17  
> 状态：design-only  
> 范围：`snndl` 主线，且只讨论 `offline layout / artifact generator`  
> 目标：在不改 runtime 主契约、不再引入 online reorder 的前提下，基于最新 Stage A 静态证据，为下一轮 offline scorer 给出可直接执行的设计与最小实现方案。

---

## 0. 一句话判断

当前主线实现本身并不是“不稳定”或“根本错误”，真正不够完美的地方是：

- 现有 `P3-C1` / `hol_profile_constrained_v2_1` 仍然主要是在保护局部 shared-line 风险；
- 它还没有显式保护 `oldest-head` 周围的 closure-friendly 邻域几何；
- 因而一旦走到 `P3-C2a` 这种 broad relaxation，就会出现两类失真：
  - `target-head displacement`
  - `closure-neighborhood drift`

所以，下一轮不能再把“让 target 更靠前”当成主目标，而必须把 scorer 升级成：

- **Guard 1：target-head displacement penalty**
- **Guard 2：closure-neighborhood drift penalty**

这就是本轮推荐的 `dual-guard anti-burial` 主线。

---

## 1. 为什么说当前布局不是坏掉了，而是目标函数不完整

### 1.1 主线 runtime 已经稳定，问题在 layout 目标

我们已经反复验证：

- baseline runtime 可以稳定 closure；
- `BeginApply -> issue -> retire/drain -> PE_DONE -> START_STEP seq=2` 闭环已成立；
- 当前最重的前端损失来自 `vlf_younger_ahead`；
- 因此主问题不是 runtime 行为缺失，而是：
  - `locality_first issue + global_inorder retire`
  - 与当前 offline 布局目标之间存在结构失配。

也就是说，主线实现稳定，但当前布局更像是在优化：

- locality
- line fill
- 局部 shared-line 风险

而不是在优化：

- `oldest head` 能否尽快 break-ice
- `target head` 周围的 rank 邻域是否仍然 closure-friendly

### 1.2 最新静态证据说明“只看 target 是否前移”是不够的

Stage A 第二批静态 diff 已经给出三个决定性结论：

1. 对 `pe00/core00, target_pre=3438`：
- `P3-C2a` 把 target 从 `1962 -> 1763`，前移了 `199`
- 但 runtime closure 更差

2. 同一 target 的 `±256 rank` 邻域：
- union 有 `713` 个 pre
- 真正发生 rank 变化的只有 `16` 个
- 其中 `14` 个是 `|delta| >= 128` 的大位移

3. top abnormal cores 里同时存在两类现象：
- target 本身大幅变化，但邻域只动少量关键 pre
- target 自己不动，但邻域里有几十到上百个 pre 被重排

这说明：

- `target_pre` 的 rank 只是结果表象；
- 真正影响 closure 的，是 target 周围那一小撮关键邻居，以及它们共同组成的 tail geometry；
- 当前 scorer 最大的问题不是“不够激进”，而是**没有把 neighborhood geometry 作为一等公民来保护**。

---

## 2. 下一轮 scorer 的三个候选方向

### 2.1 方案 A：Target-Only Head Penalty

做法：

- 继续沿用 `hol_profile_constrained_v2_1`
- 只额外强化 `head_hits / head_depth_avg`
- 目标是让 high-risk pre 更靠前，减少 oldest-head burial

优点：

- 实现最小
- 改动面最窄

缺点：

- 很容易重演 `P3-C2a` 的问题
- 会把注意力过度集中在 target 自身，而忽视 target 周围的关键邻域
- 无法解释“target 不动但 neighborhood 已坏”的失败型

结论：

- 不推荐作为主线方案

### 2.2 方案 B：Dual-Guard Constrained Greedy

做法：

- 保留 `P3-C1` 当前的 constrained greedy 基础框架
- 仍然使用：
  - `profile_path`
  - `hol_profile_path`
  - `pre_to_pairs`
  - `neighbor_pool / fallback_pool`
- 但在候选打分时，显式引入两层 guard：
  - `target-head displacement penalty`
  - `closure-neighborhood drift penalty`

优点：

- 能直接覆盖 Stage A 暴露出的两类失真
- 不需要改 runtime / index contract
- 可以沿用当前 generator 结构，不会再次把主线带回高风险路径

缺点：

- 需要补一层离线 neighborhood surrogate
- 解释性和参数化比 `P3-C1` 更复杂一些

结论：

- **推荐作为下一轮主线方案**

### 2.3 方案 C：Hard Neighborhood Freeze

做法：

- 对头部高风险 pre 直接建立“冻结邻域”
- 一旦某个 target-pre 周围出现 closure-friendly 形态，就尽量不再允许其邻域发生重排

优点：

- 对 `neighborhood drift` 抑制最强

缺点：

- 过于僵硬
- 可能把 locality 与 fill 的可用搜索空间锁死
- 更像 guardrail，而不像 scorer

结论：

- 只适合作为 B 的兜底护栏，不适合作为独立主方案

---

## 3. 推荐方案：`dual_guard_hol_constrained_v3`

### 3.1 设计目标

推荐的新 order mode 暂定为：

- `hol_profile_dual_guard_v3`

其核心目标不是简单“让头更靠前”，而是：

1. 保护 oldest-head 不被继续深埋
2. 保护 target 周围有助于 break-ice 的邻域几何
3. 仍然保留 `P3-C1` 当前已有的 locality / fill 收益
4. 严禁再次引入 `P3-C2a` 那种 broad fat-tail reshape

### 3.2 仍然保持不变的东西

以下内容必须冻结：

1. 不改 runtime
2. 不改 `prepareGcssVlfIssueQueue_()` / `popNextGcssVlfIssueEntry_()` / `tryRetireEdges_()`
3. 不改 `base + pre_rank` contract
4. 不改 index 语义
5. 不做 line-chunk / split-pre / online reorder

也就是说，这仍然是一个纯 generator / artifact 层方案。

---

## 4. Dual-Guard 的核心思想

### 4.1 Guard 1：Target-Head Displacement

这层 guard 回答的问题是：

- 当前候选会不会把高风险 target-pre 自身推到更差的位置？

它关注的是：

- `head_hits(pre)`
- `head_depth_avg(pre)`
- `head_depth_sum(pre)`
- `seg_len(pre)`

与 `P3-C1` 的不同点不在于有没有 head-risk，而在于：

- 不再只把这些量用于 shared-line risk
- 而是明确把它们当成“target 本体不能被继续破坏”的惩罚

最小 surrogate 可以定义成：

- `target_penalty(cand) = target_risk(cand) * projected_head_exposure(cursor, seg_len)`

其中：

- `target_risk(cand)` 由 `head_hits + head_depth_avg` 构成
- `projected_head_exposure` 反映这个 pre 落在当前位置后，是否会继续处于容易被 younger bury 的物理带

第一版不追求精确 runtime 模拟，只要求能稳定区分：

- “这个 pre 继续往坏方向挪”
- 与
- “这个 pre 至少没有继续恶化”

### 4.2 Guard 2：Closure-Neighborhood Drift

这层 guard 是本轮真正新增的关键。

它回答的问题是：

- 即使 target 自身没坏，这个候选会不会破坏 target 周围那一小撮 closure-friendly 邻居？

Stage A 已经证明：

- target 不动并不等于候选安全
- 真正危险的是 target 周围关键邻居被重新排布

因此需要为每个高风险 pre 建一个轻量 neighborhood surrogate：

1. 从 `offline_layout_profile.csv` 里选出：
- `local_age_rank < head_k`
- 且 `younger_ahead_depth` 较高

2. 对这些 pre 的 transition 邻居，构建一个“弱邻域集合”：
- profile 相邻 / 近邻 co-access
- shared-line 历史碰撞
- 同窗口出现频率

3. 候选选择时，不只看 `cand` 自己的风险
- 还看它是否会让这些弱邻域发生大位移

第一版不做全局邻域图优化，只做可解释的局部 surrogate：

- `neighbor_drift_penalty(prev, cand, cursor)`

含义是：

- 如果当前位置会把高风险 target 周围的一组弱邻域切散、推远或形成新的 fat tail，就罚

### 4.3 Dual-Guard 不是新求解器，而是对现有 constrained greedy 的升级

这点很重要。

推荐方案不是推翻当前 `_order_by_profile_constrained_greedy()`，而是在它的候选池和字典序选择逻辑上增量升级：

旧版更像：

1. 先看 `fat_tail_guard`
2. 再看 `shared_line_head_risk`
3. 再看 `cand_risk`
4. 再看 locality rank

新版建议改成：

1. `hard_guard`: 禁止 broad reshape / 极端 drift
2. `target_displacement_penalty`
3. `neighborhood_drift_penalty`
4. `shared_line_head_risk`
5. locality rank
6. fallback order

这样才能把本轮学到的两类失真都正面纳入目标函数。

---

## 5. 最小可行 surrogate 设计

### 5.1 High-Risk Target Set

先从 `hol_profile_path` 中提取一个最小 target 集合：

- `local_age_rank < head_k`
- `head_depth_avg` 非零
- 按 `head_hits * head_depth_avg` 排序
- 每个 core 只保留 top `M`

建议第一版：

- `head_k = 256`
- `M = 32`

目的不是全量建模，而是把真正决定 closure 的头部高风险 pre 抓出来。

### 5.2 Weak Neighborhood Set

为每个 target-pre 建一个弱邻域集合：

来源优先级：

1. `profile trans(src, dst)` 的高权重邻居
2. 与 target 在相同 `window/post_local` 中多次共同出现的 pre
3. 与 target 有 shared-line 风险叠加的 pre

建议第一版每个 target 只保留：

- top `K = 8` 个 neighborhood pre

这样可以避免图过大，同时足够覆盖 Stage A 中“只有少量关键 pre 被重排”的现象。

### 5.3 Drift Surrogate

第一版只需要一个弱但稳定的 surrogate：

- 若一个候选让 target 邻域中的 pre：
  - 更远离 target 所在的局部物理带
  - 或更容易形成新的 shared tail
  - 或显著增加局部尾部长段拼接
- 就增加 drift penalty

可解释的最小实现形式：

1. `neighbor_band_pressure`
- 统计当前位置附近已经累计放入的 high-risk neighbor 量

2. `neighbor_split_pressure`
- 当前位置是否会把同一 target 的关键邻域切到更远的 band

3. `neighbor_tail_coupling`
- 当前 `prev + cand` 是否会制造新的高风险尾行耦合

第一轮只要这三项能区分：

- `P3-C1` 式温和邻域保持
- 与 `P3-C2a` 式关键邻域漂移

就已经足够。

---

## 6. 选择规则

### 6.1 候选池

仍然保持 `P3-C1` 的局部候选池模式：

1. 当前 profile 邻居前 `K1`
2. fallback 前 `K2`

建议首轮保持：

- `K1 = 8`
- `K2 = 8`

不在第一轮扩大搜索空间，避免 attribution 混乱。

### 6.2 新的字典序

推荐第一轮使用严格字典序，而不是加权求和：

1. `broad_reshape_guard`
2. `target_displacement_penalty`
3. `neighborhood_drift_penalty`
4. `shared_line_head_risk`
5. `cand_risk`
6. locality rank
7. fallback order

原因很简单：

- 当前主线最大的教训，就是 locality 好看不代表 closure 更好
- 所以前 3 项必须是真正的一等门槛

### 6.3 Broad Reshape Guard

这是从 `P3-C2a` 学到的硬教训。

第一轮必须显式禁止：

- broad fat-tail relaxation
- 大面积中深层 rank 漂移
- 无法解释的 neighborhood mass move

也就是说，新 scorer 不是“更大搜索空间”，而是“更严格的 guard + 更精确的局部选择”。

---

## 7. 最小实现方案

### 7.1 只改一个文件

第一轮实现只允许改：

- `/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

不改 runtime，不改 idx reader，不改其他主线组件。

### 7.2 最小新增块

建议拆成 4 个最小块：

#### Block A：风险统计扩展

在现有 `_load_hol_profile_risk_stats()` 基础上，补：

- `target_score`
- `high_risk_target_set`
- `weak_neighborhood_map`

要求：

- 完全由 `offline_layout_profile.csv` 推导
- 不依赖 runtime 新日志

#### Block B：新 order mode

新增：

- `ORDER_HOL_DUAL_GUARD_V3 = "hol_profile_dual_guard_v3"`

并在 `_choose_physical_order()` 中接入。

#### Block C：dual-guard selector

在现有 constrained greedy 基础上新增一个新 selector，例如：

- `_order_by_profile_dual_guard_greedy(...)`

要求：

- 复用现有候选池
- 复用当前 fallback / neighbor 结构
- 只增强 candidate key

#### Block D：meta 记录

meta / manifest 中新增：

- `hol_objective_version = dual_guard_v3`
- `hol_target_top_m`
- `hol_neighbor_top_k`
- `hol_dual_guard_enabled = 1`

这样后续实验结果才能做 attribution。

---

## 8. 验证与 gate

### 8.1 Gate 0：静态 gate 先行

任何 runtime 前，先过静态 gate：

1. `manifest/meta/idx` 全部通过
2. 与 `P3-C1` 对比时，不得出现无法解释的大面积 rank 重排
3. 必须能导出：
   - target rank 变化
   - neighborhood moved-pres 数量
   - large-shift 数量

### 8.2 Gate 1：只做 `P3-C1 vs candidate` 的静态对照

使用现有 Stage A 脚本，重点检查：

1. `target rank` 是否更好或至少不坏
2. `±256 rank` neighborhood 的 moved-pres 是否受控
3. `|rank_delta| >= 128` 的数量是否受控

首轮建议门槛：

- 不能比 `P3-C1` 出现更多无法解释的大位移
- 不能出现 `P3-C2a` 式 target 大幅前移/后移同时伴随 broad drift

### 8.3 Gate 2：通过后才进入短 runtime

只有静态 gate 通过，才允许做：

- `seq1`
- `pe0/core0`
- `diag-gcss-vlf-head`

如果看到：

- `head_queue_depth` 更坏
- `next_retire` 更慢
- `step1` 再次停滞

立即止损，不进入 formal。

---

## 9. 下一阶段执行顺序

### Task 0：先实现 design-only 所需的最小统计结构

目标：

- 不改变物理顺序
- 只把 `high_risk_target_set / weak_neighborhood_map` 的统计在 generator 里算出来
- 确认统计值在 meta 中可见

### Task 1：接入新 order mode，但先 shadow 计算 key

目标：

- 能跑出 candidate key
- 暂不改变最终顺序
- 先确认 key 分布是否合理

### Task 2：启用 dual-guard selector

目标：

- 只做单点参数候选
- 不 sweep
- 不叠别的 heuristic

建议首轮固定：

- `head_k = 256`
- `target_top_m = 32`
- `neighbor_top_k = 8`

### Task 3：先过静态 Stage A gate

目标：

- 只看 `P3-C1 vs candidate`
- 明确回答 candidate 是：
  - 改善了 target-displacement
  - 改善了 neighborhood drift
  - 还是两者都没有改善

### Task 4：通过后再进入最小 runtime gate

目标：

- 只做可信短口径
- 不直接 formal

---

## 10. 最终建议

下一轮最值得做的，不是“更激进地让 head 往前”，而是：

- 在 `P3-C1` 基线之上，
- 用一个更严格、更可解释的 `dual-guard scorer`
- 同时保护：
  - `target-head`
  - `closure-neighborhood`

如果这个方向仍然失败，才说明：

- 当前 whole-pre contract 对主线 anti-burial 的表达能力可能真的不够

在此之前，不应再回到 online reorder，也不应再继续调 `P3-C2a` 这类 broad relaxation 路线。
