# Tensor-SI M111-M120 下一大阶段设计（Realism Phase-8: Silicon-Anchored Decision Grade）

## 1. 输入与现状（截至 2026-02-24）

### 1.1 已完成基线
- 顶层 `realism` 轨道已从 `M47` 连续扩展到 `M110`，并完成全链路验收。
- 最新总闸结果：`tools/run_snndl_regression_gate.sh` 返回 `0`，日志 `[gate] PASS`。
- 最新 phase 聚合报告：
  - `sst_workloads/tensor_si/outputs/tensor_mesh_m110_gate/gate_20260224-164914/m110_phase7_report.json`
  - 关键字段：`status=pass`、`gate_count=9`、`pass_count=9`、`fail_count=0`。

### 1.2 当前可量化状态
- M101 readiness 关键信号（来自 `validation.log`）：
  - `score config_only=55.794`
  - `score evidence_rich=70.856`
  - `evidence_factor` 已能区分证据强弱（unverified/high）。
- 当前体系强项：
  - gate/validator/aggregate/顶层接线模式稳定。
  - phase 报告结构统一（schema + gate_results + failures）。
- 当前体系短板：
  - 指标仍以“合同趋势正确”为主，距离“可用于真实 NPU/TPU 架构决策”的可信度仍有差距。

## 2. 与“相对真实 NPU/TPU”差距（深度量化）

> 评分定义：1=代理原型，3=工程可回归，5=可用于架构决策（decision-grade）

| 维度 | 当前估计 | 目标（M120） | 主要差距 |
|---|---:|---:|---|
| 计算微结构语义（issue/scoreboard/resource） | 3.0 | 3.8 | 结构相关冲突与吞吐退化的因果链还不够硬 |
| 存储层级真实性（SMEM/L2/HBM + 命令态） | 3.1 | 3.9 | on-chip/off-chip 迁移与 bank-group 行为解释不足 |
| 编译映射可解释性（trace->行为->结果） | 2.9 | 3.8 | 能跑但难以“预测跨配置排序” |
| Scale-out/collective 真实性 | 3.0 | 3.8 | ring/tree/hybrid 策略边界与拥塞迁移还不稳 |
| 能耗-热-可靠性耦合 | 3.0 | 3.7 | 有 proxy 指标，但缺少动态节流与失效成本闭环 |
| 标定闭环（硬件锚点） | 2.8 | 3.8 | 缺少“多目标误差预算 + 自动回归”机制 |

结论：当前处于“稳定可回归（regression-grade）”，下一阶段需推进到“可决策（decision-grade）”。

## 3. Phase-8 总体目标（M111-M120）

### 3.1 阶段目标
- 从“趋势合同正确”推进到“跨配置可预测 + 可归因 + 可标定”。
- 把 M111-M120 作为第一段“硅锚定（silicon-anchored）真实性”阶段。

### 3.2 阶段硬验收门（M120 Exit Criteria）
1. 顶层 realism 总闸在固定配置下连续 3 轮 PASS（`m47..m120`）。
2. `phase8` 聚合报告 `gate_count=9` 且 `fail_count=0`（M111-M119 全通过）。
3. readiness 稳定区间达到：
   - `score_avg >= 72`
   - `distance_to_target_avg <= 12`
4. 标定闭环满足多目标误差预算：
   - latency/bandwidth/power 三目标加权误差 `<= 15%`。
5. 至少一组 scale-out 场景中，collective 算法切换边界与拥塞迁移结论可复现（重复 3 次一致率 >= 90%）。

## 4. M111-M120 里程碑设计（一次性可落地）

### M111：Readiness v4（Silicon Anchor Contract）
- 目标：建立 readiness 子项到“硬件锚点计数器”的强绑定。
- 交付：
  - `tools/run_tensor_m111_gate.sh`
  - `sst_workloads/tensor_si/tools/validate_tensor_m111_readiness_anchor_contract.py`
  - `tools/specs/tensor_m111_readiness_anchor_*.json`
- 验收：readiness 每个核心子项至少绑定 1 个原始计数器，缺失即 fail。

### M112：Pipeline Scoreboard v5（结构冲突因果化）
- 目标：把 hazard 从“统计存在”升级为“吞吐退化归因”。
- 交付：
  - `tools/run_tensor_m112_gate.sh`
  - `validate_tensor_m112_pipeline_scoreboard_v5_contract.py`
- 验收：压力场景下 RAW/WAR/WAW/structural 分布与吞吐下降方向一致。

### M113：Memory Hierarchy v5（On-chip/Off-chip 统一）
- 目标：区分 SMEM/L2/HBM 路径，形成可解释迁移。
- 交付：
  - `tools/run_tensor_m113_gate.sh`
  - `validate_tensor_m113_memory_hierarchy_v5_contract.py`
- 验收：hit-rate 与 latency 分解可稳定解释不同 tile/blocking 配置。

### M114：Cross-layer Counterfactual v3（反事实归因）
- 目标：支持“改一个控制量，验证瓶颈归因是否反转”。
- 交付：
  - `tools/run_tensor_m114_gate.sh`
  - `validate_tensor_m114_cross_layer_counterfactual_v3.py`
- 验收：三组反事实实验中，归因结论与设计预期一致率 >= 85%。

### M115：Trace/Compiler Bridge v5（映射可预测）
- 目标：提升 trace->spec 对跨配置排名的预测能力。
- 交付：
  - `tools/run_tensor_m115_gate.sh`
  - `compile_tensor_trace_v5_to_spec.py`
  - `validate_tensor_m115_trace_v5_bridge_contract.py`
- 验收：固定 workload 在多配置排序一致率 >= 80%。

### M116：Calibration Loop v4（多目标误差预算）
- 目标：把单目标校准升级为 latency/bandwidth/power 联合校准。
- 交付：
  - `tools/run_tensor_m116_gate.sh`
  - `validate_tensor_m116_calibration_loop_v4_contract.py`
  - `m116_calibration_profile.json`
- 验收：加权误差 <= 15%，并输出可追溯 profile。

### M117：Scale-out v3（Collective 算法边界）
- 目标：在 ring/tree/hybrid 之间建立可解释切换。
- 交付：
  - `tools/run_tensor_m117_gate.sh`
  - `validate_tensor_m117_scaleout_v3_contract.py`
- 验收：跨规模实验中算法切换点可复现，性能拐点可解释。

### M118：Energy/Power/Thermal v5（动态节流）
- 目标：引入 thermal proxy 与 power-cap 动态反馈。
- 交付：
  - `tools/run_tensor_m118_gate.sh`
  - `validate_tensor_m118_energy_power_thermal_v5_contract.py`
- 验收：功耗约束场景出现可解释的频率/吞吐折衷。

### M119：RAS v5（可靠性成本前沿）
- 目标：量化 retry/throttle/isolate/hybrid 策略成本前沿。
- 交付：
  - `tools/run_tensor_m119_gate.sh`
  - `validate_tensor_m119_ras_policy_v5_contract.py`
- 验收：同 fault profile 下可形成稳定 Pareto 前沿。

### M120：Phase-8 Final Gate（综合门禁）
- 目标：聚合 `M111-M119` 并给出阶段结论。
- 交付：
  - `tools/run_tensor_m120_gate.sh`
  - `sst_workloads/tensor_si/tools/aggregate_tensor_phase8_regression.py`
  - `sst_workloads/tensor_si/tools/validate_tensor_m120_phase8_report.py`
- 验收：`status=pass`，并满足 3.2 所有 exit criteria。

## 5. 顶层接线与测试矩阵（文件级设计）

### 5.1 顶层接线（必须）
- `tools/run_snndl_regression_gate.sh`
  - 新增 `m111_report_dir ... m120_report_dir`
  - 新增执行序列 `run_realism_gate m111..m120`
  - 新增 fail code 规划：`95..104`
- `tools/test_run_snndl_regression_gate_realism_contract.py`
  - 覆盖范围扩展到 `m120`
- `sst_workloads/tensor_si/tools/validate_tensor_m63_regression_hardening.py`
  - realism gate 列表扩展到 `m120`

### 5.2 单测矩阵（必须）
- gate CLI：
  - `tools/test_run_tensor_m111_gate.py ... tools/test_run_tensor_m120_gate.py`
- validator：
  - `test_validate_tensor_m111_*.py ... test_validate_tensor_m119_*.py`
  - `test_aggregate_tensor_phase8_regression.py`
  - `test_validate_tensor_m120_phase8_report.py`
- 顶层合同：
  - `tools/test_run_snndl_regression_gate_realism_contract.py`
  - `test_validate_tensor_m63_regression_hardening.py`

## 6. 执行波次（建议）

### Wave-A（基础可信度）
- `M111 -> M112 -> M113`
- 目标：先把“计数器-分数-行为”链路打通。

### Wave-B（可预测性）
- `M114 -> M115 -> M116`
- 目标：把“因果归因 + 编译映射 + 多目标标定”形成闭环。

### Wave-C（可决策）
- `M117 -> M118 -> M119 -> M120`
- 目标：产出 scale-out / power / ras 的决策级报告与阶段总闸。

## 7. 风险与回滚策略

1. 风险：新统计侵入导致历史 gate 波动。
- 缓解：新能力默认 `off`，通过 spec 显式启用。
- 回滚：保留 v4/v5 双轨 validator，异常时回落到 v4 路径。

2. 风险：校准目标过多导致过拟合。
- 缓解：固定误差预算和权重，不在阶段中途改指标。
- 回滚：保留单目标校准作为兜底（latency-only）。

3. 风险：scale-out 实验耗时过长。
- 缓解：门禁使用 step-limited，full-run 走 nightly。
- 回滚：先冻结算法边界验证，延后大规模点位。

## 8. 验证命令模板（阶段内统一）

- 单 gate 冒烟：
  - `bash tools/run_tensor_m11X_gate.sh --skip-unit --run-root tmp/tensor_m11X_gate_smoke`
- phase8 聚合冒烟：
  - `bash tools/run_tensor_m120_gate.sh --skip-unit --run-root tmp/tensor_m120_gate_smoke`
- 顶层 realism：
  - `SNNDL_GATE_BUILD=0 SNNDL_GATE_TENSOR_TRACK=realism SNNDL_GATE_TENSOR_REALISM_SKIP_UNIT=1 bash tools/run_snndl_regression_gate.sh`

## 9. 实施前冻结项（必须先确认）

1. `M111` readiness-anchor schema 字段与容错策略。
2. `M112` hazard 分类字典与统计口径。
3. `M116` 多目标误差预算权重（latency/bandwidth/power）。
4. `M120` 阶段退出阈值（score/distance/一致率/总闸三连 PASS）。

---

结论：
- `M111-M120` 不是简单延长 gate 数量，而是把现有 regression-grade 提升到 decision-grade。
- 完成本阶段后，我们将显著缩小“可回归仿真”与“可用于真实 NPU/TPU 架构决策仿真”之间的核心鸿沟。
