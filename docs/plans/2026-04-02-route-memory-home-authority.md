I'm using the writing-plans skill to create the implementation plan.

# Route-Memory-Home-Authority Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface the home-stack and controller-path authority provenance that already exists in the route-memory joint summaries through `analyze_ablation` so downstream exports and diagnostics can consume the values without reloading the raw summaries.

**Architecture:** Extend the helper that collapses the `home_stack_controller_proxy` payload so `route_memory_joint` rows include the authority metadata, and codify the new expectations in the ablation contract and codesign surface tests to break before implementation and pass afterward.

**Tech Stack:** Python 3, `unittest`/`pytest`, repo-local helpers under `snn3dexp.tools`.

---

### Task 1: Capture authority expectations in regression tests

**Files:**
- Modify `snn3dexp/tests/test_ablation_contract.py::AblationContractTests::test_analyze_ablation_projects_real_controller_runtime_metrics`
- Modify `snn3dexp/tests/test_memory_nmc_codesign_surface.py::MemoryNmcCodesignSurfaceTests::test_export_memory_nmc_codesign_surface_projects_home_path_authority_fields`

**Step 1: Add failing assertions**
- Assert that the `route_memory_joint` row produced by `analyze_ablation` exposes `home_stack_path_authority`, `home_stack_controller_pressure_authority`, `home_stack_runtime_authority_available`, and `dominant_home_controller_ids == "0,1"`.
- Seed the surface test’s fake route summary with `dominant_home_controller_ids` and assert that the exported row exposes the same authority provenance (path, controller-pressure, runtime availability, controller CSV).

**Step 2: Run failing test**
- Run `python -m pytest snn3dexp/tests/test_ablation_contract.py`.
- Observe the failure proving the analyzer lacks the new fields; capture the stack trace/output for future notes.

**Step 3: No code changes yet**
- Keep working tree uncommitted; the tests currently fail because fields are missing.

### Task 2: Surface authority metadata in `analyze_ablation`

**Files:**
- Modify `snn3dexp/tools/analyze_ablation.py`.

**Step 1: Add helper storage**
- Introduce `_controller_ids_csv` near the other helper utilities to canonicalize a list or iterable of controller IDs into a comma-delimited string.

**Step 2: Extend metric builder**
- Update `_build_home_stack_controller_metrics` to copy `path_authority_kind`, `controller_pressure_authority_kind`, `runtime_authority_available`, and the new CSV string for `dominant_home_controller_ids` (only when the payload supplies them) into the returned dictionary, alongside the existing metrics.

**Step 3: Run passing tests**
- Run `python -m pytest snn3dexp/tests/test_ablation_contract.py snn3dexp/tests/test_memory_nmc_codesign_surface.py`.
- Expect both suites to pass once the route row exposes the authority provenance.

**Step 4: Tidy**
- Review diffs and ensure no other parts of `analyze_ablation` require updates; keep changes narrow (no new files).

Plan complete and saved to `docs/plans/2026-04-02-route-memory-home-authority.md`. Two execution options:
1. Subagent-Driven (this session) — execute the above steps sequentially in the same workspace via `superpowers:subagent-driven-development`.
2. Parallel Planning (new session) — start a dedicated execution session with `superpowers:executing-plans` and hand off the plan.
Which approach?
