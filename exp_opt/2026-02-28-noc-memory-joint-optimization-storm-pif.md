# STORM-PIF：NoC 触达驱动的 GAS×内存联合优化（实验隔离版）

> 日期：2026-02-28  
> 状态：**已实现 + 已跑 A/B（ramulator2）**，当前结论为“机制生效但尚未转化为端到端收益”

## 1. 目标与边界

本轮目标不是继续做纯 NoC 包级优化，而是验证一个 **NoC 证据进入内存访问路径** 的联合机制：

- 在 Gather 阶段利用 spike 触达信息（post touch）提前触发 BCSR `colidx` 元数据读取；
- 在 Apply 阶段用本地 row-index cache 命中，减少关键路径上的 row-index 冷读等待。

为避免污染主线，机制完全做成实验隔离开关（默认关闭）。

## 2. 机制设计（STORM-PIF）

### 2.1 数据路径

1. Gather 收到触达：记录 `post_local -> block_row`（去重）  
2. 每 tick 按预算从待队列发起 `colidx` 预取（`bcsr_kind=2`）  
3. `colidx` 回包解析后写入实验 cache（`block_row -> {row_start, cols}`）  
4. 后续 `requestBCSR_()` 先查实验 cache；命中则直接定位 `global_block_index`，绕过 `rowIndexGet` 冷路径。

### 2.2 参数（全部实验开关，默认 off）

- `experimental_noc_rowidx_prefetch_enable`
- `experimental_noc_rowidx_prefetch_budget_per_tick`
- `experimental_noc_rowidx_cache_rows`
- `experimental_noc_rowidx_prefetch_gather_only`

并修复了隔离语义细节：仅当 `gather_only=1` 才在 `BeginApply` 清空待预取队列。

## 3. 代码落地点（与主线隔离）

- 机制实现：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- 机制实现：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- 参数与统计注册：`sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- finish 统计落盘与实验日志：`sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- 汇总脚本（新增 `noc_mem_joint` + 日志回退解析）：`sst_dram_si/tools/compute_essential_summary_mesh.py`
- 实验模板（隔离目录）：`NoCexp/noc_mem_joint_lab/run_pif_ablation.sh`
- 实验聚合脚本：`NoCexp/noc_mem_joint_lab/analyze_pif_ablation.py`

## 4. 观测链路（证据可追）

由于当前 `mesh_stats.csv` 对 subcomponent 统计并不总是完整可见，本轮采用双通道：

1. 常规统计通道：`exp_noc_rowidx_*` 统计项（若可见直接聚合）  
2. 日志回退通道：`SnnPESubComponent::finish()` 输出 `[exp-rowidx] ...`，`compute_essential_summary_mesh.py` 解析并写入 `noc_mem_joint`

这保证了“机制是否触发”可被稳定观测，不依赖单一统计后端。

## 5. 实验设计（A/B，ramulator2）

### 5.1 口径

- 配置：`mesh_size=4`，`max_steps=1`，`exec_mode=gas`
- 内存后端：`ramulator2`（`sst_dram_si/configs/ramulator2_ddr5_notrans.cfg`）
- seed：`271828`
- 通用项：`window_read_enable=1`，`window_read_budget=8192`

### 5.2 Case

- **A_baseline_off**：`experimental_noc_rowidx_prefetch_enable=0`
- **B_pif_on_default**：`enable=1, budget_per_tick=4, cache_rows=1024, gather_only=1`

### 5.3 产物

- 行级结果：`NoCexp/noc_mem_joint_lab/runs/pif_ablation_final_v7/summary_rows.csv`
- 聚合结果：`NoCexp/noc_mem_joint_lab/runs/pif_ablation_final_v7/summary_agg.csv`
- 每 case 原始 summary：`.../A_baseline_off/.../essential_summary_mesh.json`、`.../B_pif_on_default/.../essential_summary_mesh.json`

## 6. 结果与解读

### 6.1 机制是否触发

- A：`noc_mem_joint` 全 0（符合预期）
- B：出现显著非零：
  - `rowidx_touch_rows_total=5005`
  - `rowidx_prefetch_rows_total=434`
  - `rowidx_prefetch_bytes_total=194876`
  - `rowidx_cache_misses_total=5088`
  - `rowidx_cache_fills_total=4986`
  - `rowidx_cache_entries_final=4986`
  - `rowidx_prefetch_coverage=0.0867`

结论：**STORM-PIF 机制已经真实进入运行路径并产生了可观测预取行为**。

### 6.2 性能与 DRAM 指标

- `sim_time_actual_ns`：`172327 -> 174469`（**+1.243%**，退化）
- `wall_s`：`601 -> 589`（-1.997%，但 wall 抖动大，不作为主证据）
- `ram2_num_read_reqs_total`：`1024429 -> 1038293`（**+1.353%**）
- `ram2_avg_read_latency_0_avg`：`34.096 -> 34.117`（+0.062%，基本不变）
- `ram2_row_hit_rate_total`：`0.7699 -> 0.7646`（-0.695%）

### 6.3 关键结论

1. **功能有效**：联合优化路径已触发、可追踪。  
2. **体系结构收益尚未出现**：默认参数下覆盖率仅 `8.67%`，且单步场景几乎没有 cache reuse（`cache_hit_rate=0`），导致额外请求开销盖过潜在收益。  
3. **当前证据不足以上升为“已完成的 ISCA 级性能点”**，但已形成可靠工程底座与可复现实验框架。

## 7. 下一步（面向可发表证据）

建议优先做三件事（按收益概率排序）：

1. **提高可复用性而非盲目预取量**  
   - 进入多步口径（`max_steps>1`）+ 热行筛选，目标提升 `rowidx_cache_hit_rate`。
2. **预算自适应（NoC/Gather 压力驱动）**  
   - 预算与触达密度联动，避免低价值预取膨胀 `num_read_reqs_total`。
3. **从 row-index 扩展到 blockdata 级候选**  
   - 仅在高置信热点上提前拉取 blockdata，形成真正的 Apply 关键路径削峰。

## 8. 复现实验

```bash
cd /home/xgy/remote
SEEDS="271828" OUT_ROOT="/home/xgy/remote/NoCexp/noc_mem_joint_lab/runs/pif_ablation_final_v7" \
  /home/xgy/remote/NoCexp/noc_mem_joint_lab/run_pif_ablation.sh
```

## 9. v8 增量实现与单步矩阵结果（2026-03-01）

### 9.1 v8 新增机制（仍为实验隔离）

- 热行门控：`experimental_noc_rowidx_hot_touch_min`（触达达到阈值才入队）
- 预算自适应：`experimental_noc_rowidx_budget_adapt_enable / _max_per_tick / _q_depth`
- 新增统计：
  - `touch_events_total`
  - `rows_filtered_cold`
  - `budget_ticks_total`
  - `budget_effective_total`
  - `budget_adapt_ticks`
- `compute_essential_summary_mesh.py` 的 `[exp-rowidx]` 解析升级为通用 `key=value`，兼容新增字段。

### 9.2 v8 实验矩阵（A/B/C，ramulator2，单 seed）

- 输出目录：`NoCexp/noc_mem_joint_lab/runs/pif_ablation_v8_smoke_s1`
- `summary_agg.csv` 关键结果：
  - A (`off`)：`sim_time_actual_ns=172327`
  - B (`on_default`)：`174469`（相对 A：`+1.243%`）
  - C (`on_hot_adapt`)：`174091`（相对 A：`+1.024%`，相对 B 略回升）
- 行为证据（C）：
  - `rowidx_touch_events_total=8059`
  - `rowidx_rows_filtered_cold_total=5005`（`rows_filtered_cold_rate=0.621`）
  - `rowidx_prefetch_rows_total=178`（低于 B 的 `434`）
  - `rowidx_budget_adapt_tick_rate=1.0`（预算自适应路径确实触发）
- DRAM 侧：
  - `ram2_num_read_reqs_total`：A `1024429`，B `1038293`，C `1029480`
  - C 相比 B 已压回请求量，但端到端 `sim_time` 仍未优于 A。

### 9.3 关于“卡住”的定位结论

- 在 `max_steps=2` 口径下，首个 baseline case 出现超长运行，日志反复打印：
  - `[warn-gbi] step_gate fallback EndApply via window_cycles_apply (count=1)`
- 该现象出现在 v8 机制关闭的 baseline case，因此**不是 v8 新逻辑独有故障**，更可能是当前 step-gate/两步口径下的系统性收敛问题。
- 为避免矩阵任务“看似卡死”，实验脚本已加入：
  - `RUN_TIMEOUT_SEC`（单 run 超时保护）
  - `MAX_STEPS_OVERRIDE`（快速切换单步/多步口径）

### 9.4 当前阶段结论

1. v8 路径（热行筛选+预算自适应）已实装并可观测触发。  
2. 请求量方向有改善（C 比 B 收敛），但仍未转化为端到端性能正收益。  
3. 下一步应先稳定 `max_steps>1` 的 step-gate 收敛口径，再做多步 reuse 证明。

### 9.5 `max_steps=2` 复现结果（debug_stepgate）

- 复现命令（A-only）：
  - `timeout --foreground 1800 .../run_mesh_with_time.sh --spec NoCexp/noc_mem_joint_lab/debug_stepgate/spec_a_steps2.json`
- 结果：
  - 退出码 `124`（超时）
  - 仅产生 `mesh_run.log`/`time.txt`，未生成 `essential_summary_mesh.json`
  - 尾部持续出现 `step_gate fallback EndApply` 警告（多实例各打印一次）
- 对照试验（缩小规模）：
  - `spec_a_steps2_small.json`（`num_cores_per_pe=1`, `neurons_per_core=64`）在 `~7.93s` 内完成
  - `global_steps_done=2`
- 结论：
  - 当前问题更像“**大规模两步口径下的超长运行/收敛慢**”，而非简单的功能性死锁。
  - 在多步根因完全钉住前，主矩阵继续采用单步口径，并由超时保护保证实验可完成。

### 9.6 实验脚本稳健性增强

- `run_pif_ablation.sh` 新增：
  - `CASES`：按 case 名过滤运行（便于单 case debug）
  - `RUN_TIMEOUT_SEC`：单 run 超时保护
  - `failed_runs.csv`：记录超时/失败项
  - 缺失 `run_dir` 不再直接中断整批实验

## 10. STORM-NIP(P0) 落地与 A/B 闭环（2026-03-03）

### 10.1 本轮修复与实现（实验隔离目录）

- 实验目录：`NoCexp/noc_idx2_nip_lab`
- 脚本：`NoCexp/noc_idx2_nip_lab/run_nip_ablation.sh`
- 关键修复：此前 A/B 都显示 `idx2_* = 0` 的根因不是机制失效，而是 **spec-first 会屏蔽建模环境变量**（`MESH_SYNAPSE_WEIGHT_MODE`/`MESH_GCSS2_DIR`）。  
  本轮改为在 spec 内通过 `overrides` 显式下发：
  - `pe.core`: `synapse_weight_mode=gcss_valueonly_dstcore_idx2` + `gcss_index_template`
  - `weight_loader`（按 PE 匹配）：切换为 `gcss2.bin` raw per-core 文件模板
- 保持主线隔离：仅修改 `NoCexp` 实验脚本，不改主线实验入口。

### 10.2 复现实验

```bash
cd /home/xgy/remote/NoCexp/noc_idx2_nip_lab
CORES_PER_PE=4 NEURONS_PER_CORE=128 SEEDS="271828" MAX_STEPS=1 MESH_SST_NPROC=1 ./run_nip_ablation.sh
```

- 输出根目录：`NoCexp/noc_idx2_nip_lab/runs/nip_ablation_20260303-003521`
- 聚合结果：`NoCexp/noc_idx2_nip_lab/runs/nip_ablation_20260303-003521/summary_agg.csv`
- 运行明细：
  - A: `.../A_baseline_off/seed_271828/run/20260303-003521`
  - B: `.../B_nip_on_default/seed_271828/run/20260303-003538`

### 10.3 A/B 结果（ramulator2，single-seed smoke）

- A (`NIP=off`)：
  - `sim_time_actual_ns=5982`
  - `gas_apply_ns_avg=464.94`
  - `ram2_num_read_reqs_total=1356`
  - `ram2_avg_read_latency_0_avg=106.09`
  - `idx2_*` 全 0
- B (`NIP=on`, budget=4, cache=4096, gather_only=1)：
  - `sim_time_actual_ns=4572`（相对 A **-23.57%**）
  - `gas_apply_ns_avg=408.25`（相对 A **-12.19%**）
  - `ram2_num_read_reqs_total=1133`（相对 A **-16.45%**）
  - `ram2_avg_read_latency_0_avg=80.23`（相对 A **-24.38%**）
  - `idx2_touch_events_total=184`
  - `idx2_enqueued_total=98`
  - `idx2_prefetch_issued_total=98`
  - `idx2_demand_join_total=98`
  - `idx2_prefetch_issue_rate_vs_enqueue=1.0`
  - `idx2_demand_join_ratio=1.0`

### 10.4 机理解读与正确性边界

1. **机制触发已确认**：B 出现完整“touch -> enqueue -> prefetch issue -> demand join”链路，且 join 比例为 100%。  
2. **内存侧收益方向正确**：B 的读请求总量与平均读延迟均下降。  
3. **正确性未破坏**：A/B `validation.log` 均为 `fail=0`（各有 1 条非严格 warn）。  
4. **统计口径注意事项**：`model.synapse_weight_mode` 仍显示 `bcsr_gas`（spec state 字段），但 `synapse.gcss_lookup_hit_total` 与 `idx2_*` 非零证明 gcss idx2 实际执行路径已生效；论文口径应优先引用 `noc_mem_joint` 与 `synapse` 行为统计，而非仅看 `model.synapse_weight_mode` 字段。

## 11. STORM-NIP(P0) 复核：语义对齐矩阵与版本漂移根因（2026-03-03）

### 11.1 根因修正（不是机制逻辑回归，而是运行时库版本漂移）

- 现象：此前一轮矩阵出现 `B_nip_on_default` 的 `neurons_fired_total=0`，同时 `idx2_demand_join_total>0`、`idx2_waiters_served_total=0`。
- 复核动作：
  - 在 `WeightMemorySubsystem` 增加 STORM-NIP 诊断计数（join 回调是否为空、prefetch 回包是否有效、complete 是否命中 inflight）。
  - 重新 `make clean && make -j4 && make install` 安装最新 `SnnDL` 到 `sst_install_mpi`。
- 结论：异常来自运行时库与源码状态不一致（旧安装库）；使用最新安装后，NIP 闭环恢复正常。

### 11.2 闭环证据（修正后）

单 seed（271828）复核 run：
`/home/xgy/remote/NoCexp/noc_idx2_nip_lab/runs/diag_idx2_cb_20260303-010219/B_nip_on_default/seed_271828/run/20260303-010219`

关键日志（`[exp-idx2-prefetch]` 聚合后）：
- `demand_join=98`
- `demand_join_cb_nonnull=98`
- `waiters_served=98`
- `cache_fill=98`
- `prefetch_resp_ok=98`
- `prefetch_resp_short=0`

对应 summary：
- `spike_activity.neurons_fired_total=98`
- `spike_activity.gas_scatter_spikes_emitted_total=98`

=> 说明“prefetch -> join -> waiter callback -> cache fill”语义链路已经完整闭环。

### 11.3 多 seed A/B 语义对齐矩阵（修正后）

输出目录：
`/home/xgy/remote/NoCexp/noc_idx2_nip_lab/runs/nip_ablation_20260303-010309`

按 seed 对齐检查（A vs B）：
- `gas.synapse_ops_step_total`：一致（1280 / 1536 / 768）
- `spike_activity.neurons_fired_total`：一致（98 / 184 / 114）
- `gas_scatter_spikes_emitted_total`：一致（98 / 184 / 114）

=> 语义一致性已恢复，B 不再出现“0 firing”伪加速。

### 11.4 性能结论（修正后）

`summary_agg.csv`（3 seeds）显示：
- A: `sim_time_actual_ns = 6853.33`
- B: `sim_time_actual_ns = 8399.67`
- B 相对 A：`0.816x`（约 **18.4% 变慢**）

同时：
- `gas_apply_ns_avg`：B 仍优于 A（`570.71` vs `643.25`）
- `ram2_num_read_reqs_total`：B 低于 A（`1795.33` vs `1939.67`）
- `ram2_avg_read_latency_0_avg`：B 略低于 A（`104.54` vs `109.39`）

解释：NIP 目前在“局部内存/Apply 指标”方向有效，但尚未转化为端到端收益；额外调度/窗口交互成本抵消了内存侧收益。

### 11.5 当前可用于论文的严谨口径

- 可以主张：
  1) STORM-NIP(P0) 机制已工作（有完整 join/waiter/cachefill 证据）；
  2) 语义正确性经多 seed A/B 对齐验证。
- 不可主张（当前数据下）：
  - 端到端性能提升（`sim_time` 目前为负收益）。
- 下一步优化方向：
  - 聚焦减少 NIP 引入的调度/阶段切换开销，探索“按热点 selective join + budget 自适应 + 与 NoC 拥塞信号联动”的联合策略。

## 12. STORM-NIP(P0.1) Tail-Guard（MAX_STEPS=1 短跑）实现与 A/B/C 结果（2026-03-04）

### 12.1 实现内容（实验隔离）

- 代码路径（实验特性，不改主线语义）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
  - `sst_dram_si/tools/compute_essential_summary_mesh.py`
- 新增参数：
  - `experimental_idx2_ingress_tail_guard_enable`（默认 0）
- 机制语义：
  - 在 `experimental_idx2_ingress_prefetch_gather_only=1` 且 `window_seq!=0` 时，若 idx2 prefetch 回包到达且 **无 waiter**，则不再写入 idx2 cache，记为 `prefetch_resp_drop_tail`。
  - 若存在 waiter，仍按原路径回调，不影响正确性。

### 12.2 A/B/C 对比矩阵（短跑）

- 运行命令：
```bash
cd /home/xgy/remote/NoCexp/noc_idx2_nip_lab
OUT_ROOT=/home/xgy/remote/NoCexp/noc_idx2_nip_lab/runs/nip_ablation_tailguard_20260304-002022 \
SEEDS="271828 314159 161803" \
CORES_PER_PE=4 NEURONS_PER_CORE=128 MAX_STEPS=1 MESH_SST_NPROC=1 ./run_nip_ablation.sh
```
- 三组 case：
  - `A_baseline_off`
  - `B_nip_on_default`
  - `C_nip_on_tail_guard`（B + tail_guard=1）

### 12.3 结果与结论

- 聚合（3 seeds）：
  - A：`sim_time_actual_ns=6853.33`
  - B：`sim_time_actual_ns=8399.67`（`0.8159x` vs A）
  - C：`sim_time_actual_ns=8399.67`（与 B 基本重合）
- Tail-Guard 触发证据：
  - `idx2_prefetch_resp_drop_tail_total`：B=0，C=0（逐 seed 也为 0）
- tail 口径（`tail_ns=sim_time-max(EndScatter)`）：
  - A：`0.263/0.396/0.433`
  - B：`0.427/0.531/0.511`
  - C：`0.427/0.531/0.511`（与 B 一致）
- 解释：
  - 当前短跑负收益并非来自“无 waiter 晚到回包写 cache”这一路径（该路径在本矩阵中未出现可 drop 事件）。
  - 下一步应把优化重点转向“降低有 waiter 回包带来的 tail”或“提升命中前置率（join->hit）”，例如：
    - selective join（仅热点地址保留 join，冷地址回退 demand）；
    - prefetch 提前量控制（更早触发，而非仅 gather 中后段发起）；
    - 将 idx2 控制流量进一步与 NoC 拥塞反馈耦合。
