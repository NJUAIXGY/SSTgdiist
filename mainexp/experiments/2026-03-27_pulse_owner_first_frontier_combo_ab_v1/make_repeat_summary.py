#!/usr/bin/env python3
"""Summarize repeated runs for a single metadata-frontier case."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


BASELINE_CASE_ID = "pulse_shared_line_actual_mfb_gather_preband_dedup_off"
DEFAULT_GATHER_WINDOW_BUDGET = 6
VALIDATION_RE = re.compile(r"fail=(\d+)\s+warn=(\d+)(?:\s+strict=(\d+))?")
ELAPSED_RE = re.compile(r"Elapsed \(wall clock\) time .*: ([0-9:]+\.[0-9]+|[0-9:]+)")
EXIT_RE = re.compile(r"Exit status: (\d+)")
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


@dataclass
class RunRecord:
    run_name: str
    run_dir: Path
    cycle_cost: float
    delta_cycle_vs_baseline: float
    actual_observe_enable: Optional[int]
    actual_observe_band_slots: Optional[int]
    actual_preband_band_slots: Optional[int]
    actual_gather_window_budget: Optional[int]
    observe_enable_mismatch: int
    observe_band_slots_mismatch: int
    preband_band_slots_mismatch: int
    gather_window_budget_mismatch: int
    config_drift_any: int
    issue_deferred: float
    private_issue_avoided: float
    service_elide: float
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
    mfb_gather_launched_bands_useful: float
    mfb_gather_launched_bands_useful_ratio: float
    mfb_gather_launched_bands_dead_ratio: float
    mfb_gather_launched_bands_head2_useful_ratio: float
    mfb_gather_launched_bands_tail_only_useful_ratio: float
    mfb_gather_launched_bands_head2_dead_ratio: float
    mfb_gather_owner_lines_useful_per_replay: float
    mfb_gather_resident_hits_per_replay: float
    mfb_gather_owner_lines_useful_head2_share: float
    mfb_gather_owner_lines_useful_tail_share: float
    mfb_gather_owner_lines_dead_head2_share: float
    mfb_gather_owner_lines_dead_tail_share: float
    rowdescriptor_service_elide_per_useful_owner_line: float
    rowdescriptor_service_elide_per_replay: float
    elapsed_wall: str
    exit_status: int
    validation_fail: int
    validation_warn: int
    validation_strict: int


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


def _parse_case_budget(case_id: str) -> Optional[Dict[str, int]]:
    if case_id == BASELINE_CASE_ID:
        return {
            "observe_enable": 0,
            "observe_band": 0,
            "preband_band": 0,
            "budget": DEFAULT_GATHER_WINDOW_BUDGET,
            "is_frontier_case": 0,
        }

    match = PHASE_PROBE_CASE_RE.match(case_id)
    if match:
        return {
            "observe_enable": 1,
            "observe_band": int(match.group("observe")),
            "preband_band": int(match.group("preband")),
            "budget": int(match.group("budget")),
            "is_frontier_case": 1,
        }

    match = LEGACY_CASE_RE.match(case_id)
    if match:
        band = int(match.group("band"))
        return {
            "observe_enable": 1,
            "observe_band": band,
            "preband_band": band,
            "budget": DEFAULT_GATHER_WINDOW_BUDGET,
            "is_frontier_case": 1,
        }
    return None


def _read_validation(run_dir: Path) -> Dict[str, int]:
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


def _read_time(run_dir: Path) -> Dict[str, Any]:
    elapsed_wall = ""
    exit_status = -1
    time_path = run_dir / "time.txt"
    if not time_path.exists():
        return {"elapsed_wall": elapsed_wall, "exit_status": exit_status}
    text = time_path.read_text(encoding="utf-8", errors="ignore")
    elapsed_match = ELAPSED_RE.search(text)
    exit_match = EXIT_RE.search(text)
    if elapsed_match:
        elapsed_wall = elapsed_match.group(1)
    if exit_match:
        exit_status = int(exit_match.group(1))
    return {"elapsed_wall": elapsed_wall, "exit_status": exit_status}


def _collect_run(run_dir: Path, baseline_cycle: float, expected: Dict[str, int]) -> Optional[RunRecord]:
    summary_file = run_dir / "essential_summary_mesh.json"
    if not summary_file.exists():
        return None
    summary = _read_json(summary_file)
    effective_config = {}
    effective_path = run_dir / "effective_config.json"
    if effective_path.exists():
        effective_config = _read_json(effective_path)
    pulse = dict(summary.get("pulse", {}) or {})
    validation = _read_validation(run_dir)
    timing = _read_time(run_dir)
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
    uses_frontier_case = bool(expected["is_frontier_case"])
    observe_enable_mismatch = int(actual_observe_enable != expected["observe_enable"])
    observe_band_slots_mismatch = int(
        uses_frontier_case and actual_observe_band_slots != expected["observe_band"]
    )
    preband_band_slots_mismatch = int(
        uses_frontier_case and actual_preband_band_slots != expected["preband_band"]
    )
    gather_window_budget_mismatch = int(
        uses_frontier_case and actual_gather_window_budget != expected["budget"]
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
    cycle_cost = _to_float(_get_path(summary, "gas.cycle_cost"))
    issue_deferred = _to_float(pulse.get("pulse_pod_rowdescriptor_owner_first_issue_deferred_total"))
    private_issue_avoided = _to_float(
        pulse.get("pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total")
    )
    service_elide = _to_float(pulse.get("pulse_pod_rowdescriptor_owner_first_service_elide_total"))
    rowdesc_join_live = _to_float(
        pulse.get("pulse_rowdescriptor_owner_first_service_elide_join_live_total")
    )
    rowdesc_join_ready = _to_float(
        pulse.get("pulse_rowdescriptor_owner_first_service_elide_join_ready_total")
    )
    rowdesc_late_join = _to_float(
        pulse.get("pulse_rowdescriptor_owner_first_service_elide_late_join_total")
    )
    preband_no_trigger = _to_float(
        pulse.get("pulse_mfb_gather_preband_register_no_trigger_total")
    )
    preband_replay_enqueued = _to_float(
        pulse.get("pulse_mfb_gather_preband_replay_enqueued_total")
    )
    preband_replay_dropped_budget = _to_float(
        pulse.get("pulse_mfb_gather_preband_replay_dropped_budget_total")
    )
    mfb_gather_owner_lines_useful = _to_float(
        pulse.get("pulse_mfb_gather_owner_lines_useful_total")
    )
    mfb_gather_owner_lines_dead = _to_float(
        pulse.get("pulse_mfb_gather_owner_lines_dead_total")
    )
    mfb_gather_owner_lines_useful_head2 = _to_float(
        pulse.get("pulse_mfb_gather_owner_lines_useful_head2_total")
    )
    mfb_gather_owner_lines_useful_tail = _to_float(
        pulse.get("pulse_mfb_gather_owner_lines_useful_tail_total")
    )
    mfb_gather_owner_lines_dead_head2 = _to_float(
        pulse.get("pulse_mfb_gather_owner_lines_dead_head2_total")
    )
    mfb_gather_owner_lines_dead_tail = _to_float(
        pulse.get("pulse_mfb_gather_owner_lines_dead_tail_total")
    )
    mfb_gather_resident_hits = _to_float(
        pulse.get("pulse_mfb_gather_resident_hits_total")
    )
    mfb_gather_launched_bands_dead = _to_float(
        pulse.get("pulse_mfb_gather_launched_bands_dead_total")
    )
    mfb_gather_launched_bands_single_useful = _to_float(
        pulse.get("pulse_mfb_gather_launched_bands_single_useful_total")
    )
    mfb_gather_launched_bands_multi_useful = _to_float(
        pulse.get("pulse_mfb_gather_launched_bands_multi_useful_total")
    )
    mfb_gather_launched_bands_head2_useful = _to_float(
        pulse.get("pulse_mfb_gather_launched_bands_head2_useful_total")
    )
    mfb_gather_launched_bands_tail_only_useful = _to_float(
        pulse.get("pulse_mfb_gather_launched_bands_tail_only_useful_total")
    )
    mfb_gather_launched_bands_head2_dead = _to_float(
        pulse.get("pulse_mfb_gather_launched_bands_head2_dead_total")
    )
    mfb_gather_launched_bands_multi_resident = _to_float(
        pulse.get("pulse_mfb_gather_launched_bands_multi_resident_total")
    )
    mfb_gather_launched_bands_resident_hits = _to_float(
        pulse.get("pulse_mfb_gather_launched_bands_resident_hits_total")
    )
    mfb_gather_launched_bands_useful = (
        mfb_gather_launched_bands_single_useful +
        mfb_gather_launched_bands_multi_useful
    )
    return RunRecord(
        run_name=run_dir.name,
        run_dir=run_dir,
        cycle_cost=cycle_cost,
        delta_cycle_vs_baseline=cycle_cost - baseline_cycle,
        actual_observe_enable=actual_observe_enable,
        actual_observe_band_slots=actual_observe_band_slots,
        actual_preband_band_slots=actual_preband_band_slots,
        actual_gather_window_budget=actual_gather_window_budget,
        observe_enable_mismatch=observe_enable_mismatch,
        observe_band_slots_mismatch=observe_band_slots_mismatch,
        preband_band_slots_mismatch=preband_band_slots_mismatch,
        gather_window_budget_mismatch=gather_window_budget_mismatch,
        config_drift_any=config_drift_any,
        issue_deferred=issue_deferred,
        private_issue_avoided=private_issue_avoided,
        service_elide=service_elide,
        rowdesc_join_live=rowdesc_join_live,
        rowdesc_join_ready=rowdesc_join_ready,
        rowdesc_late_join=rowdesc_late_join,
        preband_no_trigger=preband_no_trigger,
        preband_replay_enqueued=preband_replay_enqueued,
        preband_replay_dropped_budget=preband_replay_dropped_budget,
        mfb_gather_owner_lines_useful=mfb_gather_owner_lines_useful,
        mfb_gather_owner_lines_dead=mfb_gather_owner_lines_dead,
        mfb_gather_owner_lines_useful_head2=mfb_gather_owner_lines_useful_head2,
        mfb_gather_owner_lines_useful_tail=mfb_gather_owner_lines_useful_tail,
        mfb_gather_owner_lines_dead_head2=mfb_gather_owner_lines_dead_head2,
        mfb_gather_owner_lines_dead_tail=mfb_gather_owner_lines_dead_tail,
        mfb_gather_resident_hits=mfb_gather_resident_hits,
        mfb_gather_launched_bands_dead=mfb_gather_launched_bands_dead,
        mfb_gather_launched_bands_single_useful=mfb_gather_launched_bands_single_useful,
        mfb_gather_launched_bands_multi_useful=mfb_gather_launched_bands_multi_useful,
        mfb_gather_launched_bands_head2_useful=mfb_gather_launched_bands_head2_useful,
        mfb_gather_launched_bands_tail_only_useful=mfb_gather_launched_bands_tail_only_useful,
        mfb_gather_launched_bands_head2_dead=mfb_gather_launched_bands_head2_dead,
        mfb_gather_launched_bands_multi_resident=mfb_gather_launched_bands_multi_resident,
        mfb_gather_launched_bands_resident_hits=mfb_gather_launched_bands_resident_hits,
        mfb_gather_launched_bands_useful=mfb_gather_launched_bands_useful,
        mfb_gather_launched_bands_useful_ratio=_safe_div(
            mfb_gather_launched_bands_useful,
            preband_replay_enqueued,
        ),
        mfb_gather_launched_bands_dead_ratio=_safe_div(
            mfb_gather_launched_bands_dead,
            preband_replay_enqueued,
        ),
        mfb_gather_launched_bands_head2_useful_ratio=_safe_div(
            mfb_gather_launched_bands_head2_useful,
            preband_replay_enqueued,
        ),
        mfb_gather_launched_bands_tail_only_useful_ratio=_safe_div(
            mfb_gather_launched_bands_tail_only_useful,
            preband_replay_enqueued,
        ),
        mfb_gather_launched_bands_head2_dead_ratio=_safe_div(
            mfb_gather_launched_bands_head2_dead,
            preband_replay_enqueued,
        ),
        mfb_gather_owner_lines_useful_per_replay=_safe_div(
            mfb_gather_owner_lines_useful,
            preband_replay_enqueued,
        ),
        mfb_gather_resident_hits_per_replay=_safe_div(
            mfb_gather_resident_hits,
            preband_replay_enqueued,
        ),
        mfb_gather_owner_lines_useful_head2_share=_safe_div(
            mfb_gather_owner_lines_useful_head2,
            mfb_gather_owner_lines_useful,
        ),
        mfb_gather_owner_lines_useful_tail_share=_safe_div(
            mfb_gather_owner_lines_useful_tail,
            mfb_gather_owner_lines_useful,
        ),
        mfb_gather_owner_lines_dead_head2_share=_safe_div(
            mfb_gather_owner_lines_dead_head2,
            mfb_gather_owner_lines_dead,
        ),
        mfb_gather_owner_lines_dead_tail_share=_safe_div(
            mfb_gather_owner_lines_dead_tail,
            mfb_gather_owner_lines_dead,
        ),
        rowdescriptor_service_elide_per_useful_owner_line=_safe_div(
            service_elide,
            mfb_gather_owner_lines_useful,
        ),
        rowdescriptor_service_elide_per_replay=_safe_div(
            service_elide,
            preband_replay_enqueued,
        ),
        elapsed_wall=str(timing["elapsed_wall"]),
        exit_status=int(timing["exit_status"]),
        validation_fail=validation["fail"],
        validation_warn=validation["warn"],
        validation_strict=validation["strict"],
    )


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.9f}".rstrip("0").rstrip(".")
    return str(value)


def _summary_stat(values: List[float], fn, default: float = 0.0) -> float:
    if not values:
        return default
    return float(fn(values))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--runs-root",
        default=str(Path(__file__).resolve().with_name("runs")),
        help="root directory containing per-case run folders",
    )
    ap.add_argument("--case-id", required=True, help="case id to summarize")
    ap.add_argument(
        "--baseline-case-id",
        default=BASELINE_CASE_ID,
        help="baseline case id used for delta_cycle",
    )
    ap.add_argument(
        "--out",
        default=str(Path(__file__).resolve().with_name("snapshot") / "repeat_summary.tsv"),
        help="output tsv path",
    )
    args = ap.parse_args()

    runs_root = Path(args.runs_root).resolve()
    baseline_root = runs_root / args.baseline_case_id
    baseline_dirs = sorted(p for p in baseline_root.iterdir() if p.is_dir())
    if not baseline_dirs:
        raise SystemExit(f"baseline runs missing: {baseline_root}")
    baseline_summary = _read_json(baseline_dirs[-1] / "essential_summary_mesh.json")
    baseline_cycle = _to_float(_get_path(baseline_summary, "gas.cycle_cost"))

    case_root = runs_root / args.case_id
    if not case_root.exists():
        raise SystemExit(f"case root missing: {case_root}")
    expected = _parse_case_budget(args.case_id)
    if expected is None:
        raise SystemExit(f"unsupported case id format: {args.case_id}")
    run_dirs = sorted(
        p for p in case_root.iterdir() if p.is_dir() and p.name != "latest"
    )
    records = []
    for run_dir in run_dirs:
        record = _collect_run(run_dir, baseline_cycle=baseline_cycle, expected=expected)
        if record is not None:
            records.append(record)
    if not records:
        raise SystemExit(f"no completed runs found for case: {args.case_id}")

    delta_values = [item.delta_cycle_vs_baseline for item in records]
    cycle_values = [item.cycle_cost for item in records]
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "run_name",
        "cycle_cost",
        "delta_cycle_vs_baseline",
        "actual_observe_enable",
        "actual_observe_band_slots",
        "actual_preband_band_slots",
        "actual_gather_window_budget",
        "observe_enable_mismatch",
        "observe_band_slots_mismatch",
        "preband_band_slots_mismatch",
        "gather_window_budget_mismatch",
        "config_drift_any",
        "issue_deferred",
        "private_issue_avoided",
        "service_elide",
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
        "elapsed_wall",
        "exit_status",
        "validation_fail",
        "validation_warn",
        "validation_strict",
        "run_dir",
    ]
    lines = [
        f"# case_id\t{args.case_id}",
        f"# baseline_case_id\t{args.baseline_case_id}",
        f"# baseline_cycle_cost\t{_fmt(baseline_cycle)}",
        f"# repeat_count\t{len(records)}",
        f"# cycle_cost_mean\t{_fmt(_summary_stat(cycle_values, statistics.mean))}",
        f"# cycle_cost_min\t{_fmt(_summary_stat(cycle_values, min))}",
        f"# cycle_cost_max\t{_fmt(_summary_stat(cycle_values, max))}",
        f"# delta_cycle_mean\t{_fmt(_summary_stat(delta_values, statistics.mean))}",
        f"# delta_cycle_min\t{_fmt(_summary_stat(delta_values, min))}",
        f"# delta_cycle_max\t{_fmt(_summary_stat(delta_values, max))}",
        f"# delta_cycle_pstdev\t{_fmt(_summary_stat(delta_values, statistics.pstdev))}",
        "\t".join(header),
    ]
    for item in records:
        row = [
            item.run_name,
            item.cycle_cost,
            item.delta_cycle_vs_baseline,
            item.actual_observe_enable,
            item.actual_observe_band_slots,
            item.actual_preband_band_slots,
            item.actual_gather_window_budget,
            item.observe_enable_mismatch,
            item.observe_band_slots_mismatch,
            item.preband_band_slots_mismatch,
            item.gather_window_budget_mismatch,
            item.config_drift_any,
            item.issue_deferred,
            item.private_issue_avoided,
            item.service_elide,
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
            item.elapsed_wall,
            item.exit_status,
            item.validation_fail,
            item.validation_warn,
            item.validation_strict,
            str(item.run_dir),
        ]
        lines.append("\t".join(_fmt(v) for v in row))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[repeat-summary] wrote {out_path}")
    print(f"[repeat-summary] runs={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
