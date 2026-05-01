#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m70_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M70: phase3 full regression orchestration for M61-M69

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m70_gate）
  --skip-unit        跳过 M70 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m70_gate"
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
      echo "[m70] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

AGGREGATE="$REPO_ROOT/sst_workloads/tensor_si/tools/aggregate_tensor_phase3_regression.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m70_phase3_report.py"

GATE_M61="$REPO_ROOT/tools/run_tensor_m61_gate.sh"
GATE_M62="$REPO_ROOT/tools/run_tensor_m62_gate.sh"
GATE_M63="$REPO_ROOT/tools/run_tensor_m63_gate.sh"
GATE_M64="$REPO_ROOT/tools/run_tensor_m64_gate.sh"
GATE_M65="$REPO_ROOT/tools/run_tensor_m65_gate.sh"
GATE_M66="$REPO_ROOT/tools/run_tensor_m66_gate.sh"
GATE_M67="$REPO_ROOT/tools/run_tensor_m67_gate.sh"
GATE_M68="$REPO_ROOT/tools/run_tensor_m68_gate.sh"
GATE_M69="$REPO_ROOT/tools/run_tensor_m69_gate.sh"

for p in "$AGGREGATE" "$VALIDATOR" "$GATE_M61" "$GATE_M62" "$GATE_M63" "$GATE_M64" "$GATE_M65" "$GATE_M66" "$GATE_M67" "$GATE_M68" "$GATE_M69"
do
  if [ ! -f "$p" ]; then
    echo "[m70][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

RESULTS_TSV="$REPORT_DIR/m70_results.tsv"
: > "$RESULTS_TSV"

echo "[m70] run_root=\"$RUN_ROOT\""
echo "[m70] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m70] unit: python3 -m unittest tools/test_run_tensor_m70_gate.py sst_workloads/tensor_si/tools/test_aggregate_tensor_phase3_regression.py sst_workloads/tensor_si/tools/test_validate_tensor_m70_phase3_report.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m70_gate.py" \
    "sst_workloads/tensor_si/tools/test_aggregate_tensor_phase3_regression.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m70_phase3_report.py" \
    -v; then
    echo "[m70][P0] unit test gate failed" >&2
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

run_one_gate "m61" "$GATE_M61"
run_one_gate "m62" "$GATE_M62"
run_one_gate "m63" "$GATE_M63"
run_one_gate "m64" "$GATE_M64"
run_one_gate "m65" "$GATE_M65"
run_one_gate "m66" "$GATE_M66"
run_one_gate "m67" "$GATE_M67"
run_one_gate "m68" "$GATE_M68"
run_one_gate "m69" "$GATE_M69"

M70_REPORT="$REPORT_DIR/m70_phase3_report.json"
python3 "$AGGREGATE" --results-file "$RESULTS_TSV" --out "$M70_REPORT" --label "m70" | tee "$REPORT_DIR/aggregate.log"

python3 "$VALIDATOR" \
  --report "$M70_REPORT" \
  --min-gates 9 \
  --required-gate m61 \
  --required-gate m62 \
  --required-gate m63 \
  --required-gate m64 \
  --required-gate m65 \
  --required-gate m66 \
  --required-gate m67 \
  --required-gate m68 \
  --required-gate m69 \
  --expect-pass 1 \
  --label "m70" | tee "$REPORT_DIR/validation.log"

{
  echo "results_tsv=$RESULTS_TSV"
  echo "report=$M70_REPORT"
  echo "validation=$REPORT_DIR/validation.log"
  echo "---"
} >> "$MANIFEST"

echo "[m70] PASS"
echo "[m70] manifest: $MANIFEST"
echo "[m70] report: $M70_REPORT"
echo "[m70] validation: $REPORT_DIR/validation.log"
