# Memory/NMC Phase2 Main Entry And Route Diff Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `run_memory_nmc_codesign_matrix.py` 升级成 `phase2` 的 canonical main entry，并把 `traffic_route / window_route` 的 runtime-controller / real-home-path 差分固化为正式导出产物。

**Architecture:** 在现有 matrix orchestrator 基础上继续上抬，而不是新建平行主入口。orchestrator 负责串起 `baseline -> fixed-step -> codesign surface -> phase2 artifacts -> route diff report`，其中 route diff report 独立为一个可复用 exporter，既能被 orchestrator 调用，也能被后续 phase2/paper/report 链单独消费。

**Tech Stack:** Python 3、`unittest`、现有 `snn3dexp.tools.*` 编排/导出链、JSON/Markdown/CSV artifact 约定

---

### Task 1: 锁定 phase2 main entry 合约

**Files:**
- Modify: `snn3dexp/tests/test_run_memory_nmc_codesign_matrix.py`
- Reference: `snn3dexp/tools/run_memory_nmc_codesign_matrix.py`
- Reference: `snn3dexp/tools/export_phase2_paper_artifacts.py`

**Step 1: 写失败测试**

测试点：
- `run_memory_nmc_codesign_matrix()` 可选调用 `export_phase2_paper_artifacts`
- 能把 `baseline_ablation_path / fixed_step_summary_path / baseline_overlay_ablation_paths / stop_window_ablation_paths` 正确透传
- 最终 summary 带：
  - `phase2_artifacts.available`
  - `phase2_artifacts.path`
  - `phase2_artifacts.outputs`

**Step 2: 运行测试确认红灯**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix.RunMemoryNmcCodesignMatrixTests.test_run_memory_nmc_codesign_matrix_optionally_exports_phase2_artifacts -v`

Expected: FAIL，提示缺少 phase2 export 能力或 summary 字段不存在

### Task 2: 锁定 route/runtime diff exporter 合约

**Files:**
- Create: `snn3dexp/tests/test_export_memory_nmc_route_runtime_diff.py`
- Create: `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- Reference: `snn3dexp/tools/export_memory_nmc_codesign_surface.py`

**Step 1: 写失败测试**

测试点：
- 输入一个最小 matrix summary 后，会抽取：
  - `traffic_route`
  - `window_route`
- 会输出：
  - JSON summary
  - CSV rows
  - Markdown report
- traffic route report 会明确记录：
  - `dominant_home_runtime_controller_overlap_delta`
  - `pe_nic_real_home_path_service_deficit_total_delta`
  - `synapse_real_home_path_service_deficit_total_delta`
- window route report 会明确记录：
  - `dataflow_controller_alignment_transition`
  - `pe_nic_dominant_controller_outstanding_requests_accum_delta`
  - `synapse_dominant_controller_outstanding_requests_accum_delta`

**Step 2: 运行测试确认红灯**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_export_memory_nmc_route_runtime_diff -v`

Expected: FAIL，提示模块不存在或缺少期望输出

### Task 3: 实现 route/runtime diff exporter

**Files:**
- Create: `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`
- Test: `snn3dexp/tests/test_export_memory_nmc_route_runtime_diff.py`

**Step 1: 写最小实现**

实现内容：
- 接受 matrix summary path 或 summary dict
- 过滤 `matrix_rows` 中的 `traffic_route / window_route`
- 投影两类报告：
  - `traffic_route_diffs`
  - `window_route_diffs`
- 生成：
  - `memory_nmc_route_runtime_diff_summary.json`
  - `memory_nmc_route_runtime_diff.csv`
  - `memory_nmc_route_runtime_diff.md`

**Step 2: 跑测试确认转绿**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_export_memory_nmc_route_runtime_diff -v`

Expected: PASS

### Task 4: 实现 phase2 main entry 增强

**Files:**
- Modify: `snn3dexp/tools/run_memory_nmc_codesign_matrix.py`
- Modify: `snn3dexp/tests/test_run_memory_nmc_codesign_matrix.py`
- Reference: `snn3dexp/tools/export_phase2_paper_artifacts.py`
- Reference: `snn3dexp/tools/export_memory_nmc_route_runtime_diff.py`

**Step 1: 写最小实现**

实现内容：
- 给 orchestrator 增加可选 phase2 artifact export 开关/参数
- 在同一轮编排中调用：
  - `export_phase2_paper_artifacts`
  - `export_memory_nmc_route_runtime_diff`
- summary 新增：
  - `phase2_artifacts`
  - `route_runtime_diff`
- CLI 新增对应选项，保证：
  - `compose-only / runtime smoke / full runtime`
  - 三者共用同一入口

**Step 2: 跑定向测试确认转绿**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix -v`

Expected: PASS

### Task 5: 文档对齐与 fresh 验证

**Files:**
- Modify: `docs/plans/nextarc/2026-03-23-3d-snn-status-refresh-and-nextarc.md`
- Modify: `TECH_PROGRESS.md`

**Step 1: 跑相关 fresh regression**

Run:
- `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_memory_nmc_codesign_matrix snn3dexp.tests.test_export_memory_nmc_route_runtime_diff snn3dexp.tests.test_phase2_paper_artifacts snn3dexp.tests.test_memory_nmc_codesign_surface snn3dexp.tests.test_fixed_step_sweep snn3dexp.tests.test_run_fixed_step_multicase_sweep snn3dexp.tests.test_phase2_baseline_suite -v`

Expected: PASS

**Step 2: 做一次真实 compose-only 或 runtime smoke 主链验证**

Run:
- `cd /home/xgy/remote && python3 -m snn3dexp.tools.run_memory_nmc_codesign_matrix --matrix-label matrix23_phase2_mainline_smoke --baseline-run-tag matrix23_phase2_mainline_traffic --fixed-step-run-tag matrix23_phase2_fixed_step_4_10us --compose-only`

Expected:
- 生成 matrix summary
- 生成 phase2 artifacts
- 生成 route/runtime diff report

**Step 3: 更新状态文档与进度日志**

必须 append / update：
- `run_memory_nmc_codesign_matrix.py` 已成为 phase2 canonical main entry
- `traffic_route / window_route` 差分已形成正式导出产物
- fresh regression 命令与真实产物路径
- 下一步 TODO
