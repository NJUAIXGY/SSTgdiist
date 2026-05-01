#!/usr/bin/env python3
"""Build a compare.tsv snapshot for the PULSE rowdescriptor ready-join dedup A/B run."""

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
    "gas.apply_ns_avg",
    "gas.gather_ns_avg",
    "gas.scatter_ns_avg",
    "gas.memctrl_payload_utilization",
    "spike_activity.neurons_fired_total",
    "spike_activity.total_spikes_processed",
)

SNN_EDGE_RECORD_METRICS: Tuple[str, ...] = (
    "snn_edge_record.attempt_total",
    "snn_edge_record.commit_total",
    "snn_edge_record.skip_gate_total",
    "snn_edge_record.skip_stage_total",
    "snn_edge_record.skip_capacity_total",
    "snn_edge_record.skip_reject_total",
    "snn_edge_record.fastpath_handler_entry_total",
    "snn_edge_record.fastpath_wms_missing_total",
    "snn_edge_record.fastpath_backend_not_ready_total",
    "snn_edge_record.fastpath_stage_block_total",
    "snn_edge_record.process_local_handler_entry_total",
    "snn_edge_record.process_local_wms_missing_total",
    "snn_edge_record.process_local_backend_not_ready_total",
    "snn_edge_record.process_local_stage_block_total",
    "snn_edge_record.deliver_window_handler_entry_total",
    "snn_edge_record.deliver_window_wms_missing_total",
    "snn_edge_record.deliver_window_backend_not_ready_total",
    "snn_edge_record.deliver_window_stage_block_total",
)

SNN_WMS_FRONTIER_METRICS: Tuple[str, ...] = (
    "snn_wms_frontier.record_prerank_entry_total",
    "snn_wms_frontier.record_prerank_premphf_mode_total",
    "snn_wms_frontier.record_prerank_existing_rank_total",
    "snn_wms_frontier.record_prerank_new_rank_total",
    "snn_wms_frontier.record_prerank_total",
    "snn_wms_frontier.collect_entry_total",
    "snn_wms_frontier.lookup_attempt_total",
    "snn_wms_frontier.collect_line_notes_total",
)

PULSE_METRICS: Tuple[str, ...] = (
    "pulse_shared_service_hits_total",
    "pulse_shared_service_misses_total",
    "pulse_ready_fanout_total",
    "pulse_ready_fanout_avg",
    "pulse_actual_gate_taken_total",
    "pulse_mfb_gather_record_prerank_entry_total",
    "pulse_mfb_gather_record_prerank_premphf_mode_total",
    "pulse_mfb_gather_record_prerank_existing_rank_total",
    "pulse_mfb_gather_record_prerank_new_rank_total",
    "pulse_mfb_gather_record_prerank_total",
    "pulse_mfb_gather_gate_reject_total",
    "pulse_mfb_gather_collect_entry_total",
    "pulse_mfb_gather_lookup_attempt_total",
    "pulse_mfb_gather_lookup_hit_total",
    "pulse_mfb_gather_lookup_miss_total",
    "pulse_mfb_gather_prerank_oob_total",
    "pulse_mfb_gather_collect_line_notes_total",
    "pulse_mfb_gather_collected_bands_total",
    "pulse_mfb_gather_barrier_input_bands_total",
    "pulse_mfb_gather_barrier_replay_bands_total",
    "pulse_mfb_gather_register_trigger_total",
    "pulse_mfb_gather_owner_first_rate",
    "pulse_rowdescriptor_ready_transition_total",
    "pulse_rowdescriptor_join_ready_total",
    "pulse_rowdescriptor_ready_join_shortcut_candidates_total",
    "pulse_rowdescriptor_ready_join_shortcut_taken_total",
    "pulse_rowdescriptor_ready_join_shortcut_blocked_not_ready_total",
    "pulse_rowdescriptor_ready_join_shortcut_release_deferred_total",
    "pulse_rowdescriptor_ready_join_shortcut_apply_complete_total",
    "pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total",
    "pulse_rowdescriptor_ready_join_shortcut_release_missing_total",
    "pulse_rowdescriptor_ready_join_descriptor_elide_total",
    "pulse_rowdescriptor_ready_join_lines_elide_total",
    "pulse_rowdescriptor_ready_join_lines_per_descriptor_elide_avg",
    "pulse_pod_rowdescriptor_owner_first_issue_deferred_total",
    "pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total",
    "pulse_pod_rowdescriptor_owner_first_service_elide_total",
)


def _get_path(data: Dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _safe_ratio(numer: Any, denom: Any) -> float | None:
    try:
        n = float(numer)
        d = float(denom)
    except Exception:
        return None
    if d == 0.0:
        return None
    return n / d


def _collect_case_metrics(run_dir: Path) -> Dict[str, Any]:
    summary = _read_json(run_dir / "essential_summary_mesh.json")
    validation = _read_validation_counts(run_dir)
    pulse = dict(summary.get("pulse", {}) or {})
    elide_avg = _safe_ratio(
        pulse.get("pulse_rowdescriptor_ready_join_lines_elide_total", 0),
        pulse.get("pulse_rowdescriptor_ready_join_descriptor_elide_total", 0),
    )
    if elide_avg is not None:
        pulse["pulse_rowdescriptor_ready_join_lines_per_descriptor_elide_avg"] = elide_avg

    values: Dict[str, Any] = {
        "validation.fail": validation["fail"],
        "validation.warn": validation["warn"],
        "validation.strict": validation["strict"],
    }
    for metric in MAINLINE_METRICS[3:]:
        value = _get_path(summary, metric)
        values[metric] = 0.0 if value is None else value
    for metric in SNN_EDGE_RECORD_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in SNN_WMS_FRONTIER_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in PULSE_METRICS:
        values[metric] = pulse.get(metric, 0)
    return values


def _load_cases(path: Path) -> Tuple[str, List[Dict[str, str]]]:
    payload = _read_json(path)
    cases = payload.get("cases", [])
    baseline_case = payload.get("baseline_case", "")
    if not isinstance(cases, list) or len(cases) < 2:
        raise SystemExit("this experiment expects at least 2 cases in cases.json")
    return baseline_case, cases


def _format_value(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if value is None:
        return "0"
    return str(value)


def _delta_value(base: Any, cand: Any) -> Any:
    if isinstance(base, int) and isinstance(cand, int):
        return cand - base
    return float(cand) - float(base)


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
        "# profile\tpulse_rowdescriptor_ready_join_dedup_ab_v1",
        "\t".join(header),
    ]
    ordered_metrics = MAINLINE_METRICS + SNN_EDGE_RECORD_METRICS + SNN_WMS_FRONTIER_METRICS + PULSE_METRICS
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
    baseline_case_id, cases = _load_cases(cases_path)
    payload = _read_json(cases_path)
    experiment_id = str(payload.get("experiment_id", cases_path.parent.name))

    case_by_id = {str(case.get("id", "")): case for case in cases}
    if baseline_case_id not in case_by_id:
        raise SystemExit(f"baseline case not found: {baseline_case_id}")

    baseline_case = case_by_id[baseline_case_id]
    baseline_metrics = _collect_case_metrics(Path(str(baseline_case.get("run_dir", ""))).resolve())

    candidate_rows: List[Tuple[str, Dict[str, Any]]] = []
    for case in cases:
        case_id = str(case.get("id", ""))
        if case_id == baseline_case_id:
            continue
        candidate_rows.append(
            (
                case_id,
                _collect_case_metrics(Path(str(case.get("run_dir", ""))).resolve()),
            )
        )

    _write_compare(
        out_path,
        experiment_id=experiment_id,
        baseline_label=str(baseline_case.get("id", "baseline")),
        baseline_metrics=baseline_metrics,
        candidate_rows=candidate_rows,
    )
    print(f"[snapshot] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
