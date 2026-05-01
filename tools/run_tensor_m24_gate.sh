#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m24_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M24: memHierarchy multi-MemController channels + addr interleave(swizzle) trend gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m24_gate）
  --skip-unit        跳过 M24 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m24_gate"
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
      echo "[m24] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
M24_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m24_memctrl_channels_trends.py"

SPEC_CH1="$REPO_ROOT/tools/specs/tensor_m24_memctrl_channels_1ch_v3.json"
SPEC_CH4="$REPO_ROOT/tools/specs/tensor_m24_memctrl_channels_4ch_v3.json"
SPEC_HOT="$REPO_ROOT/tools/specs/tensor_m24_memctrl_interleave_hot_v3.json"
SPEC_SPREAD="$REPO_ROOT/tools/specs/tensor_m24_memctrl_interleave_spread_v3.json"

for p in \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$M24_VALIDATOR" \
  "$SPEC_CH1" "$SPEC_CH4" "$SPEC_HOT" "$SPEC_SPREAD"
do
  if [ ! -f "$p" ]; then
    echo "[m24][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m24] run_root=\"$RUN_ROOT\""
echo "[m24] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m24] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m24_gate.py sst_workloads/tensor_si/test_tensor_spec.py snndl_system/test_builders.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_validate_tensor_m24_memctrl_channels_trends.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m24_gate.py" \
    "sst_workloads/tensor_si/test_tensor_spec.py" \
    "snndl_system/test_builders.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m24_memctrl_channels_trends.py" \
    -v; then
    echo "[m24][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$3"

  echo "[m24][$scenario] validate: $spec" >&2
  python3 "$CLI" validate "$spec" >&2

  echo "[m24][$scenario] run: bash \"$RUNNER\" --spec \"$spec\"" >&2
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
    echo "[m24][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m24][P2][$scenario] missing summary: $summary" >&2
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

mkdir -p "$RUN_ROOT/ch1" "$RUN_ROOT/ch4" "$RUN_ROOT/hot" "$RUN_ROOT/spread"

sum_ch1=$(run_one "ch1" "$SPEC_CH1" "$RUN_ROOT/ch1") || exit $?
sum_ch4=$(run_one "ch4" "$SPEC_CH4" "$RUN_ROOT/ch4") || exit $?
sum_hot=$(run_one "hot" "$SPEC_HOT" "$RUN_ROOT/hot") || exit $?
sum_spread=$(run_one "spread" "$SPEC_SPREAD" "$RUN_ROOT/spread") || exit $?

python3 "$M24_VALIDATOR" \
  --ch1 "$sum_ch1" \
  --ch4 "$sum_ch4" \
  --hot "$sum_hot" \
  --spread "$sum_spread" \
  --label "m24" | tee "$REPORT_DIR/validation.log"

echo "[m24] PASS"
echo "[m24] manifest: $MANIFEST"
echo "[m24] validation: $REPORT_DIR/validation.log"

