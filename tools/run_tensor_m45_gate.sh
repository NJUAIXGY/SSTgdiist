#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m45_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M45: calibration feedback loop gate (whitelist + safety + drift constraint)

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m45_gate）
  --skip-unit        跳过 M45 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m45_gate"
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
      echo "[m45] unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RUN_ROOT")

M41_GATE="$REPO_ROOT/tools/run_tensor_m41_gate.sh"
CLI="$REPO_ROOT/tools/snndl_spec_cli.py"
RUNNER="$REPO_ROOT/tools/run_snndl_with_time.sh"
M0_CONTRACT="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m0_contract.py"
M42_SUMMARY="$REPO_ROOT/sst_workloads/tensor_si/tools/summarize_tensor_npu_readiness.py"
M43_COMPARE="$REPO_ROOT/sst_workloads/tensor_si/tools/compare_tensor_readiness_drift.py"
M43_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m43_drift_contract.py"
M45_APPLY="$REPO_ROOT/sst_workloads/tensor_si/tools/apply_tensor_calibration_feedback.py"
M45_SAFETY="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m45_feedback_safety.py"
BASELINE_SPEC="$REPO_ROOT/tools/specs/tensor_m43_golden_baseline.json"
WHITELIST="$REPO_ROOT/tools/specs/tensor_m45_feedback_whitelist.json"
TARGET_SPEC="$REPO_ROOT/tools/specs/tensor_m45_feedback_target_v3.json"

for p in \
  "$M41_GATE" "$CLI" "$RUNNER" "$M0_CONTRACT" "$M42_SUMMARY" \
  "$M43_COMPARE" "$M43_VALIDATOR" "$M45_APPLY" "$M45_SAFETY" \
  "$BASELINE_SPEC" "$WHITELIST" "$TARGET_SPEC"
do
  if [ ! -f "$p" ]; then
    echo "[m45][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m45] run_root=\"$RUN_ROOT\""
echo "[m45] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m45] unit: python3 -m unittest tools/test_run_tensor_m45_gate.py sst_workloads/tensor_si/tools/test_apply_tensor_calibration_feedback.py sst_workloads/tensor_si/tools/test_validate_tensor_m45_feedback_safety.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m45_gate.py" \
    "sst_workloads/tensor_si/tools/test_apply_tensor_calibration_feedback.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m45_feedback_safety.py" \
    -v; then
    echo "[m45][P0] unit test gate failed" >&2
    exit 10
  fi
fi

M41_OUT=""
M41_RUN_ROOT="$RUN_ROOT/m41_candidate"
if ! M41_OUT=$(bash "$M41_GATE" --skip-unit --run-root "$M41_RUN_ROOT" 2>&1); then
  echo "$M41_OUT" | tee "$REPORT_DIR/m41_gate.log"
  echo "[m45][P1] m41 gate failed" >&2
  exit 11
fi

echo "$M41_OUT" | tee "$REPORT_DIR/m41_gate.log"

CALIB_PROFILE=$(echo "$M41_OUT" | sed -n 's/^\[m41\] calibration: //p' | tail -n 1)
if [ -z "$CALIB_PROFILE" ] || [ ! -f "$CALIB_PROFILE" ]; then
  echo "[m45][P1] cannot parse m41 calibration profile path" >&2
  exit 11
fi

PATCHED_SPEC="$REPORT_DIR/tensor_m45_feedback_patched_v3.json"
PATCH_REPORT="$REPORT_DIR/m45_feedback_patch_report.json"
python3 "$M45_APPLY" \
  --source-spec "$TARGET_SPEC" \
  --profile "$CALIB_PROFILE" \
  --whitelist "$WHITELIST" \
  --out "$PATCHED_SPEC" \
  --patch-report "$PATCH_REPORT" \
  --label "m45" | tee "$REPORT_DIR/apply.log"

python3 "$M45_SAFETY" \
  --patch-report "$PATCH_REPORT" \
  --whitelist "$WHITELIST" \
  --expect-pass 1 \
  --label "m45" | tee "$REPORT_DIR/safety.log"

python3 "$CLI" validate "$PATCHED_SPEC" | tee "$REPORT_DIR/spec_validate.log"

RUN_OUT=$(
  TENSOR_SI_RUN_ROOT="$RUN_ROOT/candidate" \
  TENSOR_SI_SST_NPROC=1 \
  SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst" \
  bash "$RUNNER" --spec "$PATCHED_SPEC" 2>&1
)

echo "$RUN_OUT" | tee "$REPORT_DIR/candidate_run.log"

CANDIDATE_RUN_DIR=$(echo "$RUN_OUT" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
if [ -z "$CANDIDATE_RUN_DIR" ]; then
  echo "[m45][P1] cannot parse candidate run_dir" >&2
  exit 11
fi

python3 "$M0_CONTRACT" --run-dir "$CANDIDATE_RUN_DIR" --scenario "m45_feedback_candidate" | tee "$REPORT_DIR/m0_contract.log"

CANDIDATE_SUMMARY="$CANDIDATE_RUN_DIR/essential_summary_tensor_mesh.json"
if [ ! -f "$CANDIDATE_SUMMARY" ]; then
  echo "[m45][P1] missing candidate summary: $CANDIDATE_SUMMARY" >&2
  exit 11
fi

CANDIDATE_REPORT="$REPORT_DIR/m45_candidate_readiness_report.json"
python3 "$M42_SUMMARY" \
  --summary "$CANDIDATE_SUMMARY" \
  --profile "$CALIB_PROFILE" \
  --out "$CANDIDATE_REPORT" | tee "$REPORT_DIR/readiness_summary.log"

DRIFT_REPORT="$REPORT_DIR/m45_drift_report.json"
python3 "$M43_COMPARE" \
  --baseline-spec "$BASELINE_SPEC" \
  --candidate-report "$CANDIDATE_REPORT" \
  --out "$DRIFT_REPORT" \
  --label "m45" | tee "$REPORT_DIR/drift_compare.log"

python3 "$M43_VALIDATOR" \
  --drift-report "$DRIFT_REPORT" \
  --expect-pass 1 \
  --label "m45" | tee "$REPORT_DIR/drift_validation.log"

{
  echo "baseline_spec=$BASELINE_SPEC"
  echo "target_spec=$TARGET_SPEC"
  echo "calibration_profile=$CALIB_PROFILE"
  echo "patched_spec=$PATCHED_SPEC"
  echo "patch_report=$PATCH_REPORT"
  echo "candidate_run_dir=$CANDIDATE_RUN_DIR"
  echo "candidate_summary=$CANDIDATE_SUMMARY"
  echo "candidate_report=$CANDIDATE_REPORT"
  echo "drift_report=$DRIFT_REPORT"
  echo "---"
} >> "$MANIFEST"

echo "[m45] PASS"
echo "[m45] manifest: $MANIFEST"
echo "[m45] patch_report: $PATCH_REPORT"
echo "[m45] drift_report: $DRIFT_REPORT"
