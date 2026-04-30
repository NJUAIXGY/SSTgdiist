#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from riscv_snn_isa_lab.tools import riscv_snn_lab


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nightly_sidecar.py",
        description="Isolated CI sidecar for the experimental riscv_snn nightly gate",
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=None,
        help="Override the required nightly family count; default derives from the authority family surface",
    )
    parser.add_argument(
        "--summary",
        default="",
        help="Override the dated nightly index output path",
    )
    parser.add_argument(
        "--history",
        default="",
        help="Override the stable history index output path",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Override the stable sidecar gate report output path",
    )
    parser.add_argument(
        "--no-register",
        action="store_true",
        help="Skip manifest registration for the underlying nightly matrix runs",
    )
    parser.add_argument(
        "--no-protocol",
        action="store_true",
        help="Skip the toolchain audit protocol precheck in the underlying nightly gate",
    )
    parser.add_argument(
        "--with-equivalence",
        action="store_true",
        help="Attach the dated equivalence matrix to the sidecar report and fold it into the top-level experimental gate",
    )
    parser.add_argument(
        "--with-full-equivalence",
        action="store_true",
        help="Attach the dated full-all equivalence snapshot as a research-only non-blocking section",
    )
    parser.add_argument(
        "--with-optional-group",
        action="append",
        default=[],
        choices=tuple(sorted(riscv_snn_lab._mainline_optional_groups())),
        help=(
            "Attach one authority-defined optional-group equivalence surface as a research-only non-blocking "
            "section; repeat as needed"
        ),
    )
    parser.add_argument(
        "--with-queue-equivalence",
        action="store_true",
        help=(
            "Attach the dated queue_optional equivalence matrix as a research-only non-blocking section "
            "without changing the default authority-required family gate"
        ),
    )
    parser.add_argument(
        "--with-abi-audit",
        action="store_true",
        help="Attach the dated ABI authority audit to the sidecar report without making it a blocking gate",
    )
    parser.add_argument(
        "--with-artifact-isolation",
        action="store_true",
        help="Attach the stable artifact-isolation verifier report as a research-only non-blocking section",
    )
    args = parser.parse_args(argv)

    report = riscv_snn_lab.run_ci_sidecar(
        min_count=int(args.min_count) if args.min_count is not None else None,
        register=not bool(args.no_register),
        protocol=not bool(args.no_protocol),
        with_equivalence=bool(args.with_equivalence),
        with_full_equivalence=bool(args.with_full_equivalence),
        with_optional_groups=list(args.with_optional_group) if args.with_optional_group else None,
        with_queue_equivalence=bool(args.with_queue_equivalence),
        with_abi_audit=bool(args.with_abi_audit),
        with_artifact_isolation=bool(args.with_artifact_isolation),
        summary_path=Path(args.summary) if args.summary else None,
        history_path=Path(args.history) if args.history else None,
        report_path=Path(args.report) if args.report else None,
    )
    print(report["report_path"])
    return 0 if report["gate_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
