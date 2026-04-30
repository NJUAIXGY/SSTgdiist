# BCSR10k 论文级实验矩阵（Freeze vs NoFreeze(N1)）2026-01-22

> 目标：为论文级对比提供“可复现、低噪声、口径统一”的实验运行方式。  
> 核心对比：`exec_mode=gas` vs `exec_mode=naive_raw`，并进行 `L1 on/off`、`step_activation_fraction sweep`、`repeat×2`。

---

## 0. 统一口径（所有 run 必须一致）

### 0.1 固定输入/结构
- 模型：`sst_dram_si/test_mesh_4x4.py`
- 权重数据集（默认）：`sst_dram_si/weights/bcsr_global_16pe_fanout256_10k`
- 终止语义：**step-limited**（不使用 stop-at time）
  - `MESH_MAX_STEPS>0` 会强制 `GLOBAL_STEP_SYNC_ENABLE=1`
- 实验维度：
  - `exec_mode ∈ {gas, naive_raw}`
  - `MESH_L1_ENABLE ∈ {0,1}`
  - `MESH_STEP_ACTIVATION_FRACTION ∈ {0.001,0.01,0.05,0.1}`（可按论文需要调整）
  - `repeat = 2`（同 seed 重跑两次，允许轻微漂移）

### 0.2 推荐固定参数（论文默认）
- `MESH_MAX_STEPS=4`（避免只测到冷启动）
- `MESH_STEP_ACTIVATION_SEED=314159`
- `MESH_STEP_ACTIVATION_FANOUT=256`
- `MESH_VALIDATE_PROFILE=paper`

---

## 1. 动力学 Profile 定义（避免“freeze 粘住”）

> 关键原则：**不修改** `sst_dram_si/local_run_config.json`；所有差异都由脚本显式 `export` 覆盖，并写入 `meta.json`，保证 freeze→nofreeze 可一键切换。

### 1.1 Freeze（Phase-A）
- 定义：跨步不积累膜电位（更像“只做访存/路由闭环”的负载）
- 生效 env：
  - `MESH_STEP_RESET_MEM_EACH_STEP=1`
  - `MESH_ALLOW_ZERO_FIRING_LONG=1`（冻结态允许 `neurons_fired_total==0` 通过 validator）
  - `MESH_STEP_ACTIVATION_EVENT_WEIGHT=0.0`
    - 说明：`StepActivationSubsystem` 当前注释为“预留字段”，此处主要用于 provenance（结果口径记录），不作为功能依赖。
- 运行脚本（单次/矩阵）：
  - `sst_dram_si/tools/run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_with_time.sh`
  - `sst_dram_si/tools/run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_matrix.sh`

### 1.2 NoFreeze（N1）
- 定义：保持 `step_random_activation`，允许跨步传播（不做每步膜电位复位）
- 生效 env：
  - `MESH_STEP_RESET_MEM_EACH_STEP=0`
  - `MESH_ALLOW_ZERO_FIRING_LONG=0`
  - `MESH_STEP_ACTIVATION_EVENT_WEIGHT=1.0`（provenance-only，同上）
- 运行脚本（新增）：
  - `sst_dram_si/tools/run_mesh_bcsr10k_nofreeze_exec_mode_l1_sweep_with_time.sh`
  - `sst_dram_si/tools/run_mesh_bcsr10k_nofreeze_exec_mode_l1_sweep_matrix.sh`

---

## 2. 如何运行（推荐流程）

### 2.1 Smoke：先跑 1 step 验证切换不粘住

> 建议默认开启静默运行以减少 `mesh_run.log` 的 IO 噪声：`export MESH_QUIET=1`。  
> 静默仅影响 mesh_template(Python) 的 print，不影响 C++ 关键 marker 与统计落盘。

#### Freeze smoke（gas）
```bash
export "MESH_QUIET=1"
export "MESH_VALIDATE_PROFILE=paper"
export "MESH_MAX_STEPS=1"
export "MESH_L1_ENABLE=0"
export "MESH_STEP_ACTIVATION_FRACTION=0.001"
export "MESH_STEP_ACTIVATION_SEED=314159"
export "MESH_STEP_ACTIVATION_FANOUT=256"
sst_dram_si/tools/run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_with_time.sh gas
```

#### NoFreeze smoke（gas）
```bash
export "MESH_QUIET=1"
export "MESH_VALIDATE_PROFILE=paper"
export "MESH_MAX_STEPS=1"
export "MESH_L1_ENABLE=0"
export "MESH_STEP_ACTIVATION_FRACTION=0.001"
export "MESH_STEP_ACTIVATION_SEED=314159"
export "MESH_STEP_ACTIVATION_FANOUT=256"
sst_dram_si/tools/run_mesh_bcsr10k_nofreeze_exec_mode_l1_sweep_with_time.sh gas
```

检查点：
- `validation.log` 末尾 `fail=0`
- `meta.json` 中：
  - Freeze：`model.step_reset_mem_each_step=1`
  - NoFreeze：`model.step_reset_mem_each_step=0`

### 2.2 论文矩阵：完整 sweep（repeat×2）

#### Freeze matrix
```bash
export "MESH_QUIET=1"
export "MESH_VALIDATE_PROFILE=paper"
export "MESH_MAX_STEPS=4"
export "MESH_STEP_ACTIVATION_SEED=314159"
export "MESH_STEP_ACTIVATION_FANOUT=256"
sst_dram_si/tools/run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_matrix.sh
```

#### NoFreeze matrix（N1）
```bash
export "MESH_QUIET=1"
export "MESH_VALIDATE_PROFILE=paper"
export "MESH_MAX_STEPS=4"
export "MESH_STEP_ACTIVATION_SEED=314159"
export "MESH_STEP_ACTIVATION_FANOUT=256"
sst_dram_si/tools/run_mesh_bcsr10k_nofreeze_exec_mode_l1_sweep_matrix.sh
```

---

## 3. 输出结构（run_dir 必含关键产物）

每个 run 目录包含（脚本自动生成）：
- `mesh_run.log`：SST 输出（应保持安静；verbose=0 不刷屏）
- `time.txt`：`/usr/bin/time -v` wallclock/最大内存等
- `meta.json`：provenance（schema_version=1），包含：
  - `model.step_reset_mem_each_step`、`model.step_activation_event_weight`
  - `environment.MESH_STEP_RESET_MEM_EACH_STEP` 等 env 记录
- `effective_config.json`：GAS/memory 侧实际生效参数（granularity/merge 等）
- `essential_summary_mesh.json`：论文主统计口径（统一入口）
- `validation.log`：验收结果（paper profile）

输出目录组织（按 group/mode/l1/fraction）：
```
sst_dram_si/outputs_large/paper2/<run_group>/<mode>/l1_<0|1>/frac_<tag>/<timestamp>/
```

---

## 4. 汇总与作图（建议并行工作流）

### 4.1 汇总 TSV
对某个 group-root 生成矩阵汇总（freeze/nofreeze 均可用同一个脚本）：
```bash
python3 "sst_dram_si/tools/summarize_mesh_bcsr10k_freeze_exec_mode_l1_sweep.py" \
  --root "sst_dram_si/outputs_large/paper2/<run_group>"
```

产物：
- `<root>/matrix_summary.tsv`
- `<root>/matrix_ratios.tsv`
- `<root>/inconclusive_runs.tsv`（如存在）

### 4.2 论文主指标（建议）
- **Memory traffic（主口径）**：`memctrl.bytes_est_total`、`memctrl.requests_received_GetS`
- **Runtime（主口径）**：`wall_s`（来自 `time.txt`）、`model.sim_time_actual_ns`
- **补充**：`memory.memory_bytes`（SnnDL 上游逻辑 read bytes，用于解释“请求粒度/overfetch”差异）

### 4.3 多智能体/并行建议（可在多终端并行）
- Workstream A：跑矩阵（freeze / nofreeze 各一组）
- Workstream B：汇总 TSV + 自动过滤 FAIL/WARN（paper profile）
- Workstream C：从 TSV 生成图表与论文表格（bytes、gets、wall、sim_ns vs fraction）
