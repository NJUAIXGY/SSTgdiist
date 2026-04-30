#!/usr/bin/env python3
"""Aggregate M100 phase6 regression gate results."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List


def _parse_results(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for ln, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 4:
            raise ValueError(f"line {ln}: expected 4 columns: gate status report_dir log")
        gate = str(parts[0]).strip()
        status = str(parts[1]).strip().lower()
        report_dir = str(parts[2]).strip()
        log_path = str(parts[3]).strip()
        if not gate:
            raise ValueError(f"line {ln}: empty gate")
        if status not in {"pass", "fail"}:
            raise ValueError(f"line {ln}: invalid status={status!r}")
        rows.append({"gate": gate, "status": status, "report_dir": report_dir, "log": log_path})
    if not rows:
        raise ValueError("results file has no rows")
    return rows


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-file", required=True, help="TSV results file")
    ap.add_argument("--out", required=True, help="output json report")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    results_p = Path(args.results_file).expanduser().resolve()
    out_p = Path(args.out).expanduser().resolve()

    if not results_p.exists():
        print(f"[m100][P0] missing --results-file: {results_p}", file=sys.stderr)
        return 2

    try:
        rows = _parse_results(results_p)
    except Exception as exc:
        print(f"[m100][P0] invalid results file: {exc}", file=sys.stderr)
        return 2

    gate_count = len(rows)
    pass_count = sum(1 for r in rows if r["status"] == "pass")
    fail_count = gate_count - pass_count
    failures = sorted(r["gate"] for r in rows if r["status"] == "fail")

    report = {
        "schema_version": 1,
        "phase": "phase6",
        "generated_at_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "status": "pass" if fail_count == 0 else "fail",
        "results_file": str(results_p),
        "gate_count": int(gate_count),
        "pass_count": int(pass_count),
        "fail_count": int(fail_count),
        "gate_results": rows,
        "failures": failures,
    }

    try:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[m100][P0] write report failed: {exc}", file=sys.stderr)
        return 2

    prefix = f"[m100:{args.label}] " if args.label else "[m100] "
    print(f"{prefix}status={report['status']} gates={gate_count} pass={pass_count} fail={fail_count}")
    print(f"{prefix}report={out_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
