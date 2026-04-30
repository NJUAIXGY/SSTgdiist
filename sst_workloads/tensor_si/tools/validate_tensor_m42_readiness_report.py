#!/usr/bin/env python3
"""Validate M42 aggregated readiness report contract."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any) -> Tuple[bool, float]:
    try:
        if isinstance(value, bool):
            return False, 0.0
        if isinstance(value, (int, float)):
            f = float(value)
            return math.isfinite(f), f
        txt = str(value).strip()
        if not txt:
            return False, 0.0
        f = float(txt)
        return math.isfinite(f), f
    except Exception:
        return False, 0.0


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="M42 readiness report json path")
    ap.add_argument("--min-scenarios", type=int, default=3, help="minimum expected scenario count")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    report_p = Path(args.report).expanduser().resolve()
    if not report_p.exists():
        return _fail(2, f"[m42][P0] missing --report: {report_p}")

    try:
        report = _load_json(report_p)
    except Exception as exc:
        return _fail(2, f"[m42][P0] cannot parse report json: {exc}")
    if not isinstance(report, dict):
        return _fail(2, "[m42][P0] report root must be object")

    scenario_count = int(report.get("scenario_count", 0) or 0)
    if scenario_count < max(1, int(args.min_scenarios)):
        return _fail(3, f"[m42][P1] scenario_count too small: {scenario_count} < {args.min_scenarios}")

    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != scenario_count:
        return _fail(3, "[m42][P1] invalid scenarios list or scenario_count mismatch")

    ok_total, total = _to_float(report.get("capability_score_total_avg"))
    ok_dist, dist = _to_float(report.get("distance_to_target_avg"))
    if not ok_total or total < 0.0 or total > 100.0:
        return _fail(3, f"[m42][P1] invalid capability_score_total_avg: {report.get('capability_score_total_avg')!r}")
    if not ok_dist or dist < 0.0:
        return _fail(3, f"[m42][P1] invalid distance_to_target_avg: {report.get('distance_to_target_avg')!r}")

    breakdown = report.get("capability_score_breakdown_avg")
    if not isinstance(breakdown, dict) or not breakdown:
        return _fail(3, "[m42][P1] missing capability_score_breakdown_avg")

    for k, v in breakdown.items():
        ok, f = _to_float(v)
        if not ok or f < 0.0 or f > 100.0:
            return _fail(3, f"[m42][P1] invalid breakdown avg value: {k}={v!r}")

    top_gaps = report.get("top_gaps")
    if not isinstance(top_gaps, list) or not top_gaps:
        return _fail(3, "[m42][P1] top_gaps must be non-empty list")
    for i, item in enumerate(top_gaps):
        if not isinstance(item, dict):
            return _fail(3, f"[m42][P1] top_gaps[{i}] must be object")
        dim = str(item.get("dimension", "")).strip()
        if not dim:
            return _fail(3, f"[m42][P1] top_gaps[{i}] missing dimension")
        ok_gap, gap = _to_float(item.get("gap_avg"))
        if not ok_gap or gap < 0.0:
            return _fail(3, f"[m42][P1] top_gaps[{i}] invalid gap_avg")

    flags = report.get("regression_drift_flags_union")
    if not isinstance(flags, list):
        return _fail(3, "[m42][P1] regression_drift_flags_union must be list")

    conf = str(report.get("calibration_confidence", "")).strip().lower()
    if conf not in {"unverified", "low", "medium", "high"}:
        return _fail(3, f"[m42][P1] invalid calibration_confidence: {conf!r}")

    level = str(report.get("readiness_level", "")).strip().upper()
    if level not in {"L0", "L1", "L2", "L3"}:
        return _fail(3, f"[m42][P1] invalid readiness_level: {level!r}")

    prefix = f"[m42:{args.label}] " if args.label else "[m42] "
    print(f"{prefix}scenario_count={scenario_count} score_avg={total:.3f} distance_avg={dist:.3f}")
    print(f"{prefix}readiness_level={level} calibration_confidence={conf} top_gaps={len(top_gaps)}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
