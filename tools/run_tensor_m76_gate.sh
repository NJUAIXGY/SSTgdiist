#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m76_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M76: calibration loop v3 contract gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m76_gate）
  --skip-unit        跳过 M76 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m76_gate"
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
      echo "[m76] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
FITTER="$REPO_ROOT/sst_workloads/tensor_si/tools/fit_tensor_calibration_from_evidence.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m76_calibration_loop_v3_contract.py"
SPEC_BASE="$REPO_ROOT/tools/specs/tensor_m76_calib_loop_baseline_v3.json"
SPEC_TARGET="$REPO_ROOT/tools/specs/tensor_m76_calib_loop_target_v3.json"
REF_PROFILE="$REPO_ROOT/tools/specs/tensor_m76_reference_profiles_v3.json"

for p in "$CLI" "$RUNNER" "$M0_CONTRACT" "$FITTER" "$VALIDATOR" "$SPEC_BASE" "$SPEC_TARGET" "$REF_PROFILE"
do
  if [ ! -f "$p" ]; then
    echo "[m76][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m76] run_root=\"$RUN_ROOT\""
echo "[m76] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m76] unit: python3 -m unittest tools/test_run_tensor_m76_gate.py sst_workloads/tensor_si/tools/test_fit_tensor_calibration_from_evidence.py sst_workloads/tensor_si/tools/test_validate_tensor_m76_calibration_loop_v3_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m76_gate.py" \
    "sst_workloads/tensor_si/tools/test_fit_tensor_calibration_from_evidence.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m76_calibration_loop_v3_contract.py" \
    -v; then
    echo "[m76][P0] unit test gate failed" >&2
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
    echo "[m76][P1][$scenario] cannot parse run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m76][P2][$scenario] missing summary: $summary" >&2
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

PROFILE_JSON="$REPORT_DIR/m76_calibration_loop_profile.json"
python3 "$FITTER" \
  --baseline "$sum_base" \
  --target "$sum_target" \
  --reference "$REF_PROFILE" \
  --out "$PROFILE_JSON" \
  --tag "m76_calibration_loop_v3" | tee "$REPORT_DIR/fit.log"

python3 "$VALIDATOR" \
  --profile "$PROFILE_JSON" \
  --baseline "$sum_base" \
  --target "$sum_target" \
  --reference "$REF_PROFILE" \
  --expect-pass 1 \
  --label "m76" | tee "$REPORT_DIR/validation.log"

echo "[m76] PASS"
echo "[m76] manifest: $MANIFEST"
echo "[m76] profile: $PROFILE_JSON"
echo "[m76] validation: $REPORT_DIR/validation.log"
