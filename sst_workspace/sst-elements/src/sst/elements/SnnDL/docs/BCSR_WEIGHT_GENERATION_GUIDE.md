# BCSR 权重文件：生成 / 校验 / 加载指南

本指南用于**稳定、可复现**地生成 SnnDL 所需的 BCSR 权重文件（含 `blockids`），并说明如何在 `sst_dram_si/test_mesh_4x4.py`（4×4 mesh 模版）中加载与验证。

> 适用场景：你需要（1）重建权重目录；（2）验证 meta/stride/对齐口径；（3）对照性能（GAS apply）与正确性（权重是否全 0）。

---

## 0. 背景：SnnDL 需要什么样的 BCSR 文件？

每个 **PE/core** 对应一个二进制文件：

- 例：`".../pe00/core00.bcsr.bin"`
- 配套 meta：`".../pe00/core00.bcsr.bin.meta.json"`

二进制布局（Little-endian，按 `align` 对齐）：

1. `rowptr`：`uint32[n_block_rows + 1]`
2. `colidx`：`uint16/uint32[nnz_blocks]`（由 `idx_bytes` 决定）
3. `blockdata`：`float32[nnz_blocks * br * bc]`
4. `blockids`：`uint32[nnz_blocks * br * bc]`

meta 必备字段（示例）：

- 维度：`rows/cols/br/bc`
- 编码：`idx_bytes/val_bytes`（当前权重仅支持 `val_bytes=4`）
- 布局偏移：`rowptr_offset/colidx_offset/blockdata_offset/blockids_offset`
- 文件：`file_size`、`total_blocks`

> **关于 `blockids`：** 在 mesh 模版的 Step/Reachability 路径中，`blockids` 被用于携带 “post_global”（或 sentinel），因此生成工具必须写出该段。

---

## 1. 推荐生成工具（仓库内置）

### 1.1 全局 Mesh BCSR 生成器（推荐）

脚本：`"sst_dram_si/tools/gen_bcsr_global_mesh.py"`

- 输出结构：`out_dir/pe{pe:02d}/core{core:02d}.bcsr.bin[.meta.json]`
- 支持：
  - `mode=outgoing`（推荐）：按 **pre 固定 fanout** 生成全局出边，再按 post 归并为各 PE/core 的入边集合
  - `mode=incoming`：按 **post 固定 fanout** 直接采样（更快，适合小样验证）

### 1.2 单核/单目录 BCSR 生成器（辅助）

脚本：`"sst_dram_si/tools/generate_bcsr.py"`

- 适用于：快速构造小规模格式样例，用于验证读取路径/偏移/对齐（不用于论文主数据集）。

---

## 2. 生成两类常用数据集（10k/PE 与 100k/PE）

> 建议**不要覆盖**现有稳定目录；优先生成到新目录后用 `MESH_BCSR_DIR` 指向新目录做 A/B 对比。

### 2.1 4×4 mesh（10k/PE，fanout=256，local_ratio=0.85）

- 参数口径：
  - `num_pes=16`
  - `neurons_per_pe=10000`
  - `cores_per_pe=20`
  - `rows_per_core=500`（20×500=10000）
  - `cols=16×10000=160000` ⇒ `bc=16` 时 `block_col_max=10000`，可用 `idx_bytes=2`

生成命令：

```bash
python3 "sst_dram_si/tools/gen_bcsr_global_mesh.py" \
  --num-pes 16 --neurons-per-pe 10000 \
  --cores-per-pe 20 --rows-per-core 500 \
  --fanout 256 --local-ratio 0.85 \
  --br 1 --bc 16 --idx-bytes 2 --align 64 \
  --mode outgoing \
  --out-dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_regen"
```

> 体积提示：该规模目录通常为 **GiB 级**（每 core 约 14–15MiB，16×20 cores 总计约 4–5GiB），请预留磁盘空间。

### 2.2 4×4 mesh（100k/PE，fanout=256，local_ratio=0.85）

- 参数口径：
  - `neurons_per_pe=100000`
  - `rows_per_core=5000`（20×5000=100000）
  - `cols=16×100000=1600000` ⇒ `bc=16` 时 `block_col_max=100000`，**需要 `idx_bytes=4`**

生成命令：

```bash
python3 "sst_dram_si/tools/gen_bcsr_global_mesh.py" \
  --num-pes 16 --neurons-per-pe 100000 \
  --cores-per-pe 20 --rows-per-core 5000 \
  --fanout 256 --local-ratio 0.85 \
  --br 1 --bc 16 --idx-bytes 4 --align 64 \
  --mode outgoing \
  --out-dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_100k_regen"
```

---

## 3. 校验（强烈建议生成后立刻做）

### 3.1 校验 meta 一致性（rows/cols/编码）

脚本：`"sst_dram_si/tools/verify_bcsr_meta_mesh.py"`

10k/PE：

```bash
python3 "sst_dram_si/tools/verify_bcsr_meta_mesh.py" \
  --dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_regen" \
  --rows-per-core 500 --cols 160000
```

100k/PE：

```bash
python3 "sst_dram_si/tools/verify_bcsr_meta_mesh.py" \
  --dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_100k_regen" \
  --rows-per-core 5000 --cols 1600000
```

### 3.2 校验 stride 与对齐（避免错位导致非确定性/读回 0）

`sst_dram_si/test_mesh_4x4.py` 会扫描权重目录下 **所有** `meta.json`，取 `file_size` 最大值作为 `GLOBAL_BCSR_CORE_FILE_SIZE`，并进一步做 `8192` 对齐得到 `PER_CORE_WEIGHT_STRIDE`：

- 目的：避免不同 core 的 `file_size` 不一致时，base_addr + stride 映射错位（曾导致 run 间非确定性/发放异常）。

因此生成时建议：

- `--align 64`（与现有工具默认一致）
- 不要手工拼接 file（保持脚本写出的 `file_size/offset` 自洽）

---

## 4. 在 mesh 模版中使用新权重目录

`sst_dram_si/test_mesh_4x4.py` 支持用环境变量覆盖权重根目录：

```bash
cd "sst_dram_si"
export MESH_BCSR_DIR="$(pwd)/weights/bcsr_global_16pe_fanout256_10k_regen"
export MESH_SIM_TIME="10us"
./tools/run_mesh_with_time.sh
```

输出目录示例：

- `"sst_dram_si/outputs_large/paper2/dram_mesh_4x4/YYYYMMDD-HHMMSS/essential_summary_mesh.json"`

快速验收建议：

- 10us：确认不 fatal，且 `memory.*`、`gas.windows`、`window_metrics` 非零（数量级合理）
- 100us：确认 `gas.windows`、NIC 包数、发放统计处于预期数量级（允许轻微漂移）

---

## 5. 常见坑（与“权重读回 0 / 非确定性”强相关）

1. **idx_bytes 设置错误（2/4）**
   - 10k/PE：可用 `idx_bytes=2`
   - 100k/PE：必须 `idx_bytes=4`（否则 block_col 溢出）
2. **stride 不覆盖最大 file_size**
   - 必须用所有 core 的最大 `file_size` 作为 stride 基准（mesh 模版已实现扫描）
3. **core 基址未按 8KiB 对齐**
   - GatherBufferIF 的某些聚合策略会 `alignDown` 地址到 `row_bytes_guess`（默认 8192）；若 base/stride 非 8KiB 对齐，可能出现“下溢到区间外”的地址（甚至导致 fatal）
4. **想做“快速小样”但仍走全量 outgoing 构图**
   - `gen_bcsr_global_mesh.py --mode outgoing` 需要遍历全局 pre 集合构图；仅想验证格式时建议改用 `--mode incoming` 或用 `"generate_bcsr.py"` 构造最小样例。

---

## 6. BlockCols（`bc`）调优：体积 vs 路由/Apply 负载

`bc` 决定 BCSR 每个 block 的列宽：`block_bytes = br * bc * (val_bytes + 4)`（这里 `val_bytes=4`，另 4B 为 `blockids`）。

- **`bc` 更大**：每个 block 更“宽”，对稀疏 fanout 会写入更多 0（体积更大），但 block 数可能更少（更利于缓存命中/更少 colidx 读）。
- **`bc` 更小**：每个 block 更“窄”，体积更小，但 block 数可能变多（更吃 row/colidx 与 block-cache），Apply 阶段可能出现长尾。

> 结论提示：`bc` 的最优点是 workload/缓存策略相关的，需要用 `essential_summary_mesh.json` 的 `apply_ns_p95` / `payload_bytes_*` / `memory.*` 做对照，而不是只看权重目录体积。

### 6.1 生成 `bc=8` / `bc=4`（10k/PE，fanout=256）

```bash
# bc=8
python3 "sst_dram_si/tools/gen_bcsr_global_mesh.py" \
  --num-pes 16 --neurons-per-pe 10000 \
  --cores-per-pe 20 --rows-per-core 500 \
  --fanout 256 --local-ratio 0.85 \
  --br 1 --bc 8 --idx-bytes 2 --align 64 \
  --mode outgoing \
  --out-dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_bc8"

# bc=4
python3 "sst_dram_si/tools/gen_bcsr_global_mesh.py" \
  --num-pes 16 --neurons-per-pe 10000 \
  --cores-per-pe 20 --rows-per-core 500 \
  --fanout 256 --local-ratio 0.85 \
  --br 1 --bc 4 --idx-bytes 2 --align 64 \
  --mode outgoing \
  --out-dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_bc4"
```

生成后立刻校验（推荐）：

```bash
python3 "sst_dram_si/tools/verify_bcsr_meta_mesh.py" \
  --dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_bc8" \
  --rows-per-core 500 --cols 160000

python3 "sst_dram_si/tools/verify_bcsr_meta_mesh.py" \
  --dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_bc4" \
  --rows-per-core 500 --cols 160000
```

### 6.2 A/B 对照建议口径（严格 GAS 语义）

1. 分别跑 100us：

```bash
cd "sst_dram_si"
export MESH_SIM_TIME="100us"

export MESH_BCSR_DIR="weights/bcsr_global_16pe_fanout256_10k_bc8"
./tools/run_mesh_with_time.sh

export MESH_BCSR_DIR="weights/bcsr_global_16pe_fanout256_10k_bc4"
./tools/run_mesh_with_time.sh
```

2. 对照 `essential_summary_mesh.json`：
   - `gas.apply_ns_{avg,p95}`（核心）
   - `window_metrics.payload_bytes_{avg,max}`、`bursts_avg`、`inflight_peak_max`
   - `memory.memory_requests` / `memory.memory_bytes`

3. 校验 Step 注入是否一致（避免把“路由构建错误”误判为性能差异）：
   - 在 `mesh_stats.csv` 中汇总 `step_activation_spikes_injected / route_hits / route_misses`
   - 理想情况下：不同 `bc` 下 **Step 注入统计应完全一致**（同 seed、同配置）。

> 备注：即便 Step 注入一致，`neurons_fired_total` 仍可能因为“窗口边界/时序”差异而产生一定漂移；评估性能请优先看 `apply_ns_*` 与 `payload/memory.*`。

---

## 7. 关键坑：Step reachability 的 offsets 不能当成“全局常量”

同一权重目录下，不同 core 的 `total_blocks` 可能不同，从而导致：

- `blockdata_offset`
- `blockids_offset`

会随 **每个 core 文件**变化（见 `coreXX.bcsr.bin.meta.json`）。

因此：

- **不要**用 `pe00/core00` 的 meta offset 当成所有 core 的固定 offset；
- Step reachability 构建（从文件解析 routes）必须使用 **每个文件自己的 meta offsets**，否则会出现：
  - `step_activation_*` 统计与 `neurons_fired_total` 随 run/布局（如 `bc`）大幅漂移；
  - 甚至出现“发放异常/归零”的假象。

---

（完）
