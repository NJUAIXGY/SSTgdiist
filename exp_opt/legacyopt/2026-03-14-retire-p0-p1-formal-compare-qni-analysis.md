# Retire 下一阶段 P0/P1 完成文档

> 日期：2026-03-14
> 状态：done
> 范围：`P0 formal comparison 固化` + `P1 queued_not_issued / vlf_younger_ahead 机理分析`

---

## 0. 目的

本文件用于完成上一轮确定的两个下一阶段任务：

1. `P0`：把 frozen baseline / formal baseline / formal shadow 三组口径固化成可复用 comparison 基线；
2. `P1`：基于正式 replay 结果，把 `queued_not_issued` 的主导机理继续往前端拆清，判断下一阶段是否应继续押注真实 `per_post retire`。

输入 run：

- frozen baseline reference：
  - `mainexp/experiments/2026-03-12_atlas_core_step2_seedonly_ab_v1/runs/baseline_step2_seed_only_frac003/20260313-164701`
- formal baseline replay：
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_baseline_replay/20260314-190546`
- formal shadow replay：
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_shadow_replay/20260314-190546`

---

## 1. P0：formal comparison 固化

### 1.1 主统计 comparison

| run | validation | simulated time | global_steps_done | memctrl.req_total | memctrl.bytes_est_total | gas.memctrl_payload_utilization | gas.payload_bytes_per_memctrl_req_avg | gas.memctrl_traffic_amplification | gas.retire_crosspost_blocked_edges_total |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| frozen baseline ref `20260313-164701` | `fail=0 warn=0 strict=0` | `581.049 us` | `2` | `397207` | `25421248` | `0.2449300679494571` | `15.675524348765254` | `4.082798034442862` | `232715266461` |
| formal baseline replay `20260314-190546` | `fail=0 warn=0 strict=0` | `581.049 us` | `2` | `397207` | `25421248` | `0.2449300679494571` | `15.675524348765254` | `4.082798034442862` | `232715266461` |
| formal shadow replay `20260314-190546` | `fail=0 warn=0 strict=0` | `581.049 us` | `2` | `397207` | `25421248` | `0.2449300679494571` | `15.675524348765254` | `4.082798034442862` | `232715266461` |

### 1.2 contract / attribution comparison

| run | phase breakdown | head source mix | gcss phase mix | gcss queued reason mix | shadow enable | shadow cycles | shadow edges | shadow edges share of policy loss |
|---|---|---|---|---|---:|---:|---:|---:|
| frozen baseline ref `20260313-164701` | legacy summary schema 未显式写 `contracts.*` | `gcss` 主导 | 存在 | 不存在 | N/A | N/A | N/A | N/A |
| formal baseline replay `20260314-190546` | `true` | `gcss` 主导 | 存在 | 存在 | `0` | `0` | `0` | `0.0` |
| formal shadow replay `20260314-190546` | `true` | `gcss` 主导 | 存在 | 存在，且与 baseline 完全一致 | `1` | `324108` | `1554837` | `6.681284918024792e-06` |

### 1.3 P0 结论

- formal baseline replay 已经足够作为后续 candidate 的新固定 baseline：
  - 它与 frozen baseline reference 的主统计逐项一致；
  - 说明 Task 0-3 新增 contract / phase breakdown plumbing 不污染主线行为。
- formal shadow replay 证明 `shadow per-post retire` 仍然是 observe-only：
  - 它不改 memctrl；
  - 不改 `crosspost_blocked_edges_total`；
  - 不改 `gcss_phase_mix`、`gcss_queued_reason_mix`、`head_source_mix`。
- frozen baseline reference 属于较早 summary schema：
  - 已有 `gcss_phase_mix`；
  - 但没有新的 `contracts.*` 与 `gcss_queued_reason_mix`；
  - 因此后续 comparison 应优先以 `formal baseline replay` 为主引用口径。

---

## 2. P1：queued_not_issued / vlf_younger_ahead 机理分析

### 2.1 数据源与口径

本节主分析来自：

- `formal_baseline_replay/20260314-190546/essential_summary_mesh.json`
- `formal_baseline_replay/20260314-190546/pe*/core_step_perf_db.csv`

注意：

- `core_step_perf_db.csv` 的 `seq=1/2` 行是“截至该 seq 的累计值”，不是每步独立增量；
- 因此：
  - `seq=1` 表示 step1 结束累计；
  - `seq=2` 表示最终累计；
  - step2 增量需用 `seq2 - seq1` 差分。

### 2.2 全局 reason split

formal baseline 最终累计（`seq=2` / summary 对齐）：

- `queued_not_issued hol_cycles = 143221487`
- `queued_not_issued blocked_edges = 181289839940`
- 其中：
  - `vlf_younger_ahead hol_cycles = 142876530`
  - `vlf_younger_ahead blocked_edges = 180652442276`
  - `vlf_front_inflight_full hol_cycles = 344957`
  - `vlf_front_inflight_full blocked_edges = 637397664`

占比：

- `vlf_younger_ahead / queued_not_issued hol_cycles = 99.759%`
- `vlf_younger_ahead / queued_not_issued blocked_edges = 99.648%`
- `vlf_front_inflight_full / queued_not_issued hol_cycles = 0.241%`
- `vlf_front_inflight_full / queued_not_issued blocked_edges = 0.352%`

也就是说，当前 `queued_not_issued` 基本不是：

- loader not ready
- weight sram stall
- pending younger ahead
- pending front inflight full

而是几乎被单一原因 `vlf_younger_ahead` 主导。

### 2.3 时间维度：step2 更重，但不是“只有 step2 才有”

累计值：

- step1 结束：
  - `queued_not_issued hol_cycles = 62961598`
  - `queued_not_issued blocked_edges = 79886733666`
- 最终 step2 结束：
  - `queued_not_issued hol_cycles = 143221487`
  - `queued_not_issued blocked_edges = 181289839940`

step2 增量：

- `queued_not_issued hol_cycles delta = 80259889`
- `queued_not_issued blocked_edges delta = 101403106274`

解释：

- step1 已经存在显著 `queued_not_issued`；
- 但 step2 又继续追加了约 `56%` 的最终 `queued_not_issued` 总量；
- 这与已有 `top1_step_crosspost_share = 0.5702080090574466` 一致，说明主痛点确实偏向 `seq=2`，但不是纯粹的 step2 特例。

### 2.4 空间维度：系统性分散，不是少数热点

从最终 `seq=2` 累计值看，各 PE 的 `queued_not_issued hol_cycles` 分布为：

- 最高：`pe12 = 9563535`，只占全局 `6.677%`
- 最低：`pe04 = 8548915`，仍占全局 `5.969%`

也就是说：

- 16 个 PE 全部处于同一量级；
- 不是某一个 PE 或少数 PE 独占问题。

从 core 级 concentration 看：

- `top1_core_crosspost_share = 0.003643327856800017`
- `top1_core_window_crosspost_share = 0.0020704023991513494`
- `top4_cores_crosspost_share = 0.014530719906881134`

从 `queued_not_issued` final seq2 直接算 top-N share：

- top1 core：`0.364%`
- top5 cores：`1.792%`
- top10 cores：`3.553%`
- top20 cores：`7.014%`

因此，`queued_not_issued -> vlf_younger_ahead` 是一个明显的系统性分散问题，而不是 patch 几个 hotspot 就能解决的局部异常。

### 2.5 代表性 core-window

下表列出 final seq2 中 `queued_not_issued hol_cycles` 最高的一组 core-window：

| pe/core | seq | qni_hol | qni_blocked | vlf_younger_ahead_hol | vlf_younger_ahead_blocked | vlf_front_inflight_full_hol | vlf_front_inflight_full_blocked |
|---|---:|---:|---:|---:|---:|---:|---:|
| `pe10/core0` | `2` | `521902` | `730947914` | `521806` | `730719218` | `96` | `228696` |
| `pe12/core13` | `2` | `515596` | `737500349` | `515564` | `737428221` | `32` | `72128` |
| `pe12/core12` | `2` | `510553` | `715833314` | `496871` | `682271008` | `13682` | `33562306` |
| `pe12/core3` | `2` | `509144` | `714275180` | `497012` | `684237836` | `12132` | `30037344` |
| `pe14/core6` | `2` | `508903` | `685727791` | `508819` | `685661563` | `84` | `66228` |

可见：

- 主流窗口几乎都是 `vlf_younger_ahead ~= queued_not_issued`；
- 少数窗口会混入可见的 `front_inflight_full` 次因，但量级仍远小于 `younger_ahead`。

### 2.6 为什么这会压低真实 `per_post retire` 候选优先级

formal shadow 给出两个同时成立的事实：

1. 上界并不小：
   - `shadow_recoverable_blocked_edges_upper_bound_total = 232715266461`
   - `shadow_recoverable_blocked_ratio_upper_bound = 0.9989341342195708`
2. 但真实 shadow 账本里可提交机会很小：
   - `recoverable_edges_total = 1554837`
   - `recoverable_edges_share_of_policy_loss = 6.681284918024792e-06`

这说明：

- 仅从“cross-post blocked 很多”并不能推出“切成 per-post retire 就能恢复很多”；
- 大量 blocked edges 在当前时序下并没有变成“同 tick 内 shadow 真可提交”的 ready-and-committable work；
- 因此问题更像：
  - 前端 VLF / issue queue 的 older-head 推进被 younger entries 长时间压住；
  - 而不是末端 retire contract 一改就会自然释放大块收益。

---

## 3. P0/P1 完成后的阶段判断

P0/P1 完成后，当前最稳的阶段判断是：

- Task 0-3 已经正式闭环；
- 真实 `per_post retire` 不应再作为下一阶段默认优先项；
- 下一阶段应转到：
  - `GCSS/VLF front-end ordering`
  - `older-head fairness`
  - `front inflight release / admission`

换句话说：

- 当前最值得优先回答的问题不是“retire 能不能改”
- 而是“为什么 older GCSS head 长时间发不出去，而 younger VLF entry 一直排在前面”

---

## 4. 建议的后续任务

### P2：补 front-end / ordering 观测

建议新增但仍保持 observe-only 的指标：

- older-head age / wait histogram
- younger-ahead depth histogram
- VLF front 被 younger 占住时的 front residency
- admission / inflight release 相关时延

目标不是立刻改策略，而是把 `vlf_younger_ahead` 再拆成可操作的更细原因。

### P3：前端 candidate，小步 A/B

在不动默认 retire contract 的前提下，优先考虑：

- older-first / age-fair 倾向
- VLF front reorder / fairness
- inflight release 更快回收

所有 candidate 都应：

- 先对照 formal baseline；
- 再检查 `queued_not_issued` 与 `vlf_younger_ahead` 是否下降；
- 最后才看系统级收益。

### P4：真实 per-post retire 仅保留为备选

只有满足以下任一条件时，才建议重提真实 `per_post retire`：

- 证明当前 shadow ledger 明显低估 recoverable opportunity；
- 或者前端 candidate 做完后，仍有大量无法解释的 policy loss 残留。

---

## 5. 一句话结论

`P0` 证明了 Task 0-3 的正式 replay 不污染 frozen baseline；`P1` 证明了当前真正要优先解决的是 `queued_not_issued -> vlf_younger_ahead` 的前端顺序问题，而不是直接切默认 `per_post retire`。
