#!/usr/bin/env bash
set -euo pipefail

CASE_ID="${1:-}"
if [ -z "$CASE_ID" ]; then
  echo "usage: $0 <baseline_mainline_step1_seed_only_frac003|atlas_lss_negative_control_step1_seed_only_frac003|rail_p1_span_only_step1_seed_only_frac003|rail_p2_span_head_issue_step1_seed_only_frac003>" >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
RUNNER="$PROJECT_ROOT/sst_dram_si/tools/run_mesh_with_time.sh"

COMMON_ENV=(
  MESH_EXPERIMENTAL_ENABLE=1
  MESH_VALIDATE_PROFILE=paper
  MESH_MAX_STEPS=1
  MESH_STEP_SEED_ONLY_MODE=1
  MESH_STEP_ACTIVATION_FRACTION=0.03
  MESH_MEM_BACKEND=ramulator2
  MESH_RAMULATOR2_CONFIG_FILE=/home/xgy/remote/sst_dram_si/configs/ramulator2_ddr5.cfg
  MESH_GAS_VLF_ENABLE=1
  MESH_GAS_VLF_RUN_ENABLE=0
  MESH_GAS_ATLAS_CORE_ENABLE=0
  MESH_NOC_TYPE=multicast_mesh
  MESH_MULTICAST_ENABLE=1
  MESH_MULTICAST_BLOCK_W=2
  MESH_MULTICAST_BLOCK_H=2
  MESH_MULTICAST_INGRESS_POLICY=top_left
  MESH_MULTICAST_INTER_POLICY=xy
  MESH_MULTICAST_INTRA_POLICY=manhattan_x_first
)

case "$CASE_ID" in
  baseline_mainline_step1_seed_only_frac003)
    CASE_ENV=(
      MESH_SYNAPSE_WEIGHT_MODE=gcss_valueonly_dstcore_vlf_premphf_plp
      MESH_GCSSPLP_DIR=/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_v7_lpblp_j8
      MESH_GAS_ATLAS_PE_ENABLE=0
    )
    ;;
  atlas_lss_negative_control_step1_seed_only_frac003)
    CASE_ENV=(
      MESH_SYNAPSE_WEIGHT_MODE=gcss_valueonly_dstpe_atlas_lss_v1
      MESH_GCSSATLAS_DIR=/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstpe_atlas_lss_v1_fanout256_10k
      MESH_GAS_ATLAS_PE_ENABLE=1
      MESH_GAS_RAIL_SPAN_CAP=0
      MESH_GAS_RAIL_LOOKAHEAD_CAP=0
      MESH_GAS_RAIL_FANOUT_CAP=0
    )
    ;;
  rail_p1_span_only_step1_seed_only_frac003)
    CASE_ENV=(
      MESH_SYNAPSE_WEIGHT_MODE=gcss_valueonly_dstpe_atlas_lss_v1
      MESH_GCSSATLAS_DIR=/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstpe_atlas_lss_v1_fanout256_10k
      MESH_GAS_ATLAS_PE_ENABLE=1
      MESH_GAS_RAIL_SPAN_CAP=32
      MESH_GAS_RAIL_LOOKAHEAD_CAP=128
      MESH_GAS_RAIL_FANOUT_CAP=8
    )
    ;;
  rail_p2_span_head_issue_step1_seed_only_frac003)
    CASE_ENV=(
      MESH_SYNAPSE_WEIGHT_MODE=gcss_valueonly_dstpe_atlas_lss_v1
      MESH_GCSSATLAS_DIR=/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstpe_atlas_lss_v1_fanout256_10k
      MESH_GAS_ATLAS_PE_ENABLE=1
      MESH_GAS_RAIL_SPAN_CAP=32
      MESH_GAS_RAIL_LOOKAHEAD_CAP=128
      MESH_GAS_RAIL_FANOUT_CAP=8
      MESH_GAS_RAIL_HEAD_ISSUE_ENABLE=1
      MESH_GAS_RAIL_ISSUE_STAGE_CAP=16
      MESH_GAS_RAIL_HEAD_SLACK=32
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
