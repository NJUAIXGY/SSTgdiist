# Snn3dexp Windowed SNN Global-Step Control Plane Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade `snn3dexp` so `processing.workload_impl=snn` with windowed GAS no longer relies on `GatherBufferIF` auto windows alone, but instantiates a minimal real `GlobalGasStepController -> MultiCorePE(gas_step_ctrl) -> GatherBufferIF(step_gate)` control plane.

**Architecture:** Keep the change isolated in the Python-side `snn3dexp` object-graph builder. Detect windowed SNN runtime in `platform/sst_graph.py`, sink `global_step_sync_enable/global_step_done_policy` into each PE, create one mesh-level `SnnDL.GlobalGasStepController`, and connect it to all processing PEs via `gas_step_ctrl`. Keep the rest of the routing/memory graph unchanged so existing `traffic_mem` and non-windowed cases stay backward compatible.

**Tech Stack:** Python 3, `unittest`, `snn3dexp/platform/sst_graph.py`, existing fake-SST graph tests, existing SnnDL `GlobalGasStepController` / `MultiCorePE` / `GatherBufferIF`

**Current Status (2026-03-21):** 本批实现已完成并进入当前 canonical baseline 路径。

- `windowed SNN` graph 已正式注入：
  - `SnnDL.GlobalGasStepController`
  - `gas_step_ctrl` control-plane links
  - `GatherBufferIF.step_gate_enable=1`
- `full_3d_snn_window` 与 `full_3d_snn_window_monolithic_proxy` 已在 `arc4_refresh_20260321` 下 fresh `smoke_passed`。
- 两个 case 已正式进入 `arc4_baseline_compose_20260321` 的 9-case baseline suite。
- 当前剩余缺口：
  - 还需要把 `windowed SNN` 与 `traffic_mem` 的 compare surface 做成统一入口
  - 还需要为 fresh canonical cases 开启 HotSpot sidecar

---

### Task 1: Lock The Builder Contract With Failing Tests

**Files:**
- Modify: `snn3dexp/tests/test_sst_graph_builder.py`

**Step 1: Write the failing test**

Add tests that require:
- `build_sst_graph_manifest(...)` to emit a `control_plane_nodes` list containing exactly one `SnnDL.GlobalGasStepController` for windowed `workload_impl=snn`
- `build_sst_graph_manifest(...)` to emit `control_plane_links` connecting every `multicore_pe_<id>.gas_step_ctrl` to the controller
- processing PE params to include `global_step_sync_enable=1` and default `global_step_done_policy=endscatter`
- `GatherBufferIF` params to switch from `step_gate_enable=0` to `step_gate_enable=1` for windowed SNN

**Step 2: Run test to verify it fails**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_sst_graph_builder.SstGraphBuilderTests -v`

Expected: FAIL because the manifest currently has no control-plane component/link surface and still uses `step_gate_enable=0`.

### Task 2: Implement The Minimal Global-Step Graph

**Files:**
- Modify: `snn3dexp/platform/sst_graph.py`

**Step 1: Add minimal control-plane helpers**

Implement helpers that:
- detect when `workload_impl=snn` is running in windowed GAS mode
- build a single `GlobalGasStepController` descriptor
- build one `gas_step_ctrl` link per processing PE

Keep the scope narrow:
- no new routing logic
- no new runtime controller semantics
- no changes for non-windowed or non-SNN cases

**Step 2: Sink step-sync params into the PE/memory subgraph**

Update the processing graph builder so that windowed SNN:
- sets `global_step_sync_enable=1`
- defaults `global_step_done_policy=endscatter`
- preserves optional user overrides if explicitly supplied
- enables `GatherBufferIF.step_gate_enable=1`
- keeps `emit_stage_events=1` and strict/non-lenient behavior

**Step 3: Expose the new graph in the manifest and emitter**

Update manifest generation and `emit_sst_graph(...)` so:
- `control_plane_nodes` and `control_plane_links` are part of the manifest
- real SST emission instantiates the controller before links are connected
- the fake-SST path used by tests also sees the controller and links

**Step 4: Run focused tests**

Run: `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_sst_graph_builder.SstGraphBuilderTests -v`

Expected: PASS

### Task 3: Verify Case/Run Integration

**Files:**
- Modify: `snn3dexp/tests/test_run_case.py`
- Modify: `snn3dexp/cases/full_3d_snn_window/spec.json` (only if an explicit case-level override is needed)

**Step 1: Write a failing integration test if required**

If `run_case` or the catalog needs to surface the new control plane, add a test that requires:
- the built manifest for `full_3d_snn_window` to include the controller node and links
- the effective object graph to preserve `workload_impl=snn`

**Step 2: Implement the minimal adjustment**

Only add case/spec plumbing if needed. Prefer builder-side inference over spec bloat.

**Step 3: Run the focused test set**

Run:
- `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_sst_graph_builder -v`
- `cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_case -v`

Expected: PASS

### Task 4: Real Smoke And Progress Log

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run a real smoke**

Run a short real case such as:
- `cd /home/xgy/remote && python3 -m snn3dexp.tools.run_case --case full_3d_snn_window --run-tag task_global_step_ctrl_smoke --sst-smoke --stop-at 250ns`

Current aligned fresh evidence:
- `cd /home/xgy/remote && python3 snn3dexp/tools/run_case.py full_3d_snn_window --run-tag arc4_refresh_20260321 --sst-smoke --stop-at 2us --global-step-max-steps 4 --test-max-spikes 16`
- `cd /home/xgy/remote && python3 snn3dexp/tools/run_case.py full_3d_snn_window_monolithic_proxy --run-tag arc4_refresh_20260321 --sst-smoke --stop-at 2us --global-step-max-steps 4 --test-max-spikes 16`

Expected:
- manifest generation succeeds
- SST object graph instantiates the global-step controller
- the run completes without `gas_step_ctrl` linkage/config fatal
- aligned fresh runs now additionally prove that the control-plane path is compatible with the current phase2 summary / baseline-suite flow

**Step 2: Append progress log**

Append a new `TECH_PROGRESS.md` entry documenting:
- new control-plane object graph
- new manifest surfaces
- verification commands/results
- next steps for deeper windowed-SNN compare work

**Step 3: Final verification**

Run: `cd /home/xgy/remote && tail -n 120 TECH_PROGRESS.md`

Expected: new entry appears at file end only
