# DRAM‑SI 4×4 Mesh · 10k/PE · Strict GAS 技术报告（截至 2025‑11‑18）

本报告记录 4×4 mesh、10k/PE、严格 GAS（Gather→Apply→Scatter）在 BCSR 权重与 Step 随机发放下的最新进展、关键修复、复现方法与后续计划。

## 场景与基线
- Mesh 与规模：4×4（16 PEs），每 PE 20 cores×500 rows=10,000 neurons/PE
- 权重：全局 BCSR（fanout≈256，local≈85% / remote≈15%，br=1，bc=16，idx=2B，val=4B）
  - 10k/PE 权重目录：`sst_dram_si/weights/bcsr_global_16pe_fanout256_10k/pe{00..15}/core{00..19}.bcsr.bin[.meta.json]`
  - 关键偏移（对齐 64）：rowptr=0, colidx=2048, blockdata=226432, blockids=7404928
  - per‑core stride：与 meta 文件大小严格一致（按最大 core 文件对齐 64B）
- 注入：Step 随机发放（SpikeSource/TestTraffic 关闭；诊断阶段可临时开启）
- 语义：Strict GAS（事件权重=0；ΔV 仅由 Apply 的内存权重产生；Scatter 负责发放）
- 运行：32 线程；脚本 `sst_dram_si/tools/run_mesh_with_time.sh`
  - 输出目录示例：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251118-014524`

## 已完成修复与确认
1) GAS 窗口与读回路径
- GatherBufferIF 自动窗口恢复；空窗也能推进（不再卡在 Gather）。
- BeginApply 能发起按边读（BCSR priming），回调进入 SnnPESubComponent 累加 ΔV。
- RowPtr 预载/就绪检查到位；响应尺寸校验与越界保护已加。

2) 地址与 I/O 一致性
- WeightLoader 使用 per‑PE base + per‑core stride 写入；SnnPESubComponent 读地址同源；强制 probe 显示 `mem==file`（样本：PE0/core0）。
- 解决早期异常极值/负权重：读地址/stride/offset 对齐后，探针值合理；为稳态运行仍保留权重守卫（|w|>10 或非有限值→0）。

3) 路由与注入
- Step BCSR reachability 成功加载（每核 routes 构建完毕），并在 BeginGather 注入。
- `dest_node` 计算修正：依据 `neurons_per_pe=10000`，避免跨核→跨 PE 映射错误。

4) NIC 与统计
- `compute_essential_summary_mesh.py` 汇总兼容 “SnnNIC” 与 “:network_interface” 统计名；100us 稳态可见非零 NIC 发送统计。
- `sim_stop_ns` 生效（`MESH_ALT_STOP=1`）；确保 10us/100us 跑满时长。

## 最新稳态结果（100us）
- 路径：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251118-014524`
- essential_summary（摘录）：
  - memory: requests=14,851,091，bytes≈6.588e9
  - gas: windows=5,486；avg(ns) gather≈156.7 / apply≈102.7 / scatter≈38.9
  - spike_activity: total_spikes_processed=139；window_spikes_total=278；neurons_fired_total=7,730
  - nic: spikes_sent=572,840；spikes_recv=0；packets_sent=572,840；packets_recv=0

说明：spike_activity 统计的是 Scatter 发放（神经元越阈）而非注入数；NIC 指标统计的是 Step 注入的网络侧数据，两者口径不同，出现数量级差异属预期。

## 已知问题与待办
- 发放率偏低：ΔV 命中稀疏，短时间窗口内越阈较少（但非零）。
- NIC 接收统计（recv）在当前 steady run 中为 0：后续需要在汇总层确认是否仅统计发送端，或在仿真层增加接收端计数。
- 诊断开关：需在稳态回归时保持关闭，仅在短测时打开，避免 I/O 干扰性能与日志体量。

## 复现实验步骤
1) 构建 SnnDL 组件
```
cd sst_workspace/sst-elements/src/sst/elements/SnnDL
make -j4 && make install
```
2) 运行 10us / 100us（确保跑满）
```
cd sst_dram_si
MESH_ALT_STOP=1 MESH_SIM_TIME=10us  tools/run_mesh_with_time.sh
MESH_ALT_STOP=1 MESH_SIM_TIME=100us tools/run_mesh_with_time.sh
```
3) 如未自动生成 summary，可补算
```
python3 tools/compute_essential_summary_mesh.py --run-dir sst_dram_si/outputs_large/paper2/dram_mesh_4x4/<timestamp>
```
4) 关键 grep 检查（mesh_run.log）
```
# 阶段推进与读回
grep -n "diag-stage] BeginApply" mesh_run.log
grep -n "diag-resp" mesh_run.log
grep -n "\[GAS\]\[Delta\]" mesh_run.log
# Step 路由加载与注入
grep -n "step-activation" mesh_run.log
# 权重对齐探针（若启用）
grep -n "VERIFY\]" mesh_run.log
```

## 诊断/运行参数要点（稳态建议）
- Strict GAS：`event_weight_fallback=0`
- GBI/SnnPES：`window_auto=1`、`manual_window_drive=0`、`emit_stage_events=1`（日志级别常规）
- Step：`fraction=2e-4`（或按需要），`use_bcsr_routes=1`
- 权重：B C S R 偏移按上节值传递；per‑core stride 与 meta 文件大小一致
- 运行：32 线程；`MESH_ALT_STOP=1`；`MESH_GAS_CYCLES=200,40,40`（回归口径）

## 下一步计划（分阶段）
- Phase A（巩固稳态）
  1) 保持严格 GAS 与当前回归参数，重复 100us 跑满，校验 `memory/gas/NIC(send)/spike_activity` 均非零。
  2) 在不放大日志的前提下，增加一次 mem==file 抽样（单核）复核地址一致性。
- Phase B（接收侧与链路可视化）
  3) 在汇总层补充 NIC 接收统计聚合；如有必要，在 SnnNIC 增加接收端计数并入 CSV。
  4) 保留低噪声的 route/local/remote 概览输出（单次/单核），验证 85/15 比例健康度。
- Phase C（选择性优化）
  5) 若需提升发放率，可在保证 Strict GAS 的前提下，微调 route 选择（epsilon/topk）或窗口周期；完成后恢复回归口径。

## 参考文件
- 代码：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.{cc,h}`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/MultiCorePE.{cc,h}`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.{cc,h}`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnNIC.{cc,h}`
- 脚本与工具：
  - `sst_dram_si/test_mesh_4x4.py`
  - `sst_dram_si/tools/run_mesh_with_time.sh`
  - `sst_dram_si/tools/compute_essential_summary_mesh.py`
- 最新稳态结果：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251118-014524`

> 注：报告中的诊断开关仅用于短测定位；稳态回归与大规模实验请保持关闭，以免影响统计与性能。
