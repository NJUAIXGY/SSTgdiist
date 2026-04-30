# Neuron Mapping Acceptor V2 + Hotspot Editor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a risk-sensitive macro acceptor v2 and a block-level hotspot patch editor so macro-zone decisions can escape near-miss stable points while block refinement can still reduce tail risk under bounded communication regression.

**Architecture:** Extend the existing macro selection gate pipeline with richer risk-sensitive features, regime-aware runtime acceptance, and decision tracing. Reuse the current block-coarsened SA refinement path as the minimal hotspot patch editor host by upgrading candidate generation from generic neighboring parts to hotspot-targeted patches with bounded acceptance.

**Tech Stack:** C++17, existing `GraphPartitioningStrategy` block/macro placement pipeline, Python macro policy trainer, in-repo C++ integration tests and export smoke tests.

---

### Task 1: Add failing acceptor-v2 regression tests

**Files:**
- Modify: `experimental_features/neuron_mapping_framework/tests/test_snn_sample_export.cpp`

**Step 1: Write failing tests**
- Add one test that feeds a gate JSON with a new acceptor-v2 config and expects:
  - runtime trace contains `acceptor_type`, `acceptor_prob`, `acceptor_reason`
  - a near-miss sample is accepted when tail regression is within the configured budget and comm/hop improvement is strong enough
- Add one test that expects the same v2 config to reject when the tail regression budget is exceeded.

**Step 2: Run focused test binary to verify failure**
Run: `cd experimental_features/neuron_mapping_framework && make run-snn-export-test`
Expected: test fails because v2 fields / runtime behavior do not exist yet.

### Task 2: Implement macro risk-sensitive acceptor v2

**Files:**
- Modify: `experimental_features/neuron_mapping_framework/rl_partition_pe/train_macro_zone_policy.py`
- Modify: `experimental_features/neuron_mapping_framework/src/strategies/GraphPartitioningStrategy.cpp`

**Step 1: Extend training summaries/features**
- Add `comm_gain` and a small set of regime/risk features to `RecordConstraintSummary` and `build_acceptor_features(...)`.
- Derive a v2 config payload from trace statistics with explicit tail-regression budget and minimum comm/hop compensation.

**Step 2: Extend gate JSON schema**
- Emit a new `selection_acceptor_type` branch for v2.
- Persist enough scalar fields for runtime use and trace auditing.

**Step 3: Implement runtime acceptance**
- Parse the new v2 fields in `loadMacroSelectionGateConfig(...)`.
- In `assignPartitionsToPEs(...)`, evaluate the v2 acceptor before fallback.
- Emit trace fields for `selection_comm_gain`, `acceptor_logit`, `acceptor_prob`, `acceptor_reason`, and `acceptor_type`.

**Step 4: Re-run focused tests**
Run: `cd experimental_features/neuron_mapping_framework && make run-snn-export-test`
Expected: acceptor-v2 tests pass.

### Task 3: Add failing hotspot-editor regression tests

**Files:**
- Modify: `experimental_features/neuron_mapping_framework/tests/test_working_integration.cpp`

**Step 1: Write failing tests**
- Add one test that enables the new hotspot editor on a block-coarsened case and expects tail/objective improvement versus the same config with editor disabled.
- Add one test that ensures the editor respects a communication regression budget or no-ops when no useful patch exists.

**Step 2: Run focused integration tests to verify failure**
Run: `cd experimental_features/neuron_mapping_framework && make run-test`
Expected: new tests fail because hotspot patch editing is not implemented.

### Task 4: Implement block-level hotspot patch editor

**Files:**
- Modify: `experimental_features/neuron_mapping_framework/include/core/Types.h`
- Modify: `experimental_features/neuron_mapping_framework/src/strategies/GraphPartitioningStrategy.cpp`

**Step 1: Add config knobs**
- Introduce minimal block hotspot editor toggles and bounded runtime knobs in `MappingConfig`.

**Step 2: Upgrade candidate generation**
- In block-SA refinement, detect hotspot-driven patch candidates from `part_cut_load`, `block_adj`, and local tail-pressure signals.
- Prefer moves/swaps touching hotspot partitions before falling back to generic candidate search.

**Step 3: Add bounded acceptance and trace**
- Reuse existing objective/tail calculations and only accept patch moves that improve objective or stay within configured bounded regression.
- Emit lightweight patch trace metadata when the existing block-SA trace is enabled.

**Step 4: Re-run focused integration tests**
Run: `cd experimental_features/neuron_mapping_framework && make run-test`
Expected: hotspot-editor tests pass.

### Task 5: Full verification and progress log

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run fresh verification**
- `cd experimental_features/neuron_mapping_framework && make test-compile`
- `cd experimental_features/neuron_mapping_framework && make run-snn-export-test`
- `cd experimental_features/neuron_mapping_framework && make run-test`

**Step 2: Update progress log**
- Append what changed, how to run, observed metrics/results, and next TODOs to `TECH_PROGRESS.md`.

