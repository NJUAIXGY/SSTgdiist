#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m14_gate.sh [--run-root <dir>] [--skip-unit]

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m14_gate）
  --skip-unit        跳过 M14 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m14_gate"
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
      echo "[m14] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SPEC_TRAIN="$REPO_ROOT/tools/specs/tensor_m14_training_step_dma_v3.json"

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
TRAIN_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m14_training_step_dma.py"

for p in "$SPEC_TRAIN" "$CLI" "$RUNNER" "$M0_CONTRACT" "$TRAIN_VALIDATOR"
do
  if [ ! -f "$p" ]; then
    echo "[m14][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m14] run_root=\"$RUN_ROOT\""
echo "[m14] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m14] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m14_gate.py sst_workloads/tensor_si/test_tensor_spec.py snndl_system/test_builders.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_validate_tensor_m14_training_step_dma.py sst_workloads/tensor_si/tools/test_generate_tensor_training_step_spec.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m14_gate.py" \
    "sst_workloads/tensor_si/test_tensor_spec.py" \
    "snndl_system/test_builders.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m14_training_step_dma.py" \
    "sst_workloads/tensor_si/tools/test_generate_tensor_training_step_spec.py" \
    -v; then
    echo "[m14][P0] unit test gate failed" >&2
    exit 10
  fi
fi

SCENARIO="training_step_dma"
SCENARIO_ROOT="$RUN_ROOT/$SCENARIO"
mkdir -p "$SCENARIO_ROOT"

echo "[m14][$SCENARIO] validate: $SPEC_TRAIN"
if ! python3 "$CLI" validate "$SPEC_TRAIN"; then
  echo "[m14][P0][$SCENARIO] spec validate failed" >&2
  exit 10
fi

echo "[m14][$SCENARIO] run: bash \"$RUNNER\" --spec \"$SPEC_TRAIN\""
run_out=""
if ! run_out=$(
  TENSOR_SI_RUN_ROOT="$SCENARIO_ROOT" \
  TENSOR_SI_SST_NPROC=1 \
  SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst" \
  bash "$RUNNER" --spec "$SPEC_TRAIN" 2>&1
); then
  echo "$run_out"
  echo "[m14][P1][$SCENARIO] runner failed" >&2
  exit 11
fi
echo "$run_out"

run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
if [ -z "$run_dir" ]; then
  echo "[m14][P1][$SCENARIO] cannot parse tensor run_dir" >&2
  exit 11
fi

python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$SCENARIO" --expect-collective

summary="$run_dir/essential_summary_tensor_mesh.json"
if [ ! -f "$summary" ]; then
  echo "[m14][P2][$SCENARIO] missing summary: $summary" >&2
  exit 12
fi

{
  echo "scenario=$SCENARIO"
  echo "spec=$SPEC_TRAIN"
  echo "run_dir=$run_dir"
  echo "summary=$summary"
  echo "---"
} >> "$MANIFEST"

python3 "$TRAIN_VALIDATOR" --summary "$summary" | tee "$REPORT_DIR/training_validation.log"

echo "[m14] PASS"
echo "[m14] manifest: $MANIFEST"
echo "[m14] training_validation: $REPORT_DIR/training_validation.log"
