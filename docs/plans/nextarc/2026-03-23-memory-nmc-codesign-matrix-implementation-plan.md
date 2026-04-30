# Memory/NMC Co-Design Matrix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `snn3dexp` 落地一条 canonical `memory/NMC + co-design` 实验主链，把 `traffic_mem` 与 `fixed-step windowed SNN` 的 `direct_v4 vs bundle_v3`、`HBM-like vs monolithic-like` 对照统一成可执行实验矩阵。

**Architecture:** 复用现有 `run_case.py`、`analyze_ablation.py`、`analyze_fixed_step_sweep.py` 与 `export_memory_nmc_codesign_surface.py`，新增一个 `fixed-step multicase` runner 和一个更高层的 matrix orchestrator。runner 负责把 windowed SNN 的 canonical fixed-step run tags 真正执行出来，orchestrator 负责串起 traffic baseline、window fixed-step、surface export，并写出统一 matrix summary。

**Tech Stack:** Python 3、`unittest`、现有 `snn3dexp.tools.*` 编排链、JSON/CSV artifact 约定

---

### Task 1: 锁定 Fixed-Step Runner 合约

**Files:**
- Create: `snn3dexp/tests/test_run_fixed_step_multicase_sweep.py`
- Reference: `snn3dexp/tools/run_window_stop_multicase_sweep.py`
- Reference: `snn3dexp/tools/analyze_fixed_step_sweep.py`

**Step 1: 写失败测试**

测试点：
- 输入 canonical run tags 时，会为每个 `case_id × run_tag` 调一次 `execute_case`
- `task_fixed_step_4_10us` 会下推 `global_step_ctrl_max_steps=4`
- `task_fixed_step_4_10us_sp64` 会额外下推 `test_max_spikes=64`
- 会写出 `run_tag_manifests/<run_tag>.json`
- summary 会包含 `runs`、`run_tag_manifests`、`outputs.summary_json/csv`

**Step 2: 运行测试确认红灯**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_fixed_step_multicase_sweep -v`

Expected: `ModuleNotFoundError` 或 runner 未实现导致失败

### Task 2: 实现 Fixed-Step Runner

**Files:**
- Create: `snn3dexp/tools/run_fixed_step_multicase_sweep.py`
- Modify: `snn3dexp/tools/run_case.py` 仅在确有必要时复用已有 helper，不改变既有 CLI 语义
- Test: `snn3dexp/tests/test_run_fixed_step_multicase_sweep.py`

**Step 1: 写最小实现**

实现内容：
- 默认 case ids 复用 `analyze_fixed_step_sweep.DEFAULT_CASE_IDS`
- 默认 run tags 复用 `analyze_fixed_step_sweep.DEFAULT_RUN_TAGS`
- 解析 run tag 中的 `step_budget / stop_at / spike_budget_override`
- 调用 `execute_case(..., stop_at=..., processing_param_overrides=...)`
- 为每个 run tag 产出 `case_ids + run_tags_by_case` manifest
- 写出 `fixed_step_multicase_sweep_summary.json` 和 csv

**Step 2: 跑测试确认转绿**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_fixed_step_multicase_sweep -v`

Expected: PASS

### Task 3: 锁定 Matrix Orchestrator 合约

**Files:**
- Create: `snn3dexp/tests/test_run_memory_nmc_codesign_matrix.py`
- Reference: `snn3dexp/tools/export_memory_nmc_codesign_surface.py`
- Reference: `snn3dexp/tools/run_case.py`
- Reference: `snn3dexp/tools/run_fixed_step_multicase_sweep.py`

**Step 1: 写失败测试**

测试点：
- orchestrator 会先跑 traffic baseline，再单独补跑 `full_3d_tile_bundle_v3`
- 会写 `traffic_run_tag_manifest.json`
- 会调用 `analyze_ablation` 产出 traffic baseline ablation
- 会调用 fixed-step runner 和 `analyze_fixed_step_sweep`
- 会调用 `export_memory_nmc_codesign_surface`
- 最终 summary 会带：
  - `traffic_manifest`
  - `baseline_ablation`
  - `fixed_step_execution`
  - `fixed_step_analysis`
  - `codesign_surface`
  - `matrix_rows`

**Step 2: 运行测试确认红灯**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v`

Expected: `ModuleNotFoundError` 或 orchestrator 未实现导致失败

### Task 4: 实现 Matrix Orchestrator

**Files:**
- Create: `snn3dexp/tools/run_memory_nmc_codesign_matrix.py`
- Test: `snn3dexp/tests/test_run_memory_nmc_codesign_matrix.py`

**Step 1: 写最小实现**

实现内容：
- 定义 canonical traffic case ids：
  - `baseline_2d`
  - `memory_only_3d`
  - `noc_only_3d`
  - `full_3d`
  - `full_3d_monolithic_proxy`
  - `full_3d_tile_bundle_v3`
- 定义 canonical fixed-step window case ids：
  - `full_3d_snn_window`
  - `full_3d_snn_window_bundle_v3`
  - `full_3d_snn_window_monolithic_proxy`
- 串起：
  - `run_phase2_baseline_suite`
  - `execute_case` 补跑 `full_3d_tile_bundle_v3`
  - `analyze_ablation`
  - `run_fixed_step_multicase_sweep`
  - `analyze_fixed_step_sweep`
  - `export_memory_nmc_codesign_surface`
- 从 surface summary 中抽取统一 `matrix_rows`：
  - `traffic_mem_compare_rows`
  - `window_bundle_breakdown_rows`
  - `window_memory_model_breakdown_rows`

**Step 2: 跑测试确认转绿**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v`

Expected: PASS

### Task 5: 回归验证与文档对齐

**Files:**
- Modify: `docs/plans/nextarc/2026-03-23-3d-snn-status-refresh-and-nextarc.md`
- Modify: `TECH_PROGRESS.md`

**Step 1: 跑相关回归**

Run:
- `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_fixed_step_multicase_sweep snn3dexp.tests.test_run_memory_nmc_codesign_matrix snn3dexp.tests.test_fixed_step_sweep snn3dexp.tests.test_window_stop_multicase_sweep snn3dexp.tests.test_memory_nmc_codesign_surface -v`

Expected: PASS

**Step 2: 更新状态文档**

更新内容：
- 当前 `memory/NMC` 主线已从“分析入口”升级为“runner + orchestrator + unified matrix”能力
- 明确 fixed-step runner 的新增位置和 canonical matrix 入口

**Step 3: 追加 TECH_PROGRESS**

必须 append：
- 新增文件/功能
- 验证命令
- 结果
- 下一步 TODO
