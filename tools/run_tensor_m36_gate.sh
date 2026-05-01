#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m36_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M36: dashboard contract gate (required subset + derived metrics invariants)

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m36_gate）
  --skip-unit        跳过 M36 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m36_gate"
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
      echo "[m36] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
M36_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m36_dashboard_contract.py"

# Representative scenarios:
# - ramulator2 backend (mem-heavy, latency signals likely present)
# - on-chip conflict (no DRAM traffic but on-chip stall signals)
# - mxu throttled (compute-bound + DRAM reads, latency samples may be absent but avg keys must be stable)
SPEC_RAM2="$REPO_ROOT/tools/specs/tensor_m25_mem_backend_ram2_v3.json"
SPEC_ONCHIP_CONFLICT="$REPO_ROOT/tools/specs/tensor_m32_mxu_onchip_conflict_v3.json"
SPEC_MXU_THROTTLED="$REPO_ROOT/tools/specs/tensor_m30_mxu_feed_throttled_v3.json"

for p in \
  "$CLI" "$RUNNER" "$M0_CONTRACT" "$M36_VALIDATOR" \
  "$SPEC_RAM2" "$SPEC_ONCHIP_CONFLICT" "$SPEC_MXU_THROTTLED"
do
  if [ ! -f "$p" ]; then
    echo "[m36][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m36] run_root=\"$RUN_ROOT\""
echo "[m36] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m36] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py tools/test_run_tensor_m36_gate.py sst_workloads/tensor_si/test_tensor_spec.py snndl_system/test_builders.py sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py sst_workloads/tensor_si/tools/test_validate_tensor_m36_dashboard_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "tools/test_run_tensor_m36_gate.py" \
    "sst_workloads/tensor_si/test_tensor_spec.py" \
    "snndl_system/test_builders.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m0_contract.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m36_dashboard_contract.py" \
    -v; then
    echo "[m36][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local spec="$2"
  local scenario_root="$3"

  echo "[m36][$scenario] validate: $spec" >&2
  python3 "$CLI" validate "$spec" >&2

  echo "[m36][$scenario] run: bash \"$RUNNER\" --spec \"$spec\"" >&2
  local run_out=""
  run_out=$(
    TENSOR_SI_RUN_ROOT="$scenario_root" \
    TENSOR_SI_SST_NPROC=1 \
    SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst" \
    bash "$RUNNER" --spec "$spec" 2>&1
  )
  echo "$run_out" >&2

  local run_dir=""
  run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$run_dir" ]; then
    echo "[m36][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "$scenario" >&2

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m36][P2][$scenario] missing summary: $summary" >&2
    return 12
  fi

  {
    echo "scenario=$scenario"
    echo "spec=$spec"
    echo "run_dir=$run_dir"
    echo "summary=$summary"
    echo "---"
  } >> "$MANIFEST"

  echo "$summary"
}

mkdir -p "$RUN_ROOT/ram2" "$RUN_ROOT/onchip_conflict" "$RUN_ROOT/mxu_throttled"

sum_ram2=$(run_one "ram2" "$SPEC_RAM2" "$RUN_ROOT/ram2") || exit $?
sum_onchip=$(run_one "onchip_conflict" "$SPEC_ONCHIP_CONFLICT" "$RUN_ROOT/onchip_conflict") || exit $?
sum_mxu=$(run_one "mxu_throttled" "$SPEC_MXU_THROTTLED" "$RUN_ROOT/mxu_throttled") || exit $?

: > "$REPORT_DIR/validation.log"
python3 "$M36_VALIDATOR" --summary "$sum_ram2" --label "ram2" | tee -a "$REPORT_DIR/validation.log"
python3 "$M36_VALIDATOR" --summary "$sum_onchip" --label "onchip_conflict" | tee -a "$REPORT_DIR/validation.log"
python3 "$M36_VALIDATOR" --summary "$sum_mxu" --label "mxu_throttled" | tee -a "$REPORT_DIR/validation.log"

echo "[m36] PASS"
echo "[m36] manifest: $MANIFEST"
echo "[m36] validation: $REPORT_DIR/validation.log"

