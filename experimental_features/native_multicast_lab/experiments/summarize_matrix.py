#!/usr/bin/env python3

import argparse
import csv
import json
import os
from typing import Any, Dict, List, Tuple


def _int_from_tag(tag: str, key: str) -> int:
    # Example: "..._s16_hash4" => key="s" returns 16
    parts = tag.split("_")
    for p in parts:
        if p.startswith(key):
            try:
                return int(p[len(key) :], 10)
            except Exception:
                return 0
    return 0


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _mean(xs: List[float]) -> float:
    return sum(xs) / float(len(xs)) if xs else 0.0


def _collect_rows(summary: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cfg = summary.get("suite_config", {}) or {}
    run_id = str(summary.get("run_id", "") or "")
    ingress = str(cfg.get("MULTICAST_INGRESS_POLICY", "") or "")
    service = int(cfg.get("ROUTER_SERIALIZE_SERVICE_CYCLES", 0) or 0)
    edges_csv = str(cfg.get("EDGES_CSV", "") or "")
    sim_time = str(cfg.get("SIM_TIME", "") or "")
    stop_cycle = int(cfg.get("TRAFFIC_STOP_CYCLE", 0) or 0)
    period = int(cfg.get("TRAFFIC_PERIOD_CYCLES", 0) or 0)
    batch = int(cfg.get("TRAFFIC_BATCH_SIZE", 0) or 0)

    rows: List[Dict[str, Any]] = []
    for c in summary.get("comparisons", []) or []:
        row = {
            "run_id": run_id,
            "ingress": ingress,
            "service_cycles": service,
            "seed": int(c.get("seed", 0) or 0),
            "out_ratio_unicast_over_multicast": float(c.get("out_ratio_unicast_over_multicast", 0.0) or 0.0),
            "fwd_xy_ratio_unicast_over_multicast": float(c.get("fwd_xy_ratio_unicast_over_multicast", 0.0) or 0.0),
            "rx_ratio_spike_over_spikekey": float(c.get("rx_ratio_spike_over_spikekey", 0.0) or 0.0),
            "p95_lat_ratio_unicast_over_multicast": float(c.get("p95_lat_ratio_unicast_over_multicast", 0.0) or 0.0),
            "p99_lat_ratio_unicast_over_multicast": float(c.get("p99_lat_ratio_unicast_over_multicast", 0.0) or 0.0),
            "overflow_frac_delta_unicast_minus_multicast": float(
                c.get("overflow_frac_delta_unicast_minus_multicast", 0.0) or 0.0
            ),
            "sim_time": sim_time,
            "traffic_stop_cycle": stop_cycle,
            "traffic_period_cycles": period,
            "traffic_batch_size": batch,
            "edges_csv": edges_csv,
        }
        rows.append(row)

    grouped: Dict[str, Any] = {
        "run_id": run_id,
        "ingress": ingress,
        "service_cycles": service,
        "sim_time": sim_time,
        "traffic_stop_cycle": stop_cycle,
        "traffic_period_cycles": period,
        "traffic_batch_size": batch,
        "edges_csv": edges_csv,
    }
    if rows:
        grouped.update(
            {
                "seeds": [r["seed"] for r in rows],
                "mean_out_ratio_unicast_over_multicast": _mean([r["out_ratio_unicast_over_multicast"] for r in rows]),
                "mean_fwd_xy_ratio_unicast_over_multicast": _mean(
                    [r["fwd_xy_ratio_unicast_over_multicast"] for r in rows]
                ),
                "mean_rx_ratio_spike_over_spikekey": _mean([r["rx_ratio_spike_over_spikekey"] for r in rows]),
                "mean_p95_lat_ratio_unicast_over_multicast": _mean(
                    [r["p95_lat_ratio_unicast_over_multicast"] for r in rows]
                ),
                "mean_p99_lat_ratio_unicast_over_multicast": _mean(
                    [r["p99_lat_ratio_unicast_over_multicast"] for r in rows]
                ),
                "mean_overflow_frac_delta_unicast_minus_multicast": _mean(
                    [r["overflow_frac_delta_unicast_minus_multicast"] for r in rows]
                ),
            }
        )

    return rows, grouped


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize native multicast lab matrix runs (suite_summary.json) into CSV/JSON.")
    ap.add_argument("--runs-root", type=str, default="")
    ap.add_argument("--prefix", type=str, default="matrix_")
    ap.add_argument("--out-csv", type=str, default="")
    ap.add_argument("--out-json", type=str, default="")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    runs_root = os.path.abspath(args.runs_root) if args.runs_root.strip() else os.path.join(here, "runs")

    out_csv = os.path.abspath(args.out_csv) if args.out_csv.strip() else os.path.join(runs_root, "matrix_summary.csv")
    out_json = os.path.abspath(args.out_json) if args.out_json.strip() else os.path.join(runs_root, "matrix_summary.json")

    all_rows: List[Dict[str, Any]] = []
    grouped_rows: List[Dict[str, Any]] = []

    for name in sorted(os.listdir(runs_root)):
        if not name.startswith("20"):
            continue
        if args.prefix and args.prefix not in name:
            continue
        p = os.path.join(runs_root, name, "suite_summary.json")
        if not os.path.isfile(p):
            continue
        summary = _load_json(p)
        rows, grouped = _collect_rows(summary)
        if rows:
            all_rows.extend(rows)
            grouped_rows.append(grouped)

    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    if all_rows:
        fieldnames = list(all_rows[0].keys())
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in all_rows:
                w.writerow(r)
    else:
        with open(out_csv, "w", encoding="utf-8") as f:
            f.write("")

    payload = {
        "repo_root": os.path.relpath(repo_root, repo_root),
        "runs_root": os.path.relpath(runs_root, repo_root),
        "prefix": args.prefix,
        "runs_count": len(grouped_rows),
        "groups": grouped_rows,
        "rows": all_rows,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    print(f"[summary] runs={len(grouped_rows)} rows={len(all_rows)} out_csv={os.path.relpath(out_csv, repo_root)}")
    print(f"[summary] out_json={os.path.relpath(out_json, repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

