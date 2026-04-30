#!/usr/bin/env python3
"""Validate M45 feedback patch safety contract."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

CONF_RANK = {"unverified": 0, "low": 1, "medium": 2, "high": 3}


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


def _rank(conf: str) -> int:
    return CONF_RANK.get(str(conf or "").strip().lower(), -1)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch-report", required=True, help="M45 patch report json")
    ap.add_argument("--whitelist", required=True, help="M45 whitelist json")
    ap.add_argument("--expect-pass", type=int, default=1, help="when 1, require status=pass and no violations")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    report_path = Path(args.patch_report).expanduser().resolve()
    whitelist_path = Path(args.whitelist).expanduser().resolve()

    for p, flag in ((report_path, "--patch-report"), (whitelist_path, "--whitelist")):
        if not p.exists():
            return _fail(2, f"[m45][P0] missing {flag}: {p}")

    try:
        report = _load_json(report_path)
        whitelist = _load_json(whitelist_path)
    except Exception as exc:
        return _fail(2, f"[m45][P0] cannot parse json: {exc}")

    if not isinstance(report, dict) or not isinstance(whitelist, dict):
        return _fail(2, "[m45][P0] report/whitelist root must be object")

    status = str(report.get("status", "")).strip().lower()
    if status not in {"pass", "fail"}:
        return _fail(3, f"[m45][P1] invalid status: {status!r}")

    allowed_paths = {str(x).strip() for x in whitelist.get("allowed_paths", []) if str(x).strip()}
    if not allowed_paths:
        return _fail(3, "[m45][P1] whitelist.allowed_paths must be non-empty")

    numeric_limits = whitelist.get("numeric_limits") if isinstance(whitelist.get("numeric_limits"), dict) else {}

    applied = report.get("applied_changes")
    if not isinstance(applied, list):
        return _fail(3, "[m45][P1] applied_changes must be list")

    for idx, item in enumerate(applied):
        if not isinstance(item, dict):
            return _fail(3, f"[m45][P1] applied_changes[{idx}] must be object")
        path = str(item.get("path", "")).strip()
        if not path:
            return _fail(3, f"[m45][P1] applied_changes[{idx}] missing path")
        if path not in allowed_paths:
            return _fail(3, f"[m45][P1] path not in whitelist: {path}")

        if path in numeric_limits:
            rule = numeric_limits.get(path)
            if not isinstance(rule, dict):
                return _fail(3, f"[m45][P1] invalid numeric limit rule for {path}")

            ok_old, old_v = _to_float(item.get("old"))
            ok_new, new_v = _to_float(item.get("new"))
            if not ok_old or not ok_new:
                return _fail(3, f"[m45][P1] non-numeric old/new for {path}")

            ok_min, min_v = _to_float(rule.get("min"))
            ok_max, max_v = _to_float(rule.get("max"))
            ok_ratio, max_ratio = _to_float(rule.get("max_ratio"))
            if not ok_min or not ok_max or min_v > max_v:
                return _fail(3, f"[m45][P1] invalid min/max rule for {path}")
            if new_v < min_v or new_v > max_v:
                return _fail(3, f"[m45][P1] new value out of min/max for {path}")
            if ok_ratio and max_ratio > 1.0 and old_v > 0.0:
                lo = old_v / max_ratio
                hi = old_v * max_ratio
                if new_v < lo - 1e-9 or new_v > hi + 1e-9:
                    return _fail(3, f"[m45][P1] new value breaks max_ratio for {path}")

    conf = str(report.get("profile_confidence", "")).strip().lower()
    conf_min = str(report.get("confidence_min", "")).strip().lower()
    if _rank(conf) < 0 or _rank(conf_min) < 0:
        return _fail(3, "[m45][P1] invalid confidence fields")
    if _rank(conf) < _rank(conf_min):
        return _fail(3, "[m45][P1] profile confidence lower than minimum")

    violations = report.get("violations")
    if not isinstance(violations, list):
        return _fail(3, "[m45][P1] violations must be list")

    if int(args.expect_pass) == 1:
        if status != "pass":
            return _fail(3, f"[m45][P1] expected pass but got status={status}")
        if violations:
            return _fail(3, f"[m45][P1] expected no violations but got {len(violations)}")

    prefix = f"[m45:{args.label}] " if args.label else "[m45] "
    print(f"{prefix}status={status} applied={len(applied)} violations={len(violations)}")
    print(f"{prefix}confidence={conf} min={conf_min}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
