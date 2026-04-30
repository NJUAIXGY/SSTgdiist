# PULSE Pre-Base Shared Lookup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land an isolated `PE-scoped pre_base shared lookup` path for GCSS pre-MPHF mode so repeated cross-core `{pre_global -> (base,len)}` resolution can be served once per PE-window and reused by later cores, then close the loop with an SRAM-on `mainexp` A/B.

**Architecture:** Reuse the existing PULSE PE-scoped/static-registry pattern, but target the earlier `pre_base/len` metadata object instead of exact value lines. The first core that resolves a `pre_global` in a PE/window becomes the owner-fill, stores the resolved `{base,len}` in a bounded shared registry, and later cores hit the shared entry instead of redoing the local idx lookup path. Exact value issue/retire semantics remain unchanged; only the metadata lookup service plane is shared.

**Tech Stack:** C++17 SST/SnnDL components, Python `unittest`, Python summary/snapshot tooling, `mainexp` A/B harness.

---

### Task 1: Lock runtime/config export with failing tests

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_pulse_config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/runtime.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`

**Step 1: Write the failing test**

Extend runtime pulse config tests to expect a new isolated switch:

- `pulse_prebase_shared_lookup_enable`

with env name:

- `MESH_PULSE_PREBASE_SHARED_LOOKUP_ENABLE`

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.mesh_template.test_runtime_pulse_config.RuntimePulseConfigTests.test_pulse_prebase_shared_lookup_env_is_exported_when_experimental_enable_is_on -v
```

Expected: FAIL because the runtime key does not exist yet.

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
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1/test_make_snapshot.py`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1/make_snapshot.py`

**Step 1: Write the failing tests**

Extend summary/snapshot expectations for:

- `pulse_prebase_lookup_owner_fill_total`
- `pulse_prebase_lookup_shared_hits_total`
- `pulse_prebase_lookup_entries_peak`
- derived:
  - `pulse_prebase_lookup_hit_ratio`

Also ensure snapshot can compare:

- `model.sim_time_actual_ns`
- `sram.weight_idx.lookup_total`
- `sram.weight_idx.predicted_extra_cycles_total`
- `sram.weight.bank_conflict_ticks_total`

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse.ComputeEssentialSummaryMeshPulseCLITest.test_pulse_prebase_lookup_metrics_are_aggregated_and_derived -v
```

and:

```bash
cd /home/xgy/remote && python3 \
  /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1/test_make_snapshot.py -v
```

Expected: FAIL because the new metrics are not emitted yet.

**Step 3: Write minimal implementation**

Teach summary/snapshot tooling to aggregate and emit the new stats while preserving existing rows.

**Step 4: Run tests to verify they pass**

Re-run the same commands and expect PASS.

### Task 3: Lock the pre-base shared registry contract with failing C++ tests

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_metadata_lookup_registry.cc`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/PulseMetadataLookupRegistry.h`

**Step 1: Write the failing tests**

Add a small registry test that verifies:

- the first core filling `(scope_id, window_seq, pre_global)` becomes owner-fill
- later cores hit the shared entry and get the same `{base,len}`
- repeated lookups by the same core stay deterministic
- `closeWindow(...)` clears only the targeted window state

**Step 2: Run test to verify it fails**

Run:

```bash
g++ -std=c++17 \
  -I /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL \
  /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_metadata_lookup_registry.cc \
  -o /tmp/test_pulse_metadata_lookup_registry && /tmp/test_pulse_metadata_lookup_registry
```

Expected: FAIL because the registry does not exist yet.

**Step 3: Write minimal implementation**

Implement a bounded static registry keyed by:

- `(scope_id, window_seq, pre_global)`

and storing:

- `base`
- `len`
- `owner_core_id`
- `consumer_count`

**Step 4: Run test to verify it passes**

Re-run the same compile-and-run command and expect PASS.

### Task 4: Implement the isolated pre-base shared lookup actual path

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`

**Step 1: Add new runtime knob and observability stats**

Add default-off knob:

- `pulse_prebase_shared_lookup_enable`

Add new stats:

- `pulse_prebase_lookup_owner_fill_total`
- `pulse_prebase_lookup_shared_hits_total`
- `pulse_prebase_lookup_entries_peak`

**Step 2: Use the shared registry in pre-MPHF lookup**

In `lookupGcssPreBaseLen_(...)`:

- keep non-pre-MPHF modes unchanged
- when the new knob is off, keep the old path unchanged
- when the new knob is on and `window_seq != 0`:
  - try shared lookup first
  - on hit, return shared `{base,len}` without local idx-path accounting
  - on miss, execute the current local lookup path, then publish the resolved `{base,len}` into the shared registry

**Step 3: Bound lifetime to the active window**

At `EndScatter` / window close:

- clear only the targeted PE/window entries
- keep all existing seed/frontier cleanup intact

**Step 4: Attribute stats cleanly**

Track:

- owner fills
- later shared hits
- registry entries peak

without perturbing unrelated PULSE counters.

### Task 5: Build regressions and component verification

**Files:**
- No new files beyond the above

**Step 1: Run Python regressions**

Run:

```bash
cd /home/xgy/remote && python3 -m unittest \
  sst_dram_si.mesh_template.test_runtime_pulse_config \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse -v
```

Expected: PASS.

**Step 2: Run C++ registry tests**

Run:

```bash
g++ -std=c++17 \
  -I /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL \
  /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_metadata_seed_registry.cc \
  -o /tmp/test_pulse_metadata_seed_registry && /tmp/test_pulse_metadata_seed_registry

g++ -std=c++17 \
  -I /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL \
  /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_pulse_metadata_lookup_registry.cc \
  -o /tmp/test_pulse_metadata_lookup_registry && /tmp/test_pulse_metadata_lookup_registry
```

Expected: PASS.

**Step 3: Build and install SnnDL**

Run:

```bash
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j1
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make install
```

Expected: exit `0`.

### Task 6: Add isolated SRAM-on mainexp closure

**Files:**
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1/cases.json`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1/run_case.sh`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1/make_snapshot.py`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1/test_make_snapshot.py`

**Step 1: Write the failing snapshot test**

Expect the new `compare.tsv` to include:

- validation guards
- `model.sim_time_actual_ns`
- `memory.memory_requests`
- `memhierarchy.memctrl.req_total`
- `sram.weight_idx.lookup_total`
- `sram.weight_idx.predicted_extra_cycles_total`
- `sram.weight.bank_conflict_ticks_total`
- `pulse_prebase_lookup_owner_fill_total`
- `pulse_prebase_lookup_shared_hits_total`
- `pulse_prebase_lookup_entries_peak`
- `pulse_prebase_lookup_hit_ratio`

**Step 2: Create the A/B cases**

Use the same GCSS pre-MPHF baseline as the current PULSE actual path, but explicitly enable SRAM modeling:

- `MESH_SRAM_MODEL_ENABLE=1`
- `MESH_SRAM_WEIGHT_IDX_ENABLE=1`

Candidate enables:

- `MESH_PULSE_PREBASE_SHARED_LOOKUP_ENABLE=1`

Everything else stays aligned with the current Stage-A actual shared-line baseline.

**Step 3: Run fresh A/B**

Run:

```bash
cd /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1 && \
  ./run_case.sh pulse_shared_line_actual_sram_baseline

cd /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1 && \
  ./run_case.sh pulse_shared_line_actual_sram_prebase_lookup

cd /home/xgy/remote/mainexp/experiments/2026-03-18_pulse_prebase_shared_lookup_sram_ab_v1 && \
  ./make_snapshot.py
```

Expected:

- both runs `fail=0 warn=0 strict=0`
- `memory.memory_requests` and `memctrl.req_total` stay close or identical
- `sram.weight_idx.lookup_total` drops in candidate
- candidate shows non-zero `pulse_prebase_lookup_owner_fill_total` / `pulse_prebase_lookup_shared_hits_total`
- if the model is sensitive enough, `model.sim_time_actual_ns` and/or `gas.apply_ns_avg` improve

### Task 7: Append progress log

**Files:**
- Modify (append only): `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Append completion record**

Append:

- what changed
- verification commands
- fresh run directories
- key metrics
- honest interpretation of whether this path produced PE-internal benefit
- next-step recommendation
