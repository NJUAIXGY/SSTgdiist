#!/usr/bin/env bash
set -euo pipefail

# Compare experiment runner (exec_mode=gas, max_steps=4).
# This remains the heavyweight full experiment entrypoint.
# For routine bounded validation, use run_mesh_compare_steps4_gas_smoke.sh instead.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export MESH_COMPARE_ROLE="${MESH_COMPARE_ROLE:-full}"
export MESH_COMPARE_BOUNDED_VALIDATION="${MESH_COMPARE_BOUNDED_VALIDATION:-0}"
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-4}"

exec "$SCRIPT_DIR/run_mesh_exec_mode_compare_with_time.sh" gas
