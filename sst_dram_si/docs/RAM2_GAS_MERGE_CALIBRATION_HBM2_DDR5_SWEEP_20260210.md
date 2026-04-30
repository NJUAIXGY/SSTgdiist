# Ramulator2（HBM2/DDR5）GAS 粗/细合并参数标定：下一步 Sweep 计划（cacheline 默认语义）

日期：2026-02-10

## 目标

在 **cacheline 作为默认搬运语义**（`MESH_GAS_MERGE_POLICY=cacheline`）下，针对不同 DRAM 后端（Ramulator2 的 **HBM2 / DDR5**）标定 GAS 的合并参数：

- 细合并：`gap_merge_k_bytes`（k）、`burst_bytes_max`（Lmax）
- 粗合并：`row_window_bytes`、`row_window_timeout_ns`

产出：

1) 每个后端各自的“推荐参数组合”（k/Lmax/rowwin/tmo）。  
2) 结果表 `calibration_results.tsv`（便于论文表格/图表进一步加工）。  

## 实验固定项（必须一致）

### 模型与规模

- 模型：`sst_dram_si/test_mesh_4x4.py`
- 规模：16PE（4x4），`MESH_MAX_STEPS=4`
- 执行：`MESH_EXEC_MODE=gas`

### 语义对齐（strict-step）

- 全局 step 同步：`MESH_GLOBAL_STEP_SYNC=1`
- step 完成口径：`MESH_GLOBAL_STEP_DONE_POLICY=drain`
- 最小排空周期：`MESH_GLOBAL_STEP_DRAIN_MIN_CYCLES=200`
- step 内顺序门控：`MESH_GAS_STEP_SEQ_GATE_ENABLE=1`

### 冻结动力学（read-only）

目标口径：**只读权重，不积累膜电位、不触发阈值**（用于“访存/时间”公平对比）。

- `MESH_FREEZE_READONLY=1`
- `MESH_READONLY_V_THRESH=1e9`
- `MESH_READONLY_TAU_MEM=0.001`
- `MESH_STEP_RESET_MEM_EACH_STEP=1`

### 工作负载点（标定默认点）

- seed：`MESH_STEP_ACTIVATION_SEED=314159`
- fanout：`MESH_STEP_ACTIVATION_FANOUT=256`
- fraction：`MESH_STEP_ACTIVATION_FRACTION=0.03`
- BCSR 数据集：`sst_dram_si/weights/bcsr_global_16pe_fanout256_10k`（不生成新数据集）

### 其他

- L1：默认关（`MESH_L1_ENABLE=0`）
- QUIET：开（`MESH_QUIET=1`）
- 校验 profile：`MESH_VALIDATE_PROFILE=paper`
- 一致路径：强制 staging（`MESH_GAS_FORCE_DEFER=1`，保证 k/rowwin/tmo=0 时仍走完整 GAS 分段路径）

## 指标与验收

### 1) Correctness gate（必须）

以 `validation.log` 与 `essential_summary_mesh.json` 为准：

- `run.no_emergency_shutdown` 通过
- `steps_completed == 4`（global step 控制器按 4 step 正常退出）
- `gas.*` 与 `memhierarchy.*` 核心字段齐全（否则视为 FAIL/无效点）

### 2) 性能口径（用于选最优）

以 `calibration_results.tsv` 的列为准（脚本自动提取）：

- `sim_cycles`（主目标，越小越好；**用 SST 仿真周期/时间作为“模型性能”口径**）
- `wall_s`（辅助口径：只是“主机运行耗时”，用于排障/估算跑完需要多久，不作为体系结构结论）
- `memctrl_bytes` / `memctrl_gets`（事务与流量）
- `gas_unique_bytes`、`gas_payload_bytes`、`gas_overfetch_ratio`（合并覆盖/有效负载/过取比例）
- `row_hit_rate`、`avg_read_lat`（Ramulator2 指标）

## 后端选择（必须用 NoTranslation 版本）

为了保留地址局部性与 bank×row 结构，标定使用：

- HBM2：`sst_dram_si/configs/ramulator2_hbm2_notrans.cfg`
- DDR5：`sst_dram_si/configs/ramulator2_ddr5_notrans.cfg`

（`RandomTranslation` 版本会打散局部性，不利于观察 row-hit 与合并收益。）

## Sweep 方案（推荐：三阶段，逐维扫参）

> 原则：一次只扫一个维度，避免自适应策略干扰；所有候选点必须保证 `row_window_bytes <= Lmax` 且 `gap_k_bytes <= Lmax`。

### Phase 0：Preflight（每个后端 1 点）

目的：确保脚本/接口一致性，避免“伪失败污染 sweep”。

- 固定：`k=0, Lmax=8192, rowwin=0, tmo=0`
- 每个后端跑 1 次，必须 PASS 才进入 Phase A。

### Phase A：细合并（k / Lmax）

rowwin 关闭（`rowwin=0, tmo=0`），只扫 k/Lmax。

- HBM2_notrans：
  - `k ∈ {0, 64, 128, 256}`
  - `Lmax ∈ {4096, 8192}`
- DDR5_notrans：
  - `k ∈ {0, 64, 128, 256}`
  - `Lmax ∈ {8192, 16384}`

选点规则（每个后端独立选）：

1) 只在 PASS 点中选  
2) 先最小化 `wall_s`，再比较 `memctrl_bytes`（脚本 pick_best 逻辑一致）  
3) 同时记录 `gas_overfetch_ratio`（用于后续解释“为什么快/为什么慢”）

### Phase B：粗合并（row_window_bytes）

固定 Phase A 的最优 (k, Lmax)，tmo 固定 0：

- `rowwin ∈ {256, 512, 1024, 2048, 4096}`
- `tmo=0`

目的：找到“允许更大 gap 吸收”的安全区间；同时观察 overfetch 是否失控、row_hit 是否提升。

### Phase C：粗合并（row_window_timeout_ns）

固定 Phase A 最优 (k, Lmax) 与 Phase B 最优 rowwin：

- `tmo ∈ {0, 50, 100, 200}`

目的：用 timeout 控制“等待更多聚合 vs 提前 flush 段”的权衡，避免卡住或事务爆炸。

## 执行命令（可直接复制）

统一入口脚本：

- `sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh`

建议每个 run 加超时（防止单点卡死）：

- `MESH_CAL_SST_TIMEOUT_SEC=3600`（1h/点；Step=4 通常远小于此，仅用于保险）

### 1) Preflight：HBM2_notrans

```bash
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_hbm2_ddr5_v1 \
MESH_CAL_BACKENDS="ram2_hbm2_notrans" \
MESH_CAL_SWEEP_MODE=fine_only \
MESH_CAL_GAP_K_LIST="0" \
MESH_CAL_LMAX_LIST="8192" \
MESH_CAL_ROWWIN_LIST="0" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0" \
MESH_STEP_ACTIVATION_FRACTION=0.03 \
MESH_CAL_SST_TIMEOUT_SEC=3600 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh
```

### 2) Preflight：DDR5_notrans

```bash
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_hbm2_ddr5_v1 \
MESH_CAL_BACKENDS="ram2_ddr5_notrans" \
MESH_CAL_SWEEP_MODE=fine_only \
MESH_CAL_GAP_K_LIST="0" \
MESH_CAL_LMAX_LIST="8192" \
MESH_CAL_ROWWIN_LIST="0" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0" \
MESH_STEP_ACTIVATION_FRACTION=0.03 \
MESH_CAL_SST_TIMEOUT_SEC=3600 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh
```

### 3) Phase A：HBM2_notrans（k/Lmax）

```bash
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_hbm2_ddr5_v1 \
MESH_CAL_BACKENDS="ram2_hbm2_notrans" \
MESH_CAL_SWEEP_MODE=fine_only \
MESH_CAL_GAP_K_LIST="0 64 128 256" \
MESH_CAL_LMAX_LIST="4096 8192" \
MESH_CAL_ROWWIN_LIST="0" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0" \
MESH_STEP_ACTIVATION_FRACTION=0.03 \
MESH_CAL_SST_TIMEOUT_SEC=3600 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh
```

### 4) Phase A：DDR5_notrans（k/Lmax）

```bash
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_hbm2_ddr5_v1 \
MESH_CAL_BACKENDS="ram2_ddr5_notrans" \
MESH_CAL_SWEEP_MODE=fine_only \
MESH_CAL_GAP_K_LIST="0 64 128 256" \
MESH_CAL_LMAX_LIST="8192 16384" \
MESH_CAL_ROWWIN_LIST="0" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0" \
MESH_STEP_ACTIVATION_FRACTION=0.03 \
MESH_CAL_SST_TIMEOUT_SEC=3600 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh
```

### 5) Phase B/C（rowwin/tmo）

Phase A 跑完后，从同组 `calibration_results.tsv` 里取每个后端的 best (k,Lmax)。然后将 `MESH_CAL_GAP_K_LIST/MESH_CAL_LMAX_LIST` 收敛为单点，进入 coarse：

（示例：把 `<BEST_K>`、`<BEST_LMAX>`、`<BEST_ROWWIN>` 换成你选出的值）

```bash
# Phase B: rowwin sweep (tmo=0)
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_hbm2_ddr5_v1 \
MESH_CAL_BACKENDS="ram2_ddr5_notrans" \
MESH_CAL_SWEEP_MODE=two_phase \
MESH_CAL_GAP_K_LIST="<BEST_K>" \
MESH_CAL_LMAX_LIST="<BEST_LMAX>" \
MESH_CAL_ROWWIN_LIST="0 256 512 1024 2048 4096" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0" \
MESH_STEP_ACTIVATION_FRACTION=0.03 \
MESH_CAL_SST_TIMEOUT_SEC=3600 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh

# Phase C: timeout sweep (rowwin fixed)
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_hbm2_ddr5_v1 \
MESH_CAL_BACKENDS="ram2_ddr5_notrans" \
MESH_CAL_SWEEP_MODE=two_phase \
MESH_CAL_GAP_K_LIST="<BEST_K>" \
MESH_CAL_LMAX_LIST="<BEST_LMAX>" \
MESH_CAL_ROWWIN_LIST="<BEST_ROWWIN>" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0 50 100 200" \
MESH_STEP_ACTIVATION_FRACTION=0.03 \
MESH_CAL_SST_TIMEOUT_SEC=3600 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh
```

## 结果位置与后处理

- 结果表：`sst_dram_si/outputs_large/paper2/<group>/calibration_results.tsv`
- 每个点的 run_dir 里：`essential_summary_mesh.json`、`effective_config.json`、`validation.log`、`mesh_stats.csv`

建议后处理（后续单独做）：按 backend 分组，画 `wall_s` vs `memctrl_bytes` 的 Pareto；并对比 `row_hit_rate` 与 `gas_overfetch_ratio` 解释拐点。

---

## 下一步：Phase D（稳健性与 coarse 复核，建议优先做）

> 背景：在 `fraction=0.03` 的初步数据里，**coarse row-window（rowwin>0）几乎都让 overfetch 主导**（memctrl_bytes 与 wall 显著变差）。  
> 这并不意外：cacheline 语义下，最终仍会落到 cacheline 事务；row-window 吸洞会把段 span 拉大，从而扩大被拆分出来的 cacheline 数。
>
> 但为了“论文级结论”稳健，仍建议做两类复核：
> 1) 只扫 **更小的 rowwin**（避免一上来就进入病态 overfetch 区域）  
> 2) 做 **fraction 微扫**，确认 time-opt/bytes-opt 不是单点过拟合

### D1) coarse（rowwin/tmo）轻量复核：只扫小 rowwin

每个后端各选一个 fine 最优点作为固定基线（示例用当前观察到的 time-opt；你也可以替换为 bytes-opt）：

- HBM2_notrans：`k=128, Lmax=4096`（或更保守 `k=0, Lmax=4096`）
- DDR5_notrans：`k=256, Lmax=8192`（或更保守 `k=0, Lmax=8192`）

然后只扫：

- `rowwin ∈ {0, 64, 128, 256}`
- `tmo ∈ {0, 50, 100}`

执行示例（DDR5_notrans，注意：rowwin=0 也会被记录在结果里，便于同表对比）：

```bash
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_phaseD_rowwin_small_ddr5_v1 \
MESH_CAL_BACKENDS="ram2_ddr5_notrans" \
MESH_CAL_SWEEP_MODE=full_grid \
MESH_CAL_GAP_K_LIST="256" \
MESH_CAL_LMAX_LIST="8192" \
MESH_CAL_ROWWIN_LIST="0 64 128 256" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0 50 100" \
MESH_STEP_ACTIVATION_FRACTION=0.03 \
MESH_CAL_SST_TIMEOUT_SEC=3600 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh
```

验收/判断：
- 若所有 `rowwin>0` 点依旧明显更差：就可以把 **coarse merge 定性为“cacheline 默认语义下的负例/消融项”**，并在后续论文矩阵里默认禁用（rowwin=0,tmo=0）。
- 若出现少量“rowwin>0 且 wall 更好”的点：再把这些点拉到 Phase E（fraction 微扫）验证其稳定性。

### D2) fraction 微扫：验证 fine 最优点的稳健性

目的：确认 “time-opt / bytes-opt” 在不同负载点下不漂移得太厉害。

- fractions：`{0.01, 0.03, 0.05}`（必要时再扩 `0.1`）
- 只跑 `rowwin=0,tmo=0`（先把 coarse 变量隔离出去）
- 每个 fraction：各后端跑 2 点（time-opt / bytes-opt）

示例（DDR5_notrans，fraction=0.01）：

```bash
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_phaseD_frac0p01_ddr5_v1 \
MESH_CAL_BACKENDS="ram2_ddr5_notrans" \
MESH_CAL_SWEEP_MODE=fine_only \
MESH_CAL_GAP_K_LIST="0 256" \
MESH_CAL_LMAX_LIST="8192" \
MESH_CAL_ROWWIN_LIST="0" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0" \
MESH_STEP_ACTIVATION_FRACTION=0.01 \
MESH_CAL_SST_TIMEOUT_SEC=3600 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh
```

### D3) （可选，但论文更“好写”）DDR5 地址映射变体：最大化激发 GAS 的局部性恢复潜力

若你希望在论文里更清晰地展示 “GAS 的排序/分桶/合并确实能在更差的地址局部性下恢复性能”，建议把 DDR5 的 `AddrMapper` 作为“同一物理介质下的对照维度”：

- baseline：`ram2_ddr5_notrans`（ChRaBaRoCo）
- stress：`ram2_ddr5_notrans_mop4clxor`（MOP4CLXOR；更强扰乱）
- alt：`ram2_ddr5_notrans_robaraco`（RoBaRaCoCh；另一种线性映射）
- optional：`ram2_ddr5_notrans_x16_mop4clxor`（x16+扰乱；冲突更敏感）

这些 tag 已可直接用于校准脚本（见 `run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh` 的 backend case）。

---

## 已跑：Phase E（fraction=0.10，高负载点复核）

目的：补齐 Phase D2 里“必要时再扩 0.1”的高负载点，并同时覆盖 DDR5 映射变体，观察 `gap_k` 是否在更高负载下出现更明确的 time-opt 区间。

执行（fine_only；rowwin/tmo 固定为 0）：

```bash
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_phaseE_frac0p10_v1 \
MESH_CAL_BACKENDS="ram2_hbm2_notrans ram2_ddr5_notrans ram2_ddr5_notrans_mop4clxor ram2_ddr5_notrans_x16_mop4clxor" \
MESH_CAL_SWEEP_MODE=fine_only \
MESH_CAL_GAP_K_LIST="0 256" \
MESH_CAL_LMAX_LIST="8192" \
MESH_CAL_ROWWIN_LIST="0" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0" \
MESH_STEP_ACTIVATION_FRACTION=0.1 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh
```

结果位置：
- `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_cal_phaseE_frac0p10_v1/calibration_results.tsv`

核心结论（当前 workload + cacheline 语义下）：
- 对 HBM2_notrans / DDR5_notrans / DDR5_notrans_mop4clxor / DDR5_notrans_x16_mop4clxor：
  - `gap_k=0, Lmax=8192, rowwin=0, tmo=0` 同时是 **bytes-opt 与 time-opt**；
  - `gap_k=256` 在所有上述后端上都显著抬高 `memctrl_bytes`，并在映射扰乱（MOP4CLXOR/x16）场景下显著变慢。
- 因此：在论文矩阵里，建议把 `gap_k>0`、`rowwin>0` 都作为 **消融/负例**（展示其风险与对后端/映射的敏感性），默认配置保持 `gap_k=0,rowwin=0`。

---

## 下一步：Phase F（小范围 Pareto，目标：用 sim_cycles 证明“overfetch ↔ time”权衡是否存在）

背景：粗/细合并（gap/row-window）**必然可能引入 overfetch**；为了让论文“好写”，我们需要在 **模型时间（SST sim_cycles）** 口径下，找出是否存在：

- `sim_cycles` 更小（更快完成 4 step）
- 但 `memctrl_bytes` 更大（更多流量/overfetch）

### F0) 时间口径（必须统一）

- `sim_cycles` 来自每个 run 的 `essential_summary_mesh.json`：
  - 优先字段：`gas.cycle_cost`（注释口径：cycles@1GHz == ns）
  - 兜底字段：`model.sim_time_actual_ns`
- `wall_s` 只用于“跑完耗时”估算/排障；**不要用于体系结构结论**。

> 注：`run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh` 已将 `sim_cycles` 写入 `calibration_results.tsv`（列名 `sim_cycles`）。

### F1) 小范围 Pareto（探索）——先在“最可能受益”的 DDR5 stress 后端找拐点

选择一个最“merge-friendly”的点来找 Pareto 拐点：

- 后端：`ram2_ddr5_notrans_x16_mop4clxor`（并发更低 + 映射更扰乱；更容易让 row-hit 变得“值钱”）
- fraction：先用 `0.03`（中负载）；若出现候选 trade-off，再拉到 `0.10` 做复核
- 扫描网格（包含粗+细合并，但保持范围很小）：
  - `gap_k ∈ {0, 64, 128, 256}`
  - `Lmax ∈ {1024, 8192}`
  - `rowwin ∈ {0, 256}`
  - `tmo ∈ {0}`（先不引入第三个维度；避免矩阵爆炸）

执行示例（探索：DDR5_x16_mop4clxor，fraction=0.03）：

```bash
MESH_GAS_CAL_RUN_GROUP=dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_pareto_small_ddr5x16mop4_frac0p03_v1 \
MESH_CAL_BACKENDS="ram2_ddr5_notrans_x16_mop4clxor" \
MESH_CAL_SWEEP_MODE=full_grid \
MESH_CAL_GAP_K_LIST="0 64 128 256" \
MESH_CAL_LMAX_LIST="1024 8192" \
MESH_CAL_ROWWIN_LIST="0 256" \
MESH_CAL_ROWWIN_TIMEOUT_LIST="0" \
MESH_STEP_ACTIVATION_FRACTION=0.03 \
./sst_dram_si/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh
```

生成 Pareto 点（sim_cycles vs memctrl_bytes）：

```bash
python3 sst_dram_si/tools/pareto_from_calibration_results.py \
  --tsv sst_dram_si/outputs_large/paper2/dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_pareto_small_ddr5x16mop4_frac0p03_v1/calibration_results.tsv \
  --write
```

产物：
- `.../pareto_points.tsv`：直接可用于画图/表格（或再二次处理成 CSV）。

### F2) 小范围 Pareto（复核）——把“候选 trade-off 点”拉到另一负载/另一映射确认

当且仅当 Phase F1 出现满足下述条件的候选点，才进入复核：

- 候选点满足：`sim_cycles < baseline(sim_cycles)` 且 `memctrl_bytes > baseline(memctrl_bytes)`
  - baseline 定义：`gap_k=0,rowwin=0,Lmax=8192`（同一后端、同一 fraction）

复核建议（最小集合）：
- 同一后端：把 fraction 拉到 `0.10`（高负载）
- 另一后端：`ram2_ddr5_notrans`（映射更“正常”，检查是否只在 stress 才成立）
- 只跑候选点 + baseline（不要再扫全矩阵）

复核跑法：直接用同一个校准脚本，但把 `MESH_CAL_GAP_K_LIST/MESH_CAL_LMAX_LIST/MESH_CAL_ROWWIN_LIST` 收敛为单点/双点即可。

---

## 已跑：Phase F1（DDR5_x16_mop4clxor，fraction=0.03）结果（Pareto 塌缩）

运行组：
- `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_pareto_small_ddr5x16mop4_frac0p03_v1/`
  - `calibration_results.tsv`（PASS 点共 10 个：8 个 fine 点 + 2 个 rowwin=256 消融点）
  - `pareto_points.tsv`（由 `pareto_from_calibration_results.py --write` 生成）

结论（在 cacheline 默认语义下）：
- Pareto 前沿只有一个点：`gap_k=0,rowwin=0`（`Lmax` 不影响 `sim_cycles/memctrl_bytes`）。
- `gap_k>0` 会同时推高 `memctrl_bytes` 与 `sim_cycles`（被 baseline 完全支配）。
- `rowwin=256` 明显恶化，且在 `Lmax=8192` 时进入极端慢路径（`sim_cycles` 与 `memctrl_bytes` 均大幅上升）。

解释要点（为论文写作准备）：
- 由于 Apply 分桶已按 bank×row 聚类，且 cacheline 语义下“有效事务粒度”仍是 cacheline，吸洞/行窗（gap/rowwin）不会带来 row-hit 的结构性提升，反而引入 overfetch，
  因而在 `sim_cycles` 与 `memctrl_bytes` 两个目标上都更差。

---

## （新增）Workload 局部性旋钮：Clustered Pre 采样（用于“让粗/细合并显效”的对照）

背景：在 **uniform Bernoulli pre 采样** + **随机 fanout** 下，同一 bank×row 内往往只有很少 cacheline 请求，导致：
- row-hit 上限偏低；
- coarse/fine merge（尤其吸洞）很容易变成纯 overfetch（bytes 与 cycles 双输）。

为在不改变权重数据集的前提下，构造“可控的空间局部性”对照点，我们新增 StepActivation 的可选 pre 采样模式：
- `bernoulli`（默认）：逐神经元伯努利采样（历史行为不变）
- `clustered`：每个 core 选取若干段连续的 pre（制造列访问簇；更容易出现 bank×row 内的密集访问）

配置（仅脚本层环境变量；不要求改 local_run_config.json）：
- `MESH_STEP_ACTIVATION_PRE_PATTERN=clustered`
- `MESH_STEP_ACTIVATION_PRE_CLUSTER_LEN=64`（单位：neuron；0=自动默认 64）

注意：`clustered` 模式下，pre 选择为“按目标数量构造连续段”（近似匹配 `fraction` 的期望），与 `bernoulli` 的逐点独立采样在方差上不同；因此它主要用于**体系结构敏感性/消融**，不作为默认 workload 口径。

示例（DDR5_notrans，fraction=0.03，Step=4，read-only freeze）：
- 运行组：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_clusteredpre_trial_v1/`
- 观察：`row_hit_rate_total` 可显著抬升到 ~0.79（相比 uniform 模式常见的 ~0.3）

建议用法（论文叙事更稳健）：
1) 主结论仍以 uniform workload（`bernoulli`）为准，cacheline 默认语义下 `gap_k=0,rowwin=0` 作为推荐参数；
2) `clustered` 作为“可控局部性对照”，用于展示：当 row-hit 变得可提升时，粗/细合并的 overfetch 风险与收益边界如何变化（必要时再引入更小 rowwin/k 的微扫）。
