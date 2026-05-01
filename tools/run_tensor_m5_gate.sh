#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m5_gate.sh [--run-root <dir>] [--skip-unit] [--keep-going] [--drift-baseline <summary.json>] [--drift-threshold <ratio>]

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m5_gate）
  --skip-unit        跳过 M5 轻量单测集合
  --keep-going       某场景失败后继续跑后续场景（默认失败即停）
  --drift-baseline   可选：指定 event_hard 对比基线 summary，用于漂移告警
  --drift-threshold  可选：漂移阈值（默认: 0.30，表示 30%）
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m5_gate"
RUN_ROOT="$RUN_ROOT_DEFAULT"
SKIP_UNIT=0
KEEP_GOING=0
DRIFT_BASELINE=""
DRIFT_THRESHOLD="0.30"

while [ $# -gt 0 ]; do
  case "$1" in
    --run-root)
      RUN_ROOT="${2:-}"
      shift 2
      ;;
    --skip-unit)
      SKIP_UNIT=1
      shift
      ;;
    --keep-going)
      KEEP_GOING=1
      shift
      ;;
    --drift-baseline)
      DRIFT_BASELINE="${2:-}"
      shift 2
      ;;
    --drift-threshold)
      DRIFT_THRESHOLD="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[m5] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SPEC_LEGACY="$REPO_ROOT/tools/specs/tensor_m5_credit_return_legacy_tick_tile_v3.json"
SPEC_EVENT_HARD="$REPO_ROOT/tools/specs/tensor_m5_credit_return_event_hard_tile_v3.json"
SPEC_EVENT_SOFT="$REPO_ROOT/tools/specs/tensor_m5_credit_return_event_soft_tile_v3.json"
SPEC_EVENT_PAYLOAD_FIRST="$REPO_ROOT/tools/specs/tensor_m5_credit_return_event_payload_first_tile_v3.json"
SPEC_EVENT_UNCAPPED="$REPO_ROOT/tools/specs/tensor_m5_credit_return_event_uncapped_tile_v3.json"
SPEC_EVENT_STRESS="$REPO_ROOT/tools/specs/tensor_m5_credit_return_event_stress_tile_v3.json"

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
TREND_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m5_trends.py"
DRIFT_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m5_drift.py"

for p in \
  "$SPEC_LEGACY" "$SPEC_EVENT_HARD" "$SPEC_EVENT_SOFT" \
  "$SPEC_EVENT_PAYLOAD_FIRST" "$SPEC_EVENT_UNCAPPED" "$SPEC_EVENT_STRESS" \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$TREND_VALIDATOR" "$DRIFT_VALIDATOR"
do
  if [ ! -f "$p" ]; then
    echo "[m5][P0] missing required file: $p" >&2
    exit 10
  fi
done

if [ -n "$DRIFT_BASELINE" ] && [ ! -f "$DRIFT_BASELINE" ]; then
  echo "[m5][P0] drift baseline not found: $DRIFT_BASELINE" >&2
  exit 10
fi

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m5] run_root=\"$RUN_ROOT\""
echo "[m5] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m5] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m5_gate.py sst_workloads/tensor_si/tools/test_validate_tensor_m5_trends.py sst_workloads/tensor_si/tools/test_validate_tensor_m5_drift.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m5_gate.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m5_trends.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m5_drift.py" \
    -v; then
    echo "[m5][P0] unit test gate failed" >&2
    exit 10
  fi
fi

declare -A RUN_DIRS=()

run_one() {
  local scenario="$1"
  local spec="$2"
  local expect_collective="$3"
  local scenario_root="$RUN_ROOT/$scenario"
  mkdir -p "$scenario_root"

  echo "[m5][$scenario] validate: $spec"
  if ! python3 "$CLI" validate "$spec"; then
    echo "[m5][P0][$scenario] spec validate failed" >&2
    return 10
  fi

  echo "[m5][$scenario] run: bash \"$RUNNER\" --spec \"$spec\""
  local run_out=""
  if ! run_out=$(
    TENSOR_SI_RUN_ROOT="$scenario_root" bash "$RUNNER" --spec "$spec" 2>&1
  ); then
    echo "$run_out"
    echo "[m5][P1][$scenario] runner failed" >&2
    return 11
  fi
  echo "$run_out"

  local run_dir=""
  run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$run_dir" ]; then
    echo "[m5][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  local contract_args=()
  contract_args+=(--run-dir "$run_dir" --scenario "$scenario" --expect-tile)
  if [ "$expect_collective" = "1" ]; then
    contract_args+=(--expect-collective)
  fi
  python3 "$M0_CONTRACT" "${contract_args[@]}"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    return "$rc"
  fi

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m5][P2][$scenario] missing summary: $summary" >&2
    return 12
  fi

  RUN_DIRS["$scenario"]="$run_dir"
  {
    echo "scenario=$scenario"
    echo "spec=$spec"
    echo "run_dir=$run_dir"
    echo "summary=$summary"
    echo "---"
  } >> "$MANIFEST"

  echo "[m5][$scenario] PASS"
  return 0
}

SCENARIOS=(
  legacy_tick
  event_hard
  event_soft
  event_payload_first
  event_uncapped
  event_stress
)
SPECS=(
  "$SPEC_LEGACY"
  "$SPEC_EVENT_HARD"
  "$SPEC_EVENT_SOFT"
  "$SPEC_EVENT_PAYLOAD_FIRST"
  "$SPEC_EVENT_UNCAPPED"
  "$SPEC_EVENT_STRESS"
)
EXPECT_COLLECTIVE=(1 1 1 1 1 1)

FAIL_COUNT=0
for idx in "${!SCENARIOS[@]}"; do
  scenario="${SCENARIOS[$idx]}"
  spec="${SPECS[$idx]}"
  expect_collective="${EXPECT_COLLECTIVE[$idx]}"
  rc=0
  run_one "$scenario" "$spec" "$expect_collective" || rc=$?
  if [ "$rc" -ne 0 ]; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "[m5] FAIL scenario=$scenario rc=$rc" >&2
    if [ "$KEEP_GOING" != "1" ]; then
      exit "$rc"
    fi
  fi
done

if [ "$FAIL_COUNT" -ne 0 ]; then
  echo "[m5] FAIL: $FAIL_COUNT scenario(s) failed" >&2
  exit 13
fi

python3 "$TREND_VALIDATOR" \
  --legacy-tick "${RUN_DIRS[legacy_tick]}/essential_summary_tensor_mesh.json" \
  --event-hard "${RUN_DIRS[event_hard]}/essential_summary_tensor_mesh.json" \
  --event-soft "${RUN_DIRS[event_soft]}/essential_summary_tensor_mesh.json" \
  --event-payload-first "${RUN_DIRS[event_payload_first]}/essential_summary_tensor_mesh.json" \
  --event-uncapped "${RUN_DIRS[event_uncapped]}/essential_summary_tensor_mesh.json" \
  --event-stress "${RUN_DIRS[event_stress]}/essential_summary_tensor_mesh.json" \
  | tee "$REPORT_DIR/trend_validation.log"

if [ -n "$DRIFT_BASELINE" ]; then
  python3 "$DRIFT_VALIDATOR" \
    --current "${RUN_DIRS[event_hard]}/essential_summary_tensor_mesh.json" \
    --baseline "$DRIFT_BASELINE" \
    --threshold "$DRIFT_THRESHOLD" \
    | tee "$REPORT_DIR/drift_validation.log"
fi

echo "[m5] PASS"
echo "[m5] manifest: $MANIFEST"
cat "$MANIFEST"
