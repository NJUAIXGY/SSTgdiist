#!/usr/bin/env bash
set -euo pipefail

# Bounded smoke counterpart for the heavyweight steps4 gas compare experiment.
# Keeps the full experiment script intact while reusing the stable 1-step compare runner
# for routine validation.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "${MESH_SST_NPROC:-}" ] && [ -n "${MESH_COMPARE_SMOKE_NPROC:-}" ]; then
  export MESH_SST_NPROC="$MESH_COMPARE_SMOKE_NPROC"
fi
export MESH_COMPARE_ROLE="${MESH_COMPARE_ROLE:-smoke}"
export MESH_COMPARE_BOUNDED_VALIDATION="${MESH_COMPARE_BOUNDED_VALIDATION:-1}"
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-1}"

exec "$SCRIPT_DIR/run_mesh_exec_mode_compare_with_time.sh" gas
