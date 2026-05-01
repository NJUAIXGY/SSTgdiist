#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m17_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M17: mapping(json) -> compile -> schema-v3 tensor spec -> run -> contract validate

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m17_gate）
  --skip-unit        跳过 M17 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m17_gate"
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
      echo "[m17] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
COMPILER="$REPO_ROOT/sst_workloads/tensor_si/tools/compile_tpu_mapping_to_spec.py"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
M17_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m17_mapping_contract.py"

MAP_TPUV1="$REPO_ROOT/tools/specs/tensor_m17_mapping_demo_tpuv1.json"
MAP_BF16="$REPO_ROOT/tools/specs/tensor_m17_mapping_demo_bf16.json"

for p in \
  "$CLI" "$RUNNER" "$COMPILER" "$M0_CONTRACT" "$M17_VALIDATOR" \
  "$MAP_TPUV1" "$MAP_BF16"
do
  if [ ! -f "$p" ]; then
    echo "[m17][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m17] run_root=\"$RUN_ROOT\""
echo "[m17] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m17] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m17_gate.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_validate_tensor_m17_mapping_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m17_gate.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m17_mapping_contract.py" \
    -v; then
    echo "[m17][P0] unit test gate failed" >&2
    exit 10
  fi
fi

compile_one() {
  local mapping="$1"
  local out_spec="$2"
  echo "[m17] compile: $mapping -> $out_spec" >&2
  python3 "$COMPILER" --mapping "$mapping" --out "$out_spec" >&2
  if [ ! -f "$out_spec" ]; then
    echo "[m17][P1] compiler did not produce spec: $out_spec" >&2
    return 11
  fi
}

run_one() {
  local label="$1"
  local mapping="$2"
  local scenario_root="$3"

  mkdir -p "$scenario_root"
  local spec="$scenario_root/compiled_spec.json"
  compile_one "$mapping" "$spec"

  echo "[m17][$label] validate: $spec" >&2
  python3 "$CLI" validate "$spec" >&2

  echo "[m17][$label] run: bash \"$RUNNER\" --spec \"$spec\"" >&2
  local run_out=""
  run_out=$(
    TENSOR_SI_RUN_ROOT="$scenario_root/run" \
    TENSOR_SI_SST_NPROC=1 \
    SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst" \
    bash "$RUNNER" --spec "$spec" 2>&1
  )
  echo "$run_out" >&2

  local run_dir=""
  run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$run_dir" ]; then
    echo "[m17][P1][$label] cannot parse tensor run_dir" >&2
    return 12
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$label" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m17][P2][$label] missing summary: $summary" >&2
    return 13
  fi

  python3 "$M17_VALIDATOR" --mapping "$mapping" --spec "$spec" --summary "$summary" --label "$label" | tee "$REPORT_DIR/${label}_validation.log"

  {
    echo "label=$label"
    echo "mapping=$mapping"
    echo "spec=$spec"
    echo "run_dir=$run_dir"
    echo "summary=$summary"
    echo "---"
  } >> "$MANIFEST"

  echo "$summary"
}

run_one "tpuv1" "$MAP_TPUV1" "$RUN_ROOT/tpuv1"
run_one "bf16" "$MAP_BF16" "$RUN_ROOT/bf16"

echo "[m17] PASS"
echo "[m17] manifest: $MANIFEST"

