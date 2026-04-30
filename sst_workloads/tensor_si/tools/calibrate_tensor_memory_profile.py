#!/usr/bin/env python3
"""Generate deterministic M41 memory calibration profile from two summaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        txt = str(value).strip()
        if not txt:
            return 0
        return int(float(txt))
    except Exception:
        return 0


def _avg(total: int, samples: int) -> float:
    if samples <= 0:
        return 0.0
    return float(total) / float(samples)


def _confidence(sample_total: int) -> str:
    if sample_total >= 128:
        return "high"
    if sample_total >= 32:
        return "medium"
    return "low"


def _load_tensor(path: Path) -> Dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("summary root must be object")
    tensor = payload.get("tensor")
    if not isinstance(tensor, dict):
        raise ValueError("missing tensor object")
    return tensor


def build_profile(*, baseline: Path, target: Path, tag: str) -> Dict[str, Any]:
    base_t = _load_tensor(baseline)
    targ_t = _load_tensor(target)

    base_read_total = _to_int(base_t.get("tensor_mem_read_latency_cycles_total"))
    base_read_samples = _to_int(base_t.get("tensor_mem_read_latency_samples_total"))
    targ_read_total = _to_int(targ_t.get("tensor_mem_read_latency_cycles_total"))
    targ_read_samples = _to_int(targ_t.get("tensor_mem_read_latency_samples_total"))

    base_dma_busy = _to_int(base_t.get("tensor_program_dma_busy_cycles_total"))
    targ_dma_busy = _to_int(targ_t.get("tensor_program_dma_busy_cycles_total"))

    base_avg = _avg(base_read_total, base_read_samples)
    targ_avg = _avg(targ_read_total, targ_read_samples)

    if base_avg > 0.0 and targ_avg > 0.0:
        read_scale = targ_avg / base_avg
    else:
        read_scale = 1.0

    if base_dma_busy > 0 and targ_dma_busy > 0:
        dma_scale = float(targ_dma_busy) / float(base_dma_busy)
    else:
        dma_scale = 1.0

    bw_scale = 1.0 / dma_scale if dma_scale > 1e-12 else 1.0
    sample_total = max(0, base_read_samples) + max(0, targ_read_samples)

    suggested_profile = "server" if read_scale > 1.2 else "balanced"

    return {
        "schema_version": 1,
        "calibration_tag": str(tag).strip() or "m41_calib_v1",
        "inputs": {
            "baseline_summary": str(baseline),
            "target_summary": str(target),
        },
        "metrics": {
            "baseline_mem_read_latency_avg": round(base_avg, 6),
            "target_mem_read_latency_avg": round(targ_avg, 6),
            "baseline_program_dma_busy_cycles_total": int(base_dma_busy),
            "target_program_dma_busy_cycles_total": int(targ_dma_busy),
            "sample_total": int(sample_total),
        },
        "factors": {
            "read_latency_scale": round(read_scale, 6),
            "dma_busy_scale": round(dma_scale, 6),
            "suggested_mem_bandwidth_scale": round(bw_scale, 6),
        },
        "suggested_profile": suggested_profile,
        "confidence": _confidence(sample_total),
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, help="baseline summary path")
    ap.add_argument("--target", required=True, help="target summary path")
    ap.add_argument("--out", required=True, help="output calibration profile json")
    ap.add_argument("--tag", default="m41_calib_v1", help="calibration tag")
    args = ap.parse_args(argv)

    baseline = Path(args.baseline).expanduser().resolve()
    target = Path(args.target).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()

    if not baseline.exists():
        print(f"[m41][P0] missing --baseline summary: {baseline}", file=sys.stderr)
        return 2
    if not target.exists():
        print(f"[m41][P0] missing --target summary: {target}", file=sys.stderr)
        return 2

    try:
        profile = build_profile(baseline=baseline, target=target, tag=args.tag)
    except Exception as exc:
        print(f"[m41][P0] calibration build failed: {exc}", file=sys.stderr)
        return 2

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[m41][P0] write profile failed: {exc}", file=sys.stderr)
        return 2

    print(f"[m41] calibration_profile: {out}")
    print(
        "[m41] factors: "
        f"read_latency_scale={profile['factors']['read_latency_scale']} "
        f"dma_busy_scale={profile['factors']['dma_busy_scale']} "
        f"suggested_mem_bandwidth_scale={profile['factors']['suggested_mem_bandwidth_scale']}"
    )
    print(f"[m41] confidence={profile['confidence']} suggested_profile={profile['suggested_profile']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
