#!/usr/bin/env bash
set -euo pipefail

# 10k/PE + BCSR (fanout256_10k) experiment runner with:
# - exec_mode sweep (gas vs naive_raw)
# - L1 on/off sweep (via MESH_L1_ENABLE env override)
# - step_activation_fraction sweep (via MESH_STEP_ACTIVATION_FRACTION env override)
# - step-limited termination (MESH_MAX_STEPS)
#
# Output root (grouped):
#   sst_dram_si/outputs_large/paper2/<group>/<mode>/l1_<0|1>/frac_<tag>/<timestamp>/
#
# This script is "paper-grade": it writes meta.json(schema=1), essential_summary_mesh.json, and validation.log.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE_RAW="${1:-${MESH_EXEC_MODE:-gas}}"
MODE="$(printf "%s" "$MODE_RAW" | tr '[:upper:]' '[:lower:]')"
case "$MODE" in
  gas|naive_raw) ;;
  *)
    echo "[mesh-bcsr10k] invalid exec mode: ${MODE_RAW}"
    echo "usage: $0 [gas|naive_raw]"
    exit 2
    ;;
esac

# Required sweep knobs (can be provided as env).
FRACTION="${MESH_STEP_ACTIVATION_FRACTION:-}"
if [ -z "$FRACTION" ]; then
  echo "[mesh-bcsr10k] missing MESH_STEP_ACTIVATION_FRACTION (e.g. 0.001)"
  exit 2
fi

L1_RAW="${MESH_L1_ENABLE:-}"
if [ -z "$L1_RAW" ]; then
  echo "[mesh-bcsr10k] missing MESH_L1_ENABLE (0/1)"
  exit 2
fi
L1="$(printf "%s" "$L1_RAW" | tr '[:upper:]' '[:lower:]')"
case "$L1" in
  0|1|true|false|yes|no|on|off) ;;
  *)
    echo "[mesh-bcsr10k] invalid MESH_L1_ENABLE=$L1_RAW (expected 0/1/true/false)"
    exit 2
    ;;
esac

# Normalize L1 tag to 0/1 for directory naming.
L1_TAG="0"
if [ "$L1" = "1" ] || [ "$L1" = "true" ] || [ "$L1" = "yes" ] || [ "$L1" = "on" ]; then
  L1_TAG="1"
fi

# Group output directory under paper2.
RUN_GROUP="${MESH_BCSR10K_RUN_GROUP:-dram_mesh_4x4_bcsr10k_freeze_exec_mode_l1_sweep}"
RUN_ROOT="$PROJECT_ROOT/outputs_large/paper2/$RUN_GROUP/$MODE/l1_${L1_TAG}"
mkdir -p "$RUN_ROOT"

# Add fraction tag for easy browsing; still record exact value in meta.json.
FRACTION_TAG="$(printf "%s" "$FRACTION" | sed -e 's/[.]/p/g' -e 's/[-]/m/g' -e 's/[+]/_/g' -e 's#[/ ]#_#g')"
RUN_ROOT="$RUN_ROOT/frac_${FRACTION_TAG}"
mkdir -p "$RUN_ROOT"

TS="$(date +%Y%m%d-%H%M%S-%N)"
RUN_DIR="$RUN_ROOT/$TS"
mkdir -p "$RUN_DIR"

export MESH_RUN_DIR="$RUN_DIR"
export MESH_EXEC_MODE="$MODE"
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-4}"

# Force 10k BCSR dataset unless user overrides explicitly.
export MESH_BCSR_DIR="${MESH_BCSR_DIR:-$PROJECT_ROOT/weights/bcsr_global_16pe_fanout256_10k}"

# Quiet mode by default for paper-grade matrix runs (reduces log IO noise).
export MESH_QUIET="${MESH_QUIET:-1}"

# Freeze-dynamics acceptance: allow neurons_fired_total==0 for long runs (validator gate).
# NOTE: Set unconditionally to avoid "profile stickiness" from caller shells.
export MESH_ALLOW_ZERO_FIRING_LONG="1"
# Freeze: do NOT accumulate membrane across steps (N1 对照的 freeze 口径)
export MESH_STEP_RESET_MEM_EACH_STEP="1"
# Fairness: disable within-step cascading in GAS for step-limited comparisons.
export MESH_GAS_STEP_SEQ_GATE_ENABLE="${MESH_GAS_STEP_SEQ_GATE_ENABLE:-1}"
# Provenance-only (StepActivationSubsystem 当前不使用该权重字段；保留以对齐实验口径)
export MESH_STEP_ACTIVATION_EVENT_WEIGHT="0.0"

# If the caller enables exploratory knobs (MESH_EXPERIMENTAL_ENABLE=1) while running GAS,
# force staging/defer so Apply-side experimental paths execute.
if [ "$MODE" = "gas" ]; then
  _exp_raw="${MESH_EXPERIMENTAL_ENABLE:-0}"
  _exp="$(printf "%s" "$_exp_raw" | tr '[:upper:]' '[:lower:]')"
  case "$_exp" in
    1|true|yes|y|on)
      export MESH_GAS_FORCE_DEFER="${MESH_GAS_FORCE_DEFER:-1}"
      ;;
  esac
fi

SST_PREFIX_DEFAULT="$PROJECT_ROOT/../sst_install_mpi"
# Prefer an explicit prefix/bin from the caller, but default to the repo-local MPI install
# (our non-MPI prefix may be absent or built against an incompatible glibc on some hosts).
export SST_INSTALL_PREFIX="${SST_INSTALL_PREFIX:-$SST_PREFIX_DEFAULT}"
SST_BIN="${MESH_SST_BIN:-$SST_INSTALL_PREFIX/bin/sst}"
# Ensure the chosen SST binary is runnable; fall back to the known-good MPI install.
if ! "$SST_BIN" --version >/dev/null 2>&1; then
  SST_INSTALL_PREFIX="$SST_PREFIX_DEFAULT"
  SST_BIN="$SST_INSTALL_PREFIX/bin/sst"
fi
# Hard fail if we still cannot run SST; otherwise later runs will silently produce empty dirs.
if ! "$SST_BIN" --version >/dev/null 2>&1; then
  echo "[mesh-bcsr10k] ERROR: SST binary not runnable. Tried: ${MESH_SST_BIN:-$SST_INSTALL_PREFIX/bin/sst} and fallback: $SST_BIN"
  exit 2
fi

# Isolate the runtime environment from stale shell exports (e.g. LD_LIBRARY_PATH pointing at a broken prefix).
export PATH="$SST_INSTALL_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$SST_INSTALL_PREFIX/lib:$SST_INSTALL_PREFIX/lib64:${LD_LIBRARY_PATH:-}"
MODEL="$PROJECT_ROOT/test_mesh_4x4.py"
LOG="$RUN_DIR/mesh_run.log"
TIME_FILE="$RUN_DIR/time.txt"

# Always record the SST exit code, even if the run fails mid-simulation.
# This prevents silent matrix aborts with half-created directories.
SST_EXIT_CODE=0
SST_NPROC="${MESH_SST_NPROC:-32}"
( cd "$PROJECT_ROOT" && /usr/bin/time -v -o "$TIME_FILE" "$SST_BIN" -n "$SST_NPROC" "$MODEL" ) > "$LOG" 2>&1 || SST_EXIT_CODE=$?
# GNU time: killed-by-signal may not propagate a conventional exit status; treat it as failure.
if [ -f "$TIME_FILE" ] && grep -q "Command terminated by signal" "$TIME_FILE"; then
  sig="$(sed -n 's/^Command terminated by signal \([0-9][0-9]*\).*$/\1/p' "$TIME_FILE" | head -n 1)"
  if [ -n "$sig" ]; then
    SST_EXIT_CODE=$((128 + sig))
  else
    SST_EXIT_CODE=1
  fi
fi
echo "$SST_EXIT_CODE" > "$RUN_DIR/sst_exit_code.txt"

if [ "$SST_EXIT_CODE" -ne 0 ]; then
  echo "[mesh-bcsr10k] ERROR: sst failed (exit=$SST_EXIT_CODE). See: $LOG" | tee -a "$LOG"
  # Keep partial artifacts for post-mortem; caller may choose to retry.
  exit "$SST_EXIT_CODE"
fi

# Hard gate: a "successful" run must produce non-empty mesh_stats.csv.
# Otherwise the matrix may incorrectly count an empty run as completed.
if [ ! -s "$RUN_DIR/mesh_stats.csv" ]; then
  echo "[mesh-bcsr10k] ERROR: mesh_stats.csv missing/empty; marking run as failed. See: $LOG" | tee -a "$LOG"
  exit 3
fi

# Provenance-rich meta (schema_version=1) + archive inputs.
python3 "$PROJECT_ROOT/tools/write_mesh_meta.py" \
  --run-dir "$RUN_DIR" \
  --project-root "$PROJECT_ROOT" \
  --sst-bin "$SST_BIN" \
  --model "$MODEL" \
  --sst-nproc "$SST_NPROC" > "$RUN_DIR/meta.json.log" 2>&1

python3 "$PROJECT_ROOT/tools/compute_essential_summary_mesh.py" --run-dir "$RUN_DIR"

# Standard validation (paper-grade by default).
VALIDATION_LOG="$RUN_DIR/validation.log"
PROFILE="${MESH_VALIDATE_PROFILE:-paper}"
MAX_MISS_ABS="${MESH_VALIDATE_MAX_ROUTE_MISS_ABS:-0}"
MAX_MISS_FRAC="${MESH_VALIDATE_MAX_ROUTE_MISS_FRAC:-0}"
MAX_DROP_ABS="${MESH_VALIDATE_MAX_LOCAL_DROP_ABS:-1}"
MAX_DROP_FRAC="${MESH_VALIDATE_MAX_LOCAL_DROP_FRAC:-1e-6}"
if [ "${MESH_QUIET:-0}" = "1" ] || [ "${MESH_QUIET:-0}" = "true" ] || [ "${MESH_QUIET:-0}" = "yes" ] || [ "${MESH_QUIET:-0}" = "on" ]; then
  python3 "$PROJECT_ROOT/tools/validate_essential_summary_mesh.py" \
    --run-dir "$RUN_DIR" \
    --profile "$PROFILE" \
    --max-route-miss-abs "$MAX_MISS_ABS" \
    --max-route-miss-frac "$MAX_MISS_FRAC" \
    --max-local-drop-abs "$MAX_DROP_ABS" \
    --max-local-drop-frac "$MAX_DROP_FRAC" > "$VALIDATION_LOG"
  # Print only the one-line summary to keep matrix runs quiet and reduce IO overhead.
  tail -n 1 "$VALIDATION_LOG" || true
else
  python3 "$PROJECT_ROOT/tools/validate_essential_summary_mesh.py" \
    --run-dir "$RUN_DIR" \
    --profile "$PROFILE" \
    --max-route-miss-abs "$MAX_MISS_ABS" \
    --max-route-miss-frac "$MAX_MISS_FRAC" \
    --max-local-drop-abs "$MAX_DROP_ABS" \
    --max-local-drop-frac "$MAX_DROP_FRAC" | tee "$VALIDATION_LOG"
fi

echo "[mesh-bcsr10k] run complete: $RUN_DIR"
