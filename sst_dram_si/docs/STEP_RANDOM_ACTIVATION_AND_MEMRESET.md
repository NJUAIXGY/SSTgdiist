# 步级随机发放与膜电位重置功能说明（strict GAS + simpleMem）

本文档说明当前在 Single‑PE 测试框架中新增的“两项可选能力”：
- 步级随机发放（per‑step random activation injection）
- 步末膜电位重置（reset membrane potential at end of step）

涵盖：功能设计、代码位置、参数与默认值、使用方法、注意事项，以及当前已知问题与改进方向。适用范围：sst_dram_si/test_dram_si_single_pe.py + SnnDL 组件（simpleMem 后端，BCSR 权重）。

## 1) 功能概述

- 步级随机发放（随机激活）
  - 在每个 GAS 超步（BeginGather 事件）开始时，对全局神经元集合按给定概率 fraction 进行伯努利抽样，形成本步“随机激活”的 pre 集合；每个 pre 再按 fanout 均匀采样若干 post，构造 (pre→post) 脉冲事件立即注入至目标核心。
  - 该机制不依赖前一超步 Scatter 发放结果，步间严格独立；用于稳定注入“每步固定激活率”的输入流进行链路与负载压测。

- 步末膜电位重置（步间独立）
  - 在每步 EndScatter 事件后，将所有核心神经元的膜电位 v_mem、不应期 refractory 与最后发放时间 last_spike_time 复位为静息电位 v_rest 与 0，确保下一步的动力学状态不受上一步影响。

两项能力均为可选开关，默认关闭；严格 GAS 语义（Apply 仅读权重、Scatter 统一应用 ΔV）不变。

## 2) 代码位置与职责

- MultiCorePE（父组件，管理步级时序与核心集合）
  - 步级触发：notifyStageEvent(seq,event,ts)
    - BeginGather：调用 injectStepActivations(seq, ts_ns)（若启用）
    - EndScatter：调用 resetAllCoreMembranes()（若启用）
    - 文件：sst_workspace/sst-elements/src/sst/elements/SnnDL/MultiCorePE.cc
  - 随机注入实现：injectStepActivations(uint32_t seq, uint64_t sim_time_ns)
    - 使用 mt19937_64(seed ^ (seq | (node_id<<32))) 产生独立随机序列
    - 伯努利分布（fraction）选择 pre；对每个 pre 均匀采样 fanout 个 post（全局 ID 范围内）
    - deliverSpikeToCore(dst_core, new SpikeEvent(pre, post, node_id, 0.0, ts))
  - 步末复位：resetAllCoreMembranes()
    - 逐核心调用子组件 resetMembraneState(v_rest_)
  - 参数读取（构造）：step_activation_enable / step_activation_fraction / step_activation_fanout / step_activation_seed / step_reset_mem_each_step

- SnnCoreAPI / SnnPESubComponent（子核心，执行复位）
  - 接口：SnnCoreAPI::resetMembraneState(float v_rest)（默认空实现）
    - 文件：sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnCoreAPI.h
  - 实现：SnnPESubComponent::resetMembraneState(float v_rest_value)
    - 将 v_mem 全设为 v_rest_value，refractory=0，last_spike_time=0；清空 fired_this_window_；调用 accReset_() 以翻页窗口累加器
    - 文件：sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.cc

- Python 脚本（参数透传）
  - 默认值定义：STEP_RANDOM_ACT_ENABLE / STEP_ACTIVATION_FRACTION / STEP_ACTIVATION_FANOUT / STEP_ACTIVATION_SEED / STEP_RESET_MEM_EACH_STEP
  - 配置解析：从 local_run_config.json 读取 step_* 并覆盖默认
  - 传参至 MultiCorePE：step_activation_enable、step_activation_fraction、step_activation_fanout、step_activation_seed、step_reset_mem_each_step
  - 文件：sst_dram_si/test_dram_si_single_pe.py

## 3) 配置开关与默认值

local_run_config.json：

```
{
  "step_random_activation_enable": 0,
  "step_activation_fraction": 0.03,
  "step_activation_fanout": 256,
  "step_activation_seed": 12345,
  "step_reset_mem_each_step": 0
}
```

脚本默认：
- STEP_RANDOM_ACT_ENABLE=0、STEP_RESET_MEM_EACH_STEP=0（均默认关闭）
- STEP_ACTIVATION_FRACTION=0.03、STEP_ACTIVATION_FANOUT=256、STEP_ACTIVATION_SEED=12345

MultiCorePE 参数映射：
- step_random_activation_enable → step_activation_enable
- step_activation_fraction      → step_activation_fraction
- step_activation_fanout        → step_activation_fanout
- step_activation_seed          → step_activation_seed
- step_reset_mem_each_step      → step_reset_mem_each_step

## 4) 使用方法（100k 起步）

- 启用随机注入（谨慎负载）：
  1) 设置 step_random_activation_enable=1；建议先用 step_activation_fraction=1e-4、step_activation_fanout≤128。
  2) 放大资源阈值：window_read_budget、max_outstanding_requests、gas_max_inflight_reads。
  3) 运行 ./sst_dram_si/run_singlepe_with_time.sh；观察 dram_si_stats.csv 与 essential_summary.json。
- 启用步末复位（步间独立动力学）：step_reset_mem_each_step=1。
- 关闭两项能力（基线）：两开关均设 0。

## 5) 与 GAS/BCSR 的关系与注意事项

- 严格 GAS 语义不变：Apply 仅读权重并累加，Scatter 统一应用。
- 随机注入的 post 均匀采样在稀疏 BCSR 下命中率偏低，会拉低 ΔV 累积效率；必要时考虑“权重可达采样”改进。
- 激活强度与资源阈值：大规模激活会放大窗口读与 simpleMem 压力；建议自小到大逐步放开 fraction/fanout，并配套提升 window_read_budget / max_outstanding_requests / gas_max_inflight_reads。

## 6) 当前已知问题与修复记录（持续更新）

本节滚动记录与“步级随机发放 + 步末复位”相关的已知问题与修复。时间倒序。

### 6.2（2025‑11‑08）严格 GAS 下的随机发放修正与 BCSR 路由

问题现象（100k 随机起激配置）：
- 仿真显著变慢；统计显示内存读取与脉冲处理数量巨大，但“激活神经元数”偏低、ΔV 积累效率异常。
- 基线（未开启随机发放）在早期版本中出现“发放大幅减少”的回归。

根因分析：
- 随机注入的 SpikeEvent 采用事件携带权重 weight（历史实现为常量 0.0）。在“严格 GAS”语义中，事件权重不应直接改变膜电位；应当由 Apply 阶段通过“真实权重读取→累加→在 Scatter 统一应用 ΔV”。
- 但窗口化流水起初未按“边（pre→post）集合”驱动读取：Gather 未记录边，BeginApply 无法有的放矢地按边发起读取，导致读取规模大、命中率低，ΔV 也无法按真实连边累加。

修复要点（已合入）：
- MultiCorePE
  - 新增参数：`step_activation_event_weight`（默认 0.0；保持严格 GAS 语义），`step_activation_use_bcsr_routes`（默认 0=关闭）。
  - 可选“BCSR 可达路由”取样：当 `step_activation_use_bcsr_routes=1` 时，从 BCSR 文件解析真实可达的 (pre→post) 连边集合；随机注入的 post 在这些真实边上采样，避免均匀采样带来的低命中。
  - 严格基线隔离：仅当 `step_activation_enable=1` 时加载 BCSR 路由；关闭随机发放时不加载、不影响基线。
- SnnPESubComponent（严格 GAS 窗口流水改造）
  - Gather：仅在 `apply_acc_enable=1 && gas_window_mode=1 && 阶段=Gather` 时记录本窗触达边（post_local, pre_global）到 `edges_curr_window_`。
  - BeginApply：翻页到 `edges_prev_window_`，按“上一窗的边集合”逐边发起权重读取；读响应回调中执行 `accUpdate_(post, w*count)`；支持 `window_read_budget/max_outstanding_requests` 节流。
  - Fallback：若 `edges_prev_window_` 为空，则回退到旧的 pre×post 集合只做 `cachePut`（不直接 ΔV），以保持历史口径。

诊断与验证：
- 在 `local_run_config.json` 中临时开启 `"window_read_debug": 1`，确认日志呈“上一窗边→本窗 BeginApply 发起读取→Scatter 统一应用”的顺序：
  - `[diag-edges] recordEdge ...`（仅 Gather 期）
  - `[diag-edges] BeginApply seq=... edges_prev=...`
  - `[diag-window-read] BeginApply: issued=... outstanding=...`
- 运行脚本：`cd sst_dram_si && ./run_singlepe_with_time.sh`（100k 基准）。

基线与回归：
- 关闭随机发放（`step_random_activation_enable=0`）时，BCSR 路由加载不会触发；统计恢复到修改前水平（已在回归测试中验证）。

参数与示例（仅供诊断参考）：
```
"step_random_activation_enable": 1,
"step_activation_fraction": 1e-5,
"step_activation_fanout": 128,
"step_activation_event_weight": 0.0,
"step_activation_use_bcsr_routes": 1,
"step_activation_bcsr_template": "weights/bcsr_from_spikes_N100k/core{core:02d}.bcsr.bin",
"step_activation_bcsr_rows_per_core": 5000,
"step_activation_bcsr_br": 16,
"step_activation_bcsr_bc": 16,
"step_activation_bcsr_idx_bytes": 2,
"step_activation_bcsr_val_bytes": 4,
"step_activation_bcsr_rowptr_offset": 0,
"step_activation_bcsr_colidx_offset": 1280,
"step_activation_bcsr_blockdata_offset": 76544,
"step_activation_bcsr_blockids_offset": 38585088,
"step_activation_bcsr_weight_epsilon": 0.0
```

注意：保持 `step_activation_event_weight=0.0`，以免引入“事件直接加权”的非 GAS 贡献；ΔV 由 Apply 的读→累加路径产生。

### 6.1（2025‑11‑07）已修复：Stage 事件链路导致功能未触发

### 6.1 已修复：Stage 事件链路导致功能未触发

此前在一些配置（尤其是 simpleMem + strict GAS）下，BeginGather/EndScatter 事件无法传递到 MultiCorePE，随机注入与步末复位“逻辑存在但不会触发”。根因是：

1. `SnnPESubComponent::appendStageEventRow_()` 仅在 `stage_events_csv` 非空时才上报事件；未设置 CSV 时直接返回。
2. `handleMemoryResponse()` 只有在 `apply_acc_enable=1` 时才处理 `GasOpData`；而 step 级功能与学习写回无关。
3. Python 脚本只在启用 GatherBufferIF 时为核心透传 `stage_events_csv`，simpleMem 配置下默认缺失。

修复（已合入 main）：

- Stage 事件永远上报给父组件（不再依赖 CSV 路径），即使 `apply_acc_enable=0` 也会触发 Begin/End 钩子。
- `test_dram_si_single_pe.py` 为每个核心默认传入 `stage_events_csv`，确保 simpleMem 场景也能产生日志。

**验证**：运行 100k BCSR 基线时查看 `outputs_large/.../pe_stage_events_db.csv`，Begin/End 记录应连续递增；若打开 step_random_activation_enable，`pe_window_spikes_db.csv` 中的发放计数也会同步变化。

### 6.0 仍需关注的问题

- 性能瓶颈：高激活强度下仿真显著变慢，甚至被 watchdog 终止；规避：fraction 降至 1e‑5/1e‑6、减小 fanout 或分步注入。
- 命中率偏低：post 均匀采样与 BCSR 稀疏图不匹配；改进方向：权重感知采样。
- 统计观察：若需观察阶段时长随负载变化，将 emit_stage_events_lenient 设为 0（不影响是否发放）。

如需定位新的问题，请确保 Stage 事件 CSV/窗口统计文件仍然写入，并可在需要时开启 `window_read_debug=1` 观察窗口级读链路。

## 9) BCSR 路由采样（随机发放可选项）

当 `step_activation_use_bcsr_routes=1` 时，MultiCorePE 会在初始化时按核读取 BCSR 索引，构建“pre→post 可达路由”表，仅用作随机发放的后继节点取样集合：
- 模板：`step_activation_bcsr_template`，支持 `{core:02d}` 等占位符替换。
- 结构：`rowptr`/`colidx`/`blockdata`/`blockids` 四段，偏移与精度由参数提供。
- 过滤：忽略绝对零权重（或 |w|<=epsilon）的边，支持 `step_activation_bcsr_weight_epsilon`。
- 作用范围：仅影响随机发放 post 取样；不改变权重读取与累加的 GAS 路径。

失败回退：
- 当模板/偏移不匹配或读取失败时，打印警告并回退为“均匀 post 采样”。

基线隔离：
- 当 `step_random_activation_enable=0` 时，BCSR 路由加载不会触发，避免对基线的任何影响。

## 7) 参考（文件与函数）

- MultiCorePE：sst_workspace/sst-elements/src/sst/elements/SnnDL/MultiCorePE.cc
  - notifyStageEvent(...)：BeginGather→injectStepActivations()；EndScatter→resetAllCoreMembranes()
  - injectStepActivations(uint32_t, uint64_t)
  - resetAllCoreMembranes()
- SnnCoreAPI / SnnPESubComponent：
  - sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnCoreAPI.h：resetMembraneState(float)
  - sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.cc：resetMembraneState 实现
- 脚本：sst_dram_si/test_dram_si_single_pe.py（step_* 默认、解析、透传）

## 8) 快速示例

local_run_config.json 片段：

```
{
  "sim_time": "80us",
  "step_random_activation_enable": 1,
  "step_activation_fraction": 1e-4,
  "step_activation_fanout": 128,
  "step_activation_seed": 271828,
  "step_reset_mem_each_step": 0,
  "window_read_budget": 4194304,
  "max_outstanding_requests": 8192,
  "gas_max_inflight_reads": 8192
}
```

执行：`cd sst_dram_si && ./run_singlepe_with_time.sh`；查看 `outputs_large/paper2/dram_N100k/latest/essential_summary.json`。
