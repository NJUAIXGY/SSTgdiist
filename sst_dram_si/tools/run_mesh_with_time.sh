#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
用法:
  run_mesh_with_time.sh [--spec <spec.json>]

选项:
  --spec <spec.json>   启用 spec-first（会导出 MESH_SPEC_JSON）；stop/max_steps 由 spec 决定
  -h, --help           显示帮助
EOF
}

to_lower() {
  echo "$1" | tr '[:upper:]' '[:lower:]'
}

is_truthy() {
  case "$(to_lower "${1:-}")" in
    1|true|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

normalize_synapse_mode() {
  local mode
  mode="$(to_lower "${1:-}")"
  case "$mode" in
    gscc_valueonly_dstcore) mode="gcss_valueonly_dstcore" ;;
    gscc_valueonly_dstcore_vlf_premphf) mode="gcss_valueonly_dstcore_vlf_premphf" ;;
    gscc_valueonly_dstcore_vlf_premphf_plp) mode="gcss_valueonly_dstcore_vlf_premphf_plp" ;;
  esac
  echo "$mode"
}

requires_gcss_mode() {
  [ -n "${MESH_EXPERIMENTAL_GCSS_VLF_QUEUE_POLICY:-}" ] \
    || [ -n "${MESH_EXPERIMENTAL_GCSS_VLF_FAIR_BAND_SIZE:-}" ] \
    || [ -n "${MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_ENABLE:-}" ] \
    || [ -n "${MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT:-}" ] \
    || [ -n "${MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES:-}" ] \
    || [ -n "${MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD:-}" ] \
    || [ -n "${MESH_GCSSPLP_DIR:-}" ] \
    || [ -n "${MESH_GCSSVLF_DIR:-}" ] \
    || [ -n "${MESH_GCSS2_DIR:-}" ] \
    || [ -n "${MESH_GCSS_DIR:-}" ] \
    || [ -n "${MESH_EXPERIMENTAL_GCSS_PHASE_BREAKDOWN_ENABLE:-}" ]
}

default_library_freshness_markers_csv() {
  cat <<'EOF'
atlas_enable_state_local_storage_effective_total,atlas_control_runtime_all_zero_total,atlas_control_runtime_state_fabric_absent_total,atlas_control_runtime_state_fabric_present_idle_total,atlas_control_runtime_state_produced_without_queue_total,atlas_control_runtime_state_queued_without_consume_total,atlas_control_runtime_state_consumed_active_total
EOF
}

resolve_sndl_library_for_freshness() {
  local explicit_path
  explicit_path="${MESH_LIBRARY_FRESHNESS_LIB:-}"
  if [ -n "$explicit_path" ]; then
    echo "$explicit_path"
    return 0
  fi
  if [ -z "${SST_ADD_LIB_PATH:-}" ]; then
    return 1
  fi
  local candidate
  IFS=':' read -r -a _mesh_lib_dirs <<< "$SST_ADD_LIB_PATH"
  for candidate in "${_mesh_lib_dirs[@]}"; do
    if [ -f "$candidate/libSnnDL.so" ]; then
      echo "$candidate/libSnnDL.so"
      return 0
    fi
  done
  return 1
}

preflight_assert_library_freshness() {
  if is_truthy "${MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT:-}"; then
    echo "[mesh] skip library freshness preflight: MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT=${MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT}"
    return 0
  fi
  local sndl_lib markers_csv
  if ! sndl_lib="$(resolve_sndl_library_for_freshness)"; then
    echo "[mesh] error: library freshness preflight could not locate libSnnDL.so from SST_ADD_LIB_PATH; set MESH_LIBRARY_FRESHNESS_LIB or MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT=1." >&2
    exit 2
  fi
  if [ ! -f "$sndl_lib" ]; then
    echo "[mesh] error: library freshness preflight target does not exist: $sndl_lib" >&2
    exit 2
  fi
  markers_csv="${MESH_LIBRARY_FRESHNESS_REQUIRED_MARKERS:-$(default_library_freshness_markers_csv)}"
  python3 - "$sndl_lib" "$markers_csv" <<'PY'
from pathlib import Path
import sys

lib_path = Path(sys.argv[1])
markers = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
blob = lib_path.read_bytes()
missing = [marker for marker in markers if marker.encode("utf-8") not in blob]
if missing:
    print(
        f"[mesh] error: library freshness preflight failed for {lib_path}; missing markers: {', '.join(missing)}",
        file=sys.stderr,
    )
    raise SystemExit(2)
print(f"[mesh] library freshness OK: {lib_path}")
PY
}

preflight_assert_mode() {
  local syn_mode
  syn_mode="$(normalize_synapse_mode "${MESH_SYNAPSE_WEIGHT_MODE:-}")"
  if requires_gcss_mode; then
    if [ -z "$syn_mode" ]; then
      echo "[mesh] error: GCSS-related env detected but MESH_SYNAPSE_WEIGHT_MODE is empty; refusing to run to avoid accidental bcsr_gas fallback." >&2
      exit 2
    fi
    if [[ "$syn_mode" != gcss* ]]; then
      echo "[mesh] error: GCSS-related env detected but MESH_SYNAPSE_WEIGHT_MODE=$syn_mode is not a GCSS mode." >&2
      exit 2
    fi
  fi

  if [ "$syn_mode" = "gcss_valueonly_dstcore_vlf_premphf_plp" ] && [ -z "${MESH_GCSSPLP_DIR:-}" ]; then
    echo "[mesh] error: synapse mode is gcss_valueonly_dstcore_vlf_premphf_plp but MESH_GCSSPLP_DIR is empty." >&2
    exit 2
  fi

  if [[ "$syn_mode" == "gcss_valueonly_dstcore_idx2" || "$syn_mode" == "gcss_idx2_rowmphf" || "$syn_mode" == "gcss_valueonly_dstcore_vlf_premphf" || "$syn_mode" == "gcss_valueonly_dstcore_vlf_premphf_plp" ]]; then
    if ! is_truthy "${MESH_EXPERIMENTAL_ENABLE:-}"; then
      echo "[mesh] error: MESH_SYNAPSE_WEIGHT_MODE=$syn_mode requires MESH_EXPERIMENTAL_ENABLE=1." >&2
      exit 2
    fi
  fi
}

postflight_assert_effective_mode() {
  local expected_mode effective_cfg mode_actual
  expected_mode="$(normalize_synapse_mode "${MESH_ASSERT_SYNAPSE_WEIGHT_MODE:-${MESH_SYNAPSE_WEIGHT_MODE:-}}")"
  if [ -z "$expected_mode" ]; then
    return 0
  fi
  effective_cfg="$RUN_DIR/effective_config.json"
  if [ ! -f "$effective_cfg" ]; then
    echo "[mesh] error: expected effective config not found for mode assertion: $effective_cfg" >&2
    exit 2
  fi
  mode_actual="$(
    python3 - "$effective_cfg" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    cfg = json.load(f)
mode = str(cfg.get("synapse_weight_mode", "") or "").strip().lower()
aliases = {
    "gscc_valueonly_dstcore": "gcss_valueonly_dstcore",
    "gscc_valueonly_dstcore_vlf_premphf": "gcss_valueonly_dstcore_vlf_premphf",
    "gscc_valueonly_dstcore_vlf_premphf_plp": "gcss_valueonly_dstcore_vlf_premphf_plp",
}
print(aliases.get(mode, mode))
PY
  )"
  if [ "$mode_actual" != "$expected_mode" ]; then
    echo "[mesh] error: synapse mode drift detected, expected=$expected_mode actual=$mode_actual (effective_config)." >&2
    exit 2
  fi
  echo "[mesh] assert synapse mode OK: $mode_actual"
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
SPEC_FIRST=0
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
RUN_ROOT="$PROJECT_ROOT/outputs_large/paper2/dram_mesh_4x4"
if [ -n "${MESH_RUN_ROOT:-}" ]; then
  RUN_ROOT="$MESH_RUN_ROOT"
fi
mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$RUN_ROOT/$TS"
mkdir -p "$RUN_DIR"
export MESH_RUN_DIR="$RUN_DIR"

if [ -n "$SPEC_JSON" ]; then
  SPEC_FIRST=1
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

preflight_assert_mode

SST_BIN_USER="${SST_BIN:-}"
SST_ADD_LIB_PATH="${SST_ADD_LIB_PATH:-}"
MESH_DEFAULT_NPROC=32
if [ -n "$SST_BIN_USER" ]; then
  SST_BIN="$SST_BIN_USER"
else
  SST_BIN_MPI="$REPO_ROOT/sst_install_mpi/bin/sst"
  SST_BIN_PAR="$REPO_ROOT/sst_install/bin/sst"
  SST_BIN_SER="$REPO_ROOT/sst_install_serial/bin/sst"
  # Require a working parallel SST binary; never silently fall back to serial.
  if [ -x "$SST_BIN_MPI" ] && "$SST_BIN_MPI" --version >/dev/null 2>&1; then
    SST_BIN="$SST_BIN_MPI"
    MESH_DEFAULT_NPROC=32
  elif [ -x "$SST_BIN_PAR" ] && "$SST_BIN_PAR" --version >/dev/null 2>&1; then
    SST_BIN="$SST_BIN_PAR"
    MESH_DEFAULT_NPROC=32
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
MODEL="$PROJECT_ROOT/test_mesh_4x4.py"
LOG="$RUN_DIR/mesh_run.log"
TIME_FILE="$RUN_DIR/time.txt"
META_FILE="$RUN_DIR/meta.json"

# Default add-lib-path for mesh_template (dev workflow: load in-tree built element libs).
if [ -z "$SST_ADD_LIB_PATH" ]; then
  _DEFAULT_LIBS=()
  for p in \
    "$REPO_ROOT/sst_workspace/sst-elements/src/sst/elements/SnnDL/.libs" \
    "$REPO_ROOT/sst_workspace/sst-elements/src/sst/elements/merlin/.libs" \
    "$REPO_ROOT/sst_workspace/sst-elements/src/sst/elements/memHierarchy/.libs"
  do
    if [ -d "$p" ]; then
      _DEFAULT_LIBS+=("$p")
    fi
  done
  if [ "${#_DEFAULT_LIBS[@]}" -gt 0 ]; then
    SST_ADD_LIB_PATH="$(IFS=:; echo "${_DEFAULT_LIBS[*]}")"
  fi
fi
preflight_assert_library_freshness

# memHierarchy depends on ramulator; auto-add if present (dev workflow).
RAMULATOR_LIB_DIR="$REPO_ROOT/externals/ramulator2"
if [ -f "$RAMULATOR_LIB_DIR/libramulator.so" ]; then
  if [ -n "${LD_LIBRARY_PATH:-}" ]; then
    export LD_LIBRARY_PATH="$RAMULATOR_LIB_DIR:$LD_LIBRARY_PATH"
  else
    export LD_LIBRARY_PATH="$RAMULATOR_LIB_DIR"
  fi
fi

SST_ARGS=()
if [ -n "$SST_ADD_LIB_PATH" ]; then
  IFS=':' read -r -a _SST_LIBS <<< "$SST_ADD_LIB_PATH"
  for p in "${_SST_LIBS[@]}"; do
    if [ -n "$p" ]; then
      SST_ARGS+=(--add-lib-path "$p")
    fi
  done
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
postflight_assert_effective_mode
maybe_run_thermal_export

# === 标准验收：单次 run 的口径一致性/算术约束（默认不做 baseline 对比） ===
# 说明：validate 脚本会根据 summary 内的 sim_time 自动决定是否强制要求 100us 非零发放。
VALIDATION_LOG="$RUN_DIR/validation.log"
if [ "$SPEC_FIRST" -eq 1 ]; then
  PROFILE="${MESH_VALIDATE_PROFILE:-dev}"
else
  PROFILE="${MESH_VALIDATE_PROFILE:-paper}"
fi
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
# 用法示例：
#   export MESH_VALIDATE_BASELINE_DIR="/path/to/baseline_run_dir"
#   export MESH_VALIDATE_ABS_TOL="40"
#   export MESH_VALIDATE_REL_TOL="0.01"
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
echo "[mesh] artifacts:"
echo "  - $LOG"
echo "  - $TIME_FILE"
echo "  - $META_FILE"
echo "  - $RUN_DIR/effective_config.json"
echo "  - $RUN_DIR/essential_summary_mesh.json"
echo "  - $RUN_DIR/atlas_activation_trace.json"
echo "  - $VALIDATION_LOG"
