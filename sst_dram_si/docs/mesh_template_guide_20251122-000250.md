# Mesh 模版深入手册（4×4 Mesh）

版本时间：2026-01-16（面向论文级可复现回归：默认 step-limited）

更新说明：
- 2026-01-10：全局 Step/GAS 同步（`GLOBAL_STEP_SYNC_ENABLE=1`）场景下，GAS 三阶段（Gather/Apply/Scatter）默认改为“负载/显式完成驱动”，不再依赖固定 `window_cycles_*` 强制结束，用于消除多 PE/多 core 下的节奏抖动与发放归零风险。
- 2026-01-16（重要）：回归/论文模式统一采用 step-limited（指定仿真 `N` 个 global step 后停止），不再依赖引擎级 `stop-at`；同时引入可复现元数据 `meta.json(schema_version=1)` 与 `--profile paper` 严格验收。
- 2026-01-18（重要）：统一内存建模默认语义为 **cacheline 粒度**（更贴近主流 memHierarchy/DRAM）；增加 `effective_config.json` 记录最终生效参数，避免配置文件与实际行为不一致导致误读。

本手册面向当前 4×4 mesh 模版，覆盖：位置/启动（step-limited）/执行模式（gas vs naive）/输出产物与口径/关键配置/统计与验收/权重来源/常见问题。按本文档使用，可获得“论文级可复现”的结果喵～ (..•˘_˘•..)

---

## 0. 术语与核心原则（务必先读）
- global step（本文的 step）：由 `GlobalGasStepController` 广播 `START_STEP(seq)` 并以 `PE_DONE(seq)` 汇聚的同步步；step-limited 的停止条件以它为准。
- GAS window（窗口）：`GatherBufferIF` 自身生成的窗口序号/阶段事件（`BeginGather/BeginApply/BeginScatter/EndScatter`）；窗口数量可能与 global step 数不一一对应。
- 为什么必须 step-limited：引擎级 `stop-at` 会在 NoC/DRAM 仍有在途事务时硬截断仿真，导致统计口径不可复现；step-limited 会在完成并排空指定步数后自然结束。

---

## 1. 模版位置
- 运行工程：`"sst_dram_si"`
- 驱动脚本（默认 step-limited）：`"sst_dram_si/tools/run_mesh_with_time.sh"`
- RAM2 版本（默认 step-limited）：`"sst_dram_si/tools/run_mesh_with_time_ram2.sh"`
- 模型入口：`"sst_dram_si/test_mesh_4x4.py"`（RAM2 对应 `"sst_dram_si/test_mesh_4x4_ram2.py"`）
- 模版实现：`"sst_dram_si/mesh_template/"`

---

## 2. 快速启动（统一 step-limited）
### 2.1 一键回归（推荐）
默认脚本会设置 `MESH_MAX_STEPS` 的默认值（当前为 `2`），并在结束后自动生成 summary + 执行验收（默认 paper profile）。

```bash
cd "sst_dram_si"
./tools/run_mesh_with_time.sh
```

说明：
- 脚本会依次生成：`meta.json`（含 sha256 归档）、`essential_summary_mesh.json`、`validation.log`。
- 因为脚本 `set -e`，验收失败会直接返回非 0（用于回归门槛）。

### 2.2 明确指定跑几个 step（强烈建议写入实验记录）
```bash
cd "sst_dram_si"
export MESH_MAX_STEPS="4"             # 你要的 global step 数
export MESH_VALIDATE_PROFILE="paper"  # 建议论文/回归固定写明
./tools/run_mesh_with_time.sh
```

建议步数（仅建议，最终以论文需要为准）：
- `MESH_MAX_STEPS=1`：最快 sanity（检查不崩/统计链路存在）
- `MESH_MAX_STEPS=2`：最小可复现回归（推荐默认）
- `MESH_MAX_STEPS=4/8`：更稳的统计平均/更强的回归门槛

### 2.3 关于 `MESH_SIM_TIME`（step-limited 下不再用于停止）
- 仅当 `MESH_MAX_STEPS<=0` 时才会启用引擎 `stop-at`（见 `"sst_dram_si/mesh_template/entry.py:48"`）；而 paper/回归模式要求 `MESH_MAX_STEPS>0`。
- `local_run_config.json` 的 `sim_time` / 环境变量 `MESH_SIM_TIME` 在 step-limited 下主要用于“配置记录/派生指标输入”，不会强制停止；summary 会优先使用 `model.sim_time_actual_ns` 做归一化。

---

## 3. 执行模式：GAS vs naive（对比基线）
本模版支持通过环境变量切换“GAS/window 路径”与“naive 立即读路径”，用于严谨对比：
- `MESH_EXEC_MODE="gas"`（默认）：启用 `GatherBufferIF`（窗口化 Gather/Apply/Scatter）。
- `MESH_EXEC_MODE="naive_raw"`：不启用 GAS/window；spike 到达立刻发起读（对照基线）。
  - 注：BCSR 的 cache/prefetch/populate/inflight-coalescing 已在 SnnDL 内部全局禁用，因此不再区分 `naive_opt`。

示例（仍然 step-limited 停止）：
```bash
cd "sst_dram_si"
export MESH_EXEC_MODE="naive_raw"
export MESH_MAX_STEPS="4"
./tools/run_mesh_with_time.sh
```

注意：
- naive 模式下不会产生 GAS 专属产物（例如 `pe*/pe_stage_events_db.csv`、`coreXX_window_metrics.csv`）；`essential_summary_mesh.json` 中 `gas.windows=0` 属正常现象。
- 论文/主回归建议只用 `exec_mode=gas`；naive 对比建议使用 `--profile dev` 验收（paper profile 更偏向 GAS+SNN 主路径的强约束）。

---

## 4. 输出产物与查看
每次运行输出目录：`"sst_dram_si/outputs_large/paper2/dram_mesh_4x4/YYYYMMDD-HHMMSS"`

核心文件：
- `"mesh_run.log"`：运行日志
- `"time.txt"`：`/usr/bin/time -v` 输出（用于 wallclock）
- `"mesh_stats.csv"`：SST 统计 CSV（summary 的主要来源）
- `"effective_config.json"`：**最终生效的关键建模参数**（包含 dense 读粒度、GatherBufferIF 有效 merge_policy/burst 等；用于避免 `local_run_config.json` 误导）
- `"meta.json"`：可复现元数据（schema v1，paper profile 必须）
- `"inputs/local_run_config.json"`：归档的运行配置（带 sha256）
- `"essential_summary_mesh.json"`：关键结果摘要（schema v2：只保留结果 + `refs`；不再内嵌配置树）
- `"validation.log"`：验收输出（默认 paper profile）

gas 模式额外产物（用于 GAS 正确性/统计）：
- `"peXX/pe_stage_events_db.csv"`：GAS 阶段事件
- `"peXX/coreYY_window_metrics.csv"`：每核窗口统计（需启用导出）

快速查看：
```bash
cd "RUN_DIR"
jq -r '.refs, .model, .gas, .step, .step_activation, .memory, .memhierarchy, .nic, .wallclock' "essential_summary_mesh.json"
```

建议额外查看 effective 参数（强烈推荐）：
```bash
cd "RUN_DIR"
jq -r '.default_read_granularity, .line_size_bytes, .exec_mode, .force_dense, (.per_core[0] // {})' "effective_config.json"
```

---

## 5. 论文级可复现性（paper profile）与验收
### 5.1 元数据（meta.json schema v1）
由 `"sst_dram_si/tools/write_mesh_meta.py"` 生成，`"run_mesh_with_time*.sh"` 已自动调用。`meta.json(schema_version=1)` 关键包含：
- versions：SST/Python 版本
- environment：关键环境变量（含 `MESH_MAX_STEPS`）
- inputs：`inputs/local_run_config.json`（sha256）以及可选的 BCSR meta 归档
- model：mesh 规模/口径（含 `max_steps`）

### 5.2 paper profile 的强约束（为什么会 FAIL）
`"sst_dram_si/tools/validate_essential_summary_mesh.py"` 在 `--profile paper` 下会强制：
- `meta.json` 存在且 `schema_version=1`
- `inputs/local_run_config.json` sha256 校验通过（防止“跑完换配置文件”）
- 必须 step-limited：`MESH_MAX_STEPS>0`（否则 FAIL）
- `windows_incomplete==0`（若为 gas 模式，阶段事件必须完整）
- StepActivation 的算术守恒/丢失阈值（默认 `route_miss=0`；`local_drop` 仅允许极小阈值）

单独手动跑验收：
```bash
python3 "sst_dram_si/tools/validate_essential_summary_mesh.py" \
  --run-dir "RUN_DIR" \
  --profile "paper" \
  --strict
```

运行脚本内可通过环境变量调阈值（默认值见 `"sst_dram_si/tools/run_mesh_with_time.sh"`）：
- `MESH_VALIDATE_MAX_ROUTE_MISS_ABS` / `MESH_VALIDATE_MAX_ROUTE_MISS_FRAC`
- `MESH_VALIDATE_MAX_LOCAL_DROP_ABS` / `MESH_VALIDATE_MAX_LOCAL_DROP_FRAC`

对比稳定基线（建议纳入回归门槛）：
```bash
python3 "sst_dram_si/tools/validate_essential_summary_mesh.py" \
  --run-dir "RUN_DIR" \
  --baseline "BASELINE_RUN_DIR" \
  --profile "paper" \
  --strict
```

脚本方式（更适合固定 CI/回归配置）：
```bash
cd "sst_dram_si"
export MESH_VALIDATE_BASELINE_DIR="BASELINE_RUN_DIR"
./tools/run_mesh_with_time.sh
```

快速自查“step-limited + meta 口径一致”：
```bash
cd "RUN_DIR"
jq -r '.schema_version, .environment.MESH_MAX_STEPS, .model.max_steps' "meta.json"
```

---

## 6. 关键配置（从“正确性”出发）
### 6.1 step-limited：只认一个开关
- `MESH_MAX_STEPS`（环境变量）：要仿真的 global step 数；论文/回归必须 >0。

### 6.2 local_run_config.json（建议作为“实验配置真源”）
路径：`"sst_dram_si/local_run_config.json"`（会在 run 时被归档到 `RUN_DIR/inputs/`）

常用字段（节选）：
- `global_step_sync_enable`：建议保持 `1`（与 step-limited 搭配）
- `routing_mode`：通常为 `"weight_driven"`
- Step 随机激发（Step Random Activation）：
  - `step_random_activation_enable`
  - `step_activation_fraction`
  - `step_activation_fanout`
  - `step_activation_seed`
  - `step_activation_use_bcsr_routes`

### 6.3 GatherBufferIF（内存聚合/窗口化，gas 模式核心）
`"sst_dram_si/test_mesh_4x4.py"` 已在模板中设置关键参数；理解这些参数对“统计口径”很重要：
- `emit_stage_events=1`：写 `pe_stage_events_db.csv`（用于统计 windows 和阶段完整性）
- `export_window_metrics_csv=1`：写 `coreYY_window_metrics.csv`（用于 `window_metrics` 聚合）
- `k_adapt_enable=1`：仅打开段级统计（不改变控制行为）
- `ctrl_enable=0`：关闭控制（保证“统计不影响行为”）

`window_cycles_{gather,apply,scatter}` 的语义（重要）：
- 非全局同步（`GLOBAL_STEP_SYNC_ENABLE=0` / `step_gate_enable=0`）：legacy 模式，`window_cycles_*` 作为阶段时长（周期），G/A/S 由窗口时钟推进。
- 全局同步（`GLOBAL_STEP_SYNC_ENABLE=1` / `step_gate_enable=1`）：默认 step-gate 模式：
  - Gather：由 workload 在输入静默收敛后显式触发 `EndGather`（默认 `gas_gather_quiesce_cycles=32`），不依赖固定周期。
  - Apply：当 `required_set` 全部 ready 自动结束（allReady），不依赖固定周期。
  - Scatter：workload 完成 scatter 事务后显式触发 `EndScatter`（通常 1 cycle 内结束）。
  - 模板会将 `window_cycles_*` 默认置为 `0/0/0`；如需兼容旧实验，可通过 `MESH_GAS_CYCLES="g,a,s"` 显式覆盖。

### 6.4 Step 随机激发（Step Random Activation）
参数来源：`"sst_dram_si/local_run_config.json"`

语义（简化版）：
- 以 `fraction` 从 pre 集合抽样，按 `fanout` 生成投递尝试并注入（可选通过 BCSR reachability 把 post 约束为“真实有边”）。
- `essential_summary_mesh.json` 的 `step_activation.*` 用于量化注入强度与丢失情况（paper profile 会对此做强约束）。

推荐（论文/回归）：
- `step_activation_fraction`：建议从 `1e-3 ~ 5e-3` 起步，逐步加压（避免把性能抖动误当模型现象）
- `step_activation_fanout=256`：与 BCSR 数据集 fanout 对齐

---

## 7. 统计数据：检验项与意义（面向论文正确性）
本模板的“可复现正确性闭环”由三部分组成：
- `mesh_stats.csv`（原始统计）→ `"sst_dram_si/tools/compute_essential_summary_mesh.py"` 聚合 → `essential_summary_mesh.json`
- `"sst_dram_si/tools/write_mesh_meta.py"` 生成 `meta.json` 并归档输入配置（含 sha256）
- `"sst_dram_si/tools/validate_essential_summary_mesh.py"` 在 profile 下做口径/算术约束验收

你在论文里最常需要引用/检查的字段（节选）：
- `gas.windows`：GAS window 数（来自 `pe_stage_events_db.csv`，仅 gas 模式有意义）
- `gas.windows_incomplete`：不完整窗口数（paper profile 要求为 0）
- `window_metrics.*`：核心窗口统计（来自 `coreYY_window_metrics.csv`，需要启用导出）
- `step_activation.*`：注入强度与丢失（`route_misses/local_drops` 是正确性红线）
- `memory.*`：内存请求与字节统计（基于 `mesh_stats.csv` 聚合）
- `nic.*`：网络统计（基于 `mesh_stats.csv` 聚合；已避免 spikes/packets 双计数）
- `wallclock.*`：运行资源消耗（来自 `time.txt`）

---

## 8. 权重与 BCSR 数据来源
- 默认自动探测（`write_mesh_meta.py`）：
  - `"weights/bcsr_global_16pe_fanout256_10k"` 或 `"weights/bcsr_global_16pe_fanout256"`
  - 读取 `"pe00/core00.bcsr.bin.meta.json"` 的 `rows` 推导 `neurons_per_core`
- 覆盖权重目录：
  - `MESH_BCSR_DIR` 指向包含 `peXX/coreYY.*` 的权重目录（优先）

---

## 9. 常见问题（按“会影响正确性”优先级）
- paper profile 直接 FAIL：大概率是 `MESH_MAX_STEPS<=0`（你仍在用 stop-at 思维）；按 2.2 设置 `MESH_MAX_STEPS`。
- naive 对比跑不出 GAS 产物：正常；建议用 `--profile dev` 验收。
- `window_metrics` 为 0：确认 gas 模式且启用了导出（模板默认启用）；若你改了配置，确认 `export_window_metrics_csv=1` 且统计口径未被关闭。
- NIC 统计看起来“翻倍/异常”：请确认使用最新 summary 生成逻辑（`compute_essential_summary_mesh.py` 已避免 spikes/packets 双计数）。

---

## 10. 清理与存储建议
- 输出目录体积可能很大（尤其是每核窗口 CSV）；建议至少保留：
  - `meta.json`、`inputs/`、`essential_summary_mesh.json`、`validation.log`
- 其余可按需要归档/清理。

---

（完）
