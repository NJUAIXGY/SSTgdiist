#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

OUT_ROOT="${OUT_ROOT:-$SCRIPT_DIR/runs/nip_ablation_$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT_ROOT"

if [ -n "${SST_BIN:-}" ]; then
  SST_BIN="$SST_BIN"
elif [ -x "$REPO_ROOT/sst_install_serial/bin/sst" ]; then
  SST_BIN="$REPO_ROOT/sst_install_serial/bin/sst"
else
  SST_BIN="$REPO_ROOT/sst_install_mpi/bin/sst"
fi

RAM2_CFG="${RAM2_CFG:-$REPO_ROOT/sst_dram_si/configs/ramulator2_ddr5_notrans.cfg}"
BCSR_DIR="${BCSR_DIR:-$REPO_ROOT/sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2}"
GCSS2_DIR="${GCSS2_DIR:-$REPO_ROOT/sst_dram_si/weights/gcss_valueonly_dstcore_idx2_rowmphf_fanout256_10k_v2_j32}"

SEEDS="${SEEDS:-271828}"
MESH_SST_NPROC="${MESH_SST_NPROC:-1}"
RUN_TIMEOUT_SEC="${RUN_TIMEOUT_SEC:-0}"
MAX_STEPS="${MAX_STEPS:-1}"
CORES_PER_PE="${CORES_PER_PE:-20}"
NEURONS_PER_CORE="${NEURONS_PER_CORE:-500}"
MESH_SIZE="${MESH_SIZE:-4}"
CASES="${CASES:-}"

if [ ! -x "$SST_BIN" ]; then
  echo "[nip-ablation] SST binary not found/executable: $SST_BIN" >&2
  exit 2
fi
if [ ! -f "$RAM2_CFG" ]; then
  echo "[nip-ablation] ramulator2 config not found: $RAM2_CFG" >&2
  exit 2
fi
if [ ! -d "$BCSR_DIR" ]; then
  echo "[nip-ablation] bcsr dir not found: $BCSR_DIR" >&2
  exit 2
fi
if [ ! -d "$GCSS2_DIR" ]; then
  echo "[nip-ablation] gcss2 dir not found: $GCSS2_DIR" >&2
  exit 2
fi

cases=(
  "A_baseline_off:0:4:4096:1:0"
  "B_nip_on_default:1:4:4096:1:0"
  "C_nip_on_tail_guard:1:4:4096:1:1"
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

build_gcss2_overrides_json() {
  local mesh_size="$1"
  local total_pes=$((mesh_size * mesh_size))
  local gcss2="$2"
  local json='['
  json+='{"match":{"role":"pe.core"},"params":{"synapse_weight_mode":"gcss_valueonly_dstcore_idx2","gcss_index_template":"'"$gcss2"'/pe{pe:02d}/core{core:02d}.gcss2.idx.bin"},"strict":true}'
  local pe
  for ((pe=0; pe<total_pes; pe++)); do
    local pe2
    pe2=$(printf "%02d" "$pe")
    json+=',{"match":{"role":"weight_loader","tags":{"pe":'"$pe"'}},"params":{"weight_format":"raw","per_core_files":1,"file_template":"'"$gcss2"'/pe'"$pe2"'/core{core:02d}.gcss2.bin","validate_length":0,"bcsr_enable":0},"strict":true}'
  done
  json+=']'
  printf '%s' "$json"
}

for item in "${cases[@]}"; do
  IFS=":" read -r CASE_NAME NIP_ENABLE NIP_BUDGET NIP_CACHE_ENTRIES NIP_GATHER_ONLY NIP_TAIL_GUARD <<<"$item"
  if ! should_run_case "$CASE_NAME"; then
    echo "[nip-ablation] skip case=$CASE_NAME (filtered by CASES='$CASES')"
    continue
  fi

  for SEED in $SEEDS; do
    CASE_ROOT="$OUT_ROOT/$CASE_NAME/seed_${SEED}"
    SPEC_PATH="$CASE_ROOT/spec.json"
    mkdir -p "$CASE_ROOT"
    OVERRIDES_JSON="$(build_gcss2_overrides_json "$MESH_SIZE" "$GCSS2_DIR")"
    cat > "$SPEC_PATH" <<JSON
{
  "schema_version": 3,
  "model": "mesh",
  "platform": {
    "mesh_size": $MESH_SIZE,
    "exec_mode": "gas",
    "stop": { "mode": "step_limited", "max_steps": $MAX_STEPS }
  },
  "workload": { "type": "snn" },
  "loader": {
    "chunk_bytes": 4096
  },
  "pe": {
    "num_cores_per_pe": $CORES_PER_PE,
    "neurons_per_core": $NEURONS_PER_CORE,
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
      "experimental_idx2_ingress_prefetch_enable": $NIP_ENABLE,
      "experimental_idx2_ingress_prefetch_budget_per_tick": $NIP_BUDGET,
      "experimental_idx2_ingress_prefetch_cache_entries": $NIP_CACHE_ENTRIES,
      "experimental_idx2_ingress_prefetch_gather_only": $NIP_GATHER_ONLY,
      "experimental_idx2_ingress_tail_guard_enable": $NIP_TAIL_GUARD
    }
  },
  "overrides": $OVERRIDES_JSON
}
JSON

    echo "[nip-ablation] run case=$CASE_NAME seed=$SEED max_steps=$MAX_STEPS cores=$CORES_PER_PE npc=$NEURONS_PER_CORE"
    set +e
    if [ "$RUN_TIMEOUT_SEC" -gt 0 ]; then
      MESH_RUN_ROOT="$CASE_ROOT/run" \
      MESH_SST_NPROC="$MESH_SST_NPROC" \
      SST_BIN="$SST_BIN" \
      MESH_VALIDATE_PROFILE="dev" \
      MESH_EXPERIMENTAL_ENABLE="1" \
      MESH_BCSR_DIR="$BCSR_DIR" \
      MESH_GCSS2_DIR="$GCSS2_DIR" \
      timeout --foreground "$RUN_TIMEOUT_SEC" \
        "$REPO_ROOT/sst_dram_si/tools/run_mesh_with_time.sh" --spec "$SPEC_PATH"
      RUN_RC=$?
    else
      MESH_RUN_ROOT="$CASE_ROOT/run" \
      MESH_SST_NPROC="$MESH_SST_NPROC" \
      SST_BIN="$SST_BIN" \
      MESH_VALIDATE_PROFILE="dev" \
      MESH_EXPERIMENTAL_ENABLE="1" \
      MESH_BCSR_DIR="$BCSR_DIR" \
      MESH_GCSS2_DIR="$GCSS2_DIR" \
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
        echo "[nip-ablation] timeout case=$CASE_NAME seed=$SEED sec=$RUN_TIMEOUT_SEC"
      else
        echo "$CASE_NAME,$SEED,$RUN_RC,run_error" >> "$FAILED_CSV"
        echo "[nip-ablation] failed case=$CASE_NAME seed=$SEED rc=$RUN_RC"
      fi
      continue
    fi

    RUN_DIR=$(ls -1dt "$CASE_ROOT/run"/* 2>/dev/null | head -n 1 || true)
    if [ -z "$RUN_DIR" ]; then
      if [ ! -f "$FAILED_CSV" ]; then
        echo "case,seed,run_rc,reason" > "$FAILED_CSV"
      fi
      echo "$CASE_NAME,$SEED,3,missing_run_dir" >> "$FAILED_CSV"
      echo "[nip-ablation] cannot locate run dir: $CASE_ROOT/run"
      continue
    fi

    python3 "$SCRIPT_DIR/analyze_nip_ablation.py" collect \
      --run-dir "$RUN_DIR" \
      --case "$CASE_NAME" \
      --seed "$SEED" \
      --out-csv "$ROWS_CSV"
  done
done

if [ ! -f "$ROWS_CSV" ]; then
  echo "[nip-ablation] no successful runs, skip aggregate"
  exit 4
fi

python3 "$SCRIPT_DIR/analyze_nip_ablation.py" aggregate \
  --in-csv "$ROWS_CSV" \
  --baseline-case "A_baseline_off" \
  --out-csv "$AGG_CSV" \
  --out-json "$AGG_JSON"

echo "[nip-ablation] completed"
echo "[nip-ablation] rows: $ROWS_CSV"
echo "[nip-ablation] aggregate: $AGG_CSV"
echo "[nip-ablation] aggregate: $AGG_JSON"
if [ -f "$FAILED_CSV" ]; then
  echo "[nip-ablation] failed runs: $FAILED_CSV"
fi
