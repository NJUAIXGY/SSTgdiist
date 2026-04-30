# 当前 single-PE 测试参数与开关总览（含 2026-03-26 remote runtime 备注）

本文件梳理当前单节点/单PE测试中用到的全部可配置“参数与开关”，覆盖：
- 运行配置入口（local_run_config.json）与脚本映射关系
- GAS（Gather/Apply/Scatter）相关开关与参数
- BCSR 权重读写相关参数（生成/加载/读取）
- 调试与统计开关
- 100k 与 1M 两个规模的“配置快照”与推荐组合

适用范围：`sst_dram_si/test_dram_si_single_pe.py`（Single-PE DRAM 访存实验），权重采用“spike→BCSR 合成，WeightLoader(raw)落入内存，PE端以 BCSR 方式读取”的路径；本文同时覆盖历史 `simpleMem` 口径与当前 remote 活跃基线使用的 `ramulator2` 口径。

---

## 0) 2026-03-26 当前活跃基线快照

下面这组信息优先级高于本文后面保留的旧 `100k/1M + simpleMem` 快照；如果主人现在要在 remote 环境复现实验，先看这里：

- 当前活跃 single-PE baseline：
  - `num_cores_per_pe=20`
  - `neurons_per_core=500`
  - `sim_time="100us"`
  - `mem_backend="ramulator2"`
  - 原始 `mc_mem_size="64MiB"`，但运行期可能被 single-PE helper 自动扩成 effective 容量
- 当前推荐 wrapper：
  - `cd "/home/xgy/remote/sst_dram_si" && ./tools/run_singlepe_with_time.sh "/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_N1k"`
  - 这份 wrapper 已硬化为：
    - 优先 `/home/xgy/remote/sst_install_mpi/bin/sst`
    - 其次 `/home/xgy/remote/sst_install/bin/sst`
    - 明确拒绝 fallback 到 serial SST
- 当前 single-PE runtime helper：
  - `/home/xgy/remote/sst_dram_si/runtime_paths.py`
  - 已负责三类 remote 宿主漂移收敛：
    - `resolve_singlepe_ramulator2_config()`：优先 repo-local memHierarchy cfg，缺失时回退本地 cfg
    - `resolve_singlepe_mc_mem_size()`：若 `num_cores * weight_stride` 超过原始 `mc_mem_size`，则向上对齐到整 MiB 的 effective 容量
    - `resolve_singlepe_spike_dataset()`：默认 dataset 会先查 repo root 的 `SnnDL_Basic/`，再回退到 `github_submission/SnnDL_Basic/`
- 当前 real smoke 已验证通过：
  - 目录：`/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_N1k/20260326-141530`
  - authority 文件：
    - `local_run_config.effective.json`
    - `essential_summary.json`
  - 结果摘要：
    - `wallclock.real = 56.51`
    - `memory_requests = 13`
    - `dram_bytes_read = 832`
    - `total_spikes_processed = 789`
    - `total_neurons_fired = 530`
  - 当前 authority 摘要：
    - `local_run_config.effective.json.mc_mem_size = "383MiB"`
    - `local_run_config.effective.json.mc_mem_size_configured = "64MiB"`
    - `local_run_config.effective.json.mc_mem_size_auto_expanded = 1`
    - `essential_summary.json.runtime_config.mc_mem_size.effective = "383MiB"`
    - `essential_summary.json.runtime_config.dataset_path.effective = "/home/xgy/remote/github_submission/SnnDL_Basic/spike_data/complex_input_pe_0_class_A.txt"`
- 当前最重要的使用注意：
  - `local_run_config.json` 里的 `mc_mem_size` 仍然是“原始配置值”，但从这次起 single-PE 的实际 effective 值已经写回：
    - `RUN_DIR/local_run_config.effective.json`
    - `RUN_DIR/essential_summary.json.runtime_config`
  - `dataset_path` 若未在 `local_run_config.json` 显式给出，summary 会保持：
    - `runtime_config.dataset_path.configured = null`
    - `runtime_config.dataset_path.effective = <resolved absolute path>`
  - 本文后面的 `100k/1M + simpleMem` 段落仍有参考价值，但它们更多是历史快照，不代表现在 remote 上正在使用的主 baseline。

---

## 1) 配置入口与优先级
- 主入口：`sst_dram_si/local_run_config.json`
  - 绝大多数开关由此注入至测试脚本（`test_dram_si_single_pe.py`），再分发到各组件（MemCtrl / WeightLoader / MultiCorePE / SnnPESubComponent）。
  - 若脚本中存在默认值，`local_run_config.json` 中的同名键优先覆盖默认。
- 当前推荐运行入口：`sst_dram_si/tools/run_singlepe_with_time.sh`
  - 根目录旧 wrapper `sst_dram_si/run_singlepe_with_time.sh` 仍然存在，但这次 remote 验证与 parallel selector 硬化都走的是 `tools/` 下面这份 wrapper。
- 权重文件与偏移：由合成脚本输出 meta.json 提供；在 `local_run_config.json` 中回填给运行时（BCSR offsets/stride）。

---

## 2) 全量开关清单（按功能分组）

以下均为 `local_run_config.json` 的键；括号给出含义与典型取值。末尾附“当前 100k/1M 快照”。

### 2.1 基础运行与数据集
- `sim_time`（仿真时长，字符串，如 `"100us"`）
- `num_cores_per_pe`（每PE核心数，当前=20）
- `neurons_per_core`（每核心神经元数，100k=5000；1M=50000）
- `enable_spike_source`（启用文本脉冲源，1/0）
- `dataset_path`（脉冲文本路径，相对脚本目录；若未显式给出，single-PE runtime helper 会尝试自动解析默认 dataset 路径）
- `event_weight`（事件权重回退值，仅在禁用内存权重时使用）
- `start_time_us`（脉冲起始时间，us）
- `loop_dataset`（数据集循环，1/0）

### 2.2 内存系统与后端
- `mem_backend`（内存后端：`"simple"` 或 `"ramulator2"`；当前 remote 活跃 baseline 使用 `ramulator2`）
- `mc_mem_size`（内存大小声明，例如 `"64GiB"`/`"512GiB"`；single-PE 当前会在运行期按 WeightLoader footprint 自动扩成 effective 容量）
- `line_size_bytes`（子组件视角的 cache line，当前=64）
- `bank_bits` / `bank_shift`（行窗口/映射推断相关；simpleMem 不敏感，ramulator2 下主要影响行/银行相关实验判读）

### 2.3 权重加载（WeightLoader）
- `enable_weight_loader`（启用运行时权重写入，1/0）
- `enable_memory_weights`（启用“从内存取权重”，1/0）
- `enable_weight_fetch`（PE 侧允许发起权重读取，1/0）
- `weight_format`（`"raw"|"bin"|"csv"|"bcsr"`；当前使用 `"raw"`，直接把 BCSR 原始文件写入内存）
- `per_core_files`（每核一文件，1/0）
- `file_template`（权重文件模板，支持 `{core:02d}`）
- `per_node_stride`（每核内存步长/跨度，字节，对齐到 64KiB；来自 meta）
- `validate_length`（加载时长度校验，1/0）
- `loader_fill_value`（无文件时的填充值 FP32）
- `loader_verbose` / `loader_timed_seed_enable` / `loader_timed_seed_allow_cache`（加载器日志/时序写入选项）

### 2.4 BCSR 布局（运行时读取所需）
- `index_mode`（索引模式：`"bcsr_post_row"` 表示 行=post_local，列=pre_global）
- `bcsr_block_rows`（br，默认 16）
- `bcsr_block_cols`（bc，默认 16；1M 推荐 8 以缓解块膨胀）
- `bcsr_val_bytes`（块内标量字节，FP32=4）
- `bcsr_idx_bytes`（colidx 项字节，U16=2/U32=4；取决于列数上限）
- `bcsr_rowptr_offset` / `bcsr_colidx_offset` / `bcsr_blockdata_offset` / `bcsr_blockids_offset`（四段偏移；严格按合成器 meta 回填）

### 2.5 GAS（窗口化 Gather/Apply/Scatter）
- `gas_enable`（启用 GAS 框架，1/0）
- `gas_strict_mode`（严格 GAS：仅 Scatter 应用 ΔV；Apply 仅窗口读/累加，1/0）
- `gas_window_auto`（启用固定窗口周期（G/A/S），1/0）
- `gas_window_cycles_gather` / `gas_window_cycles_apply` / `gas_window_cycles_scatter`（ns：200/40/40）
- `apply_acc_enable`（Apply 阶段启用窗口累加器，1/0）
- `window_read_enable`（开启 Apply 窗口读/单列读，1/0）
- `window_read_budget`（每窗口读请求预算（计数），越大覆盖越多）
- `max_outstanding_requests`（PE 侧并发上限，建议先提升它）
- `gas_max_inflight_reads`（GBI/GAS 侧并发上限）
- `row_window_enable`（DRAM 行窗口优化开关；当前=0）
- `merge_read_cacheline` / `merge_read_row`（读合并策略；当前=1/0）
- `defer_issue_until_apply`（调度策略实验位，默认0）

### 2.6 Scheme‑1（致密预取路径，默认关闭）
- `scheme1_enable`（1/0；strict GAS + BCSR 路径下应为 0）

### 2.7 Spike 切片/时间分散（可选）
- `spike_segment_enable`（启用切片处理，1/0）
- `spike_slices` / `spike_slice_window_us` / `spike_slice_gap_us`（切片配置）

### 2.8 神经元/阈值模型
- `v_thresh`（阈值，诊断可降到极小值验证闭环）
- `tau_mem` / `t_ref`（膜常数/不应期）
- `use_event_weight_fallback`（无内存权重时回退到事件权重）

### 2.9 调试与统计
- `node_verbose` / `core_verbose`（日志冗余度）
- `window_read_debug`（窗口读阶段诊断，1/0；打印 BeginApply 摘要/补发，及 [diag-bcsr-weight]）
- `stats_csv`（CSV 输出路径；wrapper 会改写到当前 run 目录）
- `stage_events_csv`（G/A/S 阶段事件 CSV；wrapper 会改写到当前 run 目录）
- `verify_weights` / `weight_verify_samples` / `verify_log_each_sample` / `expected_weight_value`（权重校验相关）

---

## 快速基线（100k 可复现发放）

```json
{
  "sim_time": "100us",
  "window_read_enable": 1,
  "window_read_budget": 4194304,
  "max_outstanding_requests": 32768,
  "gas_max_inflight_reads": 65536,
  "spike_segment_enable": 0,
  "emit_stage_events_lenient": 1,
  "index_mode": "bcsr_post_row",
  "file_template": "weights/bcsr_from_spikes_N100k/core{core:02d}.bcsr.bin",
  "dataset_path": "outputs_large/paper2/dram_N100k/spikessrcdstN100000.txt"
}
```

说明：若将 `spike_segment_enable=1` 且削减预算/并发（如 `window_read_budget≤512 KiB`、`max_outstanding_requests≤128`、`gas_max_inflight_reads≤4096`），窗口内读取覆盖显著降低，通常不会出现发放。

---

## 3) 当前配置快照（100k，活跃）
文件：`sst_dram_si/local_run_config.json`（已回切 100k 并放大窗口/并发）

- 规模：`num_cores_per_pe=20`，`neurons_per_core=5000`，`sim_time="100us"`
- Spike：`enable_spike_source=1`，`dataset_path=outputs_large/paper2/dram_N100k/spikessrcdstN100000.txt`
- 内存后端：`mem_backend="simple"`，`mc_mem_size="64GiB"`
- 权重加载（raw 写入 BCSR 文件）：
  - `enable_weight_loader=1`，`enable_memory_weights=1`，`enable_weight_fetch=1`
  - `weight_format="raw"`，`per_core_files=1`
  - `file_template="weights/bcsr_from_spikes_N100k/core{core:02d}.bcsr.bin"`
  - `per_node_stride=77093632`
- BCSR（读取布局）：
  - `index_mode="bcsr_post_row"`，`bcsr_block_rows=16`，`bcsr_block_cols=16`
  - `bcsr_val_bytes=4`，`bcsr_idx_bytes=2`
  - 偏移：`rowptr=0`，`colidx=1280`，`blockdata=76544`，`blockids=38585088`
- GAS（严格窗口 + 大预算/并发）：
  - `gas_enable=1`，`gas_strict_mode=1`，`gas_window_auto=1`
  - `gas_window_cycles_{g,a,s}=200/40/40`（ns）
  - `apply_acc_enable=1`，`window_read_enable=1`，`read_force_single=1`
  - `window_read_budget=4194304`，`max_outstanding_requests=32768`，`gas_max_inflight_reads=65536`
  - `merge_read_cacheline=1`，`merge_read_row=0`，`row_window_enable=0`
- Scheme‑1：`scheme1_enable=0`
- 调试：`core_verbose=0`，`window_read_debug=1`，`stats_csv`/`stage_events_csv` 由 wrapper 注入到 run 目录

运行参考（历史口径）：`cd sst_dram_si && ./run_singlepe_with_time.sh`

当前 remote 推荐口径：`cd sst_dram_si && ./tools/run_singlepe_with_time.sh "<run_base>"`

---

## 4) 预置配置快照（1M，待验证）
文件/建议：按 meta 回填并适度提升并发/预算；若遇 `memory_requests=0`，先开启 `window_read_debug` 与 `core_verbose` 排查 pre/post 集合。

- 规模：`num_cores_per_pe=20`，`neurons_per_core=50000`，`sim_time="100us"`
- Spike：`dataset_path=outputs_large/paper2/dram_N1M/spikessrcdstN1000000.txt`
- 内存后端：`mem_backend="simple"`，`mc_mem_size="512GiB"`
- 权重加载（raw 写入 BCSR 文件）：
  - `file_template="weights/bcsr_from_spikes_N1M/core{core:02d}.bcsr.bin"`
  - `per_node_stride=395080192`
- BCSR（读取布局）：
  - `index_mode="bcsr_post_row"`，`bcsr_block_rows=16`，`bcsr_block_cols=8`
  - `bcsr_val_bytes=4`，`bcsr_idx_bytes=4`
  - 偏移：`rowptr=0`，`colidx=12544`，`blockdata=1549824`，`blockids=198315008`
- GAS 建议（起步）：
  - `apply_acc_enable=1`，`window_read_enable=1`，`read_force_single=1`
  - `window_read_budget≥524288`，`max_outstanding_requests≥4096`，`gas_max_inflight_reads≥8192`
- 调试：`core_verbose=1`，`window_read_debug=1`（观察 BeginApply 摘要与 [diag-bcsr-weight]）

注：首次 1M 运行出现 `memory_requests=0` 的典型原因是“上一窗口的 active_pre_prev_window_/posts_list_prev_window_ 未形成”，需先排查路由/本地映射是否将 dst 正确投递到所属 core（`global_neuron_base=core_idx*neurons_per_core`）。

---

## 5) BCSR 合成与偏移（供回填）
- 合成脚本：`sst_dram_si/tools/spikes_to_bcsr.py`
  - 100k：`--rows-per-core 5000 --cols-total 100000 --br 16 --bc 16 --idx-bytes 2`
  - 1M：`--rows-per-core 50000 --cols-total 1000000 --br 16 --bc 8 --idx-bytes 4`
- meta 输出：`core{core:02d}.bcsr.bin.meta.json`
  - 含四段偏移与 per_core_stride；严格以 meta 为准回填至 `local_run_config.json`。

---

## 6) 调试与验证建议
- 启用 `window_read_debug=1`：
  - BeginApply 摘要 `[diag-window-read]`：打印上一窗口活跃 pre 与触达 post 的规模、预算与并发（判断是否形成集合/是否受 budget 限制）。
  - 权重命中 `[diag-bcsr-weight]`：打印 `(core, post_local→post_global, pre_global, weight)`，用于与 spike→BCSR 的预期对比。
- 统计口径：
  - `memory_requests > 0`、`dram_bytes_read > 0`：窗口读已覆盖到 BCSR 段。
  - `total/unique_neurons_fired > 0`：闭环发放成立（与 `v_thresh` 与覆盖度相关）。
- 日志对照：`sst_dram_si/tools/analyze_bcsr_weight_logs.py` 可抽查日志/权重是否一致（注意仅覆盖“被访问的 pair”）。

---

## 7) 常见组合与建议
- 严格 GAS + BCSR 基线：
  - 关闭 Scheme‑1（`scheme1_enable=0`），开启 `window_read_enable=1` + `read_force_single=1`，`index_mode="bcsr_post_row"`。
  - 提升 `max_outstanding_requests` 优先于 `window_read_budget`（先提升并发，再扩大预算）。
- 100k 起步：`window_read_budget=524288`、`max_outstanding_requests=4096`、`gas_max_inflight_reads=8192`；若覆盖不足导致发放低，再加档（如本次 8× 放大）。
- 1M 起步：`bc=8`、`idx_bytes=4`、`window_read_budget≥524288`、并发≥4096 并开启日志核查集合形成情况。
- 若 spike 时间高度集中（例如所有在 5us）：
  - 更经济的做法是“分散时间/启用切片”，而不是无限放大 `window_read_budget`。

---

## 8) 运行与产物
- 运行（历史口径）：`./sst_dram_si/run_singlepe_with_time.sh`
- 运行（当前 remote 推荐）：`cd sst_dram_si && ./tools/run_singlepe_with_time.sh "<run_base>"`
- 产物目录：
  - `outputs_large/paper2/dram_N100k/<ts>/` 或 `dram_N1M/<ts>/`
  - `latest/` 软链指向最近一次运行
  - `essential_summary.json`：关键结果（memory/spike/gas/window 等）
  - `logs/last_run.wrapper.log`：详细日志（含 `[diag-*]`）
