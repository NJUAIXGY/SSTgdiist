#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
RUNNER="$PROJECT_ROOT/sst_dram_si/tools/run_mesh_with_time.sh"
RUN_ROOT="$SCRIPT_DIR/runs/idx2_ingress_finish_stats_smoke_tiny"
SPEC="$SCRIPT_DIR/spec.json"

mkdir -p "$RUN_ROOT"

env \
  SST_BIN=/home/xgy/remote/sst_install_mpi/bin/sst \
  MESH_EXPERIMENTAL_ENABLE=1 \
  MESH_SST_NPROC=1 \
  MESH_VALIDATE_PROFILE=dev \
  MESH_RUN_ROOT="$RUN_ROOT" \
  "$RUNNER" --spec "$SPEC"

LATEST_RUN=$(find "$RUN_ROOT" -mindepth 1 -maxdepth 1 -type d | LC_ALL=C sort | tail -n 1)
if [ -n "${LATEST_RUN:-}" ]; then
  ln -sfn "$LATEST_RUN" "$RUN_ROOT/latest"
  echo "[run_case] latest -> $LATEST_RUN"
fi
