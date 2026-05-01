# 主线下一阶段：Row-Band Anti-Compaction V1 设计

> 日期：2026-03-18  
> 状态：design-approved  
> 范围：`snndl` 主线，仅限 `offline generator / artifact layout`  
> 目标：在不修改 runtime 主契约的前提下，针对 `current formal profile` 导致的极端 `8KB/16KB row-window` 聚集，落一个最小可验证的 second-pass anti-compaction 候选。

---

## 0. 一句话结论

当前 top memory regression 的真正主因已经前移到：

- `current formal profile + pure profile_greedy`

而不是：

- `anchor_separator real mode`
- `v2_1` 本身

`v2_1` 实际上已经在 line 级做了部分放松，但它没有打破 `8KB/16KB row-window` 级别的极端聚集。

因此这一阶段的最小候选不应继续在 `anchor_separator` 末端做微调，而应直接在：

- `hol_profile_constrained_v2_1` 的 baseline order 输出之后

增加一个非常小、非常保守的 second-pass：

- **`band-aware stripe scatter`**

---

## 1. 问题重述

对 top memory cores 的统一口径分析已经给出三组关键事实：

1. `old baseline profile_greedy`
- `same_8KB_row_rate ≈ 0.874`
- `same_16KB_window_rate ≈ 0.884`

2. `current formal profile_greedy`
- `same_8KB_row_rate = 1.0`
- `same_16KB_window_rate = 1.0`
- 真正把 adjacency 压成极端 row-band compaction 的是它

3. `hol_profile_constrained_v2_1`
- `same_line_rate` 比 pure `current profile_greedy` 已经明显下降
- 但 `same_8KB_row_rate ≈ 0.996`
- `same_16KB_window_rate ≈ 0.996`

也就是说：

- `v2_1` 解决了部分 line compaction
- 但没有解决 row-band compaction

我们要处理的不是“继续降低 same-line”，而是：

- **主动把连续高局部性的 run 从同一个 `8KB/16KB band` 里拆开**

---

## 2. 为什么选 second-pass stripe，而不是继续改 greedy scorer

本轮有三个可选方向：

### 方案 A：在 `_order_by_profile_constrained_greedy()` 里继续加 row-band penalty

优点：
- 直接在选择阶段约束 band compaction

缺点：
- 会继续扰动 `v2_1` 的核心决策路径
- 调参面更大
- 容易重新走回“打分越来越复杂但主线越来越不稳”的旧路

### 方案 B：在 `anchor_separator` 末端继续做 block emission 调整

优点：
- 改动局部

缺点：
- 已经被证据否定为主矛盾
- `shadow vs candidate` 几乎相同

### 方案 C：在 `v2_1` 输出 order 后做 second-pass `band-aware stripe scatter`

优点：
- 不改 runtime
- 不改 `v2_1` 核心 greedy 决策
- 只在离线最终 order 上做小范围、可解释的结构修正
- 容易用静态 proxy 独立评估

缺点：
- 是比较粗粒度的修复，不直接感知 profile 边权

**本阶段选 C。**

理由：

- 主线最重要的是“先用最小风险把 row-band compaction 打开一个口子”；
- second-pass stripe 比继续改 scorer 更符合这个目标。

---

## 3. 最小候选：`hol_profile_constrained_v2_1_rowband_stripe_v1`

### 3.1 入口形式

新增一个独立实验 mode：

- `hol_profile_constrained_v2_1_rowband_stripe_v1`

它的生成流程是：

1. 先按现有 `hol_profile_constrained_v2_1` 得到 baseline order
2. 再对这条 order 做一次 second-pass `rowband stripe repair`

这意味着：

- 现有 `v2_1` mode 保持不变
- 现有 `anchor_separator` mode 保持不变
- 新候选可独立生成、独立验证、独立回退

### 3.2 second-pass repair 的核心思想

把 `v2_1` 输出 order 按 value 数切成固定大小的 microblocks，然后在一个多 row 的窗口内做条带化交错输出。

默认参数：

- `microblock_values = 256`
- `row_values = 2048` 也就是 `8KB row`
- `stripe_rows = 4`

推导：

- 一个 `8KB row` 包含 `2048 values`
- 一个 row 内共有 `2048 / 256 = 8` 个 microblocks
- `stripe_rows = 4` 时，每次拿 `32` 个连续 microblocks 作为一个 stripe group

组内重排规则：

- 原始 group：
  - `0 1 2 3 4 5 6 7 | 8 9 10 11 12 13 14 15 | 16 ... | 24 ...`
- stripe 输出：
  - `0 8 16 24 1 9 17 25 2 10 18 26 ...`

效果：

- 原本会被连续塞进同一 row / 相邻 rows 的 run
- 现在被主动打散到 4 个 rows、2 个 `16KB windows`

### 3.3 为什么固定选 `stripe_rows = 4`

因为我们的目标不只是降低 `same_8KB_row_rate`，还要实质降低：

- `same_16KB_window_rate`

若只做 `stripe_rows = 2`：

- 很多热点仍会留在同一个 `16KB window`

而 `stripe_rows = 4`：

- 会跨 `4 * 8KB = 32KB`
- 至少能把原始连续 run 打散出当前 `16KB band`

---

## 4. 作用边界

以下内容本阶段明确不做：

1. 不改 runtime
2. 不改 `bcsr_gas`
3. 不改 `prepareGcssVlfIssueQueue_()` / `popNextGcssVlfIssueEntry_()` / `tryRetireEdges_()`
4. 不改 `anchor_separator` 逻辑
5. 不修改已有 `v2_1` mode 的行为
6. 不引入 profile-weight aware 的复杂 scorer penalty

也就是说，这只是：

- **`v2_1` 输出 order 的一个离线 second-pass repair**

---

## 5. 代码落点

预计只改两类文件：

1. generator
- `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

2. unit tests
- `sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

计划新增：

- 新 order mode 常量
- `rowband stripe` 默认参数
- 一个纯 helper：
  - 输入：baseline order + `pre_to_pairs`
  - 输出：repaired order + 轻量 stats

---

## 6. 验证口径

### 6.1 单测

至少锁住两件事：

1. stripe helper 在一个人工可控的小例子上，确实能把连续 row 运行打散
2. 新 mode 确实是在 `v2_1` 基础上接入 second-pass，而不是改坏原始选择路径

### 6.2 静态 proxy

优先仍看 top memory cores：

- `pe10/core11`
- `pe08/core15`
- `pe01/core02`
- `pe12/core01`
- `pe14/core13`
- `pe02/core02`

验收方向：

1. 相对 `v2_1`
- `same_8KB_row_rate` 下降
- `same_16KB_window_rate` 下降
- `avg_row8_gap` 上升
- `avg_win16_gap` 上升

2. 相对 `old baseline`
- 不要求回到 old
- 但不能把 line locality 完全打崩

也就是：

- 我们接受 line locality 有所回撤
- 但目标是“用有限的 line 回撤，换明确的 row-band 解压”

### 6.3 runtime gate

本阶段不直接承诺 full runtime promotion。

顺序必须是：

1. 先过单测
2. 先过静态 proxy
3. 静态 proxy 明显成立后，再决定是否生成 artifact 做 frozen MPI32 short gate

---

## 7. 风险与止损条件

### 7.1 主要风险

1. stripe 太强，导致 HOL 改善被完全冲掉
2. row-band 确实解开了，但 line fragmentation 过高
3. second-pass 过粗，收益不稳定

### 7.2 止损条件

如果出现以下任一情况，本方案不继续扩展：

1. `same_8KB_row_rate` / `same_16KB_window_rate` 没有实质下降
2. `same_line_rate` 直接塌回 old baseline 附近，但 row-band 仍无明显改善
3. 生成的新 order 在 top memory cores 上没有方向性收益

若止损，则下一步再考虑：

- 把 row-band 约束前移进 greedy scorer
- 但那应当是下一阶段方案，不是这次最小候选

---

## 8. 本轮推荐执行顺序

1. 新增设计文档
2. 先写两条 unit tests
3. 新增 `hol_profile_constrained_v2_1_rowband_stripe_v1`
4. 跑 `unittest + py_compile`
5. 跑 top memory cores 静态 proxy
6. 再决定是否值得生成下一版 artifact

---

## 9. 最终结论

这次不是要“再发明一个更复杂的 v2_1 scorer”，而是要先用最小 second-pass repair 去验证一件事：

- **只要把 `v2_1` 形成的连续热点 run 从同一个 `8KB/16KB band` 中拆开，memory regression 的主形状能不能显著缓解。**

如果这件事成立，后面再考虑把它精细化成：

- row-band quota
- profile-weight aware anti-compaction
- 或更局部的 band-aware local repair

如果这件事不成立，再转向 scorer-level 方案也不迟。
