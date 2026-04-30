# Tensor-SI M61-M70 下一大阶段设计（Realism Phase-3）

## 1. 目标与结论

### 1.1 本阶段目标
- 在已完成 `M47-M60` 回归体系基础上，把 Tensor-SI 从“可观测代理模型”推进到“跨层可解释、可校准、可归因”的准真实 NPU/TPU 仿真阶段。
- 目标输出不是单点性能数字，而是：
  - 计算/存储/互连三层统一瓶颈解释；
  - 参数变化引起的趋势可预测；
  - 对真实硬件行为具备可映射的语义锚点。

### 1.2 当前阶段结论（截至 2026-02-24）
- gate 状态：
  - 顶层 realism 轨道 `m47~m60` 已全量接线并 PASS。
  - 关键接线见 `tools/run_snndl_regression_gate.sh`（m56~m60 fail code 40~44 + report_dir 输出）。
- readiness 状态：
  - 典型多场景平均：`capability_score_total_avg=62.264`，`distance_to_target_avg=22.736`，`readiness_level=L1`（见 `m42_readiness_report.json`）。
  - 证据增强场景（M58 evidence_rich）：`score=59.761`，`distance=25.239`，`evidence_factor=0.94`，仍未跨过 L2 门槛。
- 现状判断：
  - 系统已具备“工程可回归”的 realism 框架；
  - 但距离“相对合理真实”的 NPU/TPU 仍差约 **一个完整大阶段（M61-M70）**，核心短板在命令级内存准确性、跨层联动归因、能耗/RAS校准闭环。

---

## 2. 现状深度总结

## 2.1 已落地能力（M47-M60）

### A. 回归与门禁基础
- `m47` 建立了 multi-gate realism 编排与聚合报告。
- `m48~m55` 覆盖 pipeline、memory timing proxy、NoC/collective 压力、energy/fault 的趋势合同。
- `m56~m60` 新增：
  - M56：NoC VC pressure contract（credit/backpressure/noc_budget/inflight）；
  - M57：memory command-lite 可观测（ACT/PRE/RDWR + row service）；
  - M58：evidence-v2 readiness 权重；
  - M59：trace->spec 桥接；
  - M60：energy + RAS phase2 合同。

### B. 关键统计可观测性
- 新增命令级统计（proxy 层）：
  - `tensor_mem_cmd_act_total`
  - `tensor_mem_cmd_pre_total`
  - `tensor_mem_cmd_rdwr_total`
  - `tensor_mem_row_service_cycles_total`
- readiness 已能识别：
  - `missing_mem_cmd_observability`
  - `bank_queue_pressure_hotspot`
  - `single_node_bandwidth_limited_proxy`
  - 等漂移标志。

### C. 证据链能力
- `M52` 有参考 profile 和 confidence；
- `M58` 把“证据强弱”映射到评分折减（`evidence_factor`）；
- `M46` 可做多场景回归/漂移收敛并出报告。

## 2.2 当前可量化结果（最近一次 realism 产物）

- M56：
  - `credit_stall`：baseline `0`，pressure `134546`，relaxed `2754`
  - `noc_budget_stall`：baseline `0`，pressure `135492`，relaxed `0`
- M57：
  - `cmd_pre`：locality `252`，conflict `1023`，parallel `240`
  - `row_service_avg`：locality `17.240`，conflict `27.996`，parallel `20.844`
- M58：
  - `score`: config_only `43.160` -> evidence_rich `59.761`
  - `factor`: `0.740` -> `0.940`
- M59：
  - `program_ops`: `4` -> `20`
  - `program_iters`: `1` -> `4`
- M60：
  - `energy_per_mac`: efficiency `0.002039`，fault `0.007711`，recovery `0.004231`

---

## 3. 与真实 NPU/TPU 差距分析

> 说明：这里“真实”指可用于架构决策/参数探索的工程仿真可信度，不指 cycle-perfect RTL 等价。

## 3.1 差距矩阵（现状 vs 目标）

1. 内存命令级准确性（差距：大）
- 现状：
  - M57 为 command-lite 映射（row_hit/miss/conflict -> ACT/PRE/RDWR 计数）。
  - 能做趋势判别，但仍属代理模型。
- 真实目标：
  - 显式命令时序状态机（bank/bank-group/channel），含时序窗约束；
  - 对队列调度策略差异、并发冲突具备稳定响应。

2. 计算核心微结构（差距：大）
- 现状：
  - program 模式可表达 DMA/GEMM/collective，带 stall 统计。
  - 但 tensor core pipeline 的结构相关冲突、端口争用和 scoreboarding 仍偏简化。
- 真实目标：
  - issue/dispatch/execute/commit 分层；
  - tile residency 与 on-chip buffer 生命周期可追踪；
  - 能解释“同算子不同 schedule”细粒度差异。

3. NoC + collective 跨层耦合（差距：中-大）
- 现状：
  - M56 证明了 VC/backpressure 趋势；
  - 但 NoC 与 memory command 的耦合归因尚弱。
- 真实目标：
  - 可回答“瓶颈来自 VC 压力还是 mem queue/command 约束”；
  - 提供跨层 attribution（compute/memory/noc 占比和主导阶段）。

4. 能耗/RAS 模型可信度（差距：中）
- 现状：
  - M60 采用 proxy energy/ras 指标，排序正确，解释粗粒度。
- 真实目标：
  - 分部件能耗（core/dma/noc/memory）与事件联动；
  - 故障注入与恢复策略可参数化对比，支撑 tradeoff 结论。

5. 编译器/映射链路（差距：中）
- 现状：
  - M59 已有 trace->spec v1；
  - 仍偏“描述执行序列”，不是“约束驱动的编译映射结果”。
- 真实目标：
  - trace v2 含 dependency/resource/schedule metadata；
  - 可重放并验证编译策略对性能与能耗的影响。

6. 标定证据闭环（差距：中）
- 现状：
  - 有 confidence/evidence_factor；
  - 但参考 profile 维度较少，证据粒度不够。
- 真实目标：
  - 多维标定（latency/bw/stall mix/power proxy）；
  - 自动化偏差追踪与阈值治理。

## 3.2 readiness 视角的主要短板
- 多场景报告 top gaps（M42）显示：
  - `scalability` gap 最大；
  - `parallelism` 与 `dataflow` 次之；
  - 表明系统在“跨节点并行 + 数据流精细化 + 扩展行为”方面仍不足。

---

## 4. 下一大阶段设计：M61-M70（Realism Phase-3）

## 4.1 阶段目标
- 把 readiness 从稳定 L1 推进到稳定 L2（均值 >= 65），并把 `distance_to_target_avg` 压缩到 <= 18。
- 建立“跨层瓶颈归因报告”作为强制产物，替代单一得分导向。

## 4.2 里程碑分解

### M61：Memory Command Engine v3（命令状态机）
- 目标：
  - 从 command-lite 升级为 command-stateful（bank/bank-group/channel）。
- 交付：
  - 新参数：timing windows + queue arbitration controls；
  - 新统计：command_queue_depth、cmd_wait_breakdown、conflict_window_hits。
- 验收：
  - 合同验证中，冲突场景对 cmd_wait 与 total latency 的变化与预期一致；
  - 与 M57 指标兼容不破坏旧 gate。

### M62：Cross-Layer Bottleneck Attribution（NoC × Memory）
- 目标：
  - 联合 M56/M61 信号做瓶颈归因。
- 交付：
  - `bottleneck_attribution.json`（compute/memory/noc 比例 + 主因）；
  - readiness 新增 cross-layer flags。
- 验收：
  - 至少 3 组对照场景中 attribution 能稳定区分主导瓶颈。

### M63：Regression Gate Hardening（脚本门禁健壮性）
- 目标：
  - 补齐 `run_snndl_regression_gate.sh` 的脚本级单测。
- 交付：
  - 覆盖 `m56~m60` fail code、report_dir 解析、异常分支。
- 验收：
  - 门禁脚本单测通过，故障注入时 exit code 与错误语义一致。

### M64：Tensor Core Pipeline v2（微结构分层）
- 目标：
  - 构建 issue/dispatch/execute/commit 可观测流水。
- 交付：
  - 新统计：per-stage busy/stall、hazard 类型分解；
  - 新场景：同 workload 不同 schedule 差异可解释。
- 验收：
  - pipeline 压力场景中 stage-level 统计具备单调趋势。

### M65：Trace v2 + Compiler Mapping Contract
- 目标：
  - 把 trace->spec 从“指令清单”升级为“编译结果重放”。
- 交付：
  - trace v2 schema（依赖、资源占用、tile 元信息、collective schedule）。
- 验收：
  - 同一 trace 在不同硬件参数下表现可预测，且约束冲突可检测。

### M66：Readiness v3（解释优先）
- 目标：
  - readiness 从分数驱动升级为“分数 + 解释 + 建议”。
- 交付：
  - `readiness_v3_report.json`：
    - score
    - top bottlenecks
    - suggested parameter interventions（可机读）
- 验收：
  - 对同场景做参数微调时，建议方向与实际改善方向一致率 >= 70%。

### M67：Energy Model v3（分部件）
- 目标：
  - 把 M60 proxy 能耗拆成 core/dma/noc/memory。
- 交付：
  - 新 energy breakdown 统计与 validator。
- 验收：
  - fault/recovery/efficiency 三场景中，各部件贡献变化逻辑自洽且可解释。

### M68：RAS Model v3（策略化恢复）
- 目标：
  - 支持可选恢复策略（重试、降速、隔离）。
- 交付：
  - policy 参数与故障注入矩阵；
  - RAS 成本（性能损失/恢复时间）统一输出。
- 验收：
  - 不同策略在相同 fault profile 下呈现可重复差异。

### M69：Scale-out Realism（多节点）
- 目标：
  - 从单节点 proxy 走向小规模多节点可验证场景。
- 交付：
  - 多节点 collective 场景、跨节点瓶颈归因。
- 验收：
  - scale 提升时能正确识别扩展瓶颈转移。

### M70：Phase-3 Final Gate（综合验收）
- 目标：
  - 形成“相对合理真实”的阶段性结论。
- 验收硬指标：
  - readiness：平均 >= 65（L2）；
  - distance_to_target_avg <= 18；
  - cross-layer attribution 报告可用；
  - realism 总门禁稳定 PASS（含 M61~M70）。

---

## 5. 执行节奏与资源建议

## 5.1 建议顺序（降低风险）
1. Wave-A（基础可信度）：M61 -> M62 -> M63  
2. Wave-B（执行语义）：M64 -> M65 -> M66  
3. Wave-C（工程可决策）：M67 -> M68 -> M69 -> M70

## 5.2 风险与回滚
- 风险1：命令级模型复杂度上升导致回归不稳定  
  - 缓解：默认 `off` + capability profile gated rollout。
- 风险2：readiness 分数抖动影响历史基线  
  - 缓解：并行保留 v2/v3 报告，逐步切换。
- 风险3：多节点场景运行时长增加  
  - 缓解：先做 step-limited regression + nightly full。

---

## 6. 进入实现前的冻结项
- 冻结1：M61 timing 参数命名与默认值。
- 冻结2：M62 attribution schema（字段不可频繁变更）。
- 冻结3：M70 通过阈值（L2 与 distance 目标）作为阶段 exit criteria。

