#!/usr/bin/env bash
set -euo pipefail

CASE_NAME="${1:-}"
DRY_RUN=0
if [ "$CASE_NAME" = "--dry-run" ]; then
  DRY_RUN=1
  CASE_NAME="${2:-}"
fi
if [ -z "$CASE_NAME" ]; then
  echo "usage: $0 [--dry-run] <shared_weight_owner_off|shared_weight_owner_req_on|shared_weight_actual_owner_on>" >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
RUNNER="$PROJECT_ROOT/sst_dram_si/tools/run_mesh_with_time.sh"
RUN_DIR="$SCRIPT_DIR/runs/$CASE_NAME"
mkdir -p "$RUN_DIR"

COMMON_ENV=(
  SST_BIN=/home/xgy/remote/sst_install_mpi/bin/sst
  MESH_EXPERIMENTAL_ENABLE=1
  MESH_VALIDATE_PROFILE=dev
  MESH_SST_NPROC=1
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
  MESH_LOCAL_STORAGE_ENABLE=1
  MESH_SRAM_MODEL_ENABLE=1
  MESH_SRAM_WEIGHT_IDX_ENABLE=1
  MESH_SRAM_WEIGHT_L0_ENABLE=1
  MESH_SRAM_WEIGHT_IDX_CAPACITY_BYTES=1048576
  MESH_SRAM_WEIGHT_L0_CAPACITY_BYTES=4194304
  MESH_SRAM_WEIGHT_IDX_BANKS=8
  MESH_SRAM_WEIGHT_L0_BANKS=8
  MESH_SRAM_WEIGHT_PORTS_PER_BANK=1
  MESH_PULSE_OSA_ENABLE=1
)

case "$CASE_NAME" in
  shared_weight_owner_off)
    SPEC="$SCRIPT_DIR/spec_shared_weight_owner_off.json"
    CASE_ENV=(
      MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE=0
      MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE=0
    )
    ;;
  shared_weight_owner_req_on)
    SPEC="$SCRIPT_DIR/spec_shared_weight_owner_req_on.json"
    CASE_ENV=(
      MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE=1
      MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE=0
    )
    ;;
  shared_weight_actual_owner_on)
    SPEC="$SCRIPT_DIR/spec_shared_weight_actual_owner_on.json"
    CASE_ENV=(
      MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE=1
      MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE=1
    )
    ;;
  *)
    echo "unknown case: $CASE_NAME" >&2
    exit 2
    ;;
esac

if [ ! -f "$SPEC" ]; then
  echo "[run_case] missing spec: $SPEC" >&2
  exit 3
fi

if [ ! -f "$RUNNER" ]; then
  echo "[run_case] missing runner: $RUNNER" >&2
  exit 3
fi

echo "[run_case] case=$CASE_NAME run_dir=$RUN_DIR"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "DRY RUN: env ${COMMON_ENV[*]} ${CASE_ENV[*]} MESH_RUN_ROOT=$RUN_DIR $RUNNER --spec $SPEC"
  exit 0
fi

set +e
env "${COMMON_ENV[@]}" "${CASE_ENV[@]}" MESH_RUN_ROOT="$RUN_DIR" "$RUNNER" --spec "$SPEC"
RUN_STATUS=$?
set -e

LATEST_RUN=$(find "$RUN_DIR" -mindepth 1 -maxdepth 1 -type d | LC_ALL=C sort | tail -n 1)
if [ -n "${LATEST_RUN:-}" ]; then
  ln -sfn "$LATEST_RUN" "$RUN_DIR/latest"
  echo "[run_case] latest -> $LATEST_RUN"
fi

exit "$RUN_STATUS"
