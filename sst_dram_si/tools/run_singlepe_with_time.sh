#!/usr/bin/env bash
set -euo pipefail
# Run single-PE DRAM-SI model under time -p, then copy wallclock to the latest RUN_DIR

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_BASE=${1:-"$ROOT_DIR/outputs_large/paper2/dram_N1k"}

mkdir -p "$ROOT_DIR/logs"
LOG="$ROOT_DIR/logs/last_run.log"
# Write time output inside workspace to avoid /tmp writes under sandboxed runs
TMP_TIME="$ROOT_DIR/logs/sst_time.$$.log"

SST_BIN_USER="${SST_BIN:-}"
if [ -n "$SST_BIN_USER" ]; then
  SST_BIN="$SST_BIN_USER"
else
  SST_BIN_MPI="$ROOT_DIR/../sst_install_mpi/bin/sst"
  SST_BIN_PAR="$ROOT_DIR/../sst_install/bin/sst"
  SST_BIN_SER="$ROOT_DIR/../sst_install_serial/bin/sst"
  if [ -x "$SST_BIN_MPI" ] && "$SST_BIN_MPI" --version >/dev/null 2>&1; then
    SST_BIN="$SST_BIN_MPI"
  elif [ -x "$SST_BIN_PAR" ] && "$SST_BIN_PAR" --version >/dev/null 2>&1; then
    SST_BIN="$SST_BIN_PAR"
  elif [ -x "$SST_BIN_PAR" ]; then
    echo "[run-with-time] error: parallel SST exists but is not runnable in the current environment; refusing to fall back to serial: $SST_BIN_PAR" >&2
    exit 2
  elif [ -x "$SST_BIN_MPI" ]; then
    echo "[run-with-time] error: MPI SST exists but is not runnable in the current environment; refusing to fall back to serial: $SST_BIN_MPI" >&2
    exit 2
  elif [ -x "$SST_BIN_SER" ]; then
    echo "[run-with-time] error: only serial SST is available; refusing to fall back from parallel to serial: $SST_BIN_SER" >&2
    exit 2
  else
    echo "[run-with-time] error: no working parallel SST binary found (checked MPI and parallel installs); refusing to run." >&2
    exit 2
  fi
fi
SST_NPROC="${MESH_SST_NPROC:-32}"

/usr/bin/time -p -o "$TMP_TIME" "$SST_BIN" -n "$SST_NPROC" "$ROOT_DIR/test_dram_si_single_pe.py" | tee "$LOG"

# Pick latest timestamp run dir and copy wallclock file
RUN_DIR=$(ls -1dt "$RUN_BASE"/20* | head -n1 || true)
if [[ -n "${RUN_DIR:-}" && -d "$RUN_DIR" ]]; then
  cp -f "$TMP_TIME" "$RUN_DIR/last_run.time" || true
  # Generate/update summary
  python3 "$ROOT_DIR/tools/compute_essential_summary_singlepe.py" --run-dir "$RUN_BASE" || true
  echo "[run-with-time] Summary written under: $RUN_DIR"
else
  echo "[run-with-time] WARN: could not locate RUN_DIR under $RUN_BASE" >&2
fi
