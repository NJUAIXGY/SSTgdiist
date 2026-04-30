#!/usr/bin/env python3
"""Validate M29 program-mode DMA microarchitecture trends.

M29 intent:
- Add basic DMA microarchitecture knobs (burst/setup/engines/inflight) that
  affect program-mode DMA completion time while keeping total bytes constant.
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
    ap.add_argument("--slow", required=True, help="slow DMA summary json path")
    ap.add_argument("--fast", required=True, help="fast DMA summary json path")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    slow_path = Path(args.slow).expanduser().resolve()
    fast_path = Path(args.fast).expanduser().resolve()
    if not slow_path.exists():
        return _fail(2, f"[m29][P0] missing --slow summary: {slow_path}")
    if not fast_path.exists():
        return _fail(2, f"[m29][P0] missing --fast summary: {fast_path}")

    slow_t = _load_tensor(slow_path)
    fast_t = _load_tensor(fast_path)
    if slow_t is None or fast_t is None:
        return _fail(2, "[m29][P0] invalid summary schema: missing tensor object")

    slow_iters = _get_int(slow_t, "tensor_program_iters_total")
    fast_iters = _get_int(fast_t, "tensor_program_iters_total")
    if slow_iters <= 0 or fast_iters <= 0:
        return _fail(3, f"[m29][P1] expected program_iters_total > 0 (slow={slow_iters}, fast={fast_iters})")

    slow_r = _get_int(slow_t, "tensor_mem_bytes_read_total")
    fast_r = _get_int(fast_t, "tensor_mem_bytes_read_total")
    if slow_r <= 0 or fast_r <= 0:
        return _fail(3, f"[m29][P1] expected mem_bytes_read_total > 0 (slow={slow_r}, fast={fast_r})")
    if slow_r != fast_r:
        return _fail(3, f"[m29][P1] expected mem_bytes_read_total match (slow={slow_r}, fast={fast_r})")

    slow_dma = _get_int(slow_t, "tensor_program_dma_busy_cycles_total")
    fast_dma = _get_int(fast_t, "tensor_program_dma_busy_cycles_total")
    if slow_dma <= 0 or fast_dma <= 0:
        return _fail(3, f"[m29][P1] expected dma_busy_cycles_total > 0 (slow={slow_dma}, fast={fast_dma})")
    if slow_dma <= fast_dma:
        return _fail(3, f"[m29][P1] expected dma_busy(slow) > fast (slow={slow_dma}, fast={fast_dma})")

    prefix = f"[m29:{args.label}] " if args.label else "[m29] "
    print(f"{prefix}mem_bytes_read_total: {slow_r}")
    print(f"{prefix}program_dma_busy_cycles_total: slow={slow_dma} fast={fast_dma}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

