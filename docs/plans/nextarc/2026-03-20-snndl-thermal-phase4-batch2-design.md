# SnnDL Thermal Phase 4 Batch 2 Design

Date: 2026-03-20
Owner: Fufu
Status: Draft

## 1. 背景

`Phase4 Hooks-First Batch 1` 已完成以下基础设施：

- `ThermalRuntimeSignals`
- `ThermalConsumerSnapshot`
- `online_rc_estimator` mock
- runtime summary 对统一 thermal signals 的只读接桥

但当前链路还停留在“接口接通”的阶段，距离真正可用于正式热分析还有 4 个明显缺口：

1. `estimate_online_rc_state(...)` 还没有接到真实 `WindowPowerSample` 回放路径；
2. `snn3dexp` 还没有自己的 HotSpot 驱动适配层，只能消费 proxy summary；
3. runtime / phase2 / paper artifact 的 thermal observability 口径太薄；
4. thermal guard 还没有“只记录建议动作”的稳定合同。

这意味着当前我们虽然能产出热信号，但还不具备：

- 对真实 windowed power trace 做在线温度回放；
- 以稳定 I/O 格式把 `snn3dexp` thermal state 交给 HotSpot 风格求解器；
- 在后续分析中持续追踪 `peak/avg/gradient/hotspot count` 等热状态；
- 用 recommendation-only 方式为后续 throttle/remap 闭环冻结动作合同。

## 2. 目标与非目标

### 2.1 目标

本批次目标是把热链路升级为“可回放、可适配、可观测、可建议”的状态：

1. 新增 `WindowPowerSample -> online RC replay` 路径。
2. 新增 HotSpot adapter 层，把：
   - `WindowPowerSample`
   - `ThermalStateCache`
   - `ThermalConsumerSnapshot`
   映射到稳定的 HotSpot 驱动输入/输出接口。
3. 扩展 runtime / phase2 / paper artifact / ablation 的 thermal observability 字段。
4. 新增 thermal guard recommendation-only 合同，只记录建议，不执行动作。

### 2.2 非目标

本批次明确不做：

- 真正调用 HotSpot 二进制做 in-loop runtime 求解；
- 把推荐动作真正下发为 throttle / remap / route rewrite；
- 做 RC 参数标定或拟合；
- 改动 SST C++ 组件内部热行为。

## 3. 方案选择

### 方案 A：继续 hooks-first，但把 replay/adapter/observability 补齐，推荐

特点：

- 保持 Batch 1 的只读边界；
- 新增可独立测试的 replay 与 adapter；
- 在 runtime summary 里增加 recommendation-only 输出；
- 不改变已有 adaptive_3d 的字段与回归基线。

优点：

- 风险低；
- 与当前仓内大量 JSON summary / unittest 驱动工作流一致；
- 为后续 HotSpot sidecar 与行为闭环提供稳定过渡层。

缺点：

- 真正的温控闭环仍需下一批次继续推进。

### 方案 B：直接把 replay + adapter 接进真实 runtime 闭环

优点：

- 路径更“完整”。

缺点：

- 需求耦合太多，调试边界不清晰；
- 一旦 recommendation / execution 混在一起，回归定位会很痛苦。

结论：采用方案 A。

## 4. 核心设计

### 4.1 热配置合同

在 `snn3dexp` spec/effective config 中新增最小 `thermal` 段：

- `enabled`
- `mode`
  - `proxy_only`
  - `window_power_replay`
- `summary_path`
- `ambient_c`
- `alpha`
- `beta`

默认仍是 `proxy_only`，从而保证既有 case 不回退。

当 `mode == window_power_replay` 且 `summary_path` 可用时：

1. 从 `thermal_summary.json` / `window_power_samples.jsonl` 读取真实样本；
2. 顺序调用 `estimate_online_rc_state(...)`；
3. 生成 replay trace 与 latest thermal state；
4. 用 latest state 生成 consumer snapshot、runtime signals、HotSpot adapter payload。

### 4.2 Window Replay 合同

新增 `replay.py`，职责是把真实 `WindowPowerSample` 序列重放成热状态轨迹：

- `load_window_power_samples(...)`
- `replay_online_rc_thermal_trace(...)`

输出内容包括：

- `samples`
- `states`
- `latest_state`
- `meta`
  - `sample_count`
  - `block_count`
  - `trace_sources`
  - `duration_ns`
  - `ambient_c`
  - `alpha`
  - `beta`

第一版只需要 latest state + replay meta；不要求保存完整大对象到 phase2 summary。

### 4.3 HotSpot Adapter 合同

新增 `hotspot_adapter.py`，输出稳定 adapter payload，而不是直接跑 HotSpot：

- `adapter_version`
- `sample_id`
- `state_source`
- `power_trace_source`
- `block_inputs[]`
  - `block_name`
  - `layer_name`
  - `layer_index`
  - `block_type`
  - `power_w`
  - `temperature_c`
- `layer_inputs[]`
  - `layer_name`
  - `layer_index`
  - `temp_avg_c`
  - `temp_peak_c`
  - `temp_min_c`
- `io_summary`
  - `block_count`
  - `layer_count`
  - `has_power_trace`
  - `has_temperature_state`

这样可以把 `sst_dram_si/tools/thermal_export.py` 已有的 `WindowPowerSample` 工件复用到 `snn3dexp` 中，又不把两个系统硬耦合。

### 4.4 Thermal Observability 合同

在 runtime summary 中新增 `thermal_observability`：

- `peak_temperature_c`
- `avg_temperature_c`
- `hotspot_block_count`
- `hotspot_layer_count`
- `vertical_gradient_c`
- `top_layer_peak_c`
- `bottom_layer_peak_c`
- `thermal_hotspot_score`

在 phase2 / ablation / paper artifacts 中至少继续透出：

- `peak_temperature_c`
- `avg_temperature_c`
- `vertical_gradient_c`
- `hotspot_block_count`
- `hotspot_layer_count`
- `thermal_signal_source`
- `thermal_state_source`
- `thermal_replay_sample_count`

### 4.5 Recommendation-Only Thermal Guard

保留现有：

- `thermal_guard_actions`
- `action_labels`
- `recommended_weights`

新增：

- `recommended_actions[]`

每个建议动作包含：

- `label`
- `kind`
- `reason`
- `metric`
- `observed`
- `threshold`
- `execute`

其中 `execute` 第一版固定为 `False`，明确表明这是 recommendation-only 合同，而不是实际执行。

## 5. 接入位置

### 5.1 `mesh3d_template`

负责接纳 `thermal` 配置并带入 effective config。

### 5.2 `platform/build_system.py`

这是本批次的主接点：

1. 解析 thermal config；
2. 决定走 `proxy_only` 还是 `window_power_replay`；
3. 生成：
   - `thermal`
   - `thermal_replay`
   - `thermal_consumer_snapshot`
   - `thermal_hotspot_adapter`
   - `runtime`

### 5.3 `runtime/policy.py`

继续保持行为只读，但补充：

- `thermal_observability`
- `thermal_state_source`
- `recommended_actions`

### 5.4 `tools/run_case.py`

需要把新增 observability / recommendation / replay meta 写进：

- `runtime_summary.json`
- `phase2_case_summary.json`

### 5.5 下游分析

至少更新：

- `analyze_ablation.py`
- `export_phase2_paper_artifacts.py`

使其不会丢失新增 thermal observability 字段。

## 6. 测试策略

本批次继续严格 TDD：

1. 先为 replay/adapter 写红灯测试；
2. 再为 runtime observability / recommended actions 写红灯测试；
3. 再为 phase2 / paper artifact 扩展口径写红灯测试；
4. 最后跑聚焦回归并追加 `TECH_PROGRESS.md`。

## 7. 预期结果

Batch 2 完成后，`snn3dexp` 将从“只读 thermal hooks 已存在”升级到：

- 能重放真实 `WindowPowerSample`
- 能输出稳定 HotSpot adapter payload
- 能在 runtime / case / report 中看到完整 thermal observability
- 能记录 thermal guard 建议动作而不执行

这会为下一批的：

- HotSpot sidecar 真适配
- in-loop solver
- throttle/remap 执行闭环

打下稳定且低风险的基础。
