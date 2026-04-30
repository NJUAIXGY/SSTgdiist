#!/usr/bin/env python3
"""Validate M43 readiness drift report contract."""

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
    ap.add_argument("--drift-report", required=True, help="drift report json path")
    ap.add_argument("--expect-pass", type=int, default=1, help="when 1, require report.status == pass")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    report_path = Path(args.drift_report).expanduser().resolve()
    if not report_path.exists():
        return _fail(2, f"[m43][P0] missing --drift-report: {report_path}")

    try:
        report = _load_json(report_path)
    except Exception as exc:
        return _fail(2, f"[m43][P0] cannot parse drift report json: {exc}")
    if not isinstance(report, dict):
        return _fail(2, "[m43][P0] drift report root must be object")

    status = str(report.get("status", "")).strip().lower()
    severity = str(report.get("severity", "")).strip().lower()
    if status not in {"pass", "fail"}:
        return _fail(3, f"[m43][P1] invalid status: {status!r}")
    if severity not in {"none", "medium", "high"}:
        return _fail(3, f"[m43][P1] invalid severity: {severity!r}")

    baseline_id = str(report.get("baseline_id", "")).strip()
    if not baseline_id:
        return _fail(3, "[m43][P1] baseline_id must be non-empty")

    thresholds = report.get("thresholds")
    if not isinstance(thresholds, dict):
        return _fail(3, "[m43][P1] missing thresholds object")

    for key in ("score_total_delta_min", "breakdown_delta_min"):
        ok, _ = _to_float(thresholds.get(key))
        if not ok:
            return _fail(3, f"[m43][P1] invalid threshold field: {key}")
    ok_flags, max_flags = _to_float(thresholds.get("max_new_drift_flags"))
    if not ok_flags or max_flags < 0:
        return _fail(3, "[m43][P1] invalid max_new_drift_flags")

    deltas = report.get("deltas")
    if not isinstance(deltas, dict):
        return _fail(3, "[m43][P1] missing deltas object")

    ok_score, _ = _to_float(deltas.get("capability_score_total_avg"))
    ok_dist, _ = _to_float(deltas.get("distance_to_target_avg"))
    if not ok_score or not ok_dist:
        return _fail(3, "[m43][P1] invalid score/distance delta fields")

    breakdown_delta = deltas.get("capability_score_breakdown_avg")
    if not isinstance(breakdown_delta, dict) or not breakdown_delta:
        return _fail(3, "[m43][P1] missing capability_score_breakdown_avg delta object")
    for k, v in breakdown_delta.items():
        ok, _ = _to_float(v)
        if not ok:
            return _fail(3, f"[m43][P1] invalid breakdown delta value: {k}")

    new_flags = deltas.get("new_regression_drift_flags")
    if not isinstance(new_flags, list):
        return _fail(3, "[m43][P1] new_regression_drift_flags must be list")

    violations = report.get("violations")
    if not isinstance(violations, list):
        return _fail(3, "[m43][P1] violations must be list")

    if int(args.expect_pass) == 1 and status != "pass":
        return _fail(3, f"[m43][P1] expected pass but got status={status} with violations={len(violations)}")

    prefix = f"[m43:{args.label}] " if args.label else "[m43] "
    print(f"{prefix}status={status} severity={severity} violations={len(violations)}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
