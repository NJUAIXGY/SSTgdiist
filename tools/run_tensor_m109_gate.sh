#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m109_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M109: RAS policy v4 contract gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m109_gate）
  --skip-unit        跳过 M109 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m109_gate"
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
      echo "[m109] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m109_ras_policy_v4_contract.py"
SPEC_RETRY="$REPO_ROOT/tools/specs/tensor_m109_ras_retry_v4.json"
SPEC_THROTTLE="$REPO_ROOT/tools/specs/tensor_m109_ras_throttle_v4.json"
SPEC_ISOLATE="$REPO_ROOT/tools/specs/tensor_m109_ras_isolate_v4.json"
SPEC_HYBRID="$REPO_ROOT/tools/specs/tensor_m109_ras_hybrid_v4.json"

for p in "$CLI" "$RUNNER" "$M0_CONTRACT" "$VALIDATOR" "$SPEC_RETRY" "$SPEC_THROTTLE" "$SPEC_ISOLATE" "$SPEC_HYBRID"
do
  if [ ! -f "$p" ]; then
    echo "[m109][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m109] run_root=\"$RUN_ROOT\""
echo "[m109] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m109] unit: python3 -m unittest tools/test_run_tensor_m109_gate.py sst_workloads/tensor_si/tools/test_validate_tensor_m109_ras_policy_v4_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m109_gate.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m109_ras_policy_v4_contract.py" \
    -v; then
    echo "[m109][P0] unit test gate failed" >&2
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
    echo "[m109][P1][$scenario] cannot parse run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m109][P2][$scenario] missing summary: $summary" >&2
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

mkdir -p "$RUN_ROOT/retry" "$RUN_ROOT/throttle" "$RUN_ROOT/isolate" "$RUN_ROOT/hybrid"
sum_retry=$(run_one "retry" "$SPEC_RETRY" "$RUN_ROOT/retry") || exit $?
sum_throttle=$(run_one "throttle" "$SPEC_THROTTLE" "$RUN_ROOT/throttle") || exit $?
sum_isolate=$(run_one "isolate" "$SPEC_ISOLATE" "$RUN_ROOT/isolate") || exit $?
sum_hybrid=$(run_one "hybrid" "$SPEC_HYBRID" "$RUN_ROOT/hybrid") || exit $?

python3 "$VALIDATOR" \
  --retry "$sum_retry" \
  --throttle "$sum_throttle" \
  --isolate "$sum_isolate" \
  --hybrid "$sum_hybrid" \
  --label "m109" | tee "$REPORT_DIR/validation.log"

echo "[m109] PASS"
echo "[m109] manifest: $MANIFEST"
echo "[m109] validation: $REPORT_DIR/validation.log"
