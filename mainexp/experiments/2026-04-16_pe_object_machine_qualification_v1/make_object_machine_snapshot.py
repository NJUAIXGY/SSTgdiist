#!/usr/bin/env python3
"""Build a PE object-machine snapshot for one qualification case."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import qualification_common as common


_refresh_run_artifacts = common.refresh_run_artifacts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--cases",
        default=str(SCRIPT_DIR / "cases.json"),
        help="path to cases.json",
    )
    ap.add_argument("--case-id", required=True, help="case id to snapshot")
    ap.add_argument(
        "--out",
        default=str(SCRIPT_DIR / "snapshot" / "object_machine_snapshot.json"),
        help="output snapshot path",
    )
    ap.add_argument(
        "--refresh-runs",
        action="store_true",
        help="refresh summary/trace/validation before snapshotting",
    )
    args = ap.parse_args(argv)

    cases_path = Path(args.cases).resolve()
    cases_payload = common.load_cases(cases_path)
    case = common.find_case(cases_payload, args.case_id)
    _, resolved_run_dir = common.resolve_run_dir(cases_path, case)
    project_root = SCRIPT_DIR.parents[2]
    if args.refresh_runs:
        _refresh_run_artifacts(resolved_run_dir, project_root)

    snapshot = common.build_case_snapshot(
        cases_path,
        str(cases_payload.get("experiment_id") or SCRIPT_DIR.name),
        case,
    )
    common.write_json(Path(args.out).resolve(), snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
