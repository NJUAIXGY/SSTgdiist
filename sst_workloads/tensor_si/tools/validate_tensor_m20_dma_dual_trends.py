#!/usr/bin/env python3
"""Validate M20 program-mode DMA dual-engine trends.

M20 intent:
- Allow 1 DMA read + 1 DMA write to overlap in program mode, reducing overall
  busy cycles for schedules that prefetch inputs while writing back outputs.
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
    ap.add_argument("--off", required=True, help="dual disabled summary json path")
    ap.add_argument("--on", required=True, help="dual enabled summary json path")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    off_path = Path(args.off).expanduser().resolve()
    on_path = Path(args.on).expanduser().resolve()
    if not off_path.exists():
        return _fail(2, f"[m20][P0] missing --off summary: {off_path}")
    if not on_path.exists():
        return _fail(2, f"[m20][P0] missing --on summary: {on_path}")

    off_t = _load_tensor(off_path)
    on_t = _load_tensor(on_path)
    if off_t is None or on_t is None:
        return _fail(2, "[m20][P0] invalid summary schema: missing tensor object")

    off_iters = _get_int(off_t, "tensor_program_iters_total")
    on_iters = _get_int(on_t, "tensor_program_iters_total")
    if off_iters <= 0 or on_iters <= 0:
        return _fail(3, f"[m20][P1] expected program_iters_total > 0 (off={off_iters}, on={on_iters})")

    off_cc = _get_int(off_t, "tensor_compute_cycles_total")
    on_cc = _get_int(on_t, "tensor_compute_cycles_total")
    if off_cc <= 0 or on_cc <= 0:
        return _fail(3, f"[m20][P1] expected compute_cycles_total > 0 (off={off_cc}, on={on_cc})")
    if off_cc != on_cc:
        return _fail(3, f"[m20][P1] expected compute_cycles_total match (off={off_cc}, on={on_cc})")

    off_r = _get_int(off_t, "tensor_mem_bytes_read_total")
    on_r = _get_int(on_t, "tensor_mem_bytes_read_total")
    off_w = _get_int(off_t, "tensor_mem_bytes_write_total")
    on_w = _get_int(on_t, "tensor_mem_bytes_write_total")
    if off_r <= 0 or off_w <= 0 or on_r <= 0 or on_w <= 0:
        return _fail(3, f"[m20][P1] expected mem bytes > 0 (off_r={off_r} off_w={off_w} on_r={on_r} on_w={on_w})")
    if off_r != on_r or off_w != on_w:
        return _fail(3, f"[m20][P1] expected mem bytes match (off_r={off_r} off_w={off_w}; on_r={on_r} on_w={on_w})")

    off_dma = _get_int(off_t, "tensor_program_dma_busy_cycles_total")
    on_dma = _get_int(on_t, "tensor_program_dma_busy_cycles_total")
    if off_dma <= 0 or on_dma <= 0:
        return _fail(3, f"[m20][P1] expected program_dma_busy_cycles_total > 0 (off={off_dma}, on={on_dma})")
    if on_dma >= off_dma:
        return _fail(3, f"[m20][P1] expected dma_busy(on) < off (off={off_dma}, on={on_dma})")

    prefix = f"[m20:{args.label}] " if args.label else "[m20] "
    print(f"{prefix}compute_cycles_total: {off_cc}")
    print(f"{prefix}mem_bytes_read_total: {off_r}")
    print(f"{prefix}mem_bytes_write_total: {off_w}")
    print(f"{prefix}program_dma_busy_cycles_total: off={off_dma} on={on_dma}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
