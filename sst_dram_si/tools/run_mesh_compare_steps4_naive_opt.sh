#!/usr/bin/env bash
set -euo pipefail

# Compare experiment runner (deprecated naive_opt).
# NOTE: BCSR optimizations are globally disabled in SnnDL, so naive_opt == naive_raw.
# We keep this script name for compatibility, but route it through the shared compare runner.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export MESH_COMPARE_ROLE="${MESH_COMPARE_ROLE:-full}"
export MESH_COMPARE_BOUNDED_VALIDATION="${MESH_COMPARE_BOUNDED_VALIDATION:-0}"
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-4}"

exec "$SCRIPT_DIR/run_mesh_exec_mode_compare_with_time.sh" naive_opt
