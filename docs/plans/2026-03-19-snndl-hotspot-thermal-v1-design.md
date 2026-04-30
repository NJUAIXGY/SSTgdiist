# SnnDL HotSpot Thermal V1 Integration Design

Date: 2026-03-19
Owner: Fufu
Status: Approved

## 1. Background

当前 `SST-SnnDL` 已经具备一部分功耗/能耗侧观测基础，但还没有统一的热后端：

- `MultiCorePE` 已注册多组 SRAM energy 统计，可直接作为片上存储块的热输入。
- `SnnNIC` 已有 `packets/bytes/latency/hops` 等统计，可作为 NoC 动态功耗代理输入。
- DRAM 侧已通过 `Ramulator2 + DRAMPower` 输出 `total_energy / avg_power`，但主要是离线汇总口径，不是按热窗口原生输出。
- 当前仓内没有统一的 `temperature` 状态、热 RC 网络、HotSpot/PACT/3D-ICE 适配层，也没有温度反馈闭环。

本设计的目标不是立即把热模型嵌入 `SnnDL` 主时序，而是先建立一个稳定、可复用、适合后续升级到在线闭环的 `HotSpot V1` 介入方案。

## 2. Design Goals

- 在不改写 `SnnDL` 主时序的前提下，为当前 `2D mesh` 建立稳定的 HotSpot 离线热仿真链路。
- 复用现有 `mesh_template` / `mesh_stats.csv` / DRAM stdout 产物，尽量避免侵入性改动。
- 输出统一的 `floorplan + ptrace + hotspot config + temperature results`，使热图坐标与 mesh 拓扑一一对应。
- 采用固定热窗口的功率轨迹，而不是仅输出整个运行的单点平均功率。
- 为后续第二阶段在线温度接口预留统一的数据模型与目录结构，避免 V1 推倒重来。

## 3. Non-Goals

- V1 不做 HotSpot 在线闭环，不在 SST 仿真运行中实时调用 HotSpot。
- V1 不修改 `MultiCorePE`、`SnnNIC`、`WeightMemorySubsystem` 的主执行语义。
- V1 不尝试精确建模封装、TSV、microfluidic cooling 或 3D 堆叠层间导热。
- V1 不把外部 DRAM cell array 直接并入片上 2D die floorplan。
- V1 不追求 circuit-level 精度，允许对 compute / NoC 动态功耗使用可校准代理模型。

## 4. Chosen Integration Strategy

V1 采用 `mixed-mode, offline-first`：

1. `SST` 负责产生基础统计与运行产物。
2. `thermal_export.py` 在仿真结束后读取统计，按固定热窗口构建 block-level 功率轨迹。
3. `thermal_export.py` 自动生成 HotSpot 输入文件并调用 HotSpot。
4. 温度结果落盘，供后处理、可视化和后续温度反馈接口复用。

该策略的关键优点：

- 对当前主线最小侵入。
- 先把数据口径与 block/floorplan 对齐。
- 后续若要做在线闭环，只需把“窗口功率聚合 + HotSpot 调用”搬到运行时服务层，而无需重做 floorplan、block 命名和结果解析。

## 5. Thermal Modeling Scope for V1

### 5.1 Spatial Scope

V1 只建模当前 `2D compute die` 的片上热分布，核心对象为：

- `PE compute block`
- `PE SRAM block`
- `PE NoC/NIC block`
- 可选 `on-die memory controller block`

不纳入 V1 die floorplan 的对象：

- 外部 DDR/HBM cell array
- 封装外散热器细节
- 板级电源与 IO PHY 复杂结构

外部 DRAM 能耗在 V1 中保留为独立摘要指标，不默认进入 die floorplan。若某个场景明确把 memory controller 视为片上热点来源，可将控制器能耗映射到片边 `dram_ctrl_*` block，但不把 off-chip DRAM 芯粒本体并入同一平面。

### 5.2 Temporal Scope

V1 引入固定热窗口 `thermal_window_ns`，默认建议：

- 默认值：`1000ns` (`1us`)
- 可选值：`100ns / 500ns / 1us / 10us`

每个热窗口输出一行 `ptrace`。每列对应一个 floorplan block，值为该窗口平均功率。

## 6. Block Decomposition

### 6.1 Tile-Level Blocks

每个 mesh tile 默认拆成三个 block：

- `tile_<id>_comp`
- `tile_<id>_sram`
- `tile_<id>_noc`

若某 tile 含独立片上内存控制器，则额外增加：

- `tile_<id>_memctrl`

### 6.2 Rationale

该三块划分是 V1 的最小可用粒度：

- `comp` 表示神经元更新、控制流、算术累加等计算活动。
- `sram` 表示 `state / weight_idx / weight_l0` 等片上存储活动。
- `noc` 表示 NIC + router + link-adjacent 动态活动。

此粒度有三个直接好处：

- 与现有统计天然对齐。
- 便于在 floorplan 上保持规则、重复的 tile 版图。
- 后续升级到更细粒度时，可在 tile 内继续细分，而不改变 tile 坐标体系。

## 7. Power Source Mapping

### 7.1 SRAM Block Power

`tile_<id>_sram` 由现有累计能耗差分得到：

- `weight_idx_sram_energy_{read,write}_pj_total`
- `weight_l0_sram_energy_{read,write}_pj_total`
- `core_state_sram_energy_{read,write}_pj_total`

窗口功率公式：

- `P_sram(window) = delta_energy_pj / delta_t_s / 1e12`

若某运行只提供运行末总量，则 V1 允许先导出 run-level average power，不阻塞链路建立；但推荐第一阶段补齐窗口化导出。

### 7.2 NoC Block Power

`tile_<id>_noc` 采用可校准代理模型：

- 输入优先使用：
  - `packets_sent`
  - `payload_bytes_sent`
  - `total_bytes_sent`
  - `hop_count_sum`
  - `msg_latency_ns`
- 代理模型形式：
  - `E_noc = alpha_pkt * packets + alpha_byte * total_bytes + alpha_hop * hop_count_sum`

其中 `alpha_*` 通过配置给出，V1 不尝试在 C++ 内部实现更细的链路/交换矩阵功耗模型。

### 7.3 Compute Block Power

当前仓内尚无成熟的片上 compute energy 直接统计，因此 `tile_<id>_comp` 采用活动代理模型：

- 优先使用现有 activity/cycle 统计：
  - `sim_cycles_total`
  - `gas_activity_f`
  - `step_activation_*`
- 目标形式：
  - `P_comp(window) = P_idle + alpha_active * active_fraction + alpha_spike * spike_events`

为降低 V1 风险，推荐新增一个最小统计：

- `compute_active_cycles_total`

这样 `comp` 功耗可简化为：

- `active_fraction = delta_compute_active_cycles / delta_sim_cycles`

若第一版不补该统计，则允许退化为：

- `gas_activity_f + spike/activation counters` 的代理估计。

### 7.4 Memory Controller Block Power

若开启 `memctrl` block：

- 优先使用控制器侧可得统计或 DRAM stdout 中的 controller-adjacent 活动代理。
- 若无法获得窗口级能耗，V1 允许只输出 run-average controller power。

默认情况下：

- `memctrl` block 关闭。
- 外部 DRAM 只在最终摘要中保留，不进入 HotSpot die floorplan。

## 8. Floorplan Strategy

### 8.1 Layout Generation

V1 不要求手工维护 `*.flp` 模板。对于规则 `NxN mesh`，由导出工具自动生成 floorplan：

- 每个 tile 占据固定矩形区域。
- tile 内部再按固定比例切分为 `comp / sram / noc`。
- 例如：
  - `comp = 60% width`
  - `sram = 25% width`
  - `noc = 15% width`

支持的配置参数：

- `tile_width_um`
- `tile_height_um`
- `tile_gap_um`
- `comp_frac`
- `sram_frac`
- `noc_frac`

### 8.2 Naming Stability

floorplan block 名称必须与 `ptrace` 列名完全一致，且跨运行稳定：

- `tile_00_comp`
- `tile_00_sram`
- `tile_00_noc`
- `tile_01_comp`
- ...

这样后处理和温度可视化工具可以直接把温度矩阵重新映射回 mesh 坐标。

## 9. Output Directory and Artifacts

建议在每次运行目录下新增：

```text
<run_dir>/thermal/
  effective_thermal_config.json
  hotspot/
    snndl_mesh.flp
    snndl_mesh.ptrace
    hotspot.config
    steady.temp
    transient.temp
    grid.steady
    grid.transient
  summary/
    thermal_summary.json
    tile_temperature_summary.csv
```

其中：

- `effective_thermal_config.json` 记录所有热建模参数与代理系数。
- `snndl_mesh.flp` 为 HotSpot floorplan。
- `snndl_mesh.ptrace` 为按窗口功率轨迹。
- `tile_temperature_summary.csv` 用于把最终热点值映射回 tile/block。

## 10. Runtime and Config Plumbing

V1 在 `mesh_template` 层增加新的配置组：

- `thermal_enable`
- `thermal_backend = hotspot`
- `thermal_window_ns`
- `thermal_out_dir`
- `thermal_hotspot_bin`
- `thermal_generate_floorplan`
- `thermal_tile_width_um`
- `thermal_tile_height_um`
- `thermal_tile_gap_um`
- `thermal_comp_frac`
- `thermal_sram_frac`
- `thermal_noc_frac`
- `thermal_noc_alpha_pkt`
- `thermal_noc_alpha_byte`
- `thermal_noc_alpha_hop`
- `thermal_comp_idle_w`
- `thermal_comp_alpha_active_w`
- `thermal_comp_alpha_spike_j`
- `thermal_include_memctrl`

这些字段只影响导出和后处理，不改变现有 SST 构图和组件行为。

## 11. Data Flow

### 11.1 V1 Data Path

1. `mesh_template.build/runtime` 把热配置写入 `effective_config.json`。
2. 仿真运行，输出：
   - `mesh_stats.csv`
   - `stdout.log`
   - 现有 summary/stats 产物
3. `thermal_export.py` 读取这些产物。
4. 将累计统计按窗口重采样或差分，形成 block-level power trace。
5. 自动生成 `flp/ptrace/config`。
6. 调用 HotSpot。
7. 解析温度结果，输出 `tile_temperature_summary.csv` 与 JSON 摘要。

### 11.2 Why Not Embed into SST Now

V1 不在 `finish()` 或 runtime service 内直接执行 HotSpot，原因是：

- HotSpot 依赖与运行环境应先独立稳定。
- SST 仿真失败与热后处理失败应解耦。
- 初期更容易复跑不同热参数，不必重跑整个 SST 仿真。

## 12. Required Minimal Instrumentation Changes

V1 尽量复用现有统计，但建议补两类最小增强：

### 12.1 Strongly Recommended

- `compute_active_cycles_total`
  - 用于把 `comp` block 代理功耗从“拍脑袋事件数”提升到“活动周期占比”。

### 12.2 Optional

- 窗口化 SRAM energy 导出
- 控制器窗口活动统计
- router/NIC 更直接的 flit-level activity counters

若短期不补这些统计，V1 依然可以跑通，但 `comp/noc` 的物理可信度会弱一些。

## 13. Verification Plan

### 13.1 Functional Verification

- 验证 `thermal_enable=0` 时，现有仿真行为与输出不变。
- 验证 `thermal_enable=1` 时，新增 `thermal/` 目录及 HotSpot 输入输出文件。
- 验证 `ptrace` 列名与 `flp` block 名称严格一致。
- 验证 4x4 mesh 每个 tile 都能在温度汇总表中找到对应 block。

### 13.2 Sanity Checks

- 全零活动场景下，温度应趋近环境温度。
- 人工放大单个 tile 的功率代理后，该 tile 应成为热点。
- 对称 workload 下，温度图应近似对称。
- 提高 `sram` 代理能量系数后，应主要抬升 `tile_*_sram` 热点。

### 13.3 Regression Scope

- 单 PE smoke
- 4x4 baseline mesh
- 4x4 GAS mesh

三者都应可生成 HotSpot 结果，不要求第一版就完成闭环调速。

## 14. Risks and Mitigations

### 14.1 Compute Power Proxy Too Weak

风险：

- `comp` 块若仅依赖少量高层事件，温度图会偏向 SRAM/NoC。

缓解：

- 最小新增 `compute_active_cycles_total`。
- 保持代理系数可配置，并通过 microbench 做校准。

### 14.2 DRAM Not Windowed

风险：

- 外部 DRAM 平均功率无法反映瞬态热点。

缓解：

- V1 默认不把 off-chip DRAM 纳入 die floorplan。
- 后续单独做 `controller thermal` 或 3D memory thermal 版本。

### 14.3 Floorplan Geometry Arbitrary

风险：

- 若 tile 内块宽度纯经验设置，绝对温度会受影响。

缓解：

- V1 重点追求热点相对分布和趋势。
- 将 tile/block geometry 全部参数化，后续可替换成真实面积估计。

## 15. Future Upgrade Path

### 15.1 V2: Online Thermal API

在保持 block 命名和窗口语义不变的前提下，引入：

- `ThermalManager`
- 在线窗口功率累计
- 运行中 HotSpot 调用或等效 RC solver
- 温度结果回写到 PE/NoC throttling hooks

### 15.2 V3: 3D-Ready Migration

当系统升级到 3D stack/chiplet 时：

- 保留 block/power trace 接口
- 把 HotSpot 后端替换为 `3D-ICE`
- 扩展 floorplan 为 `layer/stack` 感知结构

这样 V1 的大部分导出与配置接口仍可复用。

## 16. Recommended Implementation Phases

### Phase 0

- 补 `mesh_template` 热配置
- 实现 `thermal_export.py`
- 自动生成 `flp + ptrace`
- 跑通 HotSpot 离线链路

### Phase 1

- 新增 `compute_active_cycles_total`
- 提升 `comp` block 可信度
- 完善温度摘要与可视化

### Phase 2

- 研究在线窗口聚合
- 预留 throttling hooks
- 为后续在线闭环与 3D 升级做接口冻结

## 17. Final Recommendation

对当前 `SnnDL + SST + 2D mesh` 主线，最稳的落地方式是：

- `V1 用 HotSpot 做 offline-first 热后端`
- `统一 block/floorplan/ptrace 接口`
- `只补最小必要统计`
- `不在第一版修改主时序`

这条路线既能最快产出热图和热点分析，也能为后续温度反馈和 3D 热仿真保留升级空间。
