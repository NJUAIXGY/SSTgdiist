#!/usr/bin/env python3
"""
memop snapshot tool

Goal:
- Take a small, reproducible snapshot of comparison runs under memop/experiments/<exp>/.
- Copy only the load-bearing artifacts from each SST run_dir:
  - essential_summary_mesh.json
  - effective_config.json
  - meta.json
- Generate a lightweight compare.tsv for paper tables / quick diffs.

Input:
- An experiment directory containing cases.json:
  {
    "schema_version": 1,
    "experiment_id": "...",
    "baseline_case": "off",
    "cases": [
      {"id": "off", "label": "...", "run_dir": "/abs/path/to/run"},
      {"id": "on",  "label": "...", "run_dir": "/abs/path/to/run"}
    ]
  }
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


LOAD_BEARING_FILES = ("essential_summary_mesh.json", "effective_config.json", "meta.json")

MAINLINE_METRIC_KEYS = (
    "sim_time_actual_ns",
    "memory_requests",
    "memory_bytes",
    "memctrl_bytes_est_total",
    "memctrl_req_total",
    "gas_payload_bytes_total",
    "gas_unique_bytes_total",
    "gas_overfetch_bytes_total",
    "gas_frontend_staged_reads_total",
    "gas_frontend_staged_line_touches_total",
    "gas_frontend_granules_built_total",
    "gas_frontend_line_touch_reuse_ratio",
    "gas_frontend_staged_reads_per_unique_line_avg",
    "gas_payload_bytes_per_memctrl_req_avg",
    "gas_memctrl_payload_utilization",
    "gas_memctrl_traffic_amplification",
    "gas_apply_ns_avg",
    "gas_apply_exec_ns_avg",
    "gas_apply_to_scatter_gap_ns_avg",
    "gas_retire_global_hol_cycles_total",
    "gas_retire_ready_but_blocked_edges_total",
    "gas_retire_ready_blocked_edges_per_hol_cycle_avg",
    "pipeline_rx_packets_to_staged_reads_ratio",
    "pipeline_staged_reads_to_granules_ratio",
    "pipeline_granules_to_memctrl_req_ratio",
    "pipeline_payload_bytes_per_rx_packet_avg",
    "pipeline_retire_drag_ratio",
    "imbalance_pe_total_ns_max_over_avg",
    "imbalance_pe_apply_exec_ns_max_over_avg",
    "imbalance_pe_apply_to_scatter_gap_ns_max_over_avg",
    "imbalance_steps_done_range",
)


def _read_json(p: Path) -> Dict[str, Any]:
    with p.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"expected json object at {p}")
    return obj


def _get_path(d: Dict[str, Any], path: str) -> Optional[Any]:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _as_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x))
    except Exception:
        return None


def _fmt(x: Optional[float]) -> str:
    if x is None:
        return "NA"
    # Keep stable, compact formatting for TSV.
    if abs(x) >= 1000 and float(int(x)) == float(x):
        return str(int(x))
    if abs(x) >= 1000:
        return f"{x:.3f}"
    return f"{x:.6g}"


@dataclass(frozen=True)
class Case:
    case_id: str
    label: str
    run_dir: Path


def _load_cases(exp_dir: Path) -> Tuple[str, str, List[Case]]:
    cfg_path = exp_dir / "cases.json"
    cfg = _read_json(cfg_path)
    schema = int(cfg.get("schema_version", 0) or 0)
    if schema != 1:
        raise ValueError(f"unsupported cases.json schema_version={schema} in {cfg_path}")
    exp_id = str(cfg.get("experiment_id", exp_dir.name)).strip()
    baseline = str(cfg.get("baseline_case", "")).strip()
    if not baseline:
        raise ValueError(f"missing baseline_case in {cfg_path}")
    raw_cases = cfg.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError(f"missing/invalid cases[] in {cfg_path}")
    out: List[Case] = []
    for it in raw_cases:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("id", "")).strip()
        if not cid:
            raise ValueError(f"case missing id in {cfg_path}: {it!r}")
        label = str(it.get("label", cid)).strip()
        run_dir = str(it.get("run_dir", "")).strip()
        if not run_dir:
            raise ValueError(f"case {cid} missing run_dir in {cfg_path}")
        out.append(Case(case_id=cid, label=label, run_dir=Path(run_dir)))
    ids = {c.case_id for c in out}
    if baseline not in ids:
        raise ValueError(f"baseline_case={baseline!r} not found in cases ids={sorted(ids)}")
    return exp_id, baseline, out


def _safe_case_dirname(s: str) -> str:
    # Keep filenames stable and portable.
    ok = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_", "."):
            ok.append(ch)
        else:
            ok.append("_")
    out = "".join(ok).strip("._")
    return out or "case"


def _snapshot_case(exp_dir: Path, case: Case) -> Path:
    if not case.run_dir.is_dir():
        raise FileNotFoundError(f"run_dir not found: {case.run_dir}")
    dst = exp_dir / "snapshot" / "cases" / _safe_case_dirname(case.case_id)
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "run_dir.txt").write_text(str(case.run_dir) + "\n", encoding="utf-8")
    for name in LOAD_BEARING_FILES:
        src = case.run_dir / name
        if not src.is_file():
            raise FileNotFoundError(f"missing {name} under run_dir: {src}")
        shutil.copy2(src, dst / name)
    return dst


def _extract_metrics(summary: Dict[str, Any], profile: str) -> Dict[str, Optional[float]]:
    # Keep this list small and stable (paper table friendly).
    all_metrics = {
        "sim_time_actual_ns": _as_float(_get_path(summary, "model.sim_time_actual_ns")),
        "memory_requests": _as_float(_get_path(summary, "memory.memory_requests")),
        "memory_bytes": _as_float(_get_path(summary, "memory.memory_bytes")),
        "memctrl_bytes_est_total": _as_float(_get_path(summary, "memhierarchy.memctrl.bytes_est_total")),
        "memctrl_req_total": _as_float(_get_path(summary, "memhierarchy.memctrl.req_total")),
        "gas_payload_bytes_total": _as_float(_get_path(summary, "gas.payload_bytes_total")),
        "gas_unique_bytes_total": _as_float(_get_path(summary, "gas.unique_bytes_total")),
        "gas_overfetch_bytes_total": _as_float(_get_path(summary, "gas.overfetch_bytes_total")),
        "gas_overfetch_bytes_stat_total": _as_float(_get_path(summary, "gas.overfetch_bytes_stat_total")),
        "gas_frontend_staged_reads_total": _as_float(_get_path(summary, "gas.frontend_staged_reads_total")),
        "gas_frontend_staged_line_touches_total": _as_float(_get_path(summary, "gas.frontend_staged_line_touches_total")),
        "gas_frontend_granules_built_total": _as_float(_get_path(summary, "gas.frontend_granules_built_total")),
        "gas_frontend_line_touch_reuse_total": _as_float(_get_path(summary, "gas.frontend_line_touch_reuse_total")),
        "gas_frontend_line_touch_reuse_ratio": _as_float(_get_path(summary, "gas.frontend_line_touch_reuse_ratio")),
        "gas_frontend_staged_reads_per_unique_line_avg": _as_float(_get_path(summary, "gas.frontend_staged_reads_per_unique_line_avg")),
        "gas_frontend_staged_reads_per_granule_avg": _as_float(_get_path(summary, "gas.frontend_staged_reads_per_granule_avg")),
        "gas_unique_line_count_total": _as_float(_get_path(summary, "gas.unique_line_count_total")),
        "gas_covered_line_count_total": _as_float(_get_path(summary, "gas.covered_line_count_total")),
        "gas_line_density_unique_over_covered": _as_float(_get_path(summary, "gas.line_density_unique_over_covered")),
        "gas_line_size_bytes": _as_float(_get_path(summary, "gas.line_size_bytes")),
        "gas_unique_line_bytes_total": _as_float(_get_path(summary, "gas.unique_line_bytes_total")),
        "gas_covered_line_bytes_total": _as_float(_get_path(summary, "gas.covered_line_bytes_total")),
        "gas_payload_bytes_per_unique_line_avg": _as_float(_get_path(summary, "gas.payload_bytes_per_unique_line_avg")),
        "gas_payload_bytes_per_covered_line_avg": _as_float(_get_path(summary, "gas.payload_bytes_per_covered_line_avg")),
        "gas_line_utilization_unique": _as_float(_get_path(summary, "gas.line_utilization_unique")),
        "gas_line_utilization_unique_permille": _as_float(_get_path(summary, "gas.line_utilization_unique_permille")),
        "gas_line_utilization_covered": _as_float(_get_path(summary, "gas.line_utilization_covered")),
        "gas_line_utilization_covered_permille": _as_float(_get_path(summary, "gas.line_utilization_covered_permille")),
        "gas_payload_bytes_per_memctrl_req_avg": _as_float(_get_path(summary, "gas.payload_bytes_per_memctrl_req_avg")),
        "gas_memctrl_payload_utilization": _as_float(_get_path(summary, "gas.memctrl_payload_utilization")),
        "gas_memctrl_payload_utilization_permille": _as_float(_get_path(summary, "gas.memctrl_payload_utilization_permille")),
        "gas_memctrl_traffic_amplification": _as_float(_get_path(summary, "gas.memctrl_traffic_amplification")),
        "gas_bursts_total": _as_float(_get_path(summary, "gas.bursts_total")),
        "gas_row_window_triggers_total": _as_float(_get_path(summary, "gas.row_window_triggers_total")),
        "gas_row_window_bytes_total": _as_float(_get_path(summary, "gas.row_window_bytes_total")),
        "gas_cmd_cost_veto_total": _as_float(_get_path(summary, "gas.cmd_cost_veto_total")),
        "gas_cmd_cost_veto_fine_gap_total": _as_float(_get_path(summary, "gas.cmd_cost_veto_fine_gap_total")),
        "gas_cmd_cost_veto_row_window_total": _as_float(_get_path(summary, "gas.cmd_cost_veto_row_window_total")),
        "gas_retire_global_hol_cycles_total": _as_float(_get_path(summary, "gas.retire_global_hol_cycles_total")),
        "gas_retire_ready_but_blocked_edges_total": _as_float(_get_path(summary, "gas.retire_ready_but_blocked_edges_total")),
        "gas_retire_per_post_progress_total": _as_float(_get_path(summary, "gas.retire_per_post_progress_total")),
        "gas_retire_ready_blocked_edges_per_hol_cycle_avg": _as_float(_get_path(summary, "gas.retire_ready_blocked_edges_per_hol_cycle_avg")),
        "gas_apply_ns_avg": _as_float(_get_path(summary, "gas.apply_ns_avg")),
        "gas_apply_exec_ns_avg": _as_float(_get_path(summary, "gas.apply_exec_ns_avg")),
        "gas_apply_to_scatter_gap_ns_avg": _as_float(_get_path(summary, "gas.apply_to_scatter_gap_ns_avg")),
        "pipeline_rx_packets_to_staged_reads_ratio": _as_float(_get_path(summary, "pipeline.rx_packets_to_staged_reads_ratio")),
        "pipeline_staged_reads_to_granules_ratio": _as_float(_get_path(summary, "pipeline.staged_reads_to_granules_ratio")),
        "pipeline_granules_to_memctrl_req_ratio": _as_float(_get_path(summary, "pipeline.granules_to_memctrl_req_ratio")),
        "pipeline_payload_bytes_per_rx_packet_avg": _as_float(_get_path(summary, "pipeline.payload_bytes_per_rx_packet_avg")),
        "pipeline_retire_drag_ratio": _as_float(_get_path(summary, "pipeline.retire_drag_ratio")),
        "imbalance_pe_total_ns_max_over_avg": _as_float(_get_path(summary, "imbalance.pe_total_ns_max_over_avg")),
        "imbalance_pe_apply_exec_ns_max_over_avg": _as_float(_get_path(summary, "imbalance.pe_apply_exec_ns_max_over_avg")),
        "imbalance_pe_apply_to_scatter_gap_ns_max_over_avg": _as_float(_get_path(summary, "imbalance.pe_apply_to_scatter_gap_ns_max_over_avg")),
        "imbalance_steps_done_range": _as_float(_get_path(summary, "imbalance.steps_done_range")),
        "synapse_sram_served_bytes_total": _as_float(_get_path(summary, "synapse.sram_served_bytes_total")),
        "synapse_sram_fill_bytes_total": _as_float(_get_path(summary, "synapse.sram_fill_bytes_total")),
        "synapse_sram_hit_total": _as_float(_get_path(summary, "synapse.sram_hit_total")),
        "synapse_sram_miss_total": _as_float(_get_path(summary, "synapse.sram_miss_total")),
        "synapse_index_to_values_ratio": _as_float(_get_path(summary, "synapse.index_cost.index_to_values_ratio")),
        "synapse_index_bits_per_edge": _as_float(_get_path(summary, "synapse.index_cost.index_bits_per_edge")),
    }
    if profile == "mainline":
        return {k: all_metrics.get(k) for k in MAINLINE_METRIC_KEYS}
    return all_metrics


def _write_compare_tsv(exp_dir: Path, exp_id: str, baseline: str, cases: List[Case], profile: str) -> None:
    rows: List[Tuple[str, Dict[str, Optional[float]]]] = []
    for c in cases:
        snap_dir = exp_dir / "snapshot" / "cases" / _safe_case_dirname(c.case_id)
        s = _read_json(snap_dir / "essential_summary_mesh.json")
        rows.append((c.case_id, _extract_metrics(s, profile)))

    base_metrics: Dict[str, Optional[float]] = {}
    for cid, m in rows:
        if cid == baseline:
            base_metrics = m
            break

    keys = list(rows[0][1].keys()) if rows else []
    out_path = exp_dir / "snapshot" / "compare.tsv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# experiment_id\t{exp_id}\n")
        f.write(f"# baseline_case\t{baseline}\n")
        f.write(f"# profile\t{profile}\n")
        f.write("case_id\tlabel\t" + "\t".join(keys) + "\t" + "\t".join([f"{k}_ratio_vs_base" for k in keys]) + "\n")
        for c in cases:
            m = next(mm for cid, mm in rows if cid == c.case_id)
            vals = [_fmt(m.get(k)) for k in keys]
            ratios: List[str] = []
            for k in keys:
                v = m.get(k)
                b = base_metrics.get(k)
                if v is None or b is None or b == 0:
                    ratios.append("NA")
                else:
                    ratios.append(_fmt(v / b))
            f.write(f"{c.case_id}\t{c.label}\t" + "\t".join(vals) + "\t" + "\t".join(ratios) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp-dir", required=True, help="memop/experiments/<exp> directory containing cases.json")
    ap.add_argument(
        "--profile",
        choices=("all", "mainline"),
        default="all",
        help="metric profile for compare.tsv (default: all)",
    )
    args = ap.parse_args()

    exp_dir = Path(args.exp_dir).resolve()
    exp_id, baseline, cases = _load_cases(exp_dir)

    # Snapshot
    for c in cases:
        _snapshot_case(exp_dir, c)

    # Compare
    _write_compare_tsv(exp_dir, exp_id, baseline, cases, args.profile)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
