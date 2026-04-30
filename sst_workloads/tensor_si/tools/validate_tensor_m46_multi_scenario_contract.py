#!/usr/bin/env python3
"""Validate M46 multi-scenario aggregated report contract."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


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


def _check_summary_object(obj: Any, name: str) -> Tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, f"{name} must be object"
    for key in ("min", "max", "avg"):
        ok, _ = _to_float(obj.get(key))
        if not ok:
            return False, f"{name}.{key} must be finite number"
    return True, ""


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="M46 multi-scenario report json")
    ap.add_argument("--min-scenarios", type=int, default=4, help="minimum expected scenario count")
    ap.add_argument("--required-scenario", action="append", default=[], help="required scenario name (repeatable)")
    ap.add_argument("--expect-pass", type=int, default=1, help="when 1, require overall status=pass")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    report_path = Path(args.report).expanduser().resolve()
    if not report_path.exists():
        return _fail(2, f"[m46][P0] missing --report: {report_path}")

    try:
        report = _load_json(report_path)
    except Exception as exc:
        return _fail(2, f"[m46][P0] cannot parse report json: {exc}")

    if not isinstance(report, dict):
        return _fail(2, "[m46][P0] report root must be object")

    status = str(report.get("status", "")).strip().lower()
    if status not in {"pass", "fail"}:
        return _fail(3, f"[m46][P1] invalid status: {status!r}")

    scenario_count = int(report.get("scenario_count", 0) or 0)
    if scenario_count < max(1, int(args.min_scenarios)):
        return _fail(3, f"[m46][P1] scenario_count too small: {scenario_count} < {args.min_scenarios}")

    rows = report.get("scenario_results")
    if not isinstance(rows, list) or len(rows) != scenario_count:
        return _fail(3, "[m46][P1] invalid scenario_results or scenario_count mismatch")

    pass_count = int(report.get("pass_count", 0) or 0)
    fail_count = int(report.get("fail_count", 0) or 0)
    waived_count = int(report.get("waived_count", 0) or 0)

    seen: Set[str] = set()
    names: List[str] = []
    pass_calc = 0
    fail_calc = 0
    waived_calc = 0

    for idx, item in enumerate(rows):
        if not isinstance(item, dict):
            return _fail(3, f"[m46][P1] scenario_results[{idx}] must be object")

        name = str(item.get("name", "")).strip()
        if not name:
            return _fail(3, f"[m46][P1] scenario_results[{idx}] missing name")
        if name in seen:
            return _fail(3, f"[m46][P1] duplicate scenario name: {name}")
        seen.add(name)
        names.append(name)

        row_status = str(item.get("status", "")).strip().lower()
        drift_status = str(item.get("drift_status", "")).strip().lower()
        waived = bool(item.get("waived", False))

        if row_status not in {"pass", "fail", "waived"}:
            return _fail(3, f"[m46][P1] scenario={name} invalid status: {row_status!r}")
        if drift_status not in {"pass", "fail"}:
            return _fail(3, f"[m46][P1] scenario={name} invalid drift_status: {drift_status!r}")

        if row_status == "pass":
            pass_calc += 1
            if drift_status != "pass":
                return _fail(3, f"[m46][P1] scenario={name} pass status requires drift_status=pass")
            if waived:
                return _fail(3, f"[m46][P1] scenario={name} pass status cannot set waived=true")
        elif row_status == "fail":
            fail_calc += 1
            if drift_status != "fail":
                return _fail(3, f"[m46][P1] scenario={name} fail status requires drift_status=fail")
            if waived:
                return _fail(3, f"[m46][P1] scenario={name} fail status cannot set waived=true")
        else:
            waived_calc += 1
            if drift_status != "fail":
                return _fail(3, f"[m46][P1] scenario={name} waived status requires drift_status=fail")
            if not waived:
                return _fail(3, f"[m46][P1] scenario={name} waived status requires waived=true")

            reason = str(item.get("waiver_reason", "")).strip()
            expires = str(item.get("waiver_expires_at", "")).strip()
            if not reason or not expires:
                return _fail(3, f"[m46][P1] scenario={name} waived status requires reason + expires_at")
            try:
                exp = dt.date.fromisoformat(expires)
            except Exception:
                return _fail(3, f"[m46][P1] scenario={name} invalid waiver_expires_at: {expires!r}")
            if exp < dt.date.today():
                return _fail(3, f"[m46][P1] scenario={name} waiver expired: {expires}")

        for key in (
            "candidate_score_total_avg",
            "candidate_distance_to_target_avg",
            "score_delta",
            "distance_delta",
        ):
            ok, _ = _to_float(item.get(key))
            if not ok:
                return _fail(3, f"[m46][P1] scenario={name} invalid numeric field: {key}")

    if pass_calc != pass_count or fail_calc != fail_count or waived_calc != waived_count:
        return _fail(
            3,
            "[m46][P1] pass/fail/waived count mismatch "
            f"(report={pass_count}/{fail_count}/{waived_count}, calc={pass_calc}/{fail_calc}/{waived_calc})",
        )

    if (pass_count + fail_count + waived_count) != scenario_count:
        return _fail(3, "[m46][P1] pass+fail+waived must equal scenario_count")

    expected_status = "pass" if fail_count == 0 else "fail"
    if status != expected_status:
        return _fail(3, f"[m46][P1] status mismatch: status={status}, expected={expected_status}")

    for req in [str(x).strip() for x in args.required_scenario if str(x).strip()]:
        if req not in seen:
            return _fail(3, f"[m46][P1] missing required scenario: {req}")

    failures = report.get("failures")
    if not isinstance(failures, list):
        return _fail(3, "[m46][P1] failures must be list")
    if sorted(str(x).strip() for x in failures if str(x).strip()) != sorted([n for n in names if any(r.get("name") == n and str(r.get("status", "")).strip().lower() == "fail" for r in rows)]):
        return _fail(3, "[m46][P1] failures list mismatch with scenario_results")

    waivers = report.get("waivers")
    if not isinstance(waivers, list):
        return _fail(3, "[m46][P1] waivers must be list")

    ok, msg = _check_summary_object(report.get("score_delta_summary"), "score_delta_summary")
    if not ok:
        return _fail(3, f"[m46][P1] {msg}")
    ok, msg = _check_summary_object(report.get("distance_delta_summary"), "distance_delta_summary")
    if not ok:
        return _fail(3, f"[m46][P1] {msg}")

    if int(args.expect_pass) == 1 and status != "pass":
        return _fail(3, f"[m46][P1] expected pass but got status={status} fail_count={fail_count}")

    prefix = f"[m46:{args.label}] " if args.label else "[m46] "
    print(f"{prefix}status={status} scenarios={scenario_count} pass={pass_count} waived={waived_count} fail={fail_count}")
    print(f"{prefix}required_ok={len([x for x in args.required_scenario if str(x).strip()])}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
