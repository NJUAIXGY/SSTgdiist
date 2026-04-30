# PULSE-MFB C0/C1 Diagnostics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the minimum owner-first diagnostics needed to prove whether the current F2 metadata-seed path is still structurally late-join only.

**Architecture:** Keep the current F2 behavior unchanged and default-off. Extend the existing metadata-seed path with three new counters: `pulse_mfb_owner_eligible_total`, `pulse_metadata_seed_join_only_total`, and `pulse_metadata_seed_owner_already_exists_total`, then derive `pulse_mfb_owner_first_rate` in the summary and surface the new fields in the existing `mainexp` snapshot.

**Tech Stack:** C++17 SST/SnnDL components, Python summary tooling, Python `unittest`, `mainexp` harness.

---

### Task 1: Lock summary derivation with failing tests

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`

**Step 1: Write the failing test**

Extend the pulse summary tests so they expect:

- `pulse_mfb_owner_eligible_total`
- `pulse_metadata_seed_join_only_total`
- `pulse_metadata_seed_owner_already_exists_total`
- derived:
  - `pulse_mfb_owner_first_rate`

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse.ComputeEssentialSummaryMeshPulseCLITest.test_pulse_metadata_seed_metrics_are_aggregated_and_derived -v
```

Expected: FAIL because the summary tool does not derive the new owner-first diagnostic field yet.

**Step 3: Write minimal implementation**

Teach `compute_essential_summary_mesh.py` to aggregate the new counters and derive:

- `pulse_mfb_owner_first_rate = pulse_metadata_seed_prefetch_owner_total / pulse_mfb_owner_eligible_total`

**Step 4: Run test to verify it passes**

Run the same unittest command again and expect PASS.

### Task 2: Lock experiment snapshot with failing tests

**Files:**
- Modify: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1/test_make_snapshot.py`
- Modify: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1/make_snapshot.py`

**Step 1: Write the failing test**

Extend the snapshot test to expect:

- `pulse_mfb_owner_eligible_total`
- `pulse_mfb_owner_first_rate`
- `pulse_metadata_seed_join_only_total`
- `pulse_metadata_seed_owner_already_exists_total`

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 \
  /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1/test_make_snapshot.py -v
```

Expected: FAIL because the snapshot script does not emit the new diagnostic rows yet.

**Step 3: Write minimal implementation**

Update `make_snapshot.py` so the new diagnostic counters and derived owner-first rate appear in `compare.tsv`.

**Step 4: Run test to verify it passes**

Run the same test command again and expect PASS.

### Task 3: Add isolated C0/C1 counters to the metadata-seed path

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`

**Step 1: Add new counters**

Add:

- `pulse_mfb_owner_eligible_total`
- `pulse_metadata_seed_join_only_total`
- `pulse_metadata_seed_owner_already_exists_total`

**Step 2: Increment counters at the current structural late point**

Use the existing current F2 path semantics:

- `pulse_mfb_owner_eligible_total` increments when a cross-core overlap first becomes seed-eligible (`reg.trigger_seed`)
- `pulse_metadata_seed_join_only_total` increments when the seed path registers only as a joiner (`!join.owner`)
- `pulse_metadata_seed_owner_already_exists_total` increments on the same `!join.owner` path to make the current late-trigger structure explicit

**Step 3: Export stats through the existing pulse observability path**

Make the new counters visible in SST stats and downstream summary.

### Task 4: Build and regression verification

**Files:**
- No new files beyond the above

**Step 1: Run Python regression**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse \
  sst_dram_si.mesh_template.test_runtime_pulse_config -v
```

Expected: PASS.

**Step 2: Build and install SnnDL**

Run:

```bash
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j1
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make install
```

Expected: exit `0`.

### Task 5: Fresh mainexp closure

**Files:**
- Reuse: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1/*`
- Modify if needed: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1/make_snapshot.py`

**Step 1: Run fresh baseline**

```bash
cd /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1 && \
  ./run_case.sh pulse_shared_line_actual_baseline
```

**Step 2: Run fresh candidate**

```bash
cd /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1 && \
  ./run_case.sh pulse_shared_line_actual_metadata_seed_top24_budget6
```

**Step 3: Generate compare snapshot**

```bash
cd /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1 && \
  ./make_snapshot.py
```

**Step 4: Interpret gate**

Use the new fields to answer:

- Is `pulse_mfb_owner_first_rate` still `0`?
- Are `pulse_metadata_seed_join_only_total` and `pulse_metadata_seed_owner_already_exists_total` approximately equal to `pulse_mfb_owner_eligible_total`?

If yes, the current trigger point is proven structurally too late and the next implementation phase must move to `pre-issue barrier` rather than tuning F2.

### Task 6: Record results

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Append-only progress entry**

Append:

- what changed
- verification commands
- fresh experiment paths
- new owner-first diagnostics
- explicit next-step decision

**Step 2: State explicit next gate**

If owner-first rate remains zero:

- next phase is `PULSE-MFB barrier observe / pre-band owner-first`

If owner-first rate becomes non-zero:

- next phase can consider `pre-band actual seed`
