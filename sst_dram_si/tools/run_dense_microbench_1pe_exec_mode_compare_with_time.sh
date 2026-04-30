#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(cd "$PROJECT_ROOT/.." && pwd)

MODE_RAW="${1:-${MESH_EXEC_MODE:-gas}}"
MODE="$(printf "%s" "$MODE_RAW" | tr '[:upper:]' '[:lower:]')"

case "$MODE" in
  gas|naive_raw) ;;
  *)
    echo "[dense-microbench] invalid exec mode: ${MODE_RAW}"
    echo "usage: $0 [gas|naive_raw]"
    exit 2
    ;;
esac

export MESH_EXEC_MODE="$MODE"
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-1}"

RUN_ROOT="$PROJECT_ROOT/outputs_large/paper2/dense_microbench_1pe_exec_mode_compare/$MODE"
mkdir -p "$RUN_ROOT"

TS=$(date +%Y%m%d-%H%M%S-%N)
RUN_DIR="$RUN_ROOT/$TS"
mkdir -p "$RUN_DIR"
export MESH_RUN_DIR="$RUN_DIR"

select_sst_bin() {
  if [ -n "${SST_BIN:-}" ]; then
    echo "$SST_BIN"
    return 0
  fi
  local sst_mpi="$REPO_ROOT/sst_install_mpi/bin/sst"
  local sst_par="$REPO_ROOT/sst_install/bin/sst"
  local sst_ser="$REPO_ROOT/sst_install_serial/bin/sst"
  if [ -x "$sst_mpi" ] && "$sst_mpi" --version >/dev/null 2>&1; then echo "$sst_mpi"; return 0; fi
  if [ -x "$sst_par" ] && "$sst_par" --version >/dev/null 2>&1; then echo "$sst_par"; return 0; fi
  if [ -x "$sst_ser" ] && "$sst_ser" --version >/dev/null 2>&1; then echo "$sst_ser"; return 0; fi
  if [ -x "$sst_mpi" ]; then echo "$sst_mpi"; return 0; fi
  if [ -x "$sst_par" ]; then echo "$sst_par"; return 0; fi
  if [ -x "$sst_ser" ]; then echo "$sst_ser"; return 0; fi
  return 1
}

SST_BIN="$(select_sst_bin)"
MODEL="$PROJECT_ROOT/microbench_dense_1pe/test_dense_microbench.py"
MODEL_DIR="$PROJECT_ROOT/microbench_dense_1pe"

LOG="$RUN_DIR/mesh_run.log"
TIME_FILE="$RUN_DIR/time.txt"
META_FILE="$RUN_DIR/meta.json"

# Default to 32 ranks to match other experiment runners; override via SST_N if needed.
SST_N="${SST_N:-${MESH_SST_NPROC:-32}}"

( cd "$PROJECT_ROOT" && /usr/bin/time -v -o "$TIME_FILE" "$SST_BIN" -n "$SST_N" "$MODEL" ) > "$LOG" 2>&1

python3 - <<'PY' > "$META_FILE"
import json, os, pathlib

run_dir = pathlib.Path(os.environ["MESH_RUN_DIR"])
project_root = pathlib.Path(os.environ.get("PROJECT_ROOT", "") or ".").resolve()
model_dir = project_root / "microbench_dense_1pe"

cfg_path = model_dir / "local_run_config.json"
cfg = {}
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}

meta = {
    "kind": "dense_microbench_1pe",
    "exec_mode": (os.environ.get("MESH_EXEC_MODE") or "").strip().lower() or "gas",
    "max_steps": int(os.environ.get("MESH_MAX_STEPS") or "0"),
    "sst_n": int(os.environ.get("SST_N") or "1") if (os.environ.get("SST_N") or "").strip() else 1,
    "timebase": "1ps",
    "mesh_size": int(cfg.get("mesh_size", 1)),
    "node_limit": int(cfg.get("node_limit", 1)),
    "num_cores_per_pe": int(cfg.get("num_cores_per_pe", 1)),
    "neurons_per_core": int(cfg.get("neurons_per_core", 500)),
    "disable_network": bool(cfg.get("disable_network", True)),
    "l1_enable": int(bool(cfg.get("l1_enable", 0))),
    "sim_time": str(cfg.get("sim_time", "100us")),
    "allow_zero_firing_long": bool(cfg.get("allow_zero_firing_long", True)),
}

for env_key, meta_key, conv in (
    ("MESH_SIM_TIME", "sim_time_override", str),
    ("MESH_STEP_ACTIVATION_FRACTION", "step_activation_fraction", float),
    ("MESH_STEP_ACTIVATION_FANOUT", "step_activation_fanout", int),
    ("MESH_STEP_ACTIVATION_SEED", "step_activation_seed", int),
    ("MESH_NODE_LIMIT", "node_limit_override", int),
    ("MESH_DENSE_STRICT_CACHELINE", "dense_strict_cacheline_override", str),
    ("MESH_GAS_MERGE_POLICY", "gas_merge_policy_override", str),
    ("MESH_GAS_GAP_K_BYTES", "gas_gap_k_bytes_override", int),
    ("MESH_GAS_LMAX_BYTES", "gas_lmax_bytes_override", int),
    ("MESH_GAS_ROW_WINDOW_BYTES", "gas_row_window_bytes_override", int),
    ("MESH_GAS_ROW_WINDOW_TIMEOUT_NS", "gas_row_window_timeout_ns_override", int),
    ("MESH_GAS_MAX_INFLIGHT", "gas_max_inflight_override", int),
    ("MESH_GAS_WINDOW_CYCLES_GATHER", "gas_window_cycles_gather_override", int),
    ("MESH_GAS_WINDOW_CYCLES_APPLY", "gas_window_cycles_apply_override", int),
    ("MESH_GAS_WINDOW_CYCLES_SCATTER", "gas_window_cycles_scatter_override", int),
):
    v = (os.environ.get(env_key) or "").strip()
    if not v:
        continue
    try:
        meta[meta_key] = conv(v)
    except Exception:
        meta[meta_key + "_raw"] = v

print(json.dumps(meta, indent=2, ensure_ascii=False))
PY

if [ -f "$MODEL_DIR/local_run_config.json" ]; then
  cp "$MODEL_DIR/local_run_config.json" "$RUN_DIR/local_run_config.json"
fi

python3 "$PROJECT_ROOT/tools/compute_essential_summary_mesh.py" --run-dir "$RUN_DIR"
python3 "$PROJECT_ROOT/tools/validate_essential_summary_mesh.py" --run-dir "$RUN_DIR" | tee "$RUN_DIR/validation.log"

echo "[dense-microbench] exec_mode=$MODE max_steps=$MESH_MAX_STEPS run complete: $RUN_DIR"
