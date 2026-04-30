#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
用法:
  run_mesh_with_time_ram2.sh [--spec <spec.json>]

选项:
  --spec <spec.json>   启用 spec-first（会导出 MESH_SPEC_JSON）；stop/max_steps 由 spec 决定
  -h, --help           显示帮助
EOF
}

maybe_run_thermal_export() {
  local effective_cfg thermal_enable
  effective_cfg="$RUN_DIR/effective_config.json"
  if [ ! -f "$effective_cfg" ]; then
    return 0
  fi
  thermal_enable="$(
    python3 - "$effective_cfg" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        cfg = json.load(f)
    thermal = cfg.get("thermal") if isinstance(cfg, dict) else None
    enable = int((thermal or {}).get("enable", 0) or 0)
    print(1 if enable != 0 else 0)
except Exception:
    print(0)
PY
  )"
  if [ "$thermal_enable" != "1" ]; then
    return 0
  fi
  echo "[mesh] thermal export enabled: $RUN_DIR"
  if ! python3 "$PROJECT_ROOT/tools/thermal_export.py" --run-dir "$RUN_DIR"; then
    echo "[mesh] WARN: thermal export failed; continuing main run validation." >&2
  fi
}

SPEC_JSON=""
while [ $# -gt 0 ]; do
  case "$1" in
    --spec)
      SPEC_JSON="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[mesh] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(cd "$PROJECT_ROOT/.." && pwd)
source "$SCRIPT_DIR/mesh_library_freshness_preflight.sh"
RUN_ROOT="$PROJECT_ROOT/outputs_large/paper2/dram_mesh_4x4_ram2"
mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$RUN_ROOT/$TS"
mkdir -p "$RUN_DIR"
export MESH_RUN_DIR="$RUN_DIR"

if [ -n "$SPEC_JSON" ]; then
  SPEC_ABS=$(
    python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$SPEC_JSON"
  )
  if [ ! -f "$SPEC_ABS" ]; then
    echo "[mesh] spec not found: $SPEC_ABS" >&2
    exit 2
  fi
  export MESH_SPEC_JSON="$SPEC_ABS"
  echo "[mesh] spec-first enabled: MESH_SPEC_JSON=$MESH_SPEC_JSON"
else
  # 论文/回归默认采用 step-limited：由 GlobalGasStepController(max_steps) 结束仿真（不使用 stop-at）。
  export MESH_MAX_STEPS="${MESH_MAX_STEPS:-2}"
fi

SST_BIN_USER="${SST_BIN:-}"
MESH_DEFAULT_NPROC=32
if [ -n "$SST_BIN_USER" ]; then
  SST_BIN="$SST_BIN_USER"
else
  SST_BIN_MPI="$REPO_ROOT/sst_install_mpi/bin/sst"
  SST_BIN_PAR="$REPO_ROOT/sst_install/bin/sst"
  SST_BIN_SER="$REPO_ROOT/sst_install_serial/bin/sst"
  if [ -x "$SST_BIN_MPI" ] && "$SST_BIN_MPI" --version >/dev/null 2>&1; then
    SST_BIN="$SST_BIN_MPI"
  elif [ -x "$SST_BIN_PAR" ] && "$SST_BIN_PAR" --version >/dev/null 2>&1; then
    SST_BIN="$SST_BIN_PAR"
  elif [ -x "$SST_BIN_PAR" ]; then
    echo "[mesh] error: parallel SST exists but is not runnable in the current environment; refusing to fall back to serial: $SST_BIN_PAR" >&2
    exit 2
  elif [ -x "$SST_BIN_MPI" ]; then
    echo "[mesh] error: MPI SST exists but is not runnable in the current environment; refusing to fall back to serial: $SST_BIN_MPI" >&2
    exit 2
  elif [ -x "$SST_BIN_SER" ]; then
    echo "[mesh] error: only serial SST is available; refusing to fall back from parallel to serial: $SST_BIN_SER" >&2
    exit 2
  else
    echo "[mesh] error: no working parallel SST binary found (checked MPI and parallel installs); refusing to run." >&2
    exit 2
  fi
fi
SST_NPROC="${MESH_SST_NPROC:-$MESH_DEFAULT_NPROC}"
MODEL="$PROJECT_ROOT/test_mesh_4x4_ram2.py"
LOG="$RUN_DIR/mesh_run.log"
TIME_FILE="$RUN_DIR/time.txt"
META_FILE="$RUN_DIR/meta.json"
SST_ADD_LIB_PATH="${SST_ADD_LIB_PATH:-}"
mesh_populate_default_sst_add_lib_path
mesh_preflight_assert_library_freshness
SST_ARGS=()
if [ -n "$SST_ADD_LIB_PATH" ]; then
  IFS=':' read -r -a _SST_LIBS <<< "$SST_ADD_LIB_PATH"
  for p in "${_SST_LIBS[@]}"; do
    if [ -n "$p" ]; then
      SST_ARGS+=(--add-lib-path "$p")
    fi
  done
fi

# memHierarchy depends on ramulator; auto-add if present (dev workflow).
RAMULATOR_LIB_DIR="$REPO_ROOT/externals/ramulator2"
if [ -f "$RAMULATOR_LIB_DIR/libramulator.so" ]; then
  if [ -n "${LD_LIBRARY_PATH:-}" ]; then
    export LD_LIBRARY_PATH="$RAMULATOR_LIB_DIR:$LD_LIBRARY_PATH"
  else
    export LD_LIBRARY_PATH="$RAMULATOR_LIB_DIR"
  fi
fi

( cd "$PROJECT_ROOT" && /usr/bin/time -v -o "$TIME_FILE" "$SST_BIN" "${SST_ARGS[@]}" -n "$SST_NPROC" "$MODEL" ) > "$LOG" 2>&1
python3 "$PROJECT_ROOT/tools/write_mesh_meta.py" \
  --run-dir "$RUN_DIR" \
  --project-root "$PROJECT_ROOT" \
  --sst-bin "$SST_BIN" \
  --model "$MODEL" \
  --sst-nproc "$SST_NPROC" > "$META_FILE.log" 2>&1
python3 "$PROJECT_ROOT/tools/compute_essential_summary_mesh.py" --run-dir "$RUN_DIR"
python3 "$PROJECT_ROOT/tools/summarize_atlas_activation_trace.py" --run-dir "$RUN_DIR"
maybe_run_thermal_export

# === 标准验收：单次 run 的口径一致性/算术约束（默认不做 baseline 对比） ===
VALIDATION_LOG="$RUN_DIR/validation.log"
PROFILE="${MESH_VALIDATE_PROFILE:-paper}"
MAX_MISS_ABS="${MESH_VALIDATE_MAX_ROUTE_MISS_ABS:-0}"
MAX_MISS_FRAC="${MESH_VALIDATE_MAX_ROUTE_MISS_FRAC:-0}"
MAX_DROP_ABS="${MESH_VALIDATE_MAX_LOCAL_DROP_ABS:-1}"
MAX_DROP_FRAC="${MESH_VALIDATE_MAX_LOCAL_DROP_FRAC:-1e-6}"
python3 "$PROJECT_ROOT/tools/validate_essential_summary_mesh.py" \
  --run-dir "$RUN_DIR" \
  --profile "$PROFILE" \
  --max-route-miss-abs "$MAX_MISS_ABS" \
  --max-route-miss-frac "$MAX_MISS_FRAC" \
  --max-local-drop-abs "$MAX_DROP_ABS" \
  --max-local-drop-frac "$MAX_DROP_FRAC" | tee "$VALIDATION_LOG"

# 可选：对比稳定基线（允许轻微漂移）。
if [ -n "${MESH_VALIDATE_BASELINE_DIR:-}" ]; then
  ABS_TOL="${MESH_VALIDATE_ABS_TOL:-40}"
  REL_TOL="${MESH_VALIDATE_REL_TOL:-0.01}"
  python3 "$PROJECT_ROOT/tools/validate_essential_summary_mesh.py" \
    --run-dir "$RUN_DIR" \
    --baseline "$MESH_VALIDATE_BASELINE_DIR" \
    --profile "$PROFILE" \
    --max-route-miss-abs "$MAX_MISS_ABS" \
    --max-route-miss-frac "$MAX_MISS_FRAC" \
    --max-local-drop-abs "$MAX_DROP_ABS" \
    --max-local-drop-frac "$MAX_DROP_FRAC" \
    --abs-tol "$ABS_TOL" \
    --rel-tol "$REL_TOL" | tee -a "$VALIDATION_LOG"
fi
echo "[mesh] run complete: $RUN_DIR"
