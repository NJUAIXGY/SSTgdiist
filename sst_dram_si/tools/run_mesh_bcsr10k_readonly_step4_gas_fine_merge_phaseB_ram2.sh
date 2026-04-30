#!/usr/bin/env bash
set -euo pipefail

# Phase B: Fine-merge calibration sweep (Ramulator2 backends, Step=4, read-only freeze).
#
# Goal:
#   Sweep "fine merge" knobs in the safe regime:
#     - row_window_* disabled (avoid coarse row-window overfetch)
#     - small gap_k and Lmax ranges
#   while keeping a consistent "full GAS" baseline via forced staging (defer_issue_until_apply=1).
#
# Outputs:
#   outputs_large/paper2/${MESH_GAS_CAL_RUN_GROUP}/...
#   plus calibration_results.tsv in the group root.
#
# Notes:
#   - No new BCSR datasets are generated (reuse weights/*_10k).
#   - Defaults are conservative to avoid accidentally launching a huge sweep.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Keep the GAS implementation path consistent across all sweep points (even when k=rowwin=tmo are zero).
export MESH_GAS_FORCE_DEFER="${MESH_GAS_FORCE_DEFER:-1}"

# Ramulator2 only (HBM2 + DDR5).
export MESH_CAL_BACKENDS="${MESH_CAL_BACKENDS:-ram2_hbm2 ram2_ddr5}"

# Phase B safe ranges (override as needed).
export MESH_CAL_GAP_K_LIST="${MESH_CAL_GAP_K_LIST:-0 64 128 256 512}"
export MESH_CAL_LMAX_LIST="${MESH_CAL_LMAX_LIST:-256 512 1024 2048 4096}"
export MESH_CAL_ROWWIN_LIST="${MESH_CAL_ROWWIN_LIST:-0}"
export MESH_CAL_ROWWIN_TIMEOUT_LIST="${MESH_CAL_ROWWIN_TIMEOUT_LIST:-0}"

# Default workload point for calibration.
export MESH_STEP_ACTIVATION_FRACTION="${MESH_STEP_ACTIVATION_FRACTION:-0.03}"

# Keep L1 disabled unless explicitly requested (matches "no L1" baseline).
export MESH_L1_ENABLE="${MESH_L1_ENABLE:-0}"

export MESH_GAS_CAL_RUN_GROUP="${MESH_GAS_CAL_RUN_GROUP:-dram_mesh_4x4_bcsr10k_readonly_step4_gas_fine_merge_phaseB_ram2_v1}"

exec "$PROJECT_ROOT/tools/run_mesh_bcsr10k_readonly_step4_gas_merge_calibration.sh"

