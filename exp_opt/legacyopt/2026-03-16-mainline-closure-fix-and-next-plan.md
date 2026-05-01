# Mainline Closure Fix 收口与下一阶段主线方案

> 日期：2026-03-16  
> 状态：design-only  
> 目标：在确认 `Stage0/1` 已回到可信主线后，给出下一阶段围绕 `HOL / younger-ahead burial` 的收敛方案，避免再次把主线带回不稳定的 runtime 试错。

---

## 0. 一句话结论

当前主线需要先明确分成两个问题：

1. `step1/step2` 不能稳定结束，是 **closure 语义错误**；
2. `retire HOL / younger-ahead burial` 很重，是 **layout + issue order + global_inorder retire 的结构失配**。

这两者不能再混着推进。

本轮结论已经足够明确：

- `closure` 的根因不在 `drain` 参数本身，而在 `Drain` done policy 会把 `bg_only` 慢核误判为空闲；
- 当前最小修复已经把这条根因命中；
- `P3-A`、`P3-B`、`P3-C0 v1` 都没有给出可直接进入主线的正向路径；
- 所以下一阶段应转成：
  - 先冻结可信 closure baseline；
  - 再重新采一轮 HOL 证据；
  - 然后优先走 **offline anti-burial v2**，而不是继续叠加 online reorder。

---

## 1. 当前已证明的事实

### 1.1 Closure 根因已经从“护栏不足”收敛到“done policy 过早”

旧失败中，`drain=200/5000` 的危险态都一致：

- `progressed=9`
- `done=9`
- `bg_only=11`

也就是：

- 一部分 core 已到 `EndScatter`；
- 但仍有一批 core 只停在 `BeginGather`；
- 旧逻辑会把这些 `bg_only` core 回退成 `hasWork()`；
- 一旦这些 core 恰好 `hasWork()==false`，PE 就可能提前发送 `PE_DONE`；
- controller 随后广播下一步 `START_STEP`，直接触发：
  - `GatherBufferIF fatal: openStep called while stage=1 (expected Idle)`

因此，`drain=50000` 之前能过，只是“拖时间拖过去了”，不是根因修复。

### 1.2 当前最小 closure fix 是正确方向

本轮最小修复只做了一件事：

- 只要某个 PE 里仍存在 `BeginGather` 停留 core，就对该 PE 保持 `active=true`；
- 不再允许 `Drain` 在 `bg_only` 核尚未真正收尾时发送 `PE_DONE`。

这意味着：

- 修复点命中根因；
- 没有去改核心 public interface；
- 没有去碰 retire contract；
- 没有把 closure 问题又扩散成新的行为改动。

### 1.3 `drain=5000` 已经回到可信闭环

`/home/xgy/remote/mainexp/experiments/2026-03-16_stage0_closure_fix/runs/stage0_drain5k_postfix/20260316-151014`

已确认：

- 无 `openStep called while stage=1`
- 有 `START_STEP seq=2`
- 有 `send PE_DONE(drain) seq=2`
- 有 `Simulation is complete`
- `validation.log` 为 `fail=0 warn=1 strict=0`
- `global_steps_done=2`
- `windows_done=32`
- `windows_incomplete=0`

这说明：

- 闭环已经恢复；
- `BeginApply -> issue/retire/drain -> PE_DONE` 的主线再次可用；
- 后续 HOL 观测终于可以回到可信基线上做。

### 1.4 HOL 主问题仍然没有变

之前所有可信分析都指向同一件事：

- 当前主损失不是 materialization 失败；
- 不是 bank credit；
- 不是 downstream busy；
- 也不是 barrier wait；

而是：

- `locality-first` 地址顺序发射
- `global_inorder` retire
- 两者叠加后，把 older head 长时间埋在 younger-ready edge 后面

所以主导瓶颈仍然是：

- `vlf_younger_ahead`
- 伴随 `vlf_front_inflight_full`

---

## 2. 为什么 P3-A / P3-B / P3-C0 现在都不是主线答案

### 2.1 P3-A：bounded rescue 只是探针，不是主收敛

`P3-A` 能轻微压低 `queued_not_issued / vlf_younger_ahead`，但：

- 总 HOL 几乎没有形成净收益；
- 阻塞更多是转移到了 `issued_wait_resp`；
- memory 主统计基本不变。

结论：

- 它证明“issue 选择时机”确实影响 front HOL；
- 但它没有解决主矛盾；
- 不值得继续作为主线方向扩大 sweep。

### 2.2 P3-B：online line-band reorder 风险过高

`P3-B banded_line_fair(band=256)` 的单点候选已经出现过：

- `seq1 BeginApply` 长时间不闭环；
- `cyc=540000` 时仍 `ba=20 ea=0 bs=0 es=0`

这条路的问题不只是“参数不好”，而是：

- 一旦把 online reorder 直接推进到队列构建/发射行为层，
- 它很容易同时改坏：
  - closure 节奏
  - inflight 形态
  - queue burial

在 closure 刚被修回来的阶段，不应该再把主线压到这条高风险路径上。

### 2.3 P3-C0 v1：whole-pre locality packing 更强，但 burial 更深

`hol_profile_greedy v1` 的已知现象很稳定：

- `memctrl.req_total` 下降
- `payload_utilization` 上升
- `line_groups_per_prepare_avg` 下降

但同时：

- `younger_ahead_depth` 明显恶化
- `older_head_wait` 恶化
- `vlf_front_inflight_full` 恶化
- 端到端 `sim_time_actual_ns` 回归

这说明：

- `whole-pre` 合约仍然更擅长“把线打包得更紧”；
- 但它不擅长 runtime 真正需要的 anti-burial；
- 所以不能再把“更强 locality packing”当作下一阶段默认方向。

---

## 3. 下一阶段的推荐主线

### 3.1 Stage A：冻结 closure baseline

目标：

- 不再让任何新的 HOL 优化工作建立在不稳定 closure 上。

具体要求：

1. 保留当前最小 closure fix，不再扩到 public interface。
2. 完成 `drain=200` 边界 run 的最终结论。
3. 固化一个最小 closure regression：
   - 单测已经覆盖 `bg_only` 回归；
   - 系统级至少保留 `drain=5000` 通过 run 作为可信样本。
4. 后续所有 HOL A/B 默认使用 closure-fixed baseline。

退出门槛：

- 至少一个可信 MPI32 baseline 在 `drain<=5000` 下稳定闭环；
- 最好确认 `drain=200` 也能成立。

### 3.2 Stage B：重新采一轮 HOL 证据，但只在可信基线上

目标：

- 不再重复“证明有 HOL”，而是更新在 closure-fixed 基线下，主损失仍然来自哪里。

固定观测组：

1. `queue_shape`
2. `issue_gate`
3. `completion_state`

建议附加：

- `younger_ahead_depth`
- `older_head_wait`
- `memctrl payload / req_total`

退出门槛：

- 能明确写出：
  - 当前 dominant HOL reason
  - 当前 dominant issue gate
  - 当前是否存在 residual completion/pathology

### 3.3 Stage C：优先做 offline anti-burial v2，而不是 online reorder

推荐路线：

- **C1：whole-pre constrained anti-burial v2**

核心思想：

- 仍然不改 runtime；
- 仍然保留现有 `base + pre_rank` 合约；
- 但 generator 目标函数不再只奖励 locality；
- 明确加入对“头部年龄错位”的惩罚约束。

推荐硬约束：

1. 限制头部窗口内的 `max younger-ahead depth`
2. 限制 `edges_per_line_group` 不可继续明显变胖
3. 保留一定 locality 收益，但不得以 burial 恶化为代价

第一轮不做 sweep，只做单点。

通过门槛：

- `completion gate` 必须先过
- `younger_ahead_depth` 不能恶化
- `vlf_front_inflight_full` 不能恶化
- 端到端至少不能明显回归

### 3.4 Stage D：只有在 C1 失败后，才讨论合约升级

如果 `whole-pre constrained anti-burial v2` 仍然失败，就说明问题更深：

- 当前 offline layout/index contract 对 anti-burial 的表达能力不够。

那时再正式进入：

- **C2：line-block / line-chunk aware hybrid packing**
- 或更激进的 contract 演进

但这一步必须满足两个前提：

1. closure baseline 已冻结；
2. 已证明 whole-pre v2 不足以承载目标。

在这之前，不建议重新回到在线 `P3-B` 式 runtime reorder。

---

## 4. 明确不再做的事情

下一阶段以下动作都不推荐：

1. 不再继续扩大 `P3-A` 参数 sweep。
2. 不再把 `P3-B` 在线队列重排作为默认主线。
3. 不再把 `drain=50000` 当作修复证据。
4. 不再把“memory 指标更好”直接等同于“主线更优”。
5. 不在 closure 仍未冻结前改 `retire` public contract。

---

## 5. 推荐执行顺序

### Task A0：Closure 收口

- 完成 `drain=200` run 结论
- 把 closure fix + `drain=5000` 成功样本写入 `TECH_PROGRESS.md`

### Task A1：可信基线再取样

- 用 closure-fixed baseline 再导出一轮 profile / summary
- 确认 `queue_shape + issue_gate + completion_state`

### Task B0：offline anti-burial v2 设计

- 在 generator 中定义新的 scorer：
  - locality reward
  - head-age displacement penalty
  - line-fatness penalty

### Task B1：单点 candidate A/B

- baseline vs candidate
- 先过 completion gate
- 再看 HOL / memory / end-to-end gate

### Task C0：若 B1 失败，再升级 contract 讨论

- 明确评估是否需要 line-block aware hybrid packing
- 只有这时才重新考虑更激进的 layout/index 演进

---

## 6. 最终判断

当前主线实现本身并不是“整体不成立”，真正的问题是：

- closure 层曾经有一个明确 bug；
- 这个 bug 会掩盖我们对 HOL 的判断；
- 在把 bug 修掉以后，HOL 主问题仍然存在，但它更像 **layout/runtime 结构失配**，而不是“再堆一个 online reorder 就能解决”的问题。

所以最稳的下一步不是继续在 runtime 上冒险，而是：

- 先冻结 closure，
- 再用可信证据重看 HOL，
- 然后优先从 offline anti-burial v2 收敛。
