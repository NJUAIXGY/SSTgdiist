#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m15_gate.sh [--run-root <dir>] [--skip-unit]

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m15_gate）
  --skip-unit        跳过 M15 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m15_gate"
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
      echo "[m15] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
M15_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m15_residency_trends.py"

SPEC_A_ON_TPUV1="$REPO_ROOT/tools/specs/tensor_m15_keep_a_on_tpuv1_v3.json"
SPEC_A_OFF_TPUV1="$REPO_ROOT/tools/specs/tensor_m15_keep_a_off_tpuv1_v3.json"
SPEC_B_ON_TPUV1="$REPO_ROOT/tools/specs/tensor_m15_keep_b_on_tpuv1_v3.json"
SPEC_B_OFF_TPUV1="$REPO_ROOT/tools/specs/tensor_m15_keep_b_off_tpuv1_v3.json"

SPEC_A_ON_BF16="$REPO_ROOT/tools/specs/tensor_m15_keep_a_on_bf16_v3.json"
SPEC_A_OFF_BF16="$REPO_ROOT/tools/specs/tensor_m15_keep_a_off_bf16_v3.json"
SPEC_B_ON_BF16="$REPO_ROOT/tools/specs/tensor_m15_keep_b_on_bf16_v3.json"
SPEC_B_OFF_BF16="$REPO_ROOT/tools/specs/tensor_m15_keep_b_off_bf16_v3.json"

for p in \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$M15_VALIDATOR" \
  "$SPEC_A_ON_TPUV1" "$SPEC_A_OFF_TPUV1" "$SPEC_B_ON_TPUV1" "$SPEC_B_OFF_TPUV1" \
  "$SPEC_A_ON_BF16" "$SPEC_A_OFF_BF16" "$SPEC_B_ON_BF16" "$SPEC_B_OFF_BF16"
do
  if [ ! -f "$p" ]; then
    echo "[m15][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m15] run_root=\"$RUN_ROOT\""
echo "[m15] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m15] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m15_gate.py sst_workloads/tensor_si/test_tensor_spec.py snndl_system/test_builders.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_validate_tensor_m15_residency_trends.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m15_gate.py" \
    "sst_workloads/tensor_si/test_tensor_spec.py" \
    "snndl_system/test_builders.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m15_residency_trends.py" \
    -v; then
    echo "[m15][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$3"

  echo "[m15][$scenario] validate: $spec" >&2
  python3 "$CLI" validate "$spec" >&2

  echo "[m15][$scenario] run: bash \"$RUNNER\" --spec \"$spec\"" >&2
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
    echo "[m15][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" --expect-tile >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m15][P2][$scenario] missing summary: $summary" >&2
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

run_group() {
  local label="$1"
  local base_root="$2"
  local spec_a_on="$3"
  local spec_a_off="$4"
  local spec_b_on="$5"
  local spec_b_off="$6"

  mkdir -p "$base_root"

  local s_a_on="${label}_keep_a_on"
  local s_a_off="${label}_keep_a_off"
  local s_b_on="${label}_keep_b_on"
  local s_b_off="${label}_keep_b_off"

  local sum_a_on
  local sum_a_off
  local sum_b_on
  local sum_b_off

  sum_a_on=$(run_one "$s_a_on" "$spec_a_on" "$base_root/$s_a_on") || return $?
  sum_a_off=$(run_one "$s_a_off" "$spec_a_off" "$base_root/$s_a_off") || return $?
  sum_b_on=$(run_one "$s_b_on" "$spec_b_on" "$base_root/$s_b_on") || return $?
  sum_b_off=$(run_one "$s_b_off" "$spec_b_off" "$base_root/$s_b_off") || return $?

  python3 "$M15_VALIDATOR" \
    --keep-a-on "$sum_a_on" \
    --keep-a-off "$sum_a_off" \
    --keep-b-on "$sum_b_on" \
    --keep-b-off "$sum_b_off" \
    --label "$label" | tee "$REPORT_DIR/${label}_validation.log"
}

run_group "tpuv1" "$RUN_ROOT/tpuv1" "$SPEC_A_ON_TPUV1" "$SPEC_A_OFF_TPUV1" "$SPEC_B_ON_TPUV1" "$SPEC_B_OFF_TPUV1"
run_group "bf16" "$RUN_ROOT/bf16" "$SPEC_A_ON_BF16" "$SPEC_A_OFF_BF16" "$SPEC_B_ON_BF16" "$SPEC_B_OFF_BF16"

echo "[m15] PASS"
echo "[m15] manifest: $MANIFEST"
echo "[m15] validations: $REPORT_DIR/tpuv1_validation.log ; $REPORT_DIR/bf16_validation.log"
