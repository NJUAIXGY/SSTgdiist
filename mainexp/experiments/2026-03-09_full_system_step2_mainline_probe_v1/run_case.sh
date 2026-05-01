#!/usr/bin/env bash
set -euo pipefail

CASE_ID="${1:-}"
if [ -z "$CASE_ID" ]; then
  echo "usage: $0 <full_system_baseline_steps2|full_system_steps2_frac0001_gbiprobe_core0>" >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
RUNNER="$PROJECT_ROOT/sst_dram_si/tools/run_mesh_with_time.sh"

COMMON_ENV=(
  MESH_EXPERIMENTAL_ENABLE=1
  MESH_VALIDATE_PROFILE=paper
  MESH_MAX_STEPS=2
  MESH_MEM_BACKEND=ramulator2
  MESH_RAMULATOR2_CONFIG_FILE=/home/xgy/remote/sst_dram_si/configs/ramulator2_ddr5.cfg
  MESH_SYNAPSE_WEIGHT_MODE=gcss_valueonly_dstcore_vlf_premphf_plp
  MESH_GCSSPLP_DIR=/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_v7_lpblp_j8
  MESH_GAS_VLF_ENABLE=1
  MESH_GAS_VLF_RUN_ENABLE=0
  MESH_NOC_TYPE=multicast_mesh
  MESH_MULTICAST_ENABLE=1
  MESH_MULTICAST_BLOCK_W=2
  MESH_MULTICAST_BLOCK_H=2
  MESH_MULTICAST_INGRESS_POLICY=top_left
  MESH_MULTICAST_INTER_POLICY=xy
  MESH_MULTICAST_INTRA_POLICY=manhattan_x_first
)

case "$CASE_ID" in
  full_system_baseline_steps2)
    CASE_ENV=(
      MESH_STEP_ACTIVATION_FRACTION=0.03
    )
    ;;
  full_system_steps2_frac0001_gbiprobe_core0)
    CASE_ENV=(
      MESH_STEP_ACTIVATION_FRACTION=0.0001
      MESH_GBI_STEPGATE_PROGRESS_ENABLE=1
      MESH_GBI_STEPGATE_PROGRESS_PERIOD_CYCLES=1024
      MESH_GBI_STEPGATE_PROGRESS_MAX_REPORTS=0
      MESH_GBI_STEPGATE_PROGRESS_OWNER_NODE=0
      MESH_GBI_STEPGATE_PROGRESS_OWNER_CORE=0
      MESH_GBI_STEPGATE_APPLY_FINISH_POLL_PERIOD_CYCLES=1
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
