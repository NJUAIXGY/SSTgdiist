#!/usr/bin/env bash
set -euo pipefail

# Run strict-GAS baseline for N=1k under outputs_large/paper2/dram_N1k
# This script temporarily swaps local_run_config.json, runs, then restores it.

ROOT_DIR=$(cd "$(dirname "$0")" && pwd)
CFG_SRC="$ROOT_DIR/configs/local_run_N1k_baseline.json"
CFG_DST="$ROOT_DIR/local_run_config.json"
BACKUP="$ROOT_DIR/local_run_config.json.prev"

if [[ ! -f "$CFG_SRC" ]]; then
  echo "[1k-baseline] Missing config: $CFG_SRC" >&2
  exit 1
fi

echo "[1k-baseline] Backing up current local_run_config.json to: $BACKUP"
cp -f "$CFG_DST" "$BACKUP" 2>/dev/null || true
echo "[1k-baseline] Installing baseline config: $CFG_SRC -> $CFG_DST"
cp -f "$CFG_SRC" "$CFG_DST"

echo "[1k-baseline] Running..."
"$ROOT_DIR/run_singlepe_with_time.sh"

echo "[1k-baseline] Restore previous local_run_config.json"
if [[ -f "$BACKUP" ]]; then
  mv -f "$BACKUP" "$CFG_DST"
fi

echo "[1k-baseline] Done. See outputs under: $ROOT_DIR/outputs_large/paper2/dram_N1k/latest"

