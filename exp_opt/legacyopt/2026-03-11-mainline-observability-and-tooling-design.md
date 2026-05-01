# 最小主线优化的观测与工具设计（design-only）

> 日期：2026-03-11
> 状态：design-only
> 目标：为当前最小主线 `DRAM-based SNN + STORM + GAS + GCSS-GLIDE + MulticastRouter` 建立一套 **以“快速定位瓶颈”为第一优先级** 的观测、汇总与分析工具层，避免继续依赖人工翻日志和临时打点推进优化。

---

## 0. 设计结论

当前主线已经具备基础观测链：

- 原始长表：`mesh_stats.csv`
- PE/step 辅助账本：`pe_stage_events_db.csv`、`pe_step_perf_db.csv`
- 聚合摘要：`essential_summary_mesh.json`
- 实验对比：`snapshot/compare.tsv`

但这套链路还不够适合当前 demo 探索阶段的“快定位”需求，主要问题不是没有统计，而是：

1. **统计过多，但因果路径不够清晰**
- 现有 summary 已混入大量非主线机制字段，主线优化时噪声偏大。

2. **有总量，没有“卡在哪一段”的稳定分类**
- 目前仍然很难在一次 run 之后快速回答：
  - 是 `NoC ingress` 慢？
  - 是 `GAS frontend build` 慢？
  - 是 `Apply issue` 被限流？
  - 是 `memory response` 慢？
  - 还是 `retire / barrier` 长尾？

3. **有 per-step，但没有主线路径分解**
- `pe_step_perf_db.csv` 已经很好，但还缺少“按主线阶段切开的阻塞原因账本”。

因此，本设计的核心不是再加一堆统计，而是建立一套 **最小主线路径观测合同**：

- 固定只围绕这条路径组织统计：
  - `STORM ingress -> RX gate -> GAS frontend build -> Apply issue -> memory service -> retire/closure -> step barrier`
- 将观测分成四层：
  - `Always-on counters`
  - `Per-step ledger`
  - `Targeted trace`
  - `Diagnosis tools`
- 将当前 `essential_summary_mesh.json` 与 `snapshot/compare.tsv` 的默认口径重新收敛为 **mainline-first**。

---

## 1. 当前链路与主要盲区

### 1.1 当前已有能力

当前代码库已经具备以下较成熟的统计基础：

- `mesh_stats.csv`
  - 来源：组件级累加器/峰值统计，适合总量类指标。
- `pe_stage_events_db.csv`
  - 来源：PE 级阶段时序标记，适合看 `BeginGather/Apply/Scatter/EndScatter`。
- `pe_step_perf_db.csv`
  - 来源：PE 级 step 账本，已包含 seed/rx/apply/memory frontend 的不少关键字段。
- `essential_summary_mesh.json`
  - 来源：`sst_dram_si/tools/compute_essential_summary_mesh.py`
  - 已能派生：
    - `gas.memctrl_payload_utilization`
    - `gas.memctrl_traffic_amplification`
    - `step.per_step[*]`
    - `slowest_steps_by_pe_total_ns_max`
- `snapshot/compare.tsv`
  - 来源：`memop/tools/snapshot_experiment.py`
  - 已适合做静态 A/B 表格。

### 1.2 当前不够用的点

对“主线优化”来说，真正难的不是看出 run 快慢，而是 **解释快慢差异落在哪一层**。当前主要盲区有：

1. `Apply` 只有结果，没有足够稳定的“阻塞原因拆分”
- 现有统计能看 `payload/lines/bursts/retire_hol`，但很难快速判断慢化到底来自：
  - 无 ready work
  - inflight 限流
  - bank credit
  - 下游 backpressure
  - retire seal / barrier

2. `memory service` 有 request 量，没有闭环时序
- `memctrl.req_total/bytes_est_total` 很好，但仍缺：
  - 响应延迟分布
  - 最慢 step 中 response completion 的拖尾形态

3. `step` 有总时间，没有自动瓶颈分类
- 当前人工仍需结合 `per_step`、`mesh_run.log`、`validation.log`、`mesh_stats.csv` 才能判断“这一步是 RX 挤压、Apply 卡住，还是 retire 长尾”。

4. 现有 `compare.tsv` 对主线优化不够聚焦
- 其中混入了不少实验性字段，容易让真正影响最小主线的核心指标淹没在列海里。

---

## 2. 设计目标与非目标

### 2.1 目标

这套设计只服务一个目标：

- **让一次 run 结束后，能够在 1-2 分钟内定位当前主线的主要瓶颈层级，而不是继续靠人工翻日志。**

更具体地说，要做到：

1. 每次 run 都能稳定回答：
- 主瓶颈更接近：
  - `NoC/RX`
  - `GAS frontend`
  - `Apply issue`
  - `Memory response`
  - `Retire/barrier`

2. 每次 A/B 都能稳定回答：
- 变快/变慢的根因是：
  - request 数变了
  - line clustering 变了
  - response latency 变了
  - retire closure 变了
  - 还是只改善了 host/bookkeeping

3. 默认产物对主线优化友好
- `summary` 和 `compare` 默认只突出主线字段。

### 2.2 非目标

本设计明确不做：

1. 不为失败探索项重新设计统计主口径
- `PRISM/HARBOR/TASS/TIDE-*` 等实验字段不再主导默认视图。

2. 不引入默认重型 trace
- 高体量事件流 trace 仅作为 targeted debug 开关存在。

3. 不把所有推导写进 runtime
- 运行时只负责写最有信息量的原始统计；复杂解释留给离线工具。

---

## 3. 观测模型：只围绕最小主线路径建模

### 3.1 最小主线路径

后续所有观测项只围绕这条路径组织：

1. `STORM` 包到达接收端
2. `RX gate / delivery`
3. 进入 `GAS` 的 frontend 记录与 build
4. `Apply` 构段并发起 issue
5. `memory` 返回 line/data
6. `retire / closure`
7. `step barrier / global completion`

### 3.2 五类必须回答的问题

每个统计都必须至少回答其中一个问题：

1. 进来的压力有多大？
- `RX` 到底收到多少包、多少 remote packet、多少包在 `BeginGather` 之前就堆到了？

2. 压力在 frontend 被组织成了什么？
- 有多少 staged reads、多少 unique lines、多少 granules、多少 payload/line reuse？

3. `Apply` 为什么没有更快 issue？
- 是没有 ready、还是 ready 但发不出去？

4. 数据回来了以后卡在哪里？
- response latency、retire blocking、barrier wait 各占多少？

5. 最慢的是谁？
- 哪个 `seq`、哪个 `PE`、哪一段时间占比最大？

---

## 4. 观测分层设计

### 4.1 Layer A：Always-on totals（低成本、默认开启）

载体：

- `mesh_stats.csv`
- `essential_summary_mesh.json`

用途：

- 做 run 完整性检查
- 做主线总量 A/B
- 做 bottleneck classifier 的输入

原则：

- 只放总量、均值、峰值这类稳定指标
- 不放高频明细

### 4.2 Layer B：Per-step ledger（中成本、默认开启）

载体：

- `pe_step_perf_db.csv`
- `pe_stage_events_db.csv`
- `step.per_step[*]`

用途：

- 定位“最慢 step/PE”
- 把总量差异投影回某几个慢 step

原则：

- 一行代表一个 `PE × seq`
- 保持宽表，但字段必须是主线相关

### 4.3 Layer C：Targeted trace（高成本、按需开启）

载体：

- 新增可选 trace 文件，例如：
  - `pe_pipeline_block_db.csv`
  - `pe_mem_wave_db.csv`

用途：

- 当 Layer A/B 还不足以解释时，针对一个 `PE/seq` 看细节

原则：

- 必须支持 owner filter（单 PE / 单 core / 单 seq）
- 默认关闭

### 4.4 Layer D：Diagnosis tools（离线工具，默认使用）

载体：

- 新增 Python CLI 工具

用途：

- 自动把 Layer A/B 数据翻译成“现在最可能卡在哪”
- 生成主线友好的 compare / hotspot / report

---

## 5. 建议新增的主线统计

以下统计全部按“问题驱动”设计，不做无目的堆砌。

### 5.1 RX / Ingress 侧

#### 目标

回答：

- 当前步到底是被 `NoC ingress` 压住，还是包到了以后在本地才卡住？

#### 建议新增

1. `snn_rx_packets_during_gather_total`
2. `snn_rx_packets_during_apply_total`
3. `snn_rx_packets_during_scatter_total`
- 目的：
  - 区分包主要压在哪个阶段到达。

4. `snn_rx_remote_key_packets_total`
5. `snn_rx_local_key_packets_total`
- 目的：
  - 区分远端网络输入与本地环回输入。

6. `snn_rx_gate_pending_peak`
- 目的：
  - 看 RX gate 是否已经形成主线 choke point。

#### 放置层

- 总量与峰值：`mesh_stats.csv`
- per-step 聚合：`pe_step_perf_db.csv`

#### 实现落点

- [SnnWorkload.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc)
- [MultiCorePE.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc)

### 5.2 GAS Frontend Build 侧

#### 目标

回答：

- 收到的传播压力经过 frontend 后，被组织成了什么形态？

#### 建议新增

1. `gas_frontend_nonempty_windows_total`
2. `gas_frontend_empty_windows_total`
- 目的：
  - 区分“窗口慢”与“其实没活”。

3. `gas_frontend_reads_per_nonempty_window_avg`
4. `gas_frontend_unique_lines_per_nonempty_window_avg`
5. `gas_frontend_granules_per_nonempty_window_avg`
- 目的：
  - 让 window 粒度更可比较，而不是只看 run 总量。

6. `gas_frontend_line_touch_reuse_p50/p95`
- 目的：
  - 当前已有均值比率，但缺稳健分位数。

#### 放置层

- 总量：`mesh_stats.csv`
- 分位/窗口统计：可通过 `pe_step_perf_db.csv` 汇总，不必写超高频 trace

#### 实现落点

- [GatherBufferIF.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc)
- [GasCustomCmd.h](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/gas/GasCustomCmd.h)

### 5.3 Apply Issue 阶段

#### 目标

这是当前最缺的主线统计层。它必须回答：

- `Apply` 慢，是因为没有 work，还是有 work 但发不出去？

#### 建议新增阻塞原因计数

1. `gas_apply_issue_attempt_total`
2. `gas_apply_issue_success_total`

3. `gas_apply_issue_block_no_ready_total`
4. `gas_apply_issue_block_inflight_cap_total`
5. `gas_apply_issue_block_bank_credit_total`
6. `gas_apply_issue_block_downstream_busy_total`
7. `gas_apply_issue_block_retire_guard_total`

#### 建议新增峰值/占比

8. `gas_apply_ready_queue_peak`
9. `gas_apply_ready_queue_nonempty_cycles_total`
10. `gas_apply_issue_success_ratio`

#### 放置层

- 总量/峰值：`mesh_stats.csv`
- per-step 聚合：`pe_step_perf_db.csv`
- 若还不够，再加 debug-only `pe_pipeline_block_db.csv`

#### 实现落点

- [GatherBufferIF.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc)
- [SnnPESubComponent.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc)
- [MultiCorePE.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc)

### 5.4 Memory Response / Completion 侧

#### 目标

回答：

- 后端真的慢，还是只是前面没有把请求组织好？

#### 建议新增

1. `gas_mem_resp_count_total`
2. `gas_mem_resp_latency_ns_sum`
3. `gas_mem_resp_latency_ns_max`
4. `gas_mem_resp_latency_ns_p95_est`

5. `gas_mem_resp_out_of_order_distance_sum`
6. `gas_mem_resp_out_of_order_distance_max`
- 若容易实现：
  - 衡量 response completion 的乱序程度是否在放大 retire 长尾。

#### 放置层

- 总量/最大值：`mesh_stats.csv`
- per-step 聚合：`pe_step_perf_db.csv`

#### 实现落点

- [StdMemEndpoint.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/stdmem/StdMemEndpoint.cc)
- [GatherBufferIF.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc)

### 5.5 Retire / Barrier 侧

#### 目标

回答：

- 数据回来了，为什么 step 还没关掉？

#### 建议新增

1. `gas_retire_ready_queue_peak`
2. `gas_retire_wait_cycles_total`
3. `gas_retire_wait_cycles_due_to_hol_total`
4. `gas_retire_wait_cycles_due_to_barrier_total`
5. `gas_retire_unblock_events_total`

当前已有：

- `gas_retire_global_hol_cycles_total`
- `gas_retire_ready_but_blocked_edges_total`
- `gas_retire_per_post_progress_total`

建议保留，但要把“blocked 的原因”再拆清楚。

#### 放置层

- 总量/峰值：`mesh_stats.csv`
- per-step 聚合：`pe_step_perf_db.csv`

#### 实现落点

- [GatherBufferIF.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc)
- [MultiCorePE.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc)

---

## 6. 派生指标设计

为了让“看数据的人”更快定位，而不是只盯原始计数，建议在
[compute_essential_summary_mesh.py](/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py)
里新增一组 **主线诊断型派生**。

### 6.1 新增 `critical_path` section

建议在 summary 中新增：

- `critical_path.stage`
  - 值域：
    - `rx_ingress`
    - `frontend_build`
    - `apply_issue`
    - `memory_response`
    - `retire_closure`
    - `barrier_wait`

- `critical_path.evidence`
  - 一个小字典，列出触发分类的关键指标。

- `critical_path.confidence`
  - `low/medium/high`

### 6.2 新增 `pipeline` section

描述最小主线路径的压缩比与放大量：

- `pipeline.rx_packets_to_staged_reads_ratio`
- `pipeline.staged_reads_to_granules_ratio`
- `pipeline.granules_to_memctrl_req_ratio`
- `pipeline.payload_bytes_per_rx_packet_avg`
- `pipeline.retire_drag_ratio`
  - 例如：
    - `apply_to_scatter_gap / total_ns`

### 6.3 新增 `imbalance` section

- `imbalance.pe_total_ns_max_over_avg`
- `imbalance.pe_apply_exec_ns_max_over_avg`
- `imbalance.pe_apply_to_scatter_gap_ns_max_over_avg`
- `imbalance.steps_done_range`

这组字段的作用是把“是全局都慢”与“只是极少数慢核拖死”区分开。

---

## 7. 工具层设计

### 7.1 `mesh_doctor.py`

#### 目标

输入一个 run dir，输出：

1. 产物完整性检查
- 是否有：
  - `mesh_stats.csv`
  - `validation.log`
  - `essential_summary_mesh.json`
  - `pe_step_perf_db.csv`

2. 主线完整性检查
- 是否真的跑的是最小主线：
  - `noc_type=multicast_mesh`
  - `GCSS-GLIDE` 口径正确
  - `GAS` 开启

3. 瓶颈分类
- 输出一句话：
  - `Likely bottleneck: apply_issue (high confidence)`

4. 建议下一步动作
- 例如：
  - “建议开启 owner-filtered block trace 看 issue block reason”

#### 设计原则

- 默认读 `essential_summary_mesh.json`
- 读不到时回退 `mesh_stats.csv`
- 不依赖人工 grep 日志

### 7.2 `mesh_compare_mainline.py`

#### 目标

替代当前“列很多但解释性偏弱”的 compare 体验。

输入：

- 两个 run dir，或一个 experiment dir

输出：

- 主线指标小表
- 一段因果解释：
  - “A 相比 B，request 数不变，但 frontend line reuse 提升，apply_exec 降低，retire gap 略降，因此主收益来自 frontend clustering 而非后端 DRAM。”

#### 设计原则

- 默认只看 mainline profile
- 实验字段默认隐藏，除非显式打开 `--experimental`

### 7.3 `mesh_hotspot_report.py`

#### 目标

从 `pe_step_perf_db.csv` 和 `pe_stage_events_db.csv` 自动输出：

- 最慢的 `seq`
- 最慢的 `PE`
- 每个慢点的阶段分解
- 推荐是否要开 targeted trace

### 7.4 `snapshot_experiment.py --profile mainline`

现有 [snapshot_experiment.py](/home/xgy/remote/memop/tools/snapshot_experiment.py) 已经很好，不建议平行造轮子。

建议最小改法：

- 增加 `--profile mainline`
- 让 `compare.tsv` 默认列数收敛到主线优化最常用的 25-35 列

这样既保留原工具，也避免主线分析被实验字段淹没。

---

## 8. 观测配置设计

当前统计开关较多，建议引入统一观测档位，而不是继续堆零散 env。

### 8.1 统一档位

建议增加：

- `MESH_OBS_PROFILE=paper`
- `MESH_OBS_PROFILE=diag_light`
- `MESH_OBS_PROFILE=diag_trace`

语义：

1. `paper`
- 保持现有主线统计
- 保证低扰动

2. `diag_light`
- 开启所有 always-on + per-step ledger
- 这是主线优化的默认档位

3. `diag_trace`
- 在 `diag_light` 基础上，允许：
  - owner PE/core filter
  - seq filter
  - targeted trace

### 8.2 为什么要统一档位

因为当前主线优化最大的问题之一不是“没有统计”，而是：

- 开关分散
- 某些 run 实际没打到统计链
- 直到 summary 出来才发现字段全零

统一档位后，`mesh_doctor.py` 可以直接检查：

- 这次 run 是否达到了诊断口径

---

## 9. 实现建议与文件落点

### 9.1 运行时统计落点

- [GatherBufferIF.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc)
  - 主负责：
    - frontend/build
    - issue block reason
    - retire/closure

- [GasCustomCmd.h](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/gas/GasCustomCmd.h)
  - 只承载需要跨组件上卷的低频窗口级统计
  - 不要无限膨胀成 trace 传输通道

- [StdMemEndpoint.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/stdmem/StdMemEndpoint.cc)
  - 主负责：
    - response latency
    - 回包 completion 侧统计

- [SnnWorkload.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc)
  - 主负责：
    - RX gate
    - 阶段内 packet 分布

- [MultiCorePE.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc)
  - 主负责：
    - PE 聚合
    - `pe_step_perf_db.csv`
    - `pe_stage_events_db.csv`
    - 新增 targeted trace 文件

### 9.2 离线工具落点

- [compute_essential_summary_mesh.py](/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py)
  - 加：
    - `critical_path`
    - `pipeline`
    - `imbalance`

- [snapshot_experiment.py](/home/xgy/remote/memop/tools/snapshot_experiment.py)
  - 加：
    - `--profile mainline`

- 新工具建议放到：
  - `/home/xgy/remote/sst_dram_si/tools/mesh_doctor.py`
  - `/home/xgy/remote/sst_dram_si/tools/mesh_compare_mainline.py`
  - `/home/xgy/remote/sst_dram_si/tools/mesh_hotspot_report.py`

---

## 10. 分阶段落地顺序

### P0：冻结主线观测合同

目标：

- 把“哪些字段是最小主线必须有的”固定下来
- 把实验字段从默认 compare 视图里降噪

产物：

- `mainline` metric profile
- `mesh_doctor.py` 的最小版本

### P1：补齐 Apply / Retire 阻塞原因

目标：

- 让最小主线第一次具备“自动回答卡在哪一层”的能力

优先新增：

- `gas_apply_issue_block_*`
- `gas_retire_wait_*`

### P2：补齐 response / closure 时序

目标：

- 回答“是后端真的慢，还是前端没组织好”

优先新增：

- `gas_mem_resp_latency_*`
- `critical_path` 分类器

### P3：补齐 targeted trace

目标：

- 当 P1/P2 仍不足以解释时，能在单 PE/单 seq 上低成本细看

---

## 11. 验收标准

这套设计实施后，主线优化至少要达到以下验收门槛：

1. 任意主线 run 完成后，`mesh_doctor.py` 能自动给出瓶颈分类与置信度。
2. 任意 A/B，`mesh_compare_mainline.py` 能输出不依赖人工读日志的差异解释。
3. 默认 compare 视图不再被实验字段淹没。
4. 新增统计若未接线成功，`validation.log` 或 doctor 必须显式报错，而不是静默归零。
5. 新增 trace 必须支持 owner/seq 过滤，不能默认全量落盘。

---

## 12. 最终建议

当前 demo 阶段，最值得先做的不是“更多机制”，而是把观测层做成下面这个形态：

1. **主线合同清晰**
- 只围绕 `STORM -> RX -> GAS build -> issue -> memory -> retire -> step`。

2. **主线默认视图干净**
- `summary/compare` 先服务最小主线，而不是服务所有探索项。

3. **统计按层放**
- 总量进 `mesh_stats.csv`
- step 账本进 `pe_step_perf_db.csv`
- 细 trace 按需开启

4. **离线工具负责解释**
- 运行时不要继续塞更多“解释逻辑”
- 解释和分类放到 doctor / compare 工具做

如果只允许先做一件事，建议优先做：

- **P1：Apply / Retire 阻塞原因拆分 + doctor 最小版本**

因为这是当前最能直接缩短“看到变慢”到“知道该改哪一层”时间的一步。
