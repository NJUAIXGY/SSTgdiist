#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m80_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M80: phase4 full regression orchestration for M71-M79

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m80_gate）
  --skip-unit        跳过 M80 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m80_gate"
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
      echo "[m80] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

AGGREGATE="$REPO_ROOT/sst_workloads/tensor_si/tools/aggregate_tensor_phase4_regression.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m80_phase4_report.py"

GATE_M71="$REPO_ROOT/tools/run_tensor_m71_gate.sh"
GATE_M72="$REPO_ROOT/tools/run_tensor_m72_gate.sh"
GATE_M73="$REPO_ROOT/tools/run_tensor_m73_gate.sh"
GATE_M74="$REPO_ROOT/tools/run_tensor_m74_gate.sh"
GATE_M75="$REPO_ROOT/tools/run_tensor_m75_gate.sh"
GATE_M76="$REPO_ROOT/tools/run_tensor_m76_gate.sh"
GATE_M77="$REPO_ROOT/tools/run_tensor_m77_gate.sh"
GATE_M78="$REPO_ROOT/tools/run_tensor_m78_gate.sh"
GATE_M79="$REPO_ROOT/tools/run_tensor_m79_gate.sh"

for p in "$AGGREGATE" "$VALIDATOR" "$GATE_M71" "$GATE_M72" "$GATE_M73" "$GATE_M74" "$GATE_M75" "$GATE_M76" "$GATE_M77" "$GATE_M78" "$GATE_M79"
do
  if [ ! -f "$p" ]; then
    echo "[m80][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

RESULTS_TSV="$REPORT_DIR/m80_results.tsv"
: > "$RESULTS_TSV"

echo "[m80] run_root=\"$RUN_ROOT\""
echo "[m80] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m80] unit: python3 -m unittest tools/test_run_tensor_m80_gate.py sst_workloads/tensor_si/tools/test_aggregate_tensor_phase4_regression.py sst_workloads/tensor_si/tools/test_validate_tensor_m80_phase4_report.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m80_gate.py" \
    "sst_workloads/tensor_si/tools/test_aggregate_tensor_phase4_regression.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m80_phase4_report.py" \
    -v; then
    echo "[m80][P0] unit test gate failed" >&2
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

run_one_gate "m71" "$GATE_M71"
run_one_gate "m72" "$GATE_M72"
run_one_gate "m73" "$GATE_M73"
run_one_gate "m74" "$GATE_M74"
run_one_gate "m75" "$GATE_M75"
run_one_gate "m76" "$GATE_M76"
run_one_gate "m77" "$GATE_M77"
run_one_gate "m78" "$GATE_M78"
run_one_gate "m79" "$GATE_M79"

M80_REPORT="$REPORT_DIR/m80_phase4_report.json"
python3 "$AGGREGATE" --results-file "$RESULTS_TSV" --out "$M80_REPORT" --label "m80" | tee "$REPORT_DIR/aggregate.log"

python3 "$VALIDATOR" \
  --report "$M80_REPORT" \
  --min-gates 9 \
  --required-gate m71 \
  --required-gate m72 \
  --required-gate m73 \
  --required-gate m74 \
  --required-gate m75 \
  --required-gate m76 \
  --required-gate m77 \
  --required-gate m78 \
  --required-gate m79 \
  --expect-pass 1 \
  --label "m80" | tee "$REPORT_DIR/validation.log"

{
  echo "results_tsv=$RESULTS_TSV"
  echo "report=$M80_REPORT"
  echo "validation=$REPORT_DIR/validation.log"
  echo "---"
} >> "$MANIFEST"

echo "[m80] PASS"
echo "[m80] manifest: $MANIFEST"
echo "[m80] report: $M80_REPORT"
echo "[m80] validation: $REPORT_DIR/validation.log"
