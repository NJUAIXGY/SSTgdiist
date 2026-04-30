#!/usr/bin/env python3
"""Validate M24 memHierarchy multi-channel (MemController) trends.

M24 intent:
- When tensor_dma_hbm_channels>1 is enabled, the tensor mesh should build a
  multi-MemController memory system per PE and the workload should stripe
  addresses (interleave) so traffic spreads across channels.
- With more channels (fine interleave), program DMA completion should improve.
- With coarse interleave (hotspot), effective parallelism should drop.
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
    ap.add_argument("--ch1", required=True, help="1-channel summary json path")
    ap.add_argument("--ch4", required=True, help="4-channel summary json path (fine interleave)")
    ap.add_argument("--hot", required=True, help="hot interleave summary json path (coarse interleave)")
    ap.add_argument("--spread", required=True, help="spread interleave summary json path (fine interleave)")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    paths = {
        "ch1": Path(args.ch1).expanduser().resolve(),
        "ch4": Path(args.ch4).expanduser().resolve(),
        "hot": Path(args.hot).expanduser().resolve(),
        "spread": Path(args.spread).expanduser().resolve(),
    }
    for k, p in paths.items():
        if not p.exists():
            return _fail(2, f"[m24][P0] missing --{k} summary: {p}")

    tensors: Dict[str, Dict[str, Any]] = {}
    for k, p in paths.items():
        t = _load_tensor(p)
        if t is None:
            return _fail(2, f"[m24][P0] invalid summary schema: missing tensor object ({k})")
        tensors[k] = t

    iters = {k: _get_int(t, "tensor_program_iters_total") for k, t in tensors.items()}
    if any(v <= 0 for v in iters.values()):
        return _fail(3, f"[m24][P1] expected program_iters_total > 0: {iters}")

    reads = {k: _get_int(t, "tensor_mem_bytes_read_total") for k, t in tensors.items()}
    if any(v <= 0 for v in reads.values()):
        return _fail(3, f"[m24][P1] expected mem_bytes_read_total > 0: {reads}")
    if len(set(reads.values())) != 1:
        return _fail(3, f"[m24][P1] expected mem_bytes_read_total match: {reads}")

    dma_busy = {k: _get_int(t, "tensor_program_dma_busy_cycles_total") for k, t in tensors.items()}
    if any(v <= 0 for v in dma_busy.values()):
        return _fail(3, f"[m24][P1] expected program_dma_busy_cycles_total > 0: {dma_busy}")

    if dma_busy["ch4"] >= dma_busy["ch1"]:
        return _fail(
            3,
            f"[m24][P1] expected dma_busy(4ch) < 1ch (ch1={dma_busy['ch1']} ch4={dma_busy['ch4']})",
        )
    if dma_busy["hot"] <= dma_busy["spread"]:
        return _fail(
            3,
            f"[m24][P1] expected dma_busy(hot) > spread (hot={dma_busy['hot']} spread={dma_busy['spread']})",
        )

    prefix = f"[m24:{args.label}] " if args.label else "[m24] "
    print(f"{prefix}mem_bytes_read_total: {next(iter(reads.values()))}")
    print(f"{prefix}program_dma_busy_cycles_total: ch1={dma_busy['ch1']} ch4={dma_busy['ch4']}")
    print(f"{prefix}program_dma_busy_cycles_total: hot={dma_busy['hot']} spread={dma_busy['spread']}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

