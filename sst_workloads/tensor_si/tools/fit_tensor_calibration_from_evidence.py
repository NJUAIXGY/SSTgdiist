#!/usr/bin/env python3
"""Build M52 evidence calibration profile from baseline/target summaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


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


def _avg(total: float, samples: float) -> float:
    if samples <= 0.0:
        return 0.0
    return float(total) / float(samples)


def _load_tensor(summary: Path) -> Dict[str, Any]:
    payload = _load_json(summary)
    if not isinstance(payload, dict):
        raise ValueError("summary root must be object")
    tensor = payload.get("tensor")
    if not isinstance(tensor, dict):
        raise ValueError("summary missing tensor object")
    return tensor


def _metric_value(metric: str, source: Dict[str, Any]) -> float:
    if metric in source:
        return _to_float(source.get(metric), 0.0)
    if metric == "tensor_mem_read_latency_cycles_avg":
        total = _to_float(source.get("tensor_mem_read_latency_cycles_total"), 0.0)
        samples = _to_float(source.get("tensor_mem_read_latency_samples_total"), 0.0)
        return _avg(total, samples)
    if metric == "tensor_mem_write_latency_cycles_avg":
        total = _to_float(source.get("tensor_mem_write_latency_cycles_total"), 0.0)
        samples = _to_float(source.get("tensor_mem_write_latency_samples_total"), 0.0)
        return _avg(total, samples)
    return 0.0


def _range_error(value: float, lo: float, hi: float) -> float:
    low = min(lo, hi)
    high = max(lo, hi)
    width = max(high - low, 1e-9)
    if low <= value <= high:
        return 0.0
    if value < low:
        return float(low - value) / float(width)
    return float(value - high) / float(width)


def build_profile(*, baseline: Path, target: Path, reference: Path, tag: str) -> Dict[str, Any]:
    base_t = _load_tensor(baseline)
    targ_t = _load_tensor(target)
    ref = _load_json(reference)
    if not isinstance(ref, dict):
        raise ValueError("reference root must be object")

    metrics = ref.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("reference.metrics must be non-empty object")

    read_base = _metric_value("tensor_mem_read_latency_cycles_avg", base_t)
    read_targ = _metric_value("tensor_mem_read_latency_cycles_avg", targ_t)
    dma_base = _metric_value("tensor_program_dma_busy_cycles_total", base_t)
    dma_targ = _metric_value("tensor_program_dma_busy_cycles_total", targ_t)

    read_scale = (read_targ / read_base) if read_base > 1e-12 else 1.0
    dma_scale = (dma_targ / dma_base) if dma_base > 1e-12 else 1.0
    bw_scale = (1.0 / dma_scale) if dma_scale > 1e-12 else 1.0

    detail: Dict[str, Dict[str, float]] = {}
    err_weighted = 0.0
    weight_total = 0.0
    for name, cfg in metrics.items():
        if not isinstance(cfg, dict):
            continue
        source_name = str(cfg.get("source", "target")).strip().lower()
        src = base_t if source_name == "baseline" else targ_t
        val = _metric_value(str(name), src)
        lo = _to_float(cfg.get("expected_min"), 0.0)
        hi = _to_float(cfg.get("expected_max"), 0.0)
        w = max(0.0, _to_float(cfg.get("weight"), 1.0))
        err = _range_error(val, lo, hi)
        detail[str(name)] = {
            "source": 0.0 if source_name == "baseline" else 1.0,
            "value": round(val, 6),
            "expected_min": round(min(lo, hi), 6),
            "expected_max": round(max(lo, hi), 6),
            "error": round(err, 6),
            "weight": round(w, 6),
        }
        err_weighted += err * w
        weight_total += w

    error_score = (err_weighted / weight_total) if weight_total > 1e-12 else 0.0

    conf_rules = ref.get("confidence_rules") if isinstance(ref.get("confidence_rules"), dict) else {}
    high_max = max(0.0, _to_float(conf_rules.get("high_max_error"), 0.15))
    medium_max = max(high_max, _to_float(conf_rules.get("medium_max_error"), 0.35))

    if error_score <= high_max:
        confidence = "high"
    elif error_score <= medium_max:
        confidence = "medium"
    else:
        confidence = "low"

    status = "pass" if error_score <= medium_max else "fail"

    return {
        "schema_version": 1,
        "calibration_tag": str(tag).strip() or "m52_evidence_v1",
        "reference_id": str(ref.get("reference_id", "tensor_m52_reference_v1")).strip() or "tensor_m52_reference_v1",
        "inputs": {
            "baseline_summary": str(baseline),
            "target_summary": str(target),
            "reference_profile": str(reference),
        },
        "factors": {
            "read_latency_scale": round(read_scale, 6),
            "dma_busy_scale": round(dma_scale, 6),
            "suggested_mem_bandwidth_scale": round(bw_scale, 6),
        },
        "evidence": {
            "error_score": round(error_score, 6),
            "metrics": detail,
            "status": status,
        },
        "confidence": confidence,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, help="baseline summary json")
    ap.add_argument("--target", required=True, help="target summary json")
    ap.add_argument("--reference", required=True, help="reference profile json")
    ap.add_argument("--out", required=True, help="output evidence profile json")
    ap.add_argument("--tag", default="m52_evidence_v1", help="calibration tag")
    args = ap.parse_args(argv)

    baseline_p = Path(args.baseline).expanduser().resolve()
    target_p = Path(args.target).expanduser().resolve()
    ref_p = Path(args.reference).expanduser().resolve()
    out_p = Path(args.out).expanduser().resolve()

    for p, flag in ((baseline_p, "--baseline"), (target_p, "--target"), (ref_p, "--reference")):
        if not p.exists():
            print(f"[m52][P0] missing {flag}: {p}", file=sys.stderr)
            return 2

    try:
        profile = build_profile(baseline=baseline_p, target=target_p, reference=ref_p, tag=args.tag)
    except Exception as exc:
        print(f"[m52][P0] build evidence profile failed: {exc}", file=sys.stderr)
        return 2

    try:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[m52][P0] write profile failed: {exc}", file=sys.stderr)
        return 2

    print(f"[m52] evidence_profile: {out_p}")
    print(
        "[m52] factors: "
        f"read_latency_scale={profile['factors']['read_latency_scale']} "
        f"dma_busy_scale={profile['factors']['dma_busy_scale']} "
        f"suggested_mem_bandwidth_scale={profile['factors']['suggested_mem_bandwidth_scale']}"
    )
    print(
        f"[m52] evidence_status={profile['evidence']['status']} "
        f"error_score={profile['evidence']['error_score']} confidence={profile['confidence']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
