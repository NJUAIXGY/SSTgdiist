# SnnDL Thermal Phase 6 Multi-Case Calibration Design

Date: 2026-03-20
Owner: Fufu
Status: Draft

## 1. 背景

`Phase 5` 已经把单个 case 的 runtime RC 与 HotSpot sidecar 偏差正式接进了 `phase2_case_summary.json`、`analyze_ablation.py` 和 `export_phase2_paper_artifacts.py`：

- 每个 case 已有：
  - `hotspot_peak_delta_c`
  - `hotspot_avg_delta_c`
  - `hotspot_block_delta`
  - `hotspot_layer_delta`
- HotSpot sidecar 的真实 3D stack run 也已经验证成功；
- runtime 仍坚持 `hooks-first / read-only`，决策源仍是 `online_rc_estimator`。

但当前偏差能力仍是“单 case 可见”，还不是“多 case 可分析”：

1. `analyze_ablation.py` 只把 delta 透传进每个 case，没有做跨 case 聚合；
2. `paper artifacts` 只能看到某个 runtime focus case 的 delta，无法回答：
   - 哪个指标整体偏差最大；
   - 哪些 case 偏差最严重；
   - 当前 RC 在不同 case 上是否稳定；
3. 还没有形成可直接支撑下一阶段 RC 标定的正式汇总产物。

Phase 6 的目标，就是把这些离散 delta 组织成“多 case 热校准摘要”。

## 2. 目标与非目标

### 2.1 目标

本阶段只做下面 3 件事：

1. **在 `analyze_ablation.py` 中形成多 case 热校准聚合块**
   - 对已选 case 做统一过滤；
   - 统计 peak/avg/block/layer 四类 delta；
   - 输出可直接追溯到 case/run_tag 的 worst-case 信息。

2. **在 `export_phase2_paper_artifacts.py` 中导出正式 calibration 产物**
   - 新增 case 级 CSV；
   - 新增 calibration summary SVG；
   - 在 summary JSON 中保留结构化 calibration 摘要。

3. **保持 hooks-first / runtime read-only 架构不变**
   - 不让 HotSpot 进入 runtime adaptive 闭环；
   - 只做 sidecar 校准分析，不改 runtime 控制语义。

### 2.2 非目标

本阶段明确不做：

- RC 参数自动拟合或自动回写；
- 新的独立 CLI 或新的分析入口；
- HotSpot transient/in-loop 耦合；
- 修改 SST C++ 热路径；
- 新的封装模型或更细物理参数求解。

## 3. 现状缺口

### 3.1 偏差字段只停留在 case 层

目前 delta 虽然已经存在，但它们分散在：

- `phase2_case_summary.json`
- `analyze_ablation.py -> cases[*].thermal_summary`
- `paper summary -> runtime_focus_metrics`

这意味着使用者仍然需要手工遍历所有 case 才能得到：

- 均值、极值、绝对均值；
- 最大偏差对应的 case；
- 哪些 case 真正具备可信 HotSpot 样本。

### 3.2 多 case 样本里存在状态差异

并不是所有 case 都适合进入校准统计：

- 有些 case 只有 adapter payload；
- 有些 case 的 HotSpot binary 被跳过；
- 有些 case 可能没有完整 layer/block 对照。

如果不先做过滤，跨 case 聚合会混入“并未真正跑 HotSpot”的样本，导致校准统计失真。

### 3.3 paper artifacts 还没有正式 calibration 页面

现有导出聚焦：

- baseline 表；
- runtime focus 图；
- route-memory compare；
- memory-model compare。

但还缺少一个明确回答“RC 与 HotSpot 偏差整体如何”的产物。

## 4. 方案设计

### 4.1 `analyze_ablation.py` 新增 `thermal_calibration` 聚合块

在顶层 summary 新增：

- `thermal_calibration.available`
- `thermal_calibration.filter`
- `thermal_calibration.summary`
- `thermal_calibration.cases`
- `thermal_calibration.metrics`

其中过滤规则固定为：

- 只统计 `cases[*].thermal_summary.hotspot_driver_status == "ran"` 的 case。

这样可以确保校准统计只基于真实 HotSpot run，而不是 fallback 或 skipped case。

### 4.2 `thermal_calibration.cases` 的语义

每个 case 记录最小必要但足够校准的信息：

- `case_id`
- `run_tag`
- `hotspot_driver_status`
- `hotspot_temperature_source`
- `runtime_peak_temperature_c`
- `hotspot_peak_temperature_c`
- `hotspot_peak_delta_c`
- `runtime_avg_temperature_c`
- `hotspot_avg_temperature_c`
- `hotspot_avg_delta_c`
- `runtime_hotspot_block_count`
- `hotspot_block_count`
- `hotspot_block_delta`
- `runtime_hotspot_layer_count`
- `hotspot_layer_count`
- `hotspot_layer_delta`

这里明确把 runtime 与 HotSpot 原始值同时保留下来，避免后续校准脚本还要重新回表做反推。

### 4.3 `thermal_calibration.metrics` 的聚合方式

对四个 delta 指标分别聚合：

- `hotspot_peak_delta_c`
- `hotspot_avg_delta_c`
- `hotspot_block_delta`
- `hotspot_layer_delta`

每个指标至少输出：

- `count`
- `mean`
- `abs_mean`
- `min`
- `max`
- `max_abs`
- `min_case_id`
- `max_case_id`
- `max_abs_case_id`
- `min_run_tag`
- `max_run_tag`
- `max_abs_run_tag`

这样可以同时回答：

- 偏差是否整体偏正/偏负；
- 平均绝对偏差有多大；
- 最坏样本是谁。

### 4.4 `thermal_calibration.summary` 的范围

summary 负责给上层快速判断：

- `eligible_case_count`
- `eligible_case_ids`
- `excluded_case_ids`
- `hotspot_status_counts`
- `hotspot_temperature_source_counts`
- `runtime_state_source_counts`

这里不会做统计拟合，只做样本质量与覆盖面摘要。

### 4.5 `export_phase2_paper_artifacts.py` 的导出

本阶段优先扩展现有导出器，而不是新建 CLI。新增输出：

1. `phase2_thermal_calibration_table.csv`
   - 逐 case 导出 calibration cases；
   - 可直接用于 spreadsheet / plotting / 后续拟合。

2. `phase2_thermal_calibration_compare.svg`
   - 以四个指标为行；
   - 展示 `mean / abs_mean / max_abs`；
   - 同时标注 worst-case case id。

3. `phase2_runtime_summary.json`
   - 保留 `thermal_calibration` 结构化块；
   - 作为 paper summary 的正式一部分。

### 4.6 兼容策略

本阶段只做增量添加：

- 不修改已有 `cases[*]` 结构；
- 不删除或重命名现有 runtime focus 字段；
- 不改变已有导出文件名；
- 只新增 calibration block 和对应产物。

这样可以保证现有 phase2/report 链路继续兼容。

## 5. 测试策略

### 5.1 `analyze_ablation.py`

新增单测锁定：

- 只有 `hotspot_driver_status == "ran"` 的 case 进入 calibration；
- metrics 的 `mean/abs_mean/max_abs` 正确；
- worst-case case id / run_tag 正确。

### 5.2 `export_phase2_paper_artifacts.py`

新增单测锁定：

- 导出 `phase2_thermal_calibration_table.csv`
- 导出 `phase2_thermal_calibration_compare.svg`
- `phase2_runtime_summary.json` 中带有 `thermal_calibration`
- calibration summary 中保留聚合结果和 eligible cases。

## 6. 实施顺序

1. 先补 Phase 6 设计与实现计划；
2. 先写 `test_ablation_contract.py` 和 `test_phase2_paper_artifacts.py` 的红灯测试；
3. 实现 `analyze_ablation.py` 的 calibration 聚合；
4. 实现 `export_phase2_paper_artifacts.py` 的 CSV/SVG/summary 导出；
5. 跑 focused tests，再跑回归；
6. append `TECH_PROGRESS.md`，记录结果与后续 RC 标定任务。
