# GAS A+B（论文主线）落地：Apply 调度（A）+ Dense weights_phys 物理布局（B）

## 背景与目标

我们把论文的“主创新点”固定为 **A+B 的跨层协同**，并明确约束：

- 默认语义以 **cacheline**（例如 64B）为最小搬运/统计粒度（memHierarchy 语义一致）。
- **禁止**在线自适应/扫参式调参：所有机制必须是确定性的、可复现的、可解释的。
- A 与 B 都必须 **严格隔离**：默认关闭；启用时必须显式配置。

这里的 B 不是“DRAM 内部 row-buffer 激活=整行搬运”，而是 **把 dense 权重在物理地址空间中按 DRAM row_bytes 对齐打包**，避免 row‑stride 非对齐造成的跨行碎片/洞；A 则在 Apply 发射侧用 bank/row 结构把这些局部性兑现成 row‑hit/BLP 的收益。

---

## B) Dense `weights_phys`（PhysV1）设计

### 设计要点（不改语义，只改地址映射）

对一个 dense 权重矩阵 `rows x cols`（权重元素 4B，FP32）：

1. **Row stride cacheline 对齐**
   - `logical_row_bytes = cols * 4`
   - `row_stride_bytes = align_up(logical_row_bytes, line_bytes)`（默认 `line_bytes=64`）

2. **按 DRAM row_bytes 打包**
   - 给定 `dram_row_bytes`（例如 8192）
   - `rows_per_dram_row = max(1, dram_row_bytes / row_stride_bytes)`
   - 一个 “group” 对应一个物理 DRAM row 段（group stride 默认为 `dram_row_bytes`）

3. **PhysV1 地址映射（row, col → addr）**

令：
- `group = row / rows_per_dram_row`
- `within = row % rows_per_dram_row`

则物理地址为：

```
addr = base_addr
     + group  * group_stride_bytes
     + within * row_stride_bytes
     + col    * 4
```

其中 `group_stride_bytes` 在 `row_stride_bytes <= dram_row_bytes` 时等于 `dram_row_bytes`，否则为 `align_up(row_stride_bytes, dram_row_bytes)`（保证每行仍在独立 group 内）。

### 运行时开关（默认关闭）

在 Core 参数中启用：
- `dense_layout_mode=phys_v1`
- `dense_phys_dram_row_bytes=<与生成器一致，例如 8192>`

硬性要求（fail-fast）：
- `base_addr % dense_phys_dram_row_bytes == 0`

实现位置：
- `services/synapse/weights/DenseWeightLayout.h`
- `services/synapse/weights/WeightMemorySubsystem.{h,cc}`（dense 读寻址）
- `services/synapse/stdmem/SnnPESubComponent_mem.cc`（naive/legacy 的 direct read/write 也一致）
- `control/SnnPESubComponent.{h,cc}`、`control/SnnPESubComponentConfig.h`、`services/workload/snn/SnnWorkload.cc`（参数解析 + weight_region_end 计算）

---

## B) `weights_phys.bin` 生成工具

脚本：
- `tools/weights_phys/gen_dense_phys_v1.py`

输出：
- `weights_phys.bin`：**纯 raw bytes**（无 header），用于 `WeightLoader(raw)` 写入内存 `[base_addr, base_addr+file_size)`。
- `weights_phys.bin.meta.json`：sidecar 元信息（复现/调试用，运行时不读取）。

示例（使用 deterministic pattern，便于 byte-exact 验证）：

```bash
python3 "sst_workspace/sst-elements/src/sst/elements/SnnDL/tools/weights_phys/gen_dense_phys_v1.py" \
  --rows 500 --cols 500 \
  --line-bytes 64 --dram-row-bytes 8192 \
  --pattern dense_rowcol_v1 --row-scale 1024 \
  --out "/tmp/weights_phys.bin"
```

将 `/tmp/weights_phys.bin` 配置给 `WeightLoader` 的 raw 模式载入（具体在 `sst_dram_si` 的装配脚本中设置 `weight_format=raw` + `single_file/per_core_files`；此文档不强制修改顶层脚本，避免污染工作区）。

---

## A) Apply 阶段 DRAM-aware（确定性）调度（现状：直接用已有 policy）

我们先把 A 固化为 **不改合并策略、只改 Apply 发射顺序/节流** 的确定性调度器：

启用方式：
- `GatherBufferIF.apply_issue_policy=bank_rr_row_sticky_age`

关键配置建议（不属于调参；是“架构/地址映射契约”的固定常量）：
- `row_bytes_guess = dense_phys_dram_row_bytes`（PhysV1 下建议相同）
- `bank_shift = log2(row_bytes_guess)`（使 bankIndex 从“物理 DRAM row 序号”的低位取模）
- `bank_bits = log2(dram_bank_count)`（由目标后端的 bank 数决定；实验中把它当成架构参数）
- `sort_policy = bank_row`（使 issue_order 与 bankRowIndex 对齐）

说明：
- A 的收益预期来自：`bank` 轮转 + `row` sticky → 更高 BLP / 更少 bank 内 row 切换 → Apply tail 降低。
- A 不依赖在线反馈/自适应；公平性由 `apply_age_fair_ns` 提供确定性上界。

---

## 隔离与 DoD（最小验收）

隔离（默认不影响现有行为）：
- 默认 `dense_layout_mode=row_major`：所有寻址与旧版一致。
- 只有显式开启 `phys_v1` 时，dense 地址映射与 `weight_region_end` 才按 PhysV1 计算。
- A 的调度器默认 `apply_issue_policy=order`；只在脚本显式开启时生效。

最小验收（建议用 dense microbench）：
1. `phys_v1` 启用后，byte-exact 校验（dense_rowcol_v1）能 PASS 或至少 WARN+INCONCLUSIVE（不允许 silent mismatch）。
2. memHierarchy 统计口径下（GetS/bytes）与期望同量级，且不出现大段 overfetch（除非显式启用 gap-merge）。

---

## 快速复现：dense microbench 4x4（baseline vs PhysV1）

说明：
- 该用例的 `cols=1024`，`logical_row_bytes=4096`，天然能按 `dram_row_bytes=8192` 打包（2 rows per DRAM row），因此 **baseline(row_major) 与 PhysV1 的地址布局等价**；
  该对比主要用于验证 PhysV1 链路正确性（byte-exact PASS + 统计/validator PASS），而不是展示收益上限。

生成 PhysV1 raw blob：

```bash
cd "sst_dram_si"
EXP_BASE="outputs_large/paper2/dense_microbench_4x4_physv1_compare"
mkdir -p "$EXP_BASE"
python3 "../sst_workspace/sst-elements/src/sst/elements/SnnDL/tools/weights_phys/gen_dense_phys_v1.py" \
  --rows 64 --cols 1024 \
  --line-bytes 64 --dram-row-bytes 8192 \
  --pattern dense_rowcol_v1 --row-scale 1024 \
  --out "$EXP_BASE/weights_phys_64x1024.bin"
```

运行 baseline（关闭 WeightLoader readback，避免将 init 校验流量混入 memctrl 口径）：

```bash
TS=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$EXP_BASE/baseline/$TS"
mkdir -p "$RUN_DIR"
MESH_RUN_DIR="$RUN_DIR" MESH_MAX_STEPS=1 MESH_SST_N=32 MESH_LOADER_VERIFY_READBACK=0 \
  "../sst_install_mpi/bin/sst" -n 32 "microbench_dense_4x4/test_dense_microbench.py" \
  >"$RUN_DIR/mesh.log" 2>&1
python3 "tools/compute_essential_summary_mesh.py" --run-dir "$RUN_DIR"
python3 "tools/validate_essential_summary_mesh.py" --run-dir "$RUN_DIR"
```

运行 PhysV1（通过 `MESH_OVERRIDES_JSON` 注入 Core/WeightLoader 参数）：

```bash
WEIGHTS_FILE="$(realpath "$EXP_BASE/weights_phys_64x1024.bin")"
OVERRIDES_JSON="$(WEIGHTS_FILE="$WEIGHTS_FILE" python3 - <<'PY'
import json, os
weights = os.environ["WEIGHTS_FILE"]
rules = [
  {"match": {"role": "pe.core", "type": "SnnDL.SnnPESubComponent"},
   "params": {"dense_layout_mode": "phys_v1", "dense_phys_dram_row_bytes": 8192},
   "strict": True},
  {"match": {"role": "weight_loader", "type": "SnnDL.WeightLoader"},
   "params": {"weight_format": "raw", "single_file": weights},
   "strict": True},
]
print(json.dumps(rules))
PY
)"
TS=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$EXP_BASE/phys_v1/$TS"
mkdir -p "$RUN_DIR"
MESH_RUN_DIR="$RUN_DIR" MESH_MAX_STEPS=1 MESH_SST_N=32 MESH_LOADER_VERIFY_READBACK=0 MESH_OVERRIDES_JSON="$OVERRIDES_JSON" \
  "../sst_install_mpi/bin/sst" -n 32 "microbench_dense_4x4/test_dense_microbench.py" \
  >"$RUN_DIR/mesh.log" 2>&1
python3 "tools/compute_essential_summary_mesh.py" --run-dir "$RUN_DIR"
python3 "tools/validate_essential_summary_mesh.py" --run-dir "$RUN_DIR"
```

下一步（用于展示收益的“非对齐 row”用例）：
- dense microbench 1PE（例如 500x500，`logical_row_bytes=2000`）需要把 `per_core_weight_stride` 与 PhysV1 的 `total_bytes=groups*dram_row_bytes`
  对齐（PhysV1 下 `total_bytes` 可能大于 `align_up(rows*cols*4, dram_row_bytes)`），否则 WeightLoader(raw) 会因为 stride 不足而 fail-fast。

---

## 2026-02-14 更新：dense microbench 1PE（500×500）矩阵结果（A/B × backend）

本节用于把 A（Apply 发射策略）与 B（PhysV1 物理布局）在 **cacheline 默认语义** 下的“可复现对比”固化下来，便于后续论文写作与复现实验。

### 固定实验口径（所有 cells 一致）

- `max_steps=4`（GlobalGasStepController）
- `seed=314159`（step random activation）
- `L1=0`
- `loader_verify_readback=0`（避免 init/readback 流量污染 steady-state 口径）
- 严格 cacheline：`merge_policy=cacheline`、`gap_k_bytes=0`、`row_window_bytes=0`、`row_window_timeout_ns=0`

### 运行目录（每格取最新 validator PASS）

| backend | layout | apply_issue_policy | run_dir | model.sim_time_actual_ns | memhierarchy.memctrl.bytes_est_total | ramulator2.row_hit_rate_total | ramulator2.avg_read_latency_0_avg |
|---|---|---|---|---:|---:|---:|---:|
| simple | row_major | order | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/simple/row_major_order/20260214-200916` | 7732 | 323136 |  |  |
| simple | row_major | bank_rr_row_sticky_age | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/simple/row_major_bank_rr_row_sticky_age/20260214-200918` | 7732 | 323136 |  |  |
| simple | phys_v1 | order | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/simple/phys_v1_order/20260214-200655` | 5490 | 190208 |  |  |
| simple | phys_v1 | bank_rr_row_sticky_age | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/simple/phys_v1_bank_rr_row_sticky_age/20260214-201051` | 5490 | 190208 |  |  |
| ram2_ddr5 | row_major | order | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/ram2_ddr5/row_major_order/20260214-201052` | 123669 | 323136 | 0.761933 | 33.9027 |
| ram2_ddr5 | row_major | bank_rr_row_sticky_age | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/ram2_ddr5/row_major_bank_rr_row_sticky_age/20260214-201054` | 123669 | 323136 | 0.761933 | 33.9027 |
| ram2_ddr5 | phys_v1 | order | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/ram2_ddr5/phys_v1_order/20260214-201056` | 71209 | 190208 | 0.775908 | 34.34 |
| ram2_ddr5 | phys_v1 | bank_rr_row_sticky_age | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/ram2_ddr5/phys_v1_bank_rr_row_sticky_age/20260214-201058` | 71209 | 190208 | 0.775908 | 34.34 |
| ram2_hbm2 | row_major | order | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/ram2_hbm2/row_major_order/20260214-201059` | 99950 | 323136 | 0.194296 | 32.5478 |
| ram2_hbm2 | row_major | bank_rr_row_sticky_age | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/ram2_hbm2/row_major_bank_rr_row_sticky_age/20260214-201101` | 99950 | 323136 | 0.194296 | 32.5478 |
| ram2_hbm2 | phys_v1 | order | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/ram2_hbm2/phys_v1_order/20260214-201102` | 62401 | 190208 | 0.157133 | 32.8286 |
| ram2_hbm2 | phys_v1 | bank_rr_row_sticky_age | `sst_dram_si/outputs_large/paper2/dense_microbench_1pe_physv1_backend_apply_compare/ram2_hbm2/phys_v1_bank_rr_row_sticky_age/20260214-201104` | 62401 | 190208 | 0.157133 | 32.8286 |

### 观察（当前用例下的结论）

- **B（PhysV1）在 `logical_row_bytes=2000` 非 cacheline 对齐的场景能显著降低 cacheline 口径流量**：
  - `memctrl.bytes_est_total`：`323136B -> 190208B`（约 `-41.1%`），并带来明显的 `sim_time_actual_ns` 降低（simple / DDR5 / HBM2 均成立）。
- **A（apply_issue_policy）在该 1PE 用例上未体现差异**：
  - 这是预期的：1PE 缺乏 bank-level 并行竞争；且当前 dense microbench 的默认 bank 参数并不会让 policy 产生不同的发射序列。
  - A 的评估应转到多 PE / 明确 bank_bits/bank_shift 的压力场景（例如 4x4 + 更高 step 负载）再下结论。

### byte-exact（dense_rowcol_v1）在 PhysV1 下的必要补齐点

- WMS（`WeightMemorySubsystem::verifyDenseReadBytes_`）必须按 `dense_layout_mode` 做 layout-aware 解码：
  - `phys_v1` 下允许 `row_stride_bytes` padding 与最后一组 group padding 的期望值为 0。
- GatherBufferIF 的 byte-exact 同样需要显式 layout：
  - `byte_exact_dense_layout_mode=phys_v1`
  - `byte_exact_dense_phys_dram_row_bytes=<与生成器一致，例如 8192>`
  - dense microbench 入口（`sst_dram_si/microbench_dense/entry.py`）在 `dense_layout_mode=phys_v1` 时会自动注入该 override；其它装配入口若需要启用 gatherbuf 的 dense byte-exact，请显式注入上述参数。

---

## 2026-02-17 更新：BCSR A/B 严格隔离矩阵（4x4, GAS, step=1）

### 目的

把 BCSR 路径中的 A/B 改动做成可复现、可审计的四格隔离实验：

- baseline：`flat + full_block`
- A：`flat + row_cacheline`
- B：`rowpack_v1 + full_block`
- AB：`rowpack_v1 + row_cacheline`

### 统一口径

- `MESH_EXEC_MODE=gas`
- `MESH_MAX_STEPS=1`
- `MESH_STEP_ACTIVATION_FRACTION=0.01`
- `MESH_STEP_ACTIVATION_SEED=314159`
- `MESH_L1_ENABLE=0`
- `MESH_SST_NPROC=32`
- 其余配置保持一致（同一 `local_run_config.json` 哈希）

### 运行脚本（新增）

```bash
cd "sst_dram_si"
./tools/run_mesh_bcsr_ab_isolation_matrix.sh
```

脚本会写入：
- `outputs_large/paper2/dram_mesh_4x4_ab_isolation_baseline/*`
- `outputs_large/paper2/dram_mesh_4x4_ab_isolation_A_row_cacheline/*`
- `outputs_large/paper2/dram_mesh_4x4_ab_isolation_B_rowpack_v2/*`
- `outputs_large/paper2/dram_mesh_4x4_ab_isolation_AB_rowpack_rowcacheline/*`

并在 stdout 打印最新四组汇总。

### 结果（最新一轮）

| variant | run_dir | memory.memory_bytes | memctrl.bytes_est_total | gas.apply_ns_avg | model.sim_time_actual_ns | spikes_injected_total |
|---|---|---:|---:|---:|---:|---:|
| baseline | `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_ab_isolation_baseline/20260217-022746` | 86492246 | 91542976 | 87919.3125 | 540471 | 402176 |
| A | `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_ab_isolation_A_row_cacheline/20260217-023114` | 86492246 | 91542976 | 87919.3125 | 540471 | 402176 |
| B | `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_ab_isolation_B_rowpack_v2/20260217-023451` | 9144058 | 25998464 | 24832.0625 | 82414 | 402176 |
| AB | `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_ab_isolation_AB_rowpack_rowcacheline/20260217-023604` | 9144058 | 25998464 | 24832.0625 | 82414 | 402176 |

### 结论（这一组口径下）

- `A == baseline`：该数据集 `br=1`，`full_block` 与 `row_cacheline` 等价，A 单独不产生可见差异。
- `B == AB`：主收益来自 B（rowpack 布局）；A 在该数据集上不叠加额外收益。
- 相对 baseline，B/AB：
  - `memory_bytes` 下降约 `89.43%`
  - `memctrl.bytes_est_total` 下降约 `71.60%`
  - `apply_ns_avg` 下降约 `71.76%`
  - `sim_time_actual_ns` 下降约 `84.75%`

### 审计性增强（本次补丁）

- `meta.json.environment` 新增：
  - `MESH_BCSR_BLOCK_FETCH_MODE`
  - `MESH_BCSR_LAYOUT_MODE`

因此四组 run 的关键隔离开关可以直接从 `meta.json` 读取，不再依赖外部命令历史推断。

---

## 2026-02-17 更新：`br=2` 复现实验（验证 A 在 `br>1` 下的独立收益）

### 生成数据集

```bash
python3 "sst_dram_si/tools/gen_bcsr_global_mesh.py" \
  --num-pes 16 --neurons-per-pe 10000 --cores-per-pe 20 --rows-per-core 500 \
  --fanout 256 --local-ratio 0.85 --br 2 --bc 16 --idx-bytes 4 --val-bytes 4 \
  --weights-cols 160000 --weight-value 1.0 --seed 271828 --mode outgoing \
  --layout flat \
  --out-dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2"

python3 "sst_dram_si/tools/gen_bcsr_global_mesh.py" \
  --num-pes 16 --neurons-per-pe 10000 --cores-per-pe 20 --rows-per-core 500 \
  --fanout 256 --local-ratio 0.85 --br 2 --bc 16 --idx-bytes 4 --val-bytes 4 \
  --weights-cols 160000 --weight-value 1.0 --seed 271828 --mode outgoing \
  --layout rowpack_v1 \
  --out-dir "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2_rowpack_v1"
```

### 运行矩阵

```bash
cd "sst_dram_si"
MESH_BCSR_DIR_FLAT="/home/xgy/remote/sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2" \
MESH_BCSR_DIR_ROWPACK="/home/xgy/remote/sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2_rowpack_v1" \
MESH_SWEEP_REPEATS=1 MESH_MAX_STEPS=1 MESH_STEP_ACTIVATION_FRACTION=0.01 \
MESH_STEP_ACTIVATION_SEED=314159 MESH_L1_ENABLE=0 MESH_SST_NPROC=32 \
./tools/run_mesh_bcsr_ab_isolation_matrix.sh
```

### 结果（最新一轮）

| variant | run_dir | memory.memory_bytes | memctrl.bytes_est_total | model.sim_time_actual_ns |
|---|---|---:|---:|---:|
| baseline | `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_ab_isolation_baseline/20260217-112206` | 288510384 | 139518016 | 584890 |
| A | `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_ab_isolation_A_row_cacheline/20260217-112550` | 279640796 | 139581824 | 582397 |
| B | `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_ab_isolation_B_rowpack_v2/20260217-112941` | 23886972 | 28848576 | 68159 |
| AB | `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_ab_isolation_AB_rowpack_rowcacheline/20260217-113110` | 23426876 | 28425536 | 67853 |

### 结论

- 与 `br=1` 不同，`br=2` 下 **A 不再是 0 收益**：
  - 相对 baseline：`memory_bytes -3.07%`，`sim_time -0.43%`。
- AB 相对 B 继续有小幅下降：
  - `memory_bytes -1.93%`，`memctrl -1.47%`，`sim_time -0.45%`。
