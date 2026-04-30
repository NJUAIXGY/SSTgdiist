#!/usr/bin/env python3
"""Validate M47 full regression report contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="m47 report json")
    ap.add_argument("--min-gates", type=int, default=10, help="minimum expected gate count")
    ap.add_argument("--required-gate", action="append", default=[], help="required gate id")
    ap.add_argument("--expect-pass", type=int, default=1, help="1=require status=pass")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    report_p = Path(args.report).expanduser().resolve()
    if not report_p.exists():
        return _fail(2, f"[m47][P0] missing --report: {report_p}")

    try:
        report = _load_json(report_p)
    except Exception as exc:
        return _fail(2, f"[m47][P0] cannot parse report json: {exc}")

    if not isinstance(report, dict):
        return _fail(2, "[m47][P0] report root must be object")

    status = str(report.get("status", "")).strip().lower()
    if status not in {"pass", "fail"}:
        return _fail(3, f"[m47][P1] invalid status={status!r}")

    rows = report.get("gate_results")
    if not isinstance(rows, list):
        return _fail(3, "[m47][P1] gate_results must be list")

    gate_count = int(report.get("gate_count", 0) or 0)
    pass_count = int(report.get("pass_count", 0) or 0)
    fail_count = int(report.get("fail_count", 0) or 0)

    if gate_count < max(1, int(args.min_gates)):
        return _fail(3, f"[m47][P1] gate_count too small: {gate_count} < {args.min_gates}")
    if len(rows) != gate_count:
        return _fail(3, "[m47][P1] gate_results size mismatch gate_count")

    seen = set()
    pass_calc = 0
    fail_calc = 0
    failures_expected: List[str] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return _fail(3, f"[m47][P1] gate_results[{idx}] must be object")
        gate = str(row.get("gate", "")).strip()
        row_status = str(row.get("status", "")).strip().lower()
        if not gate:
            return _fail(3, f"[m47][P1] gate_results[{idx}] missing gate")
        if gate in seen:
            return _fail(3, f"[m47][P1] duplicate gate={gate}")
        seen.add(gate)
        if row_status not in {"pass", "fail"}:
            return _fail(3, f"[m47][P1] gate={gate} invalid status={row_status!r}")
        if row_status == "pass":
            pass_calc += 1
        else:
            fail_calc += 1
            failures_expected.append(gate)

    if pass_calc != pass_count or fail_calc != fail_count:
        return _fail(3, f"[m47][P1] count mismatch report={pass_count}/{fail_count} calc={pass_calc}/{fail_calc}")

    expected_status = "pass" if fail_count == 0 else "fail"
    if status != expected_status:
        return _fail(3, f"[m47][P1] status mismatch status={status} expected={expected_status}")

    failures = report.get("failures")
    if not isinstance(failures, list):
        return _fail(3, "[m47][P1] failures must be list")
    failures_norm = sorted(str(x).strip() for x in failures if str(x).strip())
    if failures_norm != sorted(failures_expected):
        return _fail(3, "[m47][P1] failures list mismatch")

    for req in [str(x).strip() for x in args.required_gate if str(x).strip()]:
        if req not in seen:
            return _fail(3, f"[m47][P1] missing required gate: {req}")

    if int(args.expect_pass) == 1 and status != "pass":
        return _fail(3, f"[m47][P1] expected pass but got status={status}")

    prefix = f"[m47:{args.label}] " if args.label else "[m47] "
    print(f"{prefix}status={status} gates={gate_count} pass={pass_count} fail={fail_count}")
    print(f"{prefix}required_ok={len([x for x in args.required_gate if str(x).strip()])}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
