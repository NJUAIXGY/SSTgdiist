#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
export PROJECT_ROOT
source "$SCRIPT_DIR/mesh_library_freshness_preflight.sh"
source "$SCRIPT_DIR/mesh_compare_runner_overlay.sh"

MODE_RAW="${1:-${MESH_EXEC_MODE:-gas}}"
MODE="$(printf "%s" "$MODE_RAW" | tr '[:upper:]' '[:lower:]')"
REQUESTED_MODE="$MODE"

# NOTE:
# BCSR optimizations (cache/prefetch/populate + inflight coalescing) are now globally disabled in SnnDL,
# so "naive_opt" is equivalent to "naive_raw" in terms of weight path behavior.
if [ "$MODE" = "naive_opt" ]; then
  echo "[mesh] NOTE: exec_mode=naive_opt is deprecated (BCSR opts disabled globally); running as naive_raw"
  MODE="naive_raw"
fi

case "$MODE" in
  gas|naive_raw) ;;
  *)
    echo "[mesh] invalid exec mode: ${MODE_RAW}"
    echo "usage: $0 [gas|naive_raw]"
    exit 2
    ;;
esac

export MESH_EXEC_MODE="$MODE"
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-1}"
export MESH_COMPARE_REQUESTED_EXEC_MODE="$REQUESTED_MODE"
export MESH_COMPARE_EFFECTIVE_EXEC_MODE="$MODE"
if [ -z "${MESH_COMPARE_ROLE:-}" ]; then
  if [ "${MESH_MAX_STEPS}" = "1" ]; then
    export MESH_COMPARE_ROLE="smoke"
  else
    export MESH_COMPARE_ROLE="full"
  fi
fi
if [ -z "${MESH_COMPARE_BOUNDED_VALIDATION:-}" ]; then
  if [ "${MESH_COMPARE_ROLE}" = "smoke" ]; then
    export MESH_COMPARE_BOUNDED_VALIDATION="1"
  else
    export MESH_COMPARE_BOUNDED_VALIDATION="0"
  fi
fi

RUN_ROOT="$PROJECT_ROOT/outputs_large/paper2/dram_mesh_4x4_exec_mode_compare/$MODE"
mkdir -p "$RUN_ROOT"

TS=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$RUN_ROOT/$TS"
if [ -e "$RUN_DIR" ]; then
  suffix=1
  while [ -e "$RUN_ROOT/${TS}-${suffix}" ]; do
    suffix=$((suffix + 1))
  done
  RUN_DIR="$RUN_ROOT/${TS}-${suffix}"
fi
mkdir -p "$RUN_DIR"
export MESH_RUN_DIR="$RUN_DIR"

REPO_ROOT="$(cd "$PROJECT_ROOT/.." && pwd)"
SST_BIN_USER="${SST_BIN:-}"
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
SST_NPROC="${MESH_SST_NPROC:-32}"
COMPARE_LOADER_CHUNK_BYTES="${MESH_COMPARE_LOADER_CHUNK_BYTES:-65536}"
MODEL="$(mesh_prepare_compare_runner_overlay "$PROJECT_ROOT" "$RUN_DIR" "$COMPARE_LOADER_CHUNK_BYTES")"
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

( cd "$PROJECT_ROOT" && /usr/bin/time -v -o "$TIME_FILE" "$SST_BIN" "${SST_ARGS[@]}" -n "$SST_NPROC" "$MODEL" ) > "$LOG" 2>&1
python3 "$PROJECT_ROOT/tools/write_mesh_meta.py" \
  --run-dir "$RUN_DIR" \
  --project-root "$PROJECT_ROOT" \
  --sst-bin "$SST_BIN" \
  --model "$MODEL" \
  --sst-nproc "$SST_NPROC" > "$META_FILE.log" 2>&1

if [ ! -f "$RUN_DIR/local_run_config.json" ] && [ -f "$PROJECT_ROOT/local_run_config.json" ]; then
  cp "$PROJECT_ROOT/local_run_config.json" "$RUN_DIR/local_run_config.json"
fi

# Write a "resolved" config snapshot into run_dir so summaries/validators reflect env overrides.
if [ -f "$RUN_DIR/local_run_config.json" ]; then
  python3 - <<'PY'
import json, os, pathlib
p = pathlib.Path(os.environ["MESH_RUN_DIR"]) / "local_run_config.json"
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    data = {}
def _set(key, val):
    # only set when explicit override is present
    if val is None:
        return
    data[key] = val

_set("sim_time", (os.environ.get("MESH_SIM_TIME") or "").strip() or None)

_v = (os.environ.get("MESH_STEP_ACTIVATION_FRACTION") or "").strip()
if _v:
    try: _set("step_activation_fraction", float(_v))
    except Exception: pass
_v = (os.environ.get("MESH_STEP_ACTIVATION_FANOUT") or "").strip()
if _v:
    try: _set("step_activation_fanout", int(_v))
    except Exception: pass
_v = (os.environ.get("MESH_STEP_ACTIVATION_SEED") or "").strip()
if _v:
    try: _set("step_activation_seed", int(_v))
    except Exception: pass
_v = (os.environ.get("MESH_GLOBAL_STEP_CTRL_VERBOSE") or "").strip()
if _v:
    try: _set("global_step_ctrl_verbose", int(_v))
    except Exception: pass
_v = (os.environ.get("MESH_STEP_ACTIVATION_EVENT_WEIGHT") or "").strip()
if _v:
    try: _set("step_activation_event_weight", float(_v))
    except Exception: pass
_v = (os.environ.get("MESH_STEP_RESET_MEM_EACH_STEP") or "").strip().lower()
if _v:
    if _v in ("1", "true", "yes", "y", "on"):
        _set("step_reset_mem_each_step", 1)
    elif _v in ("0", "false", "no", "n", "off"):
        _set("step_reset_mem_each_step", 0)

p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
fi

python3 "$PROJECT_ROOT/tools/compute_essential_summary_mesh.py" --run-dir "$RUN_DIR"
python3 "$PROJECT_ROOT/tools/summarize_atlas_activation_trace.py" --run-dir "$RUN_DIR"

VALIDATION_LOG="$RUN_DIR/validation.log"
python3 "$PROJECT_ROOT/tools/validate_essential_summary_mesh.py" --run-dir "$RUN_DIR" | tee "$VALIDATION_LOG"

echo "[mesh] exec_mode=$MODE max_steps=$MESH_MAX_STEPS run complete: $RUN_DIR"
