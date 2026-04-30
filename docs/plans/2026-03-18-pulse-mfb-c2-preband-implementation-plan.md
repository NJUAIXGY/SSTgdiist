# PULSE-MFB C2 Pre-Band Owner-First Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land an isolated `pre-band owner-first seed` path that can create real resident/join opportunities before exact value-line demand, while preserving the current exact commit contract and keeping all knobs default-off.

**Architecture:** Reuse the existing `PulseSharedLineService + PulseSeededLineResidency` service plane, but move seed formation from `exact-line-per-base F2` to a new `pre-band` barrier object. The new path groups early GCSS pre-MPHF bands, elects a single owner per overlapped band, launches a bounded set of candidate line prefetches ahead of exact demand, and lets demand stay purely `resident hit / inflight join / fallback`. Existing F2 stays untouched so we can compare them cleanly.

**Tech Stack:** C++17 SST/SnnDL components, Python `unittest`, Python summary/snapshot tooling, `mainexp` A/B harness.

---

### Task 1: Lock runtime/config export with failing tests

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_pulse_config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/runtime.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`

**Step 1: Write the failing test**

Extend runtime pulse config tests to expect a new isolated config group:

- `mfb_preband_seed_enable`
- `mfb_preband_top_bands`
- `mfb_preband_lines_per_band`
- `mfb_preband_window_budget`

with env names:

- `MESH_PULSE_MFB_PREBAND_SEED_ENABLE`
- `MESH_PULSE_MFB_PREBAND_TOP_BANDS`
- `MESH_PULSE_MFB_PREBAND_LINES_PER_BAND`
- `MESH_PULSE_MFB_PREBAND_WINDOW_BUDGET`

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.mesh_template.test_runtime_pulse_config.RuntimePulseConfigTests.test_pulse_mfb_preband_seed_env_is_exported_when_experimental_enable_is_on -v
```

Expected: FAIL because the new runtime keys do not exist yet.

**Step 3: Write minimal implementation**

Plumb the new default-off config through:

- local-run config ingestion
- env overrides
- runtime export
- effective config
- component params

**Step 4: Run test to verify it passes**

Run the same unittest command again and expect PASS.

### Task 2: Lock summary and snapshot metrics with failing tests

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- Modify: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1/test_make_snapshot.py`
- Modify: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1/make_snapshot.py`

**Step 1: Write the failing tests**

Extend summary and snapshot expectations for the new `pre-band` actual path:

- `pulse_mfb_owner_launched_total`
- `pulse_mfb_preband_candidates_total`
- `pulse_mfb_preband_lines_selected_total`
- `pulse_mfb_preband_lines_owner_total`
- `pulse_mfb_preband_lines_join_only_total`
- derived:
  - `pulse_mfb_owner_first_rate`

The derived rate should prefer:

- `pulse_mfb_owner_launched_total / pulse_mfb_owner_eligible_total`

and fall back to the legacy F2 formula when the new launched stat is absent.

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse.ComputeEssentialSummaryMeshPulseCLITest.test_pulse_mfb_preband_metrics_are_aggregated_and_derived -v
```

and

```bash
cd /home/xgy/remote && python3 \
  /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1/test_make_snapshot.py -v
```

Expected: FAIL because the new metrics are not yet emitted.

**Step 3: Write minimal implementation**

Teach summary/snapshot tooling to aggregate and emit the new stats without changing existing rows.

**Step 4: Run tests to verify they pass**

Re-run the same two commands and expect PASS.

### Task 3: Lock the pre-band registry contract with failing C++ tests

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_metadata_seed_registry.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseMetadataSeedRegistry.h`

**Step 1: Write the failing tests**

Extend the existing registry smoke test so it verifies:

- two distinct cores touching the same band can trigger a single owner launch
- candidate line addresses are aligned and deduplicated
- selected lines are bounded by `max_lines`
- later registrations on the same band do not retrigger owner launch

**Step 2: Run test to verify it fails**

Run:

```bash
g++ -std=c++17 \
  -I /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL \
  /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_metadata_seed_registry.cc \
  -o /tmp/test_pulse_metadata_seed_registry && /tmp/test_pulse_metadata_seed_registry
```

Expected: FAIL because the registry does not support `pre-band` aggregation yet.

**Step 3: Write minimal implementation**

Extend `PulseMetadataSeedRegistry` with a `registerBandCandidate(...)` path that:

- keys by `(scope_id, window_seq, band_id)`
- tracks `consumer_bitmap`
- records unique aligned candidate line addresses
- triggers once when `consumer_count >= 2`

**Step 4: Run test to verify it passes**

Re-run the same compile-and-run command and expect PASS.

### Task 4: Implement isolated C2 pre-band owner-first path

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`

**Step 1: Add new runtime knobs and stats**

Add default-off knobs:

- `pulse_mfb_preband_seed_enable`
- `pulse_mfb_preband_top_bands`
- `pulse_mfb_preband_lines_per_band`
- `pulse_mfb_preband_window_budget`

Add new observability stats:

- `pulse_mfb_owner_launched_total`
- `pulse_mfb_preband_candidates_total`
- `pulse_mfb_preband_lines_selected_total`
- `pulse_mfb_preband_lines_owner_total`
- `pulse_mfb_preband_lines_join_only_total`

**Step 2: Generalize seeded-residency gating**

Make the exact demand resident lookup path active when either:

- legacy `pulse_metadata_seed_enable`
- new `pulse_mfb_preband_seed_enable`

is on.

**Step 3: Add pre-band owner-first launch**

In `prepareGcssVlfIssueQueue_()`:

- keep existing frontier observe / F2 exact-line logic unchanged
- add a new `maybeLaunchPulseMfbPrebandSeeds_(ordered)` path after metadata frontier observe
- scan top unique bands only
- use the registry to form one owner-launch event per overlapped band
- for each selected line, reuse the existing seeded line service path

**Step 4: Attribute new stats cleanly**

Track:

- object-level owner eligibility / launched counts
- line-level selected / owner / join-only counts

without weakening any existing F2 counters.

### Task 5: Build regressions and component verification

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

**Step 2: Run C++ registry smoke**

Run:

```bash
g++ -std=c++17 \
  -I /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL \
  /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_metadata_seed_registry.cc \
  -o /tmp/test_pulse_metadata_seed_registry && /tmp/test_pulse_metadata_seed_registry
```

Expected: PASS.

**Step 3: Build and install SnnDL**

Run:

```bash
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j1
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make install
```

Expected: exit `0`.

### Task 6: Add isolated mainexp closure for C2

**Files:**
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_preband_actual_ab_v1/cases.json`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_preband_actual_ab_v1/run_case.sh`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_preband_actual_ab_v1/make_snapshot.py`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_preband_actual_ab_v1/test_make_snapshot.py`

**Step 1: Write the failing snapshot test**

Expect the new `compare.tsv` to include:

- `pulse_mfb_owner_eligible_total`
- `pulse_mfb_owner_launched_total`
- `pulse_mfb_owner_first_rate`
- `pulse_mfb_preband_candidates_total`
- `pulse_mfb_preband_lines_selected_total`
- `pulse_mfb_preband_lines_owner_total`
- `pulse_mfb_preband_lines_join_only_total`
- plus resident-hit usefulness guards

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 \
  /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_preband_actual_ab_v1/test_make_snapshot.py -v
```

Expected: FAIL because the new experiment snapshot does not exist yet.

**Step 3: Write minimal experiment harness**

Create a new isolated A/B experiment:

- baseline: existing Stage-A actual shared-line baseline
- candidate: baseline + `MESH_PULSE_MFB_PREBAND_SEED_ENABLE=1`

with conservative starter knobs:

- `TOP_BANDS=24`
- `LINES_PER_BAND=4`
- `WINDOW_BUDGET=6`

**Step 4: Run test to verify it passes**

Re-run the same snapshot test command and expect PASS.

### Task 7: Fresh A/B closure and progress log

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run fresh baseline and candidate**

Run:

```bash
cd /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_preband_actual_ab_v1 && \
  ./run_case.sh pulse_shared_line_actual_baseline
```

and

```bash
cd /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_preband_actual_ab_v1 && \
  ./run_case.sh pulse_shared_line_actual_mfb_preband_top24_lines4_budget6
```

**Step 2: Generate compare snapshot**

Run:

```bash
cd /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_mfb_preband_actual_ab_v1 && \
  ./make_snapshot.py
```

**Step 3: Interpret the gate**

Use fresh results to answer:

- Is `pulse_mfb_owner_launched_total > 0`?
- Is `pulse_mfb_owner_first_rate > 0`?
- Is `pulse_metadata_seed_resident_hits_total > 0`?
- Do `memory_requests` / `memctrl.req_total` / `sim_time_actual_ns` stay non-regressive?

If yes, this confirms we have crossed from `late-join-only` into real owner-first territory.

**Step 4: Append TECH_PROGRESS.md**

Append-only entry must include:

- what changed
- verification commands
- experiment paths
- fresh metrics
- interpretation
- explicit next step (`idx2 / rowidx` or retune pre-band budget)
