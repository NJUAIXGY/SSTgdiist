# Mainline P2/P3：GCSS/VLF Front-End Ordering 优化方案

> 日期：2026-03-14
> 状态：design-only
> 范围：下一阶段主线 `P2 observability + P3 small-step candidate`
> 前提：`Task 0-3` / `P0/P1` 已完成，默认 baseline 仍保持 `global_inorder retire`

---

## 0. 一句话结论

下一阶段主线最值得投入的方向，不是真实 `per_post retire`，而是：

1. 先把 `queued_not_issued -> vlf_younger_ahead` 拆成可操作的前端时序证据链；
2. 再围绕 `older-head fairness` 做小步、可回退的 issue-side candidate；
3. 最后才考虑更次级的 `inflight release` 调优；
4. 真实 `per_post retire` 仅保留为备选，不再作为默认主线项。

---

## 1. 输入依据

本方案建立在以下结论之上：

- 主线定义仍以：
  - `DRAM-based SNN chip`
  - `GAS`
  - `GCSS-GLIDE`
  - `STORM`
  - `MulticastRouter`
  为唯一根基；
- `Task 0-3` 已经完成 formal baseline / formal shadow replay 验收；
- `P0/P1` 已确认：
  - formal baseline/shadow 可作为新的固定 comparison 口径；
  - 当前 `queued_not_issued` 的主导机理几乎就是 `vlf_younger_ahead`；
  - 问题具有 step2 偏重、但空间分散的系统性特征；
  - `shadow per-post retire` 的真实 recoverable share 极小，不支持把真实 `per_post retire` 作为下一阶段主线优先项。

关键文档：

- `exp_opt/2026-03-06-system-mainline-dram-snn-gas-storm-gcss-glide.md`
- `exp_opt/2026-03-13-gas-retire-hol-system-treatment-design.md`
- `exp_opt/2026-03-14-retire-contract-task0-3-execution.md`
- `exp_opt/2026-03-14-retire-p0-p1-formal-compare-qni-analysis.md`

关键正式 run：

- frozen baseline reference：
  - `mainexp/experiments/2026-03-12_atlas_core_step2_seedonly_ab_v1/runs/baseline_step2_seed_only_frac003/20260313-164701`
- formal baseline replay：
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_baseline_replay/20260314-190546`
- formal shadow replay：
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_shadow_replay/20260314-190546`

---

## 2. 根因已经收敛到哪里

### 2.1 文档证据

目前已确认：

- `queued_not_issued hol_cycles = 143221487`
- `queued_not_issued blocked_edges = 181289839940`
- `vlf_younger_ahead hol_cycles = 142876530`
- `vlf_younger_ahead blocked_edges = 180652442276`

占比：

- `vlf_younger_ahead / queued_not_issued hol_cycles = 99.759%`
- `vlf_younger_ahead / queued_not_issued blocked_edges = 99.648%`

同时：

- `shadow_recoverable_edges_share_of_policy_loss = 6.681284918024792e-06`

因此当前最合理的判断是：

- 问题主体不在 retire tail；
- 而在 `GCSS/VLF` 前端队列和发射顺序。

### 2.2 代码证据

当前实现里，`vlf_younger_ahead` 不是离线推断，而是运行时直接判出来的：

1. `prepareGcssVlfIssueQueue_()`
   - 先按 edge 注册顺序生成 `retire_seq`
   - 再按 `addr -> pre_global -> post_local -> retire_seq` 做 locality-first 排序
   - 最终形成 `gcss_vlf_issue_queue_`
2. `issueFromEdgesOnce_()`
   - 在 GCSS pre-MPHF 模式下，直接从 `gcss_vlf_issue_queue_` front 发射
3. `classifyGcssQueuedNotIssuedReason_()`
   - 若 global retire head 仍在 `gcss_vlf_issue_queue_` 中，且它前面还有 entry
   - 就直接记为 `VlfYoungerAhead`

换句话说，当前主线真实冲突是：

- retire 顺序来自 edge 注册顺序；
- issue 顺序来自 locality-first 地址排序；
- 二者在 `global_inorder retire` 下发生了系统性顺序冲突。

---

## 3. 下一阶段候选总表

| phase | candidate | 目标 | 最小改动点 | 预期收益 | 主要风险 | 当前优先级 |
|---|---|---|---|---|---|---|
| `P2` | front-end observability | 把 `vlf_younger_ahead` 拆成可行动子因 | `prepareGcssVlfIssueQueue_()` / `classifyGcssQueuedNotIssuedReason_()` / `updateRetireHolStatsOnTick_()` / `handleReadResp_()` | 高信息增益，几乎无行为风险 | 只会“重复证明 old head 被 younger 卡住”，但拆不出更细原因 | `P0` |
| `P3-A` | bounded older-first / age-fair rescue | 对过老 head 做有界救援，降低 younger-ahead 压制 | `prepareGcssVlfIssueQueue_()` 或 `issueFromEdgesOnce_()` | 最可能直接压低 `queued_not_issued` 与 `vlf_younger_ahead` | 可能牺牲部分 locality，抬高 `issued_wait_resp` 或 DRAM 请求 | `P1` |
| `P3-B` | line-group aware fairness reorder | 在保留 line locality 的前提下加入 fairness 次排序 | `prepareGcssVlfIssueQueue_()` | 比简单 rescue 更系统地修正深队列压制 | 解释性更复杂，更容易打坏 baseline 对照 | `P2` |
| `P3-C` | inflight release / pending-drain tuning | 缩短 response 后的 slot 回收与 pending drain 延迟 | `handleReadResp_()` / `drainPendingDirectReads_()` / `drainPendingReads_()` | 若 release 迟滞是真因，可补齐尾部效率 | 当前证据显示 `front_inflight_full` 占比很小，容易投入后无主收益 | `P3` |
| `P4` | real per-post retire fallback | 只在前端方案无法解释残留时再考虑 retire contract 演进 | retire policy / contract 层 | 理论上可处理残余 policy loss | 直接触碰 contract、strict 与可解释性，当前证据不支持优先推进 | `backup only` |

---

## 4. P2：Observability 设计

### 4.1 目标

P2 的目标不是再证明“是 `vlf_younger_ahead`”，而是回答：

1. older head 究竟会被压多久？
2. younger-ahead 的深度通常是 1~2，还是深队列长尾？
3. head 主要卡在：
   - queue 排位
   - inflight 满
   - response 之后的 release/drain
   哪一类环节？
4. step2 更重是因为：
   - 队列更深
   - 局部性排序更激进
   - 还是 response/release 更迟
   造成的？

### 4.2 建议新增的最小指标集

| 指标 | 口径 | 推荐落点 | 用途 |
|---|---|---|---|
| `older_head_wait_cycles` / histogram | global retire head 从进入 `QueuedNotIssued` 到离开该状态的等待时长 | `updateRetireHolStatsOnTick_()` | 判断 older head 是否存在明显长尾 |
| `younger_ahead_depth` / histogram | head 在 `gcss_vlf_issue_queue_` 中前方 younger entry 数 | `classifyGcssQueuedNotIssuedReason_()` | 判断问题是轻度前插还是深队列压制 |
| `retire_seq_to_vlf_pos_delta` | `retire_seq` 相对 VLF 排位的后移幅度 | `prepareGcssVlfIssueQueue_()` | 直接度量 locality-first 排序对 old head 的挤压 |
| `vlf_front_residency_cycles` | VLF front entry 在被 younger blockage 或 inflight 门限影响时的驻留时长 | `issueFromEdgesOnce_()` / `classifyGcssQueuedNotIssuedReason_()` | 判断 front 是否“占位不走” |
| `gcss_issue_deferred_total` | GCSS issue 因 inflight/budget 未能立即发出的次数 | `issueGcssByAddr_()` | 判断 head 是否从 VLF 队列转移到 pending 队列 |
| `resp_to_pending_drain_cycles` | response 返回后，到相关 pending 请求真正被重新发射的时延 | `handleReadResp_()` | 判断 inflight release / pending drain 是否偏慢 |
| `older_head_unblock_reason` | old head 最终因何解除阻塞 | `updateRetireHolStatsOnTick_()` + response/issue路径 | 为后续 candidate 选择提供止损依据 |

### 4.3 推荐的最小插桩点

优先只动以下 4 个位置：

1. `WeightMemorySubsystem::prepareGcssVlfIssueQueue_()`
2. `WeightMemorySubsystem::classifyGcssQueuedNotIssuedReason_()`
3. `WeightMemorySubsystem::updateRetireHolStatsOnTick_()`
4. `WeightMemorySubsystem::handleReadResp_()`

原因：

- 四个点合起来已经覆盖：
  - queue formation
  - queue-state classification
  - HOL runtime accumulation
  - release/drain feedback
- 对外接口几乎不用动；
- 最适合以 observe-only 形式落到现有 CSV / summary 汇总链路中。

### 4.4 P2 的成功标准

- 能稳定回答 `vlf_younger_ahead` 的主因究竟是：
  - shallow unfairness
  - deep queue unfairness
  - front occupancy
  - release/drain latency
  中的哪 1~2 项；
- 能解释 step2 更重但 step1 也已显著存在的原因；
- 能解释为什么该问题是系统性分散，而不是少数 hotspot；
- 新统计仍能纳入现有 `head_source_mix -> gcss_phase_mix -> gcss_queued_reason_mix` 证据链。

如果做不到这些，P2 就还不算完成。

---

## 5. P3-A：bounded older-first / age-fair rescue

### 5.1 核心思想

不推翻 locality-first，也不改 retire contract；只在以下条件成立时对 old head 做有界救援：

- head 等待时长超过阈值；
- 或 `younger_ahead_depth` 超过阈值；
- 或同一个 older head 连续多 tick 保持 `QueuedNotIssued`。

可选做法：

1. `prepare-stage bounded promotion`
   - 在 queue 构造时把“过老/过深”的 head 提升到更靠前的位置；
2. `issue-stage bounded rescue`
   - queue 仍按 locality-first 生成；
   - 但在真正 pop front 前，允许小范围 front scan 选择 old head。

### 5.2 推荐优先实现方式

先做更保守的 `issue-stage bounded rescue`：

- 侵入更小；
- 不改变整条 queue 的可解释性；
- 一旦发现 locality 回归，也更容易整体回退。

### 5.3 成功标准

- `queued_not_issued hol_cycles` 下降；
- `vlf_younger_ahead` 占比下降；
- `issued_wait_resp` 不显著抬高；
- `memctrl.req_total`、`payload_utilization`、`traffic_amplification` 不恶化；
- strict / summary 对照仍清晰。

### 5.4 止损标准

- 只是把 `queued_not_issued` 转移成 `issued_wait_resp`；
- `req_total` 上升或 payload 利用率明显下降；
- 改善只集中在少数 PE/core，整体 share 基本不动。

---

## 6. P3-B：line-group aware fairness reorder

### 6.1 适用条件

只有当 P2 证明：

- `younger_ahead_depth` 普遍较深；
- 仅靠 bounded rescue 无法有效降低长尾；
- 且 queue-level 排序本身就是主因；

才建议进入这一阶段。

### 6.2 核心思想

保留 line-group / addr locality 的主框架，但把排序键从：

- `addr -> pre_global -> post_local -> retire_seq`

演进为分层排序，例如：

- `age_bucket -> addr -> pre_global -> post_local -> retire_seq`
或：
- `addr_group -> fairness_subkey -> retire_seq`

目标是：

- 不彻底打散 locality；
- 但不再允许 old head 长期被一整批 younger entry 压在深位次。

### 6.3 风险

- 比 `P3-A` 更容易破坏 locality；
- 对解释性要求更高；
- 更需要 P2 的 queue-depth / position 证据支持。

因此它应该晚于 `P3-A`，而不是早于它。

---

## 7. P3-C：inflight release / pending-drain tuning

### 7.1 什么时候才值得做

只有当 P2 明确显示：

- older head 经常已经不在 `gcss_vlf_issue_queue_` front 问题里；
- 而是转入 `pending_direct_reads_` 后继续卡住；
- 或 response 返回后，pending drain 延迟明显；

才值得做这一类候选。

### 7.2 核心思路

不是直接放大 inflight，也不是乱改 budget，而是：

- 观察 response 返回后一次 drain 最多能拉动多少 pending GCSS 请求；
- 若确实存在 release 迟滞，再做更积极的 pending-drain 策略；
- 仍然尽量不改 contract，只改 response 之后的调度节奏。

### 7.3 为什么优先级较低

当前已有 formal 证据表明：

- `vlf_front_inflight_full` 占 `queued_not_issued` 的比例只有 `0.241%`
- `blocked_edges` 维度也只有 `0.352%`

这更像次因，而不是主因。

---

## 8. 实验组织与推进顺序

### 8.1 推荐顺序

1. `Stage 0`
   - 固定 `formal baseline replay` 作为对照基线
2. `Stage 1`
   - 只做 `P2 observability`
   - 不改变任何 issue / retire 行为
3. `Stage 2`
   - 做 `P3-A bounded older-first / age-fair rescue`
4. `Stage 3`
   - 若 `P3-A` 只能部分改善，再进入 `P3-B line-group aware fairness reorder`
5. `Stage 4`
   - 仅当 P2 明确显示 release/drain 是次主因时，再做 `P3-C inflight tuning`
6. `Stage 5`
   - 只有在前端候选做完仍残留大量无法解释的 `policy_loss`，才重新评估真实 `per_post retire`

### 8.2 每一阶段都必须看的指标

- `retire_global_hol_cycles_total`
- `retire_crosspost_blocked_edges_total`
- `retire_policy_loss_cycles_total`
- `queued_not_issued`
- `vlf_younger_ahead`
- `issued_wait_resp`
- `sim_time_actual_ns`
- `memctrl.req_total`
- `payload_utilization`
- `traffic_amplification`

### 8.3 promotion gate

只有同时满足以下条件，candidate 才能继续推进：

1. 结构正确
   - edge 注册 / ready / commit / drain 不出错
2. 数值正确
   - post 累积结果不异常漂移
3. strict 正确
   - `validation.log` 与主统计仍可对齐
4. 性能正确
   - HOL 真下降
   - 且 `sim_time_actual_ns` 不回归
   - 且 DRAM 行为不显著恶化

---

## 9. 当前推荐的具体执行清单

### Task A：先落 P2

1. 在 `WeightMemorySubsystem` 内部补最小 front-end instrumentation
2. 将新指标接入现有 PE CSV / summary 聚合链路
3. 对 `formal baseline replay` 复跑并出一版 `P2` 结果文档

### Task B：再做 P3-A

1. 先实现更保守的 `issue-stage bounded rescue`
2. 与 formal baseline 做单 candidate A/B
3. 若指标方向正确，再评估是否需要更强的 queue reorder

### Task C：仅在必要时做 P3-B / P3-C

1. `P3-B`
   - 需要 P2 明确证明 queue 排位深度是主矛盾
2. `P3-C`
   - 需要 P2 明确证明 response/release/drain 延迟是可观次因

---

## 10. 一句话收口

下一阶段主线不应再围绕“retire 能不能改”展开，而应围绕“为什么 locality-first 的 GCSS/VLF issue 队列会系统性压住 older head”展开；因此最合理的推进顺序是：

- `P2 observability`
- `P3-A bounded older-first`
- `P3-B fairness reorder`
- `P3-C inflight release`
- `P4 real per-post retire fallback`

其中前两步构成当前真正的主线优化核心。
