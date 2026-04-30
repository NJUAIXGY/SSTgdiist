# SnnDL Thermal Analysis Status Deep Dive

Date: 2026-03-20
Owner: Fufu
Status: Current-state deep dive

## 1. 结论先行

当前 `SnnDL` 的热分析链路已经不再是概念设计，而是已经形成了可正式产出数据的 `HotSpot offline-first` 方案：

- `mesh_template -> run_dir -> thermal_export.py -> HotSpot -> thermal_summary/analyze_thermal_runs.py` 的主链路已经闭环。
- `2D mesh` 已可稳定导出规则 floorplan 与功率轨迹。
- `3D` 已具备最小可用的 layered/grid 方案，能够生成 `LCF + per-layer FLP + ptrace`，并做 layer-stack 一致性校验。
- 真实 formal run 已经产出可复现的 `thermal_summary.json`、`tile_temperature_summary.csv`、`steady.temp/grid.steady` 等工件。
- analysis 侧已经能把多 run 的热结果统一导出为 CSV/JSON，并对 `3D stack validation` 做批量汇总。

当前最重要的事实不是“能不能跑热仿真”，而是：

1. 已经能正式产出热仿真相关数据。
2. 当前路线明确是 `offline-first`，还不是 runtime in-loop 的温度反馈系统。
3. 下一阶段最关键的增量不再是“把链路跑通”，而是“增强窗口级功耗语义、3D 校验深度和后续在线接口稳定性”。

## 2. 当前热分析的总体定位

### 2.1 目标定位

当前热分析系统服务于两类需求：

- 为 `2D mesh` 提供可复现、可批处理的热点分析与温度摘要。
- 为后续 `3D stack`、温度反馈闭环、甚至 `3D-ICE` 后端切换保留稳定的数据接口。

### 2.2 当前路线

当前正式采用的是：

- `HotSpot`
- `offline-first`
- `artifact-driven`
- `window-capable but not runtime feedback`

也就是说，SST/SnnDL 主仿真负责产出统计和运行产物，热求解在 run 结束后由 `thermal_export.py` 离线完成；热求解失败不会反向破坏主仿真完成状态。

### 2.3 当前不是的东西

当前系统还不是：

- runtime 每个 window 都在线回写温度的闭环热仿真器
- 带封装、TSV、interposer、sink/spreader 全物理细节的 3D 热平台
- 多后端统一热框架
- 完整的 per-source/per-window 物理功耗模型

## 3. 当前架构总览

当前热分析主链路可以概括为：

1. `mesh_template` 接收 `thermal` 配置，并把归一化后的热配置写入 `effective_config.json`。
2. SST/SnnDL 正常运行，产出：
   - `mesh_stats.csv`
   - `stdout.log`
   - 可选 `peXX/coreYY_window_metrics.csv`
   - 以及 spec 中声明的 `power_source` 辅助输入
3. `thermal_export.py` 读取 run 目录与有效配置，构造：
   - floorplan / LCF
   - `ptrace`
   - `hotspot.config`
4. `thermal_export.py` 调用 `HotSpot`，解析 `steady.temp` / `grid.steady` 等输出。
5. `thermal_export.py` 回写热摘要：
   - `thermal_summary.json`
   - `tile_temperature_summary.csv`
   - `layer_stack_validation.json`（若为分层 3D）
6. `analyze_thermal_runs.py` 对一个或多个 run 做批量汇总，导出统一分析表。

这条链路的关键优点是：

- 与 SST 主时序解耦，侵入性低。
- 工件稳定，可复跑、可比较、可归档。
- 已经为后续在线化预留了稳定的中间层：`window power sample -> ptrace -> thermal summary`。

## 4. 数据链路细解

## 4.1 配置入口层

当前热分析的配置入口已经在 `mesh_template` 层打通，热配置会经过：

- spec
- legacy defaults
- env/local override
- runtime mesh cfg
- `effective_config.json`

当前已经稳定下沉的关键字段包括：

- `thermal.enable`
- `thermal.backend`
- `thermal.window_ns`
- `thermal.out_dir`
- `thermal.hotspot_bin`
- `thermal.hotspot_model_type`
- `thermal.window_trace_enable`
- `thermal.window_trace_max_rows`
- 以及 floorplan / grid / layer / power_source 相关字段

这意味着“当前 run 实际使用了什么热配置”已经可以在 run 目录中追溯，而不再依赖外部命令行或环境变量猜测。

## 4.2 原始运行输入层

当前热导出器会消费三类原始输入：

### A. 统计型输入

- `mesh_stats.csv`
- 必要时配合 `stdout.log`

它们主要服务于：

- `mesh_proxy`
- `stats_prefix`
- 平均功率路径

### B. 窗口型输入

- `peXX/coreYY_window_metrics.csv`
- 不存在时可退回历史 `peXX/window_metrics.csv`

它们主要服务于：

- 多窗口 `ptrace`
- `trace_mode=windowed`

### C. 外部供电/显式表输入

- `power_source.type=csv`
- `power_source.type=stats_prefix`
- `power_source.type=mesh_proxy`
- `power_source.type=none`

这让当前系统已经支持“不同层由不同功耗来源驱动”的热实验，而不要求所有层都只靠一条统一统计链路。

## 4.3 热导出层：`thermal_export.py`

`thermal_export.py` 当前承担了整个热管线里最核心的“语义压缩”工作。

它负责把仿真统计整理成 HotSpot 可消费的热输入，并把热结果重新映射回 SnnDL 的 tile/layer 语义。

### 当前已经具备的核心职责

- 解析 `effective_config.json`
- 推断 `tile_count` / `mesh_size`
- 生成稳定 block 命名
- 生成 `2D block` 或 `3D layer/grid` 热工件
- 组装 `ptrace`
- 调用 HotSpot
- 解析温度输出
- 导出 summary / csv / validation

### 当前 block/layer 命名稳定性

当前命名体系已经稳定到可被后续工具直接依赖：

- 2D/层内 block 采用 `tile_<id>_{comp,sram,noc}` 风格
- 3D 输出会带层前缀，例如：
  - `L00_compute_top__tile_00_comp`
  - `L02_csv_bottom__tile_14_comp`

这点非常重要，因为它保证了：

- `ptrace` 列
- HotSpot 温度输出 block 名称
- `tile_temperature_summary.csv`
- analysis 导出

之间已经可以一一对齐，不需要额外再做一次名称映射。

## 4.4 HotSpot 求解层

当前已正式接通本地 HotSpot，可生成并消费如下工件：

- `hotspot.config`
- `snndl_mesh.ptrace`
- `steady.temp`
- `transient.temp`
- `grid.steady`
- `grid.transient`

对于 3D layered/grid 场景，当前还会生成：

- `snndl_mesh.lcf`
- `layer_XX_<name>.flp`

这说明当前系统已经不是只会导出前处理文件，而是真正完成了热求解，并把结果重新带回本仓库的摘要体系。

## 4.5 摘要与分析层

当前热求解后的标准摘要接口已经成形，核心包括：

- `thermal/summary/thermal_summary.json`
- `thermal/summary/tile_temperature_summary.csv`
- `thermal/summary/layer_stack_validation.json`（3D 时）

此外，批量分析统一走：

- `sst_dram_si/tools/analyze_thermal_runs.py`

它当前会导出：

- `run_summary.csv`
- `layer_summary.csv`
- `top_blocks.csv`
- `thermal_analysis.json`
- `layer_stack_validation_runs.csv`
- `layer_stack_validation_fail_layers.csv`

这意味着“单 run 温度结果”与“多 run 热实验比较”现在已经被正式拆成两层接口，而不是混在一个 JSON 里临时用。

## 5. 当前已经正式支持的能力

## 5.1 2D mesh 热分析

当前已经稳定支持：

- 规则 mesh 的自动 floorplan 生成
- `comp / sram / noc` 三类 block 划分
- HotSpot 输入工件导出
- steady/grid 温度求解
- tile/block 级温度摘要

这已经足够支撑当前 `2D mesh` 的热点定位、层/块功耗对比和不同功耗来源的实验对照。

## 5.2 最小可用 3D layered/grid 热分析

当前 3D 方向已经具备：

- 多 layer 配置
- per-layer `power_source`
- `LCF + per-layer FLP`
- `grid` 模式 HotSpot 求解
- 分层温度摘要
- `layer_stack_validation`

但这里的 3D 语义必须说清楚：

- 当前是“layered thermal geometry”
- 不是“完整 3D package/stack physics”

也就是说，当前已经能做分层热点分析和层间功耗驱动实验，但还没有进入 TSV、封装散热器、封装材料全参数一致性研究。

## 5.3 多来源功耗建模

当前已经正式支持以下来源：

- `mesh_proxy`
- `stats_prefix`
- `csv`
- `none`

其中：

- `mesh_proxy` 主要走仓内统计推导路径
- `stats_prefix` 允许显式绑定统计前缀
- `csv` 允许外部表直接供电
- `none` 允许被动层存在但不出功率

这个能力对后续 3D 很关键，因为它允许不同层采用不同功耗语义，而不强迫所有层都复用一个代理模型。

## 5.4 窗口化热轨迹

当前已经从“单行平均功率导出器”升级为真正支持：

- `trace_mode=average`
- `trace_mode=windowed`

相关字段已经进入 `thermal_summary.json`：

- `trace_mode`
- `window_count`
- `window_source`
- `window_duration_ns`
- `ptrace_row_count`

真实 windowed run 已经验证：

- `trace_mode=windowed`
- `window_count=2`
- `window_source=window_metrics`
- `snndl_mesh.ptrace` 实际出现多行功率数据

当前窗口化的本质是：

- 用 `window_metrics` 对平均功率做时间展开
- 保持时间平均回到原平均功率口径

这是当前最合理的最小可用方案，但还不是最终的高保真 per-source/per-window 能耗模型。

## 5.5 provenance 与语义硬化

当前热摘要已经具备最小但很关键的 provenance 字段：

- `power_source_contract_version = "v1"`
- `cycle_model_applicable`

其中最关键的变化是：

- `cycle_model_applicable=True` 现在不再只是“理论上这个层可以用 cycle model”
- 而是已经收紧为“该 block/layer 实际使用了 cycle-derived counter”

当前边界已经很清楚：

- `csv` / `none` 不会被伪装成 cycle-derived
- `stats_prefix` 也只有在真正满足相应条件时才会被标为 applicable

这对后续论文、批处理分析和模型解释都很重要，因为它避免了“输出字段看起来很强，但其实语义是空的”。

## 5.6 3D layer-stack 校验

当前 `thermal_export.py` 已经输出：

- `layer_stack_validation.json`
- `thermal_summary.json["layer_stack_validation"]`
- `thermal_summary.json["artifacts"]["layer_stack_validation"]`

analysis 端进一步支持：

- `run_summary.csv` 中的 stack validation 结果平铺
- `thermal_analysis.json["layer_stack_validation_summary"]`
- `layer_stack_validation_runs.csv`
- `layer_stack_validation_fail_layers.csv`

这意味着当前 3D 热分析已经不只是“能求温度”，而是已经能批量回答：

- 哪些 run 的 layer stack 配置合法
- 哪些 run 失败
- 失败原因落在哪些 layer 上

对之后参数 sweep 或 next-arc 3D 实验来说，这套接口已经足够作为正式基础设施使用。

## 5.7 批量分析与过滤视图

`analyze_thermal_runs.py` 当前支持：

- 多个 `--run-dir`
- `--nonzero-power-only`
- `--active-layers-only`

这解决了一个很实际的问题：

- passive TIM 层虽然可能有温度，但不应该干扰热点功耗归因

当前过滤已经统一作用于：

- `run_summary.csv`
- `layer_summary.csv`
- `top_blocks.csv`

这让结果更适合直接拿去做 sweep 汇总、plot 和透视。

## 6. 当前标准工件与字段接口

## 6.1 单 run 标准工件

当前一个成功热 run 的标准工件集合大致是：

```text
<run_dir>/
  effective_config.json
  mesh_stats.csv
  peXX/coreYY_window_metrics.csv         # 可选
  thermal/
    effective_thermal_config.json
    hotspot/
      hotspot.config
      snndl_mesh.ptrace
      steady.temp
      transient.temp
      grid.steady
      grid.transient
      snndl_mesh.lcf                     # 3D 时
      layer_XX_*.flp                     # 3D 时
    summary/
      thermal_summary.json
      tile_temperature_summary.csv
      layer_stack_validation.json        # 3D 且启用校验时
```

## 6.2 多 run analysis 标准工件

当前批量分析的标准输出是：

```text
<analysis_out_dir>/
  run_summary.csv
  layer_summary.csv
  top_blocks.csv
  thermal_analysis.json
  layer_stack_validation_runs.csv
  layer_stack_validation_fail_layers.csv
```

## 6.3 当前最重要的摘要字段

`thermal_summary.json` 中，当前最重要的字段包括：

- `backend`
- `hotspot_model_type`
- `trace_mode`
- `window_count`
- `window_source`
- `window_duration_ns`
- `ptrace_row_count`
- `power_source_contract_version`
- `cycle_model_applicable`
- `temperature_c`
- `layers[*].cycle_model_applicable`
- `layer_stack_validation`

`run_summary.csv` 中，当前最重要的批处理字段包括：

- `trace_mode`
- `window_count`
- `hotspot_status`
- `layer_stack_validation_status`
- `layer_stack_validation_passed`
- `layer_stack_validation_mismatch_count`
- `layer_stack_validation_mismatch_reasons`
- `total_power_w`
- `hottest_block_name`
- `hottest_layer_name`

## 7. 当前真实产物证据

## 7.1 3D formal run：`stats_prefix`

真实 run：

- `/home/xgy/remote/tmp/hotspot_formal_spec_3d_stats_prefix_v1/20260319-135209`

关键结果：

- `backend=hotspot`
- `hotspot_model_type=grid`
- `trace_mode=average`
- `window_count=1`
- `cycle_model_applicable=true`
- `layer_count=3`
- `tile_count=16`
- `hotspot.status=ran`
- `layer_stack_validation.status=passed`

热工件目录已包含：

- `snndl_mesh.lcf`
- `layer_00_cycles_top.flp`
- `layer_01_tim_mid.flp`
- `layer_02_noc_bottom.flp`
- `snndl_mesh.ptrace`
- `steady.temp`
- `grid.steady`
- `layer_stack_validation.json`

## 7.2 3D formal run：`csv`

真实 run：

- `/home/xgy/remote/tmp/hotspot_formal_spec_3d_csv_v1/20260319-135033`

关键结果：

- `backend=hotspot`
- `hotspot_model_type=grid`
- `trace_mode=average`
- `window_count=1`
- `cycle_model_applicable=true`
- `hotspot.status=ran`
- `layer_stack_validation.status=passed`

这条 run 很重要，因为它证明当前系统已经能把“外部 CSV 供电层”纳入统一 3D 热导出与求解链路。

## 7.3 真实 windowed run

真实 run：

- `/home/xgy/remote/tmp/hotspot_windowed_trace_task2/20260319-153802`

关键结果：

- `trace_mode=windowed`
- `window_count=2`
- `window_source=window_metrics`
- `window_duration_ns=1000`
- `hotspot.status=ran`

对应 `ptrace` 已实际出现：

- 1 行 header
- 2 行功率数据

这条 run 证明当前热链路已经真正具备时间维度，而不是只有整次 run 平均功率。

## 7.4 真实 analysis export

真实 analysis 输出：

- `/home/xgy/remote/tmp/hotspot_thermal_analysis_export_with_stack_summary`

当前目录已包含：

- `run_summary.csv`
- `layer_summary.csv`
- `top_blocks.csv`
- `thermal_analysis.json`
- `layer_stack_validation_runs.csv`
- `layer_stack_validation_fail_layers.csv`

真实 formal 3D runs 当前都 `passed`，所以：

- `layer_stack_validation_runs.csv`
- `layer_stack_validation_fail_layers.csv`

在真实目录里是 `header-only`

这是预期行为，不是缺数据或脚本错误。

## 8. 当前语义边界与已知限制

## 8.1 仍然是 offline-first，不是在线热反馈

当前最根本的限制是：

- 热求解发生在 run 结束后
- 温度不会在 SST 运行期间反馈给 PE/NoC/调度逻辑

所以当前系统适合：

- 热分布研究
- 参数 sweep
- 功耗来源对比
- next-stage 接口设计

但还不适合直接声称“已经具备 runtime thermal throttling”。

## 8.2 当前 windowed 仍是最小代理模型

当前 `windowed ptrace` 的时间展开依赖 `window_metrics` 权重归一化，而不是完整的窗口级物理能耗统计。

这意味着：

- 已经能看时间变化趋势
- 但还不能把它等同于“严格物理保真的逐窗能耗模型”

尤其是：

- `csv` 层当前保持跨窗口常量
- 并不会因为 `window_metrics` 被错误缩放

这是刻意保留的语义边界。

## 8.3 `cycle_model_applicable` 不等于“所有层都是真实 cycle model”

当前该字段已经强化，但仍要正确理解：

- 它表达“实际使用了 cycle-derived counter”
- 不表达“整个 run 的所有功耗都来自 cycle-accurate 物理模型”

这对当前混合来源场景尤其重要，因为一个 run 里可能同时存在：

- `mesh_proxy`
- `stats_prefix`
- `csv`
- `none`

## 8.4 3D 仍是 layered geometry，不是完整封装热系统

当前 3D 的能力重点在：

- 分层 FLP/LCF
- 分层 power source
- 分层摘要与校验

尚未完整覆盖：

- package / sink / spreader 全量一致性
- TSV / interposer / bump 等物理结构
- 更复杂的封装边界条件建模

所以当前更准确的描述是：

- `3D-ready thermal interface`
- 而不是 `full-stack 3D package thermal simulator`

## 8.5 当前只有 HotSpot 后端正式接通

虽然 schema/规划里已经为未来扩展保留空间，但当前真正落地并验证的后端只有：

- `HotSpot`

`3D-ICE`、更多 RC/封装后端都还没有进入当前实现批次。

## 8.6 最小 `memctrl` 热块尚未进入正式能力面

下一阶段路线图里已经明确提到 `memctrl` block 是后续任务，但现在仍未成为正式稳定能力。

所以当前主热点对象仍然是：

- `comp`
- `sram`
- `noc`
- 以及分层 power source 本身

## 9. 对 next arc 最应该保持稳定的接口

如果接下来继续推进热分析，当前最值得保护、不要轻易打破的是以下接口：

### 1. `effective_config.json["thermal"]`

这是“当前 run 到底怎么配热分析”的唯一正式事实来源。

### 2. block/layer 命名体系

例如：

- `tile_00_comp`
- `L02_csv_bottom__tile_14_comp`

命名一旦变化，会同时影响：

- `ptrace`
- HotSpot 输出
- summary CSV
- analysis 脚本

### 3. `thermal_summary.json` 的顶层合同

尤其是：

- `trace_mode`
- `window_count`
- `window_source`
- `power_source_contract_version`
- `cycle_model_applicable`
- `layer_stack_validation`

### 4. analysis CSV 字段

尤其是：

- `run_summary.csv`
- `layer_summary.csv`
- `top_blocks.csv`
- `layer_stack_validation_runs.csv`
- `layer_stack_validation_fail_layers.csv`

这些字段已经开始具备 sweep/plot/论文表格消费价值，后续宜增量扩展，不宜频繁改名。

## 10. 下一步任务建议

## 10.1 P0/P1 方向里最值得继续做的事

### A. 强化窗口级 provenance

当前最值得优先推进的是：

- 把“窗口化展开”继续从最小代理模型升级为更强的 per-source/per-window provenance

目标不是立刻做 runtime 闭环，而是让每个 window 的功耗来源更可解释。

### B. 扩展 3D stack validation 深度

当前已做的是 layer stack 基本一致性，下一步最合理的是补：

- package / sink / spreader 参数
- `grid_rows / grid_cols / map_mode`
- 更细的 floorplan path / block prefix 定位信息

### C. 最小 `memctrl` 热块

这是下一步把“纯 mesh 热图”推进到“compute + on-die memory edge”热图的最小增量。

## 10.2 为未来 online feedback 做准备，但不要现在混进去

当前最合理的策略仍然是：

- 先稳住 offline 数据接口
- 再抽象 runtime `window power sample` 接口
- 最后才考虑温度回写和 throttling hook

也就是说，当前 next arc 应该先做“接口冻结和语义硬化”，而不是直接把温度塞进运行时。

## 10.3 3D 后端扩展应晚于语义稳定

如果后面要引入 `3D-ICE` 或其他后端，建议前提是：

- 现有 `window` 语义稳定
- `power_source` provenance 稳定
- `layer_stack_validation` 稳定

否则会把“后端切换问题”和“输入语义不稳问题”混在一起，排查成本很高。

## 11. 当前状态的最终判断

截至 2026-03-20，当前热分析工作已经处于“第一阶段已完成，第二阶段可系统推进”的状态：

- 第一阶段完成的不是纸面设计，而是正式可运行、可产出、可分析的 HotSpot 热链路。
- 第二阶段要解决的已经不是“有没有热数据”，而是“如何让窗口级语义、3D 校验和未来在线接口更强、更稳、更可解释”。

因此，对外或对内描述当前状态时，最准确的说法应当是：

- `SnnDL 已经具备正式可产出的 HotSpot offline thermal analysis pipeline`
- `支持 2D mesh 与最小 3D layered/grid 热分析`
- `支持 average/windowed trace 与批量 analysis export`
- `尚未进入 runtime thermal feedback / full-stack 3D package modeling 阶段`
