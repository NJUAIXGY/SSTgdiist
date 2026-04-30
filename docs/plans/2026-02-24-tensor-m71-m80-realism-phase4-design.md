# Tensor-SI M71-M80 下一大阶段设计（Realism Phase-4）

## 1. 输入与现状（截至 2026-02-24）

- 已完成并通过：`M61-M70`（含顶层 `run_snndl_regression_gate.sh` realism 轨道全 PASS）。
- 当前 readiness 代表值：`score_avg=54.783`、`distance_to_target_avg=30.217`、`readiness_level=L1`（来自 `m66` 报告）。
- 当前系统能力已具备：
  - memory command proxy_v3 统计可见；
  - pipeline/noс/memory/energy/ras/trace 合同化 gate；
  - phase-3 汇总门禁（`m70`）可稳定聚合验收。
- 当前主要短板仍集中在：
  - 评分与底层结构计数器之间的强绑定不足；
  - pipeline 与 memory/noс 的因果归因链路不够硬；
  - trace/compiler 到结构行为的映射仍偏“可跑”，未到“可解释 + 可预测”。

## 2. 阶段目标（M71-M80）

- 目标1：把 readiness 从稳定 `L1` 推进到稳定 `L2`，并具备向 `L3` 过渡的证据。
- 目标2：将“可运行仿真”提升为“可用于架构决策”的仿真。
- 目标3：建立一套可量化的“真实性进度条”，不再只看单分数。

建议阶段硬指标（M80 验收门槛）：
- `capability_score_total_avg >= 68`
- `distance_to_target_avg <= 15`
- `cross_layer attribution` 在基准场景上稳定复现（重复 3 次分类一致率 >= 90%）
- `top-level realism` gate 连续 3 轮 PASS（同配置）

## 3. 差距量化（面向“相对真实可落地 NPU/TPU”）

使用 5 分制成熟度（1=初始代理，5=可用于架构决策）：

| 维度 | 当前 | 目标(M80) | 差距说明 |
|---|---:|---:|---|
| 计算微结构（issue/dispatch/execute/commit） | 2.5 | 3.5 | 有统计但因果约束不够硬 |
| 存储层级（on-chip/L2/HBM 命令态） | 2.5 | 3.5 | 命令可见但仲裁/耦合解释不足 |
| NoC 与 collective 联动 | 2.5 | 3.5 | 有压力趋势，跨层归因仍偏弱 |
| 编译/trace 到硬件行为映射 | 2.0 | 3.5 | trace 可跑，但预测能力弱 |
| 标定与证据闭环 | 2.5 | 3.5 | 有 confidence，但未形成误差闭环 |
| 能耗与 RAS 决策价值 | 2.5 | 3.5 | 可排序，细分部件与策略成本尚浅 |

结论：目前大致处于“工程可回归 + 局部可解释”阶段；距离“相对真实可落地”还差一个中等规模阶段（M71-M80）。

## 4. M71-M80 里程碑设计

| 里程碑 | 主题 | 关键交付 | 通过标准 |
|---|---|---|---|
| M71 | Readiness-计数器一致性契约 | 建立 `readiness -> raw counters` 映射表与校验器 | 每个 readiness 子项都能追溯到 >=1 个底层统计；映射缺失为硬失败 |
| M72 | Pipeline Scoreboard v3 | 增加 scoreboard/hazard 分类（RAW/WAR/WAW/struct）与阶段占比 | 压力场景下 hazard 分布可重复，且与吞吐变化方向一致 |
| M73 | Memory Arbitration v4 | command queue + bank-group arbitration + fairness 指标 | 冲突/并发场景下 latency 分解与公平性指标符合预期单调性 |
| M74 | NoC-Memory 因果联动 | 引入 NoC->memory backpressure causal tags | 能区分 “NoC 先饱和” 与 “memory 先饱和” 两类瓶颈 |
| M75 | Trace/Compiler v3 | trace 增加 tile-residency、resource window、barrier semantics | 同 trace 在不同配置下性能变化可被模型正确排序 |
| M76 | Calibration Loop v3 | 自动拟合脚本（目标: latency/bw/stall mix）+ 偏差报告 | 校准后关键误差项下降 >=30%，并产出可机读 profile |
| M77 | Scale-out v2 | 2D 拓扑 + 分层 collective（intra/inter） | 规模扩展时瓶颈迁移路径可解释且稳定复现 |
| M78 | Energy/Power v4 | core/dma/noc/memory 分部件能耗 + power budget 节流 | 能耗变化与性能退化趋势一致，反例率低于 10% |
| M79 | RAS v4 策略成本模型 | retry/throttle/isolate + 混合策略矩阵 | 同 fault profile 下策略 Pareto 前沿可重复 |
| M80 | Final Realism Gate v4 | phase-4 总报告（score+distance+causal+energy+ras） | 达成本阶段 4 项硬指标且顶层 gate 三连 PASS |

## 5. 执行顺序（降低风险）

- Wave-A（基础可信度）: `M71 -> M72 -> M73`
- Wave-B（跨层因果）: `M74 -> M75 -> M76`
- Wave-C（可决策价值）: `M77 -> M78 -> M79 -> M80`

顺序理由：
- 先把“指标可信度和追溯性”打牢（M71-M73），避免后续全是“分数变动但不可解释”。
- 再做跨层耦合与编译映射（M74-M76），保证模型能回答“为什么变快/变慢”。
- 最后推进规模化、能耗与 RAS 策略（M77-M80），形成可用于架构 tradeoff 的最终产物。

## 6. 两周冲刺计划（可直接开工）

### Sprint-1（建议 5 天）

- D1: 冻结 M71 schema（readiness 子项与 counters 映射文件格式）。
- D2: 实现 `validate_tensor_m71_readiness_counter_mapping.py` 与单测。
- D3: 实现 M72 hazard 统计接线（先 Python summary 与 validator，后 C++ 统计挂载）。
- D4: 增加 M72 gate 与 `run_snndl_regression_gate.sh` 接线。
- D5: 跑 `m71+m72` 冒烟与 top-level 小回归，修复阻塞。

### Sprint-2（建议 5 天）

- D1-D2: 实现 M73 arbitration 指标与合同。
- D3: M73 gate + regression 接线 + 失败码治理。
- D4: 执行 `m71..m73` 组合回归，固定基线。
- D5: 输出阶段报告，确认是否进入 M74。

## 7. 风险与回滚策略

- 风险A：新增统计扰动历史 gate。
  - 策略：所有新功能先 behind capability/profile 开关，默认关闭。
- 风险B：评分改动导致历史曲线断裂。
  - 策略：并行输出 `readiness_v3` 与 `readiness_v4`，过渡期双轨对比。
- 风险C：scale-out 场景耗时过高。
  - 策略：白天 `step-limited`，夜间 full-run；门禁只吃前者，报告附后者。

## 8. 验证命令模板（阶段内固定）

- 单 gate 冒烟：
  - `bash tools/run_tensor_m7X_gate.sh --skip-unit --run-root tmp/tensor_m7X_gate_smoke`
- 多 gate 串行：
  - `for m in 71 72 73; do bash tools/run_tensor_m${m}_gate.sh --skip-unit --run-root tmp/tensor_m${m}_gate_smoke; done`
- 顶层 realism：
  - `SNNDL_GATE_BUILD=0 SNNDL_GATE_TENSOR_TRACK=realism SNNDL_GATE_TENSOR_REALISM_SKIP_UNIT=1 bash tools/run_snndl_regression_gate.sh`

## 9. 进入实现前冻结项

- 冻结1：M71 映射 schema（字段命名、容错策略、硬失败规则）。
- 冻结2：M72 hazard 分类字典（避免后续统计语义漂移）。
- 冻结3：M73 fairness 指标定义（P50/P95 或 Jain 指数二选一并固定）。
- 冻结4：M80 硬阈值（score/distance/gate 连续 PASS）不在中途调整。

