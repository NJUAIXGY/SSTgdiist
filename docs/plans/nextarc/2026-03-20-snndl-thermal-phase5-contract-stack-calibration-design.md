# SnnDL Thermal Phase 5 Contract/Stack/Calibration Design

Date: 2026-03-20
Owner: Fufu
Status: Draft

## 1. 背景

`Phase 4 Batch 3` 已经把 `snn3dexp` 的 HotSpot sidecar 从“结构化 payload”推进到“真实 binary 可跑通”的状态：

- `build_platform_summary(...)` 已经正式接线 `build_hotspot_sidecar(...)`；
- `platform_summary.json` / `phase2_case_summary.json` / paper artifacts 已经能透出 HotSpot sidecar 摘要；
- 真实 HotSpot binary 已在：
  - `/home/xgy/remote/externals/HotSpot-7.0/hotspot`
- 真实 run 已成功产出 steady-state 温度与 sidecar 工件。

但当前链路仍然停留在“能跑”的阶段，而不是“正式热建模就绪”的阶段。真实 bring-up 暴露了 3 个结构性缺口：

1. `grid_rows/grid_cols` 等真实约束还没有前移到配置合同层；
2. 3D stack 仍主要依赖 active replay blocks 推断，`TIM/spreader` 等 passive layers 还不是正式 spec；
3. runtime 的 `online_rc_estimator` 与 HotSpot sidecar 已经同时存在，但缺少偏差分析字段与摘要导出，无法判断是否需要 RC 标定。

Phase 5 的目标就是补齐这 3 个缺口。

## 2. 目标与非目标

### 2.1 目标

本阶段只做下面 3 条主线：

1. **配置与合同硬化**
   - 在 `mesh3d_template/spec.py` 中前移 HotSpot grid 模式的显式校验；
   - 明确 `thermal.layers` / `hotspot_package` 的输入合同；
   - 尽量在配置解析期报错，而不是等外部 binary 拒绝。

2. **3D stack 语义补全**
   - 让 `thermal.layers` 可以正式表达 active/passive stack layers；
   - sidecar summary 与 tile CSV 同时暴露：
     - `source_layer_index`
     - `normalized_layer_index`
   - 避免 LCF 连续层号与下游分析层号语义混淆。

3. **RC vs HotSpot 偏差分析**
   - 在 phase2 / ablation / paper artifact 中新增 runtime 与 HotSpot 的偏差字段；
   - 至少输出：
     - `hotspot_peak_delta_c`
     - `hotspot_avg_delta_c`
     - `hotspot_block_delta`
     - `hotspot_layer_delta`
   - 让后续 RC 参数标定有正式数据入口。

### 2.2 非目标

本阶段明确不做：

- 把 HotSpot 结果直接注入 runtime adaptive 闭环；
- 完整 transient/in-loop thermal control；
- 多 case RC 自动拟合；
- 修改 SST C++ 组件；
- 完整物理封装建模（如更细颗粒 TSV/interposer transient package solver）。

## 3. 现状问题拆解

### 3.1 配置层仍是“透传型”，不是“合同型”

当前 `resolve_spec(...)` 会保留 HotSpot sidecar 的扩展字段，但只做了基础类型归一化，没有做真实约束校验。结果就是：

- `grid_rows/grid_cols` 即使不是 2 的幂，也会进入 runtime；
- `grid` 模式下如果 layer 语义不完整，只能等 HotSpot 自身报错；
- `hotspot_package` 仍然只能使用 helper 默认值，无法在 case spec 正式表达。

这不适合作为“正式热分析输入合同”。

### 3.2 stack 语义里缺少 passive layers 的正式入口

当前 sidecar 已经能支持多层 grid，并且在 LCF 内部把层号重排为连续索引。但下游可观测数据仍然主要来自 active replay blocks，因此：

- 真实 3D stack 中间的 TIM/spreader 层在没有显式 `thermal.layers` 时不会进入 summary；
- CSV 里的 `layer_index` 仍然偏向源层号语义；
- 下游做 layer 级聚合时，无法区分“HotSpot 用的归一化层号”和“用户/trace 原始层号”。

### 3.3 两套温度源已经同时存在，但没有偏差指标

当前：

- runtime 使用 `online_rc_estimator`；
- sidecar 使用 `HotSpot steady.temp`；
- downstream 已能导出双方各自峰值/均值。

但还没有导出二者差值。这会直接阻塞下一步判断：

- 当前 RC 是否足够可信；
- 哪些 case 偏差最大；
- 是否应该先做参数标定，还是先做更复杂的瞬态模型。

## 4. 方案设计

### 4.1 配置合同硬化

在 `snn3dexp/mesh3d_template/spec.py` 新增 thermal 校验 helper，最小范围包括：

- `thermal.mode` 继续只允许：
  - `proxy_only`
  - `window_power_replay`
- 当 `thermal.model_type == "grid"` 时：
  - `grid_rows >= 1`
  - `grid_cols >= 1`
  - `grid_rows/grid_cols` 必须为 2 的幂
- `thermal.layers` 若存在：
  - 必须是 `list[dict]`
  - 每层最少允许 `name/kind/z_um/thickness_um` 走默认归一化
  - 对重复层名、负厚度、负 `z_um` 做显式拒绝
- `thermal.hotspot_package` 若存在：
  - 支持 `ambient_k/s_sink/t_sink/s_spreader/t_spreader/t_interface`
  - 所有值必须为正数

这里的目标不是做“完美物理校验”，而是把已知会让 HotSpot 失败或让 stack 语义失真的输入尽量挡在配置入口。

### 4.2 正式 3D layer 合同

在不破坏现有 `thermal.layers` 透传能力的前提下，增加两层正式语义：

1. `effective_config["thermal"]["layers"]`
   - 继续保留用户输入；
   - 新增 `hotspot_package` 透传。

2. `hotspot_driver` summary / CSV
   - 每层暴露：
     - `name`
     - `kind`
     - `z_um`
     - `thickness_um`
     - `power_dissipating`
     - `source_layer_index`
     - `normalized_layer_index`
   - tile CSV 每行新增：
     - `source_layer_index`
     - `normalized_layer_index`

兼容策略：

- 继续保留现有 `layer_index` 字段，语义保持为“源层号/外部可读层号”；
- 新增 `normalized_layer_index` 作为 HotSpot 内部连续层号；
- 不回写或覆盖旧字段，避免破坏已有下游。

### 4.3 HotSpot package 合同

HotSpot config 目前总是使用 `HOTSPOT_PACKAGE_DEFAULTS`。Phase 5 增加受控覆盖：

- 如果用户未显式配置 `thermal.hotspot_package`：
  - 维持现有默认值；
- 如果用户显式配置：
  - 生成 `hotspot.config` 时覆盖对应 package 参数；
  - sidecar summary 中同步记录实际 package。

这样可以让后续 RC/HotSpot 标定不必修改 driver 代码，只改 case spec 即可。

### 4.4 偏差分析导出

在 `build_phase2_case_summary(...)` 中，基于：

- runtime `thermal_observability`
- HotSpot driver `metrics`

新增下面这些一级字段：

- `hotspot_peak_delta_c = peak_temperature_c - hotspot_peak_temperature_c`
- `hotspot_avg_delta_c = avg_temperature_c - hotspot_avg_temperature_c`
- `hotspot_block_delta = hotspot_block_count - hotspot_hotspot_block_count`
- `hotspot_layer_delta = hotspot_layer_count - hotspot_hotspot_layer_count`

其中 delta 的方向固定为：

- `runtime - hotspot`

这样下游读到正值时，语义统一表示“runtime 比 HotSpot 更热/更多热点”。

这些字段继续下沉到：

- `analyze_ablation.py`
- `export_phase2_paper_artifacts.py`

让 phase2 summary、ablation summary、paper runtime summary 三条链路统一可见。

## 5. 测试策略

### 5.1 配置校验

新增单测锁定：

- `grid_rows/grid_cols` 非 2 的幂时抛 `SpecError`
- `hotspot_package` 透传与数值保留

### 5.2 driver stack 语义

新增单测锁定：

- 显式 `thermal.layers` 中包含 passive layer 时：
  - sidecar summary `layers` 保留 passive/active 信息
  - CSV 暴露 `source_layer_index` 和 `normalized_layer_index`
- 显式 `hotspot_package` 时：
  - `hotspot.config` 使用配置值
  - summary 同步反映配置值

### 5.3 偏差分析

新增单测锁定：

- `build_phase2_case_summary(...)` 生成 delta 字段
- `export_phase2_paper_artifacts.py` 的 runtime focus metrics 保留这些 delta 字段

## 6. 实施顺序

1. 先补设计与实现计划；
2. 先写红灯测试，锁定：
   - spec 校验
   - driver 层语义 / package 合同
   - phase2/paper delta 导出
3. 再做最小实现；
4. 最后跑 targeted tests + fresh regression，并把进展 append 到 `TECH_PROGRESS.md`。

## 7. 风险与控制

### 风险 1：过度收紧配置合同导致旧 case 失败

控制：

- 只把已经被真实 bring-up 证实的失败条件前移；
- 保持 block 模式兼容，不把 grid 约束扩散到所有 thermal 配置。

### 风险 2：layer 字段语义变更影响已有下游

控制：

- 保留旧 `layer_index` 字段；
- 只新增 `source_layer_index` / `normalized_layer_index`；
- downstream 先增量消费，不重写旧逻辑。

### 风险 3：偏差字段方向不统一

控制：

- 全链路统一定义为 `runtime - hotspot`；
- 在 phase2、ablation、paper summary 三处都用同一命名。

