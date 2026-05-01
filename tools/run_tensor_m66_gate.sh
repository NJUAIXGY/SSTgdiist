#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m66_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M66: readiness-v3 report contract gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m66_gate）
  --skip-unit        跳过 M66 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m66_gate"
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
      echo "[m66] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
SUMMARIZER="$REPO_ROOT/sst_workloads/tensor_si/tools/summarize_tensor_npu_readiness_v3.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m66_readiness_v3_contract.py"
SPEC_CFG="$REPO_ROOT/tools/specs/tensor_m66_readiness_v3_config_only.json"
SPEC_RICH="$REPO_ROOT/tools/specs/tensor_m66_readiness_v3_evidence_rich.json"

for p in "$CLI" "$RUNNER" "$M0_CONTRACT" "$SUMMARIZER" "$VALIDATOR" "$SPEC_CFG" "$SPEC_RICH"
do
  if [ ! -f "$p" ]; then
    echo "[m66][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m66] run_root=\"$RUN_ROOT\""
echo "[m66] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m66] unit: python3 -m unittest tools/test_run_tensor_m66_gate.py sst_workloads/tensor_si/tools/test_summarize_tensor_npu_readiness_v3.py sst_workloads/tensor_si/tools/test_validate_tensor_m66_readiness_v3_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m66_gate.py" \
    "sst_workloads/tensor_si/tools/test_summarize_tensor_npu_readiness_v3.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m66_readiness_v3_contract.py" \
    -v; then
    echo "[m66][P0] unit test gate failed" >&2
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
    echo "[m66][P1][$scenario] cannot parse run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m66][P2][$scenario] missing summary: $summary" >&2
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

mkdir -p "$RUN_ROOT/config_only" "$RUN_ROOT/evidence_rich"
sum_cfg=$(run_one "config_only" "$SPEC_CFG" "$RUN_ROOT/config_only") || exit $?
sum_rich=$(run_one "evidence_rich" "$SPEC_RICH" "$RUN_ROOT/evidence_rich") || exit $?

REPORT_JSON="$REPORT_DIR/readiness_v3_report.json"
python3 "$SUMMARIZER" --summary "$sum_cfg" --summary "$sum_rich" --out "$REPORT_JSON" | tee "$REPORT_DIR/summarize.log"
python3 "$VALIDATOR" --report "$REPORT_JSON" --min-scenarios 2 --expect-interventions 1 --label "m66" | tee "$REPORT_DIR/validation.log"

echo "[m66] PASS"
echo "[m66] manifest: $MANIFEST"
echo "[m66] report: $REPORT_JSON"
echo "[m66] validation: $REPORT_DIR/validation.log"
