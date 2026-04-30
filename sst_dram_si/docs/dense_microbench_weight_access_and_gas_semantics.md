# Dense Microbench：权重存储/读路径与 GAS 合并语义（cacheline 口径）

作者：浮浮酱  
最后更新：2026-01-19  

本文件用于把 dense microbench 下的“权重如何存储、一次读到底读多少字节、GAS 合并会如何改变访存口径”讲清楚，并记录一组可复现的实验与结论，便于主人和其他同学讨论。

## 1. 结论先行（本文件要解决什么）

1. dense 权重是 **FP32（4B/weight）** 的二维矩阵；当前微基准默认走 **cacheline=64B** 的请求粒度（每次读 16 个 float，行尾可能短读）。
2. 你们看到的“GAS 在低负载下 memory 更大、高负载下更小”的现象，在 dense 场景里很大概率来自：
   - dense 的 row stride 恰好是 **2000B（500 cols * 4B）**；
   - 当 `gas_gap_k_bytes` 设到 **2048B** 这种“略大于 row stride”的值时，GAS 的 gap-merge 可能把“跨 row 的稀疏访问”合并成“覆盖整段 row 间隔”的大段读取，造成 **over-fetch**；
   - 负载升高后访问更密集，合并/去重可能开始回本，导致请求数下降。
3. 若目标语义是“主流通用体系结构（cacheline/memHierarchy）”，建议把 dense 的默认模型收敛为：
   - **cacheline 粒度**为主（避免把 row-streaming/DMA 假设当作默认）；
   - gap-merge 必须与 row stride 绑定（例如 `gas_gap_k_bytes < row_stride_bytes`），否则会系统性跨 row 吸洞。

## 2. 复现入口与脚本

### 2.1 运行脚本

- `sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh`
  - 输出目录：`sst_dram_si/outputs_large/paper2/dense_microbench_1pe_exec_mode_compare/<mode>/<ts>/`
  - 注：该脚本已改为纳秒级时间戳（`%N`），避免矩阵实验在同一秒内覆盖输出目录。

### 2.2 运行配置

- `sst_dram_si/microbench_dense_1pe/local_run_config.json`
  - `neurons_per_core=500`，`mesh_size=1`，`num_cores_per_pe=1`
  - `line_size_bytes=64`
  - `l1_enable=false`（微基准默认不启用 L1）

### 2.3 常用环境变量（无需改 json）

- `MESH_EXEC_MODE=gas|naive_raw`
- `MESH_MAX_STEPS=1`（推荐 microbench 默认 1 step）
- `MESH_STEP_ACTIVATION_SEED=314159`（建议固定）
- `MESH_STEP_ACTIVATION_FRACTION=...`
- `MESH_STEP_ACTIVATION_FANOUT=256`
- `MESH_DENSE_STRICT_CACHELINE=0|1`
  - `1`：强制 strict cacheline（dense 场景禁用 gap merge 等会扩大粒度的策略）
  - `0`：允许 dense 场景启用 gap merge（仅用于研究“合并策略”的影响；结论需谨慎解读）

## 3. dense 权重数据模型：存储布局与地址计算

### 3.1 数据类型与字节数

- 每个权重：`float`（FP32）= 4 bytes

### 3.2 dense 矩阵的维度与 stride

在 1PE/1core microbench 中：

- rows = `neurons_per_core` = 500
- cols = `global_weights_cols` = total_nodes * neurons_per_pe = 1 * 500 = 500
- row_stride_bytes = cols * 4 = 500 * 4 = **2000B**
- dense_bytes_total = rows * cols * 4 = 500 * 500 * 4 = **1,000,000B**

微基准构建时会把 per-core weight region 做对齐（默认 8192B）：

- 代码：`sst_dram_si/microbench_dense/entry.py`
  - `dense_bytes = neurons_per_core * global_weights_cols * 4`
  - `per_core_weight_stride = align_up(dense_bytes, 8192)`

### 3.3 单个权重的地址公式

对（row, col）对应的权重标量：

```
addr = base_addr + (row * width + col) * 4
```

实现位置：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
  - `WeightMemorySubsystem::prepareDenseRead_()`：计算 `req_addr`

## 4. dense 权重读路径：从 spike 到 DRAM 请求

### 4.1 关键链路（简化）

1) Step 激活注入（microbench）

- `sst_workspace/.../services/stimulus/StepActivationSubsystem.cc`
  - `onGlobalStepStart(seq, ts_ns)` / `tick()` 触发一次注入

2) SNN workload 处理 spike → 权重读请求

- `sst_workspace/.../services/workload/snn/SnnWorkload.cc`
  - window-mode：BeginApply 时调用 `weight_mem_subsystem_->issueFromEdges()`
  - naive_raw：通常是 spike 到达即 `requestDense_()`（无 GAS/无窗口聚合）

3) WeightMemorySubsystem 解析/构造 dense read

- `sst_workspace/.../services/synapse/weights/WeightMemorySubsystem.cc`
  - `requestDense_(pre, post, cb)`
  - `issueDenseResolved_(row_idx, col_idx, cb_col, cb)`
  - `prepareDenseRead_(...)`（决定“这次到底读 4B / 64B / 整行”）

4) IMemoryAccess 发起 read

- `sst_workspace/.../api/IMemoryAccess.h`
- `sst_workspace/.../services/memory/StandardMemAccess.*`（标准 memHierarchy 接入）
- `sst_workspace/.../components/CachelineFragmentMemIF.*`（naive_raw baseline 的 cacheline 分片前端）
- `sst_workspace/.../components/GatherBufferIF.*`（GAS gather/apply 合并前端）

### 4.2 每次读到底读多少字节（dense 的核心）

决定读粒度的位置：

- `WeightMemorySubsystem::prepareDenseRead_()`（同上）

当前默认（SNN workload）：

- `merge_read_cacheline=1`
- `merge_read_row=0`
- `merge_read_auto=0`
- `line_size_bytes=64`

因此 dense 下单个权重（4B）会被“扩成一个 cacheline 覆盖”：

- `floats_per_line = line_size_bytes / 4 = 16`
- `col_start = floor(col / 16) * 16`
- `count_floats = min(16, width - col_start)`
- `req_size = count_floats * 4`（通常 64B，行尾可能 <64B）

注意：`row_stride_bytes=2000B` 不是 64B 对齐（`2000 mod 64 = 16`），所以跨 row 的地址序列容易出现“跨 cacheline 边界/非对齐”，在合并时会更容易触发额外的 cacheline 覆盖。

## 5. GAS 合并语义：是否符合你们的流程描述？

### 5.1 三阶段的“职责边界”（代码层面）

对齐你们的描述，当前实现大体符合：

- Gather：收集上游 read（或边集合）到 staging（窗口内不立即把每条边变成 mem req）
- Apply：
  - 从上一窗的 edge 集合出发，映射到权重地址
  - 将地址段按策略（cacheline/row/auto）归一化后排序
  - 可选 gap-merge / row-window 触发
  - 形成 granule 段后下发到内存
- Scatter：对 accumulator 的（post, dv）做一次性应用并发射 spike（microbench freeze-dynamics 时几乎无发放）

### 5.2 “≈512B（≈8×64B cacheline）”可能来源

主人提到的 “三档都稳定在 ~512B” 这种现象，通常意味着“整个 step 里只发生了极少数 cacheline 读”。浮浮酱建议按下面两类根因排查：

1) **step 注入/edge 记录没有真正生效**，导致窗口没有产生权重读（只剩初始化阶段的少量读/校验读）
   - 典型症状：`step_activation.spike_attempts_total` 明显 >0，但 `gas.synapse_ops_step_total` 或 `memory.memory_requests` 异常接近 0（或恒定很小）。
2) **节流阈值把窗口读截断**（例如 `window_read_budget` / `max_outstanding_requests` 过小）
   - 典型症状：spike_attempts_total 增大，但 `memory_requests` 在一个小常数附近“顶住”。

建议快速判别方法：优先看 `essential_summary_mesh.json` 的

- `step_activation.spike_attempts_total`
- `gas.synapse_ops_step_total`
- `memory.memory_requests`

若 attempts 明显增长但 memory_requests 不动，基本就是 gate/budget 生效了。

## 6. 近期实验记录（1PE，l1=0，seed=314159，max_steps=1）

以下为已完成的 1-step 结果（主人后续要做完整矩阵时可按此表扩展）：

| mode | fraction | pre_selected_total | spike_attempts_total | memory_requests | memory_bytes | unique_reads_total | unique_bytes_total | avg_granule_bytes | cycle_cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gas | 0.001 | 1 | 256 | 194 | 12416 | 194 | 21952 | 113.15 | 1225 |
| naive_raw | 0.001 | 1 | 256 | 256 | 16384 | - | - | - | 1271 |
| gas | 0.01 | 7 | 1792 | 3388 | 216832 | 2420 | 271360 | 112.13 | 5157 |
| naive_raw | 0.01 | 7 | 1792 | 1792 | 114688 | - | - | - | 3958 |
| gas | 0.05 | 22 | 5632 | 4096 | 262144 | 3000 | 336000 | 112.00 | 6171 |

注：

- `memory_*`：SnnDL 发起到内存前端（cacheline=64B）的请求口径，因此 `memory_bytes = memory_requests * 64`。
- `unique_*`：GAS 侧“段（granule）口径”，粒度可能不是 64B 对齐，因此会与 `memory_*` 不一致；它更接近“合并前的逻辑覆盖区间”。

## 7. 为什么会出现“低负载 gas 更大、高负载更小”（结合 dense 的地址序列）

关键事实：

- dense 地址是按 row-major 排列；
- 在 post-row/pre-col 布局下，固定 pre（列）时跨 post（行）的地址步长是 `row_stride_bytes=2000B`；
- 当 `gas_gap_k_bytes` 取到 **2048B** 这种“刚好覆盖 row stride”的阈值时，GAS 的 gap-merge 有机会把“相邻两行的 64B 读”合并为“覆盖两行之间 2000B 间隔”的大段读取：
  - 对稀疏访问：这属于典型 over-fetch，cacheline 事务数可能变大（因为你把原本不该读的 gap 也读进来了）。
  - 对密集访问：多个 row/多个 col 的访问彼此接近，合并/去重开始回本，请求数可能下降。

因此，这类现象不是“GAS 不正确”，而是说明：

- gap-merge 的 k 值与 dense 的 stride 存在强耦合；
- 若要默认建模通用 cacheline 体系结构，dense 下应避免让 k 跨过 row stride。

## 8. 推荐的下一步（把结论收敛成稳定、可解释的对比）

1) 以 cacheline 为默认语义：在 dense microbench 中把 `gas_merge_policy=cacheline` 固定为主口径；把 `row` 粒度作为“显式 row-streaming/DMA 假设”的另一组实验，不混写结论。
2) 对 gap-merge 做 stride-aware 约束（最小改动版）：
   - 计算 `row_stride_bytes = cols * 4`；
   - 建议默认满足：`gas_gap_k_bytes < row_stride_bytes`（例如直接设为 0 或 64/128）。
3) 做一个小 sweep 来验证趋势（先只跑 1 step）：
   - `fraction=0.01` 固定
   - `gas_gap_k_bytes in {0, 64, 512, 2048}`
   - 输出 `memory_requests/memory_bytes/cycle_cost` 与 GAS 的 `unique_bytes_total/avg_granule_bytes`

---

## 9. 关键代码定位索引

- dense layout / stride：
  - `sst_dram_si/microbench_dense/entry.py`
- dense 读粒度决策（4B vs 64B vs row）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
    - `WeightMemorySubsystem::prepareDenseRead_()`
- Step 注入：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/stimulus/StepActivationSubsystem.cc`
- window-mode BeginApply 发起：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- GAS 合并前端：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.*`
- naive_raw baseline cacheline 分片前端：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/CachelineFragmentMemIF.*`

