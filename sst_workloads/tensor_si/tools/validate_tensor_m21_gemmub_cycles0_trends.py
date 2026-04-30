#!/usr/bin/env python3
"""Validate M21 gemm_ub cycles=0 auto-estimation trends.

M21 intent:
- Allow gemm_ub ops to specify cycles=0 and derive cycles at runtime from
  (m,n,k) and the current compute profile (array shape, throughput scale, etc.).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


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


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", required=True, help="fast compute config summary json path")
    ap.add_argument("--slow", required=True, help="slow compute config summary json path")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    fast_path = Path(args.fast).expanduser().resolve()
    slow_path = Path(args.slow).expanduser().resolve()
    if not fast_path.exists():
        return _fail(2, f"[m21][P0] missing --fast summary: {fast_path}")
    if not slow_path.exists():
        return _fail(2, f"[m21][P0] missing --slow summary: {slow_path}")

    fast_t = _load_tensor(fast_path)
    slow_t = _load_tensor(slow_path)
    if fast_t is None or slow_t is None:
        return _fail(2, "[m21][P0] invalid summary schema: missing tensor object")

    fast_iters = _get_int(fast_t, "tensor_program_iters_total")
    slow_iters = _get_int(slow_t, "tensor_program_iters_total")
    if fast_iters <= 0 or slow_iters <= 0:
        return _fail(3, f"[m21][P1] expected program_iters_total > 0 (fast={fast_iters}, slow={slow_iters})")

    fast_mxu = _get_int(fast_t, "tensor_program_mxu_busy_cycles_total")
    slow_mxu = _get_int(slow_t, "tensor_program_mxu_busy_cycles_total")
    if fast_mxu <= 0 or slow_mxu <= 0:
        return _fail(3, f"[m21][P1] expected program_mxu_busy_cycles_total > 0 (fast={fast_mxu}, slow={slow_mxu})")
    if slow_mxu <= fast_mxu:
        return _fail(3, f"[m21][P1] expected mxu_busy(slow) > fast (fast={fast_mxu}, slow={slow_mxu})")

    fast_cc = _get_int(fast_t, "tensor_compute_cycles_total")
    slow_cc = _get_int(slow_t, "tensor_compute_cycles_total")
    if fast_cc <= 0 or slow_cc <= 0:
        return _fail(3, f"[m21][P1] expected compute_cycles_total > 0 (fast={fast_cc}, slow={slow_cc})")
    if slow_cc <= fast_cc:
        return _fail(3, f"[m21][P1] expected compute_cycles_total(slow) > fast (fast={fast_cc}, slow={slow_cc})")

    prefix = f"[m21:{args.label}] " if args.label else "[m21] "
    print(f"{prefix}program_mxu_busy_cycles_total: fast={fast_mxu} slow={slow_mxu}")
    print(f"{prefix}compute_cycles_total: fast={fast_cc} slow={slow_cc}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

