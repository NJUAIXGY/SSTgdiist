#!/usr/bin/env python3
"""Build a compare.tsv snapshot for the PULSE OSA metadata transaction A/B run."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


VALIDATION_RE = re.compile(r"fail=(\d+)\s+warn=(\d+)(?:\s+strict=(\d+))?")

MAINLINE_METRICS: Tuple[str, ...] = (
    "validation.fail",
    "validation.warn",
    "validation.strict",
    "model.sim_time_actual_ns",
    "memory.memory_requests",
    "memory.memory_bytes",
    "memhierarchy.memctrl.req_total",
    "gas.gather_ns_avg",
    "gas.apply_ns_avg",
    "gas.scatter_ns_avg",
    "gas.memctrl_payload_utilization",
    "spike_activity.neurons_fired_total",
    "spike_activity.total_spikes_processed",
)

PULSE_METRICS: Tuple[str, ...] = (
    "pulse_pod_rowdescriptor_join_ready_total",
    "pulse_pod_rowdescriptor_late_join_total",
    "pulse_rowdescriptor_ready_join_shortcut_taken_total",
    "pulse_rowdescriptor_ready_join_shortcut_late_release_taken_total",
    "pulse_metadata_txn_export_total",
    "pulse_metadata_txn_owner_launch_total",
    "pulse_metadata_txn_join_live_total",
    "pulse_metadata_txn_join_ready_total",
    "pulse_metadata_txn_late_join_total",
    "pulse_metadata_txn_ready_lease_hit_total",
    "pulse_metadata_txn_ready_lease_expired_total",
    "pulse_metadata_txn_envelope_size_sum_total",
    "pulse_metadata_frontier_observed_total",
    "pulse_metadata_frontier_same_window_reobserve_total",
    "pulse_metadata_frontier_owner_form_candidate_total",
    "pulse_metadata_frontier_join_ready_candidate_total",
    "pulse_metadata_frontier_premphf_base_observed_total",
    "pulse_metadata_frontier_premphf_base_same_window_reobserve_total",
    "pulse_metadata_frontier_premphf_base_owner_form_candidate_total",
    "pulse_metadata_frontier_premphf_base_join_ready_candidate_total",
    "pulse_metadata_frontier_premphf_band_observed_total",
    "pulse_metadata_frontier_premphf_band_same_window_reobserve_total",
    "pulse_metadata_frontier_premphf_band_owner_form_candidate_total",
    "pulse_metadata_frontier_premphf_band_join_ready_candidate_total",
    "pulse_metadata_frontier_idx2row_observed_total",
    "pulse_metadata_frontier_idx2row_same_window_reobserve_total",
    "pulse_metadata_frontier_idx2row_owner_form_candidate_total",
    "pulse_metadata_frontier_idx2row_join_ready_candidate_total",
    "pulse_metadata_frontier_rowindex_observed_total",
    "pulse_metadata_frontier_rowindex_same_window_reobserve_total",
    "pulse_metadata_frontier_rowindex_owner_form_candidate_total",
    "pulse_metadata_frontier_rowindex_join_ready_candidate_total",
    "pulse_metadata_txn_ready_join_share",
    "pulse_metadata_txn_late_join_share",
    "pulse_metadata_txn_owner_to_elide_ratio",
)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_path(data: Dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _read_validation_counts(run_dir: Path) -> Dict[str, int]:
    fail = 0
    warn = 0
    strict = 0
    log_path = run_dir / "validation.log"
    if not log_path.exists():
        return {"fail": fail, "warn": warn, "strict": strict}
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = VALIDATION_RE.search(line)
        if match:
            fail = int(match.group(1))
            warn = int(match.group(2))
            strict = int(match.group(3) or 0)
    return {"fail": fail, "warn": warn, "strict": strict}


def _load_cases(path: Path) -> Tuple[str, str, List[Dict[str, str]]]:
    payload = _read_json(path)
    return (
        str(payload.get("experiment_id", path.parent.name)),
        str(payload.get("baseline_case", "")),
        list(payload.get("cases", [])),
    )


def _collect_case_metrics(run_dir: Path) -> Dict[str, Any]:
    summary = _read_json(run_dir / "essential_summary_mesh.json")
    validation = _read_validation_counts(run_dir)
    pulse = dict(summary.get("pulse", {}) or {})

    values: Dict[str, Any] = {
        "validation.fail": validation["fail"],
        "validation.warn": validation["warn"],
        "validation.strict": validation["strict"],
    }
    for metric in MAINLINE_METRICS[3:]:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in PULSE_METRICS:
        values[metric] = pulse.get(metric, 0)
    return values


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return "0"
    return str(value)


def _delta_value(base: Any, cand: Any) -> Any:
    try:
        if isinstance(base, int) and isinstance(cand, int):
            return cand - base
        return float(cand) - float(base)
    except Exception:
        return "na"


def _write_compare(
    out_path: Path,
    experiment_id: str,
    baseline_label: str,
    baseline_metrics: Dict[str, Any],
    candidate_rows: Sequence[Tuple[str, Dict[str, Any]]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["metric", "baseline"]
    for candidate_label, _ in candidate_rows:
        header.append(candidate_label)
        header.append(f"delta_vs_baseline__{candidate_label}")

    lines = [
        f"# experiment_id\t{experiment_id}",
        f"# baseline_case\t{baseline_label}",
        "# profile\tpulse_osa_metadata_txn_ab_v1",
        "\t".join(header),
    ]
    ordered_metrics = MAINLINE_METRICS + PULSE_METRICS
    for metric in ordered_metrics:
        base = baseline_metrics.get(metric, 0)
        row = [metric, _format_value(base)]
        for _, candidate_metrics in candidate_rows:
            cand = candidate_metrics.get(metric, 0)
            row.append(_format_value(cand))
            row.append(_format_value(_delta_value(base, cand)))
        lines.append("\t".join(row))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--cases",
        default=str(Path(__file__).resolve().with_name("cases.json")),
        help="path to cases.json",
    )
    ap.add_argument(
        "--out",
        default=str(Path(__file__).resolve().with_name("snapshot") / "compare.tsv"),
        help="output compare.tsv path",
    )
    args = ap.parse_args()

    cases_path = Path(args.cases).resolve()
    out_path = Path(args.out).resolve()
    experiment_id, baseline_case_id, cases = _load_cases(cases_path)
    case_by_id = {str(case.get("id", "")): case for case in cases}
    if baseline_case_id not in case_by_id:
        raise SystemExit(f"baseline case not found: {baseline_case_id}")

    baseline_case = case_by_id[baseline_case_id]
    baseline_metrics = _collect_case_metrics(
        (cases_path.parent / str(baseline_case.get("run_dir", ""))).resolve()
    )

    candidate_rows: List[Tuple[str, Dict[str, Any]]] = []
    for case in cases:
        case_id = str(case.get("id", ""))
        if case_id == baseline_case_id:
            continue
        candidate_rows.append(
            (
                case_id,
                _collect_case_metrics((cases_path.parent / str(case.get("run_dir", ""))).resolve()),
            )
        )

    _write_compare(
        out_path,
        experiment_id,
        baseline_case_id,
        baseline_metrics,
        candidate_rows,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
