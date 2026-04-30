# Native SpikeKey Multicast (2×2 Block) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `experimental_features/native_multicast_lab/` 内把 `SpikeKey` 原生多播端到端跑通，并提供可复现（伪随机但确定性）的流量源与可观测的路由/复制计数。

**Architecture:** 新增一个轻量 `workload_impl=traffic`，仅负责“周期性生成 pre 并调用 SpikeCommSubsystem 发射”（从而触发 `SpikeKey`/多播路径），不跑神经动力学、不依赖 GAS/memHierarchy/WeightLoader。路由由 `SynapseRouteSubsystem` 通过 `mapping_mode=edges_csv` 构建（避免依赖巨大 BCSR 权重文件），并沿用既有 `multicast_*` 参数生成 2×2 block targets/core_mask。

**Tech Stack:** SST + SST-elements(SnnDL) C++17，Python SST 配置脚本，现有 `SnnDL.MulticastRouter`/`SnnDL.MulticastNIC`/`SpikeCommSubsystem`/`SynapseRouteSubsystem`。

---

## Assumptions / Non-Goals (M1)
- M1 只要求：`SpikeKey` 包在网格内可达、在 2×2 block 内复制、并按 core mask 精确投递到目标 core（能在 workload 侧计数）。
- 不做：GAS/window、权重读取/内存层次、神经元发放动力学、统计 CSV（当前 SST 输出对“init 期创建子组件”的显式 enable 可能有限制）。

---

## Task 1: 固化实验输入（edges CSV）

**Files:**
- Create: `experimental_features/native_multicast_lab/edges/mesh4x4_c4_n64_edges.csv`
- (Optional) Create: `experimental_features/native_multicast_lab/tools/gen_edges_mesh4x4_c4_n64.py`

**Step 1: 生成最小 edges CSV（固定布局）**
- 固定布局：`mesh=4x4`、`cores_per_pe=4`、`neurons_per_core=64` → `neurons_per_pe=256` → `global_neurons=4096`
- CSV 格式：`src,dst,w`（header 必须存在，w 可省略但建议写 1.0）
- 目标：让每个 `pre_global` 至少有跨 block 的目的，以触发 `SpikeKey` 多 block 发射与 block 内复制。

**推荐生成规则（确定性、覆盖 4 blocks、每 block 4 PEs）：**
- 对每个 `pre_global in [0,4096)`：
  - 对每个 `dest_pe in [0,15]` 写一条边（总行数约 65536）
  - `dest_core = (pre_global + dest_pe) % 4`
  - `post_local = pre_global % 64`
  - `dest_global = dest_pe*256 + dest_core*64 + post_local`
  - 写：`pre_global,dest_global,1.0`

**Step 2: 快速 sanity check**
- 检查行数约为 `4096*16 + 1(header)`
- 抽查几行，确认 `dst` 落在 `[0,4096)` 且分布到多个 `dest_pe`

---

## Task 2: 新增 TrafficWorkload（伪随机 pre，但确定性）

**Files:**
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.h`
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/CoreWorkloadFactory.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.in`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile`

**Step 1: 写一个“最小接口”骨架（先编译失败再补齐）**
- `TrafficWorkload` 实现 `ICoreWorkload`，提供：
  - `configureFromParams(const SST::Params&)`
  - `bindRuntime(const WorkloadRuntime&)`
  - `onInitPhase(unsigned phase)`（phase==0 里初始化路由/通信）
  - `onClockTick(uint64_t now_cycle)`（按周期注入）
  - `deliverPacket(NocPacketEvent*)`（计数 + delete packet + return true）
  - `hasWork()/ready()`（最小实现）

**Step 2: 复用 SnnWorkload 的 spike_comm 装配口径（但不创建 compute core）**
- 内部持有：
  - `std::unique_ptr<SynapseRouteSubsystem> synapse_route_`
  - `std::unique_ptr<SpikeCommSubsystem> spike_comm_`
  - `std::unique_ptr<NocSpikeTransport> noc_spike_transport_`
- `onInitPhase(0)`：
  - 解析参数：`routing_mode`、`mapping_mode`、`mapping_edges_file`、`routing_epsilon/topk`、`multicast_*`、`total_nodes/total_cores/neurons_per_pe/num_neurons/global_neuron_base` 等
  - `synapse_route_->configure(cfg)` + `bindRuntime(...)`
  - 配置 `NocSpikeTransport` 并 `SpikeCommSubsystem::bindRuntime(crt)`（必须填 `crt.noc/crt.src_core/crt.node_id`）
  - `spike_comm_->initRouting()`

**Step 3: 伪随机 pre 选择（确定性）**
- 参数（建议）：
  - `traffic_enable` (0/1)
  - `traffic_period_cycles`（>0）
  - `traffic_batch_size`（每次注入多少个 pre）
  - `traffic_seed`（uint64）
  - `traffic_pre_begin`、`traffic_pre_end`（限定在本 core 的 neuron_idx 范围内）
- RNG 规则（保证跨运行可复现）：
  - `seq`：每次注入递增（从 1 开始）
  - `rng_seed = traffic_seed ^ (uint64_t(node_id)<<32) ^ (uint64_t(core_id)<<16) ^ uint64_t(seq)`
  - `std::mt19937_64 rng(rng_seed)`
  - `uniform_int_distribution<uint32_t> dist(pre_begin, pre_end-1)`
  - 生成 `traffic_batch_size` 个 `neuron_idx`，去重（可选），调用 `spike_comm_->emitNeuronFireBatch(neuron_indices, now_cycle)`

**Step 4: 在 deliverPacket 侧做最小验收计数**
- 计数项（先用 `Output::verbose` 在 finish 打印即可）：
  - `rx_spike_total`、`rx_spikekey_total`
  - 可选：按 `dst_endpoint` 分桶（core 维度）

**Step 5: 编译/安装验证（强制）**
- Run:
  - `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
  - `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make install`

**Step 6: （可选）git 提交**
- 本仓库禁止未授权 git 写操作；如需提交请主人明确指令后再执行。

---

## Task 3: 新增 SpikeKey 多播验证脚本（实验目录）

**Files:**
- Create: `experimental_features/native_multicast_lab/test_mesh_4x4_spikekey_multicast.py`
- Modify: `experimental_features/native_multicast_lab/test_mesh_4x4_multicast_min.py`（如需增加一键切换/复用函数，可选）

**Step 1: 复用 M0 网格装配**
- Router：`SnnDL.MulticastRouter`，端口 `local/north/south/east/west`
- NIC：`SnnDL.MulticastNIC`，连接到 `router.local`

**Step 2: 每 core 配置 workload=traffic + edges_csv 路由 + multicast**
- 关键参数（每个 `SnnDL.SnnPESubComponent`）：
  - `workload_impl="traffic"`
  - `routing_mode="weight_driven"`
  - `mapping_mode="edges_csv"`
  - `mapping_edges_file="experimental_features/native_multicast_lab/edges/mesh4x4_c4_n64_edges.csv"`
  - `mapping_csv_has_header=1`, `mapping_csv_separator=","`
  - `mapping_assume_block_ids=0`（重要：避免用 `rows=num_neurons` 错当 PE stride）
  - `multicast_enable=1`, `multicast_block_w=2`, `multicast_block_h=2`, `multicast_ingress_policy="top_left"`
  - `traffic_enable=1`（可仅对某些 node/core 开启）
  - `traffic_period_cycles=...`, `traffic_batch_size=...`, `traffic_seed=...`

**Step 3: 运行与验收**
- Run: `./sst "experimental_features/native_multicast_lab/test_mesh_4x4_spikekey_multicast.py"`
- 期望：
  - 源端 core 输出“已注入/已发射”计数增长
  - 目标端 core 能观测到 `rx_spikekey_total > 0`

---

## Task 4: 路由器/网卡可观测性（为性能准备）

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.h`
- (Optional) Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastNIC.cc`
- (Optional) Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastNIC.h`

**Step 1: Router 内部计数器**
- `pkts_in_total`, `pkts_out_total`, `pkts_to_local`, `pkts_forward_xy`
- `spikekey_in_total`, `spikekey_stage_inter`, `spikekey_stage_intra`
- `spikekey_clone_total`（block 内复制次数）

**Step 2: finish() 输出一行 summary（易 grep）**
- 格式示例：`[mcast-router] node=7 in=... out=... local=... spikekey=... clones=...`

---

## Task 5: 性能对比实验（单播 vs SpikeKey 多播）

**Files:**
- Modify: `experimental_features/native_multicast_lab/test_mesh_4x4_spikekey_multicast.py`

**Step 1: 通过 env 开关切换**
- `MULTICAST_ENABLE=0/1` → 传到 core 参数 `multicast_enable`

**Step 2: 固定相同的 traffic seed 与注入规模**
- 保证可比性：同 `traffic_seed/period/batch/total_cycles`

**Step 3: 对比指标（先粗后细）**
- Router：`spikekey_clone_total`、`pkts_out_total`（包数量差异）
- 运行时间：对比两次 `sst` wall-clock（先人工粗看即可）

---

## Task 6: 为“分块路由（块内多播、块间单播）”做接口预留（仅设计，不实现）

**Design notes:**
- 使用 `WireSpikeKeyV1.route_mode` 区分策略（例如 0=blocked_tree_v1，1=chunked_v1）。
- Router 侧以小型 `switch(route_mode)` 分派到不同策略函数（KISS，不上复杂框架）。
- `SynapseRouteSubsystem` 负责产出“块内 core_mask + 块间目标集合”的抽象数据结构，Router 只负责转发与复制。

