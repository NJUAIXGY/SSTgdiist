#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."  # go to experimental_features/neuromoe_experiments

SST_ROOT="/home/anarchy/SST"
SCRIPT="$SST_ROOT/experimental_features/neuromoe_experiments/scripts/test_neuromoe_topk_4x4.py"
RES_DIR="$SST_ROOT/experimental_features/neuromoe_experiments/results"

echo "[NeuroMoE] Running sparse Top-k=4 with edges_csv gating..."
NEUROMOE_MODE=edges_csv NEUROMOE_TOPK=4 NEUROMOE_EPS=0.6 \
sst "$SCRIPT" | tee "$RES_DIR/run_edges_k4.log"

echo "[NeuroMoE] Running dense baseline with weight-driven (Top-k=0, epsilon=1e-8)..."
NEUROMOE_MODE=weight_driven NEUROMOE_TOPK=0 NEUROMOE_EPS=1e-8 \
sst "$SCRIPT" | tee "$RES_DIR/run_weight_dense.log"

echo "[NeuroMoE] Runs completed. Stats CSVs written under $RES_DIR"

