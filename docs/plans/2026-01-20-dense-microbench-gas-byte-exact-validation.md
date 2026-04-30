# Dense Microbench GAS Byte-Exact 验证方案（全特性：细/粗合并 + 全局 Step）

> 目标读者：主人/后续开发者。本文是“实验指导 + 必要最小补丁清单”，用于把 GAS 全链路正确性收敛到**字节级可证**。

## 0) 目标与范围

### 0.1 目标（DoD）

在 microbench（先 1PE/1core dense）中：

- 开启全局 step（GlobalGasStepController 同步 START_STEP/PE_DONE）。
- 开启 GAS 合并全特性：
  - **细粒度合并**：gap-merge（k/Lmax 生效）
  - **粗粒度合并**：row-window（bytes/timeout 生效）
- 做到“字节级正确”：
  1) 任意一次权重读 `ReadResp(addr,size,data)`：`data` 每个字节 == 该地址在 DRAM 的期望字节；
  2) 每条 edge 的 `weight`（与 `dv=weight*count`）与期望一致；
  3) step 语义严格闭环：`windows_done == max_steps`，`windows_incomplete==0`，且 `synapse_ops_step_total == spike_attempts_total`（没有“没读完就结束”的假象）。

### 0.2 非目标（本阶段不做）

- 不启用/不验证 GatherBufferIF 的自适应控制（`k_adapt_enable/ctrl_enable/bank_auto_enable` 等）。
- 不做性能优化与对比结论，只做 correctness（性能后续单独做）。

### 0.3 适用范围与优先级

1) P0：dense microbench 1PE（最小系统、最快收敛）
2) P1：dense microbench 4x4（并行/多核噪声）
3) P2：BCSR10k（真实 workload；可复用同一套“字节级断言”框架，但数据模型更复杂）

---

## 1) 背景：为什么必须“字节级”？

仅看 `memory_bytes` / `memHierarchy.GetS` 只能证明“读了多少”，不能证明“读对了”。在 GAS 合并路径里，常见致命错误是：

- 段合并/吸洞导致 `addr/size` 变化，但 offset 计算错误（子请求切片错位）；
- 跨 cacheline/跨 row 合并时，端点对齐错误（多读/漏读/错读）；
- ReadResp 到达顺序抖动导致累加顺序改变（已通过 retire 顺序收敛，但仍要验证 weight 值本身正确）。

因此：必须把 DRAM 中的权重初始化成“可反推/可字节对比”的模式，并在读回路径做断言式校验。

---

## 2) 数据模型：dense 权重布局与可逆模式

### 2.1 dense layout（以 1PE/1core 为例）

- 每个权重：FP32（4B）
- rows = `neurons_per_core`（默认 500）
- cols = `global_weights_cols = total_nodes * neurons_per_pe`
  - 1PE：cols=500 ⇒ **row_stride_bytes = 500 * 4 = 2000B**
- 地址公式：

```
addr = base_addr + (row * cols + col) * 4
```

代码位置：
- `sst_dram_si/microbench_dense/entry.py`（dense_bytes/stride）
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`（prepareDenseRead_）

### 2.2 权重可逆写入模式（用于 byte-exact）

主人已确认使用模式：

```
w(row,col) = float(row * 1024 + col)
```

理由（关键点）：
- 值域在 2^24 内时 float 可精确表示，`float -> bytes` 是确定的；
- 任意 `addr` 的 `row/col` 可由 `(addr-base)/4` 反推，便于在 ReadResp 处逐字节对比。

---

## 3) 必要最小补丁（为 correctness 服务；默认关闭）

> 下面 3 组改动只在 microbench 打开（避免污染性能回归/论文口径）。默认应保持关闭。

### 3.1 WeightLoader：按模式写入 + 写后读回抽样

目标：证明“落盘/写入阶段”本身就正确（否则后续全错）。

文件（实现建议）：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/WeightLoader.cc`

建议新增参数：
- `write_pattern_mode`：`"const"`（默认）/ `"dense_rowcol_v1"`
- `verify_readback_enable`：已有（但当前主要用于 raw+BCSR；dense 需补齐）
- `verify_readback_bytes`：已有（建议 64）
- `verify_readback_samples`：新增（如 16；固定 seed）

抽样地址覆盖（至少）：
- row0 col0（base 对齐）
- row0 col496（行尾短读边界）
- row1 col0（跨 row stride）
- 若干固定伪随机点（row/col 均匀）

验证方式：
- 对每个样本地址发 untimed Read；
- 将读回 bytes 与期望 bytes（按模式生成）做 `memcmp`；
- mismatch → `fatal`（microbench correctness 模式下）。

### 3.2 WeightMemorySubsystem：ReadResp 字节级校验（dense）

目标：证明“GAS 合并/拆分/回调”链路对每个字节都正确。

文件：
- microbench 实际落点（更贴近“ReadResp 落 SRAM 处”）：  
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`
    - `onDownstreamResp_()`：对每个下游 ReadResp 分片做字节级校验（在写入 SRAM 前）
    - `finishByteExact_()`：在 EndScatter 边界输出 PASS marker（或 mismatch fatal）

> 备注：WeightMemorySubsystem 的 byte-exact 校验框架也可保留/复用，但 dense microbench 的实际读路径主要由 GatherBufferIF 承担，因此本阶段以 GatherBufferIF 为主口径。

建议新增 orchestrator 参数：
- `byte_exact_verify_enable`：0/1（默认 0）
- `byte_exact_verify_mode`：`"dense_rowcol_v1"`
- `byte_exact_verify_max_mismatch`：如 8（只打印前 N 个 mismatch，最后 fatal）

校验逻辑（只对 dense，`meta.bcsr_kind==0`）：
- 计算 `offset = addr - base_addr`；
- 对 `data` 以 4B 为步长解析 `float`，反推 `(row,col)` 并生成期望 bytes；
- 逐字节比对；统计 mismatch；超阈值打印后 `fatal`。

### 3.3 WMS retire：按 edge 语义校验（weight 与 dv）

目标：证明 “edge 合并(count) + retire 顺序”语义正确（不仅是 bytes）。

文件：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
  - `tryRetireEdges_()` 内部

> 备注：dense microbench 主要验证 GAS/mem 合并正确性；edge retire 校验更适合在“完整 SNN/route/Spike 语义链路”里做（例如 BCSR10k 或最小 SNN case）。本阶段先保证 ReadResp/SRAM 字节级正确闭环。
校验点：
- 每条 `EdgeRetireEntry` ready 时，按 (post, pre_global) 反推 (row,col) 生成期望 weight；
- 校验 `weight == expected_weight`（float 精确值）；
- 校验 `dv == weight * count`（若使用 float，允许极小误差，但该模式下应可精确）。

---

## 4) 实验配置：开启 GAS 全特性（但保持 cacheline 默认语义）

### 4.1 统一开关（所有 case 都一致）

建议以 dense 1PE 为起点：
- 配置文件：`sst_dram_si/microbench_dense_1pe/local_run_config.json`
- 运行脚本：`\"sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh\" gas`

关键要求：
- 禁止 `use_event_weight_fallback`
- `disable_network=true`
- `l1_enable=false`
- `MESH_MAX_STEPS=1`
- 全局 step 同步必须开启（dense microbench 入口已默认开启）
- 为避免“预算截断造成假阳性”：
  - `window_read_budget = 0`（0=禁用预算）
  - `max_outstanding_requests` 足够大（建议 >= 4096）
  - `gas_max_inflight` 足够大（如 128/256）

### 4.2 GAS 合并参数（本方案要验证的重点）

启用全部合并特性：
- 细合并：
  - `gas_gap_k_bytes > 0`
  - `gas_lmax_bytes > 0`
- 粗合并：
  - `gas_row_window_bytes > 0`
  - `gas_row_window_timeout_ns > 0`（建议先用 40ns）

注意：dense 的 `row_stride_bytes` 会与 `k` 强耦合；本计划会用矩阵覆盖“安全 k”与“跨 row 的压力 k”两种配置，但两者都必须 byte-exact。

---

## 5) 实验矩阵（先 correctness，再压力）

统一环境变量（建议）：

```bash
export "MESH_EXEC_MODE"="gas"
export "MESH_MAX_STEPS"="1"
export "MESH_STEP_ACTIVATION_SEED"="314159"
export "MESH_STEP_ACTIVATION_FRACTION"="0.01"
export "MESH_STEP_ACTIVATION_FANOUT"="256"
```

> 说明：fraction/fanout 仅用于确保产生足够多的 edge；correctness 以 byte-exact 为准。

### Case 0：无合并（校验链路是否通）

- `gas_gap_k_bytes=0`
- `gas_row_window_bytes=0`
- `gas_row_window_timeout_ns=0`
- `gas_merge_policy="cacheline"`

### Case 1：细合并（不跨 row stride 的“主口径”）

> 1PE dense 时 row_stride_bytes=2000B，建议选 `k < 2000B`。

- `gas_gap_k_bytes` ∈ {64, 128, 256}
- `gas_lmax_bytes` ∈ {4096, 65536}

### Case 2：粗合并（row-window）

- `gas_row_window_bytes` ∈ {256, 1024, 4096}
- `gas_row_window_timeout_ns` ∈ {40, 200}

### Case 3：细+粗全开（你要的“全特性组合”）

推荐起步：
- `gas_gap_k_bytes=128`
- `gas_lmax_bytes=65536`
- `gas_row_window_bytes=1024`
- `gas_row_window_timeout_ns=40`

### Case 4：压力口径（允许跨 row stride 的合并，但仍必须 byte-exact）

目的：验证“即便 over-fetch，子请求切片/回调/累加仍完全正确”。

- `gas_gap_k_bytes=2048`（略大于 2000B）
- row-window 同 Case 3

---

## 6) 运行步骤与验收（每个 case）

### 6.1 运行

```bash
bash \"sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh\" \"gas\"
```

输出目录：
- `\"sst_dram_si/outputs_large/paper2/dense_microbench_1pe_exec_mode_compare/gas/<ts>/\"`

### 6.2 必过验收（否则该 case 失败）

从 `essential_summary_mesh.json` 检查：
- `gas.windows_done == 1`
- `gas.windows_incomplete == 0`
- `gas.synapse_ops_step_total == step_activation.spike_attempts_total`
- `byte_exact_verify`: mismatch==0（若实现为 fatal，则 run 直接失败）

### 6.3 失败时的最短排障路径

1) 若出现“总访存固定很小（例如 512B≈8条线）”：
   - 优先判定：注入/recordEdge 是否生效；或是否被 `window_read_budget/max_outstanding_requests` 截断。
2) 若 byte mismatch：
   - 先看 WeightLoader 的 readback 抽样是否通过（写错 vs 读错分离）。
   - 再看 WMS `handleReadResp_()` mismatch 打印的 (addr, idx, row, col) 定位 offset 错误。

---

## 7) 关键代码索引（便于主人 review）

- dense microbench 入口与参数透传：
  - `sst_dram_si/microbench_dense/entry.py`
  - `sst_dram_si/mesh_template/build.py`
- GAS 前端与合并实现：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`
- dense 权重读粒度决策：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
    - `prepareDenseRead_()`
    - `handleReadResp_()`
- edge retire（确定性累加/校验插入点）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
    - `tryRetireEdges_()`
- WeightLoader 写入与验证：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/WeightLoader.cc`

---

## 8) 为什么这个方案“最干净、最安全”（原则说明）

- KISS：用一个可逆的写入模式把“正确性”变成可断言的数学事实；不引入外部依赖。
- DRY：同一套 `(row,col)->bytes` 生成器同时用于 WeightLoader 写入与 WMS 读回校验，避免两套口径漂移。
- YAGNI：本阶段不引入自适应控制/性能调参；只验证 correctness。
- SOLID：校验逻辑通过参数开关注入，默认关闭，不污染主链路/性能回归。

---

## 9) 落地状态（2026-01-20 实现进度）

### 9.1 关键实现点（与原计划的差异/补强）

- **row-window enable 修正**：`sst_dram_si/mesh_template/build.py` 中 `row_window_enable` 现在由 `(row_window_bytes>0 || row_window_timeout_ns>0)` 决定，避免“只配 timeout 不生效”。
- **Apply 触发读也能走 merge/staging**：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc` 允许在 Apply 阶段也把 Read 收集进 staging，并在 Apply 的 `clockTick()` 中及时 build+issue，避免“BeginApply 才发起读 ⇒ 永远绕开 row-window/gap-merge”。
- **microbench 支持 env 覆盖**：`sst_dram_si/microbench_dense/entry.py` 支持 `MESH_GAS_*` 覆盖；`sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh` 将覆盖写入 `meta.json` 便于复现。
- **validator 允许非 strict 的大粒度 granule**：`sst_dram_si/tools/validate_essential_summary_mesh.py` 在 `dense_strict_cacheline_override=0` 时，不再以 `avg_granule_bytes <= 2*line` 作为 FAIL（因为这是刻意的 over-fetch 压力口径）。

### 9.2 复现方式（Case 0~4）

> 统一：`MESH_STEP_ACTIVATION_SEED=314159`、`MESH_MAX_STEPS=1`（脚本默认）、并在需要“非 strict”时设置 `MESH_DENSE_STRICT_CACHELINE=0`。

- Case0（无合并，strict cacheline 默认）：直接跑
  - `bash "sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh" gas`
- Case1（细合并：gap-merge）
  - `MESH_DENSE_STRICT_CACHELINE=0 MESH_GAS_GAP_K_BYTES=128 MESH_GAS_ROW_WINDOW_BYTES=0 MESH_GAS_ROW_WINDOW_TIMEOUT_NS=0 bash "sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh" gas`
- Case2（粗合并：row-window）
  - `MESH_DENSE_STRICT_CACHELINE=0 MESH_GAS_GAP_K_BYTES=0 MESH_GAS_ROW_WINDOW_BYTES=1024 MESH_GAS_ROW_WINDOW_TIMEOUT_NS=40 bash "sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh" gas`
- Case3（细+粗全开）
  - `MESH_DENSE_STRICT_CACHELINE=0 MESH_GAS_GAP_K_BYTES=128 MESH_GAS_ROW_WINDOW_BYTES=1024 MESH_GAS_ROW_WINDOW_TIMEOUT_NS=40 bash "sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh" gas`
- Case4（压力：允许跨 row stride 的 gap）
  - `MESH_DENSE_STRICT_CACHELINE=0 MESH_GAS_GAP_K_BYTES=2048 MESH_GAS_ROW_WINDOW_BYTES=1024 MESH_GAS_ROW_WINDOW_TIMEOUT_NS=40 bash "sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh" gas`

### 9.3 已跑通的结果（全部 byte-exact PASS）

以下 run 目录均包含：
- `WEIGHT_LOADER_READBACK: PASS`
- `BYTE_EXACT_VERIFY: PASS`
- validator `fail=0`

- Case0：`sst_dram_si/outputs_large/paper2/dense_microbench_1pe_exec_mode_compare/gas/20260120-114939-501597285/`
- Case1：`sst_dram_si/outputs_large/paper2/dense_microbench_1pe_exec_mode_compare/gas/20260120-120928-106764820/`
- Case2：`sst_dram_si/outputs_large/paper2/dense_microbench_1pe_exec_mode_compare/gas/20260120-120357-356496438/`
- Case3：`sst_dram_si/outputs_large/paper2/dense_microbench_1pe_exec_mode_compare/gas/20260120-120937-967012718/`
- Case4：`sst_dram_si/outputs_large/paper2/dense_microbench_1pe_exec_mode_compare/gas/20260120-120954-061517078/`

### 9.4 P1（4x4）验证（byte-exact 允许“部分节点无本地读”→SKIP，不再整体 fatal）

- 4x4 strict cacheline（Case0）：
  - `sst_dram_si/outputs_large/paper2/dense_microbench_4x4_exec_mode_compare/gas/20260120-121745-353499505/`
- 4x4 row-window（Case2，`MESH_DENSE_STRICT_CACHELINE=0`）：
  - `sst_dram_si/outputs_large/paper2/dense_microbench_4x4_exec_mode_compare/gas/20260120-121824-366860999/`
- 4x4 gap-merge（Case1，`MESH_DENSE_STRICT_CACHELINE=0`，`MESH_GAS_GAP_K_BYTES=128`）：
  - `sst_dram_si/outputs_large/paper2/dense_microbench_4x4_exec_mode_compare/gas/20260120-122405-354890854/`
- 4x4 gap+row-window（Case3，`MESH_DENSE_STRICT_CACHELINE=0`，`MESH_GAS_GAP_K_BYTES=128`，row-window=1024B/40ns）：
  - `sst_dram_si/outputs_large/paper2/dense_microbench_4x4_exec_mode_compare/gas/20260120-122416-857048199/`
- 4x4 压力口径（Case4，`MESH_DENSE_STRICT_CACHELINE=0`，`MESH_GAS_GAP_K_BYTES=2048`，row-window=1024B/40ns）：
  - `sst_dram_si/outputs_large/paper2/dense_microbench_4x4_exec_mode_compare/gas/20260120-122429-034819667/`
