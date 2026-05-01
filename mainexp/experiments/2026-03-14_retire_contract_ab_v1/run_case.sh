#!/usr/bin/env bash
set -euo pipefail

CASE_ID="${1:-}"
if [ -z "$CASE_ID" ]; then
  echo "usage: $0 <baseline_contract_smoke|shadow_per_post_smoke>" >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
RUNNER="$PROJECT_ROOT/sst_dram_si/tools/run_mesh_with_time.sh"

COMMON_ENV=(
  MESH_EXPERIMENTAL_ENABLE=1
  MESH_VALIDATE_PROFILE=paper
  MESH_EXEC_MODE=gas
  MESH_MAX_STEPS=1
  MESH_EXPERIMENTAL_GCSS_PHASE_BREAKDOWN_ENABLE=1
  MESH_EXPERIMENTAL_RETIRE_POLICY=global_inorder
)

case "$CASE_ID" in
  baseline_contract_smoke)
    CASE_ENV=(
      MESH_EXPERIMENTAL_RETIRE_SHADOW_PER_POST_ENABLE=0
    )
    ;;
  shadow_per_post_smoke)
    CASE_ENV=(
      MESH_EXPERIMENTAL_RETIRE_SHADOW_PER_POST_ENABLE=1
    )
    ;;
  *)
    echo "unknown case: $CASE_ID" >&2
    exit 2
    ;;
esac

RUN_ROOT="$SCRIPT_DIR/runs/$CASE_ID"
mkdir -p "$RUN_ROOT"

env "${COMMON_ENV[@]}" "${CASE_ENV[@]}" MESH_RUN_ROOT="$RUN_ROOT" "$RUNNER"
