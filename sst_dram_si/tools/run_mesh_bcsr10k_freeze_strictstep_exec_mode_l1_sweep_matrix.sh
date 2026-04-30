#!/usr/bin/env bash
set -euo pipefail

# Strict-step GAS fairness matrix runner (freeze dynamics):
# - Runs the same sweep as run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_matrix.sh
# - But isolates outputs and enables GAS step_seq gating (no within-step cascading).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export MESH_BCSR10K_RUN_GROUP="${MESH_BCSR10K_RUN_GROUP:-dram_mesh_4x4_bcsr10k_freeze_step1_trend_strictstep}"
export MESH_GAS_STEP_SEQ_GATE_ENABLE="${MESH_GAS_STEP_SEQ_GATE_ENABLE:-1}"
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-1}"

# Delegate; its skip logic keys off meta.json (max_steps/seed/fanout/freeze), and our run group isolates runs.
"$SCRIPT_DIR/run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_matrix.sh"
