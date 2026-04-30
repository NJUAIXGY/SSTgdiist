#!/usr/bin/env python3
"""Aggregate readiness summaries into one M42 report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from tensor_readiness import build_readiness_assessment


CONF_ORDER = {"unverified": 0, "low": 1, "medium": 2, "high": 3}


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


def _load_effective_cfg(summary_path: Path) -> Dict[str, Any]:
    path = summary_path.parent / "effective_config.json"
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _pick_best_confidence(values: List[str]) -> str:
    best = "unverified"
    best_rank = -1
    for raw in values:
        conf = str(raw or "").strip().lower()
        rank = CONF_ORDER.get(conf, -1)
        if rank > best_rank:
            best_rank = rank
            best = conf if conf in CONF_ORDER else best
    return best


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
    ap.add_argument("--profile", default="", help="optional calibration profile json")
    ap.add_argument("--out", required=True, help="output report path")
    args = ap.parse_args(argv)

    if not args.summary:
        print("[m42][P0] at least one --summary is required", file=sys.stderr)
        return 2

    summaries: List[Path] = [Path(x).expanduser().resolve() for x in args.summary]
    for p in summaries:
        if not p.exists():
            print(f"[m42][P0] missing summary: {p}", file=sys.stderr)
            return 2

    profile_conf = ""
    if args.profile:
        profile_path = Path(args.profile).expanduser().resolve()
        if not profile_path.exists():
            print(f"[m42][P0] missing --profile: {profile_path}", file=sys.stderr)
            return 2
        try:
            profile_payload = _load_json(profile_path)
        except Exception as exc:
            print(f"[m42][P0] cannot parse --profile json: {exc}", file=sys.stderr)
            return 2
        profile_conf = str(profile_payload.get("confidence", "")).strip().lower()

    scenario_rows: List[Dict[str, Any]] = []
    gap_acc: Dict[str, List[float]] = {}
    breakdown_acc: Dict[str, List[float]] = {}
    drift_union: set[str] = set()
    confidence_values: List[str] = []

    for p in summaries:
        try:
            payload = _load_json(p)
        except Exception as exc:
            print(f"[m42][P0] cannot parse summary json {p}: {exc}", file=sys.stderr)
            return 2
        if not isinstance(payload, dict):
            print(f"[m42][P0] summary root must be object: {p}", file=sys.stderr)
            return 2

        tensor = payload.get("tensor")
        if not isinstance(tensor, dict):
            print(f"[m42][P0] missing tensor object in summary: {p}", file=sys.stderr)
            return 2

        readiness = payload.get("npu_tpu_readiness")
        if not isinstance(readiness, dict):
            readiness = build_readiness_assessment(tensor, effective_cfg=_load_effective_cfg(p))

        total = _to_float(readiness.get("capability_score_total"), _to_float(tensor.get("tensor_capability_score_total"), 0.0))
        distance = _to_float(readiness.get("distance_to_target"), _to_float(tensor.get("tensor_distance_to_target"), 0.0))
        breakdown = readiness.get("capability_score_breakdown")
        topk = readiness.get("gap_rank_topk")
        conf = str(readiness.get("calibration_confidence", "unverified")).strip().lower() or "unverified"
        flags = readiness.get("regression_drift_flags")

        if isinstance(breakdown, dict):
            for name, value in breakdown.items():
                breakdown_acc.setdefault(str(name), []).append(_to_float(value, 0.0))
        if isinstance(topk, list):
            for item in topk:
                if not isinstance(item, dict):
                    continue
                dim = str(item.get("dimension", "")).strip().lower()
                if not dim:
                    continue
                gap_acc.setdefault(dim, []).append(_to_float(item.get("gap"), 0.0))
        if isinstance(flags, list):
            for f in flags:
                tag = str(f).strip()
                if tag:
                    drift_union.add(tag)

        confidence_values.append(conf)

        scenario_rows.append(
            {
                "summary": str(p),
                "score_total": round(total, 3),
                "distance_to_target": round(distance, 3),
                "calibration_confidence": conf,
            }
        )

    totals = [float(row["score_total"]) for row in scenario_rows]
    dists = [float(row["distance_to_target"]) for row in scenario_rows]
    avg_total = sum(totals) / float(len(totals)) if totals else 0.0
    avg_dist = sum(dists) / float(len(dists)) if dists else 0.0

    breakdown_avg = {
        k: round(sum(vals) / float(len(vals)), 3)
        for k, vals in sorted(breakdown_acc.items(), key=lambda kv: kv[0])
        if vals
    }

    top_gaps = []
    for dim, vals in gap_acc.items():
        if not vals:
            continue
        top_gaps.append({"dimension": dim, "gap_avg": round(sum(vals) / float(len(vals)), 3)})
    top_gaps.sort(key=lambda x: (float(x.get("gap_avg", 0.0)), str(x.get("dimension", ""))), reverse=True)

    confidence_final = profile_conf if profile_conf in CONF_ORDER else _pick_best_confidence(confidence_values)

    report = {
        "schema_version": 1,
        "scenario_count": len(scenario_rows),
        "scenarios": scenario_rows,
        "capability_score_total_avg": round(avg_total, 3),
        "distance_to_target_avg": round(avg_dist, 3),
        "capability_score_breakdown_avg": breakdown_avg,
        "top_gaps": top_gaps[:5],
        "regression_drift_flags_union": sorted(drift_union),
        "calibration_confidence": confidence_final,
        "readiness_level": _readiness_level(avg_total),
    }

    out = Path(args.out).expanduser().resolve()
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[m42][P0] write report failed: {exc}", file=sys.stderr)
        return 2

    print(f"[m42] readiness_report: {out}")
    print(f"[m42] score_avg={report['capability_score_total_avg']} distance_avg={report['distance_to_target_avg']}")
    print(f"[m42] readiness_level={report['readiness_level']} calibration_confidence={report['calibration_confidence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
