#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m51_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M51: trace-json -> tensor spec replay bridge gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m51_gate）
  --skip-unit        跳过 M51 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m51_gate"
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
      echo "[m51] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
COMPILER="$REPO_ROOT/sst_workloads/tensor_si/tools/compile_trace_json_to_tensor_spec.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m51_trace_replay_contract.py"
SCHEMA="$REPO_ROOT/tools/specs/tensor_trace_json_v1.schema.json"
TRACE_A="$REPO_ROOT/tools/specs/tensor_m51_trace_resnet_block_mock.json"
TRACE_B="$REPO_ROOT/tools/specs/tensor_m51_trace_transformer_block_mock.json"

for p in "$CLI" "$RUNNER" "$M0_CONTRACT" "$COMPILER" "$VALIDATOR" "$SCHEMA" "$TRACE_A" "$TRACE_B"
do
  if [ ! -f "$p" ]; then
    echo "[m51][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m51] run_root=\"$RUN_ROOT\""
echo "[m51] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m51] unit: python3 -m unittest tools/test_run_tensor_m51_gate.py sst_workloads/tensor_si/tools/test_compile_trace_json_to_tensor_spec.py sst_workloads/tensor_si/tools/test_validate_tensor_m51_trace_replay_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m51_gate.py" \
    "sst_workloads/tensor_si/tools/test_compile_trace_json_to_tensor_spec.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m51_trace_replay_contract.py" \
    -v; then
    echo "[m51][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local trace="$2"
  local scenario_root="$RUN_ROOT/$scenario"
  local scenario_dir="$REPORT_DIR/$scenario"
  mkdir -p "$scenario_dir"

  local compiled_spec="$scenario_dir/compiled_${scenario}.json"
  python3 "$COMPILER" --trace "$trace" --schema "$SCHEMA" --out "$compiled_spec" | tee "$scenario_dir/compile.log"

  python3 "$CLI" validate "$compiled_spec" | tee "$scenario_dir/spec_validate.log"

  local run_out=""
  run_out=$(
    TENSOR_SI_RUN_ROOT="$scenario_root" \
    TENSOR_SI_SST_NPROC=1 \
    SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst" \
    bash "$RUNNER" --spec "$compiled_spec" 2>&1
  )
  echo "$run_out" | tee "$scenario_dir/run.log"

  local run_dir=""
  run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$run_dir" ]; then
    echo "[m51][P1][$scenario] cannot parse run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "m51_${scenario}" | tee "$scenario_dir/m0_contract.log"

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m51][P2][$scenario] missing summary: $summary" >&2
    return 12
  fi

  python3 "$VALIDATOR" \
    --trace "$trace" \
    --spec "$compiled_spec" \
    --summary "$summary" \
    --label "m51_${scenario}" | tee "$scenario_dir/contract.log"

  {
    echo "scenario=$scenario"
    echo "trace=$trace"
    echo "compiled_spec=$compiled_spec"
    echo "run_dir=$run_dir"
    echo "summary=$summary"
    echo "---"
  } >> "$MANIFEST"
}

run_one "resnet" "$TRACE_A" || exit $?
run_one "transformer" "$TRACE_B" || exit $?

echo "[m51] PASS"
echo "[m51] manifest: $MANIFEST"
