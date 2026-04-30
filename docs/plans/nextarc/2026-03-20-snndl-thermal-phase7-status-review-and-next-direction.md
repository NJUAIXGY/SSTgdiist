# SnnDL Thermal Phase7 Status Review And Next Direction

Date: 2026-03-20
Owner: Fufu
Status: Reviewed after Phase7 bugfix

## 1. 文档目的

这份文档用于把当前 `snn3dexp/SnnDL` 热分析工作的真实状态重新对齐到一份可执行判断上。

它回答 3 个问题：

1. 截至当前代码和正式产物，哪些结论已经可以正式成立。
2. 哪些地方虽然“能跑”，但还不能被当成论文级或长期稳定接口来解读。
3. 下一阶段最值得投入的方向是什么，为什么不是别的方向。

这份文档优先以当前仓库中的真实代码、测试和产物为准，而不是以早期设计假设为准。

## 2. 本轮审阅范围

本轮审阅覆盖了以下对象：

- 代码：
  - `snn3dexp/tools/run_case.py`
  - `snn3dexp/tools/analyze_ablation.py`
  - `snn3dexp/tools/export_phase2_paper_artifacts.py`
  - `snn3dexp/runtime/policy.py`
- 测试：
  - `snn3dexp/tests/test_run_case.py`
  - `snn3dexp/tests/test_ablation_contract.py`
  - `snn3dexp/tests/test_phase2_paper_artifacts.py`
  - `snn3dexp/tests/test_runtime_3d_policy.py`
- 正式产物：
  - `snn3dexp/analysis/hotspot_real_phase6_multicase_20260320_174519_ablation.json`
  - `snn3dexp/analysis/hotspot_real_phase6_multicase_20260320_174519_multicase_hotspot_report.json`
  - `snn3dexp/analysis/paper_artifacts/hotspot_real_phase6_multicase_20260320_174519/*`
- 现有设计/总结文档：
  - `docs/plans/nextarc/2026-03-20-snndl-thermal-analysis-status-deep-dive.md`
  - `docs/plans/nextarc/2026-03-20-snndl-thermal-phase6-multicase-calibration-design.md`
  - `docs/plans/nextarc/2026-03-20-snndl-online-thermal-feedback-interface-design.md`
  - `docs/plans/nextarc/2026-03-20-3d-snn-current-status-and-nextarc.md`

## 3. 当前已正式成立的结论

### 3.1 热分析主链路已经正式可用

当前可以正式确认：

- `offline-first` 热分析链路已经闭环。
- `HotSpot sidecar` 已经能在 `3D layered/grid` 配置下稳定产出正式工件。
- `phase2_case_summary -> analyze_ablation -> export_phase2_paper_artifacts` 已经形成可复用的数据发布链。
- `Phase7` 已经修复了 non-adaptive case 在 `phase2_case_summary` 中丢失 RC thermal observability 的问题。

换句话说，当前项目已经不再停留在“理论上可接热仿真”，而是已经具备：

- 可重跑的热工件；
- 可验证的测试；
- 可导出的校准表与图；
- 可用于后续迭代的稳定数据路径。

### 3.2 当前最可靠的定位仍然是 `offline-first + read-only runtime`

当前系统可以正式描述为：

- `HotSpot` 作为 sidecar/offline 校准器；
- `online_rc_estimator` 作为当前 runtime 可见温度状态来源；
- `runtime adaptive` 仍是只读 RC 状态驱动；
- `HotSpot` 结果尚未进入 runtime 行为控制闭环。

这条定位是清晰且合理的。它意味着：

- 我们已经能做“RC vs HotSpot”一致性检查；
- 但还没有进入“HotSpot in-loop thermal control”；
- 当前阶段最主要的价值是接口稳定和实验可解释性，而不是求解精度极限。

### 3.3 现有多 case 校准产物已经“可发布”，但仍不是“可定论”

目前正式产物已经给出：

- `thermal_calibration.summary.runtime_state_source_counts = {"online_rc_estimator": 4}`
- `4/4` case 都有 `hotspot_driver_status = "ran"`
- `phase2_thermal_calibration_table.csv` 和 `phase2_thermal_calibration_compare.svg` 已可生成

所以当前可以正式说：

- 热校准结果已经能被统一导出；
- 数据链路已经不会再因为 non-adaptive case 的空壳 summary 而失真；
- 当前 phase2/report 工具链已经具备“热校准对外发布”的最低能力。

## 4. 审阅结论与关键问题

下面不是“未来可能优化项”，而是当前状态中真正会影响结论质量的关键问题。

### Finding 1: 当前 multicase calibration 不是独立样本集，而是同一 replay 源的多 case 复用

严重度：高

当前 `hotspot_real_phase6_multicase_20260320_174519` 的 4 个 case 共用了同一个：

- `thermal.summary_path = /home/xgy/remote/tmp/thermal_contract_suite_v1/thermal_3d_grid_base/runs/20260320-133539/thermal/summary/thermal_summary.json`

这导致 4 个 case 的：

- `runtime_peak_temperature_c`
- `runtime_avg_temperature_c`
- `hotspot_peak_delta_c`
- `hotspot_avg_delta_c`
- `hotspot_block_delta`
- `hotspot_layer_delta`

全部相同。

这说明当前“multicase”更准确的语义是：

- 多个配置 case 都成功接入了同一个 RC replay + HotSpot sidecar 管线；
- 而不是 4 个 case 分别使用各自独立热输入形成的独立校准样本。

影响：

- 当前结果足以证明链路兼容性；
- 但不足以证明“不同 case 上 RC 标定一致性已经被真实测得”；
- 现有均值/极值统计在统计意义上样本独立性不足。

### Finding 2: `phase2_case_summary` 已修复，但 `runtime_summary.json` 仍与其存在语义分叉

严重度：高

`Phase7` 修复发生在 `build_phase2_case_summary(...)`，因此：

- `phase2_case_summary.json` 中 non-adaptive case 已正确回退到 `platform_summary.thermal_consumer_snapshot.signals`
- 但 standalone 的 `runtime_summary.json` 在 non-adaptive case 里仍然是：
  - `policy = disabled`
  - `thermal_state_source = disabled`
  - `thermal_observability = empty shell`

影响：

- 当前对外发布口径主要依赖 `phase2_case_summary`，所以 paper/calibration 已经修正；
- 但如果后续脚本直接消费 `runtime_summary.json`，仍会重新读到旧的“空壳 observability”；
- 这意味着 runtime 语义接口还没有完全冻结，存在双口径风险。

### Finding 3: 当前这批 HotSpot multicase 运行是 `composed` 语义，不适合承载 route/memory 结论

严重度：中高

当前 `hotspot_real_phase6_multicase_20260320_174519` 这批 case 的状态是：

- `status = composed`

因此导出的 baseline table 中，很多 route/memory/mapping 字段仍然是：

- 空值；
- `0.000`；
- 或不存在真实 smoke/joint runtime 支撑的占位值。

影响：

- 这批产物非常适合做 thermal contract/calibration；
- 但不适合被拿来说明 route-memory-thermal 联合行为；
- 如果后续论文或总结里混用这批数据与 runtime smoke 数据，会造成结论层面的语义漂移。

### Finding 4: 当前 paper artifacts 仍把 observe-only 与 adaptive-control case 混在同一层展示

严重度：中

在 `phase2_runtime_summary.json` 与 calibration CSV 中：

- `full_3d_mapping`
- `full_3d_thermal_guard`
- `full_3d_runtime_adaptive`

仍会一起进入 runtime focus / thermal calibration 的可视化层。

但其中只有：

- `full_3d_runtime_adaptive`

是真正启用了 runtime adaptive policy 的 case；

而：

- `full_3d_mapping`
- `full_3d_thermal_guard`

本质上仍是 observe-only / static-policy case。

影响：

- 当前图表在“热观测能力”维度没问题；
- 但在“热控制能力”维度会混淆语义；
- 这会影响下一步把这些图直接转为论文结论。

## 5. 文档对齐结论

### 5.1 仍然有效的文档

下面这些文档的主判断仍然成立：

- `2026-03-20-snndl-thermal-analysis-status-deep-dive.md`
  - “offline-first 热分析已成形”的判断仍然正确
- `2026-03-20-snndl-thermal-phase6-multicase-calibration-design.md`
  - “要把单 case delta 组织成多 case calibration”这一设计目标已完成
- `2026-03-20-snndl-online-thermal-feedback-interface-design.md`
  - “不要直接把 HotSpot 嵌进 runtime，而要先冻结 interface”这一方向仍然正确
- `2026-03-20-3d-snn-current-status-and-nextarc.md`
  - “下一阶段价值在 co-design 平台而非单一功能补丁”这一总体判断仍然正确

### 5.2 需要被当前状态覆盖的地方

下面这些口径需要用当前文档覆盖：

1. `multicase calibration` 现在已经不是“缺功能”，而是“有功能但样本语义仍需加强”。
2. `non-adaptive RC observability` 现在已经不是 open bug，而是“phase2 已修、runtime_summary 仍待统一”。
3. `paper artifacts` 现在的主要问题不是“导不出来”，而是“分组语义不够清晰”。

### 5.3 当前文档层面的统一口径

截至现在，推荐统一采用如下表述：

- 当前已经具备正式的 `offline-first RC vs HotSpot calibration` 数据产出能力。
- 当前 calibration 工具链已修复 phase2 导出缺口，但样本独立性和 artifact 语义标签仍需加强。
- 下一阶段不应直接跳到 HotSpot in-loop，而应先完成 artifact semantics hardening 和 calibration dataset split。

## 6. 下一阶段方向分析

当前下一阶段有 3 条可能路线。

### 方向 A：先做 Artifact Semantics Hardening

内容包括：

- 统一 `runtime_summary.json` 与 `phase2_case_summary.json` 的 observability 语义；
- 在 calibration / paper artifacts 中加入：
  - `runtime_enabled`
  - `control_mode`
  - `case_role`
- 明确区分：
  - `observe_only`
  - `adaptive_control`
  - `calibration_only`

优点：

- 代价最小；
- 直接提升结果可解释性；
- 能防止后续继续把不同语义的 case 混成同一统计样本；
- 是所有后续方向的公共基础。

缺点：

- 不会直接增加新的热精度；
- 也不会立即增加新的论文图数量。

判断：

这是下一步最应该优先做的方向。

### 方向 B：做真正独立的 Multicase Calibration Dataset Expansion

内容包括：

- 每个 case 使用各自独立的 window power / thermal summary 输入；
- 不再让 4 个 case 共享同一个 replay summary；
- 把 calibration 从“管线兼容性证明”升级成“跨 case 稳定性测量”。

优点：

- 能显著提升统计可信度；
- 能真正回答“不同 case 下 RC vs HotSpot 偏差是否稳定”；
- 是后续 RC 参数拟合或分层模型标定的必要前提。

缺点：

- 如果不先做方向 A，产物语义仍会混乱；
- 需要重新组织 case run 生成逻辑和输入来源。

判断：

这是第二优先级，应该紧跟在方向 A 之后。

### 方向 C：继续推进 Online Thermal Feedback Interface

内容包括：

- 冻结 `WindowPowerSample / ThermalStateCache / ThermalConsumerHooks`
- 给 runtime read-only thermal interface 提供更清晰合同；
- 为未来 adaptive thermal control 打地基。

优点：

- 长期价值高；
- 与 offline-first 路线兼容；
- 为后续真正 online thermal-aware policy 做准备。

缺点：

- 如果当前 artifact semantics 和 calibration dataset 还不稳，接口会建立在有歧义的数据口径上；
- 现在推进会过早把注意力从“数据正确”转向“接口优雅”。

判断：

这是正确方向，但不是最先要做的方向。

## 7. 推荐的下一阶段主线

推荐主线：

`Phase 8 = Artifact Semantics Hardening + Calibration Dataset Split Preparation`

推荐原因：

1. 它直接解决当前最真实的 3 个问题：
   - 双口径 runtime/phase2 summary
   - observe-only 与 adaptive-control 混合展示
   - multicase 样本不独立
2. 它不会推翻现有架构，只是在现有正式链路上继续收紧语义。
3. 它是后续：
   - dataset expansion
   - RC 标定
   - online feedback interface
   的共同前置条件。

## 8. 建议的 Phase 8 任务拆分

### Task A: 统一 runtime artifact 语义

- 让 `runtime_summary.json` 在 non-adaptive case 下也能导出 observability-only thermal state
- 保证 standalone runtime artifact 与 phase2 artifact 不再分叉

### Task B: 给所有热分析产物补充 case role / control mode 标签

- 在 `phase2_case_summary`
- 在 `analyze_ablation`
- 在 `export_phase2_paper_artifacts`

统一导出：

- `runtime_enabled`
- `control_mode`
- `case_role`

### Task C: 把 calibration 统计按语义分组

至少区分：

- `observe_only`
- `adaptive_control`

并分别给出：

- case count
- delta mean / abs_mean / max_abs

### Task D: 准备独立 multicase thermal inputs

- 梳理每个 case 自己的 `window power sample` 来源
- 明确哪些 case 具备真实独立 replay 条件
- 把“共享同一 thermal summary”的临时路径从正式评测路径中拆出去

### Task E: 重建 paper-facing outputs

- 重新生成 calibration table / svg
- 明确标注：
  - 这批是 `observe-only calibration`
  - 哪些 case 是 `adaptive control`
  - 哪些数据来自 `composed-only`

## 9. 不建议现在就做的事

当前不建议马上投入：

1. 直接把 `HotSpot` 接进 runtime adaptive 决策闭环
2. 直接做复杂 3D package/TSV/full-physics 建模
3. 在当前共享 replay 样本上做 RC 自动拟合结论
4. 把 composed-only 热产物直接拿去讲 route-memory-thermal 联合优化收益

原因很简单：

- 现在的主要问题不是“求解器不够高级”
- 而是“artifact 语义和样本组织还没彻底收紧”

## 10. 一句话结论

当前热分析已经跨过“能不能产出正式数据”的门槛，下一阶段最应该做的不是继续堆新功能，而是先把 `artifact semantics`、`case role` 和 `calibration dataset independence` 三件事收紧；只有这样，后面的在线反馈和更深 3D 热建模才会建立在可信地基上。
