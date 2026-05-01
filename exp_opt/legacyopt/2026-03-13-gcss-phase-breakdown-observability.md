# GCSS Phase Breakdown Observability 设计与使用说明

日期：2026-03-13  
状态：已实现，默认关闭；正式 baseline 复测完成

## 1. 目标

当前主线已经确认：

- `retire_hol_attribution_core.head_source_mix` 的主导源是 `GCSS`
- 但这还不能回答更关键的问题：
  - `GCSS` 是还没发出去？
  - 还是已经发出但在等返回？
  - 还是已经 ready，只是被更老的 head 卡住？

因此，本轮只做一件事：

- 在 **不改变任何 GAS 语义、issue、retire contract** 的前提下，
- 给 `GCSS` 路径增加更细的 **HOL phase breakdown observability**，
- 让后续优化能有清晰证据链，而不是继续靠猜。

这组统计是纯观测型增强：

- 不改变 `apply_issue_policy`
- 不改变 `retire` 顺序
- 不改变 `acc_update`
- 不改变 validation 结果

## 2. 开关与默认值

为了不污染主线口径，本轮新增了一个**默认关闭**的实验性开关：

- `experimental_gcss_phase_breakdown_enable`

默认值：

- `0`

启用方式：

- `SnnPESubComponent` 参数：
  - `experimental_gcss_phase_breakdown_enable=1`
- 环境变量：
  - `MESH_EXPERIMENTAL_GCSS_PHASE_BREAKDOWN_ENABLE=1`
- `local_run_config.json`：
  - `experimental_gcss_phase_breakdown_enable: true`
- spec / runtime `gas` 配置：
  - `gas.experimental_gcss_phase_breakdown_enable = 1`

当前实现里，只有显式打开时才会维护 GCSS phase 的运行时状态与对应计数；关闭时：

- phase 状态仍存在于结构体定义中，但不会被主动推进
- 相关 counters 全部保持为 `0`
- 主线 baseline 语义与主统计不受影响

## 3. 三个 phase 的严格定义

新增的细分统计只针对 **GCSS edge**。

### 3.1 `queued_not_issued`

定义：

- 某条 edge 已被登记为 `GCSS`
- 但真实的 GCSS 读请求还没有发出去

对应含义：

- 这是 **issue/admission/front-end** 阶段的等待
- 典型原因是：
  - 还在 queue 里
  - 未拿到 issue 机会
  - admission / inflight / budget / scheduler 尚未推进到它

### 3.2 `issued_wait_resp`

定义：

- GCSS 读已经成功 issue
- 但 head edge 还没有 ready
- 说明正在等待 memory response

对应含义：

- 这是 **service latency** 阶段的等待
- 典型原因是：
  - DRAM/memHierarchy 返回慢
  - 下游服务延迟高
  - address/order 导致的内存侧排队

### 3.3 `resp_ready_but_hol`

定义：

- 某些 GCSS edge 已经 ready
- 但它们不能 retire
- 因为更老的全局 head 还没 ready，形成 HOL（head-of-line）阻塞

注意：

- 这不是 “head 自己 ready 了没”
- 而是 “已经 ready 的 GCSS edge，被更老 head 卡住了多少”

对应含义：

- 这是 **retire/global ordering** 阶段的等待
- 如果这个 phase 主导，说明问题更像是：
  - 全局 in-order retire 的假依赖
  - 早 ready 的 GCSS edge 无法越过更老 head

## 4. 运行时产生位置

核心逻辑全部在：

- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`

### 4.1 状态定义

在 `WeightMemorySubsystem.h` 中新增：

- `enum class GcssRetirePhase`
- `EdgeRetireEntry.gcss_phase`
- `ready_uncommitted_gcss_edges_`

其中 `GcssRetirePhase` 包含：

- `None`
- `QueuedNotIssued`
- `IssuedWaitResp`
- `RespReadyButHol`

### 4.2 phase 推进点

phase 只在开关开启时推进。

关键推进函数：

- `registerEdgeRetire_()`
  - GCSS edge 初始标记为 `QueuedNotIssued`
- `setEdgeRetirePendingSrc_()`
  - 当 source 切到 `GCSS` 时，设为 `QueuedNotIssued`
- `setEdgeRetireIssued_()`
  - GCSS 真正发出读请求后，推进到 `IssuedWaitResp`
- `setEdgeRetireReady_()`
  - GCSS 返回并 ready 后，推进到 `RespReadyButHol`
- `tryRetireEdges_()` / `tryRetireEdgesPerPost_()`
  - retire 时递减 `ready_uncommitted_gcss_edges_`
- `updateRetireHolStatsOnTick_()`
  - 每 tick 读取 head 与 ready-queue 状态，累计 phase 统计

### 4.3 issue 时机绑定

GCSS 请求真正 issue 后，在：

- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`

由：

- `tryIssueRead_()`

在 `bcsr_kind == 4` 且 `retire_seq` 有效时调用：

- `setEdgeRetireIssued_()`

这保证 `issued_wait_resp` 反映的是“真实已经发出”的 GCSS 读，而不是逻辑上的排队状态。

## 5. 原始统计项

新增 6 个核心 counters。

### 5.1 按 HOL cycles 计

- `retire_gcss_head_queued_not_issued_cycles_total`
- `retire_gcss_head_issued_wait_resp_cycles_total`
- `retire_gcss_resp_ready_but_hol_cycles_total`

### 5.2 按 blocked edges 计

- `retire_gcss_head_queued_not_issued_blocked_edges_total`
- `retire_gcss_head_issued_wait_resp_blocked_edges_total`
- `retire_gcss_resp_ready_but_hol_blocked_edges_total`

含义区别：

- `*_cycles_total`：这种 phase 导致了多少个 tick 的 HOL
- `*_blocked_edges_total`：这种 phase 下，被卡住的 ready edges 累积有多少

前者看“时间主导”，后者看“队列规模主导”。

### 5.3 这 3 项不是简单互斥分桶

这里有一个非常重要的解释口径：

- `queued_not_issued`
- `issued_wait_resp`

这两项描述的是 **head 这条 GCSS edge 当前处在哪个阶段**，因此二者对同一 tick 是互斥的。

但：

- `resp_ready_but_hol`

描述的是 **队列里是否已经存在 ready 的 GCSS edges 被更老 head 卡住**。

因此它可以与前两项同时成立：

- head 还在 `queued_not_issued`
- 但后面已经有别的 GCSS edge ready 了

或者：

- head 已经 `issued_wait_resp`
- 但后面已有 ready GCSS edge 被 HOL 卡住

所以：

- `queued_not_issued + issued_wait_resp` 可以看作对 `head GCSS HOL cycles` 的拆分
- `resp_ready_but_hol` 则是一个可与前两项重叠的“队列阻塞存在性”指标

## 6. 落盘链路

### 6.1 WeightMemorySubsystem -> RetireObservabilityStats

导出位置：

- `WeightMemorySubsystem::retireObservabilityStats()`

### 6.2 SnnPESubComponent -> MultiCorePE

中转位置：

- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`

具体链路：

- `SnnPESubComponent.cc`
  - 从 `retireObservabilityStats()` 读出 6 个字段
  - 传给：
    - `recordStepRetireStat()`
    - `recordCoreStepRetireStat()`
- `MultiCorePE.cc`
  - 写入：
    - `pe_step_perf_db.csv`
    - `core_step_perf_db.csv`

### 6.3 summary 聚合

聚合脚本：

- `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`

新增 summary 位置：

- `essential_summary_mesh.json`
- 路径：
  - `retire_hol_attribution_core.gcss_phase_mix`

包含字段：

- `hol_cycles_by_phase`
- `blocked_edges_by_phase`
- `dominant_phase_by_hol_cycles`
- `dominant_phase_by_blocked_edges`

## 7. 与已有 `head_source_mix` 的关系

两组统计的职责不同：

### 7.1 `head_source_mix`

回答：

- HOL 的 head source 是谁？
- 是 `dense` / `cache` / `miss` / `bcsr` / `gcss` 哪一类？

### 7.2 `gcss_phase_mix`

只在 `head_source_mix` 已经确认 `GCSS` 主导之后继续回答：

- GCSS 的问题到底卡在：
  - `queued_not_issued`
  - `issued_wait_resp`
  - `resp_ready_but_hol`

因此，两者是严格串联关系：

1. 先看 `head_source_mix`
2. 若确认 `GCSS` 主导，再看 `gcss_phase_mix`

## 8. 如何解读结果

### 8.1 `queued_not_issued` 主导

说明：

- 主要瓶颈在 GCSS issue/admission/front-end

后续优化方向应优先考虑：

- issue queue / admission control
- inflight 资源分配
- 发射前的地址/phase-aware scheduler

### 8.2 `issued_wait_resp` 主导

说明：

- 主要瓶颈在 memory service latency

后续优化方向应优先考虑：

- address locality
- line utilization
- DRAM-side service order
- bank/row 命中和排队延迟

### 8.3 `resp_ready_but_hol` 主导

说明：

- 真正浪费来自 retire/global ordering

后续优化方向应优先考虑：

- 是否存在强全局 HOL
- 是否需要更细粒度但仍确定性的 retire 结构
- 是否要减少“早 ready 但不能 commit”的队列积压

## 9. 本轮正式复测口径

固定 case：

- `mainexp/experiments/2026-03-12_atlas_core_step2_seedonly_ab_v1`
- case:
  - `baseline_step2_seed_only_frac003`

固定主线：

- full-system baseline
- `step=2`
- `seed-only`
- `ramulator2 DDR5`
- `GCSS-GLIDE + STORM + MulticastRouter`

本轮只额外打开：

- `MESH_EXPERIMENTAL_GCSS_PHASE_BREAKDOWN_ENABLE=1`

因此，这轮 run 的正确预期是：

- `validation.log` 仍然必须 `fail=0 warn=0`
- 主统计应与 baseline 一致或仅有统计噪声级差异
- 新增差异只应体现在 phase breakdown 观测结果上

## 10. 当前验证状态

已完成：

- plumbing test
- summary test
- mesh_template config/build plumbing
- `make -j4`
- `make install`

已验证通过：

- `python3 -m unittest sst_dram_si/tools/test_compute_essential_summary_mesh_p0_p1.py sst_dram_si/tools/test_gbi_stepgate_progress_plumbing.py sst_dram_si/mesh_template/test_multicast_noc.py sst_dram_si/mesh_template/test_sram_effective_config_provenance.py`
- `17 tests OK`

中途核对已确认：

- 新 run 的 `effective_config.json` 中：
  - `gas.experimental_gcss_phase_breakdown_enable = 1`
  - `per_core[].gatherbuf.experimental_gcss_phase_breakdown_enable = 1`

正式 baseline run 结果：

- run 目录：
  - `/home/xgy/remote/mainexp/experiments/2026-03-12_atlas_core_step2_seedonly_ab_v1/runs/baseline_step2_seed_only_frac003/20260313-164701`
- 验收：
  - `validation.log: fail=0 warn=0 strict=0`
- 中途核对：
  - `effective_config.json`
    - `gas.experimental_gcss_phase_breakdown_enable = 1`
    - `per_core[].gatherbuf.experimental_gcss_phase_breakdown_enable = 1`

## 11. 本轮结果与解读

### 11.1 主统计完全不变

相对上一条正式 baseline：

- `/home/xgy/remote/mainexp/experiments/2026-03-12_atlas_core_step2_seedonly_ab_v1/runs/baseline_step2_seed_only_frac003/20260313-155517`

本轮关键主统计保持完全一致：

- `sim_time_actual_ns = 581049`
- `memctrl.req_total = 397207`
- `memctrl.bytes_est_total = 25421248`
- `gas.memctrl_payload_utilization = 0.2449300679494571`
- `gas.payload_bytes_per_memctrl_req_avg = 15.675524348765254`
- `gas.memctrl_traffic_amplification = 4.082798034442862`
- `gas.retire_crosspost_blocked_edges_total = 232715266461`

这说明：

- 新开关确实是**纯观测**
- 没有改变主线行为
- 可以安全用于后续诊断实验

### 11.2 `head_source_mix` 结论保持不变

本轮仍然是：

- `dominant_src_by_hol_cycles = gcss`
- `dominant_src_by_blocked_edges = gcss`
- `gcss_hol_cycles_share = 1.0`
- `gcss_blocked_edges_share = 1.0`

因此，上一轮“GCSS 是真正主导源”的结论被再次确认。

### 11.3 `gcss_phase_mix` 的核心结论

本轮新增得到：

- `hol_cycles_by_phase`
  - `queued_not_issued = 143221487`
  - `issued_wait_resp = 26261557`
  - `resp_ready_but_hol = 169483044`
- `blocked_edges_by_phase`
  - `queued_not_issued = 181289839940`
  - `issued_wait_resp = 51673734423`
  - `resp_ready_but_hol = 232963574363`
- `dominant_phase_by_hol_cycles = resp_ready_but_hol`
- `dominant_phase_by_blocked_edges = resp_ready_but_hol`

如果按“head phase 拆分”来读：

- `queued_not_issued / gcss_head_hol = 84.50%`
- `issued_wait_resp / gcss_head_hol = 15.50%`

这说明：

- GCSS head-HOL 的主要来源不是“已经发出但等太久”
- 而是“更老的 GCSS head 还没真正发出去”

也就是说，**issue/admission/front-end** 才是当前更值得优先优化的部分。

### 11.4 `resp_ready_but_hol = 100%` 的含义

还有一个很强的信号：

- `resp_ready_but_hol_cycles_total = gcss_head_hol_cycles_total`
- 即：
  - `169483044 / 169483044 = 1.0`

含义不是“所有问题都来自 retire”

而是：

- 在每一个 GCSS head 被卡住的 tick 上，
- 队列里都已经存在 ready 的 GCSS edges 被更老 head 挡住

这说明当前 GCSS 队列呈现出一种非常典型的结构：

- 老 head 常常还在 `queued_not_issued` 或 `issued_wait_resp`
- 但后面的不少 GCSS edge 已经 ready
- 全局 in-order retire 把这些 ready work 全部压在后面

因此，当前结构可以概括为：

- **主因：老 head 发不出去够快**
- **伴生现象：一旦老 head 卡住，后面 ready 的 GCSS edges 几乎总会形成 HOL 堆积**

### 11.5 top core-window 例子

例如最重的 core-window：

- `pe=2 core=12 seq=2`
- `retire_crosspost_blocked_edges_total = 481814246`
- `retire_head_hol_cycles_gcss_total = 315835`
- `retire_gcss_head_queued_not_issued_cycles_total = 268301`
- `retire_gcss_head_issued_wait_resp_cycles_total = 47534`
- `retire_gcss_resp_ready_but_hol_cycles_total = 315835`

这和全局结论一致：

- `queued_not_issued` 明显大于 `issued_wait_resp`
- `ready_but_hol` 与 `gcss head hol` 等长

### 11.6 对下一轮优化的直接指导

基于这轮证据链，优先级已经很明确：

1. 第一优先：
   - 继续深挖 `GCSS queued_not_issued`
   - 也就是 issue/admission/front-end 为什么没把更老 head 尽快送出去
2. 第二优先：
   - 在不破坏主线的前提下，思考如何减少“老 head 未发出时，后面 ready work 全部白等”的程度
3. 暂时不是第一优先：
   - 单纯去优化 DRAM service latency
   - 因为 `issued_wait_resp` 只占 `15.5%` 的 head-phase HOL

所以，这轮 observability 给出的最硬结论是：

- **当前 GCSS 的第一瓶颈更像 admission / issue 侧，而不是纯 memory service 侧。**
