# tensor_si（Tensor/Systolic workload：独立实验目录）

本目录提供一个**独立的 tensor 工作负载模板**，用于在 SST 的 Mesh NoC + Memory 系统上模拟 **GEMM/systolic 类计算带来的 compute/memory/NoC 压力**。

设计原则：
- 与主实验目录 `sst_dram_si/` **完全解耦**：脚本、输出与验证口径不混用；
- 复用现有平台核：`SnnDL.MultiCorePE` + `SnnDL.SnnPESubComponent` + `SnnDL.SnnNIC` + `merlin.mesh` + `memHierarchy`；
- 统计口径由组件端注册表决定：通过 `TENSOR_SI_WORKLOAD_STATS_MODULES` 选择聚合模块（避免在 `MultiCorePE.cc` 堆叠硬编码）。

---

## 快速开始（4×4 mesh）

```bash
cd "sst_workloads/tensor_si"
export TENSOR_SI_SIM_TIME="10us"
bash "./tools/run_tensor_mesh_with_time.sh"
```

输出位于 `outputs/tensor_mesh_4x4/<timestamp>/`，包含：
- `tensor_mesh_run.log`：SST 控制台输出
- `mesh_stats.csv`：每个 PE 的聚合统计（MultiCorePE）
- `essential_summary_tensor_mesh.json`：关键信息摘要（供回归/对比）
- `validation.log`：摘要校验结果（PASS/FAIL）
- `time.txt`：`/usr/bin/time -v` 资源统计

### `essential_summary_tensor_mesh.json` 口径说明（dashboard 友好）

`essential_summary_tensor_mesh.json` 是对 `mesh_stats.csv` 中 `tensor_*` 统计的聚合（PE 求和/求最大），并包含少量 **派生字段**（M36）用于简化可视化：
- `tensor_mem_read_latency_cycles_avg = tensor_mem_read_latency_cycles_total / tensor_mem_read_latency_samples_total`
- `tensor_mem_write_latency_cycles_avg = tensor_mem_write_latency_cycles_total / tensor_mem_write_latency_samples_total`
- 当 `samples==0` 时，`avg` 固定为 `0.0`（避免 dashboard 侧除零/缺字段分支）。

关于 program busy 相关字段（容易误读，特别说明）：
- `tensor_program_{dma,mxu,vec,coll}_busy_cycles_total`：对应 slot/engine 处于 `active` 状态的**占用周期**（即便当周期没有前进、或在 fence 等待中，也可能累计）。
- `tensor_program_any_busy_cycles_total`：当周期内发生了“前进”（`did_mem|did_compute|did_collective|did_comm` 任一为真）才 +1，更接近 **progress cycles**，不保证大于/小于各 busy 计数。
- 因此不要用 `any_busy` 作为 `dma_busy/mxu_busy/...` 的上界或分母；做利用率/占用分析时应分别使用各子系统总周期：
  - DMA：`tensor_dma_cycles_total`
  - compute(MXU)：`tensor_compute_cycles_total`
  - vector：`tensor_vector_cycles_total`
  - collective：`tensor_collective_cycles_total`

---

## Level-2：tile 执行语义（更真实的依赖/背压）

`bulk`（默认）是 iteration 粒度的快速模型；`tile` 是 tile-seg 粒度的推进模型，会把 compute 的推进与 DMA/内存 outstanding/backpressure 绑定，并输出 stall 分解统计（`tensor_stall_*`）。

```bash
cd "sst_workloads/tensor_si"
TENSOR_SI_TENSOR_EXEC_MODE="tile" \
TENSOR_SI_TENSOR_TILE_SCHEDULE="auto" \
TENSOR_SI_TENSOR_WRITEBACK_POLICY="at_end_of_k" \
bash "./tools/run_tensor_mesh_with_time.sh"
```

---

## Collective（近似建模 + 可选 barrier）

### 1) 注入 collective 流量（不阻塞）

```bash
cd "sst_workloads/tensor_si"
TENSOR_SI_TENSOR_COLLECTIVE_TYPE="allreduce" \
TENSOR_SI_TENSOR_COLLECTIVE_BYTES="1048576" \
TENSOR_SI_TENSOR_COLLECTIVE_PERIOD="100" \
TENSOR_SI_TENSOR_COLLECTIVE_PATTERN="ring" \
TENSOR_SI_TENSOR_COLLECTIVE_PACKET_BYTES="256" \
bash "./tools/run_tensor_mesh_with_time.sh"
```

### 2) blocking barrier（iteration 间等待）

当 `TENSOR_SI_TENSOR_COLLECTIVE_BLOCKING=1` 时，将 collective 当作 iteration 间 barrier：
- `per_core`：每个 core 独立等待自身 epoch `recv_bytes >= expected` 后继续（默认）
- `per_pe`：同一 PE 内所有 cores 的 epoch 完成后，PE 内任一 core 才能进入下一 iteration
- `per_system`：全系统（nodes×cores）epoch 完成后，系统内任一 core 才能进入下一 iteration

```bash
cd "sst_workloads/tensor_si"
TENSOR_SI_TENSOR_COLLECTIVE_TYPE="allreduce" \
TENSOR_SI_TENSOR_COLLECTIVE_BYTES="1048576" \
TENSOR_SI_TENSOR_COLLECTIVE_PERIOD="100" \
TENSOR_SI_TENSOR_COLLECTIVE_PATTERN="ring" \
TENSOR_SI_TENSOR_COLLECTIVE_PACKET_BYTES="256" \
TENSOR_SI_TENSOR_COLLECTIVE_BLOCKING="1" \
TENSOR_SI_TENSOR_COLLECTIVE_SCOPE="per_system" \
bash "./tools/run_tensor_mesh_with_time.sh"
```

说明：
- `tensor_collective_algo=legacy_bytes`（默认）保持历史的“字节注入 + barrier”口径。
- M3 新增 `tensor_collective_algo=ring_chunked`，支持 chunk + ring step + reduce-wait（近似）语义：
  - `TENSOR_SI_TENSOR_COLLECTIVE_CHUNK_BYTES`
  - `TENSOR_SI_TENSOR_COLLECTIVE_REDUCE_OVERHEAD_CYCLES`
  - `TENSOR_SI_TENSOR_COLLECTIVE_MAX_INFLIGHT_CHUNKS`
  - M4 新增 collective credit/backpressure（用于更接近协议级拥塞反馈）：
  - `TENSOR_SI_TENSOR_COLLECTIVE_CREDIT_ENABLE`：开启 credit 窗口节流
  - `TENSOR_SI_TENSOR_COLLECTIVE_CREDIT_WINDOW_CHUNKS`：窗口大小（chunk）
  - `TENSOR_SI_TENSOR_COLLECTIVE_CREDIT_RETURN_MODE`：credit 回收模式（`event_on_recv|legacy_tick`，默认 `event_on_recv`）
  - `TENSOR_SI_TENSOR_COLLECTIVE_BACKPRESSURE_MODE`：`hard|soft`
  - 新统计：`tensor_collective_credit_stall_cycles_total`、`tensor_collective_backpressure_stall_cycles_total`、`tensor_collective_inflight_chunks_max`
  - M5 扩展统计：`tensor_collective_credit_return_pkts_{sent,recv}_total`、`tensor_collective_credit_return_{orphan,dup}_total`、`tensor_collective_credit_return_latency_cycles_{total,max}`
  - M5（当前实现）在 `event_on_recv` 下采用按 key 批量 credit 回传：
    - key = `(seq, chunk, step, src_node, src_core)`
    - `TCCR` 包中的 `credits` 字段可大于 1（不再固定每包 1-credit）
    - 发送侧可通过 `legacy_tick` 回退到旧语义
- `per_pe/per_system` 会额外注入少量 `Control` 包做 DONE 聚合与 RELEASE 广播；可在 `tensor_pkt_{sent,recv}_total` 中观察到。
- M2 起支持 NoC 预算与重叠策略：
  - `TENSOR_SI_TENSOR_NOC_BW`：NoC 发包预算（bytes/cycle，`0`=不限制）
  - `TENSOR_SI_TENSOR_COLLECTIVE_OVERLAP_WITH_COMPUTE`：collective 与 compute 是否允许同周期重叠（`1/0`）
  - `TENSOR_SI_TENSOR_COLLECTIVE_ISSUE_PRIORITY`：NoC 仲裁优先级
    - `control_first`：collective 优先，再发 `comm`
    - `payload_first`：`comm` 优先，再发 collective

---

## 统计模块（workload-stats）

通过环境变量 `TENSOR_SI_WORKLOAD_STATS_MODULES` 选择聚合模块（逗号分隔）：

```bash
cd "sst_workloads/tensor_si"
TENSOR_SI_WORKLOAD_STATS_MODULES="tensor,stream" bash "./tools/run_tensor_mesh_with_time.sh"
```

当前常用模块：
- `tensor`：导出 `tensor_*`（compute/mem/NoC/rawbytes/collective/stall 分解等）
- `stream`：导出 `stream_*`（通信 + 内存 read-after-write 校验相关计数；用于对照）

---

## 常用环境变量（入口）

- mesh/系统：`TENSOR_SI_SIM_TIME`、`TENSOR_SI_MESH_SIZE`、`TENSOR_SI_NODE_LIMIT`、`TENSOR_SI_NETWORK_BW`、`TENSOR_SI_BUFFER_SIZE`、`TENSOR_SI_NETWORK_NUM_VNS`、`TENSOR_SI_MEM_ACCESS_TIME`
- core 布局：`TENSOR_SI_NUM_CORES_PER_PE`、`TENSOR_SI_NEURONS_PER_CORE`、`TENSOR_SI_CORE_MEM_REGION_BYTES`
- tensor（GEMM）：`TENSOR_SI_TENSOR_M`、`TENSOR_SI_TENSOR_N`、`TENSOR_SI_TENSOR_K`、`TENSOR_SI_TENSOR_ELEMENT_BYTES`、`TENSOR_SI_TENSOR_ARRAY_M`、`TENSOR_SI_TENSOR_ARRAY_N`、`TENSOR_SI_TENSOR_EFF`
- compute 档位：`TENSOR_SI_TENSOR_COMPUTE_PRECISION`、`TENSOR_SI_TENSOR_COMPUTE_PROFILE_OVERRIDE`、`TENSOR_SI_TENSOR_COMPUTE_THROUGHPUT_SCALE`、`TENSOR_SI_TENSOR_COMPUTE_PIPELINE_LATENCY`
- exec/tile：`TENSOR_SI_TENSOR_EXEC_MODE`、`TENSOR_SI_TENSOR_DATAFLOW`、`TENSOR_SI_TENSOR_TILE_M`、`TENSOR_SI_TENSOR_TILE_N`、`TENSOR_SI_TENSOR_TILE_K`、`TENSOR_SI_TENSOR_TILE_SCHEDULE`、`TENSOR_SI_TENSOR_WRITEBACK_POLICY`
- on-chip/DMA：`TENSOR_SI_TENSOR_UB_BYTES`、`TENSOR_SI_TENSOR_WEIGHT_BYTES`、`TENSOR_SI_TENSOR_ACC_BYTES`、`TENSOR_SI_TENSOR_DMA_BW`、`TENSOR_SI_TENSOR_DMA_BW_SHARED`、`TENSOR_SI_TENSOR_DMA_HBM_CHANNELS`、`TENSOR_SI_TENSOR_DMA_HBM_CH_BW`、`TENSOR_SI_TENSOR_DMA_HBM_CH_INTERLEAVE`、`TENSOR_SI_TENSOR_DOUBLE_BUFFER`、`TENSOR_SI_TENSOR_MEM_REQ_BYTES`、`TENSOR_SI_TENSOR_MEM_MAX_OUT`
- on-chip(M3)：`TENSOR_SI_TENSOR_ONCHIP_MODEL_ENABLE`、`TENSOR_SI_TENSOR_UB_BANK_BYTES`、`TENSOR_SI_TENSOR_UB_READ_PORTS`、`TENSOR_SI_TENSOR_UB_WRITE_PORTS`、`TENSOR_SI_TENSOR_ACC_BANK_BYTES`、`TENSOR_SI_TENSOR_ACC_READ_PORTS`、`TENSOR_SI_TENSOR_ACC_WRITE_PORTS`、`TENSOR_SI_TENSOR_SPILL_ENABLE`、`TENSOR_SI_TENSOR_SPILL_PACKET_BYTES`、`TENSOR_SI_TENSOR_SPILL_SHARE_NOC_BUDGET`
- on-chip(M4 bank-aware)：`TENSOR_SI_TENSOR_ONCHIP_BANK_MODEL_ENABLE`、`TENSOR_SI_TENSOR_UB_BANK_COUNT`、`TENSOR_SI_TENSOR_UB_BANK_SELECT_POLICY`、`TENSOR_SI_TENSOR_UB_BANK_CONFLICT_MODE`、`TENSOR_SI_TENSOR_ACC_BANK_COUNT`、`TENSOR_SI_TENSOR_ACC_BANK_SELECT_POLICY`、`TENSOR_SI_TENSOR_ACC_BANK_CONFLICT_MODE`、`TENSOR_SI_TENSOR_BANK_QUEUE_DEPTH`
- collective：`TENSOR_SI_TENSOR_COLLECTIVE_TYPE`、`TENSOR_SI_TENSOR_COLLECTIVE_BYTES`、`TENSOR_SI_TENSOR_COLLECTIVE_PERIOD`、`TENSOR_SI_TENSOR_COLLECTIVE_PATTERN`、`TENSOR_SI_TENSOR_COLLECTIVE_PACKET_BYTES`、`TENSOR_SI_TENSOR_COLLECTIVE_BLOCKING`、`TENSOR_SI_TENSOR_COLLECTIVE_SCOPE`、`TENSOR_SI_TENSOR_COLLECTIVE_ALGO`、`TENSOR_SI_TENSOR_COLLECTIVE_CHUNK_BYTES`、`TENSOR_SI_TENSOR_COLLECTIVE_REDUCE_OVERHEAD_CYCLES`、`TENSOR_SI_TENSOR_COLLECTIVE_MAX_INFLIGHT_CHUNKS`、`TENSOR_SI_TENSOR_NOC_BW`、`TENSOR_SI_TENSOR_COLLECTIVE_OVERLAP_WITH_COMPUTE`、`TENSOR_SI_TENSOR_COLLECTIVE_ISSUE_PRIORITY`
- collective(M4/M5 credit/backpressure)：`TENSOR_SI_TENSOR_COLLECTIVE_CREDIT_ENABLE`、`TENSOR_SI_TENSOR_COLLECTIVE_CREDIT_WINDOW_CHUNKS`、`TENSOR_SI_TENSOR_COLLECTIVE_CREDIT_RETURN_MODE`、`TENSOR_SI_TENSOR_COLLECTIVE_BACKPRESSURE_MODE`
- 统计模块：`TENSOR_SI_WORKLOAD_STATS_MODULES`

---

## 回归 Gate（M4/M5 + 漂移告警）

```bash
# 只跑 M5 gate（跳过 unit）
bash "tools/run_tensor_m5_gate.sh" --skip-unit

# M5 gate + 漂移告警（event_hard 对比基线）
bash "tools/run_tensor_m5_gate.sh" \
  --skip-unit \
  --drift-baseline "/path/to/baseline_event_hard_summary.json" \
  --drift-threshold "0.30"

# 统一入口：DRAM-SI smoke + tensor smoke + tensor m4/m5 gate
SNNDL_GATE_BUILD=0 \
SNNDL_GATE_MESH_MAX_STEPS=1 \
SNNDL_GATE_TENSOR_SIM_TIME=1us \
bash "tools/run_snndl_regression_gate.sh"
```

统一入口常用开关：
- `SNNDL_GATE_TENSOR_MGATES=1|0`：是否串联 tensor m4/m5 gate（默认 1）
- `SNNDL_GATE_TENSOR_MGATES_SKIP_UNIT=1|0`：m4/m5 gate 是否跳过 unit（默认 1）
- `SNNDL_GATE_MESH_VALIDATE_PROFILE=dev|paper`：DRAM-SI 验收口径（默认 `dev`）
- `SNNDL_GATE_TENSOR_M5_DRIFT_BASELINE=/path/to/summary.json`：统一入口传递 M5 漂移基线
- `SNNDL_GATE_TENSOR_M5_DRIFT_THRESHOLD=0.30`：统一入口传递 M5 漂移阈值

---

## 作为模板创建新 workload 目录（推荐）

```bash
bash "sst_workloads/tools/new_workload_dir.sh" "<new_workload_dir_name>"
```

脚本会以 `tensor_si` 为模板拷贝目录结构（自动排除 `outputs/analysis/__pycache__`），然后你可以在新目录内替换：
- Python 包名/入口脚本（例如 `tensor_template/*` 的 import 路径）
- `tools/run_*` 脚本名称与输出目录前缀
