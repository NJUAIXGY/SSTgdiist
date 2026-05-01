#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m31_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M31: memory latency observability trend gate (simpleMem vs ramulator2)

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m31_gate）
  --skip-unit        跳过 M31 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m31_gate"
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
      echo "[m31] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
M31_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m31_mem_latency_trends.py"

# Reuse the canonical simple-vs-ram2 specs; M31 is about new observability signals.
SPEC_SIMPLE="$REPO_ROOT/tools/specs/tensor_m25_mem_backend_simple_v3.json"
SPEC_RAM2="$REPO_ROOT/tools/specs/tensor_m25_mem_backend_ram2_v3.json"

for p in \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$M31_VALIDATOR" \
  "$SPEC_SIMPLE" "$SPEC_RAM2"
do
  if [ ! -f "$p" ]; then
    echo "[m31][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m31] run_root=\"$RUN_ROOT\""
echo "[m31] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m31] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m31_gate.py sst_workloads/tensor_si/test_tensor_spec.py snndl_system/test_builders.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_validate_tensor_m31_mem_latency_trends.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m31_gate.py" \
    "sst_workloads/tensor_si/test_tensor_spec.py" \
    "snndl_system/test_builders.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m31_mem_latency_trends.py" \
    -v; then
    echo "[m31][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$3"

  echo "[m31][$scenario] validate: $spec" >&2
  python3 "$CLI" validate "$spec" >&2

  echo "[m31][$scenario] run: bash \"$RUNNER\" --spec \"$spec\"" >&2
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
    echo "[m31][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m31][P2][$scenario] missing summary: $summary" >&2
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

mkdir -p "$RUN_ROOT/simple" "$RUN_ROOT/ram2"

sum_simple=$(run_one "simple" "$SPEC_SIMPLE" "$RUN_ROOT/simple") || exit $?
sum_ram2=$(run_one "ram2" "$SPEC_RAM2" "$RUN_ROOT/ram2") || exit $?

python3 "$M31_VALIDATOR" \
  --simple "$sum_simple" \
  --ram2 "$sum_ram2" \
  --label "m31" | tee "$REPORT_DIR/validation.log"

echo "[m31] PASS"
echo "[m31] manifest: $MANIFEST"
echo "[m31] validation: $REPORT_DIR/validation.log"

