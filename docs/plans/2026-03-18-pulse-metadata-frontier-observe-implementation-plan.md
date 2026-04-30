# PULSE Metadata Frontier Observe Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the failed value-line frontier probe with an earlier PE-internal metadata-frontier probe by exporting per-core top-H pre-MPHF metadata objects (`pre_base` / `pre_band`) and closing the loop with a fresh `mainexp` observe-only experiment.

**Architecture:** The new batch remains strictly observe-only and default-off. `WeightMemorySubsystem` will export top-H unique metadata objects from the existing GCSS-VLF issue queue after `pre_base/len + pre_rank` lookup, a PE-scoped metadata registry will measure cross-core overlap for `pre_base` and coarser `pre_band`, `MultiCorePE` will surface the new `pulse_metadata_frontier_*` stats, and `compute_essential_summary_mesh.py` plus a fresh `mainexp` harness will derive overlap ratios for formal A/B analysis.

**Tech Stack:** C++17 SST/SnnDL components, Python mesh config and summary tooling, `unittest`, `mainexp` run harness.

---

### Task 1: Lock runtime config with failing tests

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_pulse_config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/runtime.py`

**Step 1: Write the failing test**

Add a runtime config test that expects:

- `MESH_PULSE_METADATA_FRONTIER_OBSERVE_ENABLE=1`
- `MESH_PULSE_METADATA_FRONTIER_TOP_ITEMS=48`
- `MESH_PULSE_METADATA_FRONTIER_BAND_SLOTS=256`

to appear in `rt.mesh_cfg["pulse"]` only when `MESH_EXPERIMENTAL_ENABLE=1`.

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest sst_dram_si.mesh_template.test_runtime_pulse_config.RuntimePulseConfigTests.test_pulse_metadata_frontier_observe_env_is_exported_when_experimental_enable_is_on -v
```

Expected: FAIL because the new metadata-frontier fields are not exported yet.

**Step 3: Write minimal implementation**

Plumb the new pulse metadata-frontier fields through the runtime/config/build chain.

**Step 4: Run test to verify it passes**

Run the same unittest command again and expect PASS.

### Task 2: Lock summary metrics with failing tests

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`

**Step 1: Write the failing test**

Extend the pulse summary tests to expect aggregation and derivation of:

- `pulse_metadata_frontier_windows_total`
- `pulse_metadata_frontier_base_items_exported_total`
- `pulse_metadata_frontier_base_overlap_items_total`
- `pulse_metadata_frontier_base_overlap_peer_total`
- `pulse_metadata_frontier_base_max_exported_per_window`
- `pulse_metadata_frontier_band_items_exported_total`
- `pulse_metadata_frontier_band_overlap_items_total`
- `pulse_metadata_frontier_band_overlap_peer_total`
- `pulse_metadata_frontier_band_max_exported_per_window`

and derived fields:

- `pulse_metadata_frontier_base_overlap_ratio`
- `pulse_metadata_frontier_base_avg_peer_overlap`
- `pulse_metadata_frontier_band_overlap_ratio`
- `pulse_metadata_frontier_band_avg_peer_overlap`

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_pulse.ComputeEssentialSummaryMeshPulseCLITest.test_pulse_metadata_frontier_metrics_are_aggregated_and_derived -v
```

Expected: FAIL because the summary tool does not yet know these metrics.

**Step 3: Write minimal implementation**

Teach `compute_essential_summary_mesh.py` to derive the new metadata-frontier ratios when the stats are present.

**Step 4: Run test to verify it passes**

Run the same unittest command again and expect PASS.

### Task 3: Add isolated pre-MPHF metadata-frontier observe plumbing in SnnDL

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseMetadataFrontierObserveRegistry.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`

**Step 1: Implement the minimal registry**

Add a PE-scoped observe-only registry keyed by:

- `scope_id`
- `window_seq`
- `kind`
- `object_id`

where the first batch only emits:

- `kind = premphf_base`
- `kind = premphf_band`

**Step 2: Extend the issue entry with metadata identity**

When `prepareGcssVlfIssueQueue_()` builds GCSS-VLF entries, persist enough metadata to recover:

- `pre_base`
- `pre_len`

from the already executed `lookupGcssPreBaseLen_()` path.

**Step 3: Export top-H metadata frontier**

For the first `H` unique `pre_global` items in the ordered issue queue:

- observe one `premphf_base` object keyed by `pre_base`
- observe one `premphf_band` object keyed by `pre_base / band_slots`

Track separate exported/overlap counters for base and band.

**Step 4: Plumb stats to MultiCorePE**

Extend the existing pulse observability path so the new `pulse_metadata_frontier_*` counters appear as SST stats.

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
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_frontier_observe_ab_v1/cases.json`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_frontier_observe_ab_v1/run_case.sh`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_frontier_observe_ab_v1/make_snapshot.py`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_frontier_observe_ab_v1/test_make_snapshot.py`

**Step 1: Baseline case**

Use `PULSE Stage-A actual shared-line baseline` without metadata-frontier observe.

**Step 2: Candidate case**

Enable:

- `MESH_PULSE_METADATA_FRONTIER_OBSERVE_ENABLE=1`
- `MESH_PULSE_METADATA_FRONTIER_TOP_ITEMS=64`
- `MESH_PULSE_METADATA_FRONTIER_BAND_SLOTS=256`

while keeping all other behavior identical.

**Step 3: Run fresh A/B**

Run baseline and candidate through the harness.

**Step 4: Generate compare snapshot**

Include:

- mainline metrics
- `pulse_metadata_frontier_*` metrics
- derived base/band overlap ratios

### Task 6: Record results

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Append-only progress entry**

Append:

- what changed
- how to run / verify
- fresh experiment paths
- metadata-frontier overlap findings
- next-step decision

**Step 2: State explicit next gate**

If `pre_base` / `pre_band` overlap is stably non-zero on the Stage-A actual baseline, next batch is:

- `F2 shared metadata seeding`

If both remain approximately zero, stop and record that the current mainline lacks PE-internal metadata overlap at this probe point.
