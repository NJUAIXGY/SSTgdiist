#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m100_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M100: phase6 full regression orchestration for M91-M99

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m100_gate）
  --skip-unit        跳过 M100 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m100_gate"
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
      echo "[m100] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

AGGREGATE="$REPO_ROOT/sst_workloads/tensor_si/tools/aggregate_tensor_phase6_regression.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m100_phase6_report.py"

GATE_M91="$REPO_ROOT/tools/run_tensor_m91_gate.sh"
GATE_M92="$REPO_ROOT/tools/run_tensor_m92_gate.sh"
GATE_M93="$REPO_ROOT/tools/run_tensor_m93_gate.sh"
GATE_M94="$REPO_ROOT/tools/run_tensor_m94_gate.sh"
GATE_M95="$REPO_ROOT/tools/run_tensor_m95_gate.sh"
GATE_M96="$REPO_ROOT/tools/run_tensor_m96_gate.sh"
GATE_M97="$REPO_ROOT/tools/run_tensor_m97_gate.sh"
GATE_M98="$REPO_ROOT/tools/run_tensor_m98_gate.sh"
GATE_M99="$REPO_ROOT/tools/run_tensor_m99_gate.sh"

for p in "$AGGREGATE" "$VALIDATOR" "$GATE_M91" "$GATE_M92" "$GATE_M93" "$GATE_M94" "$GATE_M95" "$GATE_M96" "$GATE_M97" "$GATE_M98" "$GATE_M99"
do
  if [ ! -f "$p" ]; then
    echo "[m100][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

RESULTS_TSV="$REPORT_DIR/m100_results.tsv"
: > "$RESULTS_TSV"

echo "[m100] run_root=\"$RUN_ROOT\""
echo "[m100] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m100] unit: python3 -m unittest tools/test_run_tensor_m100_gate.py sst_workloads/tensor_si/tools/test_aggregate_tensor_phase6_regression.py sst_workloads/tensor_si/tools/test_validate_tensor_m100_phase6_report.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m100_gate.py" \
    "sst_workloads/tensor_si/tools/test_aggregate_tensor_phase6_regression.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m100_phase6_report.py" \
    -v; then
    echo "[m100][P0] unit test gate failed" >&2
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

run_one_gate "m91" "$GATE_M91"
run_one_gate "m92" "$GATE_M92"
run_one_gate "m93" "$GATE_M93"
run_one_gate "m94" "$GATE_M94"
run_one_gate "m95" "$GATE_M95"
run_one_gate "m96" "$GATE_M96"
run_one_gate "m97" "$GATE_M97"
run_one_gate "m98" "$GATE_M98"
run_one_gate "m99" "$GATE_M99"

M100_REPORT="$REPORT_DIR/m100_phase6_report.json"
python3 "$AGGREGATE" --results-file "$RESULTS_TSV" --out "$M100_REPORT" --label "m100" | tee "$REPORT_DIR/aggregate.log"

python3 "$VALIDATOR" \
  --report "$M100_REPORT" \
  --min-gates 9 \
  --required-gate m91 \
  --required-gate m92 \
  --required-gate m93 \
  --required-gate m94 \
  --required-gate m95 \
  --required-gate m96 \
  --required-gate m97 \
  --required-gate m98 \
  --required-gate m99 \
  --expect-pass 1 \
  --label "m100" | tee "$REPORT_DIR/validation.log"

{
  echo "results_tsv=$RESULTS_TSV"
  echo "report=$M100_REPORT"
  echo "validation=$REPORT_DIR/validation.log"
  echo "---"
} >> "$MANIFEST"

echo "[m100] PASS"
echo "[m100] manifest: $MANIFEST"
echo "[m100] report: $M100_REPORT"
echo "[m100] validation: $REPORT_DIR/validation.log"
