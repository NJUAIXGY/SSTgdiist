#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

CASES=(
  rowindex_object_off
  rowindex_object_on
)

for case_id in "${CASES[@]}"; do
  "$SCRIPT_DIR/run_case.sh" "$case_id"
done

python3 "$SCRIPT_DIR/make_snapshot.py" --cases "$SCRIPT_DIR/cases.json" --out "$SCRIPT_DIR/snapshot/compare.tsv"
echo "[run_ab] snapshot -> $SCRIPT_DIR/snapshot/compare.tsv"
echo "[run_ab] gate_tsv -> $SCRIPT_DIR/snapshot/gate_summary.tsv"
echo "[run_ab] gate_json -> $SCRIPT_DIR/snapshot/gate_summary.json"
