# 最小主线观测与工具蓝图（结合 ActiveN 的深度重构版）

> 日期：2026-03-12  
> 状态：design-only  
> 目标：在不盲动优化的前提下，为当前最小主线  
> `DRAM-based SNN + STORM + GAS + GCSS-GLIDE + MulticastRouter`  
> 设计一套 **真正服务“下一步优化决策”** 的观测、诊断与实验工具体系。

---

## 0. 核心结论

当前最小主线最缺的不是新机制，而是：

- **一套围绕关键路径组织的观测合同**
- **一套能自动做瓶颈分类的离线工具**
- **一套把“看到变慢”快速变成“知道该改哪里”的诊断工作流**

结合我们现有主线和 `ActiveN: A Scalable and Flexibly-Programmable Event-Driven Neuromorphic Processor`，最重要的结论是：

1. **主线优化必须从“端到端数据流”看，而不是继续把 NoC / frontend / memory / retire 分别看。**
2. **当前统计链已经有骨架，但还没有“关键路径解释力”。**
3. **最值得先补的不是更多总量，而是 Apply/Response/Retire 三段的因果拆分。**
4. **离线工具层应该成为主角，runtime 只提供稳定、低噪声、可聚合的原始统计。**

因此，后续工作不应再是“再打点一些数”，而应是：

- 固定一条最小主线路径；
- 对这条路径建立阶段账本；
- 用 doctor/compare/hotspot 三类工具自动解释；
- 只有在解释不够时，才进入 targeted trace。

---

## 1. 当前主线需要什么，不需要什么

### 1.1 我们真正要优化的对象

当前最小主线的真实命题不是抽象的“系统变快”，而是：

- **在 STORM 把 spike 送到接收端之后，GAS 如何把这些压力组织成 DRAM-friendly 的 Apply；**
- **在 Apply 发起之后，memory response 和 strict retire 如何共同决定 step closure；**
- **最终每一步到底是卡在 ingress、frontend、issue、response、还是 barrier。**

因此，主线观测必须围绕这一条链建模：

1. `STORM ingress`
2. `RX gate / local delivery`
3. `GAS frontend build`
4. `Apply issue / admission`
5. `memory response / completion`
6. `retire / closure`
7. `step barrier`

### 1.2 当前不应该做的事

这轮设计明确不做：

1. 不以失败探索项为中心设计默认视图
- `PRISM / HARBOR / TASS / TIDE-* / control tweaks` 不再主导默认统计口径。

2. 不引入默认重型 trace
- 默认 run 仍应是低扰动、可常态开启的。

3. 不把“解释逻辑”继续塞到 runtime
- runtime 负责记录事实；
- 解释、分类、A/B 对比应放到离线工具。

---

## 2. ActiveN 对我们的真正启发

这篇文章对我们最有价值的，不是它的实现长相，而是它对“事件驱动系统怎么成立”的拆法。

### 2.1 启发一：不要只看 memory requests，要看“延迟是如何被分散和遮蔽的”

ActiveN 的一个核心观点是：

- SNN 的本质瓶颈不是算力，而是 sparse access；
- 真正关键的是 **把 memory latency 分散到队列、消息、异步执行流里**；
- 因此评估系统时，不能只看总请求数，还要看：
  - outstanding 在哪里堆积；
  - 哪一级队列成为 choke point；
  - latency 有没有被 overlap 掉。

这对我们的直接启发是：

- 当前只看 `memctrl_req_total / bytes_est_total / payload_utilization` 还不够；
- 必须补上：
  - `Apply` 发不出去的原因；
  - `response` 回来的节奏；
  - `retire` 为什么没有及时闭合。

换句话说：

- **当前主线缺的不是 memory 总量统计，而是 latency-hiding 失败的位置统计。**

### 2.2 启发二：事件驱动系统的关键不是“事件多”，而是“事件有优先级、有预算、有队列语义”

ActiveN 明确建模了：

- 事件优先级；
- 消息队列；
- 发消息时的 room check；
- 非抢占 handler 下的死锁规避。

这对我们最重要的启发不是照搬 AM，而是：

- 主线优化不能只问“这一轮有多少活”；
- 还要问“为什么明明有活，却没有被推进”。

所以我们需要的不是抽象 occupancy，而是：

1. `ready but not issued`
2. `issued but waiting first response`
3. `response returned but not retired`
4. `retired but step not closed`

这四类状态，正是当前最小主线最缺的因果分解。

### 2.3 启发三：系统要能回答“当前是 compute-bound 还是 memory-bound”，而不是只报最终 runtime

ActiveN 在评估里非常重视：

- memory bandwidth saturation；
- occupancy；
- compute-bound / memory-bound regime 的切换。

对我们而言，等价的问题不是“core 利用率”，而是：

- 当前 run 是：
  - `RX/ingress-bound`
  - `frontend-build-bound`
  - `apply-issue-bound`
  - `memory-response-bound`
  - `retire/barrier-bound`

这其实就是我们应该做的 **critical-path classifier**。

### 2.4 启发四：先建立稳定 contract，再谈扩展

ActiveN 的路径非常清楚：

- 先把 dataflow contract 固定；
- 再围绕这个 contract 去扩规模、扩核数、扩 memory bandwidth。

对我们最重要的提醒是：

- 在 demo 主线还没完全收稳前，不应该继续盲目做机制探索；
- 应先把：
  - 运行时统计合同；
  - summary 合同；
  - compare 合同；
  - diagnose 合同
  固定下来。

---

## 3. 结合当前代码库，现状其实比想象中更好

当前并不是“没有观测能力”，而是“观测能力还没收口成主线工具链”。

### 3.1 已经存在的关键基础

代码库已经具备：

1. `mesh_stats.csv`
- 有大量组件级计数器；
- `GatherBufferIF.cc` 已有 frontend / line / overfetch / cmd-cost / inflight 等统计；
- `MultiCorePE.cc` 已聚合 GAS / retire / latency 等不少指标。

2. `pe_stage_events_db.csv`
- 已提供：
  - `BeginGather`
  - `BeginApply`
  - `EndApply`
  - `BeginScatter`
  - `EndScatter`
- 并且 `compute_essential_summary_mesh.py` 已派生：
  - `apply_exec_ns`
  - `apply_to_scatter_gap_ns`

3. `pe_step_perf_db.csv`
- 当前已经聚合了：
  - `seed_*`
  - `rx_*`
  - `rx_packets_before_bg_total`
  - `rx_gate_*`
  - `frontend_*`
  - `unique/covered/overfetch`
  - `payload/bursts`
  - `apply_bank_credit_effective`
  - `cmd_cost_veto_*`
  - `acc_updates/posts_touched/scatter_spikes`

4. `compute_essential_summary_mesh.py`
- 已能形成：
  - `gas.*`
  - `step.per_step[*]`
  - `slowest_steps_by_pe_total_ns_max`
  - `gas_memctrl_payload_utilization`
  - `gas_memctrl_traffic_amplification`

5. `snapshot_experiment.py`
- 已是一个很好的快照基座；
- 只是默认列过多且混入太多探索字段。

### 3.2 现状的根本问题

问题不是“没有数据”，而是：

1. **关键路径还没有被显式建模**
- summary 里有很多字段，但默认没有告诉你“当前最可能卡在哪一层”。

2. **Apply/Response/Retire 的因果链断着**
- 我们知道 `apply_ns` 慢；
- 但还不能稳定回答：
  - 没 ready？
  - 有 ready 发不出去？
  - 发出去了但 response 慢？
  - response 回来了但 retire 卡住？

3. **默认 compare 视图太宽，不适合 demo 主线决策**
- 当前 `compare.tsv` 适合归档；
- 不适合“5 分钟内判断下一轮该改哪一层”。

---

## 4. 新的观测模型：从“统计集合”改成“关键路径账本”

后续所有统计都只服务一个目标：

- **让一次 run 结束后，在 1-2 分钟内完成瓶颈定位，并指导下一步实验。**

### 4.1 关键路径账本

定义一条固定路径：

1. `Ingress pressure`
2. `RX acceptance`
3. `Frontend shaping`
4. `Issue admission`
5. `Response service`
6. `Retire closure`
7. `Barrier completion`

每一层都必须同时回答两个问题：

1. 量有多大？
2. 阻塞为什么发生？

### 4.2 诊断输出必须回答的五个问题

每次 run 至少要能自动回答：

1. 当前主要压力来自哪里？
- 网络输入多，还是本地 frontend build 慢？

2. frontend 把输入组织成了什么？
- line reuse 是改善了还是退化了？

3. Apply 为什么没继续前进？
- 无 ready 还是有 ready 发不出去？

4. 数据回来后为什么 step 还没关？
- response 拖尾还是 retire / barrier 拖尾？

5. 是大家都慢，还是少数 PE/seq 拖死？
- 即 imbalance 问题。

---

## 5. 最该先补的统计，不是最多的统计

下面不是“所有可能想加的统计”，而是最值得先做的一组。

## 5.1 P0 必补：Apply issue 阻塞原因

这是当前最值钱的一层。

### 目标

把：

- “Apply 慢”

拆成：

- “没有 ready”
- “有 ready，但 inflight 满”
- “有 ready，但 bank credit / downstream 限住”
- “ready 了，但 retire guard 卡住”

### 建议新增

放入 `GasStatEvent` 和 `pe_step_perf_db.csv`：

- `gas_apply_issue_attempt_total`
- `gas_apply_issue_success_total`
- `gas_apply_issue_block_no_ready_total`
- `gas_apply_issue_block_inflight_cap_total`
- `gas_apply_issue_block_bank_credit_total`
- `gas_apply_issue_block_downstream_busy_total`
- `gas_apply_issue_block_retire_guard_total`
- `gas_apply_ready_queue_peak`
- `gas_apply_ready_queue_nonempty_cycles_total`

### 为什么最值得先做

因为这会第一次让我们能回答：

- 当前应该去改 frontend clustering，
- 还是去改 admission / credit / outstanding，
- 还是根本不该碰 Apply，而该去看 response / retire。

## 5.2 P0 必补：Response 闭环时序

当前已经有：

- `memctrl_req_total`
- `bytes_est_total`
- `mem_read_latency_cycles` 直方图统计

但 summary 并没有把它们变成主线可读指标。

### 建议新增

优先在 summary + per-step 中补：

- `gas_mem_resp_count_total`
- `gas_mem_resp_latency_ns_avg`
- `gas_mem_resp_latency_ns_p95`
- `gas_mem_resp_latency_ns_max`
- `gas_mem_resp_out_of_order_distance_avg`
- `gas_mem_resp_out_of_order_distance_max`

以及四个特别关键的 landmark：

- `apply_first_issue_delay_ns`
- `apply_first_down_resp_delay_ns`
- `apply_first_granule_done_delay_ns`
- `apply_first_up_resp_delay_ns`

这几个变量在 `GatherBufferIF.cc` 内部其实已经存在，只是还停留在 debug/progress 输出层。

### 这组统计解决什么问题

它能回答：

- Apply 慢，是因为 issue 慢，还是 issue 后第一波 response 太晚；
- granule completion 是不是拖尾；
- upstream ready 是否被 downstream completion 明显拉长。

## 5.3 P0 必补：Retire / Barrier 拖尾原因

当前有：

- `gas_retire_global_hol_cycles_total`
- `gas_retire_ready_but_blocked_edges_total`

但这还不够。

### 建议新增

- `gas_retire_wait_cycles_total`
- `gas_retire_wait_cycles_due_to_hol_total`
- `gas_retire_wait_cycles_due_to_barrier_total`
- `gas_retire_wait_cycles_due_to_not_ready_total`
- `gas_retire_ready_queue_peak`
- `gas_retire_unblock_events_total`
- `step_barrier_wait_ns`

### 为什么重要

当前很多“Apply 看起来做完了但 step 没结束”的情况，实际上很可能来自：

- response completion 乱序；
- strict retire seal；
- barrier drain。

如果这层拆不开，后续优化仍然会高概率误判。

## 5.4 P1 建议：RX ingress 的阶段分布

当前 `pe_step_perf_db.csv` 已有：

- `rx_packets_total`
- `rx_local_packets_total`
- `rx_remote_packets_total`
- `rx_packets_before_bg_total`
- `rx_gate_*`

这已经很有价值。

但为了更好地区分 “网络先堵” vs “本地后堵”，建议再补：

- `snn_rx_packets_during_gather_total`
- `snn_rx_packets_during_apply_total`
- `snn_rx_packets_during_scatter_total`
- `snn_rx_gate_pending_peak`

这样可以更清楚地知道：

- 包到底是在 BeginGather 前堆住，还是在 Apply / Scatter 期间持续灌入造成 closure 拖尾。

## 5.5 P1 建议：Frontend window 形态分位数

当前已有：

- `frontend_staged_reads`
- `frontend_staged_line_touches`
- `frontend_granules_built`
- `unique_line_count`
- `covered_line_count`

下一步更值得补的是 **分布**，而不是更多均值：

- `gas_frontend_nonempty_windows_total`
- `gas_frontend_empty_windows_total`
- `gas_frontend_reads_per_nonempty_window_avg`
- `gas_frontend_unique_lines_per_nonempty_window_avg`
- `gas_frontend_granules_per_nonempty_window_avg`
- `gas_frontend_line_touch_reuse_p50`
- `gas_frontend_line_touch_reuse_p95`

原因很简单：

- 主线 demo 阶段常常不是均值问题，而是少数极差窗口拖慢整体。

---

## 6. 我们真正需要的不是新 summary，而是新的“解释层”

`compute_essential_summary_mesh.py` 下一步最值得做的，不是再堆派生式，而是新增三个 section。

## 6.1 `critical_path`

输出：

- `critical_path.stage`
- `critical_path.confidence`
- `critical_path.evidence`

值域建议固定为：

- `rx_ingress`
- `frontend_build`
- `apply_issue`
- `memory_response`
- `retire_closure`
- `barrier_wait`

### 作用

这是 doctor 和 compare 的统一锚点。

如果这个 section 做不出来，后面所有工具都会变成“看起来很多数，但仍靠人工解释”。

## 6.2 `pipeline`

记录关键路径上的压缩比和放大量：

- `pipeline.rx_packets_to_staged_reads_ratio`
- `pipeline.staged_reads_to_granules_ratio`
- `pipeline.granules_to_memctrl_req_ratio`
- `pipeline.payload_bytes_per_rx_packet_avg`
- `pipeline.retire_drag_ratio`
- `pipeline.first_issue_to_first_resp_ratio`

### 作用

它不直接告诉你“哪层慢”，但能告诉你：

- 压力在路径上是被压缩了、放大了、还是只是平移了。

## 6.3 `imbalance`

建议新增：

- `imbalance.pe_total_ns_max_over_avg`
- `imbalance.pe_apply_exec_ns_max_over_avg`
- `imbalance.pe_apply_to_scatter_gap_ns_max_over_avg`
- `imbalance.steps_done_range`

### 作用

它用来区分：

- “系统整体都慢”
- “其实只是少数 PE / seq 拖慢”

这个区分对主线优化很重要，因为后者更适合先做 hotspot / long-tail 诊断，而不是全局机制改动。

---

## 7. 工具层必须变成默认入口

### 7.1 `mesh_doctor.py`

这是第一优先级工具。

### 输入

- 一个 run dir

### 输出

1. 产物完整性检查
- 是否有：
  - `mesh_stats.csv`
  - `essential_summary_mesh.json`
  - `pe_stage_events_db.csv`
  - `pe_step_perf_db.csv`
  - `validation.log`

2. 主线口径检查
- 是否真的是：
  - 最小主线 backend
  - `GAS` mode
  - 预期 `GCSS-GLIDE` 口径
  - 预期 `MulticastRouter / STORM` 口径

3. 瓶颈分类
- 输出一句：
  - `Likely bottleneck: memory_response (medium confidence)`

4. 下一步建议
- 例如：
  - `建议打开 owner-filtered response trace`
  - `建议先看 seq=37 的 apply_issue block reason`

### 设计原则

- 默认读 `essential_summary_mesh.json`
- 缺失时回退 `mesh_stats.csv + pe_step_perf_db.csv`
- 缺字段不静默归零，要显式提示“诊断不可信”

### 价值

这会把一次 run 的人工分析时间从“翻多个文件”压缩成“先看一句诊断，再决定是否深入”。

### 7.2 `mesh_compare_mainline.py`

当前 `snapshot_experiment.py` 很适合继续保留，但必须加一个面向主线的解释层。

### 输入

- 两个 run dir，或一个 experiment dir

### 输出

1. 主线指标小表
2. 差异解释
- 例如：
  - request 数没变；
  - frontend reuse 提升；
  - first response 变早；
  - retire drag 略降；
  - 因此主收益更像 frontend shaping，而不是 memory latency 本身改善。

### 设计原则

- 默认 `--profile mainline`
- 实验字段默认隐藏
- 只在 `--experimental` 时展开探索项

### 7.3 `mesh_hotspot_report.py`

这个工具应该专门处理 long-tail：

输入：

- `pe_step_perf_db.csv`
- `pe_stage_events_db.csv`

输出：

- 最慢 `seq`
- 最慢 `PE`
- 每个慢点的阶段分解
- 是否建议开启 trace

### 7.4 `snapshot_experiment.py --profile mainline`

不建议重造快照轮子。

最好的做法是：

- 在 [memop/tools/snapshot_experiment.py] 下新增 `--profile mainline`
- 把默认 compare 列收敛到 25-35 列

这样：

- 老实验不受影响；
- 主线分析体验显著改善；
- 不会分裂工具链。

---

## 8. 新的运行时统计合同应该怎么组织

### 8.1 四层模型

#### Layer A：Always-on totals

载体：

- `mesh_stats.csv`
- `essential_summary_mesh.json`

职责：

- 总量
- 峰值
- 常规派生
- doctor 输入

#### Layer B：Per-step ledger

载体：

- `pe_step_perf_db.csv`
- `pe_stage_events_db.csv`

职责：

- 最慢 step / PE 定位
- 阶段分解
- bottleneck classifier 证据

#### Layer C：Targeted trace

建议新增：

- `pe_pipeline_block_db.csv`
- `pe_mem_wave_db.csv`

职责：

- 当 Layer A/B 不足以解释时，针对单 PE / 单 seq 细看。

#### Layer D：Diagnosis tools

载体：

- `mesh_doctor.py`
- `mesh_compare_mainline.py`
- `mesh_hotspot_report.py`

职责：

- 自动解释
- 聚焦主线
- 给下一步动作建议

### 8.2 统一观测档位

建议引入：

- `MESH_OBS_PROFILE=paper`
- `MESH_OBS_PROFILE=diag_light`
- `MESH_OBS_PROFILE=diag_trace`

语义：

1. `paper`
- 最低扰动；
- 只保证论文主结果口径。

2. `diag_light`
- 主线优化默认档；
- 开启总量 + per-step ledger。

3. `diag_trace`
- 在 `diag_light` 基础上允许 owner / seq 过滤 trace。

### 8.3 为什么这个档位很重要

因为当前一个真实问题是：

- run 结束才发现某些统计没接上；
- 然后这次 run 对诊断几乎没有价值。

统一 profile 后，doctor 和 validator 就可以显式检查：

- 这次 run 是否达到了诊断合同。

---

## 9. 结合代码落点，最合理的接线方案

### 9.1 `GatherBufferIF.cc`

这里是第一主战场。

适合新增：

- Apply issue block reason
- ready queue / nonempty cycles
- response landmark
- retire wait breakdown

原因：

- 这里最靠近：
  - build
  - issue
  - response
  - closure

### 9.2 `api/IGasStageSink.h` 与 `GasCustomCmd.h`

建议扩 `GasStatEvent`，但只承载：

- 低频、窗口级、强解释力统计

不应把它变成高频 trace 通道。

### 9.3 `StdMemEndpoint.cc`

这里最适合补：

- response latency
- response completion 节奏
- 可选的乱序距离统计

### 9.4 `MultiCorePE.cc`

这里负责把 runtime 事实沉淀成：

- `mesh_stats.csv`
- `pe_step_perf_db.csv`
- `pe_stage_events_db.csv`

建议继续把它作为：

- step 聚合中心；
- hotspot trace 落盘中心；
- doctor 友好的账本出口。

### 9.5 `compute_essential_summary_mesh.py`

最适合新增：

- `critical_path`
- `pipeline`
- `imbalance`

并把已有 `step.per_step[*]` 继续作为：

- doctor / hotspot 的直接输入。

### 9.6 `snapshot_experiment.py`

最适合新增：

- `--profile mainline`

而不是分裂成另一套快照脚本。

---

## 10. 分阶段实施顺序

### P0：先让系统能回答“卡在哪”

这是最重要的一步。

#### 交付

1. `gas_apply_issue_block_*`
2. `gas_mem_resp_latency_*`
3. `gas_retire_wait_*`
4. `critical_path`
5. `mesh_doctor.py` 最小版本

#### 验收标准

- 任意主线 run 结束后，doctor 能给出：
  - 一个 stage
  - 一个 confidence
  - 两三条 evidence

### P1：再让系统能回答“为什么 A 比 B 快”

#### 交付

1. `pipeline`
2. `imbalance`
3. `mesh_compare_mainline.py`
4. `snapshot_experiment.py --profile mainline`

#### 验收标准

- 任意 A/B，不依赖人工翻日志，也能得到一段差异解释。

### P2：最后补 targeted trace

#### 交付

1. `pe_pipeline_block_db.csv`
2. `pe_mem_wave_db.csv`
3. owner / seq filter
4. `mesh_hotspot_report.py`

#### 验收标准

- 当 doctor 给出中低置信度时，能低成本进入单 PE / 单 seq 深挖。

---

## 11. 一个更激进但更正确的建议

相比“给所有方向都加统计”，更建议你们把默认主线视图收得更狠一些。

### 建议默认只保留三类字段

1. **关键路径字段**
- RX / frontend / issue / response / retire / barrier

2. **memory 主证据**
- request
- bytes
- payload utilization
- line reuse
- latency

3. **不平衡字段**
- slowest step
- max/avg
- long-tail

### 不建议继续放进默认视图的东西

- 已经失败或边缘化探索项的专属字段
- 需要额外前提才能解释的实验统计
- 没有下一步动作指向的“有趣数字”

因为 demo 阶段最怕的不是信息不够，而是：

- **真正关键的 8 个数字被 80 个次要字段淹没。**

---

## 12. 最终建议

如果只允许现在先做一件事，我建议不是去改机制，而是：

- **把 Apply/Response/Retire 的因果链补完整，并做出 doctor 最小版本。**

原因很简单：

1. 这会立刻提升主线优化效率；
2. 它最符合当前 demo 阶段的需求；
3. 它直接借鉴了 ActiveN 最有价值的思想：
- 不只看总吞吐；
- 要看延迟是在哪里没有被遮蔽；
- 要看队列、阶段、优先级和 closure 是如何共同决定性能的。

因此，当前最合理的工作顺序应该是：

1. 固定主线观测合同；
2. 优先补 Apply / Response / Retire 诊断；
3. 做 doctor / compare 的主线入口；
4. 再决定下一步该动 frontend、issue、memory 还是 barrier。

这会比继续盲试优化，更快把主线从 demo 推向可解释、可收敛、可写论文的状态。
