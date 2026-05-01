#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m60_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M60: energy+RAS phase2 contract gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m60_gate）
  --skip-unit        跳过 M60 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m60_gate"
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
      echo "[m60] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m60_energy_ras_phase2_contract.py"
SPEC_EFF="$REPO_ROOT/tools/specs/tensor_m60_energy_efficiency_v3.json"
SPEC_FAULT="$REPO_ROOT/tools/specs/tensor_m60_fault_injection_v3.json"
SPEC_RECOVERY="$REPO_ROOT/tools/specs/tensor_m60_fault_recovery_v3.json"

for p in "$CLI" "$RUNNER" "$M0_CONTRACT" "$VALIDATOR" "$SPEC_EFF" "$SPEC_FAULT" "$SPEC_RECOVERY"
do
  if [ ! -f "$p" ]; then
    echo "[m60][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m60] run_root=\"$RUN_ROOT\""
echo "[m60] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m60] unit: python3 -m unittest tools/test_run_tensor_m60_gate.py sst_workloads/tensor_si/tools/test_validate_tensor_m60_energy_ras_phase2_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m60_gate.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m60_energy_ras_phase2_contract.py" \
    -v; then
    echo "[m60][P0] unit test gate failed" >&2
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
    echo "[m60][P1][$scenario] cannot parse run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m60][P2][$scenario] missing summary: $summary" >&2
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

mkdir -p "$RUN_ROOT/efficiency" "$RUN_ROOT/fault" "$RUN_ROOT/recovery"
sum_eff=$(run_one "efficiency" "$SPEC_EFF" "$RUN_ROOT/efficiency") || exit $?
sum_fault=$(run_one "fault" "$SPEC_FAULT" "$RUN_ROOT/fault") || exit $?
sum_recovery=$(run_one "recovery" "$SPEC_RECOVERY" "$RUN_ROOT/recovery") || exit $?

python3 "$VALIDATOR" --efficiency "$sum_eff" --fault "$sum_fault" --recovery "$sum_recovery" --label "m60" | tee "$REPORT_DIR/validation.log"

echo "[m60] PASS"
echo "[m60] manifest: $MANIFEST"
echo "[m60] validation: $REPORT_DIR/validation.log"
