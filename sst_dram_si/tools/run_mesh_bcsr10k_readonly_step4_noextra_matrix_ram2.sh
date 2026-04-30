#!/usr/bin/env bash
set -euo pipefail

# Paper-grade Step=4 experiment matrix (NO extra BCSR datasets) on Ramulator2 backend.
#
# - Baselines:           MESH_EXEC_MODE=gas vs naive_raw
# - Termination:         step-limited (MESH_MAX_STEPS=4)
# - Fairness:            strict-step gating (no within-step cascading)
# - Dynamics:            read-only freeze (still reads weights, but disables firing)
# - Memory backend:      memHierarchy.ramulator2 (configFile required)
#
# Sweep (default):
#   - fraction sweep @ fanout=256  (reuses weights/bcsr_global_16pe_fanout256_10k)
#
# NOTE: We intentionally do NOT run a fanout sweep by default to avoid accidental large
# output trees and repeated manual cleanups. Enable it explicitly if needed.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MATRIX_SH="$SCRIPT_DIR/run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_matrix.sh"
SUMMARIZE_PY="$PROJECT_ROOT/tools/summarize_mesh_bcsr10k_freeze_exec_mode_l1_sweep.py"
OUTPUT_BASE="$PROJECT_ROOT/outputs_large/paper2"

if [ ! -x "$MATRIX_SH" ]; then
  echo "[step4-ram2] ERROR: missing runner: $MATRIX_SH"
  exit 2
fi
if [ ! -f "$SUMMARIZE_PY" ]; then
  echo "[step4-ram2] ERROR: missing summarizer: $SUMMARIZE_PY"
  exit 2
fi

# -------- Common invariants (avoid env stickiness across runs) --------
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-4}"
export MESH_SWEEP_L1="${MESH_SWEEP_L1:-0}"
export MESH_SWEEP_MODES="${MESH_SWEEP_MODES:-gas naive_raw}"
export MESH_SWEEP_REPEATS="${MESH_SWEEP_REPEATS:-2}"
export MESH_SWEEP_RETRY_MAX="${MESH_SWEEP_RETRY_MAX:-3}"

export MESH_STEP_ACTIVATION_SEED="${MESH_STEP_ACTIVATION_SEED:-314159}"

# Deterministic step boundaries (platform control; allowed for both baselines).
export MESH_GLOBAL_STEP_SYNC="1"
export MESH_GLOBAL_STEP_DONE_POLICY="${MESH_GLOBAL_STEP_DONE_POLICY:-drain}"
export MESH_GLOBAL_STEP_DRAIN_MIN_CYCLES="${MESH_GLOBAL_STEP_DRAIN_MIN_CYCLES:-200}"

# Fairness: disable within-step cascading (GAS uses the same step_seq gating as naive_raw).
export MESH_GAS_STEP_SEQ_GATE_ENABLE="${MESH_GAS_STEP_SEQ_GATE_ENABLE:-1}"

# Read-only freeze (still exercises memory/NoC; disables firing).
export MESH_FREEZE_READONLY="1"
export MESH_READONLY_V_THRESH="${MESH_READONLY_V_THRESH:-1000000000.0}"
export MESH_READONLY_TAU_MEM="${MESH_READONLY_TAU_MEM:-0.001}"
export MESH_STEP_RESET_MEM_EACH_STEP="1"
export MESH_ALLOW_ZERO_FIRING_LONG="1"

# Keep logs quiet for performance runs.
export MESH_QUIET="${MESH_QUIET:-1}"

# -------- Ramulator2 backend --------
export MESH_MEM_BACKEND="ramulator2"
export MESH_RAMULATOR2_CONFIG_FILE="${MESH_RAMULATOR2_CONFIG_FILE:-$PROJECT_ROOT/configs/ramulator2_ddr4_openrow.cfg}"
if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
  echo "[step4-ram2] ERROR: missing ramulator2 config: $MESH_RAMULATOR2_CONFIG_FILE"
  exit 2
fi

CFG_TAG="$(basename "$MESH_RAMULATOR2_CONFIG_FILE")"
CFG_TAG="${CFG_TAG%.cfg}"
CFG_TAG="$(printf "%s" "$CFG_TAG" | tr '[:upper:]' '[:lower:]' | sed -e 's/[^a-z0-9_]/_/g')"

echo "[step4-ram2] mem_backend=$MESH_MEM_BACKEND cfg=$MESH_RAMULATOR2_CONFIG_FILE tag=$CFG_TAG"
echo "[step4-ram2] max_steps=$MESH_MAX_STEPS repeats=$MESH_SWEEP_REPEATS modes=($MESH_SWEEP_MODES) l1=($MESH_SWEEP_L1)"
echo "[step4-ram2] seed=$MESH_STEP_ACTIVATION_SEED strict_step_gate=$MESH_GAS_STEP_SEQ_GATE_ENABLE"
echo "[step4-ram2] readonly: v_thresh=$MESH_READONLY_V_THRESH tau_mem=$MESH_READONLY_TAU_MEM"

# -------- Fraction sweep (fanout=256, reuse existing 10k BCSR) --------
GROUP_FRAC="${MESH_STEP4_FRAC_RUN_GROUP:-dram_mesh_4x4_bcsr10k_readonly_step4_frac_sweep_${CFG_TAG}_v1}"
export MESH_BCSR10K_RUN_GROUP="$GROUP_FRAC"
export MESH_STEP_ACTIVATION_FANOUT="256"
export MESH_SWEEP_FRACTIONS="${MESH_SWEEP_FRACTIONS:-0.001 0.01 0.03 0.05 0.1}"
export MESH_BCSR_DIR="${MESH_BCSR_DIR:-$PROJECT_ROOT/weights/bcsr_global_16pe_fanout256_10k}"
if [ ! -d "$MESH_BCSR_DIR" ]; then
  echo "[step4-ram2] ERROR: missing weights dir: $MESH_BCSR_DIR"
  exit 2
fi
echo "[step4-ram2] sweep=fraction group=$GROUP_FRAC bcsr_dir=$MESH_BCSR_DIR fanout=$MESH_STEP_ACTIVATION_FANOUT fractions=($MESH_SWEEP_FRACTIONS)"
"$MATRIX_SH"
python3 "$SUMMARIZE_PY" --root "$OUTPUT_BASE/$GROUP_FRAC" --take-last "$MESH_SWEEP_REPEATS"

echo "[step4-ram2] DONE"

