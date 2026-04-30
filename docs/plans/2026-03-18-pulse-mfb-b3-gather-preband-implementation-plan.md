# PULSE-MFB B3 Gather-PreBand Barrier Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move `PULSE-MFB` from the too-late `BeginApply issue-queue` trigger to a `Gather-collected, BeginApply-launched` pre-band barrier that stays compatible with the current `gcss_valueonly_dstcore_vlf_premphf_plp` mainline and can materially increase `ready-before-demand` for shared line service.

**Architecture:** Reuse the current `PulseMetadataSeedRegistry + PulseSharedLineService + PulseSeededLineResidency + PulseSeededLineTracker` service plane, but stop discovering pre-band candidates from the already-ordered exact issue queue. Instead, collect top gathered `pre_band -> candidate line` objects while spikes are still being recorded in the Gather window, persist them in a small per-core pending collector, and replay them into the existing PE-scoped owner-election path immediately after `beginApplyWindow(seq)` and before exact issue preparation. This keeps the optimization default-off, PE-internal, service-plane-only, and comparable against the current C2 `apply-stage preband` path.

**Tech Stack:** C++17 SST/SnnDL components, Python mesh runtime/config tooling, Python `unittest`, `mainexp` harness, append-only progress logging.

---

### Task 1: Lock runtime/config export for the new gather-preband path

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_pulse_config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/runtime.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`

**Step 1: Write the failing test**

Extend runtime pulse config tests to expect a new isolated config group:

- `pulse_mfb_gather_preband_enable`
- `pulse_mfb_gather_top_bands`
- `pulse_mfb_gather_lines_per_band`
- `pulse_mfb_gather_window_budget`

with env names:

- `MESH_PULSE_MFB_GATHER_PREBAND_ENABLE`
- `MESH_PULSE_MFB_GATHER_TOP_BANDS`
- `MESH_PULSE_MFB_GATHER_LINES_PER_BAND`
- `MESH_PULSE_MFB_GATHER_WINDOW_BUDGET`

and verify they are ignored unless `MESH_EXPERIMENTAL_ENABLE=1`.

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.mesh_template.test_runtime_pulse_config.RuntimePulseConfigTests.test_pulse_mfb_gather_preband_env_is_exported_when_experimental_enable_is_on -v
```

Expected: FAIL because the new gather-preband keys are not exported yet.

**Step 3: Write minimal implementation**

Plumb the new default-off fields through:

- env overrides
- runtime mesh config
- effective config export
- component param emission

without changing any existing `pulse_mfb_preband_seed_enable` behavior.

**Step 4: Run test to verify it passes**

Re-run the same unittest command and expect PASS.

### Task 2: Lock summary and snapshot metrics for gather-preband diagnostics

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_gbi_stepgate_progress_plumbing.py`

**Step 1: Write the failing tests**

Extend summary/plumbing expectations for a gather-preband namespace:

- `pulse_mfb_gather_owner_eligible_total`
- `pulse_mfb_gather_owner_launched_total`
- `pulse_mfb_gather_preband_candidates_total`
- `pulse_mfb_gather_preband_lines_selected_total`
- `pulse_mfb_gather_preband_lines_owner_total`
- `pulse_mfb_gather_preband_lines_join_only_total`
- `pulse_mfb_gather_head_distance_sum_total`
- `pulse_mfb_gather_head_distance_samples_total`
- `pulse_mfb_gather_seed_to_first_demand_cycles_total`
- `pulse_mfb_gather_seed_to_first_demand_samples_total`
- `pulse_mfb_gather_seed_ready_before_demand_total`
- `pulse_mfb_gather_seed_inflight_join_total`

and derived fields:

- `pulse_mfb_gather_owner_first_rate`
- `pulse_mfb_gather_head_distance_avg`
- `pulse_mfb_gather_seed_to_first_demand_cycles_avg`
- `pulse_mfb_gather_ready_before_demand_ratio`

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse.ComputeEssentialSummaryMeshPulseCLITest.test_pulse_mfb_gather_preband_metrics_are_aggregated_and_derived -v
```

and

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.tools.test_gbi_stepgate_progress_plumbing.GbiStepgateProgressPlumbingTest.test_pulse_gather_preband_statistics_are_declared_and_forwarded -v
```

Expected: FAIL because the new gather-preband metrics are not emitted yet.

**Step 3: Write minimal implementation**

Teach the summary/plumbing path to surface the new metrics while keeping:

- legacy C2 `pulse_mfb_*`
- metadata-seed `pulse_metadata_*`
- prebase shared lookup `pulse_prebase_*`

fully unchanged.

**Step 4: Run tests to verify they pass**

Re-run the same unittest commands and expect PASS.

### Task 3: Lock the gather collector contract with failing C++ tests

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseGatherPrebandCollector.h`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_gather_preband_collector.cc`

**Step 1: Write the failing tests**

Add a focused collector test that verifies:

- repeated edges from the same core/window deduplicate the same aligned line
- lines are grouped by `band_id`
- earliest touch rank is preserved as the ordering key
- per-band line selection is capped by `lines_per_band`
- emitted band order is bounded by `top_bands`

**Step 2: Run test to verify it fails**

Run:

```bash
g++ -std=c++17 \
  -I /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL \
  /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_gather_preband_collector.cc \
  -o /tmp/test_pulse_gather_preband_collector && /tmp/test_pulse_gather_preband_collector
```

Expected: FAIL because the collector does not exist yet.

**Step 3: Write minimal implementation**

Implement a tiny per-core/window helper that stores:

- `band_id`
- `min_touch_rank`
- `selected_line_addrs`

with deterministic, bounded replay order.

**Step 4: Run test to verify it passes**

Re-run the same compile-and-run command and expect PASS.

### Task 4: Implement gather-collected candidate formation in `WeightMemorySubsystem`

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`

**Step 1: Add isolated knobs, stats, and source tags**

Add a new source enum for gather-preband launches and new counters for the gather namespace only.

**Step 2: Add a raw pre-MPHF helper**

Split the current pre-MPHF metadata lookup so gather-time collection can obtain:

- `pre_base`
- `pre_len`

without consuming the existing `pulse_prebase_shared_lookup_enable` actual-path counters.

**Step 3: Hook candidate collection to the earliest path with full metadata**

From `recordEdgeWithPreRankCount(...)`, when:

- `isGcssValueOnlyPreMphfMode_()`
- `pulse_mfb_gather_preband_enable`
- loader/index state is ready

compute:

- `band_id = pre_base / band_slots`
- `widx = pre_base + pre_rank`
- `line_addr = align_down(gcssValuesBaseAddr() + widx * sizeof(float))`

and store it into the new `PulseGatherPrebandCollector`.

**Step 4: Reset and carry the collector across windows safely**

Reset the collector on window-clear / rollover exactly where current edge/pre-rank state is reset, so stale gather data can never leak into a later window.

### Task 5: Replay gathered bands into the existing owner-first service plane

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseMetadataSeedRegistry.h`

**Step 1: Add a new replay point at the start of Apply**

Immediately after `beginApplyWindow(seq)` establishes `window_seq_`, and before the exact GCSS-VLF issue queue is prepared, replay the local collected bands into the existing PE-scoped `PulseMetadataSeedRegistry`.

**Step 2: Reuse existing line-service machinery**

For each triggered owner launch:

- reuse `issuePulseSeededLine_(...)`
- reuse `PulseSharedLineService`
- reuse `PulseSeededLineResidency`
- reuse `PulseSeededLineTracker`

but attribute everything to the new `PulseSeedSource::MfbGatherPreband`.

**Step 3: Keep C2 apply-stage preband untouched**

The old `pulse_mfb_preband_seed_enable` path must remain:

- default-off
- behaviorally unchanged
- independently comparable

No mixing of gather-stage and apply-stage counters is allowed.

**Step 4: Preserve exactness boundaries**

Confirm the new replay point:

- does not modify retire order
- does not register architectural state early
- only changes service timing and residency timing

### Task 6: Plumb stats through PE/component boundaries

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`

**Step 1: Add params and ELI/stat declarations**

Declare the new gather-preband params and statistics in:

- component param docs
- `SST_ELI_DOCUMENT_STATISTICS`
- `registerStatistic(...)`

**Step 2: Forward the new WMS counters**

Extend the existing `recordPulseAgendaObservability(...)` forwarding path so the gather-preband stats appear in PE-level stats and CSV exports.

**Step 3: Re-run plumbing tests**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.tools.test_gbi_stepgate_progress_plumbing -v
```

Expected: PASS.

### Task 7: Build regressions and focused verification

**Files:**
- No new files beyond the above

**Step 1: Run Python regression**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.mesh_template.test_runtime_pulse_config \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse \
  sst_dram_si.tools.test_gbi_stepgate_progress_plumbing -v
```

Expected: PASS.

**Step 2: Run C++ collector smoke**

Run:

```bash
g++ -std=c++17 \
  -I /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL \
  /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_gather_preband_collector.cc \
  -o /tmp/test_pulse_gather_preband_collector && /tmp/test_pulse_gather_preband_collector
```

Expected: PASS.

**Step 3: Build and install SnnDL**

Run:

```bash
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j1
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make install
```

Expected: exit `0`.

### Task 8: Add isolated `mainexp` closure for the gather-preband route

**Files:**
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_gather_preband_actual_ab_v1/cases.json`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_gather_preband_actual_ab_v1/run_case.sh`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_gather_preband_actual_ab_v1/make_snapshot.py`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_gather_preband_actual_ab_v1/test_make_snapshot.py`

**Step 1: Baseline case**

Reuse the current Stage-A actual baseline:

- `pulse_shared_line_actual_baseline`

**Step 2: Candidate case**

Enable only the new gather-preband path:

- `MESH_PULSE_MFB_GATHER_PREBAND_ENABLE=1`
- `MESH_PULSE_MFB_GATHER_TOP_BANDS=24`
- `MESH_PULSE_MFB_GATHER_LINES_PER_BAND=4`
- `MESH_PULSE_MFB_GATHER_WINDOW_BUDGET=6`

Keep legacy `pulse_mfb_preband_seed_enable=0` so the comparison is clean.

**Step 3: Optional reference case**

If the snapshot helper can stay simple, add the existing C2 apply-stage candidate as a third reference column:

- `pulse_shared_line_actual_mfb_preband_top24_lines4_budget6`

This is optional; do not complicate the harness if it delays the first closure.

**Step 4: Generate compare snapshot**

Include:

- mainline timing/memory metrics
- new gather-preband metrics
- direct comparison against the old C2 lead-time numbers when available

### Task 9: Append progress and decide the next gate

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Append-only progress entry**

Record:

- what changed
- how to run / verify
- fresh experiment directories
- gather-preband lead-time and usefulness metrics
- whether `ready-before-demand` materially improved over C2

**Step 2: State the next gate explicitly**

If gather-preband improves:

- `pulse_mfb_gather_ready_before_demand_ratio`
- `pulse_mfb_gather_seed_to_first_demand_cycles_avg`
- and begins reducing `memory_requests` or `apply_ns_avg`

then the next batch is:

- `current-mainline gather-barrier tuning`
- followed by `prebase metadata-object actualization`

If gather-preband still mostly collapses into inflight-join, stop patching line service again and pivot to:

- `prebase/idx2 metadata-object actual path`
- with `rowidx` kept as a separate BCSR-only sidecar line.
