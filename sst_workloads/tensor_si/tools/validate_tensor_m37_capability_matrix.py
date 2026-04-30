#!/usr/bin/env python3
"""Validate M37 capability matrix scoring contract."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from tensor_readiness import build_readiness_assessment


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


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


def _load_effective_config(summary_path: Path) -> Dict[str, Any]:
    path = summary_path.parent / "effective_config.json"
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dimension_names(matrix: Dict[str, Any]) -> List[str]:
    dims = matrix.get("dimensions") if isinstance(matrix, dict) else None
    if not isinstance(dims, list):
        return []
    names: List[str] = []
    for item in dims:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        if not name:
            continue
        names.append(name)
    return names


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True, help="essential_summary_tensor_mesh.json path")
    ap.add_argument("--matrix", required=True, help="tensor capability matrix json path")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    summary_path = Path(args.summary).expanduser().resolve()
    matrix_path = Path(args.matrix).expanduser().resolve()

    if not summary_path.exists():
        return _fail(2, f"[m37][P0] missing --summary: {summary_path}")
    if not matrix_path.exists():
        return _fail(2, f"[m37][P0] missing --matrix: {matrix_path}")

    try:
        payload = _load_json(summary_path)
    except Exception as exc:
        return _fail(2, f"[m37][P0] cannot parse summary json: {exc}")
    if not isinstance(payload, dict):
        return _fail(2, "[m37][P0] summary root must be object")

    try:
        matrix = _load_json(matrix_path)
    except Exception as exc:
        return _fail(2, f"[m37][P0] cannot parse matrix json: {exc}")
    if not isinstance(matrix, dict):
        return _fail(2, "[m37][P0] matrix root must be object")

    dims = _dimension_names(matrix)
    if len(dims) < 5:
        return _fail(3, f"[m37][P1] expected >=5 capability dimensions in matrix (got {len(dims)})")

    tensor = payload.get("tensor")
    if not isinstance(tensor, dict):
        return _fail(3, "[m37][P1] missing tensor object in summary")

    readiness = payload.get("npu_tpu_readiness")
    if not isinstance(readiness, dict):
        readiness = build_readiness_assessment(tensor, effective_cfg=_load_effective_config(summary_path), matrix=matrix)

    total_ok, total = _to_float(readiness.get("capability_score_total"))
    if not total_ok:
        return _fail(3, "[m37][P1] invalid capability_score_total")
    if total < 0.0 or total > 100.0:
        return _fail(3, f"[m37][P1] capability_score_total out of range [0,100]: {total}")

    breakdown = readiness.get("capability_score_breakdown")
    if not isinstance(breakdown, dict):
        return _fail(3, "[m37][P1] missing capability_score_breakdown")

    for name in dims:
        ok, value = _to_float(breakdown.get(name))
        if not ok:
            return _fail(3, f"[m37][P1] missing or invalid breakdown score: {name}")
        if value < 0.0 or value > 100.0:
            return _fail(3, f"[m37][P1] breakdown score out of range [0,100]: {name}={value}")

    dist_ok, dist = _to_float(readiness.get("distance_to_target"))
    if not dist_ok or dist < 0.0:
        return _fail(3, f"[m37][P1] invalid distance_to_target: {readiness.get('distance_to_target')}")

    topk = readiness.get("gap_rank_topk")
    if not isinstance(topk, list) or not topk:
        return _fail(3, "[m37][P1] gap_rank_topk must be a non-empty list")
    if len(topk) > 3:
        return _fail(3, f"[m37][P1] gap_rank_topk expected <=3 entries (got {len(topk)})")

    prev_gap = float("inf")
    for i, item in enumerate(topk):
        if not isinstance(item, dict):
            return _fail(3, f"[m37][P1] gap_rank_topk[{i}] must be object")
        name = str(item.get("dimension", "")).strip().lower()
        if not name:
            return _fail(3, f"[m37][P1] gap_rank_topk[{i}] missing dimension")
        ok_gap, gap = _to_float(item.get("gap"))
        if not ok_gap or gap < 0.0:
            return _fail(3, f"[m37][P1] gap_rank_topk[{i}] invalid gap")
        if gap > prev_gap + 1e-9:
            return _fail(3, "[m37][P1] gap_rank_topk must be sorted by descending gap")
        prev_gap = gap

    conf = str(readiness.get("calibration_confidence", "")).strip().lower()
    if conf not in {"unverified", "low", "medium", "high"}:
        return _fail(3, f"[m37][P1] invalid calibration_confidence: {conf!r}")

    flags = readiness.get("regression_drift_flags")
    if not isinstance(flags, list):
        return _fail(3, "[m37][P1] regression_drift_flags must be list")

    # If flattened score exists, ensure consistency.
    if "tensor_capability_score_total" in tensor:
        flat_ok, flat_total = _to_float(tensor.get("tensor_capability_score_total"))
        if flat_ok and abs(flat_total - total) > 1e-6:
            return _fail(3, f"[m37][P1] flattened total mismatch: tensor={flat_total} readiness={total}")

    prefix = f"[m37:{args.label}] " if args.label else "[m37] "
    print(f"{prefix}score_total={total:.3f} distance_to_target={dist:.3f}")
    print(f"{prefix}breakdown={{{', '.join(f'{k}:{breakdown.get(k)}' for k in dims)}}}")
    print(f"{prefix}gap_rank_topk={len(topk)} calibration_confidence={conf} drift_flags={len(flags)}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
