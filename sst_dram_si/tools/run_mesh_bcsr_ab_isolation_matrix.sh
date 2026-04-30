#!/usr/bin/env bash
set -euo pipefail

# BCSR A/B strict-isolation matrix (GAS only).
#
# Variants:
# - baseline: flat dataset + full_block
# - A:        flat dataset + row_cacheline
# - B:        rowpack_v1 dataset + full_block
# - AB:       rowpack_v1 dataset + row_cacheline
#
# Output roots:
#   outputs_large/paper2/dram_mesh_4x4_ab_isolation_{baseline,A_row_cacheline,B_rowpack_v2,AB_rowpack_rowcacheline}
#
# Notes:
# - Keeps all non-target knobs identical.
# - Uses step-limited runs (default max_steps=1) for reproducibility.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUNNER="$PROJECT_ROOT/tools/run_mesh_with_time.sh"

if [ ! -x "$RUNNER" ]; then
  echo "[ab-isolation] ERROR: runner not found or not executable: $RUNNER" >&2
  exit 2
fi

FLAT_DATASET="${MESH_BCSR_DIR_FLAT:-$PROJECT_ROOT/weights/bcsr_global_16pe_fanout256_10k}"
ROWPACK_DATASET="${MESH_BCSR_DIR_ROWPACK:-$PROJECT_ROOT/weights/bcsr_global_16pe_fanout256_10k_rowpack_v1}"

if [ ! -d "$FLAT_DATASET" ]; then
  echo "[ab-isolation] ERROR: flat dataset missing: $FLAT_DATASET" >&2
  exit 2
fi
if [ ! -d "$ROWPACK_DATASET" ]; then
  echo "[ab-isolation] ERROR: rowpack dataset missing: $ROWPACK_DATASET" >&2
  exit 2
fi

inspect_dataset_shape() {
  local dataset_root="$1"
  local dataset_tag="$2"
  local meta_path="$dataset_root/pe00/core00.bcsr.bin.meta.json"
  if [ ! -f "$meta_path" ]; then
    echo "[ab-isolation] WARN: meta not found for $dataset_tag: $meta_path"
    return
  fi

  local br bc val_bytes
  read -r br bc val_bytes < <(
    python3 - "$meta_path" <<'PY'
import json
import sys

meta_path = sys.argv[1]
with open(meta_path, "r", encoding="utf-8") as f:
    d = json.load(f)

br = int(d.get("br", 0) or 0)
bc = int(d.get("bc", 0) or 0)
val_bytes = int(d.get("val_bytes", 4) or 4)
print(br, bc, val_bytes)
PY
  )

  if [ "${br:-0}" -le 0 ] || [ "${bc:-0}" -le 0 ] || [ "${val_bytes:-0}" -le 0 ]; then
    echo "[ab-isolation] WARN: invalid shape in $meta_path (br=$br bc=$bc val_bytes=$val_bytes)"
    return
  fi

  local block_bytes=$((br * bc * val_bytes))
  local row_slice_bytes=$((bc * val_bytes))
  echo "[ab-isolation] dataset[$dataset_tag] br=$br bc=$bc val_bytes=$val_bytes block_bytes=$block_bytes row_slice_bytes=$row_slice_bytes"
  if [ "$br" -eq 1 ]; then
    echo "[ab-isolation] NOTE: dataset[$dataset_tag] uses br=1, so full_block == row_cacheline by design (A may be no-op)."
  fi
}

MESH_MAX_STEPS="${MESH_MAX_STEPS:-1}"
MESH_STEP_ACTIVATION_FRACTION="${MESH_STEP_ACTIVATION_FRACTION:-0.01}"
MESH_STEP_ACTIVATION_SEED="${MESH_STEP_ACTIVATION_SEED:-314159}"
MESH_SST_NPROC="${MESH_SST_NPROC:-32}"
MESH_L1_ENABLE="${MESH_L1_ENABLE:-0}"
MESH_VALIDATE_PROFILE="${MESH_VALIDATE_PROFILE:-paper}"
MESH_QUIET="${MESH_QUIET:-1}"
REPEATS="${MESH_SWEEP_REPEATS:-1}"
# Low-load guard (A-path stabilization):
# when fraction is very low, row_cacheline may increase per-request overhead.
# Guard can switch row_cacheline -> full_block for A/AB runs at low load.
MESH_AB_ROW_CACHELINE_GUARD_ENABLE="${MESH_AB_ROW_CACHELINE_GUARD_ENABLE:-1}"
MESH_AB_ROW_CACHELINE_GUARD_FRAC_THRESHOLD="${MESH_AB_ROW_CACHELINE_GUARD_FRAC_THRESHOLD:-0.02}"

echo "[ab-isolation] flat=$FLAT_DATASET"
echo "[ab-isolation] rowpack=$ROWPACK_DATASET"
inspect_dataset_shape "$FLAT_DATASET" "flat"
inspect_dataset_shape "$ROWPACK_DATASET" "rowpack"
echo "[ab-isolation] max_steps=$MESH_MAX_STEPS frac=$MESH_STEP_ACTIVATION_FRACTION seed=$MESH_STEP_ACTIVATION_SEED nproc=$MESH_SST_NPROC repeats=$REPEATS"
echo "[ab-isolation] row_cacheline_guard_enable=$MESH_AB_ROW_CACHELINE_GUARD_ENABLE frac_threshold=$MESH_AB_ROW_CACHELINE_GUARD_FRAC_THRESHOLD"

float_le() {
  python3 - "$1" "$2" <<'PY'
import sys
a = float(sys.argv[1])
b = float(sys.argv[2])
sys.exit(0 if a <= b else 1)
PY
}

resolve_fetch_mode() {
  local requested="$1"
  local effective="$requested"
  if [ "$requested" = "row_cacheline" ] && [ "$MESH_AB_ROW_CACHELINE_GUARD_ENABLE" = "1" ]; then
    if float_le "$MESH_STEP_ACTIVATION_FRACTION" "$MESH_AB_ROW_CACHELINE_GUARD_FRAC_THRESHOLD"; then
      effective="full_block"
      echo "[ab-isolation] NOTE: low-load guard applied (frac=$MESH_STEP_ACTIVATION_FRACTION <= $MESH_AB_ROW_CACHELINE_GUARD_FRAC_THRESHOLD): row_cacheline -> full_block" >&2
    fi
  fi
  echo "$effective"
}

run_one() {
  local tag="$1"
  local dataset="$2"
  local fetch_mode_requested="$3"
  local layout_tag="$4"
  local fetch_mode
  fetch_mode="$(resolve_fetch_mode "$fetch_mode_requested")"
  local run_root="$PROJECT_ROOT/outputs_large/paper2/$tag"
  mkdir -p "$run_root"

  echo "[ab-isolation] run tag=$tag dataset=$(basename "$dataset") fetch_req=$fetch_mode_requested fetch_eff=$fetch_mode layout_tag=$layout_tag"
  MESH_RUN_ROOT="$run_root" \
  MESH_EXEC_MODE="gas" \
  MESH_MAX_STEPS="$MESH_MAX_STEPS" \
  MESH_STEP_ACTIVATION_FRACTION="$MESH_STEP_ACTIVATION_FRACTION" \
  MESH_STEP_ACTIVATION_SEED="$MESH_STEP_ACTIVATION_SEED" \
  MESH_STEP_RESET_MEM_EACH_STEP="1" \
  MESH_ALLOW_ZERO_FIRING_LONG="1" \
  MESH_GAS_STEP_SEQ_GATE_ENABLE="1" \
  MESH_BCSR_DIR="$dataset" \
  MESH_BCSR_BLOCK_FETCH_MODE="$fetch_mode" \
  MESH_AB_EFFECTIVE_FETCH_MODE="$fetch_mode" \
  MESH_BCSR_LAYOUT_MODE="$layout_tag" \
  MESH_L1_ENABLE="$MESH_L1_ENABLE" \
  MESH_SST_NPROC="$MESH_SST_NPROC" \
  MESH_VALIDATE_PROFILE="$MESH_VALIDATE_PROFILE" \
  MESH_QUIET="$MESH_QUIET" \
  "$RUNNER"
}

for r in $(seq 1 "$REPEATS"); do
  echo "[ab-isolation] repeat $r/$REPEATS"
  run_one "dram_mesh_4x4_ab_isolation_baseline" "$FLAT_DATASET" "full_block" "flat"
  run_one "dram_mesh_4x4_ab_isolation_A_row_cacheline" "$FLAT_DATASET" "row_cacheline" "flat"
  run_one "dram_mesh_4x4_ab_isolation_B_rowpack_v2" "$ROWPACK_DATASET" "full_block" "rowpack_v1"
  run_one "dram_mesh_4x4_ab_isolation_AB_rowpack_rowcacheline" "$ROWPACK_DATASET" "row_cacheline" "rowpack_v1"
done

python3 "$PROJECT_ROOT/tools/gate_ab_isolation_matrix.py" \
  --baseline-root "$PROJECT_ROOT/outputs_large/paper2/dram_mesh_4x4_ab_isolation_baseline" \
  --a-root "$PROJECT_ROOT/outputs_large/paper2/dram_mesh_4x4_ab_isolation_A_row_cacheline" \
  --b-root "$PROJECT_ROOT/outputs_large/paper2/dram_mesh_4x4_ab_isolation_B_rowpack_v2" \
  --ab-root "$PROJECT_ROOT/outputs_large/paper2/dram_mesh_4x4_ab_isolation_AB_rowpack_rowcacheline" \
  --fired-pass-rel-tol "${MESH_AB_GATE_FIRED_PASS_REL_TOL:-${MESH_AB_GATE_FIRED_REL_TOL:-0.001}}" \
  --fired-warn-rel-tol "${MESH_AB_GATE_FIRED_WARN_REL_TOL:-0.01}"

echo "[ab-isolation] done."
