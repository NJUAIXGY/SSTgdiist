# GCSSIDX2（Row-MPHF）：把 GCSS 常驻索引压到 values/10 的实验方案（隔离落地 + 闭环验证）

作者：浮浮酱（nekomata-engineer）  
日期：2026-03-01  
基线口径：`4x4 bcsr10k step1`（Ramulator2 DDR5，`apply_issue_policy=order`，semseal 严格验证）

> 背景：现有 `GCSSIDX1`（显式 pre 列表 + posts 列表 + per-edge widx）在 `bcsr10k` 上约 `~1.10 MiB/core`，
> 而 values-only (`gcss.bin`) 约 `~500 KiB/core`，索引反而比 values 大（本末倒置）。
>
> 目标：把“常驻 SRAM 的索引”压制到 **比 values 小一个数量级**，即：
> - 以当前数据集为例：`values≈512000 B/core`，目标 `index<=51200 B/core`（<=50 KiB/core）。
> - 等价的 bits/edge 目标：`index_bits_per_edge <= 3.2`（因为 values=32 bits/edge）。
>
> 本文给出 `GCSSIDX2`：**Row-MPHF（按 post 分行的最小完美哈希）+ row-major values**，
> 并提供隔离落地与 memop 闭环验证方案。

---

## 0. 关键假设（已确认，决定压缩是否可做到 10x）

1. **运行时不会对不存在的 `(pre_global, post_local)` 做 lookup**。一旦出现此类情况，视为 bug（fail-fast）。
2. 因此 `GCSSIDX2` 的 on-chip 索引 **不需要 membership check**（不需要布隆/指纹），可以按“纯 MPHF/retrieval”极致压缩。
3. 权重拓扑与 values 内容为静态（离线生成）；在线学习/插删边不在本方案范围。

> 解释：MPHF 对“集合内 key”是完美映射；对“集合外 key”会给出未定义位置。
> 我们用“不会发生集合外查询”的系统约束替代 membership check，从而把索引压到 few-bits/key 量级。

---

## 1. 设计总览（GCSSIDX2 是“DRAM-based”系统的正确姿势）

**核心方向**：
- DRAM：只存 `float32` values（values-only stream），仍走每 PE 本地地址域（dst_core resident）。
- SRAM：只存“足以把 `(post_local, pre_global)` 映射到行内 slot”的 few-bits/key 结构。

**为什么 values 必须 row-major（按 post 分行）**：
- GAS 的边 key/退役顺序是 `(post, pre)`（post-major），这会影响“真实访问地址序列”。
- 之前 A(pre_post clustered) 证明：只追求 values 连续而忽略 DRAM row/bank 语义，会导致 `row_hit_rate` 崩盘与冲突暴涨，出现“流量降了但时间没降”。
- 因此 `GCSSIDX2` 选择 **row-major values**：把“局部性”对齐到 GAS 的确定性顺序，避免 row-thrash。

**预计 SRAM 索引开销（以 bcsr10k 当前规模直观估算）**：
- 每 core edges `E≈128k`，bucket 目标 `t=4`：pilot 数量约 `E/4≈32k` 个，若 pilot=1B，则 `~32KB`。
- 再加 per-row 元数据（`row_base/seed/bucket_off/len`）约 `~7–10KB`。
- 合计期望 `~40KB/core`（<< 50KB/core），满足 values/10（并留出一定余量）。

---

## 2. 文件与数据格式（严格隔离，不影响 GCSSIDX1）

### 2.1 DRAM values：`coreXX.gcss2.bin`（row-major，raw float32）

- 内容：连续 `float32`（little-endian），无 header。
- 逻辑布局：
  - `row_base[r]`：第 `r` 行（`post_local=r`）在 values 数组的起始 index（单位：float 元素）
  - 行内 slot `pos`：`widx = row_base[r] + pos`
  - DRAM 地址：`addr = base_addr + 4*widx`
- 约束：`len(values) == edges_total`（全 core 所有行 edges 之和）。

### 2.2 SRAM 索引：`coreXX.gcss2.idx.bin`（Row-MPHF，纯映射）

目标：给定 `(post_local=r, pre_global)`，O(1) 算出 `pos`，再得到 `widx`。

#### 2.2.1 Header（建议 v2）

```
struct GcssIdx2HeaderV1 {
  char magic[8];          // "GCSSIDX2"
  uint32_t version;       // 1
  uint32_t rows_per_core; // e.g. 500
  uint32_t edges_total;   // total edges (sum row_len)
  uint32_t bucket_target; // e.g. 4
  uint32_t pilot_bits;    // 8 (must be 8 for size goal)
  uint32_t hash_kind;     // 1=splitmix32-like
  uint32_t flags;         // bit0=strict_mode
};
```

#### 2.2.2 Arrays（紧凑存储；全部 little-endian）

- `uint32_t row_base[rows_per_core+1]`
- `uint16_t row_len[rows_per_core]`：每行 edges 数（典型 200–300）
- `uint32_t row_seed[rows_per_core]`：每行 seed（用于 hash）
- `uint16_t row_bucket_count[rows_per_core]`：每行桶数 `B_r = ceil(row_len/t)`
- `uint32_t row_bucket_off[rows_per_core+1]`：pilot 拼接偏移（单位：pilot 元素）
- `uint8_t pilots[sum(row_bucket_count)]`：每桶一个 pilot（8-bit）

> 注：若某行构建无法在 8-bit pilot 下成功，生成器应换 seed 重试；不允许 silent fallback 到 16-bit pilot，
> 因为这会直接破坏 “index<=values/10” 的目标。失败就离线报错并中止生成。

---

## 3. Row-MPHF 生成算法（离线，确定性，可自检）

位置建议（实验隔离）：`sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_idx2_rowmphf.py`

### 3.1 输入与边集合一致性（避免“集合外查询”）

- 输入权重来源：与 route builder 同源（BCSR dir），并使用完全一致的过滤规则：
  - `routing_epsilon`
  - core 划分（rows_per_core）
  - `(pre_global, post_local)` 的定义与映射
- 生成器必须输出 manifest（JSON）：记录上述参数 + 关键 hash/版本号，便于 run_dir 追溯。

### 3.2 每行构建（bucket + pilot）

对固定行 `r`：
1. 收集该行的 keys：`K_r = {pre_global}`，以及对应 `weight(pre_global)`。
2. 设 `L = |K_r| = row_len[r]`，桶数 `B = ceil(L / bucket_target)`。
3. 桶分配：`bucket = h1(pre_global, seed_r) % B`。
4. 桶内映射函数（给定 pilot `p`）：
   - `pos = (h2(pre_global, seed_r) + p) % L`
5. 依 bucket size 降序处理：为每个桶寻找 `p in [0..255]`，使桶内所有 key 映射到未占用 slot。
6. 若某桶 256 个 pilot 均失败：递增 `seed_r` 并重试该行（全行重来，确保确定性）。

### 3.3 values 填充（row-major）

一旦行 `r` 的每个 key 都有唯一 `pos`：
- 写入 values：`values[row_base[r] + pos] = weight(pre_global)`

### 3.4 自检（必须）

生成器必须提供 `--self-check`：
- 对每行检查 slot 占用无冲突，且覆盖 `L` 个 key。
- 对每个 key 重新用 `(seed, pilots)` 计算 `pos`，验证取回的 weight 与原 weight 完全一致（或容差极小）。
- 可选：对每 core 抽样 N 条边，用 BCSR 解析出的 weight 与 gcss2 values 对比。

---

## 4. Runtime 接入点（不改 GAS 语义，强隔离）

### 4.1 新模式字符串（仅实验模式可用）

- 新增 `synapse_weight_mode=gcss_valueonly_dstcore_idx2`（或 alias：`gcss_idx2_rowmphf`）
- 仅在 `MESH_EXPERIMENTAL_ENABLE=1` 时允许启用（避免误入主线）

### 4.2 新索引加载器（新文件承载，避免堆砌）

新增文件（建议）：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexRowMphf.h`

职责：
- 解析 `GCSSIDX2` header + arrays
- 提供 `lookup(pre_global, post_local) -> widx`

### 4.3 WeightMemorySubsystem 行为

当 mode 为 idx2：
- init：按 `gcss_index_template` 加载 `.gcss2.idx.bin`
- lookup：
  - `r = post_local`（0..rows_per_core-1）
  - `b = h1(pre, seed[r]) % bucket_count[r]`
  - `p = pilots[row_bucket_off[r] + b]`
  - `pos = (h2(pre, seed[r]) + p) % row_len[r]`
  - `widx = row_base[r] + pos`
- issue：复用现有 `requestGCSS_(widx)`（DRAM read 仍是 `base+4*widx`）

严格性：
- 对“集合外查询”不做 membership check；但对明显非法情况 fail-fast：
  - `post_local>=rows_per_core`
  - `row_len[r]==0`
  - 文件加载失败/格式错误
- 可保留一个调试开关 `MESH_GCSS_IDX2_DEBUG_SAMPLE_CHECK=1`：
  - 只在模拟器端启用：随机抽样少量 lookup，用 BCSR/manifest 做对照（不计入 SRAM 面积口径）。

---

## 5. 验证与统计（必须能“证明目标达成”）

### 5.1 SRAM 索引大小（核心目标统计）

离线统计（从 weights dir 扫描得到，进入 memop 快照与论文表）：
- `idx2.index_total_bytes`
- `idx2.index_bytes_per_core_{min,p50,p90,max}`
- `idx2.values_total_bytes`（`gcss2.bin` 总大小）
- `idx2.index_to_values_ratio`
- `idx2.index_bits_per_edge`（= `8*index_total_bytes/edges_total`）

建议把这组统计写入：
- `memop/experiments/<exp>/snapshot/compare.tsv`（新增列）
或
- `essential_summary_mesh.json` 的 `synapse.index_cost`（由 summary 脚本在 run_dir 生成时离线补齐）

### 5.2 正确性与语义（必须）

semseal 口径：
- `validation.log`: `fail=0 warn=0`
- `gcss_lookup_miss_total == 0`（idx2 模式下建议把“lookup 次数”计入 hit；miss 仅用于捕捉非法行/空行等 fatal 前置错误）

### 5.3 内存侧收益与 DRAM 行局部性（必须）

从 `essential_summary_mesh.json` 提取（与现有 GCSS v1 同口径可比）：
- `memhierarchy.memctrl.req_total / bytes_est_total`
- `ramulator2.row_hit_rate_total / row_conflict_rate_total / avg_read_latency_0_avg`
- `gas.apply_ns_avg / gas.cycle_cost`
- `synapse.read_source.gcss.{reqs,bytes}`（验证 meta read 归零）

---

## 6. 闭环实验矩阵（memop 承载，严格隔离）

实验目录建议：
- `memop/experiments/2026-03-xx_gcss_idx2_rowmphf_bcsr10k_step1_semseal_v1/`

cases（至少 3 组）：
1. `baseline_bcsr_gas`
2. `gcss_v1_noA_scan`（现有最佳时间收益对照）
3. `gcss_idx2_rowmphf_rowmajor`（本方案）

运行建议（示意）：
```bash
cd /home/xgy/remote/sst_dram_si
export MESH_EXPERIMENTAL_ENABLE=1
export MESH_MAX_STEPS=1
export MESH_MEM_BACKEND=ramulator2
export MESH_RAMULATOR2_CONFIG_FILE=/home/xgy/remote/sst_dram_si/configs/ramulator2_ddr5.cfg
export MESH_EXEC_MODE=gas
export MESH_SYNAPSE_WEIGHT_MODE=gcss_valueonly_dstcore_idx2
export MESH_GCSS2_DIR=$PWD/weights/gcss_valueonly_dstcore_idx2_rowmphf_fanout256_10k_v1
./tools/run_mesh_with_time.sh
```

---

## 7. 落地状态（2026-03-02，已完成首轮闭环）

### 7.1 代码已落地

- 生成器（并行版）：
  - `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_idx2_rowmphf.py`
  - 新增 `--jobs` 多进程并行（按 core）
  - 当前稳定参数：`bucket_target=3`（`bucket_target=4` 在真实行分布上存在不可构建行）
- 运行时：
  - `services/synapse/weights/GcssIndexRowMphf.h`
  - `WeightMemorySubsystem` 已接入 `gcss_valueonly_dstcore_idx2` / `gcss_idx2_rowmphf`
  - idx2 lookup miss 已按 strict fail-fast 处理
- mesh_template：
  - 新增 `MESH_GCSS2_DIR`
  - `synapse_weight_mode` 支持 `gcss_valueonly_dstcore_idx2`
  - 护栏：idx2 需 `MESH_EXPERIMENTAL_ENABLE=1`

### 7.2 生成结果（全量 16PE × 20core）

命令：
```bash
python3 sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_idx2_rowmphf.py \
  --bcsr-dir sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2 \
  --out-dir sst_dram_si/weights/gcss_valueonly_dstcore_idx2_rowmphf_fanout256_10k_v2_j32 \
  --epsilon 1e-8 \
  --bucket-target 3 \
  --max-seed-tries 4096 \
  --jobs 32
```

结果（done 行）：
- `cores=320`
- `total_edges=40960000`
- `values_total_bytes=163840000`
- `index_total_bytes=16280915`
- `index_to_values_ratio=0.099371`
- `index_bits_per_edge=3.1799`
- 总耗时约 `654s`（约 `10m54s`）

### 7.3 闭环实验结果（4x4 bcsr10k step1, Ramulator2）

run_dir：
- baseline：`.../baseline_bcsr_gas/20260302-032212`
- gcss_v1：`.../gcss_v1_scan/20260302-032956`
- gcss_idx2：`.../gcss_idx2_rowmphf/20260302-033521`

关键结论：
- 三组 semseal：`fail=0`
- idx2 与 v1 性能接近（step1）：
  - `sim_time_actual_ns`：idx2 `0.542x` baseline，v1 `0.523x` baseline
  - `memctrl.req_total`：idx2 `0.615x` baseline，v1 `0.616x` baseline
  - `row_hit_rate_total`：idx2 `1.088x` baseline，v1 `1.085x` baseline
- 索引成本目标达成：
  - v1：`index_to_values_ratio=2.262`（索引明显大于 values）
  - idx2：`index_to_values_ratio=0.099`（索引压到 values/10 以内）

成功标准（硬门槛）：
- `idx2.index_bytes_per_core_p50 <= values_per_core/10`（<=50KiB/core）
- semseal PASS（fail=0 warn=0）

成功标准（性能/内存侧期望）：
- `ramulator2.row_hit_rate_total` 不应像 `A(pre_post)` 那样崩盘；
- `gas.cycle_cost` 至少不劣于 `gcss_v1_noA_scan`（允许小幅噪声，但不能系统性回归）。

---

## 7. 关键风险与对策（实验隔离下可接受）

1. **集合不一致导致“集合外查询”**（这是最危险的 silent-bug）  
   - 对策：生成器与 route builder 同源/同过滤；manifest 记录参数；必要时启用 debug sample check。
2. **离线构建失败**（某行在 8-bit pilot 下找不到映射）  
   - 对策：seed 重试（deterministic）；必要时调整 bucket_target（不允许 pilot_bits 升级）。
3. **row-locality 回归**  
   - 对策：values 固定 row-major；若仍回归，优先检查 bank/row 映射（`bank_auto_enable` 与 `row_bytes_guess`）而不是盲目重排。

---

## 8. 参考（背景阅读，用于论文相关工作）

- Perfect hash / minimal perfect hash 概念综述：https://en.wikipedia.org/wiki/Perfect_hash_function
- “pilot + buckets” 方向（代表性论文/系统）：PTHash / PtrHash（可作为实现灵感，但我们的设计需与 GAS 语义、dst_core resident 约束联合建模）
