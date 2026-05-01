#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
RUN_CASE="$SCRIPT_DIR/run_case.sh"

TOP_ITEMS_LIST=(${TOP_ITEMS_LIST:-16 24 32})
BAND_SLOTS_LIST=(${BAND_SLOTS_LIST:-64 96 128})
OBSERVE_BAND_SLOTS_LIST=(${OBSERVE_BAND_SLOTS_LIST:-128})
PREBAND_BAND_SLOTS_LIST=(${PREBAND_BAND_SLOTS_LIST:-64 80 96 128})
GATHER_WINDOW_BUDGET_LIST=(${GATHER_WINDOW_BUDGET_LIST:-4 6 8})
GRID_MODE="${GRID_MODE:-phase_probe}"
INCLUDE_BASELINE="${INCLUDE_BASELINE:-1}"
FORCE_RERUN="${FORCE_RERUN:-0}"

case_done() {
  local case_id="$1"
  local run_root="$SCRIPT_DIR/runs/$case_id"
  local latest_dir="$run_root/latest"
  local time_file="$latest_dir/time.txt"
  local validation_file="$latest_dir/validation.log"

  if [ "$FORCE_RERUN" = "1" ]; then
    return 1
  fi
  if [ ! -L "$latest_dir" ] || [ ! -f "$time_file" ] || [ ! -f "$validation_file" ]; then
    return 1
  fi
  if ! rg -q "Exit status:\\s+0" "$time_file"; then
    return 1
  fi
  if ! rg -q "fail=0\\s+warn=0\\s+strict=0" "$validation_file"; then
    return 1
  fi
  return 0
}

run_case_with_skip() {
  local case_id="$1"
  if case_done "$case_id"; then
    echo "[run_grid] skip completed case: $case_id"
    return 0
  fi
  echo "[run_grid] run case: $case_id"
  "$RUN_CASE" "$case_id"
}

if [ "$INCLUDE_BASELINE" = "1" ]; then
  run_case_with_skip "pulse_shared_line_actual_mfb_gather_preband_dedup_off"
fi

if [ "$GRID_MODE" = "legacy" ]; then
  for top in "${TOP_ITEMS_LIST[@]}"; do
    for band in "${BAND_SLOTS_LIST[@]}"; do
      case_id="pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top${top}_band${band}"
      run_case_with_skip "$case_id"
    done
  done
else
  for top in "${TOP_ITEMS_LIST[@]}"; do
    for observe_band in "${OBSERVE_BAND_SLOTS_LIST[@]}"; do
      for preband_band in "${PREBAND_BAND_SLOTS_LIST[@]}"; do
        for budget in "${GATHER_WINDOW_BUDGET_LIST[@]}"; do
          case_id="pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top${top}_observe_band${observe_band}_preband_band${preband_band}_budget${budget}"
          run_case_with_skip "$case_id"
        done
      done
    done
  done
fi

echo "[run_grid] done"
