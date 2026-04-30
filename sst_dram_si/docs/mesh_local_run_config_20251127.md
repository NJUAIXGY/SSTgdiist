# Mesh 4×4 `local_run_config.json` 参数说明（2025-11-27 基线 run）

对应配置文件路径：

- `sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251127-190110/local_run_config.json`

该配置用于 4×4 Mesh 高激活场景的 10us 基线回归（严格 GAS + Step 随机激发）。下面按功能分组说明各字段含义。

---

## 1. 全局仿真与规模参数

- `sim_time: "10us"`  
  仿真目标时长。脚本会用它设置 `sst.setProgramOption("stop-at", sim_time)`；也可被环境变量 `MESH_SIM_TIME` 覆盖。

- `num_cores_per_pe: 20`  
  每个 PE（MultiCorePE）包含的核心数量。与 `neurons_per_core` 共同决定每个 PE 的神经元数：
  `neurons_per_pe = num_cores_per_pe * neurons_per_core`。

- `neurons_per_core: 5000`  
  每核神经元数量。若 BCSR meta 文件中包含 `rows` 字段，则实际运行时会优先使用 meta 中的行数覆盖该值。

---

## 2. Spike 输入 / SpikeSource

- `enable_spike_source: false`  
  是否启用 `SnnDL.SpikeSource` 组件作为外部脉冲源。  
  - `false`：当前 Mesh 模板主要依赖 Step 随机激发；`dataset_path` 等仅用于兼容单 PE 脚本。  
  - `true`：会从 `dataset_path` 指定的数据集中读取 spike。

- `dataset_path: "outputs_large/paper2/dram_N100k_single/spike_one.txt"`  
  SpikeSource 使用的数据集路径（文本文件），仅在 `enable_spike_source=true` 时生效。

- `event_weight: 1`  
  当启用事件权重回退（`use_event_weight_fallback=1`）时使用的默认权重。当前 Mesh 基线不依赖该路径（完全依赖内存权重）。

- `start_time_us: 1`  
  SpikeSource 开始发放的时间（μs）。

- `loop_dataset: 0`  
  是否循环播放数据集。`0` 表示只播放一次，`1` 表示循环。

---

## 3. 权重加载与权重来源

- `enable_weight_loader: true`  
  是否启用 `SnnDL.WeightLoader` 将权重写入内存。关闭仅用于极端调试。

- `enable_memory_weights: 1`  
  MultiCorePE 是否从内存中读取权重（正常路径）。若为 0，则依赖事件权重回退或默认值。

- `enable_weight_fetch: 1`  
  SnnPESubComponent 是否启用权重读取路径。设为 0 会绕过标准内存权重路径，一般不建议在 Mesh 基线中修改。

- `use_event_weight_fallback: 0`  
  是否启用事件权重回退：
  - `0`：所有 ΔV 来自内存权重（BCSR + GAS）；  
  - `1`：在缺失权重时可回退到 `event_weight`。

- `weight_format: "raw"`  
  权重文件格式。Mesh 4×4 使用 raw + BCSR meta 手工指定布局。

- `per_core_files: 1`  
  是否按“每核一个文件”组织权重。`1` 表示 `coreXX.bcsr.bin` 这类 per-core 文件布局。

- `file_template: "weights/bcsr_N100k_new/core{core:02d}.bcsr.bin"`  
  单 PE dram_si 脚本使用的 BCSR 权重模板。Mesh 4×4 模板使用自己的 `bcsr_global_16pe_fanout256_10k` 目录，本字段主要用于兼容单 PE。

- `validate_length: 0`  
  是否对权重长度做严格验证（0 关闭，>0 打开）。

---

## 4. 内存 / Cache / MemController 配置

- `mem_backend: "simple"`  
  MemController 后端类型：  
  - `"simple"`：简单固定延迟内存模型（当前 Mesh baseline 使用）；  
  - `"ramulator2"`：对接 Ramulator2 DRAM 模型。

- `mc_mem_size: "64GiB"`  
  内存控制器抽象出的总内存容量，用于地址合法性与容量检查。

- `line_size_bytes: 64`  
  L1 cache 行大小，以及 SnnPESubComponent 使用的 `line_size_bytes`。

- `max_outstanding_requests: 32768`  
  每个核心允许的最大并发 StandardMem 请求数量。用于限制下游 DRAM 请求压力。

- `disable_weight_cache: 0`  
  是否禁用核心内部权重 cache。0 表示启用缓存，1 表示每次访问都从内存读取。

- `read_force_single: 1`  
  是否强制以单一模式下发读请求，常用于诊断严格 GAS 下的读行为。

- `merge_read_cacheline: 1`  
  是否按 cacheline 将多个读请求合并。

- `merge_read_row: 0`  
  是否按“行”维度合并读请求。当前配置关闭。

- `bank_bits: 4` / `bank_shift: 16`  
  从物理地址中抽取 bank 信息的位数及偏移，用于 bank 行行为建模。

---

## 5. GAS / GatherBufferIF 相关参数

> 注意：下面字段是“逻辑配置”，具体传给 SnnPESubComponent 与 GatherBufferIF 的值由脚本 `test_mesh_4x4.py` 衍生而来。  
> Mesh GAS 模式使用严格窗口：200/40/40 ns + auto window。

- `gas_enable: 1`  
  表示配置期望启用 GAS 行为，脚本据此设置核心侧 `gas_enable`。

- `gas_window_auto: 1`  
  启用自动窗口驱动：按 `gas_window_cycles_*` 决定 Gather/Apply/Scatter 各阶段时长。

- `gas_sram_bytes: 1048576`  
  GatherBufferIF 内部 SRAM 容量（字节），用于缓存聚合后的 granule。

- `gas_max_inflight_reads: 65536`  
  GatherBufferIF 允许的最大并发下游读请求数。

- `gap_merge_k_bytes: 2048`  
  gap 合并阈值（KiB，脚本中会 ×1024）。相邻地址间隔小于该值可归并为单次读。

- `burst_bytes_max: 65536`  
  单次 burst/granule 最大字节数，用于限制合并后的请求大小。

- `row_window_enable: 0`  
  是否启用“按行窗口”的读请求聚合。当前配置为 0，完全依赖固定窗口。

- `gather_auto_end_bytes: 2097152` / `gather_auto_end_reads: 0`  
  Gather 阶段自动结束条件：  
  - bytes 达到阈值（约 2MiB）时提前结束；  
  - reads 阈值为 0 表示不按次数截断。

- `gas_window_cycles_gather: 200`  
  Gather 阶段目标时长（ns）。

- `gas_window_cycles_apply: 40`  
  Apply 阶段目标时长（ns）。

- `gas_window_cycles_scatter: 40`  
  Scatter 阶段目标时长（ns）。

- `apply_acc_enable: 1`  
  是否启用窗口化累加器（Apply 阶段的 ΔV 累加逻辑）。Mesh 严格 GAS 下必须为 1。

- `gas_strict_mode: 1`  
  严格 GAS 模式：必须按 Gather→Apply→Scatter 顺序执行，且在窗口内完成累加。

- `probe_gas_enable: false`  
  是否启用 GAS 探针 CSV（`probe_gas_samples.csv`），会带来额外 I/O 开销，默认关闭。

---

## 6. 神经元动力学参数

- `v_thresh: 1e-05`  
  默认阈值（仅在脚本未根据层类型覆盖时使用）。Mesh 模板中实际按层重写：
  - 输入层：0.02  
  - 隐藏层：0.03  
  - 输出层：0.035

- `tau_mem: 200`  
  膜时间常数（单位由实现决定，通常为 ms 级）。控制膜电位衰减速度。

- `t_ref: 2`  
  不应期长度（refractory period），单位为仿真周期。

---

## 7. 统计与日志控制

- `stats_csv: "outputs_large/paper2/dram_N100k_single/dram_si_stats.csv"`  
  单 PE dram_si 模式下统计输出路径。Mesh 模式使用的是 `_RUN_OUTPUT_DIR/mesh_stats.csv`，该字段保留兼容性。

- `node_verbose: 1` / `core_verbose: 2`  
  MultiCorePE 和 SnnPESubComponent 的 verbose 等级。  
  - 0：基本静默；  
  - 1–2：适度调试输出；  
  - 更高等级可能产生大量日志，仅用于排查问题。

- `loader_verbose: 0`  
  WeightLoader 日志等级。

- `loader_timed_seed_enable: false` / `loader_timed_seed_allow_cache: true`  
  控制权重载入的种子与缓存行为，用于保证可复现与性能调优。

- `verify_weights: false` / `weight_verify_samples: 256`  
  权重文件与内存内容的运行期验证开关与样本数。当前配置关闭验证（避免额外读）。

- `verify_log_each_sample: 0`  
  是否为每个验证样本输出日志。

- `log_weight_details: 0`  
  是否输出详细权重日志（per-edge/per-block），默认关闭以避免日志爆炸。

- `window_read_debug: 0`  
  GatherBufferIF 窗口读调试输出开关，默认关闭。

- `window_stats_enable: 1`  
  MultiCorePE 时间窗口统计开关，用于收集每 20us 的统计分布。

- `window_us: 20`  
  时间窗口长度（微秒），配合 `window_stats_enable` 使用。

- `stage_events_csv: "sst_dram_si/outputs_large/paper2/dram_N100k_single/stage_events_db_100us.csv"`  
  单 PE 阶段事件输出路径。Mesh 模式使用 `pe*/pe_stage_events_db.csv`，该字段主要对单 PE 有效。

- `emit_stage_events: 1` / `emit_stage_events_lenient: 1`  
  控制是否写出 stage events 以及是否以宽松模式写出（宽松模式避免阶段缺失导致 fatal）。

---

## 8. BCSR 几何与偏移

- `index_mode: "bcsr_post_row"`  
  索引模式：行 index 对应 post-local，列 index 对应 pre-global（post-owned BCSR）。

- `bcsr_block_rows: 20` / `bcsr_block_cols: 16`  
  BCSR 每 block 的行数（br）和列数（bc）。

- `bcsr_val_bytes: 4` / `bcsr_idx_bytes: 4`  
  权重值（float）和索引（colidx / blockids）的字节数。

- `bcsr_rowptr_offset: 0`  
  BCSR 文件中 rowptr 段偏移（字节）。

- `bcsr_colidx_offset: 1024`  
  colidx 段偏移。

- `bcsr_blockdata_offset: 150464`  
  blockdata（权重块数据）段偏移。

- `bcsr_blockids_offset: 47955904`  
  blockids 段偏移。

这些偏移与 `weights/bcsr_N100k_new/core{core:02d}.bcsr.bin.meta.json` 中的信息保持一致，用于确保内存寻址正确。

---

## 9. Step 随机激发配置

- `step_random_activation_enable: 1`  
  启用 Step 级随机激发（严格 GAS 场景下的主要发放机制）。

- `step_activation_fraction: 0.001`  
  每个 Step 中 pre 神经元被选为激活源的伯努利概率。  
  在总神经元数约 `N ≈ mesh_size² * num_cores_per_pe * neurons_per_core` 下，
  期望激活数约为 `N × fraction`。

- `step_activation_fanout: 256`  
  每个被选中的 pre 向多少个 post 发放脉冲。

- `step_activation_seed: 271828`  
  Step 激发的随机数种子，固定后便于跨 run 对齐实验。

- `step_activation_event_weight: 0.0`  
  事件权重 fallback 的值；在当前“权重完全来自 BCSR”配置下不参与实际计算。

- `step_activation_use_bcsr_routes: 1`  
  是否使用 BCSR 路由表（从 BCSR 文件抽取实际存在边），仅对存在边的 post 发放，避免在无出边 pre 上浪费尝试。

- `step_activation_log_enable: 0`  
  是否启用 Step 激活构建路由时的详细日志（`[[step-diag-*]]`），默认关闭。

- `step_diag_enable: 0` / `step_diag_cap: 0`  
  Step 诊断开关与采样上限。当前关闭，避免额外输出。

- `step_reset_mem_each_step: 0`  
  是否在每个 Step 结束后重置膜电位，当前为 0（保留时间上的记忆）。

---

## 10. 其他控制开关

- `enable_profiler: false`  
  是否启用额外的 profiler（脚本/组件级）。

- `spike_segment_enable: 0`  
  是否启用 spike segmentation 相关功能。

- `spike_slices: 20` / `spike_slice_window_us: 5` / `spike_slice_gap_us: 0`  
  Spike segmentation 的分片数、窗口长度和间隔（当前未启用）。

- `apply_dense_acc_enable: 1`  
  是否启用致密累加器实现，用于提升 Apply 阶段的累加效率。

- `scheme1_enable: 0`  
  是否启用 scheme-1（分片式 GAS 模式）。当前配置关闭。

- `routing_mode: "weight_driven"`  
  路由模式，`weight_driven` 表示根据权重矩阵（或 BCSR）动态推导路由，而非固定表。

---

本说明覆盖了当前 Mesh 4×4 高激活基线 run 所使用的 `local_run_config.json` 主要字段，可作为后续参数调优、实验设计与对比的参考文档。  
