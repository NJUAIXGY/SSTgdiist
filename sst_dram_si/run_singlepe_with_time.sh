#!/usr/bin/env bash
set -euo pipefail

# Run SST single-PE experiment with wallclock capture and auto summary
# Usage: ./run_singlepe_with_time.sh [extra sst args]

ROOT_DIR=$(cd "$(dirname "$0")" && pwd)
CFG_PATH="$ROOT_DIR/local_run_config.json"
SST_BIN="$ROOT_DIR/../sst_install/bin/sst"
MODEL_PY="$ROOT_DIR/test_dram_si_single_pe.py"
SUMMARY_PY="$ROOT_DIR/tools/compute_essential_summary_singlepe.py"

# Derive run base from dataset_path in config; fallback to dram_N1k
RUN_BASE_DEFAULT="$ROOT_DIR/outputs_large/paper2/dram_N1k"
RUN_BASE_DIR="$RUN_BASE_DEFAULT"
if [[ -f "$CFG_PATH" ]]; then
  RUN_BASE_DIR=$(python3 - "$ROOT_DIR" <<'PY'
import json,os,sys
root=sys.argv[1]
cfg=json.load(open(os.path.join(root,'local_run_config.json'),'r'))
p=cfg.get('dataset_path','outputs_large/paper2/dram_N1k/spikes_srcdst.txt')
base=os.path.dirname(os.path.join(root,p))
print(os.path.abspath(base))
PY
  )
fi
mkdir -p "$RUN_BASE_DIR"

echo "[run] RUN_BASE_DIR=$RUN_BASE_DIR"

# Run SST with wallclock capture
TMP_P_TIME=$(mktemp)
TMP_V_TIME=$(mktemp)
set +e
/usr/bin/time -v -o "$TMP_V_TIME" "$SST_BIN" -n 32 "$MODEL_PY" "$@" > "$ROOT_DIR/logs/last_run.wrapper.log" 2>&1
RC=$?
set -e

# Locate latest timestamp run dir
latest_dir=$(ls -1dt "$RUN_BASE_DIR"/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null | head -n1 || true)
if [[ -z "$latest_dir" ]]; then
  echo "[run] WARN: no timestamp run directory found under $RUN_BASE_DIR"
  latest_dir="$RUN_BASE_DIR"
fi

# Extract wallclock/user/sys/maxrss into last_run.time
{
  # GNU time -v output fields
  wall=$(grep -E "Elapsed \(wall clock\) time" "$TMP_V_TIME" | awk -F': ' '{print $2}' | tr -d '\r' | head -n1)
  user=$(grep -E "User time \(seconds\)" "$TMP_V_TIME" | awk -F': ' '{print $2}' | tr -d '\r' | head -n1)
  sys=$(grep -E "System time \(seconds\)" "$TMP_V_TIME" | awk -F': ' '{print $2}' | tr -d '\r' | head -n1)
  maxrss=$(grep -E "Maximum resident set size|最大驻留集大小" "$TMP_V_TIME" | grep -Eo "[0-9]+" | tail -n1)
  [[ -n "$wall" ]] && echo "WALL=$wall"
  [[ -n "$user" ]] && echo "USER=$user"
  [[ -n "$sys" ]] && echo "SYS=$sys"
  [[ -n "$maxrss" ]] && echo "MAXRSS=$maxrss"
} > "$latest_dir/last_run.time" || true
rm -f "$TMP_V_TIME"

# Auto summary to parent and to latest run dir
python3 "$SUMMARY_PY" --run-dir "$RUN_BASE_DIR" --out "$RUN_BASE_DIR/essential_summary.json" >/dev/null 2>&1 || true
if [[ -f "$RUN_BASE_DIR/essential_summary.json" ]]; then
  cp "$RUN_BASE_DIR/essential_summary.json" "$latest_dir/essential_summary.json"
fi

# Maintain 'latest' symlink for quick access
ln -sfn "$latest_dir" "$RUN_BASE_DIR/latest"

echo "[run] Completed with RC=$RC; latest=$latest_dir"
exit "$RC"
