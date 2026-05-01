#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

"$SCRIPT_DIR/run_case.sh" rowindex_stress_off || true
"$SCRIPT_DIR/run_case.sh" rowindex_stress_on || true

python3 "$SCRIPT_DIR/make_snapshot.py" \
  --cases "$SCRIPT_DIR/cases.json" \
  --out "$SCRIPT_DIR/snapshot/compare.tsv"
