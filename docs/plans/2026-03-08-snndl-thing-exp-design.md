# snndl-thing-exp Design

**Goal:** 新建一个与 `mainexp/`、`memop/`、`sst_workloads/` 解耦的顶层实验容器 `snndl-thing-exp/`，专门承载 SnnDL SRAM timing 相关 smoke / debug / ablation 测试，不污染主线实验目录与默认输出路径。

## 背景与约束

当前仓库里已有多条实验主线：

- `mainexp/experiments/`：主叙事与正式对比实验；
- `memop/experiments/`：memory optimization 方向实验；
- `sst_workloads/`：独立 workload 驱动场景。

这类目录结构适合已经稳定成型的实验矩阵，但不适合当前 `SnnDL SRAM timing` 这种仍在快速迭代、需要频繁 smoke/debug 的分支。为了避免临时 runner、spec、输出 run_dir 挤进主线目录，这里单独建立 `snndl-thing-exp/`。

## 推荐结构

`snndl-thing-exp/` 采用轻量“独立实验仓”布局：

- `README.md`：说明隔离原则、目录职责、运行方式；
- `cases/<case_id>/case.json`：每个实验 case 的元信息与默认 env；
- `cases/<case_id>/spec.json`：spec-first 的 mesh 配置，不修改 `sst_dram_si/local_run_config.json`；
- `tools/run_case.py`：统一 runner，负责 validate spec、设置隔离输出目录、调用 `sst_dram_si/tools/run_mesh_with_time.sh --spec ...`；
- `tests/test_run_case.py`：只测 runner 的路径解析与隔离行为；
- `runs/`、`run_logs/`、`snapshot/`、`summary/`：实验输出目录，全部限定在 `snndl-thing-exp/` 内。

## 隔离策略

- **配置隔离**：使用 `spec-first` 驱动，实验参数写入 `cases/*/spec.json` 的 `components.pe.core` override，不要求修改主线 `local_run_config.json`。
- **输出隔离**：runner 强制设置 `MESH_RUN_ROOT=<repo>/snndl-thing-exp/runs/<case_id>`，所有时间戳 run_dir 都落在实验目录下。
- **主线零侵入**：不向 `mainexp/`、`memop/` 写任何 run_dir、snapshot 或 case 文件。
- **后续扩展**：后面可继续在 `cases/` 下增加 `sram_timing_ab/`、`state_sram_debug/` 等 case，而不需要修改主线脚本。

## 第一批承载内容

第一批先提供一个 `sram_timing_smoke` case：

- `schema_version=3`
- `step_limited max_steps=1`
- 通过 `components.pe.core` 打开 `state_sram_enable`、`weight_idx_sram_enable`、`weight_l0_sram_enable`
- 使用 `control.global_step_done.policy=drain` 降低稀疏 smoke 的 barrier 收敛风险
- 禁用 `SpikeSource`，改用轻量 `step random activation`（`activation_fraction=0.001`, `activation_fanout=1`）降低 wall-clock 并保持非零 memory traffic
- 默认 `MESH_SST_NPROC=1`、`MESH_VALIDATE_PROFILE=dev`

这个 case 的目标不是给论文出数，而是验证：

1. `snndl-thing-exp` 自己能独立驱动 mesh；
2. 输出路径被正确约束在本实验目录；
3. 后续 SRAM timing 联调不用再污染主线实验。
