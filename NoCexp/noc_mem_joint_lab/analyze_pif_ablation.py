#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def _parse_wall_seconds(v: str) -> float:
    s = (v or "").strip()
    if not s:
        return 0.0
    parts = s.split(":")
    try:
        nums = [float(x) for x in parts]
    except Exception:
        return 0.0
    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        return nums[0] * 60.0 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600.0 + nums[1] * 60.0 + nums[2]
    return 0.0


def collect(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).resolve()
    summary_path = run_dir / "essential_summary_mesh.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"summary not found: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    model = summary.get("model") or {}
    gas = summary.get("gas") or {}
    wallclock = summary.get("wallclock") or {}
    ram2 = summary.get("ramulator2") or {}
    joint = summary.get("noc_mem_joint") or {}

    row: Dict[str, str] = {
        "case": str(args.case),
        "seed": str(args.seed),
        "run_dir": str(run_dir),
        "sim_time_actual_ns": f"{_to_float(model.get('sim_time_actual_ns')):.6f}",
        "gas_global_steps_done": f"{_to_float(gas.get('global_steps_done')):.6f}",
        "wall_s": f"{_parse_wall_seconds(str(wallclock.get('wall', ''))):.6f}",
        "rowidx_touch_rows_total": f"{_to_float(joint.get('rowidx_touch_rows_total')):.6f}",
        "rowidx_touch_events_total": f"{_to_float(joint.get('rowidx_touch_events_total')):.6f}",
        "rowidx_rows_filtered_cold_total": f"{_to_float(joint.get('rowidx_rows_filtered_cold_total')):.6f}",
        "rowidx_rows_filtered_cold_rate": f"{_to_float(joint.get('rowidx_rows_filtered_cold_rate')):.6f}",
        "rowidx_prefetch_rows_total": f"{_to_float(joint.get('rowidx_prefetch_rows_total')):.6f}",
        "rowidx_prefetch_bytes_total": f"{_to_float(joint.get('rowidx_prefetch_bytes_total')):.6f}",
        "rowidx_prefetch_rows_deferred_total": f"{_to_float(joint.get('rowidx_prefetch_rows_deferred_total')):.6f}",
        "rowidx_prefetch_rows_failed_total": f"{_to_float(joint.get('rowidx_prefetch_rows_failed_total')):.6f}",
        "rowidx_budget_ticks_total": f"{_to_float(joint.get('rowidx_budget_ticks_total')):.6f}",
        "rowidx_budget_effective_total": f"{_to_float(joint.get('rowidx_budget_effective_total')):.6f}",
        "rowidx_budget_effective_per_tick": f"{_to_float(joint.get('rowidx_budget_effective_per_tick')):.6f}",
        "rowidx_budget_adapt_ticks_total": f"{_to_float(joint.get('rowidx_budget_adapt_ticks_total')):.6f}",
        "rowidx_budget_adapt_tick_rate": f"{_to_float(joint.get('rowidx_budget_adapt_tick_rate')):.6f}",
        "rowidx_cache_hits_total": f"{_to_float(joint.get('rowidx_cache_hits_total')):.6f}",
        "rowidx_cache_misses_total": f"{_to_float(joint.get('rowidx_cache_misses_total')):.6f}",
        "rowidx_cache_fills_total": f"{_to_float(joint.get('rowidx_cache_fills_total')):.6f}",
        "rowidx_cache_full_drop_total": f"{_to_float(joint.get('rowidx_cache_full_drop_total')):.6f}",
        "rowidx_cache_entries_final": f"{_to_float(joint.get('rowidx_cache_entries_final')):.6f}",
        "rowidx_prefetch_coverage": f"{_to_float(joint.get('rowidx_prefetch_coverage')):.6f}",
        "rowidx_cache_hit_rate": f"{_to_float(joint.get('rowidx_cache_hit_rate')):.6f}",
        "ram2_num_read_reqs_total": f"{_to_float(ram2.get('num_read_reqs_total')):.6f}",
        "ram2_avg_read_latency_0_avg": f"{_to_float(ram2.get('avg_read_latency_0_avg')):.6f}",
        "ram2_row_hit_rate_total": f"{_to_float(ram2.get('row_hit_rate_total')):.6f}",
        "ram2_row_conflict_rate_total": f"{_to_float(ram2.get('row_conflict_rate_total')):.6f}",
    }

    out_csv = Path(args.out_csv).resolve()
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(row.keys())
    exists = out_csv.exists()
    with out_csv.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        w.writerow(row)
    print(f"[pif-ablation] row appended: {out_csv}")


def _mean(vals: List[float]) -> float:
    if not vals:
        return 0.0
    return sum(vals) / float(len(vals))


def aggregate(args: argparse.Namespace) -> None:
    in_csv = Path(args.in_csv).resolve()
    if not in_csv.exists():
        raise FileNotFoundError(f"input csv not found: {in_csv}")

    rows: List[Dict[str, str]] = []
    with in_csv.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    if not rows:
        raise RuntimeError("no rows to aggregate")

    groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("case", ""))].append(row)

    metric_cols = [
        "sim_time_actual_ns",
        "gas_global_steps_done",
        "wall_s",
        "rowidx_touch_rows_total",
        "rowidx_touch_events_total",
        "rowidx_rows_filtered_cold_total",
        "rowidx_rows_filtered_cold_rate",
        "rowidx_prefetch_rows_total",
        "rowidx_prefetch_bytes_total",
        "rowidx_prefetch_rows_deferred_total",
        "rowidx_prefetch_rows_failed_total",
        "rowidx_budget_ticks_total",
        "rowidx_budget_effective_total",
        "rowidx_budget_effective_per_tick",
        "rowidx_budget_adapt_ticks_total",
        "rowidx_budget_adapt_tick_rate",
        "rowidx_cache_hits_total",
        "rowidx_cache_misses_total",
        "rowidx_cache_fills_total",
        "rowidx_cache_full_drop_total",
        "rowidx_cache_entries_final",
        "rowidx_prefetch_coverage",
        "rowidx_cache_hit_rate",
        "ram2_num_read_reqs_total",
        "ram2_avg_read_latency_0_avg",
        "ram2_row_hit_rate_total",
        "ram2_row_conflict_rate_total",
    ]

    agg_rows: List[Dict[str, float]] = []
    for case_name in sorted(groups.keys()):
        g = groups[case_name]
        out: Dict[str, float] = {"num_runs": float(len(g))}
        for k in metric_cols:
            vals = [_to_float(x.get(k)) for x in g]
            out[k] = _mean(vals)
        out["case"] = case_name  # type: ignore[assignment]
        agg_rows.append(out)

    baseline = None
    for row in agg_rows:
        if str(row.get("case")) == str(args.baseline_case):
            baseline = row
            break
    if baseline is None:
        raise RuntimeError(f"baseline case not found in csv: {args.baseline_case}")

    for row in agg_rows:
        sim = _to_float(row.get("sim_time_actual_ns"))
        wall = _to_float(row.get("wall_s"))
        lat = _to_float(row.get("ram2_avg_read_latency_0_avg"))
        b_sim = _to_float(baseline.get("sim_time_actual_ns"))
        b_wall = _to_float(baseline.get("wall_s"))
        b_lat = _to_float(baseline.get("ram2_avg_read_latency_0_avg"))
        row["sim_speedup_vs_baseline"] = (b_sim / sim) if (b_sim > 0 and sim > 0) else 0.0
        row["wall_speedup_vs_baseline"] = (b_wall / wall) if (b_wall > 0 and wall > 0) else 0.0
        row["ram2_latency_improve_vs_baseline"] = (b_lat / lat) if (b_lat > 0 and lat > 0) else 0.0

    out_csv = Path(args.out_csv).resolve()
    out_json = Path(args.out_json).resolve()
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    cols = [
        "case",
        "num_runs",
        "sim_time_actual_ns",
        "sim_speedup_vs_baseline",
        "wall_s",
        "wall_speedup_vs_baseline",
        "rowidx_touch_rows_total",
        "rowidx_touch_events_total",
        "rowidx_rows_filtered_cold_total",
        "rowidx_rows_filtered_cold_rate",
        "rowidx_prefetch_rows_total",
        "rowidx_prefetch_coverage",
        "rowidx_budget_effective_per_tick",
        "rowidx_budget_adapt_tick_rate",
        "rowidx_cache_hit_rate",
        "rowidx_cache_entries_final",
        "ram2_num_read_reqs_total",
        "ram2_avg_read_latency_0_avg",
        "ram2_latency_improve_vs_baseline",
        "ram2_row_hit_rate_total",
        "ram2_row_conflict_rate_total",
    ]

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in agg_rows:
            serial = {k: row.get(k, "") for k in cols}
            w.writerow(serial)

    payload = {
        "baseline_case": str(args.baseline_case),
        "num_rows": len(rows),
        "num_cases": len(agg_rows),
        "cases": agg_rows,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[pif-ablation] aggregate written: {out_csv}")
    print(f"[pif-ablation] aggregate written: {out_json}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Collect/aggregate STORM-PIF ablation metrics.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_collect = sub.add_parser("collect")
    ap_collect.add_argument("--run-dir", required=True)
    ap_collect.add_argument("--case", required=True)
    ap_collect.add_argument("--seed", required=True)
    ap_collect.add_argument("--out-csv", required=True)
    ap_collect.set_defaults(func=collect)

    ap_agg = sub.add_parser("aggregate")
    ap_agg.add_argument("--in-csv", required=True)
    ap_agg.add_argument("--baseline-case", required=True)
    ap_agg.add_argument("--out-csv", required=True)
    ap_agg.add_argument("--out-json", required=True)
    ap_agg.set_defaults(func=aggregate)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
