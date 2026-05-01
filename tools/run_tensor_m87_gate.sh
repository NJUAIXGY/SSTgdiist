#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m87_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M87: scale-out v2 contract gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m87_gate）
  --skip-unit        跳过 M87 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m87_gate"
RUN_ROOT="$RUN_ROOT_DEFAULT"
SKIP_UNIT=0

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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[m87] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m87_scaleout_v2_contract.py"
SPEC_SINGLE="$REPO_ROOT/tools/specs/tensor_m87_scaleout_v2_single.json"
SPEC_MULTI="$REPO_ROOT/tools/specs/tensor_m87_scaleout_v2_multi.json"

for p in "$CLI" "$RUNNER" "$M0_CONTRACT" "$VALIDATOR" "$SPEC_SINGLE" "$SPEC_MULTI"
do
  if [ ! -f "$p" ]; then
    echo "[m87][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m87] run_root=\"$RUN_ROOT\""
echo "[m87] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m87] unit: python3 -m unittest tools/test_run_tensor_m87_gate.py sst_workloads/tensor_si/tools/test_validate_tensor_m87_scaleout_v2_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m87_gate.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m87_scaleout_v2_contract.py" \
    -v; then
    echo "[m87][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$3"

  python3 "$CLI" validate "$spec" >&2
  local run_out=""
  run_out=$(
    TENSOR_SI_RUN_ROOT="$scenario_root" \
    TENSOR_SI_SST_NPROC=1 \
    SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst" \
    bash "$RUNNER" --spec "$spec" 2>&1
  )
  echo "$run_out" >&2

  local run_dir=""
  run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$run_dir" ]; then
    echo "[m87][P1][$scenario] cannot parse run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m87][P2][$scenario] missing summary: $summary" >&2
    return 12
  fi

  {
    echo "scenario=$scenario"
    echo "spec=$spec"
    echo "run_dir=$run_dir"
    echo "summary=$summary"
    echo "---"
  } >> "$MANIFEST"

  echo "$summary"
}

mkdir -p "$RUN_ROOT/single" "$RUN_ROOT/multi"
sum_single=$(run_one "single" "$SPEC_SINGLE" "$RUN_ROOT/single") || exit $?
sum_multi=$(run_one "multi" "$SPEC_MULTI" "$RUN_ROOT/multi") || exit $?

python3 "$VALIDATOR" --single "$sum_single" --multi "$sum_multi" --label "m87" | tee "$REPORT_DIR/validation.log"

echo "[m87] PASS"
echo "[m87] manifest: $MANIFEST"
echo "[m87] validation: $REPORT_DIR/validation.log"
