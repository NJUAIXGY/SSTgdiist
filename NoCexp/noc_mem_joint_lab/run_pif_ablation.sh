#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

OUT_ROOT="${OUT_ROOT:-$SCRIPT_DIR/runs/pif_ablation_$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT_ROOT"

if [ -n "${SST_BIN:-}" ]; then
  SST_BIN="$SST_BIN"
elif [ -x "$REPO_ROOT/sst_install_serial/bin/sst" ]; then
  SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst"
else
  SST_BIN="$REPO_ROOT/sst_install_mpi/bin/sst"
fi
RAM2_CFG="${RAM2_CFG:-$REPO_ROOT/sst_dram_si/configs/ramulator2_ddr5_notrans.cfg}"
SEEDS="${SEEDS:-271828 271829}"
MESH_SST_NPROC="${MESH_SST_NPROC:-1}"
RUN_TIMEOUT_SEC="${RUN_TIMEOUT_SEC:-0}"
MAX_STEPS_OVERRIDE="${MAX_STEPS_OVERRIDE:-}"
CASES="${CASES:-}"

if [ ! -x "$SST_BIN" ]; then
  echo "[pif-ablation] SST binary not found/executable: $SST_BIN" >&2
  exit 2
fi
if [ ! -f "$RAM2_CFG" ]; then
  echo "[pif-ablation] ramulator2 config not found: $RAM2_CFG" >&2
  exit 2
fi

cases=(
  "A_baseline_off:0:4:1024:1:1:0:32:16:1"
  "B_pif_on_default:1:4:1024:1:1:0:32:16:1"
  "C_pif_on_hot_adapt:1:4:1024:1:2:1:24:8:1"
)

ROWS_CSV="$OUT_ROOT/summary_rows.csv"
AGG_CSV="$OUT_ROOT/summary_agg.csv"
AGG_JSON="$OUT_ROOT/summary_agg.json"
FAILED_CSV="$OUT_ROOT/failed_runs.csv"

should_run_case() {
  local case_name="$1"
  if [ -z "$CASES" ]; then
    return 0
  fi
  for c in $CASES; do
    if [ "$c" = "$case_name" ]; then
      return 0
    fi
  done
  return 1
}

for item in "${cases[@]}"; do
  IFS=":" read -r CASE_NAME PIF_ENABLE PIF_BUDGET PIF_CACHE_ROWS PIF_GATHER_ONLY PIF_HOT_TOUCH_MIN PIF_BUDGET_ADAPT_ENABLE PIF_BUDGET_ADAPT_MAX PIF_BUDGET_ADAPT_Q_DEPTH MAX_STEPS <<<"$item"
  if ! should_run_case "$CASE_NAME"; then
    echo "[pif-ablation] skip case=$CASE_NAME (filtered by CASES='$CASES')"
    continue
  fi
  if [ -n "$MAX_STEPS_OVERRIDE" ]; then
    MAX_STEPS="$MAX_STEPS_OVERRIDE"
  fi
  for SEED in $SEEDS; do
    CASE_ROOT="$OUT_ROOT/$CASE_NAME/seed_${SEED}"
    SPEC_PATH="$CASE_ROOT/spec.json"
    mkdir -p "$CASE_ROOT"
    cat > "$SPEC_PATH" <<JSON
{
  "schema_version": 3,
  "model": "mesh",
  "platform": {
    "mesh_size": 4,
    "exec_mode": "gas",
    "stop": { "mode": "step_limited", "max_steps": $MAX_STEPS }
  },
  "workload": { "type": "snn" },
  "loader": {
    "chunk_bytes": 4096
  },
  "pe": {
    "num_cores_per_pe": 20,
    "neurons_per_core": 500,
    "core": {
      "apply_dense_acc_enable": true,
      "memory_warmup_cycles": 200,
      "loader_barrier_cycles": 0
    }
  },
  "memory": {
    "type": "memHierarchy",
    "backend": {
      "type": "ramulator2",
      "config_file": "$RAM2_CFG"
    }
  },
  "gas": {
    "merge_policy": "cacheline",
    "max_inflight": 128,
    "apply_bank_credit": 0,
    "window_cycles": { "gather": 200, "apply": 40, "scatter": 40 }
  },
  "step": {
    "random_activation_enable": 1,
    "activation_fraction": 0.0002,
    "activation_fanout": 256,
    "activation_seed": $SEED,
    "activation_use_bcsr_routes": true
  },
  "components": {
    "pe.core": {
      "window_read_enable": 1,
      "window_read_budget": 8192,
      "experimental_noc_rowidx_prefetch_enable": $PIF_ENABLE,
      "experimental_noc_rowidx_prefetch_budget_per_tick": $PIF_BUDGET,
      "experimental_noc_rowidx_cache_rows": $PIF_CACHE_ROWS,
      "experimental_noc_rowidx_prefetch_gather_only": $PIF_GATHER_ONLY,
      "experimental_noc_rowidx_hot_touch_min": $PIF_HOT_TOUCH_MIN,
      "experimental_noc_rowidx_budget_adapt_enable": $PIF_BUDGET_ADAPT_ENABLE,
      "experimental_noc_rowidx_budget_adapt_max_per_tick": $PIF_BUDGET_ADAPT_MAX,
      "experimental_noc_rowidx_budget_adapt_q_depth": $PIF_BUDGET_ADAPT_Q_DEPTH
    }
  }
}
JSON

    echo "[pif-ablation] run case=$CASE_NAME seed=$SEED max_steps=$MAX_STEPS"
    set +e
    if [ "$RUN_TIMEOUT_SEC" -gt 0 ]; then
      MESH_RUN_ROOT="$CASE_ROOT/run" \
      MESH_SST_NPROC="$MESH_SST_NPROC" \
      SST_BIN="$SST_BIN" \
        timeout --foreground "$RUN_TIMEOUT_SEC" \
        "$REPO_ROOT/sst_dram_si/tools/run_mesh_with_time.sh" --spec "$SPEC_PATH"
      RUN_RC=$?
    else
      MESH_RUN_ROOT="$CASE_ROOT/run" \
      MESH_SST_NPROC="$MESH_SST_NPROC" \
      SST_BIN="$SST_BIN" \
        "$REPO_ROOT/sst_dram_si/tools/run_mesh_with_time.sh" --spec "$SPEC_PATH"
      RUN_RC=$?
    fi
    set -e
    if [ "$RUN_RC" -ne 0 ]; then
      if [ ! -f "$FAILED_CSV" ]; then
        echo "case,seed,run_rc,reason" > "$FAILED_CSV"
      fi
      if [ "$RUN_RC" -eq 124 ]; then
        echo "$CASE_NAME,$SEED,$RUN_RC,timeout" >> "$FAILED_CSV"
        echo "[pif-ablation] timeout case=$CASE_NAME seed=$SEED sec=$RUN_TIMEOUT_SEC"
      else
        echo "$CASE_NAME,$SEED,$RUN_RC,run_error" >> "$FAILED_CSV"
        echo "[pif-ablation] failed case=$CASE_NAME seed=$SEED rc=$RUN_RC"
      fi
      continue
    fi

    RUN_DIR=$(ls -1dt "$CASE_ROOT/run"/* 2>/dev/null | head -n 1 || true)
    if [ -z "$RUN_DIR" ]; then
      if [ ! -f "$FAILED_CSV" ]; then
        echo "case,seed,run_rc,reason" > "$FAILED_CSV"
      fi
      echo "$CASE_NAME,$SEED,3,missing_run_dir" >> "$FAILED_CSV"
      echo "[pif-ablation] cannot locate run dir: $CASE_ROOT/run"
      continue
    fi

    python3 "$SCRIPT_DIR/analyze_pif_ablation.py" collect \
      --run-dir "$RUN_DIR" \
      --case "$CASE_NAME" \
      --seed "$SEED" \
      --out-csv "$ROWS_CSV"
  done
done

if [ ! -f "$ROWS_CSV" ]; then
  echo "[pif-ablation] no successful runs, skip aggregate"
  exit 4
fi

python3 "$SCRIPT_DIR/analyze_pif_ablation.py" aggregate \
  --in-csv "$ROWS_CSV" \
  --baseline-case "A_baseline_off" \
  --out-csv "$AGG_CSV" \
  --out-json "$AGG_JSON"

echo "[pif-ablation] completed"
echo "[pif-ablation] rows: $ROWS_CSV"
echo "[pif-ablation] aggregate: $AGG_CSV"
echo "[pif-ablation] aggregate: $AGG_JSON"
if [ -f "$FAILED_CSV" ]; then
  echo "[pif-ablation] failed runs: $FAILED_CSV"
fi
