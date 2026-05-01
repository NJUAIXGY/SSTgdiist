# 主线下一阶段执行指引：从 `P3-C2a` 回到以 Head Burial 为中心的 Offline Anti-Burial 主线

> 日期：2026-03-17  
> 状态：design-only  
> 范围：`snndl` 主线；只讨论 `DRAM-based SNN + GAS + GCSS-GLIDE + STORM + MulticastRouter` 下的后续优化方向  
> 目的：把最近一轮 `closure` 修复、`P3-A/P3-B/P3-C1/P3-C2a` 试验、以及 `seq1` 运行时头部诊断的经验收束成一份可执行的主线指引，避免再次回到错误的 runtime 试错路线。

---

## 0. 一句话结论

当前主线的真实问题不是“runtime 坏了”，而是：

- baseline runtime 已经是稳定可闭环的；
- 当前主损失来自 `offline layout` 与 `locality_first issue + global_inorder retire` 的结构失配；
- 这个失配在运行时表现为 **older head 被 younger-ready edges 深埋**；
- 因此下一阶段的主线不应继续叠加 online reorder，而应回到：
  - **在完全保持 runtime 主契约不变的前提下，围绕 oldest-head burial 重新设计 offline anti-burial scorer / placement。**

---

## 1. 目前已经真正学到的东西

### 1.1 `closure` 与 `HOL` 必须彻底拆开

我们已经验证：

- `closure` 问题的根因是旧 `Drain done policy` 会把 `bg_only` 慢核误判为空闲；
- 当前最小修复已经命中这条根因；
- `drain=5000` 的 closure-fixed baseline 已经能稳定走完：
  - `BeginApply -> issue / retire / drain -> PE_DONE`
  - 且能进入 `START_STEP seq=2`
  - `windows_incomplete=0`

因此，后续所有优化工作都必须建立在 **closure-fixed baseline** 上。  
不能再把“step1 不动”与“主线 HOL 很重”混成一个问题。

### 1.2 当前主矛盾不是 loader / materialization / bank credit

已有 baseline 证据已经说明：

- 不是 loader not ready；
- 不是 materialization fail；
- 不是 response 完全不回来；
- 不是 bank credit 或 downstream busy 主导；
- 也不是 barrier wait 主导。

当前主矛盾是：

- `retire` 顺序来自 edge 注册顺序；
- `issue` 顺序来自 `locality_first` 地址排序；
- `global_inorder retire` 把这两者硬绑定起来；
- 一旦 older head 被 younger-ready edges 埋深，整个窗口就会被强顺序 retire 放大成 HOL。

### 1.3 `P3-A` / `P3-B` / `P3-C2a` 各自教会了我们什么

`P3-A` 告诉我们：

- issue 选择时机确实会影响前端 HOL；
- 但 bounded rescue 更像探针，而不是主线答案；
- 它没有从根上消除 burial。

`P3-B` 告诉我们：

- online reorder 在逻辑上并非完全错误；
- 但它工程上太危险，一旦触碰 queue-build / issue 行为，就很容易把 closure、inflight 形态、queue 几何一起打乱；
- 当前阶段不适合作为主线继续推进。

`P3-C2a` 告诉我们：

- 问题不是 wave-head corruption；
- 真问题是 **中深层 burial 被进一步放大**；
- relaxed fat-tail guard 这一类“广域放宽”会把一些中等长度段搬到更差的位置，最终把 oldest head 深埋到 `global_inorder retire` 难以承受的程度。

### 1.4 最新 `seq1` 头部诊断给了最关键的直接证据

在 `P3-C2a` 的 fresh debug rerun 中：

- `seq1` 刚进入 `BeginApply`，`pe0/core0` 的第一条头部诊断就是：
  - `head_phase=queued_not_issued`
  - `head_qni_reason=vlf_younger_ahead`
  - `head_queue_depth=614`
  - `next_retire=0`
- 在前 `64` 条头部诊断内：
  - `next_retire` 始终不动；
  - `retired` 始终是 `0`；
  - `ready_uncommitted_gcss` 却从 `0` 增长到 `63`；
  - `head_qni_reason` 始终是 `vlf_younger_ahead`。

这条证据链已经足以说明：

- younger edges 一直在 issue / ready；
- oldest head 并不是发不出去，而是退不出去；
- 真正的系统性问题是 **deep HOL burial**。

---

## 2. 哪些事情现在应当明确停止

### 2.1 停止把 online reorder 当作默认主线

后续不再默认推进：

- `P3-B` 式 queue-build reorder；
- 新的 runtime issue rescue 叠加；
- 任何会改变 `prepareGcssVlfIssueQueue_()` / `popNextGcssVlfIssueEntry_()` / `tryRetireEdges_()` 主行为的候选。

除非后续有非常强的反证，否则 runtime 行为路径保持冻结。

### 2.2 停止继续调 `P3-C2a`

`P3-C2a` 现在应视为正式失败方向：

- 它不是“参数还没调对”；
- 它已经在可信口径下给出了 closure fail + deep burial 的直接运行时证据；
- 不值得继续在 relaxed fat-tail guard 上做试探。

### 2.3 停止只看 memory 指标就判断候选优劣

对于当前主问题：

- `memctrl.req_total`
- `payload_utilization`
- `traffic_amplification`

仍然重要，但它们不再是第一门槛。

更前置的门槛必须是：

- `seq1 head_queue_depth`
- `seq1 first-retire latency`
- `next_retire` 在早期窗口中的推进情况

如果 oldest head 仍然深埋，那么即使 memory 指标好看，候选也不应继续推进。

### 2.4 停止一上来就做长 formal rerun

任何新 offline candidate，都不该直接进入长 formal A/B。

必须先过短门槛：

1. artifact 静态检查；
2. `seq1` 头部诊断 gate；
3. 仅在前两项通过后，再进入 formal。

---

## 3. 下一阶段的正确主线

## 3.1 主方向：回到 `P3-C1` 基线，做 head-aware offline anti-burial

下一阶段的推荐起点不是 `P3-C2a`，而是：

- 回到 `P3-C1`
- 在 `P3-C1` 的基础上重新设计下一代 scorer / placement

核心要求：

- **不改 runtime 主闭环**
- **不引入新的 online reorder**
- **只在 generator / artifact 层做改动**

目标不是抽象地“更公平”，而是非常具体地：

1. 降低 `seq1` oldest head 的初始埋深；
2. 缩短 oldest head 的首次 retire 延迟；
3. 在压 burial 的同时，不把 locality 收益换没。

### 3.2 新 scorer 的中心目标必须改变

旧方向更偏向：

- line 填充；
- locality；
- profile/co-access；
- 某些 fat-tail 的弱正则。

下一阶段应把 scorer 的主目标改成：

1. `oldest-head burial` 惩罚
2. `first-retire latency` 代理惩罚
3. `younger_ahead_depth` 尾部惩罚
4. locality 作为约束项，而非唯一主目标

换句话说：

- locality 仍然重要；
- 但它应是护栏，不应再是唯一优化目标。

如果一个 candidate 让 locality 更漂亮，却把 oldest head 埋到 `500+` 深度，那它就不是主线候选。

### 3.3 建议的设计原则

下一阶段 candidate 应满足：

- 保持 `base + pre_rank` 基本 contract 不变；
- 不修改 loader / runtime lookup 主行为；
- 不引入新的索引语义；
- 尽量从现有 `hol_profile_constrained_v2_1` / `P3-C1` 逻辑演进，而不是另起炉灶。

最不应该做的是：

- 广域放宽 fat-tail；
- 为了更高 fill 去牺牲 oldest-head 的位置；
- 同时叠多个新 heuristic，导致 attribution 混乱。

---

## 4. 下一阶段的实验与验收 gate

## 4.1 Gate 0：artifact 静态 gate

在任何 runtime 验证前，先做静态检查。

目标：

- 确认新 candidate 没有破坏语义；
- 先判断它是不是又在大范围搬动中深层 rank。

建议检查项：

1. manifest / meta / idx 自检必须通过；
2. `(pre -> base,len)` diff 必须可解释；
3. 与 `P3-C1` 比较时，不能出现“无约束的大面积 rank 重排”；
4. 必须保留 `profile_path` / `hol_profile_path` 引用链，便于重放分析。

涉及路径：

- generator:
  - `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
- baseline profile:
  - `mainexp/experiments/2026-03-16_closure_fixed_baseline_observe/runs/baseline_formalenv_drain200_profile/20260316-164913/gcssplp_profiles`
- 参考 artifact:
  - `sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_hol_constrained_v2_1_p3c1_formal_j4`

## 4.2 Gate 1：`seq1` 头部诊断 gate

这是下一阶段最关键的短门槛。

固定目标：

- 只看 `pe0/core0`
- 只看 `seq1`
- 只回答 oldest head 是否仍深埋

固定 runtime 入口：

- `sst_dram_si/test_mesh_4x4.py`
- `sst_dram_si/tools/run_mesh_with_time.sh`

固定 runtime 诊断点：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`

必须看的日志：

- `diag-gcss-vlf`
- `diag-gcss-vlf-head`
- `sentinel-step-drain`

建议记录的硬指标：

1. 初始 `head_queue_depth`
2. 前 `64` 条头部诊断内：
   - `next_retire` 是否推进
   - `retired` 是否增长
   - `head_qni_reason` 是否持续为 `vlf_younger_ahead`
3. `head_wait_cycles_max`
4. `ready_uncommitted_gcss` 增长速度

推荐的临时红黄绿判断：

- `red`
  - 初始 `head_queue_depth >= 512`
  - 且前 `64` 条头部诊断里 `next_retire` 始终不动
  - 且 `head_qni_reason` 持续为 `vlf_younger_ahead`
- `yellow`
  - 初始 `head_queue_depth` 落在 `256~511`
  - 或 `next_retire` 虽推进，但非常慢
- `green`
  - 初始 `head_queue_depth < 256`
  - 或 oldest head 能在很早的诊断窗口内开始 retire 推进

这里的阈值不是最终理论边界，而是下一阶段的工程止损线：

- 目的是尽快筛掉明显会重演 `P3-C2a` 的候选；
- 不是替代 formal 的最终结论。

## 4.3 Gate 2：短 closure gate

只有通过 `Gate 1` 的候选，才进入短 closure gate。

目标：

- 在不打开大日志的情况下确认它至少不会重新掉回 `step1` 停滞。

建议口径：

- 仍用 `MESH_MAX_STEPS=2`
- 保持 `locality_first + global_inorder`
- 不叠加其他新策略

需要确认：

- 能走出 `BeginApply`
- 不出现持续性的 `ba=20 ea=0 bs=0 es=0`
- `windows_incomplete` 不应明显恶化

## 4.4 Gate 3：正式 formal gate

只有通过前面所有短 gate，才进入 formal A/B。

formal 阶段的 promotion gate：

1. 结构正确
   - `windows_incomplete = 0`
   - `global_steps_done` 不回退
2. HOL 方向正确
   - `younger_ahead_depth` 下降
   - `older_head_wait` 下降
3. memory 方向不能恶化
   - `memctrl.req_total` 不显著恶化
   - `payload_utilization` 不显著恶化
4. 端到端不回归
   - `sim_time_actual_ns` 至少不明显变差

---

## 5. 下一阶段建议的具体任务顺序

### Task 1：先补 `P3-C1` 的 `seq1` 头部基线

当前我们已经拿到了 `P3-C2a` 的 `seq1` head-burial 证据。  
下一步必须补上 `P3-C1` 同口径数据，回答：

- `P3-C1` 的初始 `head_queue_depth` 是多少？
- `P3-C1` 在前 `64` 条头部诊断里，`next_retire` 推进得多快？
- `P3-C2a` 到底比 `P3-C1` 多埋了多少？

没有这组同口径对照，就无法把后续 scorer 的改进量说清楚。

### Task 2：在 generator 中引入“head-burial first” scorer

只在：

- `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

里做新一轮 scorer 设计，且首轮只做最小单点候选。

建议：

- 不做 sweep；
- 不做多分支 heuristic cascade；
- 只加一组可解释的 burial penalty。

### Task 3：生成 1 个保守 candidate

candidate 应满足：

- 来源是 `P3-C1`；
- 只额外加“head-burial / first-retire”惩罚；
- 不再使用 `P3-C2a` 的 relaxed fat-tail broad relaxation 思路。

### Task 4：先跑 `Gate 0 + Gate 1`

这一步只判断：

- candidate 是否又把 oldest head 埋深；
- 是否存在早期明显的 `next_retire=0` 长停滞。

不过 gate，不进入 formal。

### Task 5：再跑短 closure gate

确认：

- 不会重演 `step1` 长停滞；
- 不会重新把主线拖回 completion 风险。

### Task 6：最后才做 formal A/B

formal 的目的是确认：

- 这个 candidate 不只是“把最坏 red case 从 614 降到 400”；
- 而是真的同时改善了：
  - HOL
  - completion
  - memory
  - end-to-end latency

---

## 6. 决策规则

下一阶段所有 candidate，都按以下规则处理：

### 6.1 只要 runtime 主闭环被碰坏，立即停止

即使 candidate 看起来“也许能压 burial”，只要它重新引入：

- `step1` 长停滞
- `windows_incomplete`
- `PE_DONE` 无法形成闭环

就直接止损。

### 6.2 只要 head-burial 变坏，立即停止

即使 memory 指标改善，只要出现：

- `seq1 head_queue_depth` 恶化
- `next_retire` 更慢
- `head_qni_reason=vlf_younger_ahead` 更持久

就说明它不是主线正确方向。

### 6.3 不能再接受“memory 好看，但 HOL 更差”的候选

这是 `P3-C0/P3-C2a` 已经反复给出的教训。

对于当前主线：

- HOL 是更前置的结构门槛；
- memory 收益只能建立在 HOL 不恶化的前提下。

---

## 7. 本阶段明确不做的事情

1. 不再继续调 `P3-C2a`
2. 不再新增 online reorder 候选
3. 不再叠加新的 bounded rescue / runtime rescue
4. 不讨论 `global_inorder -> per_post retire`
5. 不把“更强 fill / 更强 locality”直接当成正向目标

---

## 8. 最终推荐

下一阶段最正确、最稳的推进方式是：

1. 冻结 runtime 主线；
2. 用 `P3-C1` 补齐 `seq1` head baseline；
3. 围绕 `oldest-head burial` 重做 offline scorer；
4. 先过 `seq1` head gate，再过短 closure gate，最后才进入 formal；
5. 只要 candidate 重演 `deep burial` 或 `step1` 停滞，就立即止损。

这条路线的本质不是“继续试更多技巧”，而是：

- **把优化目标从“更会打包”切换为“更不容易把 oldest head 埋死”。**

只有把这个目标切换完成，主线后续的优化才不会再次偏航。
