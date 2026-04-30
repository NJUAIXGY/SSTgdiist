#!/usr/bin/env bash
set -euo pipefail

# Usage: ./run_48threads.sh <mesh=4|8> <scenario=baseline|slice|gas|sram> <threads=40> [partitioner=simple]
MESH_SIZE=${1:-4}
SCENARIO=${2:-baseline}
THREADS=${3:-40}
PART=${4:-simple}

echo "Running ${MESH_SIZE}x${MESH_SIZE} mesh with ${THREADS} threads, scenario=${SCENARIO}, partitioner=${PART}"

# Optional allocator (tcmalloc) if available
TCMALLOC="/usr/lib/x86_64-linux-gnu/libtcmalloc.so.4"
if [[ -f "$TCMALLOC" ]]; then
  export LD_PRELOAD="$TCMALLOC"
  echo "Using tcmalloc: $TCMALLOC"
fi

# NUMA bind (single socket but keep locality)
if command -v numactl >/dev/null 2>&1; then
  NUMACTL_PREFIX=(numactl --cpunodebind=0 --membind=0)
else
  NUMACTL_PREFIX=()
fi

# Prefer high-performance config overrides
CFG="$(dirname "$0")/config_48threads.json"
if [[ -f "$CFG" ]]; then
  cp -f "$CFG" "$(dirname "$0")/local_run_config.json"
fi

LOGDIR="sst_output_data"
mkdir -p "$LOGDIR"
OUT_LOG="$LOGDIR/mesh${MESH_SIZE}x${MESH_SIZE}_${SCENARIO}_t${THREADS}.log"
OUT_TIME="$LOGDIR/mesh${MESH_SIZE}x${MESH_SIZE}_${SCENARIO}_t${THREADS}.time"
RUN_DIR="$(dirname "$0")/outputs_large/${SCENARIO}_m${MESH_SIZE}_20us"
mkdir -p "$RUN_DIR"

"/usr/bin/time" -f 'WALL=%E USER=%U SYS=%S MAXRSS=%M' -o "$OUT_TIME" \
  "${NUMACTL_PREFIX[@]}" \
  "/home/xgy/remote/sst_install/bin/sst" -n "$THREADS" --partitioner="$PART" \
  "$(dirname "$0")/test_noc_timestep.py" -- \
  --scenario "$SCENARIO" --mesh "$MESH_SIZE" --time 20us --bw 40GiB/s --firing 0.0005 \
  > "$OUT_LOG" 2>&1

cp -f "$OUT_TIME" "$RUN_DIR/last_run.time" || true

echo "Done. Time: $(cat "$OUT_TIME")"
echo "RunDir: $RUN_DIR"
echo "Stats: $RUN_DIR/noc_timestep_stats.csv"
echo "Spikes: $RUN_DIR/spikes.csv"
