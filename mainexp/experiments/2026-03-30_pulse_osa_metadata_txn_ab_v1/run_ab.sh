#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

CASES=(
  pulse_shared_line_actual_mfb_gather_preband_metadata_txn_off
  pulse_shared_line_actual_mfb_gather_preband_metadata_txn_rowdescriptor_ttl256
  pulse_shared_line_actual_mfb_gather_preband_metadata_txn_rowidx_ttl256
  pulse_shared_line_actual_mfb_gather_preband_metadata_txn_idx2_ttl256
  pulse_shared_line_actual_mfb_gather_preband_metadata_txn_preband_ttl256
  pulse_shared_line_actual_mfb_gather_preband_metadata_txn_all_ttl256
)

for case_id in "${CASES[@]}"; do
  "$SCRIPT_DIR/run_case.sh" "$case_id"
done

python3 "$SCRIPT_DIR/make_snapshot.py" --cases "$SCRIPT_DIR/cases.json" --out "$SCRIPT_DIR/snapshot/compare.tsv"
echo "[run_ab] snapshot -> $SCRIPT_DIR/snapshot/compare.tsv"
