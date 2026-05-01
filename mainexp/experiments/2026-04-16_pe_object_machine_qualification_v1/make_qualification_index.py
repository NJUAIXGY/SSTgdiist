#!/usr/bin/env python3
"""Build a qualification index across all PE object-machine cases."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import qualification_common as common


_refresh_run_artifacts = common.refresh_run_artifacts


def _case_index_entry(snapshot: Dict[str, Any], snapshot_path: Path) -> Dict[str, Any]:
    compact_objects = snapshot.get("compact_objects", {})
    return {
        "id": snapshot.get("case", {}).get("id"),
        "label": snapshot.get("case", {}).get("label"),
        "requested_run_dir": snapshot.get("case", {}).get("requested_run_dir"),
        "resolved_run_dir": snapshot.get("case", {}).get("resolved_run_dir"),
        "snapshot_path": str(snapshot_path),
        "validation": snapshot.get("validation", {}),
        "config": snapshot.get("config", {}),
        "closure": {
            key: compact_objects[key]
            for key in ("rowindex_object", "idx2_object", "preband_object")
            if key in compact_objects
        },
        "storage": {
            key: compact_objects[key]
            for key in ("shared_weight_residency", "weight_idx_store", "weight_value_store")
            if key in compact_objects
        },
        "control": {
            key: compact_objects[key]
            for key in ("activation_ingress_store", "rowdescriptor", "sync_barrier")
            if key in compact_objects
        },
        "unresolved_binding_entries": snapshot.get("derived", {}).get(
            "unresolved_binding_entries",
            0,
        ),
        "unresolved_binding_edges_total": snapshot.get("derived", {}).get(
            "unresolved_binding_edges_total",
            0,
        ),
        "schema_vocabularies": snapshot.get("derived", {}).get(
            "schema_vocabularies",
            {},
        ),
        "gate": {
            "status": common.gate_status_for_snapshot(snapshot),
            "blockers": snapshot.get("derived", {}).get("machine_blockers", []),
        },
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--cases",
        default=str(SCRIPT_DIR / "cases.json"),
        help="path to cases.json",
    )
    ap.add_argument(
        "--out",
        default=str(SCRIPT_DIR / "snapshot" / "qualification_index.json"),
        help="output qualification index path",
    )
    ap.add_argument(
        "--snapshot-dir",
        default=str(SCRIPT_DIR / "snapshot" / "cases"),
        help="directory to write per-case snapshots",
    )
    ap.add_argument(
        "--refresh-runs",
        action="store_true",
        help="refresh summary/trace/validation before indexing",
    )
    args = ap.parse_args(argv)

    cases_path = Path(args.cases).resolve()
    cases_payload = common.load_cases(cases_path)
    experiment_id = str(cases_payload.get("experiment_id") or SCRIPT_DIR.name)
    snapshot_dir = Path(args.snapshot_dir).resolve()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    project_root = SCRIPT_DIR.parents[2]

    case_entries: List[Dict[str, Any]] = []
    gate_statuses: List[str] = []
    unresolved_binding_edges_total = 0

    for case in cases_payload.get("cases", []):
        _, resolved_run_dir = common.resolve_run_dir(cases_path, case)
        if args.refresh_runs:
            _refresh_run_artifacts(resolved_run_dir, project_root)
        snapshot = common.build_case_snapshot(cases_path, experiment_id, case)
        snapshot_path = snapshot_dir / f"{case['id']}.object_machine_snapshot.json"
        common.write_json(snapshot_path, snapshot)
        case_entry = _case_index_entry(snapshot, snapshot_path)
        case_entries.append(case_entry)
        gate_statuses.append(case_entry["gate"]["status"])
        unresolved_binding_edges_total += int(
            case_entry.get("unresolved_binding_edges_total") or 0
        )

    payload = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "baseline_case": cases_payload.get("baseline_case"),
        "cases": case_entries,
        "summary": {
            "case_count": len(case_entries),
            "gate_status_counts": common.count_by(gate_statuses),
            "unresolved_binding_edges_total": unresolved_binding_edges_total,
        },
    }
    common.write_json(Path(args.out).resolve(), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
