# DRAM‑SI 4×4 Mesh（10k/PE）技术使用手册

本手册说明当前 10k/PE 规模的 4×4 mesh 配置、权重生成与加载方式、严格 GAS 路径、统计项与常见问题排查。适用于快速回归与对比评估（10us 快测与 100us 长跑）。

## 一、规模与目录
- Mesh 拓扑：4×4，共 16 个 PE（节点 0..15）。
- 每 PE：20 个核心（core00..core19），每核心 500 个神经元（合计 10,000/PE）。
- 全局 ID：列宽 cols=16×10,000=160,000。
- 权重目录（10k）：`sst_dram_si/weights/bcsr_global_16pe_fanout256_10k/`
  - 结构：`pe{pe:02d}/core{core:02d}.bcsr.bin[.meta.json]`
  - 关键 meta 字段（示例 pe00/core00.bcsr.bin.meta.json）：
    - rows=500, cols=160000, br=1, bc=16, idx_bytes=2, val_bytes=4
    - rowptr_offset, colidx_offset, blockdata_offset, blockids_offset（字节对齐）
    - fanout=256, local_ratio=0.85

## 二、权重生成与校验
- 生成（已执行一次；如需重建）：
  ```bash
  python3 sst_dram_si/tools/gen_bcsr_global_mesh.py \
    --num-pes 16 --neurons-per-pe 10000 \
    --cores-per-pe 20 --rows-per-core 500 \
    --fanout 256 --local-ratio 0.85 \
    --br 1 --bc 16 --idx-bytes 2 \
    --out-dir sst_dram_si/weights/bcsr_global_16pe_fanout256_10k
  ```
- 校验（确保 rows/cols 与 meta 一致）：
  ```bash
  python3 sst_dram_si/tools/verify_bcsr_meta_mesh.py \
    --dir sst_dram_si/weights/bcsr_global_16pe_fanout256_10k \
    --rows-per-core 500 --cols 160000
  ```

## 三、运行脚本与参数
- 模型脚本：`sst_dram_si/test_mesh_4x4.py`
- 汇总脚本：`sst_dram_si/tools/compute_essential_summary_mesh.py`
- 一键运行：`sst_dram_si/tools/run_mesh_with_time.sh`
- 重要环境变量：
  - `MESH_BCSR_DIR`（可选）：覆盖 BCSR 权重根目录，指向 10k 路径；未设置时脚本自动优先检测 10k 目录。
  - `MESH_SIM_TIME`（可选）：覆盖仿真时长，如 `10us` 进行快测。

### 快速 10us 验证（推荐）
```bash
cd sst_dram_si
MESH_BCSR_DIR="$(pwd)/weights/bcsr_global_16pe_fanout256_10k" \
MESH_SIM_TIME=10us tools/run_mesh_with_time.sh
```
输出：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/<timestamp>/`
- `mesh_run.log`：运行日志（含“检测到全局BCSR数据 ..._10k”提示）
- `mesh_stats.csv`：全局统计
- `peXX/`：分 PE 的阶段事件与窗口指标 CSV（若启用）
- `essential_summary_mesh.json`：汇总摘要（见第六节）

### 100us 长跑
```bash
cd sst_dram_si
MESH_BCSR_DIR="$(pwd)/weights/bcsr_global_16pe_fanout256_10k" \
tools/run_mesh_with_time.sh
```

## 四、严格 GAS 语义（核心开关）
- 严格 GAS：按窗口执行“Gather→BeginApply（真实读）→Apply（累加）→Scatter（统一应用ΔV）”。
- 关键参数（由 `test_mesh_4x4.py` 传入 `SnnDL.SnnPESubComponent` 与 `SnnDL.GatherBufferIF`）：
  - `gas_enable=1`
  - `gas_window_mode=1`
  - `apply_acc_enable=1`
  - `apply_dense_acc_enable=1`（仅影响累加器数据结构，不改语义）
  - `window_read_enable=1`（BeginApply 启动 “上一窗边/集合” 的真实读）
  - GatherBufferIF：`emit_stage_events=1`，`emit_stage_events_lenient=1`（便于窗口事件闭合）
  - 诊断（默认关闭）：`window_read_debug=0`
- 随机发放：事件权重固定 0.0，仅携路由信息，不直接修改膜电位，保持严格 GAS。

## 五、Spike 源与 ID 映射
- 输入层 4 个 `SpikeSource`（PE0..3），两列 TEXT（src ts）时需映射全局 ID：
  - `neuron_offset = pe_id * neurons_per_pe`（当前自动配置）
  - `neurons_per_pe = 20 × 500 = 10,000`
- 说明：若不设置 offset，PE1/2/3 的本地 ID 将被错误路由到 PE0（dest_node=0）。

## 六、统计项与汇总
- 统计输出位置：`<run_dir>/mesh_stats.csv`（全局）与 `peXX/*.csv`（分 PE）
- 关键统计（SnnDL.SnnPESubComponent/MultiCorePE/GatherBufferIF）：
  - `memory_requests`：读请求次数（节点级）
  - `mem_req_size_bytes`：读请求字节总量（节点级）
  - `mem_outstanding_at_issue`：发起时未完成请求数（节点级）
  - GAS 汇总：
    - `gas_unique_reads_total`, `gas_unique_bytes_total`
    - `gas_apply_acc_updates_total`, `gas_acc_posts_touched_total`, `gas_scatter_spikes_emitted_total`
    - `gas_acc_high_watermark_bytes_total`, `gas_acc_spill_records_total`, `gas_acc_spilled_bytes_total`
  - NIC（如启用 NoC 注入时）：`spikes_sent/recv`, `packets_sent/recv`
- 窗口事件与指标（分 PE）：
  - `peXX/pe_stage_events_db.csv`：每窗 Begin/End 事件（ns），用于统计窗口平均/分位。
  - `peXX/coreYY_window_metrics.csv`：窗口级指标（`payload_bytes/bursts/inflight_peak` 等）。
- 汇总工具：`tools/compute_essential_summary_mesh.py`
  - `memory_bytes` 优先采用 `mem_req_size_bytes`；如缺失，回退聚合 per‑PE/per‑core `window_metrics` 的 `payload_bytes` 总和。
- 典型 10us 汇总值（10k/PE）：
  - `memory_requests`≈3,168,000；`memory_bytes`≈1.267e11
  - `gas.windows`≈576；`gather/apply/scatter`≈200/40/40 ns

## 七、配置项（常用）
- `sst_dram_si/local_run_config.json`
  - `num_cores_per_pe`: 20
  - `neurons_per_core`: 500（10k/PE）
  - `sim_time`: `10us` 或 `100us`
  - GAS 参数：`gas_enable=1`, `apply_acc_enable=1`, `gas_window_auto=1`
  - GatherBufferIF/window：`window_read_enable=1`, `window_read_budget`, `max_inflight_reads` 等
  - 统计：`emit_stage_events=1`, `emit_stage_events_lenient=1`
  - 诊断：`window_read_debug`（默认 0，关闭零开销）
- 环境变量：
  - `MESH_BCSR_DIR`：优先加载的 BCSR 目录（默认自动探测 10k）。
  - `MESH_SIM_TIME`：本次仿真时长（优先于 config）。

## 八、运行与验证
- 10us 快测（推荐回归基线）：
  ```bash
  cd sst_dram_si
  MESH_BCSR_DIR="$(pwd)/weights/bcsr_global_16pe_fanout256_10k" \
  MESH_SIM_TIME=10us tools/run_mesh_with_time.sh
  ```
  - 验证点：
    - `mesh_run.log` 出现“✅ 检测到全局BCSR数据: ..._10k”。
    - `essential_summary_mesh.json` 的 `model.neurons_per_core=500`、`neurons_per_pe=10000`。
    - `memory.memory_requests` 非零；`memory_bytes` 非零。
    - `gas.windows` 与窗口平均/分位数有值。
- 100us 长跑：
  ```bash
  cd sst_dram_si
  MESH_BCSR_DIR="$(pwd)/weights/bcsr_global_16pe_fanout256_10k" \
  tools/run_mesh_with_time.sh
  ```

## 九、常见问题与排查
- 现象：`memory_bytes=0`
  - 原因：汇总未读取到 `mem_req_size_bytes` 或窗口 `payload_bytes` 为 0。
  - 处置：
    1) 确认节点级已启用 `mem_req_size_bytes`（已在脚本中开启）。
    2) 或用回退口径：聚合 per‑core `window_metrics` 的 `payload_bytes`。
- 现象：`gas.windows=0`
  - 原因：未开启 `emit_stage_events` 或窗口事件未闭合。
  - 处置：启用 GatherBufferIF 的 `emit_stage_events=1` 与 `emit_stage_events_lenient=1`。
- 现象：输入脉冲错误路由到 PE0
  - 原因：两列 TEXT 数据缺少全局 offset。
  - 处置：`neuron_offset = pe_id * neurons_per_pe`（脚本已自动设置）。
- 并发 CSV 错乱/崩溃
  - 处置：禁用 granules 导出；`window_metrics` 按 core 落盘；避免 64 实例并发写同一文件。

## 十、附录：文件与脚本
- 模型：`sst_dram_si/test_mesh_4x4.py`
- 汇总：`sst_dram_si/tools/compute_essential_summary_mesh.py`
- 运行：`sst_dram_si/tools/run_mesh_with_time.sh`
- 10k 权重：`sst_dram_si/weights/bcsr_global_16pe_fanout256_10k`
- 校验：`sst_dram_si/tools/verify_bcsr_meta_mesh.py`

> 备注：本手册默认保持严格 GAS 语义；随机发放事件权重恒为 0.0，仅携路由信息；ΔV 仅由 Apply 阶段真实权重读取与累加产生。
