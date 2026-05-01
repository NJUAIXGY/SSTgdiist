#!/usr/bin/env python3
"""Build a compare.tsv snapshot for the isolated owner-first + metadata-frontier combo A/B run."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


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
    "gas.cycle_cost",
    "gas.synapse_ops_step_total",
)

PULSE_METRICS: Tuple[str, ...] = (
    "pulse_mfb_gather_owner_first_rate",
    "pulse_pod_rowdescriptor_owner_first_issue_deferred_total",
    "pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total",
    "pulse_pod_rowdescriptor_owner_first_service_elide_total",
    "pulse_rowdescriptor_owner_first_service_elide_join_live_total",
    "pulse_rowdescriptor_owner_first_service_elide_join_ready_total",
    "pulse_rowdescriptor_owner_first_service_elide_late_join_total",
    "pulse_mfb_gather_preband_register_no_trigger_total",
    "pulse_mfb_gather_preband_replay_enqueued_total",
    "pulse_mfb_gather_preband_replay_dropped_budget_total",
    "pulse_metadata_frontier_windows_total",
    "pulse_metadata_frontier_base_items_exported_total",
    "pulse_metadata_frontier_base_overlap_items_total",
    "pulse_metadata_frontier_base_overlap_peer_total",
    "pulse_metadata_frontier_base_consumer_count_sum_total",
    "pulse_metadata_frontier_band_items_exported_total",
    "pulse_metadata_frontier_band_overlap_items_total",
    "pulse_metadata_frontier_band_overlap_peer_total",
    "pulse_metadata_frontier_band_consumer_count_sum_total",
    "pulse_mfb_gather_owner_lines_useful_total",
    "pulse_mfb_gather_owner_lines_dead_total",
    "pulse_mfb_gather_owner_lines_useful_head2_total",
    "pulse_mfb_gather_owner_lines_useful_tail_total",
    "pulse_mfb_gather_owner_lines_dead_head2_total",
    "pulse_mfb_gather_owner_lines_dead_tail_total",
    "pulse_mfb_gather_resident_hits_total",
    "pulse_mfb_gather_launched_bands_dead_total",
    "pulse_mfb_gather_launched_bands_single_useful_total",
    "pulse_mfb_gather_launched_bands_multi_useful_total",
    "pulse_mfb_gather_launched_bands_head2_useful_total",
    "pulse_mfb_gather_launched_bands_tail_only_useful_total",
    "pulse_mfb_gather_launched_bands_head2_dead_total",
    "pulse_mfb_gather_launched_bands_multi_resident_total",
    "pulse_mfb_gather_launched_bands_resident_hits_total",
)

EFFECTIVE_CONFIG_METRICS: Tuple[str, ...] = (
    "effective.pulse.metadata_frontier_observe_enable",
    "effective.pulse.metadata_frontier_band_slots",
    "effective.pulse.mfb_preband_band_slots",
    "effective.pulse.mfb_gather_window_budget",
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


def _collect_case_metrics(run_dir: Path) -> Dict[str, Any]:
    summary = _read_json(run_dir / "essential_summary_mesh.json")
    effective_config = {}
    effective_path = run_dir / "effective_config.json"
    if effective_path.exists():
        effective_config = _read_json(effective_path)
    validation = _read_validation_counts(run_dir)
    pulse = dict(summary.get("pulse", {}) or {})

    values: Dict[str, Any] = {
        "validation.fail": validation["fail"],
        "validation.warn": validation["warn"],
        "validation.strict": validation["strict"],
    }
    for metric in MAINLINE_METRICS[3:]:
        value = _get_path(summary, metric)
        values[metric] = 0.0 if value is None else value
    for metric in PULSE_METRICS:
        values[metric] = pulse.get(metric, 0)
    for metric in EFFECTIVE_CONFIG_METRICS:
        values[metric] = _get_path(effective_config, metric[len("effective."):])
    return values


def _load_cases(path: Path) -> Tuple[str, List[Dict[str, str]]]:
    payload = _read_json(path)
    cases = payload.get("cases", [])
    baseline_case = payload.get("baseline_case", "")
    if not isinstance(cases, list) or len(cases) != 2:
        raise SystemExit("this experiment expects exactly 2 cases in cases.json")
    return baseline_case, cases


def _format_value(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if value is None:
        return "None"
    return str(value)


def _delta_value(base: Any, cand: Any) -> Any:
    if base is None or cand is None:
        return "NA"
    if isinstance(base, int) and isinstance(cand, int):
        return cand - base
    try:
        return float(cand) - float(base)
    except (TypeError, ValueError):
        return "NA"


def _write_compare(
    out_path: Path,
    experiment_id: str,
    baseline_label: str,
    candidate_label: str,
    baseline_metrics: Dict[str, Any],
    candidate_metrics: Dict[str, Any],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# experiment_id\t{experiment_id}",
        f"# baseline_case\t{baseline_label}",
        "# profile\tpulse_owner_first_frontier_combo_ab_v1",
        f"metric\tbaseline\t{candidate_label}\tdelta",
    ]
    for metric in MAINLINE_METRICS + PULSE_METRICS + EFFECTIVE_CONFIG_METRICS:
        base = baseline_metrics.get(metric, 0)
        cand = candidate_metrics.get(metric, 0)
        delta = _delta_value(base, cand)
        lines.append(
            "\t".join(
                [
                    metric,
                    _format_value(base),
                    _format_value(cand),
                    _format_value(delta),
                ]
            )
        )
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
    candidate_case = next(case for case in cases if str(case.get("id", "")) != baseline_case_id)

    baseline_metrics = _collect_case_metrics(Path(str(baseline_case.get("run_dir", ""))).resolve())
    candidate_metrics = _collect_case_metrics(Path(str(candidate_case.get("run_dir", ""))).resolve())

    _write_compare(
        out_path,
        experiment_id=experiment_id,
        baseline_label=str(baseline_case.get("id", "baseline")),
        candidate_label=str(candidate_case.get("id", "candidate")),
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
    )
    print(f"[snapshot] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
