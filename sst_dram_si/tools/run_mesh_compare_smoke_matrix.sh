#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_ROOT="${MESH_COMPARE_MATRIX_RUN_ROOT:-$PROJECT_ROOT/outputs_large/paper2/dram_mesh_4x4_exec_mode_compare/matrix}"
mkdir -p "$RUN_ROOT"

TS="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$RUN_ROOT/$TS"
mkdir -p "$RUN_DIR"

run_case() {
  local label="$1"
  shift
  local log_path="$RUN_DIR/${label}.log"
  local run_dir_path="$RUN_DIR/${label}.run_dir"

  "$@" >"$log_path" 2>&1
  cat "$log_path"

  python3 - "$label" "$log_path" "$run_dir_path" <<'PY'
import sys
from pathlib import Path

label = sys.argv[1]
log_path = Path(sys.argv[2])
run_dir_path = Path(sys.argv[3])
text = log_path.read_text(encoding="utf-8", errors="replace")
run_dir = ""
for line in text.splitlines():
    if "run complete:" not in line:
        continue
    run_dir = line.split("run complete:", 1)[1].strip()
if not run_dir:
    raise SystemExit(f"[mesh-compare-matrix] failed to parse run_dir for {label}: {log_path}")
run_dir_path.write_text(run_dir + "\n", encoding="utf-8")
print(f"[mesh-compare-matrix] {label} run_dir={run_dir}")
PY
}

run_case "gas" bash "$SCRIPT_DIR/run_mesh_compare_steps4_gas_smoke.sh"
run_case "naive_raw" bash "$SCRIPT_DIR/run_mesh_compare_steps4_naive_raw_smoke.sh"
run_case "naive_opt" env \
  MESH_COMPARE_ROLE=smoke \
  MESH_COMPARE_BOUNDED_VALIDATION=1 \
  MESH_MAX_STEPS=1 \
  bash "$SCRIPT_DIR/run_mesh_exec_mode_compare_with_time.sh" naive_opt

python3 - "$RUN_DIR" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

matrix_run_dir = Path(sys.argv[1]).resolve()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"[mesh-compare-matrix] invalid json: {path}: {exc}")


def _extract_meta_model(meta: dict) -> dict:
    model = meta.get("model")
    if isinstance(model, dict):
        return model
    return meta if isinstance(meta, dict) else {}


def _parse_validation(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"fail=(\d+)\s+warn=(\d+)\s+strict=(\d+)", text)
    if not match:
        raise SystemExit(f"[mesh-compare-matrix] missing validator summary: {path}")
    return {
        "fail": int(match.group(1)),
        "warn": int(match.group(2)),
        "strict": int(match.group(3)),
    }


def _parse_boolish(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in ("1", "true", "yes", "y", "on"):
            return True
        if raw in ("0", "false", "no", "n", "off"):
            return False
    return None


cases = []
for label in ("gas", "naive_raw", "naive_opt"):
    run_dir_ref = matrix_run_dir / f"{label}.run_dir"
    run_dir = Path(run_dir_ref.read_text(encoding="utf-8").strip()).resolve()
    meta = _read_json(run_dir / "meta.json")
    summary = _read_json(run_dir / "essential_summary_mesh.json")
    validator = _parse_validation(run_dir / "validation.log")
    model = _extract_meta_model(meta)
    memory = summary.get("memory") if isinstance(summary, dict) else {}
    if not isinstance(memory, dict):
        memory = {}
    memory_requests = memory.get("memory_requests")
    memory_bytes = memory.get("memory_bytes")
    cases.append(
        {
            "label": label,
            "run_dir": str(run_dir),
            "requested_exec_mode": model.get("requested_exec_mode") or model.get("exec_mode"),
            "effective_exec_mode": model.get("effective_exec_mode") or model.get("exec_mode"),
            "compare_role": model.get("compare_role"),
            "bounded_validation": _parse_boolish(model.get("bounded_validation")),
            "validator": validator,
            "memory": {
                "memory_requests": memory_requests,
                "memory_bytes": memory_bytes,
                "nonzero": bool((memory_requests or 0) != 0 or (memory_bytes or 0) != 0),
            },
        }
    )

payload = {
    "matrix_run_id": matrix_run_dir.name,
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "cases": cases,
}

out_path = matrix_run_dir / "summary.json"
out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"[mesh-compare-matrix] summary written: {out_path}")
PY

python3 "$SCRIPT_DIR/compare_acceptance_lab.py" refresh

echo "[mesh-compare-matrix] run complete: $RUN_DIR"
echo "[mesh-compare-matrix] summary: $RUN_DIR/summary.json"
