# SnnDL Thermal Phase 4 Batch 3 Design

Date: 2026-03-20
Owner: Fufu
Status: Draft

## 1. 背景

`Phase4 Hooks-First Batch 2` 已经把 `snn3dexp` 的热链路推进到下面这个状态：

- `WindowPowerSample -> online_rc_estimator` 回放已接通；
- `thermal_hotspot_adapter` 已能输出稳定的结构化 payload；
- runtime / phase2 / ablation / paper artifact 已开始透出热可观测字段；
- thermal guard 维持 recommendation-only 合同。

但当前仍有一个核心缺口：`thermal_hotspot_adapter` 还只是“给 HotSpot 用的输入草稿”，不是一个真正会产出 HotSpot 工件、可选调用 HotSpot 二进制、并回收温度结果的 sidecar driver。

这意味着我们虽然已经能：

- 从真实 `window_power_samples.jsonl` 生成 online RC 温度轨迹；
- 在 runtime 里看到 `peak/avg/gradient/hotspot count`；

但还不能正式回答下面两个更关键的问题：

1. `snn3dexp` 自己是否能稳定产出 HotSpot 兼容工件？
2. 如果环境里存在 HotSpot 二进制，我们是否能在不碰 runtime 闭环的前提下，离线 sidecar 地产出更正式的温度解？

Batch 3 就是补这个缺口。

## 2. 目标与非目标

### 2.1 目标

本批次目标是把现有 `thermal_hotspot_adapter` 从“结构化 payload”升级成“真正可落盘、可运行、可回读”的 HotSpot sidecar driver：

1. 在 `snn3dexp/thermal/` 内新增独立 sidecar driver。
2. 复用 `sst_dram_si/tools/thermal_export.py` 已经稳定的 HotSpot 文件协议：
   - `snndl_mesh.flp`
   - `snndl_mesh.ptrace`
   - `hotspot.config`
   - `snndl_mesh.lcf`（当进入 3D/grid 模型时）
   - `tile_temperature_summary.csv`
   - `thermal_summary.json`
3. 支持两类执行结果：
   - 没有 HotSpot 二进制：只生成工件并标记 `skipped_missing_binary`
   - 有 HotSpot 二进制：真实执行并回收 `steady.temp` / `transient.temp`
4. 保持 hooks-first / read-only 路线：
   - runtime 继续消费 `online_rc_estimator`
   - HotSpot 结果先作为 sidecar 观测产物，不直接反向驱动 runtime 决策
5. 在 `platform_summary.json` / `phase2_case_summary.json` / 下游 paper artifact 中透出 HotSpot sidecar 摘要，便于正式分析与归档。

### 2.2 非目标

本批次明确不做：

- 把 HotSpot 结果直接注入 runtime adaptive 闭环；
- 执行真实 throttle / remap / route rewrite；
- 标定 HotSpot package 参数；
- 改 SST C++ 组件；
- 做完整的 in-loop transient thermal control。

## 3. 方案比较

### 方案 A：在 `snn3dexp` 里独立重写一套 HotSpot 文件协议

优点：

- 模块边界清晰。

缺点：

- 容易和 `sst_dram_si/tools/thermal_export.py` 产生协议漂移；
- 会重复维护 `.flp/.ptrace/.config/.lcf` 细节；
- 测试口径更难对齐。

### 方案 B：直接调用 `sst_dram_si/tools/thermal_export.py` CLI

优点：

- 复用现有脚本最多。

缺点：

- 输入模型不匹配：`thermal_export.py` 依赖 `run_dir + effective_config.json + mesh_stats.csv`；
- `snn3dexp` 现在手上的是 adapter payload 与 replay samples，不是同一层对象；
- 很难做细粒度单元测试。

### 方案 C：在 `snn3dexp` 新建 driver，但尽量复用 `thermal_export.py` 的协议生成与 HotSpot 启动助手，推荐

优点：

- 保留 `snn3dexp` 自己的输入合同；
- 仍然能最大化复用 HotSpot 文件协议与测试口径；
- 可以先支持 2D block，再自然延伸到 3D grid / layer stack。

缺点：

- 需要接受对 `thermal_export.py` 私有 helper 的受控依赖，或复制极少量必要逻辑。

结论：采用方案 C。

## 4. 核心设计

### 4.1 新增模块：`snn3dexp/thermal/hotspot_driver.py`

新增 sidecar driver，职责只有一件事：

- 接收 `effective_config + thermal_hotspot_adapter payload + window_power_samples`
- 产出 HotSpot 兼容工件
- 可选运行 HotSpot
- 生成结构化 sidecar summary

推荐接口：

- `build_hotspot_sidecar(...)`

输入：

- `effective_config`
- `adapter_payload`
- `window_power_samples`

输出 summary 至少包含：

- `enabled`
- `status`
- `model_type`
- `binary`
- `returncode`
- `temperature_source`
- `window_count`
- `block_count`
- `layer_count`
- `artifacts`
- `metrics`

### 4.2 2D / 3D 路线

Batch 3 需要同时照顾“当前 2D mesh”与“未来 3D 堆叠”：

- 单层时默认走 `block` 模型；
- 多层时默认走 `grid` 模型，并生成：
  - 每层 floorplan
  - `snndl_mesh.lcf`
  - `hotspot.config` 中的 `grid_rows/grid_cols/grid_map_mode/detailed_3D`

层信息来源按优先级：

1. `thermal.layers`
2. `adapter_payload.layer_inputs`
3. `window_power_samples[*].blocks[*].layer_name/layer_index`

如果没有显式 layer 配置，则使用最小默认层参数：

- `kind=mesh_active`
- `power_dissipating=True`
- `thickness_um=1`
- `lateral_heat_flow=True`
- `volumetric_heat_capacity/resistivity` 复用 `thermal_export.py` 默认值

这样 Batch 3 就能先把 2D/单层跑通，同时给 3D/grid 留出完全兼容的合同。

### 4.3 工件目录与文件合同

默认输出到：

- `<run_root>/thermal_sidecar/hotspot/`
- `<run_root>/thermal_sidecar/summary/`

首版工件：

- `hotspot/snndl_mesh.flp`
- `hotspot/snndl_mesh.ptrace`
- `hotspot/hotspot.config`
- `hotspot/snndl_mesh.lcf`（grid 模型时）
- `hotspot/layer_XX_<name>.flp`（grid 模型时）
- `hotspot/steady.temp`
- `hotspot/transient.temp`
- `summary/window_power_samples.jsonl`
- `summary/tile_temperature_summary.csv`
- `summary/thermal_summary.json`

其中：

- `window_power_samples.jsonl` 保存 driver 使用过的归一化 trace；
- `tile_temperature_summary.csv` 即使没有 HotSpot 二进制也要生成；
- 当 HotSpot 未执行时，`temperature_c` 优先回填 adapter payload 自带温度；
- 当 HotSpot 执行成功时，用 `steady.temp` 覆盖对应 block 温度。

### 4.4 Sidecar Summary 合同

`thermal_hotspot_adapter` 保持现有字段不变，同时追加：

- `driver`

也就是：

- `thermal_hotspot_adapter.io_summary` 等原字段继续可用；
- `thermal_hotspot_adapter.driver` 给出真正的 sidecar 摘要。

`driver` 建议暴露：

- `enabled`
- `status`
  - `disabled`
  - `skipped_missing_binary`
  - `skipped_empty_trace`
  - `ran`
  - `failed`
  - `failed_to_launch`
  - `failed_missing_lcf`
- `binary`
- `returncode`
- `model_type`
- `mesh_shape`
- `tile_count`
- `layer_count`
- `block_count`
- `window_count`
- `trace_mode`
- `temperature_source`
  - `adapter_payload`
  - `hotspot_steady_temp`
- `metrics`
  - `peak_temperature_c`
  - `avg_temperature_c`
  - `hotspot_block_count`
  - `hotspot_layer_count`
- `artifacts`

这样 Batch 2 的消费者不会坏，而 Batch 3 之后新的分析也有了正式落点。

### 4.5 `phase2_case_summary` 与下游贯通

在 `phase2_case_summary["thermal"]` 中新增 sidecar 相关字段：

- `hotspot_driver_status`
- `hotspot_model_type`
- `hotspot_temperature_source`
- `hotspot_peak_temperature_c`
- `hotspot_avg_temperature_c`
- `hotspot_artifacts`

保留原有 runtime thermal observability 字段不变，避免把：

- online RC replay 温度
- HotSpot sidecar 温度

混成一套指标。

下游：

- `analyze_ablation.py` 保留这些 sidecar 字段；
- `export_phase2_paper_artifacts.py` 把它们纳入 runtime/thermal focus metrics，便于正式出图时明确温度来源。

## 5. 数据流

目标数据流如下：

1. `window_power_samples.jsonl`
2. `replay_online_rc_thermal_trace(...)`
3. `thermal_consumer_snapshot`
4. `build_hotspot_adapter_payload(...)`
5. `build_hotspot_sidecar(...)`
6. sidecar 工件写入 `run_root/thermal_sidecar/`
7. `platform_summary.json` 写入 adapter + driver 摘要
8. `phase2_case_summary.json` / ablation / paper artifacts 继续透传

这里最重要的边界是：

- runtime adaptive 继续看 `online_rc_estimator`
- HotSpot sidecar 先作为“更正式的离线热求解输出”

这样我们不会把两个温度源混淆，也不会在本批次把行为风险放大。

## 6. 测试策略

Batch 3 继续严格 TDD：

1. 新增 `snn3dexp/tests/test_hotspot_driver.py`
   - 覆盖“无二进制只产工件”
   - 覆盖“fake hotspot binary 真跑并回填 steady temp”
2. 扩展 `test_runtime_3d_policy.py`
   - 确认 `build_platform_summary(...)` 能带出 `thermal_hotspot_adapter.driver`
3. 扩展 `test_run_case.py`
   - 确认 `phase2_case_summary.json` 保留 HotSpot sidecar 摘要
4. 扩展 `test_phase2_paper_artifacts.py`
   - 确认下游 focus metrics 能看到 sidecar status / 温度来源 / peak temp

## 7. 风险与回退

主要风险：

1. `thermal_export.py` 私有 helper 变更导致 sidecar 协议漂移；
2. 多层 block name / block_prefix 推断错误会导致 `.flp/.ptrace` 不匹配；
3. sidecar 产物写盘让 `build_platform_summary(...)` 变成带副作用路径。

对应缓解：

1. 尽量只复用必要 helper，并用单元测试锁定工件名与字段；
2. 优先从现有 block name 推断 layer prefix，不自己发明命名；
3. 只在 `thermal.enabled == True` 且 payload 非空时产 sidecar 工件。

## 8. 预期产出

Batch 3 完成后，`snn3dexp` 将首次具备下面这条正式链路：

- replay 热状态
- HotSpot sidecar 工件
- 可选真实 HotSpot 求解
- 平台摘要 / phase2 / paper artifact 全链透传

这将使“我们能否正式产出热仿真相关数据”从“部分可以”推进到“可以稳定产出 sidecar 级正式工件与摘要”。
