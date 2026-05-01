#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
用法:
  run_tensor_m0_gate.sh [--run-root <dir>] [--skip-unit] [--keep-going]

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m0_gate）
  --skip-unit        跳过 M0 轻量单测集合
  --keep-going       某场景失败后继续跑后续场景（默认失败即停）
  -h, --help         显示帮助
EOF
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m0_gate"
RUN_ROOT="$RUN_ROOT_DEFAULT"
SKIP_UNIT=0
KEEP_GOING=0

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
    --keep-going)
      KEEP_GOING=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[m0] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SPEC_S0="$REPO_ROOT/tools/specs/tensor_minimal_v3.json"
SPEC_S1="$REPO_ROOT/tools/specs/tensor_m0_tile_v3.json"
SPEC_S2="$REPO_ROOT/tools/specs/tensor_m0_collective_v3.json"

CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"

for p in "$SPEC_S0" "$SPEC_S1" "$SPEC_S2" "$CLI" "$RUNNER" "$CONTRACT"; do
  if [ ! -f "$p" ]; then
    echo "[m0][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m0] run_root=\"$RUN_ROOT\""
echo "[m0] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m0] unit: python3 -m unittest tools/test_snndl_spec_cli.py tools/test_run_snndl_with_time.py sst_workloads/tensor_si/test_tensor_overrides_apply.py -v"
  if ! python3 -m unittest \
    "tools/test_snndl_spec_cli.py" \
    "tools/test_run_snndl_with_time.py" \
    "sst_workloads/tensor_si/test_tensor_overrides_apply.py" \
    -v; then
    echo "[m0][P0] unit test gate failed" >&2
    exit 10
  fi
fi

run_one() {
  local scenario="$1"
  local spec="$2"
  local expect_tile="$3"
  local expect_collective="$4"
  local scenario_root="$RUN_ROOT/$scenario"

  mkdir -p "$scenario_root"

  echo "[m0][$scenario] validate: $spec"
  if ! python3 "$CLI" validate "$spec"; then
    echo "[m0][P0][$scenario] spec validate failed" >&2
    return 10
  fi

  echo "[m0][$scenario] run: bash \"$RUNNER\" --spec \"$spec\""
  local run_out=""
  if ! run_out=$(
    TENSOR_SI_RUN_ROOT="$scenario_root" bash "$RUNNER" --spec "$spec" 2>&1
  ); then
    echo "$run_out"
    echo "[m0][P1][$scenario] runner failed" >&2
    return 11
  fi
  echo "$run_out"

  local run_dir=""
  run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$run_dir" ]; then
    echo "[m0][P1][$scenario] cannot parse tensor run_dir" >&2
    return 11
  fi

  local contract_args=()
  contract_args+=(--run-dir "$run_dir" --scenario "$scenario")
  if [ "$expect_tile" = "1" ]; then
    contract_args+=(--expect-tile)
  fi
  if [ "$expect_collective" = "1" ]; then
    contract_args+=(--expect-collective)
  fi
  python3 "$CONTRACT" "${contract_args[@]}"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    return "$rc"
  fi

  {
    echo "scenario=$scenario"
    echo "spec=$spec"
    echo "run_dir=$run_dir"
    echo "---"
  } >> "$MANIFEST"

  echo "[m0][$scenario] PASS"
  return 0
}

SCENARIOS=(s0_default s1_tile s2_collective)
SPECS=("$SPEC_S0" "$SPEC_S1" "$SPEC_S2")
EXPECT_TILE=(0 1 1)
EXPECT_COLLECTIVE=(0 0 1)

FAIL_COUNT=0
for idx in "${!SCENARIOS[@]}"; do
  scenario="${SCENARIOS[$idx]}"
  spec="${SPECS[$idx]}"
  expect_tile="${EXPECT_TILE[$idx]}"
  expect_collective="${EXPECT_COLLECTIVE[$idx]}"
  if ! run_one "$scenario" "$spec" "$expect_tile" "$expect_collective"; then
    rc=$?
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "[m0] FAIL scenario=$scenario rc=$rc" >&2
    if [ "$KEEP_GOING" != "1" ]; then
      exit "$rc"
    fi
  fi
done

if [ "$FAIL_COUNT" -ne 0 ]; then
  echo "[m0] FAIL: $FAIL_COUNT scenario(s) failed" >&2
  exit 13
fi

echo "[m0] PASS"
echo "[m0] manifest: $MANIFEST"
cat "$MANIFEST"
