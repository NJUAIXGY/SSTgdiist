#!/usr/bin/env python3
"""Validate M35 mapping match vs mismatch trends using memory latency signals.

M35 intent:
- Use a minimal, controllable proxy for "mapping quality": address interleave policy.
- A hotspot (coarse interleave) should increase average memory read latency and slow DMA completion
  relative to a spread (fine interleave) mapping.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_int(d: Dict[str, Any], key: str) -> int:
    try:
        return int(d.get(key, 0) or 0)
    except Exception:
        return 0


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _load_tensor(summary_path: Path) -> Dict[str, Any] | None:
    try:
        obj = _load_json(summary_path)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    t = obj.get("tensor", {})
    return t if isinstance(t, dict) else None


def _avg(total: int, samples: int) -> float:
    if samples <= 0:
        return 0.0
    return float(total) / float(samples)


def _avg_strictly_greater(lhs: Tuple[int, int], rhs: Tuple[int, int]) -> bool:
    lhs_total, lhs_samples = lhs
    rhs_total, rhs_samples = rhs
    if lhs_samples <= 0 or rhs_samples <= 0:
        return False
    return (lhs_total * rhs_samples) > (rhs_total * lhs_samples)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hot", required=True, help="hotspot mapping summary json path (coarse interleave)")
    ap.add_argument("--spread", required=True, help="spread mapping summary json path (fine interleave)")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    hot_path = Path(args.hot).expanduser().resolve()
    spr_path = Path(args.spread).expanduser().resolve()
    if not hot_path.exists():
        return _fail(2, f"[m35][P0] missing --hot summary: {hot_path}")
    if not spr_path.exists():
        return _fail(2, f"[m35][P0] missing --spread summary: {spr_path}")

    hot_t = _load_tensor(hot_path)
    spr_t = _load_tensor(spr_path)
    if hot_t is None or spr_t is None:
        return _fail(2, "[m35][P0] invalid summary schema: missing tensor object")

    hot_iters = _get_int(hot_t, "tensor_program_iters_total")
    spr_iters = _get_int(spr_t, "tensor_program_iters_total")
    if hot_iters <= 0 or spr_iters <= 0:
        return _fail(3, f"[m35][P1] expected program_iters_total > 0 (hot={hot_iters}, spread={spr_iters})")

    hot_bytes = _get_int(hot_t, "tensor_mem_bytes_read_total")
    spr_bytes = _get_int(spr_t, "tensor_mem_bytes_read_total")
    if hot_bytes <= 0 or spr_bytes <= 0:
        return _fail(3, f"[m35][P1] expected mem_bytes_read_total > 0 (hot={hot_bytes}, spread={spr_bytes})")
    if hot_bytes != spr_bytes:
        return _fail(3, f"[m35][P1] expected mem_bytes_read_total match (hot={hot_bytes}, spread={spr_bytes})")

    hot_lat_total = _get_int(hot_t, "tensor_mem_read_latency_cycles_total")
    hot_lat_max = _get_int(hot_t, "tensor_mem_read_latency_cycles_max")
    hot_lat_samples = _get_int(hot_t, "tensor_mem_read_latency_samples_total")
    spr_lat_total = _get_int(spr_t, "tensor_mem_read_latency_cycles_total")
    spr_lat_max = _get_int(spr_t, "tensor_mem_read_latency_cycles_max")
    spr_lat_samples = _get_int(spr_t, "tensor_mem_read_latency_samples_total")

    if hot_lat_samples <= 0 or spr_lat_samples <= 0:
        return _fail(
            3,
            "[m35][P1] expected mem_read_latency_samples_total > 0 "
            f"(hot={hot_lat_samples}, spread={spr_lat_samples})",
        )
    if hot_lat_total <= 0 or spr_lat_total <= 0:
        return _fail(
            3,
            "[m35][P1] expected mem_read_latency_cycles_total > 0 "
            f"(hot={hot_lat_total}, spread={spr_lat_total})",
        )
    if not _avg_strictly_greater((hot_lat_total, hot_lat_samples), (spr_lat_total, spr_lat_samples)):
        return _fail(
            3,
            "[m35][P1] expected avg mem read latency(hot) > spread "
            f"(hot_avg={_avg(hot_lat_total, hot_lat_samples):.3f}, spread_avg={_avg(spr_lat_total, spr_lat_samples):.3f})",
        )

    hot_dma = _get_int(hot_t, "tensor_program_dma_busy_cycles_total")
    spr_dma = _get_int(spr_t, "tensor_program_dma_busy_cycles_total")
    if hot_dma <= 0 or spr_dma <= 0:
        return _fail(3, f"[m35][P1] expected program_dma_busy_cycles_total > 0 (hot={hot_dma}, spread={spr_dma})")
    if hot_dma <= spr_dma:
        return _fail(3, f"[m35][P1] expected program_dma_busy(hot) > spread (hot={hot_dma}, spread={spr_dma})")

    prefix = f"[m35:{args.label}] " if args.label else "[m35] "
    print(f"{prefix}mem_bytes_read_total: {hot_bytes}")
    print(
        f"{prefix}mem_read_latency_avg: hot={_avg(hot_lat_total, hot_lat_samples):.3f} "
        f"spread={_avg(spr_lat_total, spr_lat_samples):.3f}"
    )
    print(f"{prefix}program_dma_busy_cycles_total: hot={hot_dma} spread={spr_dma}")
    # Best-effort visibility; do not hard-fail on max due to potential noise.
    print(f"{prefix}mem_read_latency_max: hot={hot_lat_max} spread={spr_lat_max}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

