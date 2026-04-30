#!/usr/bin/env python3
"""Validate Tensor frontend readiness contract (M44)."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REQUIRED_BREAKDOWN = {"scheduler", "dataflow", "memory", "parallelism", "scalability"}


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any) -> Tuple[bool, float]:
    try:
        if isinstance(value, bool):
            return False, 0.0
        if isinstance(value, (int, float)):
            f = float(value)
            return math.isfinite(f), f
        txt = str(value).strip()
        if not txt:
            return False, 0.0
        f = float(txt)
        return math.isfinite(f), f
    except Exception:
        return False, 0.0


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True, help="essential_summary_tensor_mesh.json path")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    summary_path = Path(args.summary).expanduser().resolve()
    if not summary_path.exists():
        return _fail(2, f"[m44][P0] missing --summary: {summary_path}")

    try:
        payload = _load_json(summary_path)
    except Exception as exc:
        return _fail(2, f"[m44][P0] cannot parse summary json: {exc}")

    if not isinstance(payload, dict):
        return _fail(2, "[m44][P0] summary root must be object")

    tensor = payload.get("tensor")
    if not isinstance(tensor, dict):
        return _fail(3, "[m44][P1] missing tensor object")

    readiness = payload.get("npu_tpu_readiness")
    if not isinstance(readiness, dict):
        return _fail(3, "[m44][P1] missing npu_tpu_readiness object")

    for key in ("capability_profile", "scheduler_model", "memory_hierarchy_profile"):
        val = str(readiness.get(key, "")).strip()
        if not val:
            return _fail(3, f"[m44][P1] readiness.{key} must be non-empty")

    ok_score, score = _to_float(readiness.get("capability_score_total"))
    ok_dist, dist = _to_float(readiness.get("distance_to_target"))
    ok_target, target = _to_float(readiness.get("target_score"))
    if not ok_score or score < 0.0 or score > 100.0:
        return _fail(3, "[m44][P1] invalid capability_score_total")
    if not ok_dist or dist < 0.0:
        return _fail(3, "[m44][P1] invalid distance_to_target")
    if not ok_target or target < 0.0 or target > 100.0:
        return _fail(3, "[m44][P1] invalid target_score")

    breakdown = readiness.get("capability_score_breakdown")
    if not isinstance(breakdown, dict):
        return _fail(3, "[m44][P1] capability_score_breakdown must be object")

    missing_dims = sorted(REQUIRED_BREAKDOWN.difference(set(str(k).strip().lower() for k in breakdown.keys())))
    if missing_dims:
        return _fail(3, f"[m44][P1] breakdown missing dimensions: {', '.join(missing_dims)}")

    for dim, value in breakdown.items():
        ok, v = _to_float(value)
        if not ok or v < 0.0 or v > 100.0:
            return _fail(3, f"[m44][P1] invalid breakdown value: {dim}={value!r}")

    gaps = readiness.get("gap_rank_topk")
    if not isinstance(gaps, list) or not gaps:
        return _fail(3, "[m44][P1] gap_rank_topk must be non-empty list")
    for idx, item in enumerate(gaps):
        if not isinstance(item, dict):
            return _fail(3, f"[m44][P1] gap_rank_topk[{idx}] must be object")
        dim = str(item.get("dimension", "")).strip()
        if not dim:
            return _fail(3, f"[m44][P1] gap_rank_topk[{idx}] missing dimension")
        ok_gap, gap = _to_float(item.get("gap"))
        if not ok_gap or gap < 0.0:
            return _fail(3, f"[m44][P1] gap_rank_topk[{idx}] invalid gap")

    conf = str(readiness.get("calibration_confidence", "")).strip().lower()
    if conf not in {"unverified", "low", "medium", "high"}:
        return _fail(3, f"[m44][P1] invalid calibration_confidence: {conf!r}")

    flags = readiness.get("regression_drift_flags")
    if not isinstance(flags, list):
        return _fail(3, "[m44][P1] regression_drift_flags must be list")
    for idx, flag in enumerate(flags):
        if not str(flag).strip():
            return _fail(3, f"[m44][P1] regression_drift_flags[{idx}] must be non-empty")

    prefix = f"[m44:{args.label}] " if args.label else "[m44] "
    print(
        f"{prefix}score_total={score:.3f} distance={dist:.3f} "
        f"target={target:.3f} top_gaps={len(gaps)} drift_flags={len(flags)}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
