# Native Multicast Lab（SpikeKey / blocked multicast）

本目录用于验证与迭代 SnnDL 的“原生多播（native multicast）”路由后端，当前落地版本（M1）特点：

- **多播语义载体**：`SpikeKey`（携带 `ingress_node + stage + core_mask[]`）
- **路由语义**：块间单播到 ingress；块内按树复制并 **按 core mask 精确投递到目标 core**
- **实验范围**：不引入 GAS / memHierarchy / WeightLoader，仅做通信/路由闭环

## 目录结构

- `test_mesh_4x4_multicast_min.py`：最小网格装配（验证 router mesh + NIC 连通性）
- `test_mesh_4x4_spikekey_multicast.py`：端到端 SpikeKey 多播验证（含投递正确性自检）
- `edges/mesh4x4_c4_n64_edges.csv`：用于 weight-driven 路由构建的边集合（global neuron id）
- `tools/gen_edges_mesh4x4_c4_n64.py`：生成上述 edges CSV
- `experiments/`：实验运行与统计落盘工具（输出文件在该子目录内）
  - `experiments/runs/`：每次 suite 运行输出（CSV/JSON/日志）

## 关键组件（SnnDL 层次）

- `SnnDL.MulticastRouter`：mesh 路由器（处理 `Spike` 单播 + `SpikeKey` 两阶段多播）
- `SnnDL.MulticastNIC`：连接 PE 与 router mesh 的 NIC
- `workload_impl="traffic"`：最小 traffic-only workload，周期性触发 `SpikeCommSubsystem::emitNeuronFireBatch()`，可复现注入

## 运行（最小复现）

1) 先构建安装（只重建 SnnDL）：

```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4 && make install
```

2) 端到端 SpikeKey 多播（默认开启自检并可 fail-fast）：

```bash
SIM_TIME="20us" MULTICAST_ENABLE="1" SPIKEY_CHECK_FATAL="1" ./sst "experimental_features/native_multicast_lab/test_mesh_4x4_spikekey_multicast.py"
```

可配置参数（环境变量，默认值见脚本）：

- block 形状：`MULTICAST_BLOCK_W`、`MULTICAST_BLOCK_H`
- ingress 选择（构建 target 阶段决定 `ingress_node`）：`MULTICAST_INGRESS_POLICY`（`top_left/top_right/bottom_left/bottom_right/hash4`）
- block 间单播路由（router 层决定 INTER stage 的走法）：`MULTICAST_INTER_POLICY`（`xy/yx/hash_xy`）
- block 内多播树（router 层决定 INTRA stage 的扩散树）：`MULTICAST_INTRA_POLICY`（`manhattan_x_first/manhattan_y_first`）

验收点（日志）：

- 多个 core 输出 `[traffic] ... rx_spikekey>0` 且 `sk_bad=0`
- 多个 router 输出 `[mcast-router] ... clones>0`（证明发生复制/分发）

## 下一步（任务 1~3）

1) **正确性回归做稳**：多 seed / 多源注入 / 更长 sim_time，要求 `sk_bad==0`
2) **口径对齐**：固定 global neuron 布局、`total_nodes/neurons_per_pe/global_neuron_base` 一致性检查，避免脚本口径漂移
3) **性能画像 + 统计落盘**：对比单播 vs 多播的 router 负载与 hop 统计，输出可落盘的 CSV/JSON（见 `experiments/`）

## 性能矩阵（任务 3~4）

为了让多播优势在拥塞下更明显，本实验提供了“块内 spread + 更强 core-level 聚合”的 edges 变体：

- `edges/mesh4x4_c4_n64_edges_spread4.csv`：每 block 4 edges（spread across 2×2 block 的 4 个 PEs）
- `edges/mesh4x4_c4_n64_edges_spread16.csv`：每 block 16 edges（每 PE 覆盖更多 cores，触发多播 core_mask 聚合）

生成示例：

```bash
python3 "experimental_features/native_multicast_lab/tools/gen_edges_mesh4x4_c4_n64.py" \
  --edges-per-block 16 --in-block-mode spread \
  --out "experimental_features/native_multicast_lab/edges/mesh4x4_c4_n64_edges_spread16.csv"
```

矩阵扫参（输出落盘到 `experiments/runs/<run_id>/`）：

```bash
python3 "experimental_features/native_multicast_lab/experiments/run_suite.py" \
  --sim-time 300us --seeds 1 2 3 --enable-all \
  --traffic-period-cycles 200 --traffic-batch-size 1 --traffic-stop-cycle 20000 \
  --router-serialize-enable --router-serialize-service-cycles 16 \
  --ingress-policy hash4 --noc-lat-hist-max 262144 \
  --edges-csv "experimental_features/native_multicast_lab/edges/mesh4x4_c4_n64_edges_spread16.csv" \
  --tag "matrix_example"
```

矩阵汇总（把多个 `suite_summary.json` 汇总为一张表）：

```bash
python3 "experimental_features/native_multicast_lab/experiments/summarize_matrix.py" \
  --prefix "matrix_spread16_stop20us_sim300us_p200_b1_"
```
