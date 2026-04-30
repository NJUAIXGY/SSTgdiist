#!/usr/bin/env bash
set -euo pipefail

# Read-only freeze (paper fairness) single-point runner:
# - step-limited: MESH_MAX_STEPS=1
# - strict-step: disable within-step cascading (GAS uses the same step_seq gating as naive_raw)
# - read-only freeze: no firing (very high v_thresh) + strong leak (tiny tau_mem)
#
# This script is experiment-scoped: it only sets env overrides and delegates to the paper-grade runner.
#
# Output root (grouped):
#   sst_dram_si/outputs_large/paper2/${MESH_BCSR10K_RUN_GROUP}/{gas|naive_raw}/l1_${MESH_L1_ENABLE}/frac_${MESH_STEP_ACTIVATION_FRACTION}/<timestamp>/

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export MESH_BCSR10K_RUN_GROUP="${MESH_BCSR10K_RUN_GROUP:-dram_mesh_4x4_bcsr10k_readonly_step1_strictstep}"

# One step only (avoid time-based run-to-100us drift).
export MESH_MAX_STEPS="1"

# Use the global barrier controller for deterministic step boundaries.
export MESH_GLOBAL_STEP_SYNC="1"
export MESH_GLOBAL_STEP_DONE_POLICY="${MESH_GLOBAL_STEP_DONE_POLICY:-drain}"
export MESH_GLOBAL_STEP_DRAIN_MIN_CYCLES="${MESH_GLOBAL_STEP_DRAIN_MIN_CYCLES:-200}"

# Fairness: disable within-step cascading for BOTH gas and naive baselines.
export MESH_GAS_STEP_SEQ_GATE_ENABLE="1"

# Read-only freeze: still reads weights, but disables firing and suppresses persistence of dv.
export MESH_FREEZE_READONLY="1"
export MESH_READONLY_V_THRESH="${MESH_READONLY_V_THRESH:-1000000000.0}"
export MESH_READONLY_TAU_MEM="${MESH_READONLY_TAU_MEM:-0.001}"

# Keep logs quiet for performance runs.
export MESH_QUIET="1"

# Keep "freeze" semantics consistent across shells (avoid env stickiness).
export MESH_STEP_RESET_MEM_EACH_STEP="1"
export MESH_ALLOW_ZERO_FIRING_LONG="1"

# Default to L1 disabled unless user overrides.
export MESH_L1_ENABLE="${MESH_L1_ENABLE:-0}"

if [ -z "${MESH_STEP_ACTIVATION_FRACTION:-}" ]; then
  echo "[readonly-step1] missing MESH_STEP_ACTIVATION_FRACTION (e.g. 0.01)"
  exit 2
fi

echo "[readonly-step1] run_group=$MESH_BCSR10K_RUN_GROUP frac=$MESH_STEP_ACTIVATION_FRACTION l1=$MESH_L1_ENABLE max_steps=$MESH_MAX_STEPS"
echo "[readonly-step1] readonly: v_thresh=$MESH_READONLY_V_THRESH tau_mem=$MESH_READONLY_TAU_MEM"

"$SCRIPT_DIR/run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_with_time.sh" "gas"
"$SCRIPT_DIR/run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_with_time.sh" "naive_raw"
