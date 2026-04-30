# DRAM‑SI 4×4 Mesh · 10k/PE · Strict GAS · 进度技术报告

更新时间：2025‑11‑18

## 场景与目标
- Mesh：4×4（16 PEs），每 PE 20 cores × 500 neurons = 10,000 neurons/PE。
- 权重：全局 BCSR（br=1, bc=16, idx=2B, val=4B，fanout≈256，local≈85%）。
- 语义：Strict GAS（Gather→Apply→Scatter），仅内存权重产生 ΔV；最终模式下事件权重回退关闭。
- 目标：打通“权重读→ΔV 累加→越阈发放→跨 PE 外发→NIC 统计”，并回归稳态 100us。

## 关键修复
1) 权重读/写一致性（阶段A）
   - 以 pe00 全部 core 的最大 file_size 计算 `PER_CORE_WEIGHT_STRIDE`（64B 对齐），避免 WeightLoader 写越界。
   - WeightLoader verbose 验证 base/stride/bytes 一致；probe‑bcsr 与 probe‑gas 无异常极值，mem==file。
   - 相关：`sst_dram_si/test_mesh_4x4.py`（stride 计算与 loader 配置）。

2) 外发路由目的节点划分修正（重大）
   - SnnPESubComponent 外发扇出时：dest_node 修正为按“每 PE 神经元数 10,000”划分（而非 core 行数 500）。
   - 新增 `neurons_per_pe_cfg_` 并从脚本注入 `"neurons_per_pe": 10000`。
   - 相关：
     - `sst_workspace/.../SnnDL/SnnPESubComponent.cc/h`
     - `sst_dram_si/test_mesh_4x4.py`

3) 路由与 NIC 诊断增强（短期调试后已清理）
   - MultiCorePE 打印 Step BCSR 可达性加载（route_vectors）。
   - SnnPESubComponent 构建共享路由后输出本地/远端目的计数（现降为低噪日志）。
   - SnnNIC/MultiCorePE 短期添加 send 诊断（已去除 printf，保持生产口径）。

4) 汇总脚本修正（NIC 统计识别）
   - `tools/compute_essential_summary_mesh.py` 兼容 “SnnNIC” 与 “multicore_pe_X:network_interface” 组件名，正确聚合 CSV 中的 NIC 指标。

## 运行与验证（命令）
- 10us 快测（可选窗口放宽，仅诊断）
```bash
cd sst_dram_si
MESH_ALT_STOP=1 MESH_SIM_TIME=10us tools/run_mesh_with_time.sh
# 或短测放大窗口：MESH_GAS_CYCLES=200,100,100
```
- 100us 稳态回归
```bash
cd sst_dram_si
MESH_ALT_STOP=1 MESH_SIM_TIME=100us tools/run_mesh_with_time.sh
```
- 失败时可单独重算 summary
```bash
python3 tools/compute_essential_summary_mesh.py --run-dir \
  outputs_large/paper2/dram_mesh_4x4/<timestamp>
```

## 关键指标（最新 100us 稳态）
- 目录：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251118-014524`
- memory：
  - requests≈14,851,091；bytes≈6.588e9
- gas：
  - windows≈5,486；avg(ns)：gather≈156.69 / apply≈102.67 / scatter≈38.93
- spike_activity：
  - total_spikes_processed≈139；neurons_fired_total≈7,730
- NIC：
  - spikes_sent≈572,840；packets_sent≈572,840；recv≈0（当前场景仅统计发送侧）

说明：Strict GAS 下，ΔV 累加广泛但多数接近 0，越阈发放稀少（符合稀疏 BCSR 权重命中与窗口化逻辑）。在 100us 维度上，发放与 NIC 发送均为非零，链路稳定。

## 诊断开关与口径（使用建议）
- GAS 窗口/ΔV 诊断：`local_run_config.json → "window_read_debug": 1`（短测开启，日志量大）。
- 路由摘要：SnnPESubComponent 在构建共享路由时会输出 `[route-summary]`（低噪 SNNDL_LOG 级别）。
- NIC 统计来源：优先 CSV 汇总；若 CSV 为 0，则回退日志解析；已兼容 `:network_interface` 子组件命名。
- 回归口径：`window_read_debug=0`，`step_activation_fraction=2e-4`，`BUFFER_SIZE=8KiB`，`MESH_GAS_CYCLES=200,40,40`。

## 变更的主要文件
- SnnDL C++：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.cc/h`（dest_node 修复；neurons_per_pe 注入；路由/ΔV 诊断）
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/MultiCorePE.cc`（可达性摘要；发送路径诊断已清理）
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnNIC.cc`（发送诊断已清理）
- 脚本与工具：
  - `sst_dram_si/test_mesh_4x4.py`（stride 计算、per-core base_addr、neurons_per_pe 注入、NIC 参数）
  - `sst_dram_si/tools/compute_essential_summary_mesh.py`（NIC 聚合修正）

## 已知现象与原因总结
- “访存很忙但发放少”：Apply 累加广泛，但多数 dv≈0 或很小；Scatter 时难越阈。短时放宽窗口/提高 fraction 可提升 fired 数量，但回归口径保持严格语义。
- “NIC recv 为 0”：本场景仅统计/关注发送侧；接收侧未计提或未在 CSV 汇总，后续如需可扩展到接收端统计来源。

## TODO / 后续建议
1) 路由构建口径收敛：在 buildWeightDrivenRoutes 的“候选筛选”处暴露更多阈值参数（eps/topk），以便控制远端比例与扇出强度；并保持回归默认。
2) ΔV 统计采样：在不增大日志的前提下，增加 per‑PE 的汇总计数（如 dv_sum_per_window），用于快速判断越阈难度。
3) 性能优化：当 memory_requests 较高时，评估 GatherBufferIF 的 burst/merge 与 inflight 设置，降低内存压力。
4) （可选）NIC 接收侧统计口径：在 compute_essential_summary 中补充从 CSV 的接收端识别，或在日志统一出口打印最终统计快照。

---
如需对比不同 fraction/窗口组合对发放/NIC 的影响，建议先 10us 试验，再跑 100us 稳态；Strict GAS 语义保持不变。
