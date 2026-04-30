#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple


DEFAULT_VARIANTS: List[Tuple[str, str]] = [
    ("A_spike_unicast", "Spike(unicast)"),
    ("B_spikekey_multicast", "SpikeKey"),
    ("B_spikekey_multicast_p0", "SpikeKey+P0"),
    ("C_spiketilekey_multicast", "SpikeTileKey(B)"),
    ("C_spiketilekey_multicast_p0", "SpikeTileKey(B)+P0"),
]

METRICS: List[Tuple[str, str]] = [
    ("sim_time_actual_ns", "sim_time_actual_ns"),
    ("memory_bytes", "memory_bytes"),
    ("memctrl.bytes_est_total", "memctrl_bytes_est_total"),
    ("total_spikes_processed", "total_spikes_processed"),
    ("snn_tx.spike_packets_total", "snn_tx_spike_packets_total"),
    ("snn_tx.spikekey_packets_total", "snn_tx_spikekey_packets_total"),
    ("snn_tx.spiketilekey_packets_total", "snn_tx_spiketilekey_packets_total"),
    ("snn_rx.spike_packets_total", "snn_rx_spike_packets_total"),
    ("snn_rx.fastpath_packets_total", "snn_rx_fastpath_packets_total"),
    ("snn_rx.fallback_packets_total", "snn_rx_fallback_packets_total"),
    ("snn_rx.fastpath_posts_total", "snn_rx_fastpath_posts_total"),
    ("snn_rx.fastpath_edges_recorded_total", "snn_rx_fastpath_edges_recorded_total"),
]

VAL_SUMMARY_RE = re.compile(r"\[val\]\s+SUMMARY\b.*\bfail=(\d+)\b.*\bwarn=(\d+)\b")


@dataclass
class RunRow:
    variant_tag: str
    variant_label: str
    run_dir: str
    run_id: str
    sim_time_actual_ns: Optional[float]
    memory_bytes: Optional[float]
    memctrl_bytes_est_total: Optional[float]
    total_spikes_processed: Optional[float]
    snn_tx_spike_packets_total: Optional[float]
    snn_tx_spikekey_packets_total: Optional[float]
    snn_tx_spiketilekey_packets_total: Optional[float]
    snn_rx_spike_packets_total: Optional[float]
    snn_rx_fastpath_packets_total: Optional[float]
    snn_rx_fallback_packets_total: Optional[float]
    snn_rx_fastpath_posts_total: Optional[float]
    snn_rx_fastpath_edges_recorded_total: Optional[float]
    validation_fail: int
    validation_warn: int
    validation_pass: int


def as_float(v) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    return None


def get_nested(obj: Dict, path: str):
    cur = obj
    for key in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def p_quantile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def read_json(path: Path) -> Optional[Dict]:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def parse_validation(validation_log: Path) -> Tuple[int, int]:
    if not validation_log.is_file():
        return (1, 0)
    fail = 1
    warn = 0
    try:
        text = validation_log.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return (1, 0)
    for line in text.splitlines():
        m = VAL_SUMMARY_RE.search(line)
        if m:
            fail = int(m.group(1))
            warn = int(m.group(2))
    return (fail, warn)


def discover_rows(root: Path, variants: List[Tuple[str, str]]) -> List[RunRow]:
    rows: List[RunRow] = []
    for tag, label in variants:
        variant_root = root / tag
        if not variant_root.is_dir():
            continue
        run_dirs = sorted([p for p in variant_root.iterdir() if p.is_dir()])
        for run_dir in run_dirs:
            summary = read_json(run_dir / "essential_summary_mesh.json")
            if not summary:
                continue
            fail, warn = parse_validation(run_dir / "validation.log")
            sim_time_actual_ns = as_float(summary.get("sim_time_actual_ns"))
            if sim_time_actual_ns is None:
                sim_time_actual_ns = as_float(get_nested(summary, "model.sim_time_actual_ns"))

            memory_bytes = as_float(summary.get("memory_bytes"))
            if memory_bytes is None:
                memory_bytes = as_float(get_nested(summary, "memory.memory_bytes"))

            memctrl_bytes_est_total = as_float(summary.get("memctrl.bytes_est_total"))
            if memctrl_bytes_est_total is None:
                memctrl_bytes_est_total = as_float(get_nested(summary, "memhierarchy.memctrl.bytes_est_total"))

            total_spikes_processed = as_float(summary.get("total_spikes_processed"))
            if total_spikes_processed is None:
                total_spikes_processed = as_float(get_nested(summary, "spike_activity.total_spikes_processed"))

            snn_tx_spike_packets_total = as_float(get_nested(summary, "snn_tx.spike_packets_total"))
            snn_tx_spikekey_packets_total = as_float(get_nested(summary, "snn_tx.spikekey_packets_total"))
            snn_tx_spiketilekey_packets_total = as_float(get_nested(summary, "snn_tx.spiketilekey_packets_total"))

            snn_rx_spike_packets_total = as_float(summary.get("snn_rx.spike_packets_total"))
            if snn_rx_spike_packets_total is None:
                snn_rx_spike_packets_total = as_float(get_nested(summary, "snn_rx.spike_packets_total"))

            snn_rx_fastpath_packets_total = as_float(summary.get("snn_rx.fastpath_packets_total"))
            if snn_rx_fastpath_packets_total is None:
                snn_rx_fastpath_packets_total = as_float(get_nested(summary, "snn_rx.fastpath_packets_total"))

            snn_rx_fallback_packets_total = as_float(summary.get("snn_rx.fallback_packets_total"))
            if snn_rx_fallback_packets_total is None:
                snn_rx_fallback_packets_total = as_float(get_nested(summary, "snn_rx.fallback_packets_total"))

            snn_rx_fastpath_posts_total = as_float(summary.get("snn_rx.fastpath_posts_total"))
            if snn_rx_fastpath_posts_total is None:
                snn_rx_fastpath_posts_total = as_float(get_nested(summary, "snn_rx.fastpath_posts_total"))

            snn_rx_fastpath_edges_recorded_total = as_float(summary.get("snn_rx.fastpath_edges_recorded_total"))
            if snn_rx_fastpath_edges_recorded_total is None:
                snn_rx_fastpath_edges_recorded_total = as_float(get_nested(summary, "snn_rx.fastpath_edges_recorded_total"))

            rows.append(
                RunRow(
                    variant_tag=tag,
                    variant_label=label,
                    run_dir=str(run_dir),
                    run_id=run_dir.name,
                    sim_time_actual_ns=sim_time_actual_ns,
                    memory_bytes=memory_bytes,
                    memctrl_bytes_est_total=memctrl_bytes_est_total,
                    total_spikes_processed=total_spikes_processed,
                    snn_tx_spike_packets_total=snn_tx_spike_packets_total,
                    snn_tx_spikekey_packets_total=snn_tx_spikekey_packets_total,
                    snn_tx_spiketilekey_packets_total=snn_tx_spiketilekey_packets_total,
                    snn_rx_spike_packets_total=snn_rx_spike_packets_total,
                    snn_rx_fastpath_packets_total=snn_rx_fastpath_packets_total,
                    snn_rx_fallback_packets_total=snn_rx_fallback_packets_total,
                    snn_rx_fastpath_posts_total=snn_rx_fastpath_posts_total,
                    snn_rx_fastpath_edges_recorded_total=snn_rx_fastpath_edges_recorded_total,
                    validation_fail=fail,
                    validation_warn=warn,
                    validation_pass=1 if fail == 0 else 0,
                )
            )
    return rows


def write_results_csv(path: Path, rows: List[RunRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "variant_tag",
                "variant_label",
                "run_dir",
                "run_id",
                "sim_time_actual_ns",
                "memory_bytes",
                "memctrl_bytes_est_total",
                "total_spikes_processed",
                "snn_tx_spike_packets_total",
                "snn_tx_spikekey_packets_total",
                "snn_tx_spiketilekey_packets_total",
                "snn_rx_spike_packets_total",
                "snn_rx_fastpath_packets_total",
                "snn_rx_fallback_packets_total",
                "snn_rx_fastpath_posts_total",
                "snn_rx_fastpath_edges_recorded_total",
                "validation_fail",
                "validation_warn",
                "validation_pass",
            ]
        )
        for row in rows:
            w.writerow(
                [
                    row.variant_tag,
                    row.variant_label,
                    row.run_dir,
                    row.run_id,
                    row.sim_time_actual_ns,
                    row.memory_bytes,
                    row.memctrl_bytes_est_total,
                    row.total_spikes_processed,
                    row.snn_tx_spike_packets_total,
                    row.snn_tx_spikekey_packets_total,
                    row.snn_tx_spiketilekey_packets_total,
                    row.snn_rx_spike_packets_total,
                    row.snn_rx_fastpath_packets_total,
                    row.snn_rx_fallback_packets_total,
                    row.snn_rx_fastpath_posts_total,
                    row.snn_rx_fastpath_edges_recorded_total,
                    row.validation_fail,
                    row.validation_warn,
                    row.validation_pass,
                ]
            )


def collect_metric(rows: List[RunRow], metric_name: str) -> List[float]:
    out: List[float] = []
    for row in rows:
        v = getattr(row, metric_name)
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def write_stats_csv(path: Path, rows: List[RunRow], variants: List[Tuple[str, str]]) -> Dict[str, Dict[str, float]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    medians: Dict[str, Dict[str, float]] = {}
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "variant_tag",
                "variant_label",
                "n_total",
                "n_pass",
                "metric",
                "median",
                "p95",
                "min",
                "max",
                "mean",
            ]
        )
        for tag, label in variants:
            variant_rows = [r for r in rows if r.variant_tag == tag]
            pass_rows = [r for r in variant_rows if r.validation_pass == 1]
            medians[tag] = {}
            for _, metric_attr in METRICS:
                vals = collect_metric(pass_rows, metric_attr)
                if vals:
                    med = float(median(vals))
                    p95 = p_quantile(vals, 0.95)
                    mn = min(vals)
                    mx = max(vals)
                    avg = sum(vals) / len(vals)
                    medians[tag][metric_attr] = med
                else:
                    med = p95 = mn = mx = avg = None
                w.writerow(
                    [
                        tag,
                        label,
                        len(variant_rows),
                        len(pass_rows),
                        metric_attr,
                        med,
                        p95,
                        mn,
                        mx,
                        avg,
                    ]
                )
    return medians


def write_normalized_csv(path: Path, medians: Dict[str, Dict[str, float]], variants: List[Tuple[str, str]], baseline: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "variant_tag",
                "variant_label",
                "metric",
                "median",
                "baseline_median",
                "ratio_to_baseline",
                "improvement_pct_lower_better",
            ]
        )
        base_metrics = medians.get(baseline, {})
        for tag, label in variants:
            for _, metric_attr in METRICS:
                med = medians.get(tag, {}).get(metric_attr)
                bmed = base_metrics.get(metric_attr)
                ratio = None
                improv = None
                if isinstance(med, (int, float)) and isinstance(bmed, (int, float)) and bmed != 0:
                    ratio = float(med) / float(bmed)
                    improv = (1.0 - ratio) * 100.0
                w.writerow([tag, label, metric_attr, med, bmed, ratio, improv])


def write_conclusion_md(path: Path, medians: Dict[str, Dict[str, float]], variants: List[Tuple[str, str]], baseline: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = medians.get(baseline, {})
    label_of = {k: v for k, v in variants}
    lines: List[str] = []
    lines.append("# SpikeTile 对比实验结论表")
    lines.append("")
    lines.append(f"- baseline: `{baseline}` ({label_of.get(baseline, baseline)})")
    lines.append("")
    lines.append("## 中位数对比（lower is better）")
    lines.append("")
    lines.append("| Metric | Baseline(B) | Spike(unicast) | SpikeTileKey(C) | C vs B 改善 |")
    lines.append("|---|---:|---:|---:|---:|")

    metric_names = [
        ("sim_time_actual_ns", "sim_time_actual_ns"),
        ("memory_bytes", "memory_bytes"),
        ("memctrl_bytes_est_total", "memctrl.bytes_est_total"),
    ]
    for attr, name in metric_names:
        b = base.get(attr)
        a = medians.get("A_spike_unicast", {}).get(attr)
        c = medians.get("C_spiketilekey_multicast", {}).get(attr)
        improve = ""
        if isinstance(c, (int, float)) and isinstance(b, (int, float)) and b != 0:
            improve = f"{(1.0 - c / b) * 100.0:.3f}%"
        lines.append(
            f"| `{name}` | {fmt_num(b)} | {fmt_num(a)} | {fmt_num(c)} | {improve} |"
        )

    lines.append("")
    lines.append("## 规模一致性检查")
    lines.append("")
    lines.append("| Metric | Baseline(B) | Spike(unicast) | SpikeTileKey(C) |")
    lines.append("|---|---:|---:|---:|")
    b_sp = base.get("total_spikes_processed")
    a_sp = medians.get("A_spike_unicast", {}).get("total_spikes_processed")
    c_sp = medians.get("C_spiketilekey_multicast", {}).get("total_spikes_processed")
    lines.append(f"| `total_spikes_processed` | {fmt_num(b_sp)} | {fmt_num(a_sp)} | {fmt_num(c_sp)} |")
    lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fmt_num(v: Optional[float]) -> str:
    if v is None:
        return "-"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.6g}"


def parse_variants(raw: str) -> List[Tuple[str, str]]:
    if not raw.strip():
        return list(DEFAULT_VARIANTS)
    tags = [x.strip() for x in raw.split(",") if x.strip()]
    result: List[Tuple[str, str]] = []
    defaults = {k: v for k, v in DEFAULT_VARIANTS}
    for t in tags:
        result.append((t, defaults.get(t, t)))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Aggregate SpikeTile compare_matrix outputs.")
    ap.add_argument("--root", default="sst_dram_si/experiments/spiketile_b_v0/outputs/compare_matrix", help="compare_matrix root directory")
    ap.add_argument("--out-dir", default="", help="output directory (default: <root>/analysis_latest)")
    ap.add_argument("--variants", default="", help="comma-separated variant tags")
    ap.add_argument("--baseline", default="B_spikekey_multicast", help="baseline variant tag")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir.strip() else (root / "analysis_latest")
    variants = parse_variants(args.variants)

    rows = discover_rows(root, variants)
    if not rows:
        print(f"[aggregate] no valid run found under: {root}")
        return 2

    rows.sort(key=lambda r: (r.variant_tag, r.run_id))
    write_results_csv(out_dir / "results.csv", rows)
    medians = write_stats_csv(out_dir / "stats_by_variant.csv", rows, variants)
    write_normalized_csv(out_dir / "normalized_to_baseline.csv", medians, variants, args.baseline)
    write_conclusion_md(out_dir / "conclusion_table.md", medians, variants, args.baseline)

    print(f"[aggregate] root: {root}")
    print(f"[aggregate] outputs:")
    print(f"  - {out_dir / 'results.csv'}")
    print(f"  - {out_dir / 'stats_by_variant.csv'}")
    print(f"  - {out_dir / 'normalized_to_baseline.csv'}")
    print(f"  - {out_dir / 'conclusion_table.md'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
