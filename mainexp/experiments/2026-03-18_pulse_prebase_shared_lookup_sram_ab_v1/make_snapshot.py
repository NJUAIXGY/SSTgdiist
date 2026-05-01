#!/usr/bin/env python3
"""Build a minimal compare.tsv snapshot for the PULSE pre-base shared-lookup SRAM-on A/B run."""

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
    "memhierarchy.memctrl.req_total",
    "sram.weight_idx.lookup_total",
    "sram.weight_idx.predicted_extra_cycles_total",
    "sram.weight.bank_conflict_ticks_total",
)

PULSE_METRICS: Tuple[str, ...] = (
    "pulse_prebase_lookup_owner_fill_total",
    "pulse_prebase_lookup_shared_hits_total",
    "pulse_prebase_lookup_entries_peak",
    "pulse_prebase_lookup_hit_ratio",
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
    candidate_label: str,
    baseline_metrics: Dict[str, Any],
    candidate_metrics: Dict[str, Any],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# experiment_id\t{experiment_id}",
        f"# baseline_case\t{baseline_label}",
        "# profile\tpulse_prebase_shared_lookup_sram_ab_v1",
        f"metric\tbaseline\t{candidate_label}\tdelta",
    ]
    ordered_metrics = MAINLINE_METRICS + PULSE_METRICS
    for metric in ordered_metrics:
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
