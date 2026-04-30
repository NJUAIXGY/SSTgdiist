#!/usr/bin/env python3
"""Aggregate readiness-v3 summaries into one machine-readable report."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return float(default)
        if isinstance(value, (int, float)):
            return float(value)
        txt = str(value).strip()
        if not txt:
            return float(default)
        return float(txt)
    except Exception:
        return float(default)


def _readiness_level(avg_score: float) -> str:
    if avg_score >= 80.0:
        return "L3"
    if avg_score >= 65.0:
        return "L2"
    if avg_score >= 50.0:
        return "L1"
    return "L0"


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="append", default=[], help="summary path (repeatable)")
    ap.add_argument("--out", required=True, help="output report path")
    args = ap.parse_args(argv)

    if not args.summary:
        print("[m66][P0] at least one --summary is required", file=sys.stderr)
        return 2

    summaries = [Path(x).expanduser().resolve() for x in args.summary]
    for p in summaries:
        if not p.exists():
            print(f"[m66][P0] missing summary: {p}", file=sys.stderr)
            return 2

    scenario_rows: List[Dict[str, Any]] = []
    total_scores: List[float] = []
    total_dists: List[float] = []
    dominant_counter: Counter[str] = Counter()
    bottleneck_counter: Counter[str] = Counter()
    intervention_counter: Counter[str] = Counter()

    for p in summaries:
        try:
            payload = _load_json(p)
        except Exception as exc:
            print(f"[m66][P0] cannot parse summary json {p}: {exc}", file=sys.stderr)
            return 2
        if not isinstance(payload, dict):
            print(f"[m66][P0] summary root must be object: {p}", file=sys.stderr)
            return 2

        ready = payload.get("npu_tpu_readiness")
        if not isinstance(ready, dict):
            print(f"[m66][P0] missing npu_tpu_readiness: {p}", file=sys.stderr)
            return 2

        score = _to_float(ready.get("capability_score_total"), 0.0)
        dist = _to_float(ready.get("distance_to_target"), 0.0)
        attr = ready.get("cross_layer_attribution")
        attr_d = attr if isinstance(attr, dict) else {}
        dominant = str(attr_d.get("dominant_layer", "compute")).strip().lower() or "compute"
        top = ready.get("top_bottlenecks")
        top_list = [str(x).strip().lower() for x in top] if isinstance(top, list) else []
        suggestions = ready.get("suggested_interventions")
        sug_list = suggestions if isinstance(suggestions, list) else []

        total_scores.append(score)
        total_dists.append(dist)
        dominant_counter[dominant] += 1
        for item in top_list:
            if item:
                bottleneck_counter[item] += 1
        for item in sug_list:
            if isinstance(item, dict):
                key = str(item.get("parameter", "")).strip()
                if key:
                    intervention_counter[key] += 1

        scenario_rows.append(
            {
                "summary": str(p),
                "score_total": round(score, 3),
                "distance_to_target": round(dist, 3),
                "dominant_layer": dominant,
                "top_bottlenecks": top_list[:3],
            }
        )

    avg_score = (sum(total_scores) / float(len(total_scores))) if total_scores else 0.0
    avg_dist = (sum(total_dists) / float(len(total_dists))) if total_dists else 0.0

    report = {
        "schema_version": 1,
        "scenario_count": len(scenario_rows),
        "scenarios": scenario_rows,
        "capability_score_total_avg": round(avg_score, 3),
        "distance_to_target_avg": round(avg_dist, 3),
        "readiness_level": _readiness_level(avg_score),
        "dominant_layer_distribution": dict(sorted(dominant_counter.items(), key=lambda kv: kv[0])),
        "top_bottlenecks_union": [k for k, _v in bottleneck_counter.most_common()],
        "suggested_interventions_ranked": [
            {"parameter": key, "count": int(count)}
            for key, count in intervention_counter.most_common()
        ],
    }

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[m66] readiness_v3_report: {out}")
    print(f"[m66] score_avg={report['capability_score_total_avg']} distance_avg={report['distance_to_target_avg']}")
    print(f"[m66] readiness_level={report['readiness_level']} dominant_layers={report['dominant_layer_distribution']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
