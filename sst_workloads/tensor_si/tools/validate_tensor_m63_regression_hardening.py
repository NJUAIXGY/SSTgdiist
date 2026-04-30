#!/usr/bin/env python3
"""Validate top-level regression gate realism wiring contract (M63)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List


REALISM_GATES = [(gate, gate - 16) for gate in range(47, 111)]


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="path to tools/run_snndl_regression_gate.sh")
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    script_p = Path(args.script).expanduser().resolve()
    if not script_p.exists():
        return _fail(2, f"[m63][P0] missing --script: {script_p}")

    text = script_p.read_text(encoding="utf-8", errors="ignore")

    for gate, fail_code in REALISM_GATES:
        decl = f'm{gate}_report_dir=""'
        if decl not in text:
            return _fail(3, f"[m63][P1] missing declaration: {decl}")

        run_pat = re.compile(
            rf'^\s*m{gate}_report_dir="\$\(run_realism_gate\s+"m{gate}"\s+"\$REPO_ROOT/tools/run_tensor_m{gate}_gate\.sh"\s+{fail_code}\s*\)"\s*$',
            re.MULTILINE,
        )
        if not run_pat.search(text):
            return _fail(3, f"[m63][P1] missing/invalid run_realism_gate wiring for m{gate} fail_code={fail_code}")

        out_pat = re.compile(
            rf'^\s*echo\s+.*tensor_m{gate}_report_dir=.*\$m{gate}_report_dir.*$',
            re.MULTILINE,
        )
        if not out_pat.search(text):
            return _fail(3, f"[m63][P1] missing report output line for m{gate}")

    prefix = f"[m63:{args.label}] " if args.label else "[m63] "
    print(f"{prefix}realism_gates={len(REALISM_GATES)} wiring=ok")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
