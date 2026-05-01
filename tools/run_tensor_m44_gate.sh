#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m44_gate.sh [--run-root <dir>] [--skip-unit] [--skip-frontend-build]

说明:
  M44: frontend readiness contract + dashboard build gate

选项:
  --run-root <dir>        指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m44_gate）
  --skip-unit             跳过 M44 轻量单测集合
  --skip-frontend-build   跳过 frontend-dashboard 的 npm run build
  -h, --help              显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m44_gate"
RUN_ROOT="$RUN_ROOT_DEFAULT"
SKIP_UNIT=0
SKIP_FRONTEND_BUILD=0

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
    --skip-frontend-build)
      SKIP_FRONTEND_BUILD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[m44] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

M42_GATE="$REPO_ROOT/tools/run_tensor_m42_gate.sh"
M44_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m44_frontend_contract.py"

for p in "$M42_GATE" "$M44_VALIDATOR"
do
  if [ ! -f "$p" ]; then
    echo "[m44][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m44] run_root=\"$RUN_ROOT\""
echo "[m44] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m44] unit: python3 -m unittest tools/test_run_tensor_m44_gate.py sst_workloads/tensor_si/tools/test_validate_tensor_m44_frontend_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m44_gate.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m44_frontend_contract.py" \
    -v; then
    echo "[m44][P0] unit test gate failed" >&2
    exit 10
  fi
fi

M42_RUN_ROOT="$RUN_ROOT/m42_candidate"
M42_OUT=""
if ! M42_OUT=$(bash "$M42_GATE" --skip-unit --run-root "$M42_RUN_ROOT" 2>&1); then
  echo "$M42_OUT" | tee "$REPORT_DIR/m42_gate.log"
  echo "[m44][P1] m42 gate failed" >&2
  exit 11
fi

echo "$M42_OUT" | tee "$REPORT_DIR/m42_gate.log"

M42_MANIFEST=$(echo "$M42_OUT" | sed -n 's/^\[m42\] manifest: //p' | tail -n 1)
M42_REPORT=$(echo "$M42_OUT" | sed -n 's/^\[m42\] report: //p' | tail -n 1)

if [ -z "$M42_MANIFEST" ] || [ ! -f "$M42_MANIFEST" ]; then
  echo "[m44][P1] cannot parse m42 manifest path" >&2
  exit 11
fi
if [ -z "$M42_REPORT" ] || [ ! -f "$M42_REPORT" ]; then
  echo "[m44][P1] cannot parse m42 report path" >&2
  exit 11
fi

mapfile -t SUMMARIES < <(sed -n 's/^summary=//p' "$M42_MANIFEST")
if [ "${#SUMMARIES[@]}" -lt 1 ]; then
  echo "[m44][P1] no summary entries in m42 manifest" >&2
  exit 11
fi

CONTRACT_LOG="$REPORT_DIR/frontend_contract.log"
: > "$CONTRACT_LOG"
index=0
for summary in "${SUMMARIES[@]}"
do
  index=$((index + 1))
  if [ ! -f "$summary" ]; then
    echo "[m44][P1] summary path missing: $summary" >&2
    exit 11
  fi
  python3 "$M44_VALIDATOR" --summary "$summary" --label "m44_s$index" | tee -a "$CONTRACT_LOG"
done

FRONTEND_STATUS="skipped"
if [ "$SKIP_FRONTEND_BUILD" != "1" ]; then
  FRONTEND_STATUS="pass"
  if ! (cd "$REPO_ROOT/frontend-dashboard" && npm run build) | tee "$REPORT_DIR/frontend_build.log"; then
    FRONTEND_STATUS="fail"
    echo "[m44][P1] frontend build failed" >&2
    exit 11
  fi
fi

REPORT_JSON="$REPORT_DIR/m44_frontend_report.json"
python3 - "$REPORT_JSON" "$M42_REPORT" "$FRONTEND_STATUS" "${SUMMARIES[@]}" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1]).expanduser().resolve()
m42_report = str(sys.argv[2])
frontend_status = str(sys.argv[3])
summaries = [str(x) for x in sys.argv[4:]]

payload = {
    "schema_version": 1,
    "status": "pass",
    "m42_report": m42_report,
    "summary_count": len(summaries),
    "validated_summaries": summaries,
    "frontend_build_status": frontend_status,
}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

{
  echo "m42_report=$M42_REPORT"
  for summary in "${SUMMARIES[@]}"
  do
    echo "summary=$summary"
  done
  echo "frontend_build_status=$FRONTEND_STATUS"
  echo "frontend_report=$REPORT_JSON"
  echo "---"
} >> "$MANIFEST"

echo "[m44] PASS"
echo "[m44] manifest: $MANIFEST"
echo "[m44] report: $REPORT_JSON"
echo "[m44] validation: $CONTRACT_LOG"
if [ "$SKIP_FRONTEND_BUILD" != "1" ]; then
  echo "[m44] frontend_build_log: $REPORT_DIR/frontend_build.log"
fi
