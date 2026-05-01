#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
用法:
  run_tensor_m46_gate.sh [--run-root <dir>] [--skip-unit]

说明:
  M46: multi-scenario realism regression gate (hard drift gate + exception whitelist)

选项:
  --run-root <dir>   指定输出根目录（默认: sst_workloads/tensor_si/outputs/tensor_mesh_m46_gate）
  --skip-unit        跳过 M46 轻量单测集合
  -h, --help         显示帮助
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

RUN_ROOT_DEFAULT="$REPO_ROOT/sst_workloads/tensor_si/outputs/tensor_mesh_m46_gate"
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
      echo "[m46] unknown arg: $1" >&2
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
M46_AGGREGATE="$REPO_ROOT/sst_workloads/tensor_si/tools/aggregate_tensor_m46_multi_scenario.py"
M46_VALIDATOR="$REPO_ROOT/sst_workloads/tensor_si/tools/validate_tensor_m46_multi_scenario_contract.py"

WHITELIST="$REPO_ROOT/tools/specs/tensor_m45_feedback_whitelist.json"
SCENARIOS_SPEC="$REPO_ROOT/tools/specs/tensor_m46_feedback_scenarios.json"
POLICY_SPEC="$REPO_ROOT/tools/specs/tensor_m46_drift_policy.json"
EXCEPTIONS_SPEC="$REPO_ROOT/tools/specs/tensor_m46_gate_exceptions.json"

for p in \
  "$M41_GATE" "$CLI" "$RUNNER" "$M0_CONTRACT" "$M42_SUMMARY" \
  "$M43_COMPARE" "$M43_VALIDATOR" "$M45_APPLY" "$M45_SAFETY" \
  "$M46_AGGREGATE" "$M46_VALIDATOR" \
  "$WHITELIST" "$SCENARIOS_SPEC" "$POLICY_SPEC" "$EXCEPTIONS_SPEC"
do
  if [ ! -f "$p" ]; then
    echo "[m46][P0] missing required file: $p" >&2
    exit 10
  fi
done

mkdir -p "$RUN_ROOT"
TS=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="$RUN_ROOT/gate_$TS"
mkdir -p "$REPORT_DIR"
MANIFEST="$REPORT_DIR/manifest.txt"
touch "$MANIFEST"

echo "[m46] run_root=\"$RUN_ROOT\""
echo "[m46] report_dir=\"$REPORT_DIR\""

if [ "$SKIP_UNIT" != "1" ]; then
  echo "[m46] unit: python3 -m unittest tools/test_run_tensor_m46_gate.py sst_workloads/tensor_si/tools/test_compare_tensor_readiness_drift.py sst_workloads/tensor_si/tools/test_compare_tensor_readiness_drift_threshold_override.py sst_workloads/tensor_si/tools/test_aggregate_tensor_m46_multi_scenario.py sst_workloads/tensor_si/tools/test_validate_tensor_m46_multi_scenario_contract.py -v"
  if ! python3 -m unittest \
    "tools/test_run_tensor_m46_gate.py" \
    "sst_workloads/tensor_si/tools/test_compare_tensor_readiness_drift.py" \
    "sst_workloads/tensor_si/tools/test_compare_tensor_readiness_drift_threshold_override.py" \
    "sst_workloads/tensor_si/tools/test_aggregate_tensor_m46_multi_scenario.py" \
    "sst_workloads/tensor_si/tools/test_validate_tensor_m46_multi_scenario_contract.py" \
    -v; then
    echo "[m46][P0] unit test gate failed" >&2
    exit 10
  fi
fi

M41_OUT=""
M41_RUN_ROOT="$RUN_ROOT/m41_profile"
if ! M41_OUT=$(bash "$M41_GATE" --skip-unit --run-root "$M41_RUN_ROOT" 2>&1); then
  echo "$M41_OUT" | tee "$REPORT_DIR/m41_gate.log"
  echo "[m46][P1] m41 gate failed" >&2
  exit 11
fi

echo "$M41_OUT" | tee "$REPORT_DIR/m41_gate.log"

CALIB_PROFILE=$(echo "$M41_OUT" | sed -n 's/^\[m41\] calibration: //p' | tail -n 1)
if [ -z "$CALIB_PROFILE" ] || [ ! -f "$CALIB_PROFILE" ]; then
  echo "[m46][P1] cannot parse m41 calibration profile path" >&2
  exit 11
fi

SCENARIO_LIST="$REPORT_DIR/scenarios.tsv"
python3 - "$SCENARIOS_SPEC" "$REPO_ROOT" "$SCENARIO_LIST" <<'PY'
import json
import sys
from pathlib import Path

scenarios_spec = Path(sys.argv[1]).expanduser().resolve()
repo_root = Path(sys.argv[2]).expanduser().resolve()
out = Path(sys.argv[3]).expanduser().resolve()

payload = json.loads(scenarios_spec.read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise SystemExit("[m46][P0] scenarios spec root must be object")
rows = payload.get("scenarios")
if not isinstance(rows, list) or not rows:
    raise SystemExit("[m46][P0] scenarios spec missing non-empty scenarios list")

seen = set()
lines = []
for idx, item in enumerate(rows):
    if not isinstance(item, dict):
        raise SystemExit(f"[m46][P0] scenarios[{idx}] must be object")
    name = str(item.get("name", "")).strip()
    source = str(item.get("source_spec", "")).strip()
    enabled = bool(item.get("enabled", True))
    if not enabled:
        continue
    if not name:
        raise SystemExit(f"[m46][P0] scenarios[{idx}] missing name")
    if not source:
        raise SystemExit(f"[m46][P0] scenarios[{idx}] missing source_spec")
    if name in seen:
        raise SystemExit(f"[m46][P0] duplicate scenario name: {name}")
    seen.add(name)

    p = Path(source).expanduser()
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    else:
        p = p.resolve()
    if not p.exists():
        raise SystemExit(f"[m46][P0] scenario spec not found: {p}")
    lines.append(f"{name}\t{p}")

if not lines:
    raise SystemExit("[m46][P0] no enabled scenarios in scenarios spec")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

RESULTS_FILE="$REPORT_DIR/m46_results.tsv"
: > "$RESULTS_FILE"

run_one() {
  local name="$1"
  local source_spec="$2"
  local scenario_dir="$REPORT_DIR/scenarios/$name"
  mkdir -p "$scenario_dir"

  local base_run_out
  base_run_out=$(
    TENSOR_SI_RUN_ROOT="$RUN_ROOT/baseline_runs/$name" \
    TENSOR_SI_SST_NPROC=1 \
    SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst" \
    bash "$RUNNER" --spec "$source_spec" 2>&1
  )
  echo "$base_run_out" | tee "$scenario_dir/baseline_run.log"

  local base_run_dir
  base_run_dir=$(echo "$base_run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$base_run_dir" ]; then
    echo "[m46][P1][$name] cannot parse baseline run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$base_run_dir" --scenario "m46_${name}_baseline" | tee "$scenario_dir/baseline_m0_contract.log"

  local baseline_summary="$base_run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$baseline_summary" ]; then
    echo "[m46][P1][$name] missing baseline summary: $baseline_summary" >&2
    return 11
  fi

  local baseline_report="$scenario_dir/m46_baseline_readiness_report.json"
  python3 "$M42_SUMMARY" \
    --summary "$baseline_summary" \
    --profile "$CALIB_PROFILE" \
    --out "$baseline_report" | tee "$scenario_dir/baseline_readiness_summary.log"

  local baseline_spec="$scenario_dir/m46_baseline_spec.json"
  python3 - "$baseline_report" "$baseline_spec" "$name" <<'PY'
import json
import sys
from pathlib import Path

report_p = Path(sys.argv[1]).expanduser().resolve()
out_p = Path(sys.argv[2]).expanduser().resolve()
name = str(sys.argv[3]).strip() or "scenario"
report = json.loads(report_p.read_text(encoding="utf-8"))
if not isinstance(report, dict):
    raise SystemExit("[m46][P1] baseline readiness report root must be object")

snapshot = {
    "capability_score_total_avg": report.get("capability_score_total_avg", 0.0),
    "distance_to_target_avg": report.get("distance_to_target_avg", 0.0),
    "capability_score_breakdown_avg": report.get("capability_score_breakdown_avg", {}),
    "regression_drift_flags_union": report.get("regression_drift_flags_union", []),
}
spec = {
    "schema_version": 1,
    "baseline_id": f"m46_{name}_baseline",
    "baseline_report_snapshot": snapshot,
    "thresholds": {},
}
out_p.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

  local patched_spec="$scenario_dir/tensor_m46_feedback_patched_v3.json"
  local patch_report="$scenario_dir/m45_feedback_patch_report.json"

  python3 "$M45_APPLY" \
    --source-spec "$source_spec" \
    --profile "$CALIB_PROFILE" \
    --whitelist "$WHITELIST" \
    --out "$patched_spec" \
    --patch-report "$patch_report" \
    --label "m46_$name" | tee "$scenario_dir/apply.log"

  python3 "$M45_SAFETY" \
    --patch-report "$patch_report" \
    --whitelist "$WHITELIST" \
    --expect-pass 1 \
    --label "m46_$name" | tee "$scenario_dir/safety.log"

  python3 "$CLI" validate "$patched_spec" | tee "$scenario_dir/spec_validate.log"

  local run_out
  run_out=$(
    TENSOR_SI_RUN_ROOT="$RUN_ROOT/runs/$name" \
    TENSOR_SI_SST_NPROC=1 \
    SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst" \
    bash "$RUNNER" --spec "$patched_spec" 2>&1
  )
  echo "$run_out" | tee "$scenario_dir/candidate_run.log"

  local run_dir
  run_dir=$(echo "$run_out" | sed -n 's/^\[tensor_mesh\] run complete: //p' | tail -n 1)
  if [ -z "$run_dir" ]; then
    echo "[m46][P1][$name] cannot parse candidate run_dir" >&2
    return 11
  fi

  python3 "$M0_CONTRACT" --run-dir "$run_dir" --scenario "m46_$name" | tee "$scenario_dir/m0_contract.log"

  local summary="$run_dir/essential_summary_tensor_mesh.json"
  if [ ! -f "$summary" ]; then
    echo "[m46][P1][$name] missing candidate summary: $summary" >&2
    return 11
  fi

  local candidate_report="$scenario_dir/m46_candidate_readiness_report.json"
  python3 "$M42_SUMMARY" \
    --summary "$summary" \
    --profile "$CALIB_PROFILE" \
    --out "$candidate_report" | tee "$scenario_dir/readiness_summary.log"

  local drift_report="$scenario_dir/m46_drift_report.json"
  python3 "$M43_COMPARE" \
    --baseline-spec "$baseline_spec" \
    --threshold-spec "$POLICY_SPEC" \
    --candidate-report "$candidate_report" \
    --out "$drift_report" \
    --label "m46_$name" | tee "$scenario_dir/drift_compare.log"

  python3 "$M43_VALIDATOR" \
    --drift-report "$drift_report" \
    --expect-pass 0 \
    --label "m46_$name" | tee "$scenario_dir/drift_validation.log"

  printf '%s\t%s\t%s\t%s\n' "$name" "$candidate_report" "$drift_report" "$patch_report" >> "$RESULTS_FILE"

  {
    echo "scenario=$name"
    echo "source_spec=$source_spec"
    echo "baseline_run_dir=$base_run_dir"
    echo "baseline_summary=$baseline_summary"
    echo "baseline_report=$baseline_report"
    echo "baseline_spec=$baseline_spec"
    echo "patched_spec=$patched_spec"
    echo "patch_report=$patch_report"
    echo "run_dir=$run_dir"
    echo "summary=$summary"
    echo "candidate_report=$candidate_report"
    echo "drift_report=$drift_report"
    echo "---"
  } >> "$MANIFEST"
}

while IFS=$'\t' read -r name source_spec
do
  [ -z "$name" ] && continue
  run_one "$name" "$source_spec" || exit $?
done < "$SCENARIO_LIST"

SCENARIO_COUNT=$(wc -l < "$SCENARIO_LIST" | tr -d '[:space:]')
if [ -z "$SCENARIO_COUNT" ] || [ "$SCENARIO_COUNT" -lt 1 ]; then
  echo "[m46][P0] scenario list is empty" >&2
  exit 10
fi

M46_REPORT="$REPORT_DIR/m46_multi_scenario_report.json"
python3 "$M46_AGGREGATE" \
  --results-file "$RESULTS_FILE" \
  --exceptions "$EXCEPTIONS_SPEC" \
  --out "$M46_REPORT" \
  --label "m46" | tee "$REPORT_DIR/aggregate.log"

REQ_ARGS=()
while IFS=$'\t' read -r name _spec
do
  [ -z "$name" ] && continue
  REQ_ARGS+=(--required-scenario "$name")
done < "$SCENARIO_LIST"

python3 "$M46_VALIDATOR" \
  --report "$M46_REPORT" \
  --min-scenarios "$SCENARIO_COUNT" \
  "${REQ_ARGS[@]}" \
  --expect-pass 1 \
  --label "m46" | tee "$REPORT_DIR/validation.log"

{
  echo "scenarios_spec=$SCENARIOS_SPEC"
  echo "policy_spec=$POLICY_SPEC"
  echo "exceptions_spec=$EXCEPTIONS_SPEC"
  echo "calibration_profile=$CALIB_PROFILE"
  echo "results_file=$RESULTS_FILE"
  echo "report=$M46_REPORT"
  echo "---"
} >> "$MANIFEST"

echo "[m46] PASS"
echo "[m46] manifest: $MANIFEST"
echo "[m46] report: $M46_REPORT"
echo "[m46] validation: $REPORT_DIR/validation.log"
