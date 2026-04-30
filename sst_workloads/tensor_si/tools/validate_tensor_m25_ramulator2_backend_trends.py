#!/usr/bin/env python3
"""Validate M25 ramulator2 backend trends.

M25 intent:
- Allow tensor mesh to select memHierarchy backend type: simpleMem vs ramulator2.
- With the same workload, ramulator2 should be (strictly) slower than simpleMem on DMA completion
  (program_dma_busy_cycles_total), since it models DRAM timing.
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


def _load_effective_mesh_cfg(summary_path: Path) -> Dict[str, Any]:
    eff = summary_path.parent / "effective_config.json"
    try:
        obj = _load_json(eff)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    mesh_cfg = obj.get("mesh_cfg", {})
    return mesh_cfg if isinstance(mesh_cfg, dict) else {}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simple", required=True, help="simple backend summary json path")
    ap.add_argument("--ram2", required=True, help="ramulator2 backend summary json path")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    paths = {
        "simple": Path(args.simple).expanduser().resolve(),
        "ram2": Path(args.ram2).expanduser().resolve(),
    }
    for k, p in paths.items():
        if not p.exists():
            return _fail(2, f"[m25][P0] missing --{k} summary: {p}")

    tensors: Dict[str, Dict[str, Any]] = {}
    for k, p in paths.items():
        t = _load_tensor(p)
        if t is None:
            return _fail(2, f"[m25][P0] invalid summary schema: missing tensor object ({k})")
        tensors[k] = t

    iters = {k: _get_int(t, "tensor_program_iters_total") for k, t in tensors.items()}
    if any(v <= 0 for v in iters.values()):
        return _fail(3, f"[m25][P1] expected program_iters_total > 0: {iters}")

    reads = {k: _get_int(t, "tensor_mem_bytes_read_total") for k, t in tensors.items()}
    if any(v <= 0 for v in reads.values()):
        return _fail(3, f"[m25][P1] expected mem_bytes_read_total > 0: {reads}")
    if len(set(reads.values())) != 1:
        return _fail(3, f"[m25][P1] expected mem_bytes_read_total match: {reads}")

    dma_busy = {k: _get_int(t, "tensor_program_dma_busy_cycles_total") for k, t in tensors.items()}
    if any(v <= 0 for v in dma_busy.values()):
        return _fail(3, f"[m25][P1] expected program_dma_busy_cycles_total > 0: {dma_busy}")

    mesh_simple = _load_effective_mesh_cfg(paths["simple"])
    mesh_ram2 = _load_effective_mesh_cfg(paths["ram2"])
    if mesh_simple.get("mem_backend") not in ("simple", "", None):
        return _fail(3, f"[m25][P1] expected simple run mem_backend='simple': got {mesh_simple.get('mem_backend')!r}")
    if mesh_ram2.get("mem_backend") != "ramulator2":
        return _fail(3, f"[m25][P1] expected ram2 run mem_backend='ramulator2': got {mesh_ram2.get('mem_backend')!r}")
    ram2_cfg = (mesh_ram2.get("mem_backend_params") or {}).get("configFile")
    if not str(ram2_cfg or "").strip():
        return _fail(3, "[m25][P1] expected ram2 run to record mem_backend_params.configFile")

    if dma_busy["ram2"] <= dma_busy["simple"]:
        return _fail(
            3,
            f"[m25][P1] expected dma_busy(ram2) > simple (simple={dma_busy['simple']} ram2={dma_busy['ram2']})",
        )

    prefix = f"[m25:{args.label}] " if args.label else "[m25] "
    print(f"{prefix}mem_bytes_read_total: {next(iter(reads.values()))}")
    print(f"{prefix}program_dma_busy_cycles_total: simple={dma_busy['simple']} ram2={dma_busy['ram2']}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

