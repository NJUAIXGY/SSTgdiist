#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m42_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M42: aggregate readiness regression + distance report gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m42_gate）
  --skip-unit        跳过 M42 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m42_gate"
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
      echo "[m42] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
M42_SUMMARY="$REPO_ROOT/sst_workloads/tensor_si/tools/summarize_tensor_npu_readiness.py"
M42_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m42_readiness_report.py"
SPEC_A="$REPO_ROOT/tools/specs/tensor_m37_capability_baseline_v3.json"
SPEC_B="$REPO_ROOT/tools/specs/tensor_m39_scheduler_aggressive_v3.json"
SPEC_C="$REPO_ROOT/tools/specs/tensor_m40_mem_profile_server_v3.json"
SPEC_D="$REPO_ROOT/tools/specs/tensor_m42_readiness_mix_v3.json"

for p in \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$M42_SUMMARY" "$M42_VALIDATOR" \
  "$SPEC_A" "$SPEC_B" "$SPEC_C" "$SPEC_D"
do
  if [ ! -f "$p" ]; then
    echo "[m42][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m42] run_root=\"$RUN_ROOT\""
echo "[m42] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m42] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m42_gate.py sst_workloads/tensor_si/test_tensor_spec.py snndl_system/test_builders.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_summarize_tensor_npu_readiness.py sst_workloads/tensor_si/tools/test_validate_tensor_m42_readiness_report.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m42_gate.py" \
    "sst_workloads/tensor_si/test_tensor_spec.py" \
    "snndl_system/test_builders.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_summarize_tensor_npu_readiness.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m42_readiness_report.py" \
    -v; then
    echo "[m42][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$3"

  echo "[m42][$scenario] validate: $spec" >&2
  python3 "$CLI" validate "$spec" >&2

  echo "[m42][$scenario] run: bash \"$RUNNER\" --spec \"$spec\"" >&2
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
    echo "[m42][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m42][P2][$scenario] missing summary: $summary" >&2
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

mkdir -p "$RUN_ROOT/scenario_a" "$RUN_ROOT/scenario_b" "$RUN_ROOT/scenario_c" "$RUN_ROOT/scenario_d"

sum_a=$(run_one "capability_baseline" "$SPEC_A" "$RUN_ROOT/scenario_a") || exit $?
sum_b=$(run_one "scheduler_aggressive" "$SPEC_B" "$RUN_ROOT/scenario_b") || exit $?
sum_c=$(run_one "mem_profile_server" "$SPEC_C" "$RUN_ROOT/scenario_c") || exit $?
sum_d=$(run_one "readiness_mix" "$SPEC_D" "$RUN_ROOT/scenario_d") || exit $?

REPORT_JSON="$REPORT_DIR/m42_readiness_report.json"
python3 "$M42_SUMMARY" \
  --summary "$sum_a" \
  --summary "$sum_b" \
  --summary "$sum_c" \
  --summary "$sum_d" \
  --out "$REPORT_JSON" | tee "$REPORT_DIR/summary.log"

python3 "$M42_VALIDATOR" --report "$REPORT_JSON" --min-scenarios 3 --label "m42" | tee "$REPORT_DIR/validation.log"

echo "[m42] PASS"
echo "[m42] manifest: $MANIFEST"
echo "[m42] report: $REPORT_JSON"
echo "[m42] validation: $REPORT_DIR/validation.log"
