#!/usr/bin/env python3
"""Build grid summary (TSV) for metadata-frontier/preband sweeps with derived probes."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


LEGACY_CASE_RE = re.compile(
    r"^pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top(?P<top>\d+)_band(?P<band>\d+)$"
)
PHASE_PROBE_CASE_RE = re.compile(
    r"^pulse_shared_line_actual_mfb_gather_preband_dedup_off_"
    r"metadata_frontier_top(?P<top>\d+)_"
    r"observe_band(?P<observe>\d+)_"
    r"preband_band(?P<preband>\d+)_"
    r"budget(?P<budget>\d+)$"
)
VALIDATION_RE = re.compile(r"fail=(\d+)\s+warn=(\d+)(?:\s+strict=(\d+))?")

BASELINE_CASE_ID = "pulse_shared_line_actual_mfb_gather_preband_dedup_off"
DEFAULT_GATHER_WINDOW_BUDGET = 6


@dataclass
class CaseRecord:
    case_id: str
    run_dir: Path
    top_items: int
    band_slots: int
    observe_band_slots: int
    preband_band_slots: int
    gather_window_budget: int
    actual_observe_enable: Optional[int]
    actual_observe_band_slots: Optional[int]
    actual_preband_band_slots: Optional[int]
    actual_gather_window_budget: Optional[int]
    observe_enable_mismatch: int
    observe_band_slots_mismatch: int
    preband_band_slots_mismatch: int
    gather_window_budget_mismatch: int
    config_drift_any: int
    validation_fail: int
    validation_warn: int
    validation_strict: int
    cycle_cost: float
    memory_requests: float
    issue_deferred: float
    private_issue_avoided: float
    service_elide: float
    frontier_windows: float
    frontier_base_items: float
    frontier_base_consumers: float
    frontier_band_items: float
    frontier_band_consumers: float
    rowdesc_join_live: float
    rowdesc_join_ready: float
    rowdesc_late_join: float
    preband_no_trigger: float
    preband_replay_enqueued: float
    preband_replay_dropped_budget: float
    mfb_gather_owner_lines_useful: float
    mfb_gather_owner_lines_dead: float
    mfb_gather_owner_lines_useful_head2: float
    mfb_gather_owner_lines_useful_tail: float
    mfb_gather_owner_lines_dead_head2: float
    mfb_gather_owner_lines_dead_tail: float
    mfb_gather_resident_hits: float
    mfb_gather_launched_bands_dead: float
    mfb_gather_launched_bands_single_useful: float
    mfb_gather_launched_bands_multi_useful: float
    mfb_gather_launched_bands_head2_useful: float
    mfb_gather_launched_bands_tail_only_useful: float
    mfb_gather_launched_bands_head2_dead: float
    mfb_gather_launched_bands_multi_resident: float
    mfb_gather_launched_bands_resident_hits: float
    mfb_gather_launched_bands_useful: float = 0.0
    mfb_gather_launched_bands_useful_ratio: float = 0.0
    mfb_gather_launched_bands_dead_ratio: float = 0.0
    mfb_gather_launched_bands_head2_useful_ratio: float = 0.0
    mfb_gather_launched_bands_tail_only_useful_ratio: float = 0.0
    mfb_gather_launched_bands_head2_dead_ratio: float = 0.0
    mfb_gather_owner_lines_useful_per_replay: float = 0.0
    mfb_gather_resident_hits_per_replay: float = 0.0
    mfb_gather_owner_lines_useful_head2_share: float = 0.0
    mfb_gather_owner_lines_useful_tail_share: float = 0.0
    mfb_gather_owner_lines_dead_head2_share: float = 0.0
    mfb_gather_owner_lines_dead_tail_share: float = 0.0
    rowdescriptor_service_elide_per_useful_owner_line: float = 0.0
    rowdescriptor_service_elide_per_replay: float = 0.0
    deferred_to_elide_conversion_rate: float = 0.0
    private_to_elide_conversion_rate: float = 0.0
    delta_cycle_vs_baseline: float = 0.0
    frontier_collect_cost: float = 0.0
    frontier_collect_cost_per_item: float = 0.0


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_path(data: Dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except Exception:
        return 0.0


def _to_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(value)
    except Exception:
        return None


def _safe_div(numer: float, denom: float) -> float:
    if denom == 0:
        return 0.0
    return numer / denom


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


def _candidate_run_dir(case_root: Path) -> Optional[Path]:
    latest = case_root / "latest"
    if latest.exists():
        return latest.resolve()
    candidates = [p for p in case_root.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return sorted(candidates)[-1]


def _parse_case_budget(case_id: str) -> Optional[Dict[str, int]]:
    if case_id == BASELINE_CASE_ID:
        return {
            "top": 0,
            "band": 0,
            "observe_band": 0,
            "preband_band": 0,
            "budget": DEFAULT_GATHER_WINDOW_BUDGET,
        }

    match = PHASE_PROBE_CASE_RE.match(case_id)
    if match:
        preband_band = int(match.group("preband"))
        return {
            "top": int(match.group("top")),
            "band": preband_band,
            "observe_band": int(match.group("observe")),
            "preband_band": preband_band,
            "budget": int(match.group("budget")),
        }

    match = LEGACY_CASE_RE.match(case_id)
    if not match:
        return None
    band = int(match.group("band"))
    return {
        "top": int(match.group("top")),
        "band": band,
        "observe_band": band,
        "preband_band": band,
        "budget": DEFAULT_GATHER_WINDOW_BUDGET,
    }


def _collect_case(case_id: str, run_dir: Path, budget: Dict[str, int]) -> CaseRecord:
    summary = _read_json(run_dir / "essential_summary_mesh.json")
    effective_config = {}
    effective_path = run_dir / "effective_config.json"
    if effective_path.exists():
        effective_config = _read_json(effective_path)
    pulse = dict(summary.get("pulse", {}) or {})
    validation = _read_validation_counts(run_dir)
    actual_observe_enable = _to_optional_int(
        _get_path(effective_config, "pulse.metadata_frontier_observe_enable")
    )
    actual_observe_band_slots = _to_optional_int(
        _get_path(effective_config, "pulse.metadata_frontier_band_slots")
    )
    actual_preband_band_slots = _to_optional_int(
        _get_path(effective_config, "pulse.mfb_preband_band_slots")
    )
    actual_gather_window_budget = _to_optional_int(
        _get_path(effective_config, "pulse.mfb_gather_window_budget")
    )
    uses_frontier_case = case_id != BASELINE_CASE_ID
    observe_enable_expected = 1 if uses_frontier_case else 0
    observe_enable_mismatch = int(actual_observe_enable != observe_enable_expected)
    observe_band_slots_mismatch = int(
        uses_frontier_case and actual_observe_band_slots != budget["observe_band"]
    )
    preband_band_slots_mismatch = int(
        uses_frontier_case and actual_preband_band_slots != budget["preband_band"]
    )
    gather_window_budget_mismatch = int(
        uses_frontier_case and actual_gather_window_budget != budget["budget"]
    )
    config_drift_any = int(
        any(
            (
                observe_enable_mismatch,
                observe_band_slots_mismatch,
                preband_band_slots_mismatch,
                gather_window_budget_mismatch,
            )
        )
    )
    return CaseRecord(
        case_id=case_id,
        run_dir=run_dir,
        top_items=budget["top"],
        band_slots=budget["band"],
        observe_band_slots=budget["observe_band"],
        preband_band_slots=budget["preband_band"],
        gather_window_budget=budget["budget"],
        actual_observe_enable=actual_observe_enable,
        actual_observe_band_slots=actual_observe_band_slots,
        actual_preband_band_slots=actual_preband_band_slots,
        actual_gather_window_budget=actual_gather_window_budget,
        observe_enable_mismatch=observe_enable_mismatch,
        observe_band_slots_mismatch=observe_band_slots_mismatch,
        preband_band_slots_mismatch=preband_band_slots_mismatch,
        gather_window_budget_mismatch=gather_window_budget_mismatch,
        config_drift_any=config_drift_any,
        validation_fail=validation["fail"],
        validation_warn=validation["warn"],
        validation_strict=validation["strict"],
        cycle_cost=_to_float(_get_path(summary, "gas.cycle_cost")),
        memory_requests=_to_float(_get_path(summary, "memory.memory_requests")),
        issue_deferred=_to_float(pulse.get("pulse_pod_rowdescriptor_owner_first_issue_deferred_total")),
        private_issue_avoided=_to_float(
            pulse.get("pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total")
        ),
        service_elide=_to_float(pulse.get("pulse_pod_rowdescriptor_owner_first_service_elide_total")),
        frontier_windows=_to_float(pulse.get("pulse_metadata_frontier_windows_total")),
        frontier_base_items=_to_float(pulse.get("pulse_metadata_frontier_base_items_exported_total")),
        frontier_base_consumers=_to_float(
            pulse.get("pulse_metadata_frontier_base_consumer_count_sum_total")
        ),
        frontier_band_items=_to_float(pulse.get("pulse_metadata_frontier_band_items_exported_total")),
        frontier_band_consumers=_to_float(
            pulse.get("pulse_metadata_frontier_band_consumer_count_sum_total")
        ),
        rowdesc_join_live=_to_float(
            pulse.get("pulse_rowdescriptor_owner_first_service_elide_join_live_total")
        ),
        rowdesc_join_ready=_to_float(
            pulse.get("pulse_rowdescriptor_owner_first_service_elide_join_ready_total")
        ),
        rowdesc_late_join=_to_float(
            pulse.get("pulse_rowdescriptor_owner_first_service_elide_late_join_total")
        ),
        preband_no_trigger=_to_float(
            pulse.get("pulse_mfb_gather_preband_register_no_trigger_total")
        ),
        preband_replay_enqueued=_to_float(
            pulse.get("pulse_mfb_gather_preband_replay_enqueued_total")
        ),
        preband_replay_dropped_budget=_to_float(
            pulse.get("pulse_mfb_gather_preband_replay_dropped_budget_total")
        ),
        mfb_gather_owner_lines_useful=_to_float(
            pulse.get("pulse_mfb_gather_owner_lines_useful_total")
        ),
        mfb_gather_owner_lines_dead=_to_float(
            pulse.get("pulse_mfb_gather_owner_lines_dead_total")
        ),
        mfb_gather_owner_lines_useful_head2=_to_float(
            pulse.get("pulse_mfb_gather_owner_lines_useful_head2_total")
        ),
        mfb_gather_owner_lines_useful_tail=_to_float(
            pulse.get("pulse_mfb_gather_owner_lines_useful_tail_total")
        ),
        mfb_gather_owner_lines_dead_head2=_to_float(
            pulse.get("pulse_mfb_gather_owner_lines_dead_head2_total")
        ),
        mfb_gather_owner_lines_dead_tail=_to_float(
            pulse.get("pulse_mfb_gather_owner_lines_dead_tail_total")
        ),
        mfb_gather_resident_hits=_to_float(
            pulse.get("pulse_mfb_gather_resident_hits_total")
        ),
        mfb_gather_launched_bands_dead=_to_float(
            pulse.get("pulse_mfb_gather_launched_bands_dead_total")
        ),
        mfb_gather_launched_bands_single_useful=_to_float(
            pulse.get("pulse_mfb_gather_launched_bands_single_useful_total")
        ),
        mfb_gather_launched_bands_multi_useful=_to_float(
            pulse.get("pulse_mfb_gather_launched_bands_multi_useful_total")
        ),
        mfb_gather_launched_bands_head2_useful=_to_float(
            pulse.get("pulse_mfb_gather_launched_bands_head2_useful_total")
        ),
        mfb_gather_launched_bands_tail_only_useful=_to_float(
            pulse.get("pulse_mfb_gather_launched_bands_tail_only_useful_total")
        ),
        mfb_gather_launched_bands_head2_dead=_to_float(
            pulse.get("pulse_mfb_gather_launched_bands_head2_dead_total")
        ),
        mfb_gather_launched_bands_multi_resident=_to_float(
            pulse.get("pulse_mfb_gather_launched_bands_multi_resident_total")
        ),
        mfb_gather_launched_bands_resident_hits=_to_float(
            pulse.get("pulse_mfb_gather_launched_bands_resident_hits_total")
        ),
    )


def _discover_cases(runs_root: Path) -> List[CaseRecord]:
    records: List[CaseRecord] = []
    for case_root in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        case_id = case_root.name
        budget = _parse_case_budget(case_id)
        if budget is None:
            continue
        run_dir = _candidate_run_dir(case_root)
        if run_dir is None:
            continue
        summary_file = run_dir / "essential_summary_mesh.json"
        if not summary_file.exists():
            continue
        records.append(_collect_case(case_id, run_dir, budget=budget))
    return records


def _enrich_derived(records: Iterable[CaseRecord], baseline_cycle: float) -> None:
    for item in records:
        if item.issue_deferred > 0:
            item.deferred_to_elide_conversion_rate = item.service_elide / item.issue_deferred
        if item.private_issue_avoided > 0:
            item.private_to_elide_conversion_rate = item.service_elide / item.private_issue_avoided
        item.delta_cycle_vs_baseline = item.cycle_cost - baseline_cycle
        total_consumers = item.frontier_base_consumers + item.frontier_band_consumers
        total_items = item.frontier_base_items + item.frontier_band_items
        if total_consumers > 0:
            item.frontier_collect_cost = item.delta_cycle_vs_baseline / total_consumers
        if total_items > 0:
            item.frontier_collect_cost_per_item = item.delta_cycle_vs_baseline / total_items
        item.mfb_gather_launched_bands_useful = (
            item.mfb_gather_launched_bands_single_useful +
            item.mfb_gather_launched_bands_multi_useful
        )
        item.mfb_gather_launched_bands_useful_ratio = _safe_div(
            item.mfb_gather_launched_bands_useful,
            item.preband_replay_enqueued,
        )
        item.mfb_gather_launched_bands_dead_ratio = _safe_div(
            item.mfb_gather_launched_bands_dead,
            item.preband_replay_enqueued,
        )
        item.mfb_gather_launched_bands_head2_useful_ratio = _safe_div(
            item.mfb_gather_launched_bands_head2_useful,
            item.preband_replay_enqueued,
        )
        item.mfb_gather_launched_bands_tail_only_useful_ratio = _safe_div(
            item.mfb_gather_launched_bands_tail_only_useful,
            item.preband_replay_enqueued,
        )
        item.mfb_gather_launched_bands_head2_dead_ratio = _safe_div(
            item.mfb_gather_launched_bands_head2_dead,
            item.preband_replay_enqueued,
        )
        item.mfb_gather_owner_lines_useful_per_replay = _safe_div(
            item.mfb_gather_owner_lines_useful,
            item.preband_replay_enqueued,
        )
        item.mfb_gather_resident_hits_per_replay = _safe_div(
            item.mfb_gather_resident_hits,
            item.preband_replay_enqueued,
        )
        item.mfb_gather_owner_lines_useful_head2_share = _safe_div(
            item.mfb_gather_owner_lines_useful_head2,
            item.mfb_gather_owner_lines_useful,
        )
        item.mfb_gather_owner_lines_useful_tail_share = _safe_div(
            item.mfb_gather_owner_lines_useful_tail,
            item.mfb_gather_owner_lines_useful,
        )
        item.mfb_gather_owner_lines_dead_head2_share = _safe_div(
            item.mfb_gather_owner_lines_dead_head2,
            item.mfb_gather_owner_lines_dead,
        )
        item.mfb_gather_owner_lines_dead_tail_share = _safe_div(
            item.mfb_gather_owner_lines_dead_tail,
            item.mfb_gather_owner_lines_dead,
        )
        item.rowdescriptor_service_elide_per_useful_owner_line = _safe_div(
            item.service_elide,
            item.mfb_gather_owner_lines_useful,
        )
        item.rowdescriptor_service_elide_per_replay = _safe_div(
            item.service_elide,
            item.preband_replay_enqueued,
        )


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.9f}".rstrip("0").rstrip(".")
    return str(value)


def _sort_key(item: CaseRecord) -> Any:
    if item.case_id == BASELINE_CASE_ID:
        return (-1, -1, item.case_id)
    return (
        item.top_items,
        item.observe_band_slots,
        item.preband_band_slots,
        item.gather_window_budget,
        item.case_id,
    )


def _write_tsv(path: Path, records: List[CaseRecord], baseline_cycle: float) -> None:
    header = [
        "case_id",
        "top_items",
        "band_slots",
        "observe_band_slots",
        "preband_band_slots",
        "gather_window_budget",
        "actual_observe_enable",
        "actual_observe_band_slots",
        "actual_preband_band_slots",
        "actual_gather_window_budget",
        "observe_enable_mismatch",
        "observe_band_slots_mismatch",
        "preband_band_slots_mismatch",
        "gather_window_budget_mismatch",
        "config_drift_any",
        "validation_fail",
        "validation_warn",
        "validation_strict",
        "cycle_cost",
        "delta_cycle_vs_baseline",
        "memory_requests",
        "issue_deferred",
        "private_issue_avoided",
        "service_elide",
        "owner_deferred_to_elide_conversion_rate",
        "owner_private_to_elide_conversion_rate",
        "frontier_windows",
        "frontier_base_items",
        "frontier_base_consumers",
        "frontier_band_items",
        "frontier_band_consumers",
        "rowdesc_join_live",
        "rowdesc_join_ready",
        "rowdesc_late_join",
        "preband_no_trigger",
        "preband_replay_enqueued",
        "preband_replay_dropped_budget",
        "mfb_gather_owner_lines_useful",
        "mfb_gather_owner_lines_dead",
        "mfb_gather_owner_lines_useful_head2",
        "mfb_gather_owner_lines_useful_tail",
        "mfb_gather_owner_lines_dead_head2",
        "mfb_gather_owner_lines_dead_tail",
        "mfb_gather_resident_hits",
        "mfb_gather_launched_bands_dead",
        "mfb_gather_launched_bands_single_useful",
        "mfb_gather_launched_bands_multi_useful",
        "mfb_gather_launched_bands_head2_useful",
        "mfb_gather_launched_bands_tail_only_useful",
        "mfb_gather_launched_bands_head2_dead",
        "mfb_gather_launched_bands_multi_resident",
        "mfb_gather_launched_bands_resident_hits",
        "mfb_gather_launched_bands_useful",
        "mfb_gather_launched_bands_useful_ratio",
        "mfb_gather_launched_bands_dead_ratio",
        "mfb_gather_launched_bands_head2_useful_ratio",
        "mfb_gather_launched_bands_tail_only_useful_ratio",
        "mfb_gather_launched_bands_head2_dead_ratio",
        "mfb_gather_owner_lines_useful_per_replay",
        "mfb_gather_resident_hits_per_replay",
        "mfb_gather_owner_lines_useful_head2_share",
        "mfb_gather_owner_lines_useful_tail_share",
        "mfb_gather_owner_lines_dead_head2_share",
        "mfb_gather_owner_lines_dead_tail_share",
        "rowdescriptor_service_elide_per_useful_owner_line",
        "rowdescriptor_service_elide_per_replay",
        "frontier_collect_cost",
        "frontier_collect_cost_per_item",
        "run_dir",
    ]
    lines = [
        "# experiment_id\t2026-03-27_pulse_owner_first_frontier_combo_ab_v1",
        "# profile\tmetadata_frontier_budget_grid",
        f"# baseline_cycle_cost\t{_fmt(baseline_cycle)}",
        "\t".join(header),
    ]
    for item in sorted(records, key=_sort_key):
        row = [
            item.case_id,
            item.top_items,
            item.band_slots,
            item.observe_band_slots,
            item.preband_band_slots,
            item.gather_window_budget,
            item.actual_observe_enable,
            item.actual_observe_band_slots,
            item.actual_preband_band_slots,
            item.actual_gather_window_budget,
            item.observe_enable_mismatch,
            item.observe_band_slots_mismatch,
            item.preband_band_slots_mismatch,
            item.gather_window_budget_mismatch,
            item.config_drift_any,
            item.validation_fail,
            item.validation_warn,
            item.validation_strict,
            item.cycle_cost,
            item.delta_cycle_vs_baseline,
            item.memory_requests,
            item.issue_deferred,
            item.private_issue_avoided,
            item.service_elide,
            item.deferred_to_elide_conversion_rate,
            item.private_to_elide_conversion_rate,
            item.frontier_windows,
            item.frontier_base_items,
            item.frontier_base_consumers,
            item.frontier_band_items,
            item.frontier_band_consumers,
            item.rowdesc_join_live,
            item.rowdesc_join_ready,
            item.rowdesc_late_join,
            item.preband_no_trigger,
            item.preband_replay_enqueued,
            item.preband_replay_dropped_budget,
            item.mfb_gather_owner_lines_useful,
            item.mfb_gather_owner_lines_dead,
            item.mfb_gather_owner_lines_useful_head2,
            item.mfb_gather_owner_lines_useful_tail,
            item.mfb_gather_owner_lines_dead_head2,
            item.mfb_gather_owner_lines_dead_tail,
            item.mfb_gather_resident_hits,
            item.mfb_gather_launched_bands_dead,
            item.mfb_gather_launched_bands_single_useful,
            item.mfb_gather_launched_bands_multi_useful,
            item.mfb_gather_launched_bands_head2_useful,
            item.mfb_gather_launched_bands_tail_only_useful,
            item.mfb_gather_launched_bands_head2_dead,
            item.mfb_gather_launched_bands_multi_resident,
            item.mfb_gather_launched_bands_resident_hits,
            item.mfb_gather_launched_bands_useful,
            item.mfb_gather_launched_bands_useful_ratio,
            item.mfb_gather_launched_bands_dead_ratio,
            item.mfb_gather_launched_bands_head2_useful_ratio,
            item.mfb_gather_launched_bands_tail_only_useful_ratio,
            item.mfb_gather_launched_bands_head2_dead_ratio,
            item.mfb_gather_owner_lines_useful_per_replay,
            item.mfb_gather_resident_hits_per_replay,
            item.mfb_gather_owner_lines_useful_head2_share,
            item.mfb_gather_owner_lines_useful_tail_share,
            item.mfb_gather_owner_lines_dead_head2_share,
            item.mfb_gather_owner_lines_dead_tail_share,
            item.rowdescriptor_service_elide_per_useful_owner_line,
            item.rowdescriptor_service_elide_per_replay,
            item.frontier_collect_cost,
            item.frontier_collect_cost_per_item,
            str(item.run_dir),
        ]
        lines.append("\t".join(_fmt(v) for v in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--runs-root",
        default=str(Path(__file__).resolve().with_name("runs")),
        help="root directory containing per-case run folders",
    )
    ap.add_argument(
        "--out",
        default=str(Path(__file__).resolve().with_name("snapshot") / "grid_summary.tsv"),
        help="output tsv path",
    )
    args = ap.parse_args()

    runs_root = Path(args.runs_root).resolve()
    records = _discover_cases(runs_root)
    baseline = next((item for item in records if item.case_id == BASELINE_CASE_ID), None)
    if baseline is None:
        raise SystemExit(f"baseline case missing under runs root: {runs_root}")
    _enrich_derived(records, baseline_cycle=baseline.cycle_cost)
    out_path = Path(args.out).resolve()
    _write_tsv(out_path, records, baseline_cycle=baseline.cycle_cost)
    print(f"[grid-snapshot] wrote {out_path}")
    print(f"[grid-snapshot] cases={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
