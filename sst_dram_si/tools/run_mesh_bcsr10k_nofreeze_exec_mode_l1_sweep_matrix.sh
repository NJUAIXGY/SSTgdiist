#!/usr/bin/env bash
set -euo pipefail

# Matrix runner for 10k/PE + BCSR (fanout256_10k) "no-freeze (N1)" experiments.
#
# Defaults (override via env):
#   MESH_MAX_STEPS=4
#   MESH_STEP_ACTIVATION_FANOUT=256
#   MESH_STEP_ACTIVATION_SEED=271828
#   MESH_SWEEP_FRACTIONS="0.001 0.01 0.05 0.1"
#   MESH_SWEEP_REPEATS=2
#   MESH_SWEEP_L1="0 1"
#   MESH_SWEEP_MODES="gas naive_raw"
#
# N1/no-freeze defaults:
#   MESH_STEP_RESET_MEM_EACH_STEP=0
#   MESH_ALLOW_ZERO_FIRING_LONG=0
#
# Output root:
#   outputs_large/paper2/${MESH_BCSR10K_RUN_GROUP}/...

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export MESH_MAX_STEPS="${MESH_MAX_STEPS:-4}"
export MESH_STEP_ACTIVATION_FANOUT="${MESH_STEP_ACTIVATION_FANOUT:-256}"
export MESH_STEP_ACTIVATION_SEED="${MESH_STEP_ACTIVATION_SEED:-271828}"

export MESH_SWEEP_FRACTIONS="${MESH_SWEEP_FRACTIONS:-0.001 0.01 0.05 0.1}"
export MESH_SWEEP_REPEATS="${MESH_SWEEP_REPEATS:-2}"
export MESH_SWEEP_L1="${MESH_SWEEP_L1:-0 1}"
export MESH_SWEEP_MODES="${MESH_SWEEP_MODES:-gas naive_raw}"
export MESH_SWEEP_RETRY_MAX="${MESH_SWEEP_RETRY_MAX:-3}"

export MESH_VALIDATE_PROFILE="${MESH_VALIDATE_PROFILE:-paper}"
export MESH_QUIET="${MESH_QUIET:-1}"

# N1/no-freeze profile invariants (avoid cross-experiment stickiness).
export MESH_STEP_RESET_MEM_EACH_STEP="0"
export MESH_ALLOW_ZERO_FIRING_LONG="0"
# Paper step-limited semantics: disable within-step cascading for GAS so processed spikes == injected spikes.
export MESH_GAS_STEP_SEQ_GATE_ENABLE="${MESH_GAS_STEP_SEQ_GATE_ENABLE:-1}"
# Ensure read-only freeze cannot leak into nofreeze runs.
export MESH_FREEZE_READONLY="0"
unset MESH_READONLY_V_THRESH MESH_READONLY_TAU_MEM || true

echo "[mesh-bcsr10k-matrix] modes=$MESH_SWEEP_MODES"
echo "[mesh-bcsr10k-matrix] l1=$MESH_SWEEP_L1"
echo "[mesh-bcsr10k-matrix] fractions=$MESH_SWEEP_FRACTIONS"
echo "[mesh-bcsr10k-matrix] repeats=$MESH_SWEEP_REPEATS max_steps=$MESH_MAX_STEPS seed=$MESH_STEP_ACTIVATION_SEED fanout=$MESH_STEP_ACTIVATION_FANOUT"
echo "[mesh-bcsr10k-matrix] nofreeze(N1): step_reset_mem_each_step=$MESH_STEP_RESET_MEM_EACH_STEP allow_zero_firing_long=$MESH_ALLOW_ZERO_FIRING_LONG gas_step_seq_gate=$MESH_GAS_STEP_SEQ_GATE_ENABLE"

for mode in $MESH_SWEEP_MODES; do
  for l1 in $MESH_SWEEP_L1; do
    export MESH_L1_ENABLE="$l1"
    for frac in $MESH_SWEEP_FRACTIONS; do
      export MESH_STEP_ACTIVATION_FRACTION="$frac"
      # Skip already-completed cells (count successful runs by presence of essential_summary_mesh.json).
      FRACTION_TAG="$(printf "%s" "$frac" | sed -e 's/[.]/p/g' -e 's/[-]/m/g' -e 's/[+]/_/g' -e 's#[/ ]#_#g')"
      RUN_GROUP="${MESH_BCSR10K_RUN_GROUP:-dram_mesh_4x4_bcsr10k_nofreeze_exec_mode_l1_sweep}"
      RUN_ROOT="$PROJECT_ROOT/outputs_large/paper2/$RUN_GROUP/$mode/l1_${l1}/frac_${FRACTION_TAG}"
      done_count=0
      if [ -d "$RUN_ROOT" ]; then
        done_count="$(
          RUN_ROOT="$RUN_ROOT" PROJECT_ROOT="$PROJECT_ROOT" python3 - <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(os.environ.get("RUN_ROOT", ""))
project_root = Path(os.environ.get("PROJECT_ROOT", "") or ".").resolve()
validator = (project_root / "tools" / "validate_essential_summary_mesh.py").resolve()
max_steps = int(os.environ.get("MESH_MAX_STEPS", "0") or 0)
seed = int(os.environ.get("MESH_STEP_ACTIVATION_SEED", "0") or 0)
fanout = int(os.environ.get("MESH_STEP_ACTIVATION_FANOUT", "0") or 0)
profile = str(os.environ.get("MESH_VALIDATE_PROFILE", "paper") or "paper").strip() or "paper"
want_reset = os.environ.get("MESH_STEP_RESET_MEM_EACH_STEP", "").strip()
want_reset_i = None
if want_reset:
    want_reset_i = (
        1
        if want_reset.lower() in ("1", "true", "yes", "y", "on")
        else 0
        if want_reset.lower() in ("0", "false", "no", "n", "off")
        else None
    )

count = 0
for meta_path in sorted(root.glob("*/meta.json")):
    run_dir = meta_path.parent
    if not (run_dir / "essential_summary_mesh.json").exists():
        continue
    stats_csv = run_dir / "mesh_stats.csv"
    if not stats_csv.exists() or stats_csv.stat().st_size == 0:
        continue
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        continue
    model = meta.get("model") if isinstance(meta, dict) else None
    if not isinstance(model, dict):
        model = meta if isinstance(meta, dict) else {}
    if int(model.get("max_steps", 0) or 0) != max_steps:
        continue
    if int(model.get("step_activation_seed", 0) or 0) != seed:
        continue
    if int(model.get("step_activation_fanout", 0) or 0) != fanout:
        continue
    if want_reset_i is not None and int(model.get("step_reset_mem_each_step", 0) or 0) != want_reset_i:
        continue

    # Count only runs that pass the current validator (guards against stale validation logs).
    if validator.exists():
        proc = subprocess.run(
            [sys.executable, str(validator), "--run-dir", str(run_dir), "--profile", profile],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            continue
    else:
        # Fallback (should not happen in-repo): require validation.log summary fail=0.
        v = run_dir / "validation.log"
        if not v.exists():
            continue
        txt = v.read_text(encoding="utf-8", errors="replace")
        if "fail=0" not in txt:
            continue
    count += 1
print(count)
PY
        )" || done_count=0
      fi
      if [ "${done_count:-0}" -ge "$MESH_SWEEP_REPEATS" ]; then
        echo "[mesh-bcsr10k-matrix] skip: mode=$mode l1=$l1 frac=$frac (done=$done_count >= repeats=$MESH_SWEEP_REPEATS)"
        continue
      fi

      # Continue from already-finished count (validator-pass runs).
      success="${done_count:-0}"
      attempt=0
      attempt_max=$((MESH_SWEEP_REPEATS * MESH_SWEEP_RETRY_MAX))
      while [ "$success" -lt "$MESH_SWEEP_REPEATS" ] && [ "$attempt" -lt "$attempt_max" ]; do
        attempt=$((attempt + 1))
        echo "[mesh-bcsr10k-matrix] mode=$mode l1=$l1 frac=$frac pass=$((success + 1))/$MESH_SWEEP_REPEATS attempt=$attempt/$attempt_max"
        if "$SCRIPT_DIR/run_mesh_bcsr10k_nofreeze_exec_mode_l1_sweep_with_time.sh" "$mode"; then
          success=$((success + 1))
        else
          rc=$?
          echo "[mesh-bcsr10k-matrix] WARN: run failed (exit=$rc) attempt=$attempt/$attempt_max"
        fi
      done
      if [ "$success" -lt "$MESH_SWEEP_REPEATS" ]; then
        echo "[mesh-bcsr10k-matrix] ERROR: cell incomplete: mode=$mode l1=$l1 frac=$frac (pass=$success < repeats=$MESH_SWEEP_REPEATS)"
      fi
    done
  done
done
