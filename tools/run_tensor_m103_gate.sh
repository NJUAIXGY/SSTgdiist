#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m103_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M103: memory arbitration v4 contract gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m103_gate）
  --skip-unit        跳过 M103 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m103_gate"
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
      echo "[m103] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m103_memory_arb_v4_contract.py"
SPEC_FAIR="$REPO_ROOT/tools/specs/tensor_m103_memory_arb_v4_fair.json"
SPEC_UNFAIR="$REPO_ROOT/tools/specs/tensor_m103_memory_arb_v4_unfair.json"

for p in "$CLI" "$RUNNER" "$M0_CONTRACT" "$VALIDATOR" "$SPEC_FAIR" "$SPEC_UNFAIR"
do
  if [ ! -f "$p" ]; then
    echo "[m103][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m103] run_root=\"$RUN_ROOT\""
echo "[m103] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m103] unit: python3 -m unittest tools/test_run_tensor_m103_gate.py sst_workloads/tensor_si/tools/test_validate_tensor_m103_memory_arb_v4_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m103_gate.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m103_memory_arb_v4_contract.py" \
    -v; then
    echo "[m103][P0] unit test gate failed" >&2
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
    echo "[m103][P1][$scenario] cannot parse run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m103][P2][$scenario] missing summary: $summary" >&2
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

mkdir -p "$RUN_ROOT/fair" "$RUN_ROOT/unfair"
sum_fair=$(run_one "fair" "$SPEC_FAIR" "$RUN_ROOT/fair") || exit $?
sum_unfair=$(run_one "unfair" "$SPEC_UNFAIR" "$RUN_ROOT/unfair") || exit $?

python3 "$VALIDATOR" --fair "$sum_fair" --unfair "$sum_unfair" --label "m103" | tee "$REPORT_DIR/validation.log"

echo "[m103] PASS"
echo "[m103] manifest: $MANIFEST"
echo "[m103] validation: $REPORT_DIR/validation.log"
