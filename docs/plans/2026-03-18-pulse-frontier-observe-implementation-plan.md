# PULSE Frontier Observe Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the first isolated `PULSE-FCS` batch by exporting per-core top-H line frontier observations, aggregating overlap metrics at PE level, and closing the loop with a fresh `mainexp` observe-only experiment.

**Architecture:** The implementation stays strictly observe-only. `WeightMemorySubsystem` will export top-H unique line frontier observations from the existing GCSS issue queue, a PE-scoped frontier registry will count cross-core overlap, `MultiCorePE` will expose the new pulse stats, and `compute_essential_summary_mesh.py` will derive overlap ratios for experiment analysis.

**Tech Stack:** C++17 SST/SnnDL components, Python mesh config and summary tooling, `unittest`, `mainexp` run harness.

---

### Task 1: Lock runtime config with failing tests

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_pulse_config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`

**Step 1: Write the failing test**

Add a new runtime config test that expects:

- `MESH_PULSE_FRONTIER_OBSERVE_ENABLE=1`
- `MESH_PULSE_FRONTIER_TOP_LINES=24`

to appear in `rt.mesh_cfg["pulse"]` only when `MESH_EXPERIMENTAL_ENABLE=1`.

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest sst_dram_si.mesh_template.test_runtime_pulse_config.RuntimePulseConfigTests.test_pulse_frontier_observe_env_is_exported_when_experimental_enable_is_on -v
```

Expected: FAIL because the new pulse frontier fields are not exported yet.

**Step 3: Write minimal implementation**

Plumb the new pulse fields through `mesh_template/build.py`.

**Step 4: Run test to verify it passes**

Run the same unittest command again and expect PASS.

### Task 2: Lock summary metrics with failing tests

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`

**Step 1: Write the failing test**

Extend the pulse summary test to expect aggregation of:

- `pulse_frontier_windows_total`
- `pulse_frontier_lines_exported_total`
- `pulse_frontier_overlap_lines_total`
- `pulse_frontier_overlap_peer_total`
- `pulse_frontier_max_exported_per_window`

and derived fields:

- `pulse_frontier_overlap_ratio`
- `pulse_frontier_avg_peer_overlap`

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_pulse.ComputeEssentialSummaryMeshPulseCLITest.test_pulse_frontier_metrics_are_aggregated_and_derived -v
```

Expected: FAIL because the summary tool does not yet derive these fields.

**Step 3: Write minimal implementation**

Teach `compute_essential_summary_mesh.py` to derive the new frontier ratios when pulse stats are present.

**Step 4: Run test to verify it passes**

Run the same unittest command again and expect PASS.

### Task 3: Add isolated frontier observe plumbing in SnnDL

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseFrontierObserveRegistry.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`

**Step 1: Implement the minimal observe-only registry**

Add a header-only PE-scoped registry keyed by:

- `scope_id`
- `window_seq`
- `line_addr`

The registry only counts consumers and returns overlap information to the caller.

**Step 2: Export top-H frontier lines**

At `prepareGcssVlfIssueQueue_()` time, export the first `H` unique line addresses from the ordered GCSS issue queue when:

- `pulse_frontier_observe_enable=1`
- `pulse_agenda_enable=1`
- `window_seq_ != 0`

**Step 3: Accumulate new pulse observability counters**

Track:

- `frontier_windows_total`
- `frontier_lines_exported_total`
- `frontier_overlap_lines_total`
- `frontier_overlap_peer_total`
- `frontier_max_exported_per_window`

**Step 4: Plumb stats to MultiCorePE**

Extend the existing pulse observability path so these counters appear as `pulse_*` SST statistics.

### Task 4: Compile and integration verification

**Files:**
- No new files beyond the above

**Step 1: Run Python regression**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.mesh_template.test_runtime_pulse_config \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse -v
```

Expected: PASS.

**Step 2: Build SnnDL**

Run:

```bash
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j1
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make install
```

Expected: exit `0`.

### Task 5: Create mainexp closed-loop experiment

**Files:**
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_frontier_observe_ab_v1/cases.json`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_frontier_observe_ab_v1/run_case.sh`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_frontier_observe_ab_v1/make_snapshot.py`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_frontier_observe_ab_v1/test_make_snapshot.py`

**Step 1: Baseline case**

Use `PULSE Stage-A actual shared-line baseline` without frontier observe.

**Step 2: Candidate case**

Enable:

- `MESH_PULSE_FRONTIER_OBSERVE_ENABLE=1`
- `MESH_PULSE_FRONTIER_TOP_LINES=32`

while keeping all other behavior identical.

**Step 3: Run fresh A/B**

Run baseline and candidate through the experiment harness.

**Step 4: Generate compare snapshot**

Include:

- mainline metrics
- new pulse frontier metrics
- derived overlap ratios

### Task 6: Record results

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Append-only progress entry**

Append:

- what changed
- how to run / verify
- fresh experiment paths
- frontier overlap findings
- next step decision

**Step 2: State explicit next gate**

If frontier overlap is stably non-zero, next batch is:

- `F2 shared metadata seeding`

If not, stop and record `NO-GO`.
