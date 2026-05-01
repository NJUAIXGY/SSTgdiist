#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple


METRICS: Tuple[str, ...] = (
    "validation.fail",
    "validation.warn",
    "memory.memory_requests",
    "memhierarchy.memctrl.req_total",
    "atlas_shadow.rowindex.runtime_rowidx_prefetch_complete_inflight_miss_total",
    "atlas_shadow.rowindex.runtime_rowidx_prefetch_complete_zero_waiters_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total",
    "noc_mem_joint.rowidx_detached_demand_join_total",
    "noc_mem_joint.rowidx_detached_demand_waiters_resolved_total",
    "noc_mem_joint.rowidx_detached_demand_fallback_zero_total",
    "noc_mem_joint.rowidx_detached_demand_ready_signal_total",
    "noc_mem_joint.rowidx_detached_demand_ready_transition_total",
)


def read_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_path(obj: Dict, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def load_cases(path: Path) -> Tuple[str, List[Dict[str, str]]]:
    payload = read_json(path)
    return str(payload.get("baseline_case", "")), list(payload.get("cases", []))


def collect_validation(run_dir: Path) -> Dict[str, int]:
    log = run_dir / "validation.log"
    out = {"validation.fail": 0, "validation.warn": 0}
    if not log.exists():
        return out
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "SUMMARY run_dir=" in line:
            for token in line.split():
                if token.startswith("fail="):
                    out["validation.fail"] = int(token.split("=", 1)[1])
                elif token.startswith("warn="):
                    out["validation.warn"] = int(token.split("=", 1)[1])
    return out


def collect_case(run_dir: Path) -> Dict[str, object]:
    summary = read_json(run_dir / "essential_summary_mesh.json")
    data: Dict[str, object] = {}
    data.update(collect_validation(run_dir))
    for metric in METRICS:
        if metric.startswith("validation."):
            continue
        data[metric] = get_path(summary, metric)
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    cases_path = Path(args.cases)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    baseline, cases = load_cases(cases_path)
    root = cases_path.parent

    rows: List[List[str]] = [["metric", "baseline_case", "baseline_value", "case", "case_value"]]
    baseline_case = next((c for c in cases if c["id"] == baseline), None)
    if baseline_case is None:
      raise SystemExit(f"missing baseline case: {baseline}")

    baseline_data = collect_case((root / baseline_case["run_dir"]).resolve())
    for case in cases:
        case_id = case["id"]
        case_data = collect_case((root / case["run_dir"]).resolve())
        for metric in METRICS:
            rows.append([
                metric,
                baseline,
                str(baseline_data.get(metric)),
                case_id,
                str(case_data.get(metric)),
            ])

    with out_path.open("w", encoding="utf-8", newline="") as fout:
        writer = csv.writer(fout, delimiter="\t")
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
