#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m16_gate.sh [--run-root <dir>] [--skip-unit]

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m16_gate）
  --skip-unit        跳过 M16 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m16_gate"
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
      echo "[m16] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
M16_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m16_wavefront_trends.py"

SPEC_OFF_TPUV1="$REPO_ROOT/tools/specs/tensor_m16_wavefront_off_tpuv1_v3.json"
SPEC_ON_TPUV1="$REPO_ROOT/tools/specs/tensor_m16_wavefront_on_tpuv1_v3.json"
SPEC_OFF_BF16="$REPO_ROOT/tools/specs/tensor_m16_wavefront_off_bf16_v3.json"
SPEC_ON_BF16="$REPO_ROOT/tools/specs/tensor_m16_wavefront_on_bf16_v3.json"

for p in \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$M16_VALIDATOR" \
  "$SPEC_OFF_TPUV1" "$SPEC_ON_TPUV1" "$SPEC_OFF_BF16" "$SPEC_ON_BF16"
do
  if [ ! -f "$p" ]; then
    echo "[m16][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m16] run_root=\"$RUN_ROOT\""
echo "[m16] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m16] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m16_gate.py sst_workloads/tensor_si/test_tensor_spec.py snndl_system/test_builders.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_validate_tensor_m16_wavefront_trends.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m16_gate.py" \
    "sst_workloads/tensor_si/test_tensor_spec.py" \
    "snndl_system/test_builders.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m16_wavefront_trends.py" \
    -v; then
    echo "[m16][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$3"

  echo "[m16][$scenario] validate: $spec" >&2
  python3 "$CLI" validate "$spec" >&2

  echo "[m16][$scenario] run: bash \"$RUNNER\" --spec \"$spec\"" >&2
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
    echo "[m16][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" --expect-tile >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m16][P2][$scenario] missing summary: $summary" >&2
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

run_pair() {
  local label="$1"
  local base_root="$2"
  local spec_off="$3"
  local spec_on="$4"
  mkdir -p "$base_root"

  local sum_off
  local sum_on
  sum_off=$(run_one "${label}_off" "$spec_off" "$base_root/${label}_off") || return $?
  sum_on=$(run_one "${label}_on" "$spec_on" "$base_root/${label}_on") || return $?

  python3 "$M16_VALIDATOR" --off "$sum_off" --on "$sum_on" --label "$label" | tee "$REPORT_DIR/${label}_validation.log"
}

run_pair "tpuv1" "$RUN_ROOT/tpuv1" "$SPEC_OFF_TPUV1" "$SPEC_ON_TPUV1"
run_pair "bf16" "$RUN_ROOT/bf16" "$SPEC_OFF_BF16" "$SPEC_ON_BF16"

echo "[m16] PASS"
echo "[m16] manifest: $MANIFEST"
echo "[m16] validations: $REPORT_DIR/tpuv1_validation.log ; $REPORT_DIR/bf16_validation.log"
