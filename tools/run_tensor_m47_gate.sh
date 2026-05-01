#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m47_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M47: full regression orchestration for M37-M46

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m47_gate）
  --skip-unit        跳过 M47 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m47_gate"
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
      echo "[m47] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

AGGREGATE="$REPO_ROOT/sst_workloads/tensor_si/tools/aggregate_tensor_full_regression.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m47_full_regression_report.py"

GATE_M37="$REPO_ROOT/tools/run_tensor_m37_gate.sh"
GATE_M38="$REPO_ROOT/tools/run_tensor_m38_gate.sh"
GATE_M39="$REPO_ROOT/tools/run_tensor_m39_gate.sh"
GATE_M40="$REPO_ROOT/tools/run_tensor_m40_gate.sh"
GATE_M41="$REPO_ROOT/tools/run_tensor_m41_gate.sh"
GATE_M42="$REPO_ROOT/tools/run_tensor_m42_gate.sh"
GATE_M43="$REPO_ROOT/tools/run_tensor_m43_gate.sh"
GATE_M44="$REPO_ROOT/tools/run_tensor_m44_gate.sh"
GATE_M45="$REPO_ROOT/tools/run_tensor_m45_gate.sh"
GATE_M46="$REPO_ROOT/tools/run_tensor_m46_gate.sh"

for p in \
  "$AGGREGATE" "$VALIDATOR" \
  "$GATE_M37" "$GATE_M38" "$GATE_M39" "$GATE_M40" "$GATE_M41" \
  "$GATE_M42" "$GATE_M43" "$GATE_M44" "$GATE_M45" "$GATE_M46"
do
  if [ ! -f "$p" ]; then
    echo "[m47][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

RESULTS_TSV="$REPORT_DIR/m47_results.tsv"
: > "$RESULTS_TSV"

echo "[m47] run_root=\"$RUN_ROOT\""
echo "[m47] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m47] unit: python3 -m unittest tools/test_run_tensor_m47_gate.py sst_workloads/tensor_si/tools/test_aggregate_tensor_full_regression.py sst_workloads/tensor_si/tools/test_validate_tensor_m47_full_regression_report.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m47_gate.py" \
    "sst_workloads/tensor_si/tools/test_aggregate_tensor_full_regression.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m47_full_regression_report.py" \
    -v; then
    echo "[m47][P0] unit test gate failed" >&2
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

run_one_gate "m37" "$GATE_M37"
run_one_gate "m38" "$GATE_M38"
run_one_gate "m39" "$GATE_M39"
run_one_gate "m40" "$GATE_M40"
run_one_gate "m41" "$GATE_M41"
run_one_gate "m42" "$GATE_M42"
run_one_gate "m43" "$GATE_M43"
run_one_gate "m44" "$GATE_M44"
run_one_gate "m45" "$GATE_M45"
run_one_gate "m46" "$GATE_M46"

M47_REPORT="$REPORT_DIR/m47_full_regression_report.json"
python3 "$AGGREGATE" \
  --results-file "$RESULTS_TSV" \
  --out "$M47_REPORT" \
  --label "m47" | tee "$REPORT_DIR/aggregate.log"

python3 "$VALIDATOR" \
  --report "$M47_REPORT" \
  --min-gates 10 \
  --required-gate m37 \
  --required-gate m38 \
  --required-gate m39 \
  --required-gate m40 \
  --required-gate m41 \
  --required-gate m42 \
  --required-gate m43 \
  --required-gate m44 \
  --required-gate m45 \
  --required-gate m46 \
  --expect-pass 1 \
  --label "m47" | tee "$REPORT_DIR/validation.log"

{
  echo "results_tsv=$RESULTS_TSV"
  echo "report=$M47_REPORT"
  echo "validation=$REPORT_DIR/validation.log"
  echo "---"
} >> "$MANIFEST"

echo "[m47] PASS"
echo "[m47] manifest: $MANIFEST"
echo "[m47] report: $M47_REPORT"
echo "[m47] validation: $REPORT_DIR/validation.log"
