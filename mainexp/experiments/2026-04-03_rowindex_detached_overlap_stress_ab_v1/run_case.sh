#!/usr/bin/env bash
set -euo pipefail

CASE_ID="${1:-}"
if [ -z "$CASE_ID" ]; then
  echo "usage: $0 <rowindex_detached_overlap_off|rowindex_detached_overlap_on|rowindex_detached_overlap_pascal_off|rowindex_detached_overlap_pascal_on|rowindex_detached_overlap_probe_on|rowindex_detached_overlap_probe_off|rowindex_detached_overlap_probe_time_on|rowindex_detached_overlap_probe_time_off>" >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
RUNNER="$PROJECT_ROOT/sst_dram_si/tools/run_mesh_with_time.sh"

case "$CASE_ID" in
  rowindex_detached_overlap_off)
    SPEC="$SCRIPT_DIR/spec_off.json"
    ;;
  rowindex_detached_overlap_on)
    SPEC="$SCRIPT_DIR/spec_on.json"
    ;;
  rowindex_detached_overlap_pascal_off)
    SPEC="$SCRIPT_DIR/spec_pascal_off.json"
    ;;
  rowindex_detached_overlap_pascal_on)
    SPEC="$SCRIPT_DIR/spec_pascal_on.json"
    ;;
  rowindex_detached_overlap_probe_off)
    SPEC="$SCRIPT_DIR/spec_probe_off.json"
    ;;
  rowindex_detached_overlap_probe_on)
    SPEC="$SCRIPT_DIR/spec_probe_on.json"
    ;;
  rowindex_detached_overlap_probe_time_off)
    SPEC="$SCRIPT_DIR/spec_probe_time_off.json"
    ;;
  rowindex_detached_overlap_probe_time_on)
    SPEC="$SCRIPT_DIR/spec_probe_time_on.json"
    ;;
  *)
    echo "unknown case: $CASE_ID" >&2
    exit 2
    ;;
esac

RUN_ROOT="$SCRIPT_DIR/runs/$CASE_ID"
mkdir -p "$RUN_ROOT"

DEFAULT_BCSR_DIR="/home/xgy/remote/sst_dram_si/weights/bcsr_global_16pe_fanout256_10k"
BCSR_DIR="${MESH_BCSR_DIR:-$DEFAULT_BCSR_DIR}"
BCSR_META_SAMPLE="$BCSR_DIR/pe00/core00.bcsr.bin.meta.json"
BCSR_BIN_SAMPLE="$BCSR_DIR/pe00/core00.bcsr.bin"

if [ ! -f "$BCSR_META_SAMPLE" ] || [ ! -f "$BCSR_BIN_SAMPLE" ]; then
  echo "[run_case] missing required bcsr_gas dataset root: $BCSR_DIR" >&2
  echo "[run_case] expected files:" >&2
  echo "  - $BCSR_META_SAMPLE" >&2
  echo "  - $BCSR_BIN_SAMPLE" >&2
  exit 3
fi

set +e
env \
  SST_BIN=/home/xgy/remote/sst_install_mpi/bin/sst \
  MESH_BCSR_DIR="$BCSR_DIR" \
  MESH_EXPERIMENTAL_ENABLE=1 \
  MESH_SST_NPROC=1 \
  MESH_VALIDATE_PROFILE=dev \
  MESH_RUN_ROOT="$RUN_ROOT" \
  "$RUNNER" --spec "$SPEC"
RUN_STATUS=$?
set -e

LATEST_RUN=$(find "$RUN_ROOT" -mindepth 1 -maxdepth 1 -type d | LC_ALL=C sort | tail -n 1)
if [ -n "${LATEST_RUN:-}" ]; then
  ln -sfn "$LATEST_RUN" "$RUN_ROOT/latest"
  echo "[run_case] latest -> $LATEST_RUN"
fi

exit "$RUN_STATUS"
