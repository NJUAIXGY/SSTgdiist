#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
RUNNER="$SCRIPT_DIR/run_spiketile_with_time.sh"

if [ ! -x "$RUNNER" ]; then
  echo "[spiketile-matrix] ERROR: runner not executable: $RUNNER" >&2
  exit 2
fi

DATASET_DEFAULT="$PROJECT_ROOT/weights/bcsr_global_16pe_fanout256_10k_rowpack_v1"
DATASET="${MESH_BCSR_DIR:-$DATASET_DEFAULT}"
if [ ! -d "$DATASET" ]; then
  echo "[spiketile-matrix] ERROR: dataset missing: $DATASET" >&2
  exit 2
fi

MESH_MAX_STEPS="${MESH_MAX_STEPS:-2}"
MESH_STEP_ACTIVATION_FRACTION="${MESH_STEP_ACTIVATION_FRACTION:-0.01}"
MESH_STEP_ACTIVATION_SEED="${MESH_STEP_ACTIVATION_SEED:-314159}"
MESH_SST_NPROC="${MESH_SST_NPROC:-32}"
MESH_VALIDATE_PROFILE="${MESH_VALIDATE_PROFILE:-paper}"
MESH_QUIET="${MESH_QUIET:-1}"
MESH_MULTICAST_BLOCK_W="${MESH_MULTICAST_BLOCK_W:-2}"
MESH_MULTICAST_BLOCK_H="${MESH_MULTICAST_BLOCK_H:-2}"
MESH_EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS="${MESH_EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS:-64}"
MESH_EXPERIMENTAL_SPIKETILE_BLOCK_COLS="${MESH_EXPERIMENTAL_SPIKETILE_BLOCK_COLS:-16}"
MESH_EXPERIMENTAL_COMPACT_MASK_ENABLE="${MESH_EXPERIMENTAL_COMPACT_MASK_ENABLE:-0}"
MESH_EXPERIMENTAL_INTER_BUNDLE_ENABLE="${MESH_EXPERIMENTAL_INTER_BUNDLE_ENABLE:-0}"
MESH_EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES="${MESH_EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES:-64}"
MESH_LOADER_CHUNK_BYTES="${MESH_LOADER_CHUNK_BYTES:-65536}"
MESH_SWEEP_REPEATS="${MESH_SWEEP_REPEATS:-1}"

OUT_ROOT="${SPIKETILE_COMPARE_OUT_ROOT:-$SCRIPT_DIR/outputs/compare_matrix}"
mkdir -p "$OUT_ROOT"

run_one() {
  local tag="$1"
  local multicast_enable="$2"
  local spiketile_enable="$3"
  local spikekey_fastpath_enable="$4"
  local run_root="$OUT_ROOT/$tag"
  mkdir -p "$run_root"

  echo "[spiketile-matrix] run tag=$tag multicast=$multicast_enable spiketile=$spiketile_enable spikekey_fastpath=$spikekey_fastpath_enable"
  MESH_RUN_ROOT="$run_root" \
  MESH_EXEC_MODE="gas" \
  MESH_MAX_STEPS="$MESH_MAX_STEPS" \
  MESH_STEP_ACTIVATION_FRACTION="$MESH_STEP_ACTIVATION_FRACTION" \
  MESH_STEP_ACTIVATION_SEED="$MESH_STEP_ACTIVATION_SEED" \
  MESH_STEP_RESET_MEM_EACH_STEP="1" \
  MESH_ALLOW_ZERO_FIRING_LONG="1" \
  MESH_GAS_STEP_SEQ_GATE_ENABLE="1" \
  MESH_BCSR_DIR="$DATASET" \
  MESH_BCSR_LAYOUT_MODE="rowpack_v1" \
  MESH_BCSR_BLOCK_FETCH_MODE="row_cacheline" \
  MESH_LOADER_CHUNK_BYTES="$MESH_LOADER_CHUNK_BYTES" \
  MESH_MULTICAST_ENABLE="$multicast_enable" \
  MESH_MULTICAST_BLOCK_W="$MESH_MULTICAST_BLOCK_W" \
  MESH_MULTICAST_BLOCK_H="$MESH_MULTICAST_BLOCK_H" \
  MESH_EXPERIMENTAL_SPIKETILE_ENABLE="$spiketile_enable" \
  MESH_EXPERIMENTAL_SPIKEKEY_FASTPATH_ENABLE="$spikekey_fastpath_enable" \
  MESH_EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS="$MESH_EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS" \
  MESH_EXPERIMENTAL_SPIKETILE_BLOCK_COLS="$MESH_EXPERIMENTAL_SPIKETILE_BLOCK_COLS" \
  MESH_EXPERIMENTAL_COMPACT_MASK_ENABLE="$MESH_EXPERIMENTAL_COMPACT_MASK_ENABLE" \
  MESH_EXPERIMENTAL_INTER_BUNDLE_ENABLE="$MESH_EXPERIMENTAL_INTER_BUNDLE_ENABLE" \
  MESH_EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES="$MESH_EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES" \
  MESH_SST_NPROC="$MESH_SST_NPROC" \
  MESH_VALIDATE_PROFILE="$MESH_VALIDATE_PROFILE" \
  MESH_QUIET="$MESH_QUIET" \
  "$RUNNER"
}

for i in $(seq 1 "$MESH_SWEEP_REPEATS"); do
  echo "[spiketile-matrix] repeat $i/$MESH_SWEEP_REPEATS"
  run_one "A_spike_unicast" 0 0 0
  run_one "B_spikekey_multicast" 1 0 0
  run_one "B_spikekey_multicast_p0" 1 0 1
  run_one "C_spiketilekey_multicast" 1 1 0
  run_one "C_spiketilekey_multicast_p0" 1 1 1
done

python3 - "$OUT_ROOT" <<'PY'
import json
import os
import glob
import sys

out_root = sys.argv[1]
tags = [
    ("A_spike_unicast", "Spike(unicast)"),
    ("B_spikekey_multicast", "SpikeKey"),
    ("B_spikekey_multicast_p0", "SpikeKey+P0"),
    ("C_spiketilekey_multicast", "SpikeTileKey(B)"),
    ("C_spiketilekey_multicast_p0", "SpikeTileKey(B)+P0"),
]

print("[spiketile-matrix] summary")
print("tag,run_dir,sim_time_actual_ns,memory_bytes,memctrl.bytes_est_total,total_spikes_processed,snn_tx.spike_packets_total,snn_tx.spikekey_packets_total,snn_tx.spiketilekey_packets_total,snn_rx.spike_packets_total,snn_rx.spikekey_packets_total,snn_rx.spiketilekey_packets_total,snn_rx.fastpath_packets_total,snn_rx.fallback_packets_total")
for tag, label in tags:
    run_root = os.path.join(out_root, tag)
    candidates = sorted(glob.glob(os.path.join(run_root, "*")))
    run_dir = candidates[-1] if candidates else ""
    summary_path = os.path.join(run_dir, "essential_summary_mesh.json") if run_dir else ""
    if not run_dir or not os.path.isfile(summary_path):
        print(f"{label},(missing),-,-,-,-,-,-,-")
        continue

    with open(summary_path, "r", encoding="utf-8") as f:
        s = json.load(f)

    def pick(summary, *paths):
        for path in paths:
            cur = summary
            ok = True
            for key in path.split("."):
                if not isinstance(cur, dict):
                    ok = False
                    break
                cur = cur.get(key)
            if ok and cur is not None:
                return cur
        return ""

    sim_ns = pick(s, "sim_time_actual_ns", "model.sim_time_actual_ns")
    mem_bytes = pick(s, "memory_bytes", "memory.memory_bytes")
    mc_bytes = pick(s, "memctrl.bytes_est_total", "memhierarchy.memctrl.bytes_est_total")
    spikes = pick(s, "total_spikes_processed", "spike_activity.total_spikes_processed")
    tx_sp = pick(s, "snn_tx.spike_packets_total")
    tx_key = pick(s, "snn_tx.spikekey_packets_total")
    tx_tile = pick(s, "snn_tx.spiketilekey_packets_total")
    rx_sp = pick(s, "snn_rx.spike_packets_total")
    rx_key = pick(s, "snn_rx.spikekey_packets_total")
    rx_tile = pick(s, "snn_rx.spiketilekey_packets_total")
    fp = pick(s, "snn_rx.fastpath_packets_total")
    fb = pick(s, "snn_rx.fallback_packets_total")
    print(f"{label},{run_dir},{sim_ns},{mem_bytes},{mc_bytes},{spikes},{tx_sp},{tx_key},{tx_tile},{rx_sp},{rx_key},{rx_tile},{fp},{fb}")
PY

echo "[spiketile-matrix] done. outputs: $OUT_ROOT"
