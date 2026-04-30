# 4×4 Mesh 实验方案与落地步骤（P0→P1）

本文件给出一套可直接开跑的 4×4 网格（16 tile）网络实验方案，覆盖 Gate→K 定标→SRAM/DRAM 容量→NoC 对比→能耗→复现打包，按“参数网格、运行命令、产物路径、验收口径”组织。所有路径以仓库根目录运行 `./sst` 为基准。

---

## 主入口与脚本分工（重要）

- 主入口：`sst_dram_si/test_noc_timestep.py`
  - P0：内置四方案 baseline/slice/gas/sram，直接在 Merlin mesh（flit=32B）下对比；
  - P1：`--replay` 模式调用 `tools/noc_trace_driver.py` 重放 granules/spikes（`--multicast tree` 统一树型多播），配合 `tools/derive_end2end_breakdown.py` 输出端到端分解；
  - 优点：不依赖权重/数据文件，启动快；统计口径统一（flit=32B）；适合扫参与画图。

- CSV 生产者（可选）：`sst_dram_si/test_mesh_4x4.py`
  - 用途：在 `MESH_WEIGHT_MODE=event` 下快速导出真实 `granules_mesh.csv`/`spikes_mesh.csv`（`MESH_MAPPING_MODE=post|pre` 可切换）；
  - 现状：本机曾出现一次退出冲突（double-deletion），已用“调度表/合成 granules”兜底 Mesh 对照；后续做稳定性裁剪后再作为生产者使用；
  - 不作为主跑脚本（避免权重/数据依赖与稳定性波动），主跑脚本保持 `test_noc_timestep.py` 不变。

## 0) 前置检查（Gate 0）

目标：统一语义与配置，保证 bank_row 对齐与默认参数一致。

- 语义边界：当前版本仅对“突触数据”做 DRAM 读取；神经元状态在 PE 内本地数组更新，不走 DRAM。
- 地址映射：建议使用 DDR4 OpenRow 配置（无随机地址扰动）。HBM2 路径含 RandomTranslation，将自动禁用 bank_row 并退化为 row。
- bank_row 自动对齐：在 `sst_dram_si/local_run_config.json` 中设置：
  - `"bank_bits": "auto", "bank_shift": "auto"`
  - `"gas_sort_policy": "bank_row"`（建议）
  - `"ramulator2_config_file": "sst_dram_si/configs/ramulator2_ddr4_openrow.cfg"`
- 端到端语义：`"apply_acc_enable": 1`，跑分时可将 `"stage_events_csv": ""` 以减噪。
- 默认 GAS 参数：`k=2048B`、`Lmax=64KiB`、行窗口默认关或小阈值。

运行（100us 自检）
```bash
./sst sst_dram_si/test_dram_si_single_pe.py | tee sst_output_data/gate0_ddr4_100us.log
# 期望：日志打印 bank_row 自动推断(DDR4 RoBaRaCoCh→bits=4,shift=16)，
# CSV 出现 gas_*_total 统计行。
```

验收
- 启动日志出现 mapper 推断提示（DDR4）；HBM2 路径提示 RandomTranslation 导致退化为 row。
- `sst_dram_si/stats/*.csv` 中存在 `gas_unique_reads_total/gas_unique_bytes_total` 等条目。

### DRAM 后端（DDR4/HBM2）实验矩阵（新增）
- 目的：在两套 DRAM 后端上以相同 NoC 轨迹与前端参数复现端到端差异，固化“DDR4 vs HBM2”的对照口径。
- 配置文件：
  - DDR4（OpenRow、可启用 bank_row）：`sst_dram_si/configs/ramulator2_ddr4_openrow.cfg`
  - HBM2（默认含 RandomTranslation、bank_row 自动退化为 row）：`sst_dram_si/configs/ramulator2_hbm2.cfg`
- Gate‑0 自检命令（单PE）：
  - DDR4：`./sst sst_dram_si/test_dram_si_single_pe.py`
  - HBM2：`cp sst_dram_si/local_run_config_hbm2.json sst_dram_si/local_run_config.json && ./sst sst_dram_si/test_dram_si_single_pe.py`
- K 定标（各自 sweep 一遍；推荐 `dur=100us,2ms`）：
  - DDR4：`python3 sst_dram_si/tools/k_calibrate.py --cfg sst_dram_si/local_run_config.json --dur 100us --sort bank_row`
  - HBM2：`python3 sst_dram_si/tools/k_calibrate.py --cfg sst_dram_si/local_run_config_hbm2.json --dur 100us --sort bank_row`（如保留 RandomTranslation，实际退化为 row）
- P1 端到端分解（共用同一 NoC 轨迹，分别用 DDR4/HBM2 的阶段事件 CSV）：
  1) 生成/选择 granules：`sst_dram_si/analysis/granules.csv`
  2) NoC 重放：`python3 sst_dram_si/tools/noc_trace_driver.py --granules sst_dram_si/analysis/granules.csv --bw 32GiB/s --size 4 --multicast tree --out sst_dram_si/analysis/noc_trace_summary_tree.csv`
  3) 分解：
     - DDR4：`python3 sst_dram_si/tools/derive_end2end_breakdown.py --stages sst_dram_si/stats/stage_events_db_100us.csv --noc sst_dram_si/analysis/noc_trace_summary_tree.csv --granules sst_dram_si/analysis/granules.csv --out sst_dram_si/analysis/end2end_ddr4.csv`
     - HBM2：将 `local_run_config.json` 指向 HBM2 cfg 再跑单PE生成阶段事件，然后：`python3 sst_dram_si/tools/derive_end2end_breakdown.py --stages sst_dram_si/stats/stage_events_db_100us.csv --noc sst_dram_si/analysis/noc_trace_summary_tree.csv --granules sst_dram_si/analysis/granules.csv --out sst_dram_si/analysis/end2end_hbm2.csv`
- 验收：对比 `end2end_ddr4.csv` 与 `end2end_hbm2.csv` 的 `{t_total_ns,t_DRAM_wait_ns,t_noc_avg_ns,t_compute_ns,avg_burst_bytes}`；`t_noc_avg_ns` 基本一致，差异主要体现在 `t_DRAM_wait_ns`。

### 参数基线（当前 Mesh 默认）
- 拓扑与规模：`4×4` 节点（16 PE）。
- 每 PE：`num_cores_per_pe=16`（可被配置覆盖；未覆盖时 Mesh 脚本内置默认为 4）、`neurons_per_core=32`（未覆盖时默认 4）；每 PE 神经元总数=`num_cores_per_pe×neurons_per_core`。
- L1：容量 `16KiB`，相联度 `8`，行大小 `64B`，频率 `2GHz`。
- L2（每 PE）：容量 `128KiB`，相联度 `8`，行大小 `64B`，频率 `2GHz`，非包容。
- 内存控制器（每 PE）：时钟 `1GHz`，后端 `simpleMem`，访问时延 `100ns`，内存大小 `64MiB`。
- 片上内存总线：`1GHz`。
- GAS 前端关键：`gap_k=2048B`，`Lmax=64KiB`，`max_inflight_reads=128`，`sram_bytes=256KiB`，窗口周期（g/a/s）=`200/40/40`。
- NoC 路由器：端口数 `5`（N/E/S/W+本地）、链路带宽 `40GiB/s`（可由 `network_bandwidth` 覆盖）、交叉带宽同链路、`flit=32B`、输入/输出缓冲 `4KiB`、输入/输出延迟 `10ns`、VN 数 `1`。
- NIC：`link_bw=40GiB/s`、输入/输出缓冲 `8KiB`（可由 `buffer_size` 覆盖）。
- 其他：权重加载块 `128B`；权重基地址本地起始；Spike 源默认错峰启动；阈值按层分组（输入/隐藏/输出）。

---

## 1) 实验一：K 定标（跨 DRAM 配置）

目的：在不同 DRAM 配置下确定稳健的 `k`，验证 sweep 与微基准一致性并回填。

参数网格（建议）
- DRAM 配置：至少覆盖 DDR4 OpenRow；HBM2 需去除 RandomTranslation 再测。后续可扩至 DDR5/LPDDR5X（需新增 cfg）。
- 固定项：`Lmax ∈ {32, 64, 128} KiB`；行窗口关闭；`sort=bank_row`；`dur ∈ {100us, 2ms}`。

运行（示例）
```bash
# 数据驱动 sweep（dur=100us/2ms；基线 k=0 自动作为时延基准）
python3 sst_dram_si/tools/k_calibrate.py --dur 100us --sort bank_row --cfg sst_dram_si/local_run_config.json
python3 sst_dram_si/tools/k_calibrate.py --dur 2ms   --sort bank_row --cfg sst_dram_si/local_run_config.json

# 微基准 + 拟合（设置下限避免回填0；通过环境变量指定 RAMU cfg）
KCAL_RAMU_CFG=sst_dram_si/configs/ramulator2_ddr4_openrow.cfg \
  ./sst sst_dram_si/test_kcal_bench.py | tee sst_output_data/run_kcal_bench_ddr4.log

python3 sst_dram_si/tools/k_from_bench.py \
  --csv sst_dram_si/stats/kcal/bench_results.csv \
  --cfg sst_dram_si/local_run_config.json \
  --scene row_hit --percentile 0.75 --min-bytes 1024 \
  --out sst_dram_si/stats/kcal/k_fit_summary.json
```

产物
- Sweep：`sst_dram_si/stats/kcal/summary_k_100us_*.csv|.json`、`summary_k_2ms_*.csv|.json`
- Bench：`sst_dram_si/stats/kcal/bench_results.csv`、`k_fit_summary.json`
- 汇总表（每 cfg 一行）：`{cfg, k_sweep_best_100us, k_sweep_best_2ms, k_fit_row_hit, k_fit_row_switch, k_final}`

验收
- sweep 得到的 `k_final` 与 bench 回填接近（允许最小下限差异）。
- 使用 `k_final` 运行后：`avg_burst_bytes ↑`、`reqs_per_mib ↓`，且 `avg_read_latency_0` 不恶化（≤ 基线±1%）。

---

## 2) 实验二：SRAM/DRAM 峰值与容量评估

目的：在目标规模与发放率下量化 **SB/在途/累加器** 的峰值占用，评估 **200MB SRAM** 是否足够；必要时评估“页化累加 + mini-scatter/溢写”。

参数网格（建议）
- 发放率：`f ∈ {1%, 3%, 5%}`（通过数据集与切片参数间接控制；以窗口 CSV 中 `avg_activity_f` 验证实际 f）
- 行窗口：`row_window_bytes ∈ {16, 32, 64} KiB` × `row_window_timeout_ns ∈ {0, 300, 600}`
- 固定：`k=2048B`，`Lmax ∈ {64,128} KiB`，`sort=bank_row`

运行（示例）
```bash
# 单PE 100us/2ms/5ms 探针（建议跑2ms起）
./sst sst_dram_si/test_dram_si_single_pe.py | tee sst_output_data/run_peak_2ms.log

# 行窗口批量扫参（自动派生 avg_burst/reqs_per_mib/avg_latency）
python3 sst_dram_si/tools/sweep_row_window.py --dur 100us
python3 sst_dram_si/tools/sweep_row_window.py --dur 2ms
```

统计项（需读取/近似）
- SB：`gas_buffer_occupancy_bytes`（直方图近似峰值；可取最大桶代表峰值）。
- 在途：`gas_inflight_peak`（采样和，近似峰值）。
- 累加器：`gas_acc_high_watermark_bytes_total`、`gas_acc_spill_records_total`、`gas_acc_spilled_bytes_total`。
- 基础：`gas_unique_reads/bytes`、`gas_row_window_*`、`gas_total_bursts/payload`、`avg_read_latency_0`（stdout）。

产物（汇总 CSV）
- `{cfg, f, row_win_bytes, timeout, k, Lmax, sb_bytes_peak≈max_bin, inflight_peak≈max_bin, acc_hwm, spilled_bytes, avg_burst_bytes, reqs_per_mib, avg_read_latency_0}`

验收
- 在 200MB 约束下给出“可运行的安全区间”（参数范围）。
- 若超限：开启“页化累加 + mini-scatter/溢写”，`acc_hwm` 受控，且性能指标不显著退化。

说明
- 当前峰值指标以直方图/采样近似，后续可新增 Max 型统计或将峰值写入窗口 CSV 以增强精度。

---

## 3) 实验三：NoC 单步时延（4×4）

目标：在 4×4/mesh 上比较四方案（baseline/slice/gas/sram）的单步端到端时延与网络负载。

阶段推进
- P0（Spike-only + 本地DRAM）：用现有脚本直接开跑，产出消息量/负载（延迟分布暂缺）。
- P1（Spike + 读流量，现实/理想上界）：需要新增“轨迹驱动”或在 NIC 采集时延与导入 granule 读流量（见“扩展”）。

运行（P0，使用 test_noc_timestep.py；注意用 `--` 传递脚本参数）
```bash
# 4×4，100us，链路 32GiB/s，flit=32B（脚本内已统一），四方案：
./sst sst_dram_si/test_noc_timestep.py -- --scenario baseline --mesh 4 --time 100us --bw 32GiB/s --in-lat 10ns --out-lat 10ns
./sst sst_dram_si/test_noc_timestep.py -- --scenario slice    --mesh 4 --time 100us --bw 32GiB/s --in-lat 10ns --out-lat 10ns
./sst sst_dram_si/test_noc_timestep.py -- --scenario gas      --mesh 4 --time 100us --bw 32GiB/s --in-lat 10ns --out-lat 10ns
./sst sst_dram_si/test_noc_timestep.py -- --scenario sram     --mesh 4 --time 100us --bw 32GiB/s --in-lat 10ns --out-lat 10ns

# 可选：合成3%流量（仅用于 P0 基线注入/热点热图；多播建模使用 P1 驱动）
./sst sst_dram_si/test_noc_timestep.py -- --scenario gas --mesh 4 --time 100us --bw 32GiB/s --firing 0.03

# 汇总（若生成了 CSV 统计）
python3 sst_dram_si/tools/plot_noc_timestep.py \
  --csv sst_dram_si/analysis/noc_timestep_stats.csv \
  --out sst_dram_si/analysis/noc_timestep_summary.csv
```

产物
- `sst_dram_si/analysis/noc_timestep_stats.csv`（明细）
- `sst_dram_si/analysis/noc_timestep_summary.csv`（汇总：包/负载/计数）

验收（P0）
- 比较四方案的消息注入/路由器负载曲线；热点端口分布合理；GAS 方案注入量应低于基线。
- 时延分布列（均值/P95/P99）在 P0 暂缺；待 P1 小改后补齐。

扩展（P1 能力，树型多播，flit=32B）
- 时延采样（SST 内测）：`SnnDL.SnnNIC` 已开启 `msg_latency_ns` 直方图。若 `analysis/noc_timestep_stats.csv` 未出现，可先用 P1 驱动作为主口径。
- 读流量 + 多播（主路径）：使用 `tools/noc_trace_driver.py` 重放 granules/spikes 队列，支持 `--multicast tree|replicate`，统一 flit=32B。
  - 真实 granules：来自单PE或mesh导出的 `sst_dram_si/analysis/granules*.csv`；stage 时间：`sst_dram_si/stats/stage_events_db_100us.csv`
  - 运行（树型多播）：
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
  - 复制单播对照：`--multicast replicate` 输出 `noc_trace_summary_replicate.csv`
  - 备注：spike 多播需提供 `spikes.csv`（`SnnNIC.export_spike_csv` 或 mesh 导出）；读流量对比与多播优势主要体现在 spike 类消息。

远程占比敏感性（读侧，合成 granules）
- 生成 100% 远程：`python3 sst_dram_si/tools/gen_synth_granules.py --size 4 --count 20000 --avg-bytes 2048 --dur-ns 100000 --out sst_dram_si/analysis/granules_synth_100p_remote.csv`
- 制作目标占比：
  - 5%：`python3 sst_dram_si/tools/make_remote_ratio.py --in sst_dram_si/analysis/granules_synth_100p_remote.csv --out sst_dram_si/analysis/granules_remote5.csv --remote 0.05`
  - 20%：`python3 sst_dram_si/tools/make_remote_ratio.py --in ... --out sst_dram_si/analysis/granules_remote20.csv --remote 0.20`
  - 50%：`python3 sst_dram_si/tools/make_remote_ratio.py --in ... --out sst_dram_si/analysis/granules_remote50.csv --remote 0.50`
- 重放（树型多播示例）：
  - `python3 sst_dram_si/tools/noc_trace_driver.py --granules sst_dram_si/analysis/granules_remote5.csv  --bw 32GiB/s --size 4 --multicast tree --out sst_dram_si/analysis/noc_remote5_tree.csv`
  - `python3 sst_dram_si/tools/noc_trace_driver.py --granules sst_dram_si/analysis/granules_remote20.csv --bw 32GiB/s --size 4 --multicast tree --out sst_dram_si/analysis/noc_remote20_tree.csv`
  - `python3 sst_dram_si/tools/noc_trace_driver.py --granules sst_dram_si/analysis/granules_remote50.csv --bw 32GiB/s --size 4 --multicast tree --out sst_dram_si/analysis/noc_remote50_tree.csv`
- 产物：`p95/p99` 随远程占比、带宽、缓冲变化的曲线；`edge_flits/消息量` 堆叠。

真实端到端分解（事件成对 + 多窗）
- 背景：短跑时 `EndApply/Scatter` 可能因空窗/极少读而缺失。已在内核加入 `emit_stage_events_lenient=1` 宽松开关，并在 `BeginGather/BeginScatter` 追加写行，保证事件成对落盘。
- 采集：
  ```bash
  ./sst sst_dram_si/test_dram_si_single_pe.py -- --time 100us   # 或 5ms（推荐，均值更稳）
  # 输出：sst_dram_si/stats/stage_events_db_100us.csv（BeginGather/BeginApply/EndApply/BeginScatter/EndScatter）
  ```
- 重放 + 分解（以 remote50、tree 为例）：
  ```bash
  python3 sst_dram_si/tools/noc_trace_driver.py \
    --granules sst_dram_si/analysis/granules_remote50.csv \
    --bw 32GiB/s --size 4 --multicast tree \
    --out sst_dram_si/analysis/noc_remote50_tree.csv

  python3 sst_dram_si/tools/derive_end2end_breakdown.py \
    --stages sst_dram_si/stats/stage_events_db_100us.csv \
    --noc    sst_dram_si/analysis/noc_remote50_tree.csv \
    --granules sst_dram_si/analysis/granules_remote50.csv \
    --out    sst_dram_si/analysis/end2end_remote50_real.csv
  ```
- 兜底（短跑严格成对）：
  ```bash
  python3 sst_dram_si/tools/make_stage_schedule.py \
    --windows 50 --gather-ns 200 --apply-ns 40 --scatter-ns 40 \
    --start-ns 0 --out sst_dram_si/analysis/gas_stage_sched.csv
  python3 sst_dram_si/tools/derive_end2end_breakdown.py \
    --stages sst_dram_si/analysis/gas_stage_sched.csv \
    --noc    sst_dram_si/analysis/noc_remote50_tree.csv \
    --granules sst_dram_si/analysis/granules_remote50.csv \
    --out    sst_dram_si/analysis/end2end_remote50_sched.csv
  ```

M0/M1 映射（同步导出）
- M0（post-owned，默认） 与 M1（pre-owned）两种映射用于敏感性对照。
- 若 mesh 场景缺权重文件：可先用现有 granules.csv 做 owner/req 重映射生成 M1 对照；或将 mesh 切换至“事件权重回退”模式后真实导出再重放。
  - 运行轻量驱动：
    ```bash
    python3 sst_dram_si/tools/noc_trace_driver.py \
      --granules sst_dram_si/analysis/granules.csv \
      --size 4 --dur 100us --flit-bytes 32 --bw-bytes-per-ns 32 \
      --hop-lat-ns 2 --in-lat-ns 1 --out-lat-ns 1 \
      --out sst_dram_si/analysis/noc_trace_summary.csv
    ```
  - 输出：`sst_dram_si/analysis/noc_trace_summary.csv`，示例行：`read_req,64,avg_ns,p50_ns,p95_ns,p99_ns` 与 `read_resp,...`

说明
- 当前 `test_noc_timestep.py` 默认 flit=8B、单VN；若需 32B/flit，可在脚本中将 `NOC_FLIT_SIZE` 改为 `"32B"` 并相应调整带宽/延迟口径。

---

## 4) 能耗评估

目的：给出 `energy_total / avg_power / (可选)EDP`，展示 GAS 的能效优势。

运行（示例）
```bash
./sst sst_dram_si/test_dram_si_single_pe.py | tee sst_output_data/run_energy_100us.log
python3 sst_dram_si/tools/derive_gas_metrics.py \
  sst_dram_si/stats/ctrl_probe_100us.csv \
  --stdout sst_output_data/run_energy_100us.log
```

产物/派生
- `energy_total/energy_cmd/energy_bg` 与 `sim_time_s`；`avg_power = energy_total / sim_time_s`。
- （可选）EDP：在 DRAM 路径可用 `avg_read_latency_0` 粗估；NoC 端待 P1 采样后补。

验收
- 方案2（GAS）在 `energy_total` 或 `EDP` 至少一项优于方案1/4，且趋势随行窗口/`k` 合理。

---

## 5) 复现与打包（Artifact）

建议目录结构
```
repros/
  configs/<dram_cfgs>.json
  grids/<rowwin_grid>.yaml
  runscripts/
    run_k_sweep.sh
    run_rowwin_grid.sh
    run_noc_compare.sh
  stats/   # 原始CSV
  summary/ # 汇总CSV
  figs/    # 出图
```

一键脚本（示例命令组合）
```bash
# K-sweep + bench + 回填
python3 sst_dram_si/tools/k_calibrate.py --dur 100us --sort bank_row --cfg sst_dram_si/local_run_config.json
KCAL_RAMU_CFG=sst_dram_si/configs/ramulator2_ddr4_openrow.cfg ./sst sst_dram_si/test_kcal_bench.py
python3 sst_dram_si/tools/k_from_bench.py --csv sst_dram_si/stats/kcal/bench_results.csv \
  --cfg sst_dram_si/local_run_config.json --scene row_hit --percentile 0.75 --min-bytes 1024 \
  --out sst_dram_si/stats/kcal/k_fit_summary.json

# 行窗口网格
python3 sst_dram_si/tools/sweep_row_window.py --dur 2ms

# 4×4 NoC（四方案）
sst sst_dram_si/test_noc_timestep.py --scenario gas --mesh 4 --time 100us --bw 32GiB/s --in-lat 10ns --out-lat 10ns
```

Artifact 验收
- 新环境可一键跑通；随机种子固定（如适用）；汇总表头一致；图表可复现。
- 阶段事件序号/窗口计数匹配；跑分时可关闭阶段事件 CSV 以减噪。

---

## 指标口径（统一说明）
- NoC：`latency_ms_step_mean/p95/p99`（step 开始→最后一条相关消息到达）、`injected/delivered_{flits,bytes}`、`utilization_%(port×dir)`、`congestion_ratio`。
- DRAM：`avg_burst_bytes、reqs_per_mib、row_hit%、avg_read_latency_0`（Ramulator2 stdout）。
- 端到端：`t_total = t_DRAM_wait + t_NoC + t_compute`（报告比例）。

---

## 风险与兜底
- bank_row 未对齐：自动退化为 row；汇总中单列说明。
- SB 双缓冲未实装：报告“现实 vs 理想上界”两条曲线。
- 微基准回填为 0：加 `--min-bytes ≥ 1KiB`，以 sweep 结果为准。
- SRAM 不足：启用“页化累加 + mini-scatter/溢写”，评估吞吐/时延权衡。

---

## 附录：脚本与路径速览
- 单PE DRAM：`sst_dram_si/test_dram_si_single_pe.py`
- K 定标：`sst_dram_si/tools/k_calibrate.py`、`sst_dram_si/test_kcal_bench.py`、`sst_dram_si/tools/k_from_bench.py`
- 行窗口 sweep：`sst_dram_si/tools/sweep_row_window.py`
- 指标派生：`sst_dram_si/tools/derive_gas_metrics.py`
- 4×4 NoC：`sst_dram_si/test_noc_timestep.py`、汇总：`sst_dram_si/tools/plot_noc_timestep.py`
- DRAM 配置：`sst_dram_si/configs/ramulator2_ddr4_openrow.cfg`（OpenRow，含 DRAMPower）；HBM2 配置见同目录（含 RandomTranslation）。


---

## 4) 实验四：基线（方案1）vs GAS 对照（单PE+Mesh）
（互链参考：GAS 访存设计与 4×4 Mesh 方法学详见 `sst_dram_si/GAS访存与实验方案说明.md` 第 5 节）

目的：在相同数据与时序设定下，对比“基线切片轮换（8 次）”与“GAS 阶段化合并”的 DRAM 与 NoC 表现，形成统一的判定口径与参数建议。

统一设置（建议）
- 地址映射：`bank_bits/bank_shift: "auto"`；排序优先 `gas_sort_policy: "bank_row"`（若检测到随机翻译则自动退化为 `row`）。
- DRAM 配置：DDR4 OpenRow（或此前定标用的同一配置）。
- 时长：2ms（快速）或 5ms（稳态）。
- k/Lmax：采用第 1 节定标得到的 `k_final`；`Lmax ∈ {64,128}KiB` 二选一固定。
- 行窗口：提供两组对照——关闭（仅细合并）与开启（如 `row_window_bytes=32KiB, row_window_timeout_ns=300`）。

单PE（DRAM）对照
1) 基线运行（只读切片、无合并）：
```json
{
  "gas_enable": false,
  "scheme1_enable": true,
  "scheme1_slices": 8,
  "apply_acc_enable": 0,
  "row_window_enable": false
}
```
```bash
./sst sst_dram_si/test_dram_si_single_pe.py | tee sst_output_data/run_baseline_2ms.log
```

2) GAS 运行（阶段化合并）：
```json
{
  "gas_enable": true,
  "scheme1_enable": false,
  "gas_window_auto": true,
  "gap_merge_k_bytes": <k_final>,
  "burst_bytes_max": 65536,
  "row_window_enable": true,
  "row_window_bytes": 32768,
  "row_window_timeout_ns": 300,
  "apply_acc_enable": 0
}
```
```bash
./sst sst_dram_si/test_dram_si_single_pe.py | tee sst_output_data/run_gas_2ms.log
```

产物与口径（DRAM）
- 控制器摘要（stdout）：`avg_read_latency_0`、`row_hits/misses/conflicts`。
- 聚合 CSV：
  - 基线：`scheme1_bytes_read`（如启用）与父级直方图（请求大小/在途并发/端到端延迟）。
  - GAS：`gas_unique_reads/bytes`、`gas_row_window_triggers/bytes`、`gas_total_bursts/payload`、`gas_inflight_peak`、`gas_buffer_occupancy_bytes`。
- 判定（期望趋势）：
  - `avg_burst_bytes ↑`、`reqs_per_mib ↓`，`avg_read_latency_0` 不劣于基线（±1% 内）。
  - 行窗口开启时，`gas_row_window_triggers ↑`、有效载荷比例↑（`payload/cover`）。

4×4 Mesh（NoC）对照（主入口：test_noc_timestep.py）
1) P0 四方案直跑（示例，100us，bw=32GiB/s）：
```bash
./sst sst_dram_si/test_noc_timestep.py -- --scenario baseline --mesh 4 --time 100us --bw 32GiB/s
./sst sst_dram_si/test_noc_timestep.py -- --scenario slice    --mesh 4 --time 100us --bw 32GiB/s
./sst sst_dram_si/test_noc_timestep.py -- --scenario gas      --mesh 4 --time 100us --bw 32GiB/s
./sst sst_dram_si/test_noc_timestep.py -- --scenario sram     --mesh 4 --time 100us --bw 32GiB/s
```

2) P1 轨迹重放与端到端分解（统一树型多播，flit=32B）：
```bash
python3 sst_dram_si/tools/noc_trace_driver.py \
  --granules sst_dram_si/analysis/granules.csv \
  --stages   sst_dram_si/stats/stage_events_db_100us.csv \
  --spikes   sst_dram_si/analysis/spikes.csv \
  --bw 32GiB/s --size 4 --multicast tree \
  --out sst_dram_si/analysis/noc_trace_summary_tree.csv

python3 sst_dram_si/tools/derive_end2end_breakdown.py \
  --stages sst_dram_si/stats/stage_events_db_100us.csv \
  --noc    sst_dram_si/analysis/noc_trace_summary_tree.csv \
  --granules sst_dram_si/analysis/granules.csv \
  --out   sst_dram_si/analysis/end2end_breakdown.csv
```

判定（NoC，统一 flit=32B）
- 基线注入量与边缘链路流量显著高于 GAS，端口热点更集中；GAS 的 p95/p99 时延更低或在相同带宽下拥塞阈值右移。

可选扩展
- 远程占比：以 `make_remote_ratio.py` 生成 5/20/50% 子集，分别重放，比较两方案在远程占比上的 p95/p99 斜率差异；
- 行窗口灵敏度：固定 `k_final`，对 `row_window_bytes/timeout_ns` 做 3×3 网格，选取“平均突发↑、请求密度↓、容量峰值受控”的折中点。

Mesh 真实对照（说明）
- 若需真实 mesh 轨迹：短跑用 `test_mesh_4x4.py` 产出 `granules_mesh.csv/spikes_mesh.csv`（`MESH_WEIGHT_MODE=event`，`MESH_MAPPING_MODE=post|pre`），再回到 `test_noc_timestep.py` 的 `--replay` 路径重放与分解；
- 当前环境曾遇退出冲突，已提供 mesh‑synthetic 的远程 20%/50% 对照作为替代；后续稳定性裁剪后，将继续用 `test_mesh_4x4.py` 作为“CSV 生产者”，主跑脚本保持 `test_noc_timestep.py` 不变。
