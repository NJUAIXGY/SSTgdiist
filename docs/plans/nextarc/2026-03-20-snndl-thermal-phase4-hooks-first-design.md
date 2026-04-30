# SnnDL Thermal Phase 4 Hooks-First Design

Date: 2026-03-20
Owner: Fufu
Status: Draft

## 1. 背景

当前仓内热链路已经完成 `Phase3` 收口：

- `sst_dram_si/tools` 侧已经具备 `v2` thermal contract、`WindowPowerSample` 工件、canonical thermal contract suite。
- `snn3dexp/thermal/state_cache.py` 已经提供 replay-only `ThermalStateCache`，可以从离线 HotSpot 结果回放 block/layer 温度。
- `snn3dexp/runtime/policy.py` 已经存在 `adaptive_3d` runtime summary，但当前消费的 thermal 信号仍来自 proxy/joint summary，而不是统一的只读热状态接口。

这意味着我们已经有了“热数据会产出”和“热状态可回放”的基础，但还没有一层稳定的运行时消费桥，把：

- `WindowPowerSample`
- `ThermalStateCache`
- runtime / mapping / reliability consumer

正式连接起来。

因此 `Phase4` 的正确起点不是直接把温度接进行为闭环，而是先冻结只读消费接口，并提供一个最小在线 mock 热估计器，验证：

1. thermal 数据模型是否足够支撑运行时消费；
2. runtime consumer 是否能在不依赖 HotSpot 的情况下读取热状态；
3. 后续若接 `RC compact model / sidecar HotSpot / throttling`，是否仍可复用同一套接口。

## 2. 目标与非目标

### 2.1 目标

本阶段采用 `Hooks优先` 路线，目标是：

1. 新增统一的 `ThermalConsumerHooks` 只读接口。
2. 新增一个极轻量 `online_rc_estimator` mock source，输入为 `WindowPowerSample`，输出为 `ThermalStateCache`。
3. 让现有 `runtime.policy` / `build_platform_summary` 能在不改变行为闭环的前提下，消费统一 thermal state。
4. 让 `offline_hotspot_replay` 与 `online_rc_estimator` 两种来源共用相同 block/layer 命名与读取 API。

### 2.2 非目标

本阶段明确不做：

- 真实 runtime in-loop `HotSpot`
- 把热状态直接接进 SST 组件内部执行语义
- 真正执行 remap / throttle / route rewrite
- 构建高保真 RC 参数标定器
- 完整 3D-ICE / multi-backend thermal solver 抽象

## 3. 方案对比

### 方案 A：Hooks 优先，推荐

先定义统一只读接口，再加 mock estimator，让 runtime summary 通过统一 thermal state 读取信号。

优点：

- 风险最低；
- 与当前 `Phase3` 的 contract 收口逻辑一致；
- 后续更容易替换成更高保真 estimator 或 sidecar solver；
- 不会把 thermal contract 与 runtime 行为决策耦合。

缺点：

- 这一阶段用户可见行为变化较小；
- 主要价值在接口稳定性和后续扩展性。

### 方案 B：直接把 state cache 接进 runtime policy

让 `runtime.policy` 直接依赖 `ThermalStateCache`，但不立即执行 remap。

优点：

- 更快看到 runtime 信号链统一。

缺点：

- 还没有抽象 consumer hook，就先把 policy 绑定到 thermal source；
- 后续若接其他 consumer，会更难拆分职责。

### 方案 C：直接行为闭环

直接把 thermal state 接进 adaptive policy 动作执行。

优点：

- 表面推进最快。

缺点：

- 当前阶段风险最高；
- online/offline 一致性和调试边界都还不够稳定。

结论：本阶段采用方案 A。

## 4. 核心设计

### 4.1 新增逻辑层

在 `snn3dexp/thermal/` 下新增三层结构：

1. `consumer.py`
   - 定义只读消费接口和统一 thermal signal 提取逻辑。
2. `estimator.py`
   - 定义最小 `online_rc_estimator` mock。
3. `signals.py`
   - 定义从 `ThermalStateCache` 抽取 runtime 可消费指标的 helper。

其中职责边界如下：

- `state_cache.py`
  - 负责存储和查询 block/layer 温度状态。
- `estimator.py`
  - 负责从 `WindowPowerSample` 生成新的 thermal state。
- `signals.py`
  - 负责把 block/layer 状态压缩成 runtime 可读指标。
- `consumer.py`
  - 负责向外暴露统一的 hooks 和 consumer snapshot。

### 4.2 ThermalConsumerHooks 合同

本阶段建议暴露一个最小接口：

```text
ThermalConsumerSnapshot
  sample_id
  source
  block_temperatures[]
  layer_temperatures[]
  signals

signals
  peak_temperature_c
  avg_temperature_c
  hotspot_block_count
  hotspot_layer_count
  vertical_gradient_c
  top_layer_peak_c
  bottom_layer_peak_c
```

对外 API 建议为：

```text
build_thermal_consumer_snapshot(thermal_state)
get_runtime_thermal_signals(thermal_state)
```

这些 API 只读，不做行为决策。

## 5. Mock RC Estimator 设计

### 5.1 输入

输入直接复用 `WindowPowerSample` 工件语义：

- `sample_id`
- `duration_ns`
- `blocks[*].power_w`
- `blocks[*].block_name/layer_name/layer_index`

### 5.2 输出

输出为新的 `ThermalStateCache`：

- `source = online_rc_estimator`
- `sample_id = 当前窗口 sample_id`
- `blocks/layers` 温度由一个简单一阶模型生成

### 5.3 最小估计模型

第一版不追求物理精度，只追求接口稳定和量纲合理。建议使用：

```text
next_temp = ambient_c + alpha * power_w + beta * previous_delta
```

其中：

- `alpha`：把功率映射到温升的简化系数
- `beta`：保留前一窗口热惯性的简化系数

默认策略：

- block 温度先估计；
- layer 温度再由 block 聚合：
  - `avg`
  - `peak`
  - `min`

这样可以保证 estimator 与 offline replay 共用同一 `ThermalStateCache` 结构。

## 6. 与现有 runtime 链路的接法

### 6.1 接入位置

当前最合适的接入点不是 SST 内核，而是 `snn3dexp/platform/build_system.py` 与 `snn3dexp/runtime/policy.py` 的 summary 路径。

建议新增以下模式：

1. `build_platform_summary(...)`
   - 仍然生成当前 `thermal` proxy summary；
   - 可选地生成一个 `thermal_consumer_snapshot`；
   - 再把 snapshot 派生出的热信号传给 runtime summary。

2. `build_runtime_summary(...)`
   - 新增可选参数：
     - `thermal_state`
     - `thermal_signals`
   - 若传入则优先使用 hooks/signals；
   - 若未传入则继续 fallback 到当前 `thermal_summary` 字段。

### 6.2 为什么这样接

这样可以做到：

- 不破坏现有 `runtime.policy` 测试和输出字段；
- `adaptive_3d` 仍然只消费数字信号；
- 但 thermal signal 的来源从“proxy summary 特定字段”升级为“统一 thermal state -> signals”。

这一步是典型的“依赖倒置”收口：policy 不再隐式依赖某个热求解实现。

## 7. Phase4 分步实施建议

### Phase4-A：接口冻结

- 新增：
  - `snn3dexp/thermal/consumer.py`
  - `snn3dexp/thermal/signals.py`
- 更新：
  - `snn3dexp/thermal/__init__.py`
- 目标：
  - 定义 consumer snapshot
  - 定义 thermal signals 提取逻辑

### Phase4-B：mock estimator

- 新增：
  - `snn3dexp/thermal/estimator.py`
- 目标：
  - 从 `WindowPowerSample` 构造 `online_rc_estimator` 来源的 `ThermalStateCache`

### Phase4-C：runtime summary 接桥

- 修改：
  - `snn3dexp/runtime/policy.py`
  - `snn3dexp/platform/build_system.py`
- 目标：
  - runtime summary 优先消费 thermal signals，而不是直接读 proxy 字段
  - 但保持旧字段 fallback

### Phase4-D：轻量 case / analysis 验证

- 新增或更新测试：
  - `test_thermal_*`
  - `test_runtime_3d_policy.py`
  - `test_run_case.py`
- 目标：
  - 验证 source=`offline_hotspot_replay` 与 source=`online_rc_estimator` 两条路径都能产出同构 thermal signals

## 8. 测试策略

建议仍采用 TDD，优先覆盖以下行为：

1. `WindowPowerSample -> ThermalStateCache(online_rc_estimator)`
2. `ThermalStateCache -> ThermalConsumerSnapshot`
3. `ThermalStateCache -> runtime thermal signals`
4. `build_runtime_summary(...)` 在有 `thermal_signals` 时优先消费 hooks 路径
5. 无 hooks 时保持旧 `thermal_summary` fallback 不回退

真实 smoke 第一版不要求接 SST runtime，只要求：

- Python summary 链完整；
- 现有 `full_3d_runtime_adaptive` case 的 summary 可带出新的 thermal signal source；
- 不改变已有 `thermal_guard_actions` 的断言口径。

## 9. 风险与控制

主要风险有三类：

1. `ThermalStateCache` 与 proxy summary 双轨并存，造成信号不一致。
   - 控制：runtime 只消费 signals helper，禁止在 policy 内部直接拼 thermal 字段。
2. mock estimator 过度设计。
   - 控制：第一版只做一阶模型，不引入复杂 RC 网络参数。
3. 接口过早耦合行为闭环。
   - 控制：本阶段只产出 signals 和 snapshot，不做 action executor。

## 10. 最终建议

`Phase4` 应严格保持“hooks-first, read-only”路线：

1. 先冻结 consumer hooks 与 thermal signals；
2. 再补 mock RC estimator；
3. 再把 runtime summary 切到统一 thermal signals；
4. 最后才讨论 throttle/remap/aging 的真实行为接入。

这样做可以保证：

- `Phase3` 刚冻结的 thermal contract 不会立刻再次漂移；
- `runtime.policy` 的演进建立在统一接口之上；
- 后续 2D/3D、offline/online、HotSpot/RC 都能在同一数据模型里演进。
