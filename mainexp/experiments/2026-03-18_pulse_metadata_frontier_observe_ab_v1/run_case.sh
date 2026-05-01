#!/usr/bin/env bash
set -euo pipefail

CASE_ID="${1:-}"
if [ -z "$CASE_ID" ]; then
  echo "usage: $0 <pulse_shared_line_actual_baseline|pulse_shared_line_actual_metadata_frontier_observe_top64_band256>" >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
RUNNER="$PROJECT_ROOT/sst_dram_si/tools/run_mesh_with_time.sh"

COMMON_ENV=(
  SST_BIN=/home/xgy/remote/sst_install_mpi/bin/sst
  MESH_EXPERIMENTAL_ENABLE=1
  MESH_VALIDATE_PROFILE=paper
  MESH_MAX_STEPS=1
  MESH_STEP_SEED_ONLY_MODE=1
  MESH_STEP_ACTIVATION_FRACTION=0.03
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
  MESH_PULSE_ENABLE=1
  MESH_PULSE_OBSERVE_ONLY=1
  MESH_PULSE_INGRESS_ENABLE=1
  MESH_PULSE_AGENDA_OBSERVE_ONLY=1
  MESH_PULSE_HARBOR_ENABLE=1
  MESH_PULSE_DESCRIPTOR_ENABLE=1
  MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE=1
  MESH_PULSE_DESCRIPTOR_PACKET_MIN=4
  MESH_PULSE_INGRESS_ENTRIES=32
  MESH_PULSE_CORE_QUEUE_ENTRIES=32
  MESH_PULSE_BYPASS_HIGH_WATERMARK_PCT=50
  MESH_PULSE_BYPASS_MODE=high_watermark
)

case "$CASE_ID" in
  pulse_shared_line_actual_baseline)
    CASE_ENV=()
    ;;
  pulse_shared_line_actual_metadata_frontier_observe_top64_band256)
    CASE_ENV=(
      MESH_PULSE_METADATA_FRONTIER_OBSERVE_ENABLE=1
      MESH_PULSE_METADATA_FRONTIER_TOP_ITEMS=64
      MESH_PULSE_METADATA_FRONTIER_BAND_SLOTS=256
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

LATEST_RUN=$(find "$RUN_ROOT" -mindepth 1 -maxdepth 1 -type d | LC_ALL=C sort | tail -n 1)
if [ -n "${LATEST_RUN:-}" ]; then
  ln -sfn "$LATEST_RUN" "$RUN_ROOT/latest"
  echo "[run_case] latest -> $LATEST_RUN"
fi
