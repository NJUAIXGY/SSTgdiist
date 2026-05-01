#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m41_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M41: calibration workflow standardization gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m41_gate）
  --skip-unit        跳过 M41 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m41_gate"
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
      echo "[m41] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
M41_CALIB="$REPO_ROOT/sst_workloads/tensor_si/tools/calibrate_tensor_memory_profile.py"
M41_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m41_calibration_profile.py"
SPEC_BASE="$REPO_ROOT/tools/specs/tensor_m41_calib_baseline_simple_v3.json"
SPEC_TARGET="$REPO_ROOT/tools/specs/tensor_m41_calib_target_ram2_v3.json"

for p in \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$M41_CALIB" "$M41_VALIDATOR" "$SPEC_BASE" "$SPEC_TARGET"
do
  if [ ! -f "$p" ]; then
    echo "[m41][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m41] run_root=\"$RUN_ROOT\""
echo "[m41] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m41] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m41_gate.py sst_workloads/tensor_si/test_tensor_spec.py snndl_system/test_builders.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_calibrate_tensor_memory_profile.py sst_workloads/tensor_si/tools/test_validate_tensor_m41_calibration_profile.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m41_gate.py" \
    "sst_workloads/tensor_si/test_tensor_spec.py" \
    "snndl_system/test_builders.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_calibrate_tensor_memory_profile.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m41_calibration_profile.py" \
    -v; then
    echo "[m41][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$3"

  echo "[m41][$scenario] validate: $spec" >&2
  python3 "$CLI" validate "$spec" >&2

  echo "[m41][$scenario] run: bash \"$RUNNER\" --spec \"$spec\"" >&2
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
    echo "[m41][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m41][P2][$scenario] missing summary: $summary" >&2
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

mkdir -p "$RUN_ROOT/baseline" "$RUN_ROOT/target"

sum_base=$(run_one "baseline" "$SPEC_BASE" "$RUN_ROOT/baseline") || exit $?
sum_target=$(run_one "target" "$SPEC_TARGET" "$RUN_ROOT/target") || exit $?

PROFILE_JSON="$REPORT_DIR/calibration_profile.json"
python3 "$M41_CALIB" --baseline "$sum_base" --target "$sum_target" --out "$PROFILE_JSON" --tag "m41_calib_v1" | tee "$REPORT_DIR/calibration.log"
python3 "$M41_VALIDATOR" --profile "$PROFILE_JSON" --baseline "$sum_base" --target "$sum_target" --label "m41" | tee "$REPORT_DIR/validation.log"

echo "[m41] PASS"
echo "[m41] manifest: $MANIFEST"
echo "[m41] calibration: $PROFILE_JSON"
echo "[m41] validation: $REPORT_DIR/validation.log"
