# DRAM-SI 单PE内存研究 技术进展

本文档用于跟踪 sst_dram_si 子目录下“单PE + memHierarchy + Ramulator2”以及 Mesh 模型相关实验的进度、变更与待办。

## 2026-01-09 Mesh 模版脚本继续瘦身：BCSR/GAS/统计初始化下沉（100us 回归对比 OK）

- 目的：继续推进 `sst_dram_si/test_mesh_4x4.py` → `sst_dram_si/mesh_template/` 的分层重构，在**不改变行为/默认参数/输出口径**前提下，把入口脚本里剩余的 BCSR runtime 组装、GAS env 解析、stats 输出初始化进一步下沉，降低维护成本。
- 代码改动：
  - `sst_dram_si/mesh_template/bcsr.py`
    - 新增 `resolve_global_bcsr_runtime(...)`：一次性返回 BCSR catalog/meta/offsets + per-core stride + base_addr_shift（8KiB 对齐）+ cols/rows override。
    - 新增 `apply_step_activation_bcsr_defaults_from_global_offsets(...)`：在 Step BCSR offset 为 None 时回填默认值（保持“显式覆盖优先”语义）。
  - `sst_dram_si/mesh_template/config.py`
    - 新增 `apply_gas_env_overrides(...)`：把 `MESH_GAS_MERGE_POLICY/MESH_GAS_MAX_INFLIGHT/MESH_GAS_CYCLES` 的 env 解析与打印下沉；保持“env 变量存在即阻断 local_run_config 覆盖”的旧语义。
  - `sst_dram_si/mesh_template/paths.py`
    - 新增 `prepare_run_output_and_stats(...)`：run_dir 创建 + `mesh_stats.csv` 输出初始化（必须在创建组件前调用）。
  - `sst_dram_si/mesh_template/stats.py`
    - 新增 `enable_default_statistics(...)`：把 `enableAllStatisticsForComponentType/enableAllStatisticsForAllComponents` 的全局启用下沉，入口脚本更薄。
  - `sst_dram_si/mesh_template/task_snn.py`
    - 新增 “SNN 分类任务层次/默认频率/layers_cfg 拼装” 收敛：把固定 4×4 分层（0-3/4-7/8-11/12-15）与 4 类频率（40/80/120/200Hz）下沉，入口脚本只保留少量变量名用于兼容。
  - `sst_dram_si/mesh_template/step.py`
    - 新增 `build_step_cfg(...)`：把 Step 配置字典拼装下沉，入口脚本只负责设置默认/覆盖，避免口径漂移。
  - `sst_dram_si/mesh_template/config.py`
    - 新增 `apply_global_step_sync_env_override(...)`：把 `MESH_GLOBAL_STEP_SYNC` 的 env 覆盖解析下沉，保持“env 优先于 local_run_config”的旧语义。
  - `sst_dram_si/mesh_template/legacy_defaults.py`
    - 新增 `make_default_state()`：把 mesh 模版脚本的默认值集中为“唯一真相”，避免默认散落导致的搬家漂移。
  - `sst_dram_si/mesh_template/runtime.py`
    - 新增 `resolve_runtime(...)`：按固定顺序解析 defaults→env→local_run_config→GLOBAL_STEP_SYNC env→BCSR runtime/meta→派生→cfg 冻结；并提供可选 `MESH_DUMP_CONFIG=1` 写出 `runtime_config.json`+`sha256` 作为“防漂移护栏”。
  - `sst_dram_si/mesh_template/entry.py`
    - 新增 `run_mesh_4x4(...)`：把 resolve_runtime + build_mesh_4x4 + sst program options 封装为“一键入口”。
  - `sst_dram_si/test_mesh_4x4.py`
    - 入口收敛为极薄脚本：仅调用 `mesh_template.entry.run_mesh_4x4(sst, __file__)`，不再承载默认/覆盖/派生逻辑。
- 验证（100us，与基线严格一致）：
  - Run：`/home/xgy/remote/analysis/mesh_refactor_regress_100us`
  - Baseline：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260108-154709`
  - Compare：`python3 sst_dram_si/tools/compare_essential_summary_mesh.py --a <run> --b <baseline>` → 关键字段 Δ=0（含 `gas.*`、`memory.*`、`nic.*`、`spike_activity.*`）。

## 2026-01-05 Mesh 回归快测（按 SnnDL README）+ GAS 对接审阅记录

- 目的：按 `sst_workspace/sst-elements/src/sst/elements/SnnDL/README.md` 的推荐方式先做“能跑 + 指标不异常归零”的粗验证，并为后续严格正确性验证制定检查项。
- 回归运行：
  - 10us（SNN / Strict GAS）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260105-225511/essential_summary_mesh.json`
    - `gas.windows=51`，`neurons_fired_total=0`（符合 10us 允许为 0 的口径），无 fatal。
  - 100us（SNN / Strict GAS）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260105-225631/essential_summary_mesh.json`
    - `neurons_fired_total=2134`，无 fatal。
  - 100us（workload=stream / read-after-write 校验）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260105-225901/essential_summary_mesh.json`
    - `stream_mem_verify_fail_total=0`，`stream_pkt_bad_crc_total=0`，`stream_pkt_bad_magic_total=0`。
- 审阅备注（用于后续“严格正确性”专项）：
  - `GatherBufferIF` 的 granule key 采用 `(base<<32)^(size)` 压缩编码，需显式确认实验地址空间不会超过 32-bit base，否则存在 key 冲突风险。
  - `AccumulatorOps::mergeSpill_()` 在极端低 HWM/大窗口下可能触发“迭代 spill_log 时再次 spill”导致容器自修改风险，建议纳入强制触发 spill 的测试用例并修复后再用于论文实验。

## 2025-11-27 Mesh 4×4 回归与调试日志收口（10us）

- 目的：依据 `docs/mesh_template_guide_20251122-000250.md` 对 4×4 Mesh 模版做一次 10us 回归，并关闭 BCSR 相关的冗余调试输出，保留必要统计与汇总。
- 配置改动（文件：`sst_dram_si/local_run_config.json`）：
  - 将 BCSR/GAS 细粒度调试开关恢复为静默基线：`window_read_debug=0`、`log_weight_details=0`。
  - 关闭步级路由与 Step 激活诊断日志：`step_activation_log_enable=0`、`step_diag_enable=0`。
  - 其余 Strict GAS、Step 随机激发等参数保持不变（mesh_size=4、num_cores_per_pe=20、step_activation_fraction=1e-3、fanout=256 等）。
- 回归运行（4×4 Mesh，高激活配置）：
  - 命令：
    ```bash
    cd sst_dram_si
    MESH_SIM_TIME=10us ./tools/run_mesh_with_time.sh
    ```
  - 本次结果目录：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20251127-155058`
  - 关键摘要（`essential_summary_mesh.json`）：
    - `gas.windows ≈ 511`
    - `nic.packets_sent ≈ 1.06e5`
    - `window_metrics.payload_bytes_avg ≈ 8.9e4`，`payload_bytes_max ≈ 4.45e5`
    - `window_metrics.bursts_avg ≈ 13.6`，`inflight_peak_max ≈ 55`
    - `wallclock.wall ≈ 2:10`，`maxrss ≈ 53 GiB`
- 效果与结论：
  - 行为与统计数量级与之前 10us 回归保持一致，仅 wallclock 略有改善（从 ~2:53 收敛到 ~2:10）。
  - `mesh_run.log` 中的 `[diag-bcsr-*]`、窗口级 BCSR 读写等细粒度诊断日志已消失，保留了 Mesh 拓扑与层次、阈值等高层结构说明，满足“静默基线 + 可读摘要”的目标。
  - 后续 100us Mesh 稳定性回归可复用该静默配置，以避免日志成为额外性能因素。

## 2025-11-27 Mesh 4×4 Baseline 透传模式（无合并/行窗的 GAS 基线）

- 目的：为 4×4 Mesh 建立一个与严格 GAS 架构兼容的 baseline，用于“GAS 优化 vs 无优化”的公平对比。  
  - 保留 `GatherBufferIF` + 严格 GAS 时序（BeginGather/EndScatter + Step 激活绑定窗口）。  
  - 仅关闭 gap 合并、行窗口等访存优化，使其近似“按需直读 + 统计透传”。

- 脚本与文件：
  - 新 baseline 脚本：`sst_dram_si/test_mesh_4x4_baseline.py`（从 `test_mesh_4x4.py` 派生）。  
  - baseline 运行目录：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4_baseline/`.

- 核心改动（相对于严格 GAS 脚本 `test_mesh_4x4.py`）：
  1) 核心 SnnPESubComponent 参数（恢复为 GAS 时序）：
     - `gas_enable=1, gas_window_mode=1, apply_acc_enable=1, window_read_enable=1`。  
     - 其余如 `loader_done_key`、`max_outstanding_requests=64`、`merge_read_cacheline=1` 等保持与 GAS 脚本一致。  
     - 仍然按 BCSR meta 配置 `index_mode=bcsr_post_row`，并为 core0 提升 `verbose` 以便探针。
  2) 内存前端（GatherBufferIF 透传模式）：
     - `core_memory = core_subcomponent.setSubComponent("memory", "SnnDL.GatherBufferIF")`。  
     - 透传配置（区别于 GAS 模式）：
       - `defer_issue_until_apply = 0`（立即下发请求）。  
       - `gap_merge_enable = 0`、`gap_merge_k_bytes = 0`（禁用 gap 合并）。  
       - `row_window_enable = 0`、`row_window_bytes = 0`、`row_window_timeout_ns = 0`（禁用行窗口）。  
       - `k_adapt_enable = 1`（仅保留窗口统计，不改变行为）。  
       - 仍使用 `window_auto=1`、`window_cycles_{gather,apply,scatter} = 200/40/40`，`emit_stage_events=1`，并为每个 core 导出 `coreXX_window_metrics.csv`。
  3) 统计聚合脚本 `tools/compute_essential_summary_mesh.py`：
     - 若 `gas_scatter_spikes_emitted_total == 0`，回退使用 `multicore_pe_*` 的 `total_spikes_processed` 聚合 `spike_activity.total_spikes_processed`，兼容 baseline/非 GAS 场景。

- baseline 10us 实验（透传 GatherBufferIF，Step 激活开启）：
  - 运行示例：
    ```bash
    cd sst_dram_si
    RUN_ROOT=outputs_large/paper2/dram_mesh_4x4_baseline
    TS=$(date +%Y%m%d-%H%M%S)
    RUN_DIR="$RUN_ROOT/$TS"
    mkdir -p "$RUN_DIR"
    export MESH_RUN_DIR="$RUN_DIR"
    export MESH_SIM_TIME=10us
    ../sst_install/bin/sst -n 32 test_mesh_4x4_baseline.py > "$RUN_DIR/mesh_run.log" 2>&1
    /usr/bin/time -v -o "$RUN_DIR/time.txt" ../sst_install/bin/sst -n 32 test_mesh_4x4_baseline.py > /dev/null 2>&1
    python3 tools/compute_essential_summary_mesh.py --run-dir "$RUN_DIR"
    cp local_run_config.json "$RUN_DIR/local_run_config.json"
    ```
  - 代表性 run：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4_baseline/20251127-184822`  
    - `gas.windows = 520`（与 GAS 10us 的 ~511 接近）。  
    - `nic.packets_sent = 107526`。  
    - `window_metrics`：
      - `payload_bytes_avg ≈ 8.67e4`，`payload_bytes_max ≈ 4.62e5`。  
      - `bursts_avg ≈ 13.23`，`inflight_peak_max = 57`。  
    - `spike_activity`：
      - `total_spikes_processed = 35`。  
      - `window_spikes_total = 80`。  
      - `neurons_fired_total = 218`。  
    - `wallclock`：
      - `wall ≈ 2:08`；`user ≈ 500 s`；`sys ≈ 203 s`；`maxrss ≈ 50.4 GiB`。

- 结论与用途：
  - 该 baseline 与严格 GAS 模式在窗口数、Step 激发语义、BCSR 权重路径上保持一致，只在 GatherBufferIF 内部关闭 gap 合并与行窗口优化。  
  - 提供了一个“GAS 架构内的无优化基线”，便于后续在相同 Step 发放配置下，对比：
    - 每窗口 payload/bursts/inflight 的差异；  
    - 每窗口 / 每 run 的 memory_requests / memory_bytes；  
    - NIC 包数与 wallclock latency。  
  - 后续可在固定 Step 配置下，系统性采样多组（GAS 开/关优化）的 10us/100us run，填入外部 Excel 表（SourceRouting vs GAS）做 GSOPS / Cycle_Cost 对比。

## 2025-11-08 基线配置落地（1k / 10k）

基于《docs/BASELINE_100k_REPORT.md》的严格 GAS + BCSR 基线，为 N=1k、N=10k 制作可直接运行的配置与脚本，目录保持在 `outputs_large/paper2` 下，便于与 100k 对比复现。

- 生成 N=1k 数据集与权重：
  - 数据集：`outputs_large/paper2/dram_N1k/spikessrcdstN1000.txt`（由 N=10k 数据集筛选：src<1000 且 dst<1000）。
  - 权重：`weights/bcsr_from_spikes_N1k/core{core:02d}.bcsr.bin`（br=16, bc=16, idx=U16；偏移与 stride 见同目录 meta）。
- 配置文件（Strict GAS，一致窗口 200/40/40 ns；关闭随机脉冲）：
  - `configs/local_run_N1k_baseline.json`（20 核 × 50 神经元/核）。
  - `configs/local_run_N10k_baseline.json`（20 核 × 500 神经元/核，使用 `weights/bcsr_full_N10k` 的 meta 参数）。
- 便捷运行脚本（自动备份/恢复 `local_run_config.json` 并调用 `run_singlepe_with_time.sh`）：
  - `run_baseline_1k.sh`
  - `run_baseline_10k.sh`

运行方式：
```bash
cd sst_dram_si && ./run_baseline_1k.sh
# 或
cd sst_dram_si && ./run_baseline_10k.sh
```
结果目录：
- 1k：`sst_dram_si/outputs_large/paper2/dram_N1k/latest/`
- 10k：`sst_dram_si/outputs_large/paper2/dram_N10k/latest/`

配置要点（与 100k 基线一致）：
- Strict GAS：`gas_enable=1, gas_strict_mode=1, gas_window_auto=1, gas_window_cycles={200,40,40}`，`apply_acc_enable=1`。
- 窗口读：`window_read_enable=1, read_force_single=1, merge_read_cacheline=1, window_read_budget=4194304`。
- 并发：`max_outstanding_requests=32768, gas_max_inflight_reads=65536`。
- 权重：`weight_format=raw, per_core_files=1, index_mode=bcsr_post_row`，BCSR 参数按各自 meta 回填。

## 2025-11-05 更新：严格 GAS 统计统一与汇总器升级（单PE）

本轮聚焦“统计口径统一、低开销、可复现”。核心改动与现状如下。

### 1) 统计口径统一（唯一来源）
- 每窗发放（权威）：统一以 PE 级聚合文件 `pe_window_spikes_db.csv` 为准（EndScatter 单入口聚合）。
- 总发放次数：由上述每窗求和得到，作为 `total_neurons_fired` 唯一来源。
- 运行期平均速率（Hz/neur）：`total_neurons_fired / (N * Tsec)`，仅用于跨场景横比，非“每窗概率”。
- 去重发放率：`unique_neurons_fired_total / N`，来自 MultiCorePE 的单一累计器（首次发放置位上报）。
- stage_events（Begin*/End*）：定位调试时序用，不再作为总量口径。

对应代码/脚本改动：
- MultiCorePE：`accumulateApplyScatterStats()` 不再对 `total_neurons_fired` 加数；仅由 `accumulateWindowSpikes()`（EndScatter）聚合。（已安装）
- SnnPESubComponent：
  - 引入 `fired_this_window_`（每窗门控：同一窗同一神经元最多发一次）。
  - 引入 `fired_ever_`（去重位图，首次发放上报 PE 的 `unique_neurons_fired_total`）。
- 汇总脚本：`sst_dram_si/tools/compute_essential_summary_singlepe.py`
  - 新增 `window_firing` 段（优先读取 `pe_window_spikes_db.csv`，回退 stage_events）。
  - `total_neurons_fired` 以 PE 窗口和覆盖；派生 `run_avg_fr_hz_per_neuron`。
  - 统一单位：`Hz/neur`、`fraction`、`ns`、`MiB/s`。

### 2) 运行与产物（复现说明）
- 配置：`sst_dram_si/outputs_large/paper2/dram_N1k/local_run_config.json`
  - 严格 GAS：`gas_window_mode=1, apply_acc_enable=1, defer_issue_until_apply=1`
  - 后端：`mem_backend=ramulator2`（DDR4 cfg：memHierarchy/tests/ramulator2-ddr4.cfg）
  - 统计（实例级）：脚本为 MultiCorePE 启用了 `total_neurons_fired`、`unique_neurons_fired_total`（Accumulator）与必要直方图。
- 运行：
  ```bash
  /home/xgy/remote/sst_install/bin/sst -n 8 sst_dram_si/test_dram_si_single_pe.py
  python3 sst_dram_si/tools/compute_essential_summary_singlepe.py \
    --run-dir sst_dram_si/outputs_large/paper2/dram_N1k
  ```
- 关键产物（最新）：
  - `.../stage_events_db_100us.csv`（调试用，体量大，不作为聚合来源）
  - `.../pe_window_spikes_db.csv`（权威每窗聚合）
  - `.../dram_si_stats.csv`（SST CSV）
  - `.../essential_summary.json`（汇总：window_firing/spike_activity/memory/wallclock）

### 3) 最新结果快照（N=1k，100us，ramulator2）
- window_firing（来源：PE聚合）：
  - `windows_total=8, windows_active=8, windows_active_frac=1.0`
  - `spikes_per_window_avg_active=55.625`（占比 `~5.5625%/窗/千神经元`）
- spike_activity：
  - `total_neurons_fired=445`（=PE 每窗求和）
  - `run_avg_fr_hz_per_neuron=4450.0`（运行期平均速率）
  - `unique_neurons_fired_total`：本轮为 0（见下文“注意”）
- memory：
  - `memory_requests≈1.4K`，`dram_bytes_read≈83.2KiB`（本轮负载较轻；压测需提高 fanout/时间）

### 4) 注意与解释
- unique 口径为 0：统计通路唯一且正确，但当前配置（阈值较高/事件分布集中）导致重复发放集中在同一小批神经元；降低阈值或增加事件密度后会出现非零。
- stage_events 体量大：多核并发写入造成大量 0ns Begin*，仅用于时序调试；聚合请使用 `pe_window_spikes_db.csv`。
- 带宽单位：`approx_read_bandwidth_mib_per_s` 是发起侧估算（issue bandwidth），若需真实 DRAM 统计，优先使用 `gas_unique_bytes_total`（已自动解析优先）。

### 5) 清理与结构
- 清理旧产物：已删除 `last_run.*.log` 历史日志与旧 `stage_events_db_*.csv`，保留最新。
- 运行目录：`sst_dram_si/outputs_large/paper2/dram_N1k/`，仅保留必要产物与配置。

### 6) TODO / 下一步
1. unique 覆盖度验证：降低 `v_thresh` 或提升 `event_weight/fanout`，使 `unique_neurons_fired_total > 0`，并在 `essential_summary.json` 中输出 `unique_firing_fraction`。
2. stage_events 收敛：考虑仅由 PE 在 EndScatter 写一行（按窗），或保留核心写但在工具中按 seq 合并求和。
3. 带宽压测：延长 `sim_time` / 增强负载，观察 `gas_unique_bytes_total` 与延迟直方图的变化。
4. 多PE推广：将本轮“唯一口径 + 单入口聚合”策略推广到多PE脚本与工具，保证一致性。

## 2025-11-05 补记：1k@100us（simpleMem 后端）验证与 essential_summary 落地

背景：为规避 ramulator2 在高并发严格 GAS 场景下的 ReadResp 缺失问题，采用 simpleMem 后端做 1k@100us 的功能与统计闭环验证，并将结果固化到父目录的 summary。

- 本次配置（均已写入运行快照与有效快照）
  - 脚本：`sst_dram_si/test_dram_si_single_pe.py`
  - 配置：`sst_dram_si/local_run_config.json`（运行时复制到时间戳 RUN_DIR 并生成 `local_run_config.effective.json`）
  - 模型：20 核 × 50 神经元/核 = 1000；`sim_time=100us`
  - 后端：`mem_backend=simple`
  - GAS：window_auto=1；窗口 200/40/40 ns；`window_read_enable=1`；`window_read_budget=512`
  - 诊断：默认关闭（`core_verbose=0, read_force_single=0, disable_weight_cache=0`）

- 运行与汇总
  - 运行：`/home/xgy/remote/sst_install/bin/sst -n 8 sst_dram_si/test_dram_si_single_pe.py`
  - 汇总：`python3 sst_dram_si/tools/compute_essential_summary_singlepe.py --run-dir sst_dram_si/outputs_large/paper2/dram_N1k`
  - 产物：
    - 时间戳目录：`sst_dram_si/outputs_large/paper2/dram_N1k/20251105-141538/essential_summary.json`
    - 最新汇总（已拷贝到父目录）：`sst_dram_si/outputs_large/paper2/dram_N1k/essential_summary.json`

- 关键结果（来自 essential_summary.json）
  - memory：`memory_requests=1301`；`dram_bytes_read=5,204,000 bytes`（≈4.963 MiB）；`approx_read_bandwidth_mib_per_s≈49629.211`
  - gas_superstep_cycles（ns）：windows=358；avg/p95/p99：g=198/200/200，a=39/40/40，s=39/40/40，总=278/280/280；`sim_time_ns_observed=99960`
  - sim：`gas_windows_total=358`；配置与观测时长一致；`sim_cycles_total_config=100000`

- 结论
  - simpleMem 后端下，严格 GAS 的读/写与统计闭环均正常；窗口节奏稳定；summary 字段完整。
  - 与 ramulator2 的对比试验表明，高并发/短窗口（200/40/40）下 ramulator2 的 ReadResp 可能无法及时返还，导致 granule 长时间 NOT ready；后续需对 ramulator2 做并发与窗口参数的 A/B 调优验证。

- 后续建议（针对 ramulator2）
  1) 提高 `max_inflight_reads`（如 1024）并增大 `window_cycles_apply`（如 200→400ns），保守降低 `window_read_budget`（如 64/128）后再测 1k@100us。
  2) 若仍异常，用 simpleMem 与 ramulator2 同步跑小规模（4×10）和中规模（10×20），对比 ReadResp 与 `gas_reads_issued` 差异。

## 2025-11-05 补记：小规模严格 GAS 复现（4×10，5us）

- 目的：验证“严格 GAS + 纯内存权重”的完整闭环在小规模可用。
- 配置：4 核 × 10 神经元/核；`sim_time=5us`；`mem_backend=simple`；`window_read_enable=1`；其余诊断开关按需开启（小跑可用 `core_verbose=2, read_force_single=1, disable_weight_cache=1`）。
- 结果：
  - `stage_events_db.csv` 出现非零 EndScatter（例如 `seq=3, spikes_emitted=8`）。
  - `dram_si_stats.csv` 中 `total_neurons_fired`、`unique_neurons_fired_total`、`mem_req_size_bytes` 等指标落地；请求数按诊断路径与合并策略增加。


## 目前状态（已完成）
- 创建最小可复现实验脚本（单PE、无网络）：`sst_dram_si/test_dram_si_single_pe.py`
  - 复用模版内存栈：每核 L1 -> 本地 Bus -> 共享 L2 -> MemController。
  - 权重通过 `SnnDL.WeightLoader` 写入内存（默认填充值，支持文件模式）。
  - 统计输出可通过 `local_run_config.json` 指定 CSV 路径。
- 参数化运行配置：`sst_dram_si/local_run_config.json`
  - 支持 L1/L2 容量/行大小、MemCtrl/Loader 参数、核数/每核神经元、统计级别与 CSV 路径等。
- 接入 Ramulator2 后端
  - 重新配置并安装 `memHierarchy`，启用 `memHierarchy.ramulator2`（`--with-ramulator2=/home/anarchy/SST/externals/ramulator2`）。
  - DDR4 示例配置验证通过：`memHierarchy/tests/ramulator2-ddr4.cfg`。
- 新增 HBM2 配置样例并跑通
  - 配置文件：`sst_dram_si/configs/ramulator2_hbm2.cfg`
    - `DRAM.impl: HBM2`，`org.preset: HBM2_4Gb`，`timing.preset: HBM2_2Gbps`。
    - `Controller.{Scheduler: FRFCFS, RefreshManager: AllBank, RowPolicy: OpenRowPolicy}`。
    - `AddrMapper: ChRaBaRoCo`。
  - 避免了 rank 相关假设导致的异常（HBM2 无 rank 层级，ClosedRowPolicy 会触发 out_of_range）。
  - 运行输出包含通道级延迟、队列与行命中统计（stdout），示例：`avg_read_latency_0`、`row_hits_0` 等。
- 统计目录
  - 新建统一目录：`sst_dram_si/stats/`
  - HBM2 运行示例将统计落盘为：`sst_dram_si/stats/hbm2_stats.csv`

### 新增：HBM2 直方图验证（Batch‑A 完整验证）
- 将 HBM2 运行时长提升至 `1ms`，以收集更丰富的样本：`sst_dram_si/local_run_config_hbm2.json` 中 `sim_time: 1ms`。
- 使用 `local_run_config_hbm2.json` 作为 `local_run_config.json` 后运行：
  ```bash
  cp sst_dram_si/local_run_config_hbm2.json sst_dram_si/local_run_config.json
  mkdir -p sst_dram_si/logs && sst sst_dram_si/test_dram_si_single_pe.py | tee sst_dram_si/logs/hbm2_run.log
  ```
- 验证产物（均为 Histogram 行，已聚合到父组件 MultiCorePE 实例）：
  - `multicore_pe_0,mem_read_latency_cycles,...`
  - `multicore_pe_0,mem_read_latency_cycles_weights,...`
  - `multicore_pe_0,mem_read_latency_cycles_state,...`
  - `multicore_pe_0,mem_req_size_bytes,...`
  - `multicore_pe_0,mem_outstanding_at_issue,...`
  - 另：`pe0_l2,MSHR_occupancy,...` 与各 `pe0_core*_l1,MSHR_occupancy,...` 直方图已落盘。
- 运行日志中可见 Ramulator2 汇总：`total_num_read_requests: 13`、`avg_read_latency_0`、`row_hits_0/row_misses_0/row_conflicts_0` 等，路径：`sst_dram_si/logs/hbm2_run.log`。

## 文件与路径
- 脚本：`sst_dram_si/test_dram_si_single_pe.py`
- 配置（默认）：`sst_dram_si/local_run_config.json`
- HBM2 配置示例：`sst_dram_si/configs/ramulator2_hbm2.cfg`
- HBM2 运行配置（示例）：`sst_dram_si/local_run_config_hbm2.json`
- 输出目录规范（已采纳“方案2：细粒度分层”）：
  - 统计按“后端/窗口/配置指纹”分层：
    - `sst_dram_si/stats/<backend>/<window>/c<cores>_n<neur/core>_l<line>_l1_<kib>_l2_<kib>/hist.csv`
      - 示例（HBM2, 1ms）：`sst_dram_si/stats/hbm2/1ms/c4_n4_l64_l1_16KiB_l2_128KiB/hist.csv`
      - 示例（DDR4, 1ms）：`sst_dram_si/stats/ddr4/1ms/c4_n4_l64_l1_16KiB_l2_128KiB/hist.csv`
  - Ramulator2 原始日志与解析产物同层放置：
    - 原始：`.../ramu_raw.log`；解析：`.../ramu_parsed.csv`
  - 当配置中的 `stats_csv` 为绝对路径且不在 `sst_dram_si` 内时，脚本会将其重定向到 `sst_dram_si/<basename>`，确保产物归档在本目录。

## 统计开关与参数总览（当前）
- 全局统计与输出
  - `sst.setStatisticLoadLevel(7)`；可由 `local_run_config.json` 的 `stats_verbose` 覆盖
  - 输出：`sst.statOutputCSV`；文件路径由脚本设置，可通过 `local_run_config.json.stats_csv` 覆盖（相对路径按“后端/窗口/配置指纹”分层）

- 类型级（ComponentType）启用
  - `memHierarchy.Cache`：`sst.AccumulatorStatistic`（全量计数）
  - `memHierarchy.MemController`：`sst.AccumulatorStatistic`
  - `SnnDL.MultiCorePE`：`sst.AccumulatorStatistic`
  - `SnnDL.SnnPESubComponent`：`sst.AccumulatorStatistic`（不启用直方图，受CSV注册时机限制）
  - `SnnDL.WeightLoader`：`sst.AccumulatorStatistic`

- 实例级（Component 实例）启用
  - MultiCorePE 基本计数类统计（脚本实例级开启）：
    - `external_spikes_sent`, `external_spikes_received`, `total_spikes_processed`, `inter_core_messages`, `memory_requests`, `avg_core_utilization`, `total_neurons_fired`
  - MultiCorePE 直方图（父组件聚合；脚本实例级开启，Histogram 配置见括号）：
    - `mem_read_latency_cycles`（min=0, binwidth=4, numbins=128）
    - `mem_read_latency_cycles_weights`（同上）
    - `mem_read_latency_cycles_state`（同上）
    - `mem_req_size_bytes`（min=0, binwidth=64, numbins=32）
    - `mem_outstanding_at_issue`（min=0, binwidth=1, numbins=64）
  - Cache 直方图（实例级开启，L2 + 各 L1）：
    - `MSHR_occupancy`（min=0, binwidth=1, numbins=64）
  - WeightLoader 画像（实例级开启）：
    - 累计量（Accumulator）：`weight_bytes_written_total`, `weight_write_chunks_total`, `weight_write_total_cycles`
    - 直方图（Histogram）：`weight_write_chunk_bytes`（min=0, binwidth=64, numbins=32）, `weight_write_latency_cycles`（min=0, binwidth=64, numbins=32；仅 timed 写入有效）

- 关键运行开关与参数
  - `local_run_config.json`/`local_run_config_hbm2.json`：
    - `sim_time`: `1ms`（推荐窗口）
    - `stats_csv`: `stats/<backend>/<window>/c<cores>_n<neur/core>_l<line>_l1_<kib>_l2_<kib>/hist.csv`
    - `ramulator2_config_file`: DDR4 使用 `.../memHierarchy/tests/ramulator2-ddr4.cfg`；HBM2 使用 `sst_dram_si/configs/ramulator2_hbm2.cfg`
    - 负载相关：`neurons_per_core=16`，`loop_dataset=true`（用于更重读负载）；`start_time_us=2.0`
    - 缓存/行大小：`l1_size=16KiB`，`l1_assoc=8`，`line_size_bytes=64`，`l2_size=128KiB`，`l2_assoc=8`
    - Loader：`loader_chunk_bytes=128`，`loader_fill_value=0.25`，`per_node_stride=32768`
  - WeightLoader（组件内部参数，当前默认）：
    - `timed_seed_enable=1`（启用运行时种子写入机制）
    - `timed_seed_allow_cache=0`（默认不经过缓存执行 timed 写入，因此回退为 untimed 写入；若设为 `1` 则启用写入时延与总耗时统计）
    - `timed_seed_count=1`（每核计时写入块数）

- 已知限制与说明
  - SubComponent（SnnPESubComponent）直方图受 CSV 注册时机限制，当前通过父组件（MultiCorePE）聚合直方图验证落盘
  - `weight_write_latency_cycles` 与 `weight_write_total_cycles` 默认为 0（untimed），需将 WeightLoader 的 `timed_seed_allow_cache` 设为 `1` 才会产生非零数据


## 如何运行
```bash
# 使用默认配置（DDR4 示例）
sst sst_dram_si/test_dram_si_single_pe.py

# 切换为 HBM2 配置（可覆盖默认配置文件）
cp sst_dram_si/local_run_config_hbm2.json sst_dram_si/local_run_config.json
sst sst_dram_si/test_dram_si_single_pe.py
```
产物：`stats/<backend>/<window>/c<...>/hist.csv`（包含 MultiCorePE/L1/L2 直方图），并在同层 `ramu_raw.log` 保存 Ramulator2 汇总，后续解析生成 `ramu_parsed.csv`。

## 新增：外部 BCSR 权重文件（不改 Loader 逻辑）
- 目标：不在 Loader 中引入新逻辑，改为离线生成 BCSR 原始权重文件，使用 WeightLoader(raw, per_core_files) 写入内存；SnnPESubComponent 走现有 BCSR 读路径
- 生成脚本：`sst_dram_si/tools/generate_bcsr.py`
  - 用法（示例，64x64，全PE矩阵，每核一份相同文件）：
    ```bash
    python3 sst_dram_si/tools/generate_bcsr.py \
      --rows 64 --cols 64 --br 4 --bc 4 --cores 4 \
      --pattern diag --val 0.25 \
      --out sst_dram_si/weights/bcsr_core{core}.raw
    ```
    输出偏移（字节）：`rowptr=0, colidx=68, blockdata=100`
- 配置（HBM2 1ms 示例，已启用）见：`sst_dram_si/local_run_config.json`
  - Loader（raw）：
    - `weight_format: raw`, `per_core_files: true`, `file_template: sst_dram_si/weights/bcsr_core{core}.raw`, `validate_length: false`
  - SnnPESubComponent（BCSR）：
    - `index_mode: bcsr_post_row`
    - `bcsr_block_rows: 4`, `bcsr_block_cols: 4`, `bcsr_val_bytes: 4`, `bcsr_idx_bytes: 2`
    - `bcsr_rowptr_offset: 0`, `bcsr_colidx_offset: 68`, `bcsr_blockdata_offset: 100`
    - `bcsr_prefetch_all: false`（先关闭行级预取以规避大批量并发）
- 运行：
  ```bash
  sst sst_dram_si/test_dram_si_single_pe.py | tee sst_dram_si/logs/hbm2_bcsr_1ms.log
  ```
- 验证：HBM2 1ms 可正常完成（Ramulator2 报告 `num_read_reqs` ≈ 7，取决于触发路径）

## 新增：批次A（父组件聚合 + 实例级直方图）
- 父组件（MultiCorePE）新增组件级直方图统计，并在构造期注册（满足CSV落盘约束）：
  - `mem_read_latency_cycles`、`mem_read_latency_cycles_weights`、`mem_read_latency_cycles_state`
  - `mem_req_size_bytes`、`mem_outstanding_at_issue`
- 子组件（SnnPESubComponent）在关键路径埋点并聚合到父组件：
  - 发起时：请求大小、发起时并发（dense/BCSR 均覆盖）
  - 回包时：端到端读延迟（按权重/非权重分组）
- 脚本侧（实例级启用）：
  - 对 `multicore_pe_0` 启用上述直方图（HistogramStatistic），binwidth/桶数：延迟=4cycles×128，大小=64B×32，并发=1×64
  - 对 `memHierarchy.Cache` 启用 `MSHR_occupancy` 直方图（类型级），验证 L2 已落盘
- 验证（默认DDR4配置）：
  - `sst_dram_si/stats/dram_si_stats.csv` 中出现：
    - `multicore_pe_0,mem_read_latency_cycles,... Histogram ...`
    - `multicore_pe_0,mem_req_size_bytes,... Histogram ...`
    - `multicore_pe_0,mem_outstanding_at_issue,... Histogram ...`
  - L2：`pe0_l2,MSHR_occupancy,... Histogram ...`（已落盘）

> 注：为确保直方图采样更充分，推荐将 `sim_time` 提升至 `1ms` 或更长，或增大触发读的负载强度。

## 指标扩展计划（针对新访存方式评估）
优先级从高到低，分三批次推进。

### 批次A（轻改即可上）
- L1/L2：将 `MSHR_occupancy` 切换为直方图输出，观察并行 miss 深度分布；`Bank_conflicts` 作为累计计数。
- Snn 核心（SnnPESubComponent）新增核心级统计：
  - `mem_read_latency_cycles`（直方图）：端到端读延迟（StandardMem 回调周期 - 发起周期）。
  - `mem_req_size_bytes`（直方图）：单次请求字节大小分布（合并/突发效果）。
  - `mem_outstanding_at_issue`（直方图）：发起时刻并发请求数（MLP）。
  - 区域分组：按地址区间拆分权重区/状态区的上述统计，用于策略对照。
- Ramulator2 日志归档与解析：将 stdout tee 至 `stats/ramu_hbm2.log`，提供解析脚本生成 `stats/ramu_hbm2_parsed.csv`。

### 批次B（中等工作量）
- WeightLoader 画像：
  - `weight_bytes_written`、`weight_write_chunks`（直方图）、`weight_write_total_cycles`（总耗时）。
  - 用于对比“预置写/按需写”策略对 DRAM 的影响。
- 时间窗口化：
  - 以固定窗口（如 20us）输出 A 批次指标的分段统计，观察稳态/预热与策略切换效果。

### 批次C（后端补丁）
- `memHierarchy.ramulator2` 后端统计化（SST CSV）：
  - `backend_issue_reads/writes/rejects`、`backend_read_latency_cycles`（直方图）、`backend_queue_depth`（直方图）、`backend_ticks`。
  - 消除对 stdout 的依赖，便于与 L1/L2/Snn 指标统一聚合分析。

## 风险与规避
- HBM2 层级差异：避免使用依赖 rank 的行策略；当前采用 OpenRowPolicy + AllBank 无异常。
- 统计量开销：直方图桶数控制在合理范围，避免过多统计写 I/O 影响仿真时间。

## 待办（滚动维护）
- [x] 批次A（实现中）：
  - [x] Snn 核心：在 SnnPESubComponent 内埋点端到端读延迟（cycles）、请求大小（bytes）、发起时并发数（MLP）与权重/状态分区分类（dense/BCSR）。当前通过内部计数与可选统计指针记录，保证兼容性。
  - [x] L1/L2：脚本侧为 `memHierarchy.Cache` 启用 `MSHR_occupancy` 直方图（HistogramStatistic）。
  - [ ] 将上述直方图指标稳定输出到 CSV（SST 约束：SubComponent 在 init 阶段后创建会导致 CSV Output 限制，需选择合适的注册时机或改为组件级汇总/单独文件输出）。
- [ ] Ramulator2 日志解析脚本与 CSV 化。
- [ ] 批次B：WeightLoader 写入统计；时间窗口化实现。
- [ ] 批次C：Ramulator2 后端统计化（C++补丁与重编）。

### 本次更新要点
- 代码：
  - `SnnPESubComponent`：
    - 记录发起时请求大小、并发度（在 `issueReadCommon_` 与 BCSR发起处）；
    - 记录端到端读延迟并按权重/非权重分区分类（在 `handleMemoryResponse`）。
    - 使用 `bcsr_kind` 与 dense 地址段（`[base_addr_, base_addr_ + rows*cols*4)`）识别权重访问。
  - `test_dram_si_single_pe.py`：
    - 为 L1/L2 启用 `MSHR_occupancy` 直方图；
    - 预留了 Snn 核心直方图类型配置，但由于 CSV 注册时机限制暂不启用。
- 兼容性：保持原有功能稳定（HBM2/DDR4 均可运行）。

### 本次推进（2025‑10‑18）
- HBM2 路径直方图验证完成（父组件聚合 + 实例级 Histogram 启用，已落盘到 `stats/hbm2_stats.csv`）。
- DDR4 对比运行窗口统一到 `1ms`（便于与 HBM2 直接对比）：
  - 覆盖 `local_run_config.json` 为 DDR4 1ms（不覆盖 `ramulator2_config_file` 时脚本默认指向 DDR4；当前为显式指向）：
    ```json
    {
      "sim_time": "1ms",
      "stats_verbose": 7,
      "ramulator2_config_file": "/home/anarchy/SST/sst_workspace/sst-elements/src/sst/elements/memHierarchy/tests/ramulator2-ddr4.cfg",
      "stats_csv": "stats/ddr4_stats.csv"
    }
    ```
  - 运行：`sst sst_dram_si/test_dram_si_single_pe.py | tee sst_dram_si/logs/ddr4_run_1ms.log`
  - 产物：`sst_dram_si/stats/ddr4_stats.csv`，包含与 HBM2 路径一致的直方图条目（MultiCorePE 与 L1/L2）。
- 保存 Ramulator2 运行摘要到 `sst_dram_si/logs/hbm2_run.log` 与 `sst_dram_si/logs/ddr4_run_1ms.log`（后续用于解析脚本）。

新增：Ramulator2 日志解析与重载验证（本次完成）
- 解析并生成：
  - `sst_dram_si/stats/ramu_hbm2_parsed.csv`（来源：`logs/hbm2_run.log`）
  - `sst_dram_si/stats/ramu_ddr4_parsed.csv`（来源：`logs/ddr4_run_1ms.log`）
  - 字段：`backend,total_num_read_requests,memory_system_cycles,avg_read_latency_0,row_hits_0,row_misses_0,row_conflicts_0`
- 更重读负载设置（用于分布稳定性验证）：
  - 将 `neurons_per_core` 提升至 `16` 且开启 `loop_dataset=true`
  - DDR4 产物：`stats/ddr4/1ms/c4_n16_l64_l1_16KiB_l2_128KiB/hist.csv`（同层 `ramu_raw.log`）
  - HBM2 产物：`stats/hbm2/1ms/c4_n16_l64_l1_16KiB_l2_128KiB/hist.csv`（同层 `ramu_raw.log`）
  - 观察：在 1ms 窗口与当前数据集下，`total_num_read_requests` 仍为 13（受数据集长度与合并策略影响）；如需显著增加样本，建议延长仿真时间（如 5ms）或进一步加重前端事件强度。

新增：WeightLoader 写入画像（Batch‑B 第一项，已实现）
- 组件：`SnnDL.WeightLoader` 新增统计并在构造期注册（满足 CSV 注册要求）
- 累计量（Accumulator）：
  - `weight_bytes_written_total`（总写入字节）
  - `weight_write_chunks_total`（总写入块数）
  - `weight_write_total_cycles`（本次写入总耗时，仅 timed 模式，上报一次）
- 直方图（Histogram）：
  - `weight_write_chunk_bytes`（单次写入字节分布；bin=64B×32）
  - `weight_write_latency_cycles`（写入时延分布，仅 timed 模式）
- 启用方式（脚本已默认开启并落入当前 hist.csv）：
  - 在 `test_dram_si_single_pe.py` 中对 `pe0_weight_loader` 启用直方图与累计量；输出与其他统计共用同一 CSV。
- 路径示例：
  - DDR4（1ms, n=16, loop）：`stats/ddr4/1ms/c4_n16_l64_l1_16KiB_l2_128KiB/hist.csv`
  - HBM2（1ms, n=16, loop）：`stats/hbm2/1ms/c4_n16_l64_l1_16KiB_l2_128KiB/hist.csv`
  - 行首标识：`pe0_weight_loader,weight_write_*`

新增：MultiCorePE 时间窗口化统计（Batch‑B 第二项，已实现）
- 目标：对 A 批核心指标按固定窗口聚合，观察稳态/预热与阶段性行为
- 组件：`SnnDL.MultiCorePE` 内部聚合（默认关闭）
- 参数（新增，默认关闭）：
  - `window_stats_enable`：是否启用窗口化统计（0/1）
  - `window_us`：窗口长度（微秒，默认 20）
  - `window_csv`：输出 CSV 路径（为空则不输出；脚本会默认放在同层 `windowed/windows_<N>us.csv`）
- 窗口内聚合字段：
  - read_count（响应计数）
  - avg_read_latency_cycles（窗口内端到端读延迟均值）
  - issue_count（发起计数）
  - avg_req_size_bytes（请求大小均值）
  - avg_outstanding（发起时并发度均值）
- 输出示例（HBM2, 1ms, n=16, loop）：
  - 路径：`stats/hbm2/1ms/c4_n16_l64_l1_16KiB_l2_128KiB/windowed/windows_20us.csv`
  - 表头：`window_start_us,window_end_us,read_count,avg_read_latency_cycles,issue_count,avg_req_size_bytes,avg_outstanding`
  - 注：窗口时间基于组件注册时钟（1GHz -> 1ns/tick），内部按 ns 对齐；`window_us` 会换算为 `window_ns=window_us*1000`

### 已知限制与下一步
- SubComponent 统计以 CSV 输出存在“注册时机”限制（SST 要求 CSV 输出的统计在 wiring 之前注册），现已通过“父组件聚合+实例级启用”规避并验证落盘。
- 后续仍需：扩大仿真窗口或负载以增加样本，补充HBM2配置下的直方图验证。

后续计划（短期）：
- [x] DDR4 路径也将 `sim_time` 提升至 `1ms` 以便对比；或引入更重的读负载（例如增大 `neurons_per_core` 或循环数据集）。
- [x] 解析 `hbm2_run.log`/`ddr4_run_1ms.log` 中的 Ramulator2 指标，生成 `stats/ramu_hbm2_parsed.csv` 与 `stats/ramu_ddr4_parsed.csv`（批次A收尾）。
- [ ] 若需增样本：延长仿真窗口至 `>=5ms` 或增加/循环数据集以提高请求数量；随后更新对齐分析。
- [ ]（Batch‑B 下一项）MultiCorePE 时间窗口化统计（窗口均值/计数输出到 `windowed/windows_<N>us.csv`）。
  已完成：窗口化统计实现与验证（HBM2 1ms）；下一步可补 DDR4 同步验证。

---
更新人：Codex（SST-DRAM-SI）
更新时间：$(date +%F' '%T)
## 2025-10-22 GAS Iter‑A（细粒度合并 + bank_row 基础设施）

- What changed（代码改动）
  - GatherBufferIF：实现“细粒度合并（k/Lmax）”与 `bank_row` 排序/分桶，并稳定将 GAS 真实字节写入 CSV。
    - 新参数（均可从脚本透传）：
      - `gap_merge_enable`（0/1；默认 1）、`gap_merge_k_bytes`（k 阈值，默认 2048 B）、`burst_bytes_max`（Lmax，默认 65536 B）
      - `sort_policy=addr|row|bank_row`（默认 row）
      - `bank_bits`、`bank_shift`（bank 提取位；默认 0 禁用 bank_row）
    - 新统计：`gas_gap_absorbed_bytes`（细合并吸收的空洞字节总量，Accumulator）。
    - 行为要点：Gather 阶段暂存上游读；进入 Apply 前按 `(bank,row)` 分桶、排序并按 k/Lmax 规则合并成动态 granule；Apply 阶段按策略排序下发；响应从 SRAM 生成。
  - MultiCorePE：已持久写入 GAS 汇总统计（真实字节/事务）：
    - `gas_unique_bytes_total`、`gas_unique_reads_total`（Accumulator）。
  - 清理与回退：Apply 结束清理 `staging_reads_/granules_/required_set_`；k/Lmax 无效时自动关闭细合并；所有新增均可通过参数关停（保持旧语义）。

- Affected files
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.h/.cc`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.h/.cc`（统计汇总路径此前已落）
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/MultiCorePE.h/.cc`（GAS 汇总统计此前已落）
  - `sst_dram_si/test_dram_si_single_pe.py`（新增参数透传与统计启用）

- 参数与默认值（脚本已透传）
  - `gap_merge_enable=1`、`gap_merge_k_bytes=2048`、`burst_bytes_max=65536`
  - `sort_policy=row`（可设为 `bank_row`）
  - `bank_bits=0`、`bank_shift=0`（0 表示禁用 bank_row）

- 如何运行（100us 验证，稳定 CSV）
  1) GAS（默认 row 排序，细合并开启）：
     - `local_run_config.json` 关键项：
       - `"sim_time":"100us", "gas_enable":true, "scheme1_enable":false`
       - `"gap_merge_enable": true, "gap_merge_k_bytes": 2048, "burst_bytes_max": 65536`
       - 可选：`"gas_sort_policy":"row"`（或 `"bank_row"`，需同时提供 `bank_bits/bank_shift`）
       - 建议给出绝对 `stats_csv` 路径，例如：`"stats_csv": "/home/xgy/remote/sst_dram_si/stats/gas_100us_iterA.csv"`
     - 运行：
       - `./sst sst_dram_si/test_dram_si_single_pe.py > sst_output_data/run_gas_100us_iterA.log 2>&1`
     - 观察 CSV（真实字节与统计）：
       - `multicore_pe_0,gas_unique_bytes_total,,Accumulator,...`
       - `multicore_pe_0,gas_unique_reads_total,,Accumulator,...`
       - `multicore_pe_0,gas_gap_absorbed_bytes,,Accumulator,...`
       - `multicore_pe_0,mem_req_size_bytes,,Histogram,...`（用于基线对比）

- 正确性自检（不做调优，仅验证口径）
  - granule 不跨 bank/row；Apply 结束后 `staging_reads_/granules_/required_set_` 均清空。
  - `gas_unique_bytes_total` 与 `gas_unique_reads_total` 持续写入 CSV，记录真实突发字节与笔数。
  - `gas_gap_absorbed_bytes` 仅在空洞被合并吸收时累加；`gas_req_coalesce_size_bytes` 直方图可看到突发长度分布。
  - 控制器日志仍用于行命中/事务/时延：`row_hits/misses/conflicts`, `num_read_reqs_0`, `avg_read_latency_0`。

- bank_row（基础支持，默认禁用）
  - 启用：`"gas_sort_policy":"bank_row"`，并提供 `bank_bits`、`bank_shift`（若未知可暂置 0 保守禁用）。
  - 注意：默认映射使用 `RoBaRaCoCh` 且 Frontend 有 RandomTranslation，bank 位需按映射位表精准配置；当前阶段不做参数扫参，仅保留接口与保守默认。

- 回退说明
  - 关闭细合并：`gap_merge_enable=0`（恢复整行/CL 行为）。
  - 排序退化：`gas_sort_policy=row` 或 `addr`。
  - 参数无效（k=0 或 Lmax=0）时，细合并自动关闭。

- 样例结果（样本环境，非调优）
  - 100us（GAS，row 排序，k=2KB/Lmax=64KB）：
    - `gas_unique_reads_total≈132`，`gas_unique_bytes_total≈0.099 MiB`，`num_read_reqs_0≈5.9K`，`row_hits≈16`。
  - 2ms（GAS，旧排序；用于对比）：
    - `gas_unique_bytes_total≈2.57 MiB`，`num_read_reqs_0≈5,989`，`row_hits≈7`。
  - 说明：本阶段只完成基础设施与口径对齐，暂不做 bank 映射/阈值的调优。

## 2025-10-22 GAS Iter‑B（行窗口 row-window：按 bank,row 累计与阈值触发｜增量实现）

- What changed（行为与接口）
  - 在 GatherBufferIF 的 Apply 入口构建 granule 时，新增“行窗口（coarse）合并”路径：
    - 分桶：按 `(bank,row)`（当 `bank_bits=0` 时退化为仅 row）。
    - 排序：组内按地址（可配 `sort_policy=bank_row|row|addr`）。
    - 规则：在“细粒度合并（gap≤k 且 new_len≤Lmax）”之外，若开启 `row_window_enable=1`，则：
      1) Bytes 阈值：若当前段内累积的子读之和 `sum_bytes + size <= row_window_bytes` 且 `new_len <= burst_bytes_max`，则允许跨大 gap 合并；并记 `gas_row_window_*` 统计。
      2) Timeout 阈值：若首个子读到达时间与当前读相差 `>= row_window_timeout_ns`，则先将当前段按“行窗口触发”方式封口，再开启新段（不影响旧行为，默认超时为 0 关闭）。
  - 统计（ELI 注册，默认启用 Accumulator）：
    - `gas_row_window_triggers`：被 row-window 机制触发/标记的突发次数。
    - `gas_row_window_bytes`：对应突发的“覆盖字节”（包含空洞），用于估算行激活摊销效果与能耗改善趋势。
  - 兼容性：所有行窗口逻辑默认关闭（`row_window_enable=0`）；开启亦受 `row_window_bytes>0` 与/或 `row_window_timeout_ns>0` 进一步门控，确保不改变既有行为。

- 新参数（默认均为关闭/0）
  - `row_window_enable`（0/1）：使能行窗口逻辑（默认 0）。
  - `row_window_bytes`（uint64）：行窗口字节阈值（按“子读和”），建议 16–64 KiB 量级起步。
  - `row_window_timeout_ns`（uint64）：行窗口超时阈值（ns），用于低活跃度/小流量下的定时触发。

- 实现要点（代码）
  - 路径：`sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.h/.cc`
    - 分组与合并：`buildGranulesWithGapMerge_()` 中新增 `ReadItem.arr_ns`，并在合并循环内应用 bytes/timeout 两类触发；段封口时按是否使用了 row-window 合并进行统计标记。
    - 到达时间记录：Gather 阶段暂存上游读时，将 `staged_arrival_ns_[req_id]=getCurrentSimTimeNano()`；Apply 构建完成后清理该表。
  - 统计口径：`gas_row_window_*` 仅在“确实使用了 row-window 合并”或“因 timeout 被迫封口”时计数与累加；细合并吸收的空洞仍记入 `gas_gap_absorbed_bytes`。

- 如何启用（100us 快测建议）
  - 覆盖 `sst_dram_si/local_run_config.json` 中的 GAS 段：
    ```json
    {
      "gas_enable": true,
      "gas_window_auto": true,
      "gas_sort_policy": "row",
      "gas_row_bytes_guess": 8192,
      "gas_sram_bytes": 262144,
      "gas_max_inflight_reads": 128,
      "gap_merge_enable": true,
      "gap_merge_k_bytes": 2048,
      "burst_bytes_max": 65536,
      "row_window_enable": true,
      "row_window_bytes": 16384,
      "row_window_timeout_ns": 0,
      "sim_time": "100us",
      "stats_csv": "sst_dram_si/stats/gas_iterB_rowwin_100us.csv"
    }
    ```
  - 运行：`./sst sst_dram_si/test_dram_si_single_pe.py | tee sst_output_data/run_gas_100us_iterB_rowwin.log`
  - 观察 CSV：新增 `gas_row_window_triggers/bytes` 行（`multicore_pe_0,...` 聚合）。

- 自检脚本（离线，不跑 SST）
  - 新增：`sst_dram_si/tools/selfcheck_row_window.py`
  - 用法：`python3 sst_dram_si/tools/selfcheck_row_window.py`
  - 覆盖用例：
    - 仅细合并（gap≤k）→ 2 段
    - bytes 合并允许大 gap → 1 段
    - timeout 导致封口 → 2 段
    - bank_row 分桶阻止跨 bank 合并 → 2 段

- 后续计划
  - [ ] bank_bits/bank_shift 自动推断/校验（当前默认 0，保持禁用）。
  - [ ] 行窗口触发更细化的统计（平均突发长度、覆盖/有效字节比）。
  - [ ] 在 2ms/5ms 窗口下与方案1做“每MiB 事务数/时延”派生指标对比（已在前一节提出口径）。
## 2025-10-22 GAS 端到端语义（Phase-1）与自检增强（默认关闭回退）

本次聚焦于方案2（GAS：Gather→Apply→Scatter）的“功能实现对齐”，并补齐可观测性与最小自检能力。默认行为保持与既有配置兼容；所有测试开关默认关闭，仅在快速验证时启用。

已实现（功能面）
- 阶段化控制与屏障
  - GatherBufferIF：支持窗口驱动（window_auto），在进入 Apply 前整理并合并访问；EndApply 仅在 inflight_down 为空时发出，避免跨窗污染。
  - SnnPESubComponent：接收 Begin/End Apply/Scatter 事件，维护 `stage_seq`；在 BeginScatter 端按确定顺序应用累加并触发发放。
- 合并与排序
  - 细粒度合并：gap/Lmax（k=gap_merge_k_bytes，Lmax=burst_bytes_max）；默认启用。
  - 行窗口（粗粒度）骨架与实现：`row_window_enable/bytes/timeout`；默认按配置传递，默认关闭或保守阈值。
  - 排序策略：`sort_policy=row`（已接入）；`bank_row` 路径存在参数但默认禁用（待与 ramulator2 地址映射自动对齐后再启用）。
- SRAM/Scratchpad 与统计
  - GatherBufferIF：容量、并发限制、eviction、tail wait 统计与直方图（已注册，CSV 有输出）。
  - PE 层上卷统计：`gas_unique_reads_total`、`gas_unique_bytes_total`、行窗口触发总量、突发计数/有效载荷等（CSV 中可见）。
- Apply/Scatter 端到端骨架
  - Apply：从 ReadResp 与 cache‑hit 路径对 `post_local` 做 delta 累加（`apply_acc_enable=1`时生效）。
  - Scatter：BeginScatter 时对累加器按 `post` 升序应用，调用阈值判断后发放 spike；统计 `gas_scatter_spikes_emitted_total`。

## 2025-10-23 SB 双缓冲并行（落地）

- 目标：让 Gather(SB i+1) 与 Apply(SB i) 并行；EndApply 仅对 Apply 页 drain，避免阻塞下一页 Gather。
- 代码改动：`SnnDL/GatherBufferIF.h/.cc`
  - 引入 `sb_[2]` 双缓冲状态（granules/required_set/pending/staging/sram_blocks/LRU/inflight 计数），`apply_buf_index_/gather_buf_index_` 指示当前页。
  - Apply 期间允许接收下一页 Gather 的上游读；在 window_auto 下，clockTick 内对下一页进行 gap/Lmax/行窗口合并并按排序策略下发，形成与 Apply 的并行 DMA。
  - EndApply 屏障仅检查 Apply 页在途下行（按页计数）；阶段事件保持 `stage_seq` 并避免跨窗污染；`FlushSRAM` 只清理 Apply 页。
- 新参数：`double_buffer_enable`（默认 1）。
- 限制：`gas_stage_cycles_*` 仍统计主阶段时长，不单独计量“Apply 内并行 Gather”持续时间；可用 inflight 峰值与 `gas_unique_*` 变化侧观并发效果。

## 2025-10-23 活跃度 f 统计与窗口化输出（新增）

- 定义：窗口内活跃度 f = 窗口内出现过的活跃 pre 轴数 / 列宽（`weights_cols`）。其中“活跃 pre”指在窗口内触发过权重读取（dense/BCSR）对应的列索引 `pre_global`。
- 实现位置：
  - 记录活跃 pre：`SnnPESubComponent` 在权重读取发起路径（`post_row_pre_col` 与 `bcsr_post_row`）调用 `recordActivePre_(pre_global)`；
  - 窗口边界：在 GAS 阶段事件 `BeginApply/EndApply/BeginScatter` 上做 `activityFlush_()` 将当前窗口 f 上卷到父组件；
  - 聚合落盘：`MultiCorePE::accumulateActivityF(f)` 写入统计 `gas_activity_f`（Accumulator，PE 级），并将 f 计入时间窗口聚合，最终在窗口 CSV 中输出 `avg_activity_f` 列。
- 脚本启用：在 `sst_dram_si/test_dram_si_single_pe.py` 为 `multicore_pe_0` 显式启用 `gas_activity_f`（与其他 GAS 汇总项一并输出）。
- 窗口 CSV 列更新：
  - 旧：`window_start_us,window_end_us,read_count,avg_read_latency_cycles,issue_count,avg_req_size_bytes,avg_outstanding`
  - 新：追加 `avg_activity_f`（窗口内 f 的平均值）
- 产物与示例：
  - 聚合统计（示例）：`sst_dram_si/stats/ctrl_probe_100us.csv` 中出现 `multicore_pe_0,gas_activity_f,...`
  - 窗口统计（示例）：`sst_dram_si/stats/windowed/windows_20us.csv` 中新增 `avg_activity_f` 列。
- 说明：短窗口与稀疏数据集下 `avg_activity_f` 可能接近 0；建议延长 `sim_time`（如 2ms）或加重负载以获得更显著的非零均值。
- 方案C（调试辅助，默认开启日志，零侵入）
  - 在 BeginScatter 前打印每窗口 Delta 摘要（acc_entries 的 size、HWM、updates/posts 等），定位“是否累加到窗”。

新增/调整的参数（默认值）
- GatherBufferIF：`gap_merge_k_bytes`、`burst_bytes_max`、`row_window_enable/bytes/timeout`、`window_auto`、`max_inflight_reads` 等（保守默认）。
- SnnPESubComponent：
  - `apply_acc_enable=0`（默认关）
  - `readresp_zero_fallback=0`（默认关；仅自检用，将 0 读权重回退为 `init_default_weight` 以便验证累加链路）
  - `stage_events_csv`：可选 CSV 输出（每窗 Begin/End Apply/Scatter 行）

自检脚本与快速验证（100us）
- 目的：在不修改负载数据的前提下，快速观察“窗口累加与发放”为非 0（功能链路验证，不用于性能结论）。
- 做法：
  1) WeightLoader 首周期 timed 写入（timed_seed_enable=1, allow_cache=1），对 16 核各写满 512×512 的 dense 区（值=fill_value=0.25）。
  2) 临时将 `readresp_zero_fallback=1`（仅自检），把 0 读回退为 `init_default_weight=0.5`，确保 Apply 有非零累加；BeginScatter 可看到 spikes 非零。
  3) 运行 100us（8 线程）并检查：
     - 日志：`sst_output_data/run_gas_100us_delta_nonzero_fallback.log`
     - 片段示例：`[GAS][Delta][readresp] ... dv=0.500000 ...`
     - 节点摘要：`NODE0: 脉冲≈500+, 激发≈100+`
     - 阶段 CSV（尾部）：近 1 万行合计 `acc_updates≈149k, posts≈600, spikes≈100+`
- 恢复默认：自检后将 `readresp_zero_fallback` 设回 0（脚本已默认 0）。

运行与配置（当前默认）
- 脚本：`sst_dram_si/test_dram_si_single_pe.py`
  - GAS：`gas_window_auto=1`（窗口驱动），`apply_acc_enable=0`（默认关），`sort_policy=row`，`row_window_enable=0|保守`
  - 线程：`num_threads=8, partitioner=simple`
  - SpikeSource：可循环数据集，分片发放可配置
  - 统计输出：`sst_dram_si/stats/` 下 CSV（PE/GAS/Loader 均已注册 Accumulator/Histogram）

文件与代码热点
- GAS 控制与统计上卷：
  - GatherBufferIF：`SnnDL/GatherBufferIF.h/.cc`（窗口、合并、直方图 + Accumulator）
  - 端到端事件：`SnnDL/GasCustomCmd.h`（Begin/End Apply/Scatter）
- 上层集成与 Apply/Scatter：
  - `SnnDL/SnnPESubComponent.h/.cc`（`apply_acc_enable`、累加器、阶段 CSV、Delta 摘要）
- Baseline 方案1（严格语义）：
  - `scheme1Tick_/scheme1PrefetchSlice_`（每 superstep 仅 1 slice，其他 slice 延后；按 CL 粗粒度扫描，作为对照）
- WeightLoader（可选写入与自检）：
  - `SnnDL/WeightLoader.h/.cc`（bin/csv/raw/BCSR，timed 写入，统计）

默认关闭的自检开关
- `readresp_zero_fallback`：默认 0，仅在“功能链路是否可达”的快速自检中打开；正式实验请保持关闭。

下一步（优先级建议）
1) 行为/正确性
  - 将 Apply 累加的“有效载荷/覆盖字节”上卷到 PE 层（`gas_total_payload_bytes` 等）并对齐 CSV 导出，便于计算合并收益。
  - 修正 BeginScatter 前摘要口径：用 `acc_updates/posts_touched` 代替 `acc_entries size`，避免“map为空但窗口内有更新”的误判。
2) 性能/可观测性
  - bank_row 排序：从 ramulator2 AddrMapper 推断 bank bits/shift（禁用 RandomTranslation），默认先自动对齐再开放参数。
  - 行窗口启用与扫参：`row_window_bytes/timeout` 扫描 100us/2ms/5ms，观察 avg_burst_bytes/row buffer 命中率/平均时延。
  - 字节归一化对比：基线方案1 vs GAS，生成 `reqs/MiB`、`latency/MiB` 等派生指标（已在 tools/ 中有比较脚本雏形）。
3) 算法/实现
  - 累加器页化（Phase-2）：按页桶与 touched_mask 降低元数据开销；支持 AoS/SoA/AoSoA 批量应用。
  - 读写分批（drain）与 age 抑制饥饿（在 mem 层已有 FRFCFS，可于上层适配窗口周期）。

如何开启/关闭自检回退（仅自测）
- 打开：在 `test_dram_si_single_pe.py` 中将 core 参数 `readresp_zero_fallback` 置 1，保持 `init_default_weight=0.5`。
- 关闭：保持 `readresp_zero_fallback=0`（默认），用于正式对比实验。

派生指标脚本（用于里程碑A/B产出表）
- 工具：`sst_dram_si/tools/derive_gas_metrics.py`
- 用法：
  ```bash
  # 从统计CSV派生 avg_burst_bytes/row_window_share/reqs_per_mib 等
  python3 sst_dram_si/tools/derive_gas_metrics.py sst_dram_si/stats/gas_2ms_xxx.csv \
      --stdout sst_output_data/run_xxx.log >> sst_dram_si/stats/derived_summary.csv
  ```
  输出列：`unique_reads, unique_bytes, bursts, payload, avg_burst_bytes, req_bytes, total_mib, reqs_per_mib, rowwin_triggers, rowwin_bytes, rowwin_share, avg_read_latency_0`。

## 里程碑B（bank_row + 行窗口）进展与结果（首轮）

本里程碑聚焦“bank_row 排序启用与行窗口扫参”。已落地：
- 启发式 bank_row 自动对齐（内核层）：GatherBufferIF 内置 `detectBankFieldsHeuristic_()`；当 `bank_bits/bank_shift='auto'`（或未提供）时在运行期采样推断 `(bank_bits, bank_shift)`；
  - 检测到 `Translation.impl: RandomTranslation` → 自动禁用 bank_row（降级为 row，并输出提示）；
  - `AddrMapper.impl: RoBaRaCoCh` 情形通常推断为 `(bank_bits≈4, bank_shift≈16)`（与先前手配一致）；
  - DDR4 openrow 配置已注释 RandomTranslation（`sst_dram_si/configs/ramulator2_ddr4_openrow.cfg`）。
- 行窗口扫参工具：`sst_dram_si/tools/sweep_row_window.py`（可配 `--dur 100us|2ms|5ms`），与派生脚本 `tools/derive_gas_metrics.py` 串联，自动生成汇总 CSV 与 `summary_<dur>.csv`。
- 新增 PE 聚合统计：`gas_total_bursts`、`gas_total_payload_bytes`（便于直算 `avg_burst_bytes` 与“有效载荷比例”）。

首轮 sweep（100us 与 2ms，bytes∈{16,32,64}KiB × timeout∈{0,300,600}ns）：
- 汇总表：
  - `sst_dram_si/stats/sweeps/summary_100us.csv`
  - `sst_dram_si/stats/sweeps/summary_2ms.csv`
- 观察：
  - avg_burst_bytes ≈ 2.08 KiB；row_window_share 在 100us 为 9%±1%，2ms 为 1.6%–3.3%；平均时延基本稳定（38.4–39.1）。
  - 初步结论：在当前数据集/短时标下，bank_row+行窗口对突发长度/事务密度的改善有限；需更长时标/更高活跃度/更有结构的访问才能显著放大收益。

下一轮（B-验收收尾）
- 在 5ms 与更高激活度下补跑 sweep；
- 派生脚本中追加 `row_hits_0/row_misses_0/row_conflicts_0` 的解析列，作为“行命中率改善”的直接证据；
- 增加“方案1基线 vs GAS（bank_row+rowwin）”对照表（reqs/MiB、avg_burst_bytes、row 命中率、avg_latency）。

工具速览（B）
- 行窗口 sweep：
  ```bash
  python3 sst_dram_si/tools/sweep_row_window.py --dur 100us
  python3 sst_dram_si/tools/sweep_row_window.py --dur 2ms
  # 汇总：sst_dram_si/stats/sweeps/summary_<dur>.csv
  ```

## 里程碑C（k 校准）计划与工具

目标
- 基于仿真数据对 gap 合并阈值 k（`gap_merge_k_bytes`）进行标定，给出 `k_recommended` 并回填脚本参数；
- 准则（数据驱动）：在不恶化平均时延的前提下，最小化 reqs/MiB（或最大化 avg_burst_bytes）。

工具（新增）：`sst_dram_si/tools/k_calibrate.py`
- 做法：在行窗口关闭的前提下，扫 k ∈ {0, 512, 1024, 2048, 4096, 8192}（可配置），固定其他参数，执行 100us/2ms 运行；
- 从 CSV/日志派生 `avg_burst_bytes, reqs_per_mib, avg_read_latency_0`，择优输出 `k_recommended`；
- 输出 `summary_k_<dur>.csv` 与 `k_recommended_<dur>.json`（含选择依据）。

后续：若需要更“物理”的 k 估计，可在 sweep 基础上增加“拆分 vs 合并”的微基准，对比同一覆盖长度在不同 gap 下的合并收益，近似反解 `k ≈ (tRA+tCA+tPRE)*B`。

## 里程碑C2/C3（已落地）：微基准与在线自适应 k

本次提交已落地：

- C2 微基准（MemKCalBench）：
  - 组件：`SnnDL.MemKCalBench`（StandardMem 客户端）
  - 位置：`sst_workspace/sst-elements/src/sst/elements/SnnDL/MemKCalBench.{h,cc}`
  - 脚本：`sst_dram_si/test_kcal_bench.py`
  - 行为：生成 row_hit / row_switch 两类读取场景，在不同 `L/gap` 下分别测 Split（两次小突发）与 Merge（一次大突发）时延；输出 CSV：`scene,L,gap,split_ns,merge_ns`
  - 快速运行（100us）：
    ```bash
    ./sst sst_dram_si/test_kcal_bench.py | tee sst_output_data/run_kcal_bench_100us.log
    # 结果：sst_dram_si/stats/kcal/bench_results.csv
    ```
  - 用途：后续以该表拟合每个 L 的临界 gap（`T_merge <= T_split` 的最小 gap），从而反推 `k_empirical(L)` 与稳健的 `k_recommended`。

- C3 在线自适应 k（默认关闭）：
  - 位置：`GatherBufferIF.h/.cc`
  - 思路：在 granule 级别记录下行段时延和有效载荷，在线估计 `B_eff`（字节/纳秒，EMA）与 `O_eff`（固定开销，窗口内样本），每 N 个窗口在边界更新 `k_dyn = EMA( O_eff_avg * B_eff )` 并回填 `gap_merge_k_bytes`（带限幅与阈值）。
  - 新参数（默认值，均在 `local_run_config.json` 可配）：
    - `k_adapt_enable=false`（开关，默认关）
    - `k_adapt_window_N=8`（每 N 个窗口尝试更新一次）
    - `k_alpha_bw=0.2`、`k_alpha_k=0.2`（带宽与 k 的 EMA 系数）
    - `k_min_bytes=512`、`k_max_bytes=65536`、`k_delta_bytes=512`（限幅与更新阈值）
  - 新统计（CSV 可见）：
    - `gas_k_dyn_bytes`（当前动态 k）
    - `gas_oeff_ns_avg`（窗口内 O_eff 平均值）
    - `gas_bw_eff_bytes_per_us`（B_eff ×1000）
  - 启用方式（实验性）：
    - `"k_adapt_enable": true`（建议先在 2ms/5ms 下试跑，观察 `gas_k_dyn_bytes` 收敛与 reqs/MiB 改善）
  - 兼容与安全：
    - `k_adapt_enable=0` 时行为完全一致（静态 k）；
    - 自适应仅在 `gap_merge_enable=1` 且 `merge_policy=auto` 时生效；
    - 样本不足/异常时不更新，避免震荡。

### k_from_bench 工具（C2 拟合与回填）
- 脚本：`sst_dram_si/tools/k_from_bench.py`
- 作用：从 `bench_results.csv` 拟合每个 L 的临界 gap（`k_empirical(L)`），并按分位数（默认 P75）给出 `k_recommended`；可直接写回 `local_run_config.json.gap_merge_k_bytes`。
- 用法示例：
  ```bash
  # 先运行微基准，生成 CSV：sst_dram_si/stats/kcal/bench_results.csv
  ./sst sst_dram_si/test_kcal_bench.py

  # 拟合并回填（同时输出 summary JSON）
  python3 sst_dram_si/tools/k_from_bench.py \
    --csv sst_dram_si/stats/kcal/bench_results.csv \
    --cfg sst_dram_si/local_run_config.json \
    --scene row_hit --percentile 0.75 \
    --out sst_dram_si/stats/kcal/k_fit_summary.json
  ```

## 里程碑C 定标结果（2025-10-23）

本轮完成 C1/C2 并做 C3 验证回填，结论如下：

- C1 数据驱动 sweep（100us/2ms）：
  - 推荐值一致为 k=2048（2 KiB）。
  - 100us：reqs/MiB≈53.12，avg_read_latency_0≈38.41ns。
  - 2ms：reqs/MiB≈128.00，avg_read_latency_0≈38.99ns（baseline k=0 时 ≈39.04）。
  - 产物：
    - sst_dram_si/stats/kcal/summary_k_100us_*.csv（与 .json）
    - sst_dram_si/stats/kcal/summary_k_2ms_*.csv（与 .json）

- C2 微基准（MemKCalBench）：
  - bench_results 在当前控制器策略下给出 k_per_L={4096:0,8192:0,16384:0,32768:0}，导致 k_recommended=0。
  - 说明：row_hit 场景下“gap=0 即满足合并更优”的判据会倾向 0，不符合工程上“吸收小空洞”的目标，需对回填做下限约束。
  - 产物：sst_dram_si/stats/kcal/bench_results.csv，sst_dram_si/stats/kcal/k_fit_summary.json。

- C3 回填验证（2ms，GAS 行窗口关闭）：
  - k=0：reqs/MiB≈129.33；avg_read_latency_0≈39.02ns（不优）。
  - k=2048：reqs/MiB≈128.56；avg_read_latency_0≈38.99ns（更优，且时延稳定）。
  - 产物：
    - sst_dram_si/stats/kcal/validate_gas_nowin_2ms.csv
    - 日志：sst_output_data/run_kcal_validate_2ms*.log

- 最终结论与默认值：
  - 采用 C1 数据驱动推荐 k=2048 作为默认（已回填到 sst_dram_si/local_run_config.json）。
  - 不采用 C2 的 0 值；若使用 C2 回填，请在工具侧增加 --min_bytes（建议 ≥1024）下限。

- 复现命令（摘要）：
  - Sweep：
    - python3 sst_dram_si/tools/k_calibrate.py --dur 100us --sort bank_row
    - python3 sst_dram_si/tools/k_calibrate.py --dur 2ms --sort bank_row
  - Bench：
    - ./sst sst_dram_si/test_kcal_bench.py
    - python3 sst_dram_si/tools/k_from_bench.py --csv sst_dram_si/stats/kcal/bench_results.csv --cfg sst_dram_si/local_run_config.json --scene row_hit --percentile 0.75 --out sst_dram_si/stats/kcal/k_fit_summary.json

- TODO（工具细化）：
  - k_from_bench 增加 --min_bytes/--max_bytes 门限，默认启用下限≥1 KiB；或采用 row_switch 场景作为稳健下界。

## 设计澄清：GAS 与神经元状态存放

- 神经元状态并未在 GAS/DRAM 中持久化。v_mem / refractory / last_spike 等状态全部保存在每个核心的 SnnPESubComponent 本地数组（AoS/SoA/AoSoA），由核心本地更新与阈值判断；GAS 仅作用于“权重/索引段”的读合并与缓存。
- GAS 的 SRAM scratchpad 只缓存下行读出的 granule（权重/索引数据），用于合并与命中，不存放神经元状态。
- 因此当前 CSV 中 `mem_read_latency_cycles_state` 多为 0（未对“状态区”发起 DRAM 读）；读延迟按地址区间进行权重/非权重分类：权重区为 `[base_addr_, weight_region_end_)`，其余为“非权重”（当前未使用）。
- 代码定位（交叉验证）：
  - 状态数组与访问器：`sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.h:444-470`（`soa_v_mem_`/`soa_refrac_`/`soa_last_spike_` 与 `getMem_/setMem_/getRefrac_`）。  
  - 状态初始化：`sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.cc:224-237`。  
  - Scatter 阶段应用窗口内增量 dv 到本地状态（无 DRAM）：`sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.cc:1423-1426`。  
  - 权重区界计算与分类上卷：`sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.cc:104, 1761`；PE 聚合读延迟分类：`sst_workspace/sst-elements/src/sst/elements/SnnDL/MultiCorePE.cc:666-671`。  
  - GAS SRAM 数据缓存：`sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.h:217`（`sram_blocks_`）。
- 若后续需要将“状态”映射到全局地址空间（例如检查点/溢写），建议：
  1) 预留“状态区”地址段并在核心侧通过 StandardMem 访问；  
  2) 在 MultiCorePE 的 `mem_read_latency_cycles_state` 路径上接入真实样本；  
  3) 评估是否需要让状态读也经过 GAS（行窗口/细合并）或直通 DRAM，并定义写回语义。

---

## 新增（D3 首版骨架）：NoC 单步时延（四方案对比）脚本与解析

- 新脚本：`sst_dram_si/test_noc_timestep.py`
  - 作用：在 Merlin SimpleNetwork(mesh) 上搭建可参数化多节点网格（默认 4×4），并提供四方案一键切换：
    - baseline：关闭合并（merge_read_cacheline=0, merge_read_row=0），禁用 GAS
    - slice（方案1）：`scheme1_enable=1`，支持 `scheme1_slices/gather/slice_gap/scatter` 参数
    - gas（方案2）：`gas_enable=1` + `gas_window_mode=1`（window_auto）；保留 cacheline 合并
    - sram（方案3）：纯 SRAM 命中（禁用下行读，启用事件权重回退）
  - 网络参数：`--mesh N`、`--bw`、`--in-lat`、`--out-lat`，默认 flit=8B、buf=4KiB
  - 统计：对 `SnnDL.SnnNIC` 与 `merlin.hr_router`、`SnnDL.MultiCorePE` 开启计数统计，落盘 `sst_dram_si/analysis/noc_timestep_stats.csv`
  - 运行：
    ```bash
    sst sst_dram_si/test_noc_timestep.py --scenario gas --mesh 4 --time 100us --bw 40GiB/s --in-lat 10ns --out-lat 10ns
    ```

- 解析脚本：`sst_dram_si/tools/plot_noc_timestep.py`
  - 作用：从 `analysis/noc_timestep_stats.csv` 粗聚合 NIC 包/脉冲计数、路由器负载、PE 外部脉冲收发；输出 `analysis/noc_timestep_summary.csv`
  - 占位：端到端 P50/P99 时延列暂记为 NA，后续通过在 SnnNIC/SnnPESubComponent 中补充时间戳采集落盘后填充
  - 用法：
    ```bash
    python3 sst_dram_si/tools/plot_noc_timestep.py \
      --csv sst_dram_si/analysis/noc_timestep_stats.csv \
      --out sst_dram_si/analysis/noc_timestep_summary.csv
    ```

  - 下一步（D3 补全）：
    - 在 `SnnNIC` 侧为发送/接收记录时间戳，输出 per-message 延迟分布（均值/P99），绑定到 CSV
    - 扩展网格规模（16×16/256×256）与链路策略（每跳延迟/入队开销）参数
    - 将四方案的统计对齐到统一雷达图模板（消息量/注入/吞吐/冲突率/端到端时延）

## 2025-10-29 BankRow Auto-Align 完成与文档同步

- What changed（代码/文档）
  - 脚本侧自动对齐：从 Ramulator2 cfg 解析 AddrMapper，支持 `bank_bits/bank_shift: "auto"`；若检测到 `RandomTranslation` 则禁用 bank_row 并退化为 `row`（启动日志提示）。实现：`sst_dram_si/test_dram_si_single_pe.py:128` 与 `sst_dram_si/test_dram_si_single_pe.py:432-445`。
  - 内核侧兜底：`GatherBufferIF` 在 Apply 构段前对 staged 地址做启发式搜索（bits∈[2,6], shift∈[12,24]），一次性选优；bank_bits==0 时自然退化为按 row 分组/排序。实现：`sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.cc:479-506`, `sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.cc:420-444`, `sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.h:171-176`。
  - 伪行邻接率：在 granule 下发前按排序序列统计相邻同（row/bank_row）对，用作行局部性代理（后续可导出 CSV）。实现：`sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.cc:433-444`。
  - 文档同步：更新 `sst_dram_si/对接文档.md` 的“8) 建议的下一步”第1点，将 bank_row 自动对齐标注为“已完成（脚本 auto + 内核启发式）”，并建议在无 RandomTranslation 的 cfg 下进行长时标扫参与可视化校验。

- Affected files
  - `sst_dram_si/test_dram_si_single_pe.py:128, 432-445`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.h:171-176`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.cc:420-444, 479-506`
  - `sst_dram_si/对接文档.md`（第8节第1点）

- How to verify（DDR4, bank_row=auto）
  1) 保持 `sst_dram_si/local_run_config.json` 中 `bank_bits/bank_shift` 为 `"auto"`；将 `gas_sort_policy` 设为 `"bank_row"`；确保 `ramulator2_config_file` 指向 `sst_dram_si/configs/ramulator2_ddr4_openrow.cfg`。
  2) 运行：`./sst sst_dram_si/test_dram_si_single_pe.py | tee sst_output_data/run_ddr4_bankrow_auto.log`
  3) 期望：启动日志打印 `bank_row 自动推断: mapper=RoBaRaCoCh → bank_bits=4, bank_shift=16`；CSV 含 `gas_*_total` 与直方图；用 `python3 sst_dram_si/tools/derive_gas_metrics.py <csv> --stdout sst_output_data/run_ddr4_bankrow_auto.log` 验证 `avg_burst_bytes/reqs_per_mib`。
  4) HBM2 验证：将 cfg 切换到 `sst_dram_si/configs/ramulator2_hbm2.cfg`，期望日志提示 `RandomTranslation` 导致 bank_row 自动禁用并退化为 `row`，运行应正常。

- Open items / TODO
  1) “一致性可视化”：导出（bits,shift）与地址→(bank,row) 映射样本到 CSV，并生成热图/分桶占比分布；对比 Ramulator2 AddrMapper 计算结果。
  2) 将 `pseudo_row_adj_rate` 导出为窗口级 CSV 列，便于与 `row_hits_*` 联动分析。
  3) 若需要强一致：考虑在 memHierarchy.ramulator2 暴露真实地址映射字段到 SST 统计，取代启发式。

- 兼容性
  - 当 bank_bits=0 或 cfg 不支持自动推断时，行为退化为纯 row 排序/分桶，功能与统计稳定；无需变更现有脚本。

---

## 当前进度目录（简要）
- GAS 前端完成：Gather→Apply→Scatter；gap 合并（k/Lmax）、行窗口（bytes/timeout）、SRAM+LRU、窗口自动；统计（unique reads/bytes、row_window、bursts/payload、阶段周期、缓冲占用）稳定落盘
- bank_row 自动对齐：脚本解析 AddrMapper（auto）；HBM2/RandomTranslation 自动禁用；内核启发式兜底；失败退化为 row
- MultiCorePE 聚合与窗口化：`gas_*_total` 汇总；窗口 CSV 输出（read/issue/avg_latency/avg_size/avg_outstanding/avg_activity_f）；读时延/请求大小/MSHR 直方图启用
- Ramulator2 集成与能耗：DDR4/HBM2 跑通；DRAMPower 能耗解析与平均功率派生；日志对比与派生工具完善
- k 定标/控制：C1 sweep 默认 k=2048；C2 bench 与回填工具；闭环在线探测与采纳（k/rowwin/timeout）计数
- 方案1 基线：slice 粗扫描对照路径保留
- 辅助工具：行窗口 sweep、自检（gap/rowwin）、k_calibrate/k_from_bench、compare_ramulator2_logs、NoC 单步时延脚本骨架

## 2025-10-29 P1（NoC 时延采样）落地

- What changed
  - 在 `SnnDL.SnnNIC` 中加入 per-message 网络时延采样：发送时在载荷写入 `send_ns`，接收时计算 `now-send_ns` 并写入统计 `msg_latency_ns`（纳秒，Histogram）。
  - `test_noc_timestep.py` 默认开启 `SnnDL.SnnNIC.msg_latency_ns` 直方图（bin=50ns×200）。
- Affected files
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnNIC.h:116-123`（新增统计声明）
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnNIC.cc`（载荷扩展 `send_ns`、注册统计、接收端计入时延）
  - `sst_dram_si/test_noc_timestep.py`（实例级启用 Histogram）
- How to verify
  - 运行任一场景（baseline/slice/gas/sram）后，查看 `sst_dram_si/analysis/noc_timestep_stats.csv` 中 `SnnDL.SnnNIC,msg_latency_ns,Histogram` 行；可据此计算均值/P95/P99。
- Next
  - 轨迹驱动读流量：导出 `granules.csv/spikes.csv/gas_stage.csv`，注入 ReadReq/Resp + Spike，形成“现实/理想”双曲线（P1 第二部分）。

---
## 2025-10-29 实验文档：4×4 Mesh 方案（P0→P1）

- What changed
  - 新增实验文档：`sst_dram_si/EXPERIMENT_4x4_MESH.md`（Gate→K定标→SRAM/DRAM容量→4×4 NoC→能耗→复现打包），可直接按文档命令开跑。
  - 作为 4×4 Mesh 的 P0 框架，推荐使用 `sst_dram_si/test_noc_timestep.py`（四方案切换，Merlin mesh，轻量内存）。

- How to run（P0）
  - baseline/slice/gas/sram（100us, 4×4）：`sst sst_dram_si/test_noc_timestep.py --scenario gas --mesh 4 --time 100us --bw 32GiB/s --in-lat 10ns --out-lat 10ns`（四条分别替换 `--scenario`）
  - 汇总：`python3 sst_dram_si/tools/plot_noc_timestep.py --csv sst_dram_si/analysis/noc_timestep_stats.csv --out sst_dram_si/analysis/noc_timestep_summary.csv`
  - 预期：GAS 注入/负载低于基线；P95/P99 时延在 P1 版 NIC 采样实现后补齐。

- Next
  1) SnnNIC 增加 per-message 时延采样（均值/P95/P99 导出到 CSV）
  2) 轨迹驱动 P1：导出 `spikes.csv/granules.csv/gas_stage.csv`，注入 ReadReq/Resp + Spike 形成“现实/理想”双曲线

---

## 2025-10-29 P1‑2（NoC 重放 + 端到端分解 + 窗口峰值并入）

- What changed（新增能力/参数）
  - NoC 轻量轨迹驱动：`sst_dram_si/tools/noc_trace_driver.py`
    - 输入：`analysis/granules.csv`、`analysis/spikes.csv`（由 SnnNIC 导出）、`stats/stage_events_*.csv`
    - 选项：`--multicast=replicate|tree`，`--bw 32GiB/s` 或 `--bw-bytes-per-ns`，`--overlap=ideal|realistic`
    - 输出：`analysis/noc_trace_summary_*.csv`，字段含 `injected_flits/edge_flits/total_payload_bytes/avg/p50/p95/p99`
  - 端到端分解工具：`sst_dram_si/tools/derive_end2end_breakdown.py`
    - 融合 `stage_events(sim_time_ns)` + NoC 汇总 + `granules.csv`，输出 `analysis/end2end_breakdown.csv`
    - 口径：`t_total = t_DRAM_wait + t_NoC + t_compute`，其中 `t_compute=avg_apply+avg_scatter`，`t_DRAM_wait≈max(avg_gather−t_NoC,0)`
  - 窗口峰值并入窗口 CSV：
    - GatherBufferIF：按窗口落 `analysis/window_metrics.csv`（`window_id,payload_bytes,bursts,inflight_peak,buffer_max_bytes`），finish/dtor 兜底写出
    - MultiCorePE：在写 `stats/windowed/windows_<N>us.csv` 前合并 `window_metrics.csv`，新增列 `sb_peak_bytes,inflight_peak`
  - SnnNIC：
  - 导出脉冲轨迹：参数 `export_spike_csv`，`test_noc_timestep.py` 写入 `analysis/spikes.csv`，`test_mesh_4x4.py` 写入 `analysis/spikes_mesh.csv`

- How to run（示例）
  ```bash
  # 1) 生成 granules/window_metrics
  ./sst sst_dram_si/test_dram_si_single_pe.py

  # 2) NoC 重放（单播/树形多播对比）
  python3 sst_dram_si/tools/noc_trace_driver.py \
    --granules sst_dram_si/analysis/granules.csv \
    --spikes analysis/spikes.csv \
    --stages sst_dram_si/stats/stage_events_db_100us.csv \
    --bw 32GiB/s --multicast replicate \
    --out sst_dram_si/analysis/noc_trace_summary_from_driver.csv

  python3 sst_dram_si/tools/noc_trace_driver.py \
    --granules sst_dram_si/analysis/granules.csv \
    --spikes analysis/spikes.csv \
    --stages sst_dram_si/stats/stage_events_db_100us.csv \
    --bw 32GiB/s --multicast tree \
    --out sst_dram_si/analysis/noc_trace_summary_tree.csv

  # 3) 端到端分解
  python3 sst_dram_si/tools/derive_end2end_breakdown.py \
    --stages sst_dram_si/stats/stage_events_db_100us.csv \
    --noc sst_dram_si/analysis/noc_trace_summary_from_driver.csv \
    --granules sst_dram_si/analysis/granules.csv \
    --out sst_dram_si/analysis/end2end_breakdown.csv
  ```

- Affected files
  - `sst_dram_si/tools/noc_trace_driver.py`（新增 multicast/树型多播、带宽口径、统计列）
  - `sst_dram_si/tools/derive_end2end_breakdown.py`（新增）
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/{GatherBufferIF,MultiCorePE,SnnNIC}.*`（窗口峰值导出/合并、spike 导出）
  - `sst_dram_si/test_noc_timestep.py`、`sst_dram_si/test_mesh_4x4.py`（为 SnnNIC 传入 `export_spike_csv`；4×4 mesh 同时导出 `granules_mesh.csv/window_metrics_mesh.csv`）

- Metrics/验收
  - NoC：`injected_flits/edge_flits/total_payload_bytes/avg/p95/p99`，`tree` 相对 `replicate` 的链路节省可见
  - 端到端：`end2end_breakdown.csv` 内 `t_total_ns` 与分量可用于绘图与对比
  - 窗口：`windows_<N>us.csv` 中 `sb_peak_bytes/inflight_peak` 非零，且与 `analysis/window_metrics.csv` 一致

- Next
  - 将 `window_id` 与窗口时间对齐（避免按行序近似映射），保障跨 run 可比性
  - `noc_trace_driver` 增加更细的路由级排队模型或对接 BookSim2
  - 从 SnnNIC `msg_latency_ns` 直方图聚合 P50/P95/P99，作为 SST 内测量与 trace 驱动的交叉验证

---
## 2025-10-30 4×4 Mesh（以 test_noc_timestep.py 为统一入口）

- What changed
  - 统一 flit 口径：Merlin mesh flit=32B（与驱动一致）。
  - Mesh 映射模式：新增环境开关 `MESH_MAPPING_MODE=post|pre`（默认 post-owned/M0）。
  - WeightLoader 端口修正：避免与 L1 冲突（使用 `highlink{NUM_CORES_PER_PE}`）。
  - 文档更新：EXPERIMENT_4x4_MESH.md 改为用 `./sst ... -- --scenario ...` 形式启动 P0；P1 默认树型多播、flit=32B。

- Affected files
  - sst_dram_si/test_mesh_4x4.py:475（flit=32B），444-454（WeightLoader 端口），596-604（M0/M1 环境开关）
  - sst_dram_si/EXPERIMENT_4x4_MESH.md（P0/P1 命令、树型多播、M0/M1 同步导出说明）

- How to run
  - P0 四方案（100us，32GiB/s）：
    ```bash
    ./sst sst_dram_si/test_noc_timestep.py -- --scenario baseline --mesh 4 --time 100us --bw 32GiB/s
    ./sst sst_dram_si/test_noc_timestep.py -- --scenario slice    --mesh 4 --time 100us --bw 32GiB/s
    ./sst sst_dram_si/test_noc_timestep.py -- --scenario gas      --mesh 4 --time 100us --bw 32GiB/s
    ./sst sst_dram_si/test_noc_timestep.py -- --scenario sram     --mesh 4 --time 100us --bw 32GiB/s
    ```
    可选注入：`--firing 0.03`
  - P1 重放（树型多播，读流量）：
    ```bash
    python3 sst_dram_si/tools/noc_trace_driver.py \
      --granules sst_dram_si/analysis/granules.csv \
      --stages   sst_dram_si/stats/stage_events_db_100us.csv \
      --bw 32GiB/s --size 4 --multicast tree \
      --out sst_dram_si/analysis/noc_trace_summary_tree.csv
    python3 sst_dram_si/tools/derive_end2end_breakdown.py \
      --stages sst_dram_si/stats/stage_events_db_100us.csv \
      --noc    sst_dram_si/analysis/noc_trace_summary_tree.csv \
      --granules sst_dram_si/analysis/granules.csv \
      --out sst_dram_si/analysis/end2end_breakdown.csv
    ```

- Results snapshot（以当前 granules.csv 为例）
  - noc_trace_summary_tree.csv：read_req 42615 条、read_resp 42615 条；avg_ns≈0.44（resp）；edge_flits=19585（resp）。
  - end2end_breakdown.csv：t_total≈0.44us（NoC 主导；仅示例）。

### 4×4 Spike 多播（P1 重放，flit=32B；新增）
- A：合成 spikes（analysis/spikes.csv，单汇聚到 tile15）
  - replicate vs tree（spike 类）：
    - replicate：injected_flits=61980、edge_flits=189507、p95≈40.76ns
    - tree：injected_flits=12723、edge_flits=38946、p95≈40.76ns
  - 结论：tree 相对 replicate，injected/edge_flits 均下降≈79%，理想模型下延迟分位一致。
- B：mesh 导出 spikes（analysis/spikes_mesh.csv）
  - replicate：injected_flits=273、edge_flits=549、p95≈20.38ns
  - tree：injected_flits=174、edge_flits=342、p95≈20.38ns
  - 结论：tree 边上流量下降≈38%（fanout 小/近邻）。

### 读侧远程占比敏感性（合成 granules，avg≈2KiB）
- 数据：20000 granules，remote ∈ {5%, 20%, 50%}；BW=32GiB/s；ideal overlap
- 结果（tree）：
  - 5%：read_resp p95≈0ns、p99≈246.69ns（近“零跳”下界）；edge_flits≈172441
  - 20%：p95≈232.07ns、p99≈340.10ns；edge_flits≈698482
  - 50%：p95≈299.40ns、p99≈395.98ns；edge_flits≈1758817
- 结论：远程占比提升，edge_flits 与 p95/p99 单调上升；树型多播在 spike 上的收益更显著，读侧主要受远程密度驱动。

### 阶段事件修复
- 修复：SnnPESubComponent 追加 `sim_time_ns` 列与完整 Begin/End 事件（需 `apply_acc_enable=1`）。
- 操作：重建并安装 libSnnDL.so，删除旧 `stage_events_db_100us.csv` 后重跑单PE，现头部为：
  `seq,event,sim_time_ns,acc_updates,posts_touched,hwm_bytes,spill_records,spilled_bytes,spikes_emitted`


- Next
  - P0 统计落盘在个别环境未生成（noc_timestep_stats.csv）；可用 `summarize_nic_latency.py`（若生成）或以 P1 驱动为主口径。
  - spike 多播（tree vs replicate）对比：补充 spikes.csv 重放；消息构成堆叠图与热点端口热图。

---
## 2025-10-30 真实端到端分解（事件成对 + 多窗）

- What changed（内核最小改已安装）
  - GatherBufferIF：新增 `emit_stage_events_lenient`（默认0）。窗口到期即便 inflight>0 也发 `EndApply`，保证短/空窗口也有 `EndApply/EndScatter`。
    - sst_workspace/sst-elements/src/sst/elements/SnnDL/GatherBufferIF.{h,cc}
  - SnnPESubComponent：在 `BeginGather/BeginScatter` 分支无条件写 CSV 行（包含 `sim_time_ns`），确保事件成对。
    - sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.cc
  - 单PE脚本：为 GatherBufferIF 透传 `emit_stage_events_lenient=1`。
    - sst_dram_si/test_dram_si_single_pe.py

- 新工具（面向实验）
  - make_stage_schedule.py：按 `gather/apply/scatter(ns)` 生成“调度表”CSV（含 `sim_time_ns`），短跑兜底/对照。
  - make_remote_ratio.py：将 granules 调整为目标远程占比（读侧敏感性）。

- How to run（真实采样 + 端到端分解）
  1) 真实事件（100us/5ms 任一）：
     ```bash
     ./sst sst_dram_si/test_dram_si_single_pe.py -- --time 100us   # 或 5ms
     # 输出：sst_dram_si/stats/stage_events_db_100us.csv
     # 事件：BeginGather/BeginApply/EndApply/BeginScatter/EndScatter（多窗、成对）
     ```
  2) 远程占比 50%（树型多播，flit=32B）：
     ```bash
     python3 sst_dram_si/tools/noc_trace_driver.py \
       --granules sst_dram_si/analysis/granules_remote50.csv \
       --bw 32GiB/s --size 4 --multicast tree \
       --out sst_dram_si/analysis/noc_remote50_tree.csv
     ```
  3) 端到端分解：
     ```bash
     python3 sst_dram_si/tools/derive_end2end_breakdown.py \
       --stages sst_dram_si/stats/stage_events_db_100us.csv \
       --noc    sst_dram_si/analysis/noc_remote50_tree.csv \
       --granules sst_dram_si/analysis/granules_remote50.csv \
       --out   sst_dram_si/analysis/end2end_remote50_real.csv
     ```

- Results（remote50, 32GiB/s）
  - 平均窗口：gather≈200ns，apply≈40ns，scatter≈40ns；t_NoC≈87.28ns；t_DRAM_wait≈112.72ns（=200−87.28）；t_compute≈80ns；t_total≈280ns。
  - 5ms 长跑重算（end2end_remote50_real_5ms.csv）与 100us 短跑一致，验证口径稳定。

- Notes
  - 多核会对同一事件写多行（每 core 一行），脚本按 `seq/event/sim_time_ns` 聚合；短跑若极端空窗也可用 make_stage_schedule.py 兜底生成“调度表”重算。


## 文档更新（2025-10-30 22:29）
- 内容：完善 4×4 Mesh 实验方法学，细化 P0/P1 流程、指标口径、敏感性与排查建议。
- 影响：对外说明文档的第 5 节（4×4 Mesh 实验方法学）。
- 文件：sst_dram_si/GAS访存与实验方案说明.md
- 验证：阅读第 5 节是否涵盖 Gate‑0、数据与轨迹准备、P0/P1、容量与稳定性、指标口径与派生、敏感性与扫参、常见问题与排查。
- 下一步：如需，将该方法学与现有实验脚本对齐出一份“可执行 checklist”。


## 文档更新（2025-10-31 09:20）
- 内容：在 EXPERIMENT_4x4_MESH.md 增加‘实验四：基线（方案1）vs GAS 对照（单PE+Mesh）’，含统一设置、单PE对照、Mesh轨迹重放与判定口径。
- 影响：补齐基线 vs GAS 的实验操作说明，便于复现实验与评审。
- 文件：sst_dram_si/EXPERIMENT_4x4_MESH.md
- 验证：按新增章节完成两组运行，产出 DRAM 控制器摘要、聚合 CSV 与 NoC 重放统计，比较 avg_burst_bytes/reqs_per_mib/p95/p99 等。


## 文档更新（2025-10-31 09:21）
- 内容：建立文档互链。在 GAS 说明第 5 节加入对 `EXPERIMENT_4x4_MESH.md` 第 4 节的引用；在实验文档第 4 节加入对 GAS 说明第 5 节的引用。
- 影响：读者可在设计/实验说明间快速跳转，统一口径。
- 文件：sst_dram_si/GAS访存与实验方案说明.md，sst_dram_si/EXPERIMENT_4x4_MESH.md
- 验证：两文件相应章节含“互链参考”提示行。


## 文档更新（2025-10-31 16:44）
- 内容：在 EXPERIMENT_4x4_MESH.md 的 Gate‑0 段后新增“参数基线（当前 Mesh 默认）”，明确 4×4 拓扑、每PE核心/神经元、L1/L2 容量与行大小、内存控制器规模/时钟/延迟、总线频率、GAS 前端关键参数、NoC 路由器/NIC 带宽与缓冲等。
- 影响：统一默认值口径，便于复现实验与跨文档引用。
- 文件：sst_dram_si/EXPERIMENT_4x4_MESH.md
- 验证：阅读“参数基线（当前 Mesh 默认）”小节是否包含所列关键参数，并与 test_mesh_4x4.py 中默认/覆盖逻辑一致。


## 文档更新（2025-10-31 16:50）
- 内容：明确‘主入口与脚本分工’（test_noc_timestep.py 为主入口，test_mesh_4x4.py 为 CSV 生产者可选），并在‘实验四’中将 NoC 对照命令改为基于主入口（P0 四方案；P1 重放+端到端分解）。
- 影响：跑 Mesh 对照时的统一入口与复现命令更清晰，避免权重/数据依赖导致的不稳定。
- 文件：sst_dram_si/EXPERIMENT_4x4_MESH.md
- 验证：查看文档顶部“主入口与脚本分工”小节，以及第 4 节中 P0/P1 命令是否为 test_noc_timestep.py 与 tools/* 脚本。

## 文档更新（2025-10-31 17:10）
- 内容：补齐“DDR4/HBM2 双后端实验矩阵”与对照口径：
  - EXPERIMENT_4x4_MESH.md 增加“DRAM 后端（DDR4/HBM2）实验矩阵（新增）”，给出 Gate‑0/K‑sweep/P1 分解的成套命令与验收；
  - GAS 说明（两份）在“4×4 Mesh 实验方法学”中加入“（含 DDR4/HBM2 对照）”与专节“DRAM 后端对照（DDR4 vs HBM2）”；
  - 对接文档加入 DDR4/HBM2 cfg 列表与“对照指引”提示。
- 影响：统一两套 DRAM 后端在 Mesh/P1 场景下的运行与判定口径，便于评审与复现。
- 文件：
  - sst_dram_si/EXPERIMENT_4x4_MESH.md
  - sst_dram_si/GAS访存与实验方案说明.md
  - sst_dram_si/GAS访存与实验方案说明_润色版.md
  - sst_dram_si/对接文档.md
-
- 验证：
  - EXPERIMENT_4x4_MESH.md:43 处出现“DRAM 后端（DDR4/HBM2）实验矩阵（新增）”；
  - GAS 说明：两份文档的 5 章标题包含“（含 DDR4/HBM2 对照）”；
  - 对接文档：24 行含 DDR4/HBM2 cfg；628 行出现“【DDR4/HBM2 对照指引（新增）】”。


## 文档更新（2025-11-01 09:47）
- 内容：在 GAS访存与实验方案说明_润色版.md 文末新增‘主入口与脚本分工（同步说明）’，与 EXPERIMENT_4x4_MESH.md 的主入口/对照用法保持一致；并保留 Mesh 参数基线附录。
- 影响：单文档即可知默认 Mesh 口径与主入口用法；跨文档互链一致。
- 文件：sst_dram_si/GAS访存与实验方案说明_润色版.md
- 验证：检查文末附录是否含 Mesh 参数基线与‘主入口与脚本分工’两小节。

- 2025-11-03 实验A文档：新增 sst_dram_si/EXPERIMENT_A.md；单PE 1k@100us（ramulator2）冒烟完成，memory_requests=459，G/A/S=200/40/40ns，待补齐 dram_bytes_read。


## 2025-11-09 19:13:35 Strict GAS fixes (edge-cap, EndScatter diag)
- Code: sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.h, .cc
- Changes:
  - Added edge collector capacity guard (param `edge_collector_max_capacity`, default 1e6); logs once and increments `gas_edge_overflow` when hit.
  - Initialized and documented `weight_region_end_` (already present).
  - Added EndScatter inconsistency diagnostic (debug only; no behavior change).
  - Opportunistic Apply supplement mapping bug fixed in experimental_features copy (pre_row_post_col).
- Build:
  - cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4 && make install
- Regression (single-PE 100k):
  - ./sst_dram_si/run_singlepe_with_time.sh
  - Outputs: see `sst_dram_si/outputs_large/paper2/dram_N100k/latest/essential_summary.json`
  - Key: memory_requests=748089, dram_bytes_read_mib=220.987, neurons_fired=278, unique=139, gas_windows_total=358 (matches baseline).


## 2025-11-09 19:47:14 Weight-cache plumbing + spike mapping cache
- Code: sst_workspace/sst-elements/src/sst/elements/SnnDL/SnnPESubComponent.h, .cc, SpikeEvent.h
- Changes:
  - Introduced weightCacheTryGet_/weightCacheStore_ wrappers so `use_clock_weight_cache` can switch LRU/Clock without touching call sites.
  - Raised `max_cache_entries` default to 65536 and reserved the unordered_map to reduce rehash churn.
  - Added per-event local-index cache (SpikeEvent) so deliverSpike computes post/pre locals once and processLocalSpike reuses them.
- Build/test: cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4 && make install
- Regression: ./sst_dram_si/run_singlepe_with_time.sh -> outputs_large/paper2/dram_N100k/20251109-194504/essential_summary.json (matches baseline metrics).

- Re-run after cache log tweaks: ./sst_dram_si/run_singlepe_with_time.sh -> outputs_large/paper2/dram_N100k/20251109-194934/essential_summary.json (still matches baseline).

- 2025-11-09 20:36:26 GatherBufferIF: added stage cycle accumulators + optional CSV export; verified with ./sst_dram_si/run_singlepe_with_time.sh -> outputs_large/paper2/dram_N100k/20251109-202534/essential_summary.json (Apply auto end + Scatter immediate defaults).

- 2025-11-09 20:36:43 GatherBufferIF stage-cycle stats validated via ./sst_dram_si/run_singlepe_with_time.sh -> outputs_large/paper2/dram_N100k/20251109-203417/essential_summary.json.

## 2025-11-09 20:55:45 Stage-cycle CSV & Scatter immediate config wiring
- Code: sst_dram_si/test_dram_si_single_pe.py, sst_dram_si/local_run_config.json
- Changes:
  - Added config plumbings for `stage_cycles_csv`, `apply_auto_end_enable`, and `scatter_immediate_complete`; script now normalizes requested CSV path into each run directory and forwards toggles to GatherBufferIF.
  - Updated default local_run_config.json to emit per-window cycle CSV (stage_cycles_db_100us.csv) and enable Scatter immediate completion while keeping Apply auto-end explicit.
- Verification:
  - Syntax: `python3 -m py_compile sst_dram_si/test_dram_si_single_pe.py`.
  - Regression: `cd sst_dram_si && ./run_singlepe_with_time.sh` → outputs_large/paper2/dram_N100k/20251109-205545. Result file `stage_cycles_db_100us.csv` shows scatter column dropping到1 tick (e.g.行2/435)；essential_summary记录 memory_requests=948222、dram_bytes_read_mib=384.721、gas_windows_total=435，如预期因 Scatter 加速带来更多窗口迭代。

## 2026-01-31 Memory backend & Ramulator2 cfg review (analysis)
- What changed:
  - 审阅 mem backend 选择链路与覆盖优先级：`sst_dram_si/mesh_template/config.py`、`sst_dram_si/mesh_template/runtime.py`、`sst_dram_si/mesh_template/build.py`。
  - 汇总 Ramulator2 配置要点与实验矩阵建议：`sst_dram_si/configs/ramulator2_ddr4_openrow.cfg`、`sst_dram_si/configs/ramulator2_hbm2.cfg`、`sst_dram_si/configs/ramulator2_ddr5.cfg`、`sst_dram_si/docs/EXPERIMENT_4x4_MESH.md`、`sst_dram_si/对接文档.md`。
- How to run/verify:
  - 本次为配置审阅与实验建议，无需运行；如需复现 k/row-window 扫参，可参考 `sst_dram_si/tools/k_calibrate.py` 与 `sst_dram_si/tools/sweep_row_window.py`。
- Metrics/results:
  - 无新增指标（文档审阅输出）。
- Next steps/TODO:
  - 若需更严格校准：为 HBM2/DDR5 增补“无 RandomTranslation 变体 cfg”，并在同一 NoC 轨迹下做 DDR4/HBM2/DDR5 A/B。
