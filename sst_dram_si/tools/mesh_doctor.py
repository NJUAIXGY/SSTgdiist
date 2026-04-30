#!/usr/bin/env python3
"""
mesh_doctor.py

Quick run-directory diagnosis for the mainline path:
- artifact completeness checks
- mainline-contract checks
- bottleneck stage readout from essential_summary_mesh.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REQUIRED_ARTIFACTS = (
    "mesh_stats.csv",
    "essential_summary_mesh.json",
    "validation.log",
)

OPTIONAL_LEDGER_ARTIFACTS = (
    "pe_step_perf_db.csv",
    "pe_stage_events_db.csv",
)


def _read_json(path: Path) -> Dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object: {path}")
    return obj


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _safe_ratio(num: float, den: float) -> Optional[float]:
    if den == 0:
        return None
    return float(num / den)


def _fallback_critical_path(summary: Dict[str, Any]) -> Dict[str, Any]:
    gas = summary.get("gas") if isinstance(summary.get("gas"), dict) else {}
    step = summary.get("step") if isinstance(summary.get("step"), dict) else {}
    memctrl = summary.get("memhierarchy", {}).get("memctrl", {})
    if not isinstance(memctrl, dict):
        memctrl = {}

    apply_ns = _to_float(gas.get("apply_ns_avg"), 0.0)
    apply_gap_ns = _to_float(gas.get("apply_to_scatter_gap_ns_avg"), 0.0)
    retire_hol = _to_float(gas.get("retire_global_hol_cycles_total"), 0.0)
    retire_blocked_per_hol = _to_float(gas.get("retire_ready_blocked_edges_per_hol_cycle_avg"), 0.0)
    mem_util = _to_float(gas.get("memctrl_payload_utilization"), 0.0)
    mem_amp = _to_float(gas.get("memctrl_traffic_amplification"), 0.0)
    mem_req = _to_float(memctrl.get("req_total"), 0.0)
    steps_done_range = int(_to_float(step.get("steps_done_range"), 0.0))
    frontend_reuse = _to_float(gas.get("frontend_line_touch_reuse_ratio"), 0.0)

    stage = "apply_issue"
    confidence = "low"
    if steps_done_range > 0:
        stage = "barrier_wait"
        confidence = "high"
    elif retire_hol > 0 and (apply_gap_ns > max(0.25 * apply_ns, 1000.0) or retire_blocked_per_hol >= 200.0):
        stage = "retire_closure"
        confidence = "medium"
    elif mem_req > 0 and mem_util > 0 and mem_util < 0.10 and mem_amp >= 8.0:
        stage = "memory_response"
        confidence = "medium"
    elif frontend_reuse > 0 and frontend_reuse < 0.25:
        stage = "frontend_build"
        confidence = "medium"

    return {
        "stage": stage,
        "confidence": confidence,
        "evidence": {
            "apply_ns_avg": apply_ns,
            "apply_to_scatter_gap_ns_avg": apply_gap_ns,
            "retire_global_hol_cycles_total": retire_hol,
            "retire_ready_blocked_edges_per_hol_cycle_avg": retire_blocked_per_hol,
            "memctrl_payload_utilization": mem_util,
            "memctrl_traffic_amplification": mem_amp,
            "steps_done_range": steps_done_range,
            "frontend_line_touch_reuse_ratio": frontend_reuse,
        },
    }


def _next_action_hints(stage: str) -> List[str]:
    hints = {
        "rx_ingress": [
            "Inspect per-step RX ledger: `rx_packets_before_bg_total` and `rx_before_bg_ratio`.",
            "Check STORM packet mix (`snn_rx` key/tile/spike ratios) for ingress pressure shifts.",
        ],
        "frontend_build": [
            "Compare `frontend_staged_reads_per_unique_line_avg` and line-touch reuse across A/B.",
            "Focus on clustering/locality before touching memory-side scheduler knobs.",
        ],
        "apply_issue": [
            "Enable/inspect apply issue block-reason counters (P0 instrumentation path).",
            "Correlate `apply_ns_avg` with inflight limits and credit behavior.",
        ],
        "memory_response": [
            "Check memctrl utilization/amplification and first-response delay landmarks.",
            "Validate whether request shape changed or only service latency changed.",
        ],
        "retire_closure": [
            "Inspect retire HOL and blocked-edge counters before changing frontend knobs.",
            "Use hotspot report on slow seq/PE to confirm long-tail closure behavior.",
        ],
        "barrier_wait": [
            "Check `step.steps_done_range` and global-step synchronization consistency.",
            "Audit last-step drain/closure rather than issuing-path optimizations.",
        ],
    }
    return hints.get(stage, ["Review `critical_path.evidence` and inspect slowest steps first."])


def _check_artifacts(run_dir: Path) -> Dict[str, Any]:
    required = {name: (run_dir / name).exists() for name in REQUIRED_ARTIFACTS}
    optional = {name: (run_dir / name).exists() for name in OPTIONAL_LEDGER_ARTIFACTS}

    # Also accept per-PE ledgers.
    if not optional["pe_step_perf_db.csv"]:
        optional["pe_step_perf_db.csv"] = any(run_dir.glob("pe*/pe_step_perf_db.csv"))
    if not optional["pe_stage_events_db.csv"]:
        optional["pe_stage_events_db.csv"] = any(run_dir.glob("pe*/pe_stage_events_db.csv"))

    return {
        "required": required,
        "optional": optional,
        "required_ok": all(required.values()),
    }


def _check_mainline_contract(summary: Dict[str, Any]) -> Dict[str, Any]:
    model = summary.get("model") if isinstance(summary.get("model"), dict) else {}
    checks: Dict[str, Any] = {}

    exec_mode = str(model.get("exec_mode", "") or "").strip().lower()
    checks["exec_mode_gas"] = {
        "ok": exec_mode == "gas",
        "value": exec_mode or "unknown",
    }

    noc_type = str(model.get("noc_type", "") or "").strip().lower()
    checks["noc_type_multicast_mesh"] = {
        "ok": noc_type == "multicast_mesh",
        "value": noc_type or "unknown",
    }

    syn_mode = str(model.get("synapse_weight_mode", "") or "").strip().lower()
    checks["synapse_weight_mode_gcss"] = {
        "ok": syn_mode.startswith("gcss_"),
        "value": syn_mode or "unknown",
    }

    return {
        "checks": checks,
        "all_ok": all(bool(v.get("ok")) for v in checks.values()),
    }


def diagnose(run_dir: Path) -> Dict[str, Any]:
    artifact = _check_artifacts(run_dir)

    summary_path = run_dir / "essential_summary_mesh.json"
    summary: Dict[str, Any] = {}
    summary_loaded = False
    summary_error = ""
    if summary_path.exists():
        try:
            summary = _read_json(summary_path)
            summary_loaded = True
        except Exception as exc:
            summary_error = str(exc)

    mainline_contract = _check_mainline_contract(summary) if summary_loaded else {"checks": {}, "all_ok": False}

    if summary_loaded and isinstance(summary.get("critical_path"), dict):
        cp = dict(summary["critical_path"])
    else:
        cp = _fallback_critical_path(summary) if summary_loaded else {
            "stage": "unknown",
            "confidence": "low",
            "evidence": {"reason": "summary_unavailable"},
        }

    stage = str(cp.get("stage", "unknown") or "unknown")
    hints = _next_action_hints(stage)

    return {
        "run_dir": str(run_dir),
        "artifact": artifact,
        "summary_loaded": summary_loaded,
        "summary_error": summary_error,
        "mainline_contract": mainline_contract,
        "critical_path": cp,
        "next_actions": hints,
    }


def _print_report(diag: Dict[str, Any]) -> None:
    print(f"run_dir: {diag['run_dir']}")

    artifact = diag["artifact"]
    print(f"artifact.required_ok: {artifact['required_ok']}")
    for name, ok in artifact["required"].items():
        print(f"  required.{name}: {'OK' if ok else 'MISSING'}")
    for name, ok in artifact["optional"].items():
        print(f"  optional.{name}: {'OK' if ok else 'MISSING'}")

    print(f"summary.loaded: {diag['summary_loaded']}")
    if diag["summary_error"]:
        print(f"summary.error: {diag['summary_error']}")

    contract = diag["mainline_contract"]
    print(f"mainline_contract.all_ok: {contract.get('all_ok', False)}")
    for k, v in (contract.get("checks") or {}).items():
        print(f"  {k}: {'OK' if v.get('ok') else 'WARN'} (value={v.get('value')})")

    cp = diag["critical_path"]
    print(f"bottleneck.stage: {cp.get('stage')}")
    print(f"bottleneck.confidence: {cp.get('confidence')}")
    evidence = cp.get("evidence")
    if isinstance(evidence, dict):
        for k, v in evidence.items():
            print(f"  evidence.{k}: {v}")

    print("next_actions:")
    for hint in diag["next_actions"]:
        print(f"  - {hint}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True, help="run directory containing essential_summary_mesh.json")
    ap.add_argument("--json", action="store_true", help="print JSON report")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    diag = diagnose(run_dir)
    if args.json:
        print(json.dumps(diag, indent=2, ensure_ascii=False))
    else:
        _print_report(diag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
