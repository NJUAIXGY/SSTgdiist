#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
用法:
  run_tensor_mesh_with_time.sh [--spec <spec.json>]

选项:
  --spec <spec.json>   启用 spec-first（会导出 TENSOR_SPEC_JSON）
  -h, --help           显示帮助
EOF
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
      echo "[tensor_mesh] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(cd "$PROJECT_ROOT/../.." && pwd)

RUN_ROOT="${TENSOR_SI_RUN_ROOT:-$PROJECT_ROOT/outputs/tensor_mesh_4x4}"
mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$RUN_ROOT/$TS"
mkdir -p "$RUN_DIR"

export TENSOR_SI_RUN_DIR="$RUN_DIR"

if [ -n "$SPEC_JSON" ]; then
  SPEC_ABS=$(
    python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$SPEC_JSON"
  )
  if [ ! -f "$SPEC_ABS" ]; then
    echo "[tensor_mesh] spec not found: $SPEC_ABS" >&2
    exit 2
  fi
  export TENSOR_SPEC_JSON="$SPEC_ABS"
  echo "[tensor_mesh] spec-first enabled: TENSOR_SPEC_JSON=$TENSOR_SPEC_JSON"
fi

SST_BIN_USER="${SST_BIN:-}"
if [ -n "$SST_BIN_USER" ]; then
  SST_BIN="$SST_BIN_USER"
elif [ -x "$REPO_ROOT/sst_install_mpi/bin/sst" ]; then
  SST_BIN="$REPO_ROOT/sst_install_mpi/bin/sst"
elif [ -x "$REPO_ROOT/sst_install_serial/bin/sst" ]; then
  SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst"
else
  SST_BIN="$REPO_ROOT/sst_install/bin/sst"
fi
SST_ADD_LIB_PATH="${SST_ADD_LIB_PATH:-}"
SST_NPROC="${TENSOR_SI_SST_NPROC:-${MESH_SST_NPROC:-32}}"
MODEL="$PROJECT_ROOT/test_tensor_mesh_4x4.py"
LOG="$RUN_DIR/tensor_mesh_run.log"
TIME_FILE="$RUN_DIR/time.txt"

# Default add-lib-path for tensor_si (dev workflow: load in-tree built element libs).
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

# memHierarchy depends on ramulator; auto-add if present.
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

python3 "$PROJECT_ROOT/tools/compute_essential_summary_tensor_mesh.py" --run-dir "$RUN_DIR"
python3 "$PROJECT_ROOT/tools/validate_essential_summary_tensor_mesh.py" --summary "$RUN_DIR/essential_summary_tensor_mesh.json" | tee "$RUN_DIR/validation.log"

echo "[tensor_mesh] run complete: $RUN_DIR"
echo "[tensor_mesh] artifacts:"
echo "  - $LOG"
echo "  - $TIME_FILE"
echo "  - $RUN_DIR/effective_config.json"
echo "  - $RUN_DIR/essential_summary_tensor_mesh.json"
echo "  - $RUN_DIR/validation.log"
