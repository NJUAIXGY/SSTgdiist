#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m110_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M110: phase7 full regression orchestration for M101-M109

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m110_gate）
  --skip-unit        跳过 M110 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m110_gate"
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
      echo "[m110] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

AGGREGATE="$REPO_ROOT/sst_workloads/tensor_si/tools/aggregate_tensor_phase7_regression.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m110_phase7_report.py"

GATE_M101="$REPO_ROOT/tools/run_tensor_m101_gate.sh"
GATE_M102="$REPO_ROOT/tools/run_tensor_m102_gate.sh"
GATE_M103="$REPO_ROOT/tools/run_tensor_m103_gate.sh"
GATE_M104="$REPO_ROOT/tools/run_tensor_m104_gate.sh"
GATE_M105="$REPO_ROOT/tools/run_tensor_m105_gate.sh"
GATE_M106="$REPO_ROOT/tools/run_tensor_m106_gate.sh"
GATE_M107="$REPO_ROOT/tools/run_tensor_m107_gate.sh"
GATE_M108="$REPO_ROOT/tools/run_tensor_m108_gate.sh"
GATE_M109="$REPO_ROOT/tools/run_tensor_m109_gate.sh"

for p in "$AGGREGATE" "$VALIDATOR" "$GATE_M101" "$GATE_M102" "$GATE_M103" "$GATE_M104" "$GATE_M105" "$GATE_M106" "$GATE_M107" "$GATE_M108" "$GATE_M109"
do
  if [ ! -f "$p" ]; then
    echo "[m110][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

RESULTS_TSV="$REPORT_DIR/m110_results.tsv"
: > "$RESULTS_TSV"

echo "[m110] run_root=\"$RUN_ROOT\""
echo "[m110] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m110] unit: python3 -m unittest tools/test_run_tensor_m110_gate.py sst_workloads/tensor_si/tools/test_aggregate_tensor_phase7_regression.py sst_workloads/tensor_si/tools/test_validate_tensor_m110_phase7_report.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m110_gate.py" \
    "sst_workloads/tensor_si/tools/test_aggregate_tensor_phase7_regression.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m110_phase7_report.py" \
    -v; then
    echo "[m110][P0] unit test gate failed" >&2
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

run_one_gate "m101" "$GATE_M101"
run_one_gate "m102" "$GATE_M102"
run_one_gate "m103" "$GATE_M103"
run_one_gate "m104" "$GATE_M104"
run_one_gate "m105" "$GATE_M105"
run_one_gate "m106" "$GATE_M106"
run_one_gate "m107" "$GATE_M107"
run_one_gate "m108" "$GATE_M108"
run_one_gate "m109" "$GATE_M109"

M110_REPORT="$REPORT_DIR/m110_phase7_report.json"
python3 "$AGGREGATE" --results-file "$RESULTS_TSV" --out "$M110_REPORT" --label "m110" | tee "$REPORT_DIR/aggregate.log"

python3 "$VALIDATOR" \
  --report "$M110_REPORT" \
  --min-gates 9 \
  --required-gate m101 \
  --required-gate m102 \
  --required-gate m103 \
  --required-gate m104 \
  --required-gate m105 \
  --required-gate m106 \
  --required-gate m107 \
  --required-gate m108 \
  --required-gate m109 \
  --expect-pass 1 \
  --label "m110" | tee "$REPORT_DIR/validation.log"

{
  echo "results_tsv=$RESULTS_TSV"
  echo "report=$M110_REPORT"
  echo "validation=$REPORT_DIR/validation.log"
  echo "---"
} >> "$MANIFEST"

echo "[m110] PASS"
echo "[m110] manifest: $MANIFEST"
echo "[m110] report: $M110_REPORT"
echo "[m110] validation: $REPORT_DIR/validation.log"
