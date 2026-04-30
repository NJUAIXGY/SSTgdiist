# Snn3dexp Memory/NMC Co-Design Comparison Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the current `snn3dexp` analysis surface so it can directly explain home-access-driven memory pressure and expose `direct_v4 vs bundle_v3` plus `HBM-like NMC vs monolithic-like near-memory proxy` as first-class comparison baselines.

**Architecture:** Extend `route_memory_joint_summary` from a metrics dump into a causal bridge between home access classes and runtime service deficit. Then lift that enriched signal into `analyze_ablation.py`, so the baseline suite can compare routing style and memory model choices using one consistent case-level surface.

**Tech Stack:** Python 3, `unittest`, JSON summaries under `snn3dexp/analysis`, existing `snn3dexp/tools` analysis scripts

---

### Task 1: Plan The Home-Access Pressure Contract

**Files:**
- Modify: `snn3dexp/tests/test_route_memory_joint_analysis.py`
- Modify: `snn3dexp/tools/analyze_route_memory_joint.py`

**Step 1: Write the failing test**

Add assertions that require `build_route_memory_joint_summary()` to emit:
- `memory.home_access_pressure.classes.<class>.gather_demands_total`
- `memory.home_access_pressure.classes.<class>.stream_demands_total`
- `memory.home_access_pressure.classes.<class>.total_demands`
- `memory.home_access_pressure.classes.<class>.demand_share`
- `memory.home_access_pressure.classes.<class>.service_deficit_attribution`
- `memory.home_access_pressure.dominant_home_access_class`
- `memory.home_access_pressure.dominant_pressure_region`

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest snn3dexp.tests.test_route_memory_joint_analysis -v`
Expected: FAIL because `home_access_pressure` is not present yet.

**Step 3: Write minimal implementation**

Add a helper in `analyze_route_memory_joint.py` that aggregates:
- `tier_local_home`
- `same_xy_cross_tier`
- `remote_home`

Use existing per-node traffic semantic counters when available, compute demand totals and demand shares, and attribute region service deficit proportionally to each class's demand mix.

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest snn3dexp.tests.test_route_memory_joint_analysis -v`
Expected: PASS

### Task 2: Make Route Compression A First-Class Comparison

**Files:**
- Modify: `snn3dexp/tests/test_phase2_baseline_suite.py`
- Modify: `snn3dexp/tests/test_ablation_contract.py`
- Modify: `snn3dexp/tools/analyze_ablation.py`

**Step 1: Write the failing test**

Add an ablation test that requires:
- `route_memory_comparisons.direct_v4_vs_bundle_v3`
- base case `full_3d`
- compare case `full_3d_tile_bundle_v3`
- route mix, memory requests, total service deficit, most pressured region, gather/stream backlog deltas

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest snn3dexp.tests.test_phase2_baseline_suite snn3dexp.tests.test_ablation_contract -v`
Expected: FAIL because comparison payload is absent.

**Step 3: Write minimal implementation**

Teach `analyze_ablation.py` to derive comparison payloads from existing case summaries:
- read route version metrics from `route_memory_joint`
- read runtime deficits/backlogs from `route_memory_joint.memory.traffic_driven_runtime`
- emit a normalized route-compression comparison block

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest snn3dexp.tests.test_phase2_baseline_suite snn3dexp.tests.test_ablation_contract -v`
Expected: PASS

### Task 3: Promote HBM-like vs Monolithic-like Into Main Baseline Surface

**Files:**
- Modify: `snn3dexp/tests/test_phase2_baseline_suite.py`
- Modify: `snn3dexp/tests/test_ablation_contract.py`
- Modify: `snn3dexp/tools/analyze_ablation.py`

**Step 1: Write the failing test**

Add assertions that require:
- `memory_model_comparisons.hbm_like_vs_monolithic_like`
- base case `full_3d`
- compare case `full_3d_monolithic_proxy`
- memory-model family, vertical hops, remote-home ratio, total service deficit, vertical link pressure, reliability penalty

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest snn3dexp.tests.test_phase2_baseline_suite snn3dexp.tests.test_ablation_contract -v`
Expected: FAIL because memory-model comparison payload is absent.

**Step 3: Write minimal implementation**

Extend `analyze_ablation.py` to export a second normalized comparison surface for memory/NMC baselines and preserve backward compatibility for existing case summaries.

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest snn3dexp.tests.test_phase2_baseline_suite snn3dexp.tests.test_ablation_contract -v`
Expected: PASS

### Task 4: Full Regression And Progress Log

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run focused regression**

Run:
- `python3 -m unittest snn3dexp.tests.test_route_memory_joint_analysis -v`
- `python3 -m unittest snn3dexp.tests.test_phase2_baseline_suite -v`
- `python3 -m unittest snn3dexp.tests.test_ablation_contract -v`
- `python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics -v`
- `python3 -m unittest snn3dexp.tests.test_monolithic_memory_proxy -v`

Expected: PASS

**Step 2: Append progress log**

Append a new `TECH_PROGRESS.md` entry documenting:
- new `home_access_pressure` contract
- new route-compression comparison surface
- new HBM-vs-monolithic baseline surface
- verification commands and results

**Step 3: Final verification**

Run: `tail -n 80 TECH_PROGRESS.md`
Expected: new entry appears at file end only
