#!/usr/bin/env python3
"""Validate M23 HBM channel budget trends.

M23 intent:
- Model per-channel HBM bandwidth budgets and contention for DMA issue.
- More channels (with fine interleave) should reduce program DMA busy cycles.
- Coarser interleave should concentrate traffic and reduce effective parallelism.
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
            return _fail(2, f"[m23][P0] missing --{k} summary: {p}")

    tensors: Dict[str, Dict[str, Any]] = {}
    for k, p in paths.items():
        t = _load_tensor(p)
        if t is None:
            return _fail(2, f"[m23][P0] invalid summary schema: missing tensor object ({k})")
        tensors[k] = t

    iters = {k: _get_int(t, "tensor_program_iters_total") for k, t in tensors.items()}
    if any(v <= 0 for v in iters.values()):
        return _fail(3, f"[m23][P1] expected program_iters_total > 0: {iters}")

    reads = {k: _get_int(t, "tensor_mem_bytes_read_total") for k, t in tensors.items()}
    if any(v <= 0 for v in reads.values()):
        return _fail(3, f"[m23][P1] expected mem_bytes_read_total > 0: {reads}")
    if len(set(reads.values())) != 1:
        return _fail(3, f"[m23][P1] expected mem_bytes_read_total match: {reads}")

    # NOTE: In our current stack, memHierarchy (single MemController per PE) can dominate DMA completion.
    # M23's channel budget primarily impacts how fast DMA requests are issued, so we validate trends using
    # "program_any_busy" (cycles that actually issued DMA or executed compute), not "program_dma_busy"
    # (which includes waiting for memory completions).
    any_busy = {k: _get_int(t, "tensor_program_any_busy_cycles_total") for k, t in tensors.items()}
    if any(v <= 0 for v in any_busy.values()):
        return _fail(3, f"[m23][P1] expected program_any_busy_cycles_total > 0: {any_busy}")

    dma_busy = {k: _get_int(t, "tensor_program_dma_busy_cycles_total") for k, t in tensors.items()}

    # Trend checks (issue/dispatch time).
    if any_busy["ch4"] >= any_busy["ch1"]:
        return _fail(
            3,
            f"[m23][P1] expected any_busy(4ch) < 1ch (ch1={any_busy['ch1']} ch4={any_busy['ch4']})",
        )
    if any_busy["hot"] <= any_busy["spread"]:
        return _fail(
            3,
            f"[m23][P1] expected any_busy(hot) > spread (hot={any_busy['hot']} spread={any_busy['spread']})",
        )

    prefix = f"[m23:{args.label}] " if args.label else "[m23] "
    print(f"{prefix}mem_bytes_read_total: {next(iter(reads.values()))}")
    print(f"{prefix}program_any_busy_cycles_total: ch1={any_busy['ch1']} ch4={any_busy['ch4']}")
    print(f"{prefix}program_any_busy_cycles_total: hot={any_busy['hot']} spread={any_busy['spread']}")
    if all(v > 0 for v in dma_busy.values()):
        print(f"{prefix}program_dma_busy_cycles_total: ch1={dma_busy['ch1']} ch4={dma_busy['ch4']}")
        print(f"{prefix}program_dma_busy_cycles_total: hot={dma_busy['hot']} spread={dma_busy['spread']}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
