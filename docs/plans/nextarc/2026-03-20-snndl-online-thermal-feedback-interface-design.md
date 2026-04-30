# SnnDL Online Thermal Feedback Interface Design

Date: 2026-03-20
Owner: Fufu
Status: Drafted for next arc

## 1. 背景

当前 `SnnDL` 已经具备正式可产出的 `HotSpot offline-first` 热分析链路：

- `mesh_template` 能稳定导出热配置；
- `thermal_export.py` 能生成 `ptrace/floorplan/LCF` 并调用 `HotSpot`；
- `thermal_summary.json` 和 `analyze_thermal_runs.py` 已能输出稳定的热结果和 sweep 友好的分析表。

但当前系统仍然是离线热后处理，不是在线温度反馈系统：

- 温度不会在 SST 运行过程中被组件读取；
- PE / NoC / mapping policy 还不能基于当前温度做节流、迁移或 aging proxy；
- 真实 HotSpot 求解仍然发生在 run 完成之后。

因此，下一阶段若要推进在线 thermal feedback，最关键的不是“立刻把 HotSpot 嵌进 runtime”，而是先冻结一套稳定的运行时接口，使在线近似热管理与离线正式热导出能够共享同一套数据模型。

## 2. 设计目标

本设计的目标是定义一个最小但可扩展的在线 thermal feedback 接口，满足：

1. 与当前 `offline-first` 工件完全兼容，不推倒重来。
2. 不要求 runtime 直接调用 HotSpot。
3. 允许未来接入：
   - 在线轻量 thermal estimator
   - 周期性/窗口级 HotSpot 外部服务
   - throttling / routing / mapping / aging consumer
4. 保持当前 block/layer 命名、`window power sample`、`thermal_summary` 语义稳定。

## 3. 非目标

本设计当前不做：

- 每周期调用 HotSpot
- 真实 runtime in-loop `HotSpot` 集成
- 完整 `3D-ICE` 多后端抽象实现
- 直接修改现有 PE 主执行语义
- 立即引入复杂的 thermal-aware scheduler / mapper

## 4. 核心设计

### 4.1 三层接口

在线 thermal feedback 应拆成三层：

1. `WindowPowerSample`
   - 运行时功率采样合同
   - 负责描述“本窗口每个 block 的功率输入是什么”
2. `ThermalStateCache`
   - 运行时热状态缓存
   - 负责描述“当前组件/层/块能读到的温度快照是什么”
3. `ThermalConsumerHooks`
   - 消费端接口
   - 负责描述“PE / NoC / policy 要如何读取温度并做决策”

### 4.2 设计原则

- `WindowPowerSample` 必须与当前 `ptrace` 列名完全兼容。
- `ThermalStateCache` 必须能够映射回：
  - tile
  - block
  - layer
- runtime 里的“在线热估计”与离线 `HotSpot` 求解都应该以 `WindowPowerSample` 为输入。
- consumer 只读温度状态，不直接依赖求解器实现。

## 5. `WindowPowerSample` 合同

建议运行时统一使用如下逻辑实体：

```text
WindowPowerSample
  sample_id
  start_cycle
  end_cycle
  duration_ns
  trace_mode
  blocks[]

BlockPowerEntry
  block_name
  layer_name
  layer_index
  block_type
  power_w
  trace_source
  window_scaling_mode
  cycle_model_applicable
```

### 5.1 为什么这样定义

- `block_name` 可直接复用当前 `ptrace` 列名。
- `trace_source / window_scaling_mode / cycle_model_applicable` 直接承接当前离线 provenance v2 语义。
- 如果未来 runtime 不做真实 HotSpot，也可以基于这些字段用轻量 RC/EMA 模型先做近似温度状态。

### 5.2 与当前离线链路的关系

当前离线流程本质上已经能产出这类信息，只是现在写成：

- `snndl_mesh.ptrace`
- `thermal_summary.json`
- `tile_temperature_summary.csv`

未来在线接口不应重新发明数据结构，而应该把这套语义提前到 runtime 内部。

## 6. `ThermalStateCache` 合同

建议定义运行时热状态缓存的逻辑结构：

```text
ThermalStateCache
  sample_id
  source
  layers[]
  blocks[]

BlockTemperatureState
  block_name
  temperature_c
  valid
  source

LayerTemperatureState
  layer_name
  layer_index
  temp_avg_c
  temp_peak_c
  temp_min_c
```

### 6.1 `source` 取值建议

- `offline_hotspot_replay`
- `online_rc_estimator`
- `online_hotspot_service`
- `invalid`

### 6.2 为什么要有 cache

因为 consumer 不应该关心：

- 当前温度来自离线回放
- 还是来自在线近似器
- 还是来自未来的 HotSpot sidecar service

consumer 只应该读：

- 当前有没有有效温度
- 温度是多少
- 对应哪个 block/layer

## 7. `ThermalConsumerHooks` 合同

建议先定义只读接口，不立刻接行为：

```text
IThermalConsumer
  on_thermal_window(sample_id, thermal_state)
  maybe_get_local_temperature(block_name)
```

第一批 consumer 候选：

- PE compute throttling
- NoC/router pressure throttling
- mapping / placement heuristic
- aging / reliability proxy

### 7.1 为什么先只读

因为当前最危险的事情，是在 thermal state 语义还没冻结前，就直接把温度接进行为控制逻辑。  
这会导致：

- 调试困难
- online/offline 结果不一致
- policy 改动与 thermal interface 改动相互耦合

因此下一阶段应先冻结读取接口，再考虑谁消费它。

## 8. 在线估计器与离线 HotSpot 的协同方式

### 8.1 推荐路线

第一阶段：

- runtime 只产出 `WindowPowerSample`
- 不做真实 HotSpot
- 可选地维护一个极轻量 `ThermalStateCache`

第二阶段：

- 增加在线近似器，例如：
  - EMA/RC compact estimator
  - per-block first-order thermal model

第三阶段：

- 若需要更高保真，再引入 sidecar/异步的 HotSpot 服务
- 但输入仍然是 `WindowPowerSample`

### 8.2 为什么不直接 runtime in-loop HotSpot

因为当前直接这样做的代价太高：

- HotSpot 调用成本高
- 运行时依赖复杂
- 容易阻塞 SST 主仿真
- 调试边界不清晰

当前最合理的做法是：  
让运行时先学会“稳定产出窗口功率样本和消费温度状态”，而不是立刻学会“实时求精确温度”。

## 9. 与当前工件体系的兼容策略

为了避免接口分裂，建议保持如下映射：

- `WindowPowerSample.blocks[*].block_name`
  - 对应 `ptrace` header
- `BlockPowerEntry.power_w`
  - 对应 `ptrace` 某窗口某列值
- `BlockTemperatureState.temperature_c`
  - 对应 `steady.temp` / `tile_temperature_summary.csv`
- `ThermalStateCache.layers[*]`
  - 对应 `thermal_summary.json["layers"]`

这样做的好处是：

- 在线与离线共用 block/layer 命名
- analysis 工具不必重写
- 未来若回放 runtime sample 到离线 HotSpot，也能直接复用现有导出器

## 10. 推荐实施顺序

1. 保持当前离线 `window provenance` / `layer_stack_validation` / `analysis` 语义继续稳定。
2. 在 runtime 侧只抽象 `WindowPowerSample`，暂不做真实求温。
3. 增加 `ThermalStateCache` 的只读接口和 mock source。
4. 先接一个轻量近似热状态源，再决定是否需要 online HotSpot sidecar。
5. 最后再把 throttling / mapping / aging hooks 分批接入。

## 11. 最终建议

下一阶段在线 thermal feedback 的正确起点不是“把 HotSpot 嵌回 SST”，而是：

- 冻结 `WindowPowerSample`
- 冻结 `ThermalStateCache`
- 冻结 `ThermalConsumerHooks`

只要这三层接口稳定，后续无论使用：

- 轻量 RC 模型
- sidecar HotSpot
- 更远期的 `3D-ICE`

都不需要重写当前已经成形的热数据链路。
