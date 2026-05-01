#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
用法:
  run_tensor_m2_gate.sh [--run-root <dir>] [--skip-unit] [--keep-going]

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m2_gate）
  --skip-unit        跳过 M2 轻量单测集合
  --keep-going       某场景失败后继续跑后续场景（默认失败即停）
  -h, --help         显示帮助
EOF
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m2_gate"
RUN_ROOT="$RUN_ROOT_DEFAULT"
SKIP_UNIT=0
KEEP_GOING=0

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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[m2] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SPEC_BASELINE="$REPO_ROOT/tools/specs/tensor_m2_baseline_compat_tile_v3.json"
SPEC_ON="$REPO_ROOT/tools/specs/tensor_m2_noc_capped_overlap_on_tile_v3.json"
SPEC_OFF="$REPO_ROOT/tools/specs/tensor_m2_noc_capped_overlap_off_tile_v3.json"
SPEC_HEAVY="$REPO_ROOT/tools/specs/tensor_m2_noc_capped_heavy_collective_tile_v3.json"
SPEC_PAYLOAD_FIRST="$REPO_ROOT/tools/specs/tensor_m2_noc_capped_payload_first_tile_v3.json"

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
TREND_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m2_trends.py"

for p in \
  "$SPEC_BASELINE" "$SPEC_ON" "$SPEC_OFF" "$SPEC_HEAVY" "$SPEC_PAYLOAD_FIRST" \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$TREND_VALIDATOR"
do
  if [ ! -f "$p" ]; then
    echo "[m2][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m2] run_root=\"$RUN_ROOT\""
echo "[m2] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m2] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m2_gate.py sst_workloads/tensor_si/tools/test_validate_tensor_m2_trends.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m2_gate.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m2_trends.py" \
    -v; then
    echo "[m2][P0] unit test gate failed" >&2
    exit 10
  fi
fi

declare -A RUN_DIRS=()

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$RUN_ROOT/$scenario"
  mkdir -p "$scenario_root"

  echo "[m2][$scenario] validate: $spec"
  if ! python3 "$CLI" validate "$spec"; then
    echo "[m2][P0][$scenario] spec validate failed" >&2
    return 10
  fi

  echo "[m2][$scenario] run: bash \"$RUNNER\" --spec \"$spec\""
  local run_out=""
  if ! run_out=$(
    TENSOR_SI_RUN_ROOT="$scenario_root" bash "$RUNNER" --spec "$spec" 2>&1
  ); then
    echo "$run_out"
    echo "[m2][P1][$scenario] runner failed" >&2
    return 11
  fi
  echo "$run_out"

  local run_dir=""
  run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$run_dir" ]; then
    echo "[m2][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  local contract_args=()
  contract_args+=(--run-dir "$run_dir" --scenario "$scenario" --expect-tile --expect-collective)
  python3 "$M0_CONTRACT" "${contract_args[@]}"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    return "$rc"
  fi

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m2][P2][$scenario] missing summary: $summary" >&2
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

  echo "[m2][$scenario] PASS"
  return 0
}

SCENARIOS=(
  baseline_compat
  noc_capped_overlap_on
  noc_capped_overlap_off
  noc_capped_heavy_collective
  noc_capped_payload_first
)
SPECS=(
  "$SPEC_BASELINE"
  "$SPEC_ON"
  "$SPEC_OFF"
  "$SPEC_HEAVY"
  "$SPEC_PAYLOAD_FIRST"
)

FAIL_COUNT=0
for idx in "${!SCENARIOS[@]}"; do
  scenario="${SCENARIOS[$idx]}"
  spec="${SPECS[$idx]}"
  rc=0
  run_one "$scenario" "$spec" || rc=$?
  if [ "$rc" -ne 0 ]; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "[m2] FAIL scenario=$scenario rc=$rc" >&2
    if [ "$KEEP_GOING" != "1" ]; then
      exit "$rc"
    fi
  fi
done

if [ "$FAIL_COUNT" -ne 0 ]; then
  echo "[m2] FAIL: $FAIL_COUNT scenario(s) failed" >&2
  exit 13
fi

python3 "$TREND_VALIDATOR" \
  --baseline-compat "${RUN_DIRS[baseline_compat]}/essential_summary_tensor_mesh.json" \
  --noc-capped-overlap-on "${RUN_DIRS[noc_capped_overlap_on]}/essential_summary_tensor_mesh.json" \
  --noc-capped-overlap-off "${RUN_DIRS[noc_capped_overlap_off]}/essential_summary_tensor_mesh.json" \
  --noc-capped-heavy-collective "${RUN_DIRS[noc_capped_heavy_collective]}/essential_summary_tensor_mesh.json" \
  --noc-capped-payload-first "${RUN_DIRS[noc_capped_payload_first]}/essential_summary_tensor_mesh.json" \
  | tee "$REPORT_DIR/trend_validation.log"

echo "[m2] PASS"
echo "[m2] manifest: $MANIFEST"
cat "$MANIFEST"
