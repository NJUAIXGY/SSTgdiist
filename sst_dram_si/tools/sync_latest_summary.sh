#!/usr/bin/env bash
set -euo pipefail
# Sync the latest timestamped run summary into a stable 'latest' dir.
# Usage: tools/sync_latest_summary.sh sst_dram_si/outputs_large/paper2/dram_N1k
RUN_PARENT=${1:-"sst_dram_si/outputs_large/paper2/dram_N1k"}
if [[ ! -d "$RUN_PARENT" ]]; then
  echo "[sync-latest] run-parent not found: $RUN_PARENT" >&2
  exit 1
fi
NEWEST_DIR=$(ls -1d "$RUN_PARENT"/20??????-?????? 2>/dev/null | sort | tail -n 1 || true)
if [[ -z "$NEWEST_DIR" ]]; then
  echo "[sync-latest] no timestamped run directories under $RUN_PARENT" >&2
  exit 1
fi
LATEST_DIR="$RUN_PARENT/latest"
mkdir -p "$LATEST_DIR"
# Copy core artifacts for quick inspection
for f in essential_summary.json local_run_config.json dram_si_stats.csv pe_stage_events_db.csv; do
  if [[ -f "$NEWEST_DIR/$f" ]]; then
    cp -f "$NEWEST_DIR/$f" "$LATEST_DIR/$f"
  fi
done
# Optional: update a symlink latest -> newest
if [[ -L "$RUN_PARENT/latest-link" || -e "$RUN_PARENT/latest-link" ]]; then
  rm -f "$RUN_PARENT/latest-link"
fi
ln -s "$(basename "$NEWEST_DIR")" "$RUN_PARENT/latest-link"
echo "[sync-latest] latest refreshed -> $NEWEST_DIR"
