#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m90_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M90: phase5 full regression orchestration for M81-M89

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m90_gate）
  --skip-unit        跳过 M90 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m90_gate"
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
      echo "[m90] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

AGGREGATE="$REPO_ROOT/sst_workloads/tensor_si/tools/aggregate_tensor_phase5_regression.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m90_phase5_report.py"

GATE_M81="$REPO_ROOT/tools/run_tensor_m81_gate.sh"
GATE_M82="$REPO_ROOT/tools/run_tensor_m82_gate.sh"
GATE_M83="$REPO_ROOT/tools/run_tensor_m83_gate.sh"
GATE_M84="$REPO_ROOT/tools/run_tensor_m84_gate.sh"
GATE_M85="$REPO_ROOT/tools/run_tensor_m85_gate.sh"
GATE_M86="$REPO_ROOT/tools/run_tensor_m86_gate.sh"
GATE_M87="$REPO_ROOT/tools/run_tensor_m87_gate.sh"
GATE_M88="$REPO_ROOT/tools/run_tensor_m88_gate.sh"
GATE_M89="$REPO_ROOT/tools/run_tensor_m89_gate.sh"

for p in "$AGGREGATE" "$VALIDATOR" "$GATE_M81" "$GATE_M82" "$GATE_M83" "$GATE_M84" "$GATE_M85" "$GATE_M86" "$GATE_M87" "$GATE_M88" "$GATE_M89"
do
  if [ ! -f "$p" ]; then
    echo "[m90][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

RESULTS_TSV="$REPORT_DIR/m90_results.tsv"
: > "$RESULTS_TSV"

echo "[m90] run_root=\"$RUN_ROOT\""
echo "[m90] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m90] unit: python3 -m unittest tools/test_run_tensor_m90_gate.py sst_workloads/tensor_si/tools/test_aggregate_tensor_phase5_regression.py sst_workloads/tensor_si/tools/test_validate_tensor_m90_phase5_report.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m90_gate.py" \
    "sst_workloads/tensor_si/tools/test_aggregate_tensor_phase5_regression.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m90_phase5_report.py" \
    -v; then
    echo "[m90][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one_gate() {
  local gate_id="$1"
  local gate_script="$2"
  local gate_root="$RUN_ROOT/$gate_id"
  local gate_log="$REPORT_DIR/${gate_id}.log"

  local out=""
  local status="pass"
  if ! out=$(bash "$gate_script" --skip-unit --run-root "$gate_root" 2>&1); then
    status="fail"
  fi
  echo "$out" | tee "$gate_log"

  local gate_report_dir=""
  gate_report_dir=$(echo "$out" | sed -n 's/^\[m[0-9]\+\] report_dir="\([^"]*\)"/\1/p' | tail -n 1)

  printf '%s\t%s\t%s\t%s\n' "$gate_id" "$status" "$gate_report_dir" "$gate_log" >> "$RESULTS_TSV"

  {
    echo "gate=$gate_id"
    echo "status=$status"
    echo "report_dir=$gate_report_dir"
    echo "log=$gate_log"
    echo "---"
  } >> "$MANIFEST"
}

run_one_gate "m81" "$GATE_M81"
run_one_gate "m82" "$GATE_M82"
run_one_gate "m83" "$GATE_M83"
run_one_gate "m84" "$GATE_M84"
run_one_gate "m85" "$GATE_M85"
run_one_gate "m86" "$GATE_M86"
run_one_gate "m87" "$GATE_M87"
run_one_gate "m88" "$GATE_M88"
run_one_gate "m89" "$GATE_M89"

M90_REPORT="$REPORT_DIR/m90_phase5_report.json"
python3 "$AGGREGATE" --results-file "$RESULTS_TSV" --out "$M90_REPORT" --label "m90" | tee "$REPORT_DIR/aggregate.log"

python3 "$VALIDATOR" \
  --report "$M90_REPORT" \
  --min-gates 9 \
  --required-gate m81 \
  --required-gate m82 \
  --required-gate m83 \
  --required-gate m84 \
  --required-gate m85 \
  --required-gate m86 \
  --required-gate m87 \
  --required-gate m88 \
  --required-gate m89 \
  --expect-pass 1 \
  --label "m90" | tee "$REPORT_DIR/validation.log"

{
  echo "results_tsv=$RESULTS_TSV"
  echo "report=$M90_REPORT"
  echo "validation=$REPORT_DIR/validation.log"
  echo "---"
} >> "$MANIFEST"

echo "[m90] PASS"
echo "[m90] manifest: $MANIFEST"
echo "[m90] report: $M90_REPORT"
echo "[m90] validation: $REPORT_DIR/validation.log"
