#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m10_gate.sh [--run-root <dir>] [--skip-unit] [--keep-going]

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m10_gate）
  --skip-unit        跳过 M10 轻量单测集合
  --keep-going       某场景失败后继续跑后续场景（默认失败即停）
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m10_gate"
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
      echo "[m10] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SPEC_CHUNKS="$REPO_ROOT/tools/specs/tensor_m10_credit_chunks_v3.json"
SPEC_PKTS_ALIAS="$REPO_ROOT/tools/specs/tensor_m10_credit_pkts_alias_v3.json"

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
ALIAS_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m10_pkts_alias.py"

for p in \
  "$SPEC_CHUNKS" "$SPEC_PKTS_ALIAS" \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$ALIAS_VALIDATOR"
do
  if [ ! -f "$p" ]; then
    echo "[m10][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m10] run_root=\"$RUN_ROOT\""
echo "[m10] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m10] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m10_gate.py sst_workloads/tensor_si/test_tensor_spec.py snndl_system/test_builders.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_validate_tensor_m10_pkts_alias.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m10_gate.py" \
    "sst_workloads/tensor_si/test_tensor_spec.py" \
    "snndl_system/test_builders.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m10_pkts_alias.py" \
    -v; then
    echo "[m10][P0] unit test gate failed" >&2
    exit 10
  fi
fi

declare -A RUN_DIRS=()

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$RUN_ROOT/$scenario"
  mkdir -p "$scenario_root"

  echo "[m10][$scenario] validate: $spec"
  if ! python3 "$CLI" validate "$spec"; then
    echo "[m10][P0][$scenario] spec validate failed" >&2
    return 10
  fi

  echo "[m10][$scenario] run: bash \"$RUNNER\" --spec \"$spec\""
  local run_out=""
  if ! run_out=$(
    TENSOR_SI_RUN_ROOT="$scenario_root" bash "$RUNNER" --spec "$spec" 2>&1
  ); then
    echo "$run_out"
    echo "[m10][P1][$scenario] runner failed" >&2
    return 11
  fi
  echo "$run_out"

  local run_dir=""
  run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$run_dir" ]; then
    echo "[m10][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" --expect-collective --allow-zero-mac
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    return "$rc"
  fi

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m10][P2][$scenario] missing summary: $summary" >&2
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

  echo "[m10][$scenario] PASS"
  return 0
}

SCENARIOS=(
  chunks
  pkts_alias
)
SPECS=(
  "$SPEC_CHUNKS"
  "$SPEC_PKTS_ALIAS"
)

FAIL_COUNT=0
for idx in "${!SCENARIOS[@]}"; do
  scenario="${SCENARIOS[$idx]}"
  spec="${SPECS[$idx]}"
  rc=0
  run_one "$scenario" "$spec" || rc=$?
  if [ "$rc" -ne 0 ]; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "[m10] FAIL scenario=$scenario rc=$rc" >&2
    if [ "$KEEP_GOING" != "1" ]; then
      exit "$rc"
    fi
  fi
done

if [ "$FAIL_COUNT" -ne 0 ]; then
  echo "[m10] FAIL: $FAIL_COUNT scenario(s) failed" >&2
  exit 13
fi

python3 "$ALIAS_VALIDATOR" \
  --chunks "${RUN_DIRS[chunks]}/essential_summary_tensor_mesh.json" \
  --pkts-alias "${RUN_DIRS[pkts_alias]}/essential_summary_tensor_mesh.json" \
  | tee "$REPORT_DIR/alias_validation.log"

echo "[m10] PASS"
echo "[m10] manifest: $MANIFEST"
echo "[m10] alias_validation: $REPORT_DIR/alias_validation.log"

