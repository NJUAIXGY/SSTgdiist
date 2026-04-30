#!/usr/bin/env bash
set -euo pipefail

# GAS merge-parameter calibration runner (Step=4, read-only freeze, strict-step).
#
# Purpose:
#   Calibrate fine/coarse merging knobs (gap_k / Lmax / row_window_bytes / timeout_ns)
#   across different memory backends (simple vs ramulator2 configs).
#
# Outputs:
#   outputs_large/paper2/${MESH_GAS_CAL_RUN_GROUP}/...
#   plus a compact TSV:
#     <group>/calibration_results.tsv
#
# Safety:
#   - No new BCSR datasets are generated (reuse weights/*_10k).
#   - Quiet mode by default to reduce IO noise.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SST_PREFIX_DEFAULT="$PROJECT_ROOT/../sst_install_mpi"
export SST_INSTALL_PREFIX="${SST_INSTALL_PREFIX:-$SST_PREFIX_DEFAULT}"
SST_BIN="${MESH_SST_BIN:-$SST_INSTALL_PREFIX/bin/sst}"
if ! "$SST_BIN" --version >/dev/null 2>&1; then
  SST_INSTALL_PREFIX="$SST_PREFIX_DEFAULT"
  SST_BIN="$SST_INSTALL_PREFIX/bin/sst"
fi
if ! "$SST_BIN" --version >/dev/null 2>&1; then
  echo "[gas-cal] ERROR: SST binary not runnable. Tried: ${MESH_SST_BIN:-$SST_INSTALL_PREFIX/bin/sst} and fallback: $SST_BIN"
  exit 2
fi

# Isolate runtime env (avoid stale LD_LIBRARY_PATH from interactive shells).
export PATH="$SST_INSTALL_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$SST_INSTALL_PREFIX/lib:$SST_INSTALL_PREFIX/lib64:${LD_LIBRARY_PATH:-}"

# -------- Common invariants --------
export MESH_EXEC_MODE="gas"
export MESH_MAX_STEPS="${MESH_MAX_STEPS:-4}"
export MESH_L1_ENABLE="${MESH_L1_ENABLE:-0}"

# Keep cacheline as the default semantics for calibration (row/DMA is a different hardware assumption).
export MESH_GAS_MERGE_POLICY="${MESH_GAS_MERGE_POLICY:-cacheline}"

export MESH_STEP_ACTIVATION_SEED="${MESH_STEP_ACTIVATION_SEED:-314159}"
export MESH_STEP_ACTIVATION_FANOUT="${MESH_STEP_ACTIVATION_FANOUT:-256}"
export MESH_STEP_ACTIVATION_FRACTION="${MESH_STEP_ACTIVATION_FRACTION:-0.03}"

export MESH_GLOBAL_STEP_SYNC="1"
export MESH_GLOBAL_STEP_DONE_POLICY="${MESH_GLOBAL_STEP_DONE_POLICY:-drain}"
export MESH_GLOBAL_STEP_DRAIN_MIN_CYCLES="${MESH_GLOBAL_STEP_DRAIN_MIN_CYCLES:-200}"
export MESH_GAS_STEP_SEQ_GATE_ENABLE="${MESH_GAS_STEP_SEQ_GATE_ENABLE:-1}"

export MESH_FREEZE_READONLY="1"
export MESH_READONLY_V_THRESH="${MESH_READONLY_V_THRESH:-1000000000.0}"
export MESH_READONLY_TAU_MEM="${MESH_READONLY_TAU_MEM:-0.001}"
export MESH_STEP_RESET_MEM_EACH_STEP="1"
export MESH_ALLOW_ZERO_FIRING_LONG="1"

export MESH_VALIDATE_PROFILE="${MESH_VALIDATE_PROFILE:-paper}"
export MESH_QUIET="${MESH_QUIET:-1}"

# Calibration consistency: force staging even when k/rowwin/tmo are zero so we
# always exercise the full GAS gather/apply segmentation path (baseline included).
export MESH_GAS_FORCE_DEFER="${MESH_GAS_FORCE_DEFER:-1}"

export MESH_BCSR_DIR="${MESH_BCSR_DIR:-$PROJECT_ROOT/weights/bcsr_global_16pe_fanout256_10k}"
if [ ! -d "$MESH_BCSR_DIR" ]; then
  echo "[gas-cal] ERROR: missing weights dir: $MESH_BCSR_DIR"
  exit 2
fi

MODEL="$PROJECT_ROOT/test_mesh_4x4.py"

GROUP="${MESH_GAS_CAL_RUN_GROUP:-dram_mesh_4x4_bcsr10k_readonly_step4_gas_merge_calibration_phaseB_v2}"
OUT_BASE="$PROJECT_ROOT/outputs_large/paper2/$GROUP"
mkdir -p "$OUT_BASE"

RESULTS_TSV="$OUT_BASE/calibration_results.tsv"
if [ ! -f "$RESULTS_TSV" ]; then
  printf '%s\n' $'backend\tcfg\tgap_k\tlmax\trow_window_bytes\trow_window_timeout_ns\trun_dir\tverdict\tmemctrl_bytes\tmemctrl_gets\tgas_payload_bytes\tgas_unique_bytes\tgas_overfetch_ratio\trow_hit_rate\tavg_read_lat\tsim_cycles\twall_s' > "$RESULTS_TSV"
fi

# Sweep mode:
#   - two_phase (default): fine sweep (k,lmax with rowwin=0,tmo=0) then coarse sweep (rowwin,tmo) on best (k,lmax).
#   - fine_only: only fine sweep.
#   - full_grid: cartesian product of (k,lmax,rowwin,tmo) (can explode; not recommended).
SWEEP_MODE="${MESH_CAL_SWEEP_MODE:-two_phase}"

# Optional safety timeout for each SST run (seconds). 0=disabled.
RUN_TIMEOUT_SEC="${MESH_CAL_SST_TIMEOUT_SEC:-0}"

# Parameter grids (env override available).
# NOTE: Keep defaults intentionally bounded to avoid accidental huge sweeps.
K_LIST="${MESH_CAL_GAP_K_LIST:-0 128 256 512 1024}"
LMAX_LIST="${MESH_CAL_LMAX_LIST:-4096 8192 16384}"
ROWWIN_LIST="${MESH_CAL_ROWWIN_LIST:-0 512 1024 2048 4096}"
TMO_LIST="${MESH_CAL_ROWWIN_TIMEOUT_LIST:-0 50 100 200}"

BACKENDS="${MESH_CAL_BACKENDS:-ram2_ddr4_openrow ram2_hbm2_notrans ram2_ddr5_notrans}"

echo "[gas-cal] group=$GROUP"
echo "[gas-cal] fraction=$MESH_STEP_ACTIVATION_FRACTION fanout=$MESH_STEP_ACTIVATION_FANOUT steps=$MESH_MAX_STEPS seed=$MESH_STEP_ACTIVATION_SEED l1=$MESH_L1_ENABLE"
echo "[gas-cal] K_LIST=($K_LIST)"
echo "[gas-cal] LMAX_LIST=($LMAX_LIST)"
echo "[gas-cal] ROWWIN_LIST=($ROWWIN_LIST) TMO_LIST=($TMO_LIST)"
echo "[gas-cal] BACKENDS=($BACKENDS)"
echo "[gas-cal] RUN_TIMEOUT_SEC=$RUN_TIMEOUT_SEC"

run_one() {
  local backend_tag="$1"
  local cfg_tag="$2"
  local gap_k="$3"
  local lmax="$4"
  local rowwin="$5"
  local tmo="$6"

  # Resume-friendly: skip if this exact tuple already exists in TSV.
  if [ "${MESH_CAL_SKIP_EXISTING:-1}" = "1" ] && [ -f "$RESULTS_TSV" ]; then
    if python3 - "$RESULTS_TSV" "$gap_k" "$lmax" "$rowwin" "$tmo" >/dev/null 2>&1 <<'PY'
import sys
import os
from pathlib import Path

tsv = Path(sys.argv[1])
gap_k, lmax, rowwin, tmo = sys.argv[2:]

env_backend = os.environ.get("MESH_MEM_BACKEND", "")
cfg = os.environ.get("MESH_RAMULATOR2_CONFIG_FILE", "")

for raw in tsv.read_text(encoding="utf-8", errors="ignore").splitlines():
    if not raw.strip():
        continue
    cols = raw.split("\t")
    if len(cols) < 8:
        continue
    b, c, k, lm, rw, to = cols[0], cols[1], cols[2], cols[3], cols[4], cols[5]
    if b != env_backend:
        continue
    if c != cfg:
        continue
    if k == str(gap_k) and lm == str(lmax) and rw == str(rowwin) and to == str(tmo):
        sys.exit(0)
sys.exit(1)
PY
    then
      echo "[gas-cal] skip existing tuple: backend=$backend_tag cfg=$cfg_tag k=$gap_k lmax=$lmax rowwin=$rowwin tmo=$tmo"
      return 0
    fi
  fi

  export MESH_GAS_GAP_K_BYTES="$gap_k"
  export MESH_GAS_LMAX_BYTES="$lmax"
  export MESH_GAS_ROW_WINDOW_BYTES="$rowwin"
  export MESH_GAS_ROW_WINDOW_TIMEOUT_NS="$tmo"

  local root="$OUT_BASE/backend_${backend_tag}/cfg_${cfg_tag}/k_${gap_k}/lmax_${lmax}/rowwin_${rowwin}/tmo_${tmo}"
  mkdir -p "$root"
  local ts
  ts="$(date +%Y%m%d-%H%M%S-%N)"
  local run_dir="$root/$ts"
  mkdir -p "$run_dir"

  export MESH_RUN_DIR="$run_dir"

  local log="$run_dir/mesh_run.log"
  local time_file="$run_dir/time.txt"

  local sst_exit=0
  if [ "$RUN_TIMEOUT_SEC" != "0" ]; then
    ( cd "$PROJECT_ROOT" && /usr/bin/time -v -o "$time_file" timeout "$RUN_TIMEOUT_SEC" "$SST_BIN" -n "${MESH_SST_NPROC:-32}" "$MODEL" ) > "$log" 2>&1 || sst_exit=$?
  else
    ( cd "$PROJECT_ROOT" && /usr/bin/time -v -o "$time_file" "$SST_BIN" -n "${MESH_SST_NPROC:-32}" "$MODEL" ) > "$log" 2>&1 || sst_exit=$?
  fi
  echo "$sst_exit" > "$run_dir/sst_exit_code.txt"

  if [ "$sst_exit" -ne 0 ] || [ ! -s "$run_dir/mesh_stats.csv" ]; then
    echo "[gas-cal] WARN: run failed backend=$backend_tag cfg=$cfg_tag k=$gap_k lmax=$lmax rowwin=$rowwin tmo=$tmo exit=$sst_exit"
  else
    python3 "$PROJECT_ROOT/tools/write_mesh_meta.py" \
      --run-dir "$run_dir" \
      --project-root "$PROJECT_ROOT" \
      --sst-bin "$SST_BIN" \
      --model "$MODEL" \
      --sst-nproc "${MESH_SST_NPROC:-32}" > "$run_dir/meta.json.log" 2>&1
    python3 "$PROJECT_ROOT/tools/compute_essential_summary_mesh.py" --run-dir "$run_dir" >/dev/null 2>&1 || true

    local vlog="$run_dir/validation.log"
    python3 "$PROJECT_ROOT/tools/validate_essential_summary_mesh.py" \
      --run-dir "$run_dir" \
      --profile "$MESH_VALIDATE_PROFILE" > "$vlog" 2>&1 || true
  fi

  python3 - <<'PY' >> "$RESULTS_TSV"
import json
import os
from pathlib import Path

run_dir = Path(os.environ["MESH_RUN_DIR"]).resolve()
backend = os.environ.get("MESH_MEM_BACKEND", "")
cfg = os.environ.get("MESH_RAMULATOR2_CONFIG_FILE", "")
gap_k = os.environ.get("MESH_GAS_GAP_K_BYTES", "")
lmax = os.environ.get("MESH_GAS_LMAX_BYTES", "")
rowwin = os.environ.get("MESH_GAS_ROW_WINDOW_BYTES", "")
tmo = os.environ.get("MESH_GAS_ROW_WINDOW_TIMEOUT_NS", "")

summary_path = run_dir / "essential_summary_mesh.json"
verdict = "FAIL"
memctrl_bytes = "NA"
memctrl_gets = "NA"
gas_payload = "NA"
gas_unique = "NA"
overfetch_ratio = "NA"
row_hit_rate = "NA"
avg_read_lat = "NA"
sim_cycles = "NA"
wall_s = "NA"

def _get(d, path):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur

if summary_path.exists():
    try:
        s = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        s = {}
    exp = s.get("experiment") if isinstance(s, dict) else None
    if isinstance(exp, dict):
        verdict = str(exp.get("verdict", "PASS") or "PASS").strip().upper() or "PASS"
    else:
        # Back-compat: infer from validation.log line.
        v = run_dir / "validation.log"
        if v.exists():
            txt = v.read_text(encoding="utf-8", errors="ignore")
            verdict = "PASS" if "fail=0" in txt else "FAIL"
    memctrl_bytes = _get(s, "memhierarchy.memctrl.bytes_est_total") or "NA"
    memctrl_gets = _get(s, "memhierarchy.memctrl.req_GetS") or "NA"
    gas_payload = _get(s, "gas.payload_bytes_total") or "NA"
    gas_unique = _get(s, "gas.unique_bytes_total") or "NA"
    sim_cycles = _get(s, "gas.cycle_cost") or _get(s, "model.sim_time_actual_ns") or "NA"
    try:
        if isinstance(gas_unique, (int, float)) and float(gas_unique) > 0 and isinstance(_get(s, "gas.overfetch_bytes_total"), (int, float)):
            overfetch_ratio = float(_get(s, "gas.overfetch_bytes_total")) / float(gas_unique)
    except Exception:
        pass
    row_hit_rate = _get(s, "ramulator2.row_hit_rate_total") or "NA"
    avg_read_lat = _get(s, "ramulator2.avg_read_latency_0_avg") or "NA"
    wall = _get(s, "wallclock.wall")
    if isinstance(wall, str) and wall.strip():
        parts = wall.strip().split(":")
        try:
            if len(parts) == 2:
                wall_s = int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                wall_s = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except Exception:
            wall_s = "NA"

print(
    f"{backend}\t{cfg}\t{gap_k}\t{lmax}\t{rowwin}\t{tmo}\t{run_dir}\t{verdict}\t{memctrl_bytes}\t{memctrl_gets}\t{gas_payload}\t{gas_unique}\t{overfetch_ratio}\t{row_hit_rate}\t{avg_read_lat}\t{sim_cycles}\t{wall_s}"
)
PY
}

pick_best_k_lmax() {
  python3 - <<'PY'
import os
from pathlib import Path

tsv = Path(os.environ["RESULTS_TSV"]).resolve()
backend = os.environ.get("MESH_MEM_BACKEND", "")
cfg = os.environ.get("MESH_RAMULATOR2_CONFIG_FILE", "")

best = None  # (sim_cycles, memctrl_bytes, k, lmax)

def _to_float(x):
    try:
        return float(x)
    except Exception:
        return None

for raw in tsv.read_text(encoding="utf-8", errors="ignore").splitlines():
    if not raw.strip():
        continue
    # Skip header or malformed lines (header may contain literal "\\t")
    cols = raw.split("\t")
    if len(cols) < 16:
        continue
    b, c, k, lmax, rowwin, tmo, run_dir, verdict, memctrl_bytes, *_rest = cols
    if b != backend:
        continue
    if c != cfg:
        continue
    if rowwin != "0" or tmo != "0":
        continue
    if verdict.strip().upper() != "PASS":
        continue
    has_sim = len(cols) >= 17
    sim_s = cols[-2] if has_sim else "NA"
    sim = _to_float(sim_s)
    mbytes = _to_float(memctrl_bytes)
    if sim is None:
        continue
    if mbytes is None:
        mbytes = 1e99
    tup = (sim, mbytes, int(k), int(lmax))
    if best is None or tup < best:
        best = tup

if best is None:
    # Fallback: choose the smallest memctrl_bytes among PASS runs (rowwin=0,tmo=0).
    for raw in tsv.read_text(encoding="utf-8", errors="ignore").splitlines():
        cols = raw.split("\t")
        if len(cols) < 16:
            continue
        b, c, k, lmax, rowwin, tmo, run_dir, verdict, memctrl_bytes, *_rest = cols
        if b != backend or c != cfg:
            continue
        if rowwin != "0" or tmo != "0":
            continue
        if verdict.strip().upper() != "PASS":
            continue
        mbytes = _to_float(memctrl_bytes)
        if mbytes is None:
            continue
        has_sim = len(cols) >= 17
        sim_s = cols[-2] if has_sim else "NA"
        sim = _to_float(sim_s)
        if sim is None:
            sim = 1e99
        tup = (mbytes, sim, int(k), int(lmax))
        if best is None or tup < best:
            best = tup
    if best is None:
        print("0 4096")
    else:
        _, _, k, lmax = best
        print(f"{k} {lmax}")
else:
    _, _, k, lmax = best
    print(f"{k} {lmax}")
PY
}

for backend in $BACKENDS; do
  case "$backend" in
    simple)
      export MESH_MEM_BACKEND="simple"
      unset MESH_RAMULATOR2_CONFIG_FILE || true
      backend_tag="simple"
      cfg_tag="none"
      ;;
    ram2_ddr4_openrow)
      export MESH_MEM_BACKEND="ramulator2"
      export MESH_RAMULATOR2_CONFIG_FILE="$PROJECT_ROOT/configs/ramulator2_ddr4_openrow.cfg"
      if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
        echo "[gas-cal] WARN: missing cfg: $MESH_RAMULATOR2_CONFIG_FILE (skip $backend)"
        continue
      fi
      backend_tag="ram2"
      cfg_tag="ddr4_openrow"
      ;;
    ram2_hbm2)
      export MESH_MEM_BACKEND="ramulator2"
      export MESH_RAMULATOR2_CONFIG_FILE="$PROJECT_ROOT/configs/ramulator2_hbm2.cfg"
      if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
        echo "[gas-cal] WARN: missing cfg: $MESH_RAMULATOR2_CONFIG_FILE (skip $backend)"
        continue
      fi
      backend_tag="ram2"
      cfg_tag="hbm2"
      ;;
    ram2_hbm2_notrans)
      export MESH_MEM_BACKEND="ramulator2"
      export MESH_RAMULATOR2_CONFIG_FILE="$PROJECT_ROOT/configs/ramulator2_hbm2_notrans.cfg"
      if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
        echo "[gas-cal] WARN: missing cfg: $MESH_RAMULATOR2_CONFIG_FILE (skip $backend)"
        continue
      fi
      backend_tag="ram2"
      cfg_tag="hbm2_notrans"
      ;;
    ram2_ddr5)
      export MESH_MEM_BACKEND="ramulator2"
      export MESH_RAMULATOR2_CONFIG_FILE="$PROJECT_ROOT/configs/ramulator2_ddr5.cfg"
      if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
        echo "[gas-cal] WARN: missing cfg: $MESH_RAMULATOR2_CONFIG_FILE (skip $backend)"
        continue
      fi
      backend_tag="ram2"
      cfg_tag="ddr5"
      ;;
    ram2_ddr5_notrans)
      export MESH_MEM_BACKEND="ramulator2"
      export MESH_RAMULATOR2_CONFIG_FILE="$PROJECT_ROOT/configs/ramulator2_ddr5_notrans.cfg"
      if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
        echo "[gas-cal] WARN: missing cfg: $MESH_RAMULATOR2_CONFIG_FILE (skip $backend)"
        continue
      fi
      backend_tag="ram2"
      cfg_tag="ddr5_notrans"
      ;;
    ram2_ddr5_notrans_mop4clxor)
      export MESH_MEM_BACKEND="ramulator2"
      export MESH_RAMULATOR2_CONFIG_FILE="$PROJECT_ROOT/configs/ramulator2_ddr5_notrans_mop4clxor.cfg"
      if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
        echo "[gas-cal] WARN: missing cfg: $MESH_RAMULATOR2_CONFIG_FILE (skip $backend)"
        continue
      fi
      backend_tag="ram2"
      cfg_tag="ddr5_notrans_mop4clxor"
      ;;
    ram2_ddr5_notrans_robaraco)
      export MESH_MEM_BACKEND="ramulator2"
      export MESH_RAMULATOR2_CONFIG_FILE="$PROJECT_ROOT/configs/ramulator2_ddr5_notrans_robaraco.cfg"
      if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
        echo "[gas-cal] WARN: missing cfg: $MESH_RAMULATOR2_CONFIG_FILE (skip $backend)"
        continue
      fi
      backend_tag="ram2"
      cfg_tag="ddr5_notrans_robaraco"
      ;;
    ram2_ddr5_notrans_x16_chra)
      export MESH_MEM_BACKEND="ramulator2"
      export MESH_RAMULATOR2_CONFIG_FILE="$PROJECT_ROOT/configs/ramulator2_ddr5_notrans_x16_chra.cfg"
      if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
        echo "[gas-cal] WARN: missing cfg: $MESH_RAMULATOR2_CONFIG_FILE (skip $backend)"
        continue
      fi
      backend_tag="ram2"
      cfg_tag="ddr5_notrans_x16_chra"
      ;;
    ram2_ddr5_notrans_x16_mop4clxor)
      export MESH_MEM_BACKEND="ramulator2"
      export MESH_RAMULATOR2_CONFIG_FILE="$PROJECT_ROOT/configs/ramulator2_ddr5_notrans_x16_mop4clxor.cfg"
      if [ ! -f "$MESH_RAMULATOR2_CONFIG_FILE" ]; then
        echo "[gas-cal] WARN: missing cfg: $MESH_RAMULATOR2_CONFIG_FILE (skip $backend)"
        continue
      fi
      backend_tag="ram2"
      cfg_tag="ddr5_notrans_x16_mop4clxor"
      ;;
    *)
      echo "[gas-cal] WARN: unknown backend tag: $backend (skip)"
      continue
      ;;
  esac

  export RESULTS_TSV

  if [ "$SWEEP_MODE" = "full_grid" ]; then
    for gap_k in $K_LIST; do
      for lmax in $LMAX_LIST; do
        for rowwin in $ROWWIN_LIST; do
          for tmo in $TMO_LIST; do
            echo "[gas-cal] run backend=$backend cfg=$cfg_tag k=$gap_k lmax=$lmax rowwin=$rowwin tmo=$tmo"
            run_one "$backend_tag" "$cfg_tag" "$gap_k" "$lmax" "$rowwin" "$tmo"
          done
        done
      done
    done
    continue
  fi

  # Phase A: fine sweep (k,lmax) with rowwin=0,tmo=0
  for gap_k in $K_LIST; do
    for lmax in $LMAX_LIST; do
      echo "[gas-cal] fine backend=$backend cfg=$cfg_tag k=$gap_k lmax=$lmax rowwin=0 tmo=0"
      run_one "$backend_tag" "$cfg_tag" "$gap_k" "$lmax" 0 0
    done
  done

  if [ "$SWEEP_MODE" = "fine_only" ]; then
    continue
  fi

  best="$(pick_best_k_lmax)"
  best_k="${best%% *}"
  best_lmax="${best#* }"
  echo "[gas-cal] best (rowwin=0,tmo=0) backend=$backend cfg=$cfg_tag => k=$best_k lmax=$best_lmax"

  # Phase B: coarse sweep on best (k,lmax)
  for rowwin in $ROWWIN_LIST; do
    for tmo in $TMO_LIST; do
      if [ "$rowwin" = "0" ] && [ "$tmo" = "0" ]; then
        continue
      fi
      echo "[gas-cal] coarse backend=$backend cfg=$cfg_tag k=$best_k lmax=$best_lmax rowwin=$rowwin tmo=$tmo"
      run_one "$backend_tag" "$cfg_tag" "$best_k" "$best_lmax" "$rowwin" "$tmo"
    done
  done
done

echo "[gas-cal] DONE: $RESULTS_TSV"
