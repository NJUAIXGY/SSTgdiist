#!/usr/bin/env python3
"""Validate M31 memory latency observability trends (simpleMem vs ramulator2).

M31 intent:
- Expose per-request memory latency signals so different backends/controllers
  can be calibrated (at least in terms of trend direction).
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
    """Return lhs_total/lhs_samples > rhs_total/rhs_samples (cross-multiplied)."""
    lhs_total, lhs_samples = lhs
    rhs_total, rhs_samples = rhs
    if lhs_samples <= 0 or rhs_samples <= 0:
        return False
    return (lhs_total * rhs_samples) > (rhs_total * lhs_samples)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simple", required=True, help="simpleMem backend summary json path")
    ap.add_argument("--ram2", required=True, help="ramulator2 backend summary json path")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    simple_path = Path(args.simple).expanduser().resolve()
    ram2_path = Path(args.ram2).expanduser().resolve()
    if not simple_path.exists():
        return _fail(2, f"[m31][P0] missing --simple summary: {simple_path}")
    if not ram2_path.exists():
        return _fail(2, f"[m31][P0] missing --ram2 summary: {ram2_path}")

    simple_t = _load_tensor(simple_path)
    ram2_t = _load_tensor(ram2_path)
    if simple_t is None or ram2_t is None:
        return _fail(2, "[m31][P0] invalid summary schema: missing tensor object")

    simple_bytes = _get_int(simple_t, "tensor_mem_bytes_read_total")
    ram2_bytes = _get_int(ram2_t, "tensor_mem_bytes_read_total")
    if simple_bytes <= 0 or ram2_bytes <= 0:
        return _fail(3, f"[m31][P1] expected mem_bytes_read_total > 0 (simple={simple_bytes}, ram2={ram2_bytes})")
    if simple_bytes != ram2_bytes:
        return _fail(3, f"[m31][P1] expected mem_bytes_read_total match (simple={simple_bytes}, ram2={ram2_bytes})")

    s_total = _get_int(simple_t, "tensor_mem_read_latency_cycles_total")
    s_max = _get_int(simple_t, "tensor_mem_read_latency_cycles_max")
    s_samples = _get_int(simple_t, "tensor_mem_read_latency_samples_total")
    r_total = _get_int(ram2_t, "tensor_mem_read_latency_cycles_total")
    r_max = _get_int(ram2_t, "tensor_mem_read_latency_cycles_max")
    r_samples = _get_int(ram2_t, "tensor_mem_read_latency_samples_total")

    if s_samples <= 0 or r_samples <= 0:
        return _fail(
            3,
            "[m31][P1] expected mem_read_latency_samples_total > 0 "
            f"(simple={s_samples}, ram2={r_samples})",
        )
    if s_total <= 0 or r_total <= 0:
        return _fail(
            3,
            "[m31][P1] expected mem_read_latency_cycles_total > 0 "
            f"(simple={s_total}, ram2={r_total})",
        )

    if not _avg_strictly_greater((r_total, r_samples), (s_total, s_samples)):
        return _fail(
            3,
            "[m31][P1] expected avg mem read latency(ram2) > simple "
            f"(simple_avg={_avg(s_total, s_samples):.3f}, ram2_avg={_avg(r_total, r_samples):.3f})",
        )
    if r_max < s_max:
        return _fail(3, f"[m31][P1] expected mem_read_latency_cycles_max(ram2) >= simple (simple={s_max}, ram2={r_max})")

    prefix = f"[m31:{args.label}] " if args.label else "[m31] "
    print(f"{prefix}mem_bytes_read_total: {simple_bytes}")
    print(f"{prefix}mem_read_latency_avg: simple={_avg(s_total, s_samples):.3f} ram2={_avg(r_total, r_samples):.3f}")
    print(f"{prefix}mem_read_latency_max: simple={s_max} ram2={r_max}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

