#!/usr/bin/env python3
"""Validate M66 readiness-v3 report contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


LEVELS = {"L0", "L1", "L2", "L3"}


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--min-scenarios", type=int, default=2)
    ap.add_argument("--expect-interventions", type=int, default=1)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    report_p = Path(args.report).expanduser().resolve()
    if not report_p.exists():
        return _fail(2, f"[m66][P0] missing --report: {report_p}")

    try:
        report = _load_json(report_p)
    except Exception as exc:
        return _fail(2, f"[m66][P0] cannot parse report json: {exc}")

    if not isinstance(report, dict):
        return _fail(2, "[m66][P0] report root must be object")

    scenario_count = int(report.get("scenario_count", 0) or 0)
    if scenario_count < max(1, int(args.min_scenarios)):
        return _fail(3, f"[m66][P1] scenario_count too small: {scenario_count} < {args.min_scenarios}")

    rows = report.get("scenarios")
    if not isinstance(rows, list) or len(rows) != scenario_count:
        return _fail(3, "[m66][P1] scenarios must be list and match scenario_count")

    lvl = str(report.get("readiness_level", "")).strip().upper()
    if lvl not in LEVELS:
        return _fail(3, f"[m66][P1] invalid readiness_level={lvl!r}")

    dom = report.get("dominant_layer_distribution")
    if not isinstance(dom, dict) or not dom:
        return _fail(3, "[m66][P1] dominant_layer_distribution must be non-empty object")

    top = report.get("top_bottlenecks_union")
    if not isinstance(top, list) or not top:
        return _fail(3, "[m66][P1] top_bottlenecks_union must be non-empty list")

    interventions = report.get("suggested_interventions_ranked")
    if int(args.expect_interventions) == 1:
        if not isinstance(interventions, list) or not interventions:
            return _fail(3, "[m66][P1] expected non-empty suggested_interventions_ranked")

    prefix = f"[m66:{args.label}] " if args.label else "[m66] "
    print(
        f"{prefix}scenarios={scenario_count} readiness_level={lvl} "
        f"dominant_layers={len(dom)} top_bottlenecks={len(top)} interventions={len(interventions) if isinstance(interventions, list) else 0}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
