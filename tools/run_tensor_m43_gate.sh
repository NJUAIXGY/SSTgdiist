#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m43_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M43: fixed golden baseline drift governance gate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m43_gate）
  --skip-unit        跳过 M43 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m43_gate"
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
      echo "[m43] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

M42_GATE="$REPO_ROOT/tools/run_tensor_m42_gate.sh"
BASELINE_SPEC="$REPO_ROOT/tools/specs/tensor_m43_golden_baseline.json"
COMPARE="$REPO_ROOT/sst_workloads/tensor_si/tools/compare_tensor_readiness_drift.py"
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m43_drift_contract.py"

for p in "$M42_GATE" "$BASELINE_SPEC" "$COMPARE" "$VALIDATOR"
do
  if [ ! -f "$p" ]; then
    echo "[m43][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m43] run_root=\"$RUN_ROOT\""
echo "[m43] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m43] unit: python3 -m unittest tools/test_run_tensor_m43_gate.py sst_workloads/tensor_si/tools/test_compare_tensor_readiness_drift.py sst_workloads/tensor_si/tools/test_validate_tensor_m43_drift_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m43_gate.py" \
    "sst_workloads/tensor_si/tools/test_compare_tensor_readiness_drift.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m43_drift_contract.py" \
    -v; then
    echo "[m43][P0] unit test gate failed" >&2
    exit 10
  fi
fi

M42_RUN_ROOT="$RUN_ROOT/m42_candidate"
M42_OUT=""
if ! M42_OUT=$(bash "$M42_GATE" --skip-unit --run-root "$M42_RUN_ROOT" 2>&1); then
  echo "$M42_OUT" | tee "$REPORT_DIR/m42_gate.log"
  echo "[m43][P1] m42 gate failed" >&2
  exit 11
fi

echo "$M42_OUT" | tee "$REPORT_DIR/m42_gate.log"

CANDIDATE_REPORT=$(echo "$M42_OUT" | sed -n 's/^\[m42\] report: //p' | tail -n 1)
if [ -z "$CANDIDATE_REPORT" ] || [ ! -f "$CANDIDATE_REPORT" ]; then
  echo "[m43][P1] cannot parse candidate m42 report path" >&2
  exit 11
fi

DRIFT_REPORT="$REPORT_DIR/m43_readiness_drift_report.json"
python3 "$COMPARE" \
  --baseline-spec "$BASELINE_SPEC" \
  --candidate-report "$CANDIDATE_REPORT" \
  --out "$DRIFT_REPORT" \
  --label "m43" | tee "$REPORT_DIR/compare.log"

python3 "$VALIDATOR" --drift-report "$DRIFT_REPORT" --expect-pass 1 --label "m43" | tee "$REPORT_DIR/validation.log"

{
  echo "baseline_spec=$BASELINE_SPEC"
  echo "candidate_report=$CANDIDATE_REPORT"
  echo "drift_report=$DRIFT_REPORT"
  echo "---"
} >> "$MANIFEST"

echo "[m43] PASS"
echo "[m43] manifest: $MANIFEST"
echo "[m43] drift_report: $DRIFT_REPORT"
echo "[m43] validation: $REPORT_DIR/validation.log"
