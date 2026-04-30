#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
用法:
  run_spiketile_with_time.sh [--spec <spec.json>]

选项:
  --spec <spec.json>   启用 spec-first（会导出 MESH_SPEC_JSON）
  -h, --help           显示帮助
EOF
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
      echo "[spiketile] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
REPO_ROOT=$(cd "$PROJECT_ROOT/.." && pwd)
MODEL="$SCRIPT_DIR/test_mesh_4x4_spiketile.py"

if [ -z "${PYTHONPATH:-}" ]; then
  export PYTHONPATH="$REPO_ROOT"
elif [[ ":$PYTHONPATH:" != *":$REPO_ROOT:"* ]]; then
  export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"
fi

RUN_ROOT="$SCRIPT_DIR/outputs/runs"
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
    echo "[spiketile] spec not found: $SPEC_ABS" >&2
    exit 2
  fi
  export MESH_SPEC_JSON="$SPEC_ABS"
else
  export MESH_MAX_STEPS="${MESH_MAX_STEPS:-2}"
fi

if [ -z "${MESH_BCSR_DIR:-}" ]; then
  DEFAULT_BCSR="$PROJECT_ROOT/weights/bcsr_global_16pe_fanout256_10k_rowpack_v1"
  if [ -d "$DEFAULT_BCSR" ]; then
    export MESH_BCSR_DIR="$DEFAULT_BCSR"
  fi
fi

SST_BIN_USER="${SST_BIN:-}"
SST_ADD_LIB_PATH="${SST_ADD_LIB_PATH:-}"
DEFAULT_NPROC=32
if [ -n "$SST_BIN_USER" ]; then
  SST_BIN="$SST_BIN_USER"
else
  SST_BIN_MPI="$REPO_ROOT/sst_install_mpi/bin/sst"
  SST_BIN_PAR="$REPO_ROOT/sst_install/bin/sst"
  SST_BIN_SER="$REPO_ROOT/sst_install_serial/bin/sst"
  if [ -x "$SST_BIN_MPI" ] && "$SST_BIN_MPI" --version >/dev/null 2>&1; then
    SST_BIN="$SST_BIN_MPI"
    DEFAULT_NPROC=32
  elif [ -x "$SST_BIN_PAR" ] && "$SST_BIN_PAR" --version >/dev/null 2>&1; then
    SST_BIN="$SST_BIN_PAR"
    DEFAULT_NPROC=32
  elif [ -x "$SST_BIN_SER" ] && "$SST_BIN_SER" --version >/dev/null 2>&1; then
    SST_BIN="$SST_BIN_SER"
    DEFAULT_NPROC=1
  else
    echo "[spiketile] cannot locate a usable sst binary (set SST_BIN manually)" >&2
    exit 2
  fi
fi
SST_NPROC="${MESH_SST_NPROC:-$DEFAULT_NPROC}"

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

LOG="$RUN_DIR/mesh_run.log"
TIME_FILE="$RUN_DIR/time.txt"
META_FILE="$RUN_DIR/meta.json"
VALIDATION_LOG="$RUN_DIR/validation.log"

( cd "$PROJECT_ROOT" && /usr/bin/time -v -o "$TIME_FILE" "$SST_BIN" "${SST_ARGS[@]}" -n "$SST_NPROC" "$MODEL" ) > "$LOG" 2>&1

python3 "$PROJECT_ROOT/tools/write_mesh_meta.py" \
  --run-dir "$RUN_DIR" \
  --project-root "$PROJECT_ROOT" \
  --sst-bin "$SST_BIN" \
  --model "$MODEL" \
  --sst-nproc "$SST_NPROC" > "$META_FILE.log" 2>&1

python3 "$PROJECT_ROOT/tools/compute_essential_summary_mesh.py" --run-dir "$RUN_DIR"

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

echo "[spiketile] run complete: $RUN_DIR"
echo "[spiketile] artifacts:"
echo "  - $LOG"
echo "  - $TIME_FILE"
echo "  - $META_FILE"
echo "  - $RUN_DIR/effective_config.json"
echo "  - $RUN_DIR/essential_summary_mesh.json"
echo "  - $VALIDATION_LOG"
