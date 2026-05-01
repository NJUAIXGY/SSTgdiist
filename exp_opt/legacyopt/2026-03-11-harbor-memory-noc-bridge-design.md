# HARBOR：面向 DRAM-based SNN 主线的 Receiver-Local Memory x NoC Bridge 设计

> 日期：2026-03-11  
> 状态：设计文档（仅设计，不改语义，不落实现）  
> 基线：`full_system_baseline = STORM + GAS + GCSS-GLIDE + MulticastRouter`

## 0. 一句话结论

在当前主线已经证明：

- `STORM` 把前向 spike dissemination 压成了 `pre-centric token`
- `GCSS-GLIDE` 把后向 synapse service 压成了 `pre-major / line-friendly / row-safe` 的 DRAM 访问

之后，下一步最值得引入、也最像体系结构贡献的新增硬件，不应再是：

- 跨 block 共享 raw line
- 跨 controller 重定向 synapse service owner
- 纯控制面 hint / credit 的轻微调参

而应是一个位于 **receiver side**、同时理解 `SpikeKey(pre_global + core_mask)` 与 `GCSS-GLIDE pre-major service` 的片上桥接单元：

- **HARBOR**
- **H**ierarchical **A**ctivation-**R**ow **B**ridge for **O**ff-chip **R**etrieval

它的职责是：

1. 在 `STORM` 的 token 到达接收 PE 后，先不立即膨胀成 `per-core / per-edge`
2. 在 PE 级小 SRAM 中做 `token aggregation + core-mask merge + row/service classification`
3. 以 `GCSS-GLIDE` 的物理顺序组织真实 DRAM service
4. 把返回的 line/weight 以确定性方式 attach 回现有 `GAS retire` 链路

如果这条路线成立，它会成为当前系统主线中最自然的一块 cross-layer glue：

- `DRAM-based SNN chip`
- `GAS` memory backbone
- `GCSS-GLIDE` memory optimization
- `STORM + MulticastRouter` native-multicast NoC
- **`HARBOR` receiver-local memory x NoC bridge**

---

## 1. 为什么需要新的片上硬件，而不是继续做局部 tweak

## 1.1 当前 full-system baseline 已经把问题边界钉死了

根据 `mainexp/experiments/2026-03-08_full_system_baseline_ab_v1` 的正式口径：

- `memory_baseline = Merlin + GCSS-GLIDE`
  - `sim_time_actual_ns = 1086400`
  - `memctrl.req_total = 150110`
  - `gas.payload_bytes_per_memctrl_req_avg = 20.3304`
- `noc_baseline = STORM + GCSS-idx2`
  - `sim_time_actual_ns = 1383670`
  - `memctrl.req_total = 1684046`
  - `gas.payload_bytes_per_memctrl_req_avg = 1.81439`
- `full_system_baseline = STORM + GCSS-GLIDE`
  - `sim_time_actual_ns = 257453`
  - `memctrl.req_total = 150907`
  - `gas.payload_bytes_per_memctrl_req_avg = 20.2477`

这说明：

1. `STORM` 单独存在时，旧 memory path 会把 DRAM 请求粒度彻底拉坏；
2. `GCSS-GLIDE` 已经把 memory side 做到了当前主线最好；
3. `full_system_baseline` 的大优势来自：
   - NoC 路径保留了 multicast/shared dissemination
   - memory 路径保留了 DRAM-friendly service object

因此，系统现在缺的不是“再多一个局部优化”，而是：

- **让 NoC 送来的 `pre token`，在 receiver side 不被过早膨胀，同时又能自然落到 `GCSS-GLIDE` 的 row-safe memory service 对象上。**

## 1.2 历史失败路线已经给出反例

过去失败方案反复暴露出三个问题：

1. **共享粒度做错**
- `PRISM-SEG` 一类路径把 token 级 service 做得太细，导致 request/event 数膨胀。

2. **为了降 req_total 打坏 row locality**
- `SYNLINE`、`CLFIT` 一类路径会让 `memctrl.req_total` 下降，但同时让 `row_hit_rate_total` 崩塌，端到端更慢。

3. **只改 frontend，不改真正后端 granule**
- `TIDE-L / TIDE-BSC-LBM` 证明了：只要真实 `memctrl.req_total / bytes_est_total / row_hit_rate_total` 不变，收益就会止步于 frontend proxy。

所以，新硬件必须同时满足：

- 不跨 controller 迁移 ownership
- 不破坏 `GCSS-GLIDE` 的大地址顺序
- 不把 service 粒度做回 `per-edge`
- 真正改变后端看到的 service object

这正是 HARBOR 的设计出发点。

---

## 2. 公开架构给我们的启发，以及我们的真正差异点

这里给出基于公开资料的高层判断。重点不是“复刻公开方案”，而是抽取它们对 **memory hierarchy / event routing / local hardware service unit** 的共同启发。

## 2.1 公开系统的共同趋势

近年的代表性 neuromorphic / SNN 系统，普遍有三个共识：

1. **事件传播是分层、面向多播的**
- 例如 `Loihi 2` 明确走事件驱动、层级化、可编程的神经形态处理路径。  
  来源：Intel 官方技术简介  
  <https://www.intel.com/content/www/us/en/research/neuromorphic-computing-loihi-2-brief.html>

2. **近核 SRAM 承担状态、索引和热数据**
- `SpiNNaker2` 官方资料明确给出：每个 PE 拥有本地 SRAM，cluster/chip 级还有共享 SRAM 与外部 DRAM。  
  来源：SpiNNaker2 Developer Portal  
  <https://spinnakermanchester.github.io/developerportal/spinnaker2/>

3. **真正昂贵的大容量存储访问，必须被本地层次结构吸收与整形**
- 最近的 SNN accelerator 工作普遍强调要围绕 sparsity / locality / inactive skipping 重新组织 memory service，而不是把所有请求直接摊给统一后端。  
  参考：FireFly-S 摘要页  
  <https://arxiv.org/abs/2507.12486>

## 2.2 我们与这些工作的根本不同

我们的系统不是：

- “尽可能把权重都留在片上 SRAM”

而是：

- **以真实 DRAM-backed synapse storage 为核心前提**

这意味着：

1. 我们不能简单复用 `all-on-chip` 路线；
2. 我们必须显式面对 `64B cacheline` 语义下的 overfetch；
3. 我们的创新空间不在“更大的 SRAM”，而在：
   - **在 DRAM 前面增加一个真正理解 token 与 row/line 语义的本地服务单元**

因此，HARBOR 的定位不是普通 cache，也不是普通 scheduler，而是：

- 一个 **receiver-local synapse service bridge**
- 它把 `STORM` 的事件共享对象与 `GCSS-GLIDE` 的内存共享对象对齐起来

这正是公开工作里没有直接回答的问题。

---

## 3. 设计目标与非目标

## 3.1 设计目标

HARBOR 必须同时满足以下目标：

1. **不改变 GAS 语义**
- 不改变 `orch_.acc_update(post_local, delta)` 的数学结果
- 不引入跨 post 副作用
- 最终 commit 仍通过现有 retire 链路完成

2. **不破坏 DRAM 主线 locality**
- 不跨 controller 域打散地址流
- 不改变 `GCSS-GLIDE` 既有的 row-safe 大顺序

3. **真正改变后端 service object**
- 不再让每个 token 一到就立刻展开成 `per-core / per-edge`
- 而是先保留为 `window-local / PE-local pre service object`

4. **能在 SST 中真实建模**
- 有明确的结构状态
- 有清晰的容量、冲突、端口、队列和 backpressure
- 能增加统计项形成机理证据链

## 3.2 非目标

HARBOR 明确不做：

- 跨 `2x2 block` 的共享 raw line 服务
- 共享 partial sum
- 改动 `WeightMemorySubsystem` 的最终 commit 数学语义
- 把当前主线退回到 token-first 的不受控重排

换句话说，HARBOR 是一个 **PE-local / controller-local** 的新单元，而不是新的全局共享 memory fabric。

---

## 4. HARBOR 的核心思想

HARBOR 的第一原则是：

- **在 receiver PE 内，先保持 `pre token` 的共享语义，再决定如何 materialize 成 memory service。**

今天的主线里：

1. `STORM` 把 `SpikeKey(pre_global + core_mask)` 送到 PE
2. `SnnWorkload::deliverPacket()` 几乎立即把它转回 `expandPreGlobalToWindowEdgesFast_()`
3. `expandPreGlobalToWindowEdgesFast_()` 又把它展开成 `post_local + pre_rank`
4. `WeightMemorySubsystem::prepareGcssVlfIssueQueue_()` 再把这些 edge 重新恢复为地址序列

也就是说，现在系统存在一个明显的中间膨胀：

- `token -> edge flood -> addr rebuild`

HARBOR 要取消的，正是这段不必要的中间膨胀。

它把流程改成：

- `token arrival`
- `PE-local token aggregation`
- `PE-shared row/service wave planning`
- `line-aware DRAM issue`
- `deterministic attach to existing retire chain`

因此，HARBOR 的价值不是又做一层“调度器”，而是：

- **把 STORM 的共享对象延续到 GAS memory path，而不是在进入 receiver 后立刻丢掉。**

---

## 5. 微结构设计

HARBOR 建议作为 `PE-local hardware unit` 挂在接收侧，包含以下五个结构。

## 5.1 TAT：Token Aggregation Table

`TAT` 的 key 是：

- `pre_global`

每个表项记录：

- `window_seq`
- `core_mask_local`：该 PE 内哪些 core 需要这个 `pre`
- `arrival_count`：同一 window 内该 pre 被看到几次
- `stage_eligible`
- `pending_service`

职责：

- 对同一个 window 内重复到达的 `pre token` 做精确合并
- 避免在 `SnnWorkload` 层马上重复展开

这不是 membership cache，而是一个：

- **window-local exact service scoreboard**

## 5.2 PSD：PE-Shared Segment Directory

`PSD` 是 HARBOR 的核心 SRAM sidecar，回答：

- 这个 `pre_global` 在当前 PE 哪些 core 上有 segment
- 每个 core segment 的 `base / len`
- 这些 segment 落在哪些 `line / bank / row-band`

与当前 `dstcore` sidecar 不同，`PSD` 的组织对象是：

- `dstpe + per-core segment descriptor`

也就是说，对同一个 `pre_global`，该 PE 内多个 core 的 weight segment 被编译到同一个 PE-shared values blob 中，只是保留 per-core descriptor。

这让 HARBOR 能在不丢失 core 归属的前提下，先以 PE 为单位做 service。

## 5.3 RWQ：Row Wave Queue

`RWQ` 负责把 TAT 中活跃的 `pre` 组织成：

- `(bank, row)` 或 `row-band` 级别的 service wave

它维护：

- `open_row_tag`
- `candidate_pres`
- `expected_lines`
- `expected_payload_bytes`
- `expected_core_fanout`

仲裁原则：

1. 先守住 `GCSS-GLIDE` 的地址大顺序
2. 只在同 row / 同 band 内做有限度 compaction
3. tie-break 用确定性的 `pre_touch_order`

`RWQ` 不是自由重排器，而是：

- **row-safe admission shaper**

## 5.4 LAB：Line Attach Buffer

`LAB` 是 HARBOR 的 line-MSHR + attach buffer。

每个 line 项记录：

- `line_addr`
- `inflight`
- `waiters`
- `payload_offsets`

职责：

1. 对同一 PE 内多个 core 需要的同一条 line 做精确去重
2. DRAM 返回后，把 line 中多个 weight attach 给对应 core / pre_rank

关键点：

- `LAB` 只在同一 PE、同一 controller 域内共享
- 不跨 PE 传播 raw line

这与 `SYNLINE` 的跨 node service 有根本区别。

## 5.5 DRA：Deterministic Retire Adapter

`DRA` 的作用非常简单：

- 把 HARBOR 解析出的 `(retire_seq, weight)` 回填给现有 `WeightMemorySubsystem`

它不做：

- 提交次序修改
- 数学近似
- 跨 post 合并

最终仍由现有：

- `registerEdgeRetire_()`
- `setEdgeRetireReady_()`
- `tryRetireEdges_()`

完成严格 retire。

因此，HARBOR 新增的是 **service path**，而不是新的 commit 语义。

---

## 6. 数据格式设计：GCSS-GLIDE-PE

HARBOR 不建议替换当前 `GCSS-GLIDE` 主格式，而建议增加一个隔离的新变体：

- `gcss_valueonly_dstpe_harbor_v1`

## 6.1 values 布局

对于每个目标 `PE`：

1. 收集该 PE 内所有 core 对应的边
2. 对每个 `pre_global`：
   - 按 `core_id`
   - 再按该 core 内 `post_local` 升序
   - 组织成多个 segment
3. 把这些 segment 连续写入 PE-shared values blob

这样可以保证：

- 同一个 `pre` 在同一 PE 内多个 core 的数据彼此相邻
- 更容易在同一 line / 少数 line 内被 HARBOR 共享服务

## 6.2 index / sidecar

每个 PE 一套 sidecar：

- `pre_id = mphf(pre_global)`
- `pre_base[pre_id]`
- `pre_seg_off[pre_id]`
- `seg_desc_pool`

每个 `seg_desc` 记录：

- `core_id`
- `seg_base_delta`
- `seg_len`
- `line0`
- `bank_id`
- `row_id`

其中 `line0 / bank / row` 可以直接作为 `RWQ` 的输入，不再运行时重新大量推导。

## 6.3 HARBOR 为什么要用 dstpe，而不是继续 dstcore

因为当前主线最大的浪费之一，是：

- `SpikeKey` 在 PE 层已经告诉我们“这些 core 会一起需要某个 pre”
- 但 `dstcore` 格式让这件事在存储层完全不可见

`dstpe` 变体的价值就在于：

- **让 token 共享对象与 storage 共享对象第一次在同一个粒度上对齐**

这不是简单换 layout，而是让新的硬件单元真正有东西可吃。

---

## 7. 与现有代码的接入边界

HARBOR 的接入应该严格卡在两个安全边界之间：

1. `NoC 到达后、edge materialize 之前`
2. `WeightMemorySubsystem issue 之前、retire 之前`

## 7.1 接收侧入口

第一入口在：

- `SnnWorkload::deliverPacket()`  
  文件：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`

当前主线路径中，`SpikeKey/SpikeTileKey` 在这里被迅速导向：

- `expandPreGlobalToWindowEdgesFast_()`

HARBOR 应在这里新增分支：

- `deliverPacket() -> harbor_rx.enqueue(pre_global, core_mask_local, ts)`

而不是立即展开成 edge。

## 7.2 token 到 edge 的延迟 materialization

第二入口在：

- `expandPreGlobalToWindowEdgesFast_()`  
  文件：`SnnWorkload.cc`

当前它直接做：

- `lookupPostsLocalForPre_()`
- 对每个 `pre_rank`
- `recordEdgeWithPreRank(...)`

HARBOR 开启后，这一步改为：

- 只有当 `RWQ` 选择了该 `pre` 的 service wave 时
- 才调用一个新的 delayed materialization 接口
- 将必要的 `(post_local, pre_rank, retire_seq)` 交给 WMS

也就是说，`expandPreGlobalToWindowEdgesFast_()` 从“立即展开器”变成“按需展开器”。

## 7.3 WMS 接口边界

第三入口在：

- `WeightMemorySubsystem::prepareGcssVlfIssueQueue_()`  
  文件：`WeightMemorySubsystem.cc`

当前它从 `edge collector` 恢复：

- `pre_base + pre_rank -> addr`
- 然后做 `addr` 稳定排序

HARBOR 开启后，应新增：

- `prepareHarborIssueQueue_()`

职责：

1. 接收 HARBOR 已选择好的 PE-local service wave
2. 为其中真正需要 materialize 的 edge 注册 retire seq
3. 用 `PSD` 恢复 `addr`
4. 把多个 core 的请求合并为少量 line-aware issue

## 7.4 绝不碰的边界

以下链路不应被 HARBOR 改动：

- `commitRetireEntry_()`
- `orch_.acc_update(post_local, delta)`
- 最终 strict validation 口径

HARBOR 只能改变：

- 谁在什么时候被 materialize
- 谁在什么时候向 memory 发 line 读

不能改变：

- 数学结果
- 最终 commit 语义

---

## 8. 正确性与语义安全

HARBOR 的安全边界可以概括为三条：

1. **activation exactness**
- 一个 window 内每个真实到达的 `pre token` 仍只会对目标 post 集合生效一次

2. **weight exactness**
- 每条真实存在的 `(pre_global, post_local)` 仍读取相同 weight
- 只是 service 粒度从“立刻 per-edge”变成“先聚合后 attach”

3. **retire exactness**
- 最终 `acc_update(post_local, delta)` 的提交仍由现有 WMS retire 链路决定

因此，HARBOR 不是近似计算，也不是新语义，而是：

- **一种 receiver-local 的执行重表达**

---

## 9. 关键统计与证据链

为了证明 HARBOR 真正起效，需要新增四类统计。

## 9.1 token 聚合收益

- `gas.harbor_rx_tokens_total`
- `gas.harbor_unique_pres_total`
- `gas.harbor_token_merge_elided_total`

证明：

- HARBOR 确实在 receiver side 保留并合并了 token，而不是直接回退到 edge flood。

## 9.2 service wave 与 row-safe 行为

- `gas.harbor_row_waves_total`
- `gas.harbor_wave_pres_avg`
- `gas.harbor_wave_payload_bytes_avg`
- `gas.harbor_wave_cross_row_veto_total`

证明：

- HARBOR 的服务单位已经变成 row-safe wave，而不是自由重排。

## 9.3 line attach 与真实请求压缩

- `gas.harbor_line_attach_waiters_total`
- `gas.harbor_unique_lines_total`
- `gas.harbor_elided_line_reqs_total`
- `gas.harbor_payload_bytes_per_unique_line_avg`

证明：

- HARBOR 不是只在 proxy 上好看，而是真正减少了 line service 数。

## 9.4 主指标闭环

仍以现有主指标为准：

- `sim_time_actual_ns`
- `memhierarchy.memctrl.req_total`
- `memhierarchy.memctrl.bytes_est_total`
- `gas.payload_bytes_per_memctrl_req_avg`
- `ramulator2.row_hit_rate_total`
- `ramulator2.row_conflict_rate_total`

理想现象应是：

1. `memctrl.req_total` 下降
2. `payload_bytes_per_memctrl_req_avg` 上升
3. `row_hit_rate_total` 基本守住当前主线，或仅轻微波动
4. 最终 `sim_time_actual_ns` 改善

如果只看到前端统计改善，而主指标不动，则不能算成功。

---

## 10. 闭环实验计划

HARBOR 的实验必须放在 `mainexp`，并以当前完整系统主线为唯一基线。

## 10.1 case 矩阵

建议最小矩阵：

1. `A = full_system_baseline`
- 当前主线：`STORM + GAS + GCSS-GLIDE + MulticastRouter`

2. `B = harbor_oracle_only`
- 只做 receiver-side 统计与理论 line service 计算
- 不改变运行路径
- 用于证明 HARBOR 的理论可压缩空间

3. `C = harbor_p0_token_hold`
- 启用 `TAT + PSD + delayed materialization`
- 不做激进 row-wave compaction

4. `D = harbor_p1_full`
- 启用 `RWQ + LAB`
- 完整 PE-local service wave

## 10.2 固定口径

- `4x4 bcsr10k`
- `step1`
- `ramulator2_ddr5`
- `apply_issue_policy=order`
- 严格验证必须保持：
  - `validation.log: fail=0`

## 10.3 通过标准

只有同时满足下面三条，HARBOR 才算主线候选：

1. `memctrl.req_total` 明显下降
2. `row_hit_rate_total` 不发生灾难性回退
3. `sim_time_actual_ns` 明显改善

如果只满足 1 而不满足 2，说明重蹈 `SYNLINE/CLFIT` 覆辙；
如果只满足前端统计，说明重蹈 `TIDE-L` 类局部优化覆辙。

---

## 11. 为什么 HARBOR 比历史方案更有论文味道

HARBOR 的创新性不在于：

- “又写了一个调度器”
- “又做了一个 cache”
- “又做了一次 line fusion”

而在于它第一次把三个当前已经独立成立的系统对象，放进了同一个新增硬件单元里：

1. `STORM` 的 `pre token`
2. `GCSS-GLIDE` 的 `pre-major / row-safe` values layout
3. `GAS` 的 strict retire 语义

换句话说，HARBOR 回答的是一个很具体、也很系统的问题：

> 当 NoC 已经把“谁会一起被激活”表达成 `SpikeKey(pre + core_mask)` 之后，我们能否在接收侧新增一个轻量硬件单元，让这些共享 activation 在不破坏 DRAM row locality 的前提下，直接转化为更好的 synapse service？

这不是纯工程 patch，也不是单点 heuristic，而是：

- **一个 DRAM-based SNN 系统中真正的 memory x NoC bridge**

---

## 12. 推荐落地顺序

为控制风险，推荐按以下顺序推进：

1. `P0: Harbor oracle`
- 不改主路径，只统计理论 line / req 节省空间

2. `P1: TAT + PSD`
- 先证明 receiver-local token hold 不会破坏语义

3. `P2: RWQ + LAB`
- 再把真正的 PE-local line service 引入运行时

4. `P3: source-side optional hint`
- 可选地给 `STORM` packet 加 `service-color / row-band hint`
- 但这一步必须建立在 receiver side 已经 work 的前提上

---

## 13. 最终判断

在当前主线下，最有希望成为下一阶段正式协同硬件的，不是：

- block-shared raw-line service
- 跨 PE ownership redirection
- 纯 sender-side credit / pacing

而是：

- **HARBOR：一个 PE-local、receiver-local、token-preserving、row-safe 的 memory x NoC bridge**

它既吸收了公开 SNN 芯片“事件传播 + 本地层次结构”的共性经验，
又没有背离我们最核心的系统定位：

- **DRAM-based SNN chip**

如果后续实验能证明：

- `memctrl.req_total` 真正下降
- `payload_bytes_per_memctrl_req_avg` 真正上升
- `row_hit_rate_total` 基本守住
- `sim_time_actual_ns` 真正改善

那么 HARBOR 将非常有希望成为当前主线中最强的新增架构点。
