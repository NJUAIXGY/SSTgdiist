#!/usr/bin/env python3
"""Compare candidate readiness report against a fixed golden baseline (M43)."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Set


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return float(default)
        if isinstance(value, (int, float)):
            f = float(value)
            return f if math.isfinite(f) else float(default)
        txt = str(value).strip()
        if not txt:
            return float(default)
        f = float(txt)
        return f if math.isfinite(f) else float(default)
    except Exception:
        return float(default)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _round3(x: float) -> float:
    return float(round(float(x), 3))


def _sorted_flags(raw: List[Any]) -> List[str]:
    vals = sorted({str(v).strip() for v in raw if str(v).strip()})
    return vals


def _sorted_dims(raw: List[Any]) -> List[str]:
    vals = sorted({str(v).strip().lower() for v in raw if str(v).strip()})
    return vals


def _effective_thresholds(baseline_spec: Dict[str, Any], threshold_spec: Dict[str, Any] | None) -> Dict[str, Any]:
    base = _as_dict(baseline_spec.get("thresholds"))

    score_total_delta_min = _to_float(base.get("score_total_delta_min"), -3.0)
    breakdown_delta_min = _to_float(base.get("breakdown_delta_min"), -5.0)
    max_new_drift_flags = int(_to_float(base.get("max_new_drift_flags"), 2.0))
    enforce_dimensions = _sorted_dims(_as_list(base.get("enforce_dimensions")))

    if threshold_spec and isinstance(threshold_spec, dict):
        override_raw = threshold_spec.get("thresholds")
        override = _as_dict(override_raw if isinstance(override_raw, dict) else threshold_spec)

        if "score_total_delta_min" in override:
            score_total_delta_min = _to_float(override.get("score_total_delta_min"), score_total_delta_min)
        if "breakdown_delta_min" in override:
            breakdown_delta_min = _to_float(override.get("breakdown_delta_min"), breakdown_delta_min)
        if "max_new_drift_flags" in override:
            max_new_drift_flags = int(_to_float(override.get("max_new_drift_flags"), float(max_new_drift_flags)))
        if "enforce_dimensions" in override:
            enforce_dimensions = _sorted_dims(_as_list(override.get("enforce_dimensions")))

    if max_new_drift_flags < 0:
        max_new_drift_flags = 0

    return {
        "score_total_delta_min": float(score_total_delta_min),
        "breakdown_delta_min": float(breakdown_delta_min),
        "max_new_drift_flags": int(max_new_drift_flags),
        "enforce_dimensions": enforce_dimensions,
    }


def _compare(
    baseline_spec: Dict[str, Any],
    candidate_report: Dict[str, Any],
    candidate_path: Path,
    threshold_spec: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    baseline_id = str(baseline_spec.get("baseline_id", "m43_golden")).strip() or "m43_golden"
    baseline_snapshot = _as_dict(baseline_spec.get("baseline_report_snapshot"))
    thresholds = _effective_thresholds(baseline_spec, threshold_spec)
    score_total_delta_min = float(thresholds["score_total_delta_min"])
    breakdown_delta_min = float(thresholds["breakdown_delta_min"])
    max_new_drift_flags = int(thresholds["max_new_drift_flags"])
    enforce_dims = _sorted_dims(_as_list(thresholds.get("enforce_dimensions")))
    enforce_set: Set[str] = set(enforce_dims)

    baseline_total = _to_float(baseline_snapshot.get("capability_score_total_avg"), 0.0)
    candidate_total = _to_float(candidate_report.get("capability_score_total_avg"), 0.0)
    score_delta = candidate_total - baseline_total

    baseline_dist = _to_float(baseline_snapshot.get("distance_to_target_avg"), 0.0)
    candidate_dist = _to_float(candidate_report.get("distance_to_target_avg"), 0.0)
    distance_delta = candidate_dist - baseline_dist

    baseline_breakdown = _as_dict(baseline_snapshot.get("capability_score_breakdown_avg"))
    candidate_breakdown = _as_dict(candidate_report.get("capability_score_breakdown_avg"))
    dims = sorted(set(baseline_breakdown.keys()) | set(candidate_breakdown.keys()))
    breakdown_delta = {
        d: _round3(_to_float(candidate_breakdown.get(d), 0.0) - _to_float(baseline_breakdown.get(d), 0.0))
        for d in dims
    }

    baseline_flags = _sorted_flags(_as_list(baseline_snapshot.get("regression_drift_flags_union")))
    candidate_flags = _sorted_flags(_as_list(candidate_report.get("regression_drift_flags_union")))
    new_flags = sorted(set(candidate_flags) - set(baseline_flags))

    violations: List[Dict[str, Any]] = []

    if score_delta < score_total_delta_min:
        violations.append(
            {
                "rule": "score_total_delta_min",
                "message": "capability_score_total_avg dropped below allowed threshold",
                "actual": _round3(score_delta),
                "threshold": _round3(score_total_delta_min),
                "severity": "high",
            }
        )

    dims_for_breakdown = dims if not enforce_set else [d for d in dims if str(d).strip().lower() in enforce_set]
    for dim in dims_for_breakdown:
        delta = _to_float(breakdown_delta.get(dim), 0.0)
        if delta < breakdown_delta_min:
            violations.append(
                {
                    "rule": "breakdown_delta_min",
                    "dimension": str(dim),
                    "message": f"breakdown[{dim}] dropped below allowed threshold",
                    "actual": _round3(delta),
                    "threshold": _round3(breakdown_delta_min),
                    "severity": "medium",
                }
            )

    if len(new_flags) > max_new_drift_flags:
        violations.append(
            {
                "rule": "max_new_drift_flags",
                "message": "new drift flags exceed max allowed",
                "actual": len(new_flags),
                "threshold": max_new_drift_flags,
                "severity": "medium",
                "new_flags": new_flags,
            }
        )

    status = "pass" if not violations else "fail"
    severity = "none"
    if violations:
        severity = "high" if any(v.get("severity") == "high" for v in violations) else "medium"

    return {
        "schema_version": 1,
        "baseline_id": baseline_id,
        "candidate_report": str(candidate_path),
        "status": status,
        "severity": severity,
        "thresholds": {
            "score_total_delta_min": _round3(score_total_delta_min),
            "breakdown_delta_min": _round3(breakdown_delta_min),
            "max_new_drift_flags": max_new_drift_flags,
            "enforce_dimensions": enforce_dims,
        },
        "baseline_metrics": {
            "capability_score_total_avg": _round3(baseline_total),
            "distance_to_target_avg": _round3(baseline_dist),
            "capability_score_breakdown_avg": {k: _round3(_to_float(v, 0.0)) for k, v in baseline_breakdown.items()},
            "regression_drift_flags_union": baseline_flags,
        },
        "candidate_metrics": {
            "capability_score_total_avg": _round3(candidate_total),
            "distance_to_target_avg": _round3(candidate_dist),
            "capability_score_breakdown_avg": {k: _round3(_to_float(v, 0.0)) for k, v in candidate_breakdown.items()},
            "regression_drift_flags_union": candidate_flags,
        },
        "deltas": {
            "capability_score_total_avg": _round3(score_delta),
            "distance_to_target_avg": _round3(distance_delta),
            "capability_score_breakdown_avg": breakdown_delta,
            "new_regression_drift_flags": new_flags,
        },
        "violations": violations,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-spec", required=True, help="baseline spec json path")
    ap.add_argument("--threshold-spec", default="", help="optional override threshold spec json path")
    ap.add_argument("--candidate-report", required=True, help="candidate readiness report json path")
    ap.add_argument("--out", required=True, help="output drift report json path")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    baseline_path = Path(args.baseline_spec).expanduser().resolve()
    threshold_path = Path(args.threshold_spec).expanduser().resolve() if str(args.threshold_spec).strip() else None
    candidate_path = Path(args.candidate_report).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    if not baseline_path.exists():
        print(f"[m43][P0] missing --baseline-spec: {baseline_path}", file=sys.stderr)
        return 2
    if not candidate_path.exists():
        print(f"[m43][P0] missing --candidate-report: {candidate_path}", file=sys.stderr)
        return 2
    if threshold_path and not threshold_path.exists():
        print(f"[m43][P0] missing --threshold-spec: {threshold_path}", file=sys.stderr)
        return 2

    try:
        baseline_spec = _load_json(baseline_path)
    except Exception as exc:
        print(f"[m43][P0] cannot parse baseline spec json: {exc}", file=sys.stderr)
        return 2
    threshold_spec: Dict[str, Any] | None = None
    if threshold_path:
        try:
            threshold_spec = _load_json(threshold_path)
        except Exception as exc:
            print(f"[m43][P0] cannot parse threshold spec json: {exc}", file=sys.stderr)
            return 2
    try:
        candidate_report = _load_json(candidate_path)
    except Exception as exc:
        print(f"[m43][P0] cannot parse candidate report json: {exc}", file=sys.stderr)
        return 2

    if not isinstance(baseline_spec, dict) or not isinstance(candidate_report, dict) or (
        threshold_spec is not None and not isinstance(threshold_spec, dict)
    ):
        print("[m43][P0] baseline/candidate/threshold json root must be object", file=sys.stderr)
        return 2

    drift = _compare(baseline_spec, candidate_report, candidate_path, threshold_spec=threshold_spec)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(drift, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[m43][P0] write drift report failed: {exc}", file=sys.stderr)
        return 2

    prefix = f"[m43:{args.label}] " if args.label else "[m43] "
    print(
        f"{prefix}status={drift['status']} severity={drift['severity']} "
        f"score_delta={drift['deltas']['capability_score_total_avg']}"
    )
    print(f"{prefix}violations={len(drift.get('violations', []))} drift_report={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
