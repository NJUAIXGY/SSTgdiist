#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m63_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M63: regression gate hardening contract

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m63_gate）
  --skip-unit        跳过 M63 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m63_gate"
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
      echo "[m63] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")
VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m63_regression_hardening.py"
TARGET_SCRIPT="$REPO_ROOT/tools/run_snndl_regression_gate.sh"

for p in "$VALIDATOR" "$TARGET_SCRIPT"
do
  if [ ! -f "$p" ]; then
    echo "[m63][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m63] run_root=\"$RUN_ROOT\""
echo "[m63] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m63] unit: python3 -m unittest tools/test_run_tensor_m63_gate.py tools/test_run_snndl_regression_gate_realism_contract.py sst_workloads/tensor_si/tools/test_validate_tensor_m63_regression_hardening.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m63_gate.py" \
    "tools/test_run_snndl_regression_gate_realism_contract.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m63_regression_hardening.py" \
    -v; then
    echo "[m63][P0] unit test gate failed" >&2
    exit 10
  fi
fi

python3 "$VALIDATOR" --script "$TARGET_SCRIPT" --label "m63" | tee "$REPORT_DIR/validation.log"

{
  echo "script=$TARGET_SCRIPT"
  echo "validation=$REPORT_DIR/validation.log"
  echo "---"
} >> "$MANIFEST"

echo "[m63] PASS"
echo "[m63] manifest: $MANIFEST"
echo "[m63] validation: $REPORT_DIR/validation.log"
