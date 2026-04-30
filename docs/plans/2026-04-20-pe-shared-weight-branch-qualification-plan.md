# Shared-Weight Branch Qualification Plan Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create an isolated mainexp experiment suite that exercises the shared_weight_owner branch transition without touching the existing 2026-03-31 artifact chain.

**Architecture:** Spawn a new experiment directory (date-stamped 2026-04-14/15) that mirrors the pulse owner smoke layout but wires up three cases focused on shared-weight owner entry states, ensuring each case has its own `cases.json`, `run_case.sh`, minimal spec payload, and snapshot generator that reuses the shared gate tooling without mutating the baseline run.

**Tech Stack:** Python3-based snapshot tools (`mainexp/experiments/.../make_snapshot.py`), SST SnnDL JSON specs, shell helpers for running `python -m sst_dram_si.tools` commands, and the existing pulse owner config artifacts.

---

### Task 1: Prepare the new experiment skeleton

**Files:**
- Create: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/cases.json`
- Create: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/run_case.sh`
- Create: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/spec_shared_weight_owner_off.json`
- Create: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/spec_shared_weight_owner_req_on.json`
- Create: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/spec_shared_weight_actual_owner_on.json`
- Create: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/run_snapshot.sh`

**Step 1:** Copy the directory layout from `mainexp/experiments/2026-03-22_pulse_osa_shared_weight_owner_smoke_v1` (or owner_l0) to serve as a template for spec naming. Adjust file names to reflect the new date and shared-weight branch focus.
**Step 2:** Write `cases.json` with entries for the three scenarios (off, req_on, actual_on), pointing each to the appropriate `spec_*.json` and referencing the shared `run_snapshot.sh` for artifact generation.
**Step 3:** Craft each `spec_*.json` to toggle the shared-weight owner bits (`shared_weight_owner_enable`, `shared_weight_owner_request`, `shared_weight_actual_owner`) per case, reusing values from the pulse owner smoke experiments but not overriding baseline directories.
**Step 4:** `run_case.sh` should accept a case name, set `CASE_DIR`, and invoke the relevant SST driver (placeholder command) plus `run_snapshot.sh`; include guard flags to keep this experiment isolated.
**Step 5:** `run_snapshot.sh` hooks into the new `cases.json` to call the existing `make_snapshot.py` (from 2026-03-31 experiment) but writing outputs under the new directory.
**Step 6:** Validate the shell scripts for syntax with `env -i /bin/sh -n run_case.sh` and `run_snapshot.sh`.

### Task 2: Populate case payloads and metadata

**Files:**
- Modify: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/spec_shared_weight_owner_off.json`
- Modify: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/spec_shared_weight_owner_req_on.json`
- Modify: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/spec_shared_weight_actual_owner_on.json`
- Create: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/metadata.yaml`

**Step 1:** For each spec, define the minimal synapse activation configuration plus flags that control `shared_weight_owner_state` (mirroring the data in the March 22 experiments). Keep the rest of the config identical to the baseline to limit drift.
**Step 2:** In `metadata.yaml`, describe the branch qualification purpose, case-to-flag mapping, and expected gate names so reviewers have a quick reference.
**Step 3:** Use `jq` or Python to lint the JSON (e.g., `python -m json.tool spec_shared_weight_owner_off.json`).

### Task 3: Hook into artifact generation

**Files:**
- Create: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/snapshot_config.toml`
- Modify: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/run_snapshot.sh`

**Step 1:** `snapshot_config.toml` should define the output directories for `compare.tsv`, `gate_summary.tsv`, and `gate_summary.json` so they land under the new experiment hierarchy.
**Step 2:** Update `run_snapshot.sh` to source `snapshot_config.toml`, run the canonical `make_snapshot.py` (without altering the March 31 experiment), and capture outputs in the new `snapshot` directory.
**Step 3:** After a run, include commands to `ls snapshot` to make it easy to confirm the artifacts exist.

### Task 4: Smoke validation and instructions

**Files:**
- Modify: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/run_case.sh`
- Create: `mainexp/experiments/2026-04-14_shared_weight_branch_qualification/README.md`

**Step 1:** Add a `--dry-run` mode to `run_case.sh` that prints the command it would run, enabling quick verification of the case selection logic.
**Step 2:** Document in `README.md` how to execute a case, trigger snapshot refresh, and interpret `gate_summary.tsv`. Include notes on required environment variables and the expectation that this is architecture-first modeling work (no performance claims).
**Step 3:** Validate the README instructions by running `bash run_case.sh shared_weight_owner_req_on --dry-run` and capturing the expected output text.

### Task 5: Integration checklist updates

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1:** Append a section describing the new experiment, referencing the new directory, cases, and how to run them.
**Step 2:** Note the validation commands executed (shell syntax checks, dry runs) and that artifact generation remains tied to the 2026-03-31 `make_snapshot` script to avoid duplication.
**Step 3:** Include future next steps (e.g., hooking WP2 after shared-weight request data is captured) so the stage progression remains visible.

### Task 6: Execution handoff

**Step 1:** Save this plan and report back: detail the plan file location and ask whether to execute the plan here (subagent-driven) or hand off. Provide the two execution options as required by the writing-plans skill.

