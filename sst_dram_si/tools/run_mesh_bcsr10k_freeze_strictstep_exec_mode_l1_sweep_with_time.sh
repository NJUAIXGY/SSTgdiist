#!/usr/bin/env bash
set -euo pipefail

# Strict-step GAS fairness runner (freeze dynamics):
# - Keeps MESH_EXEC_MODE=gas (GAS pipeline enabled)
# - Enables step_seq gating at the PE boundary to disable within-step cascading
#   so gas/naive_raw share the same "no within-step cascade" step semantics.
#
# This script isolates outputs under a dedicated run group root to avoid mixing
# with legacy/non-strict runs.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Isolated output group (override via env if needed).
export MESH_BCSR10K_RUN_GROUP="${MESH_BCSR10K_RUN_GROUP:-dram_mesh_4x4_bcsr10k_freeze_step1_trend_strictstep}"

# Enable strict-step gating for GAS only (implementation lives in mesh_template/build.py).
export MESH_GAS_STEP_SEQ_GATE_ENABLE="${MESH_GAS_STEP_SEQ_GATE_ENABLE:-1}"

# Current strict-step trend experiment defaults to step-limited (1 step) for fast, low-noise sweeps.
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-1}"

# Delegate to the canonical runner (keeps all other knobs identical).
"$SCRIPT_DIR/run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_with_time.sh" "$@"
