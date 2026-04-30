#!/usr/bin/env python3
"""Validate M34 ramulator2 config -> auto MemController channel inference contract.

M34 intent:
- When using ramulator2 backend + an HBM-like config, tensor spec resolution should
  infer a sensible default tensor_dma_hbm_channels/interleave when the user omits them.
- The inferred defaults should be equivalent to explicitly setting the same values.
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


def _load_effective_tensor_cfg(summary_path: Path) -> Dict[str, Any]:
    eff = summary_path.parent / "effective_config.json"
    try:
        obj = _load_json(eff)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    cfg = obj.get("tensor_cfg", {})
    return cfg if isinstance(cfg, dict) else {}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--explicit", required=True, help="explicit 4ch summary json path")
    ap.add_argument("--auto", required=True, help="auto-inferred summary json path")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    explicit_path = Path(args.explicit).expanduser().resolve()
    auto_path = Path(args.auto).expanduser().resolve()
    if not explicit_path.exists():
        return _fail(2, f"[m34][P0] missing --explicit summary: {explicit_path}")
    if not auto_path.exists():
        return _fail(2, f"[m34][P0] missing --auto summary: {auto_path}")

    exp_t = _load_tensor(explicit_path)
    auto_t = _load_tensor(auto_path)
    if exp_t is None or auto_t is None:
        return _fail(2, "[m34][P0] invalid summary schema: missing tensor object")

    exp_r = _get_int(exp_t, "tensor_mem_bytes_read_total")
    auto_r = _get_int(auto_t, "tensor_mem_bytes_read_total")
    if exp_r <= 0 or auto_r <= 0:
        return _fail(3, f"[m34][P1] expected mem_bytes_read_total > 0 (explicit={exp_r}, auto={auto_r})")
    if exp_r != auto_r:
        return _fail(3, f"[m34][P1] expected mem_bytes_read_total match (explicit={exp_r}, auto={auto_r})")

    exp_dma = _get_int(exp_t, "tensor_program_dma_busy_cycles_total")
    auto_dma = _get_int(auto_t, "tensor_program_dma_busy_cycles_total")
    if exp_dma <= 0 or auto_dma <= 0:
        return _fail(3, f"[m34][P1] expected program_dma_busy_cycles_total > 0 (explicit={exp_dma}, auto={auto_dma})")
    if exp_dma != auto_dma:
        return _fail(3, f"[m34][P1] expected program_dma_busy_cycles_total match (explicit={exp_dma}, auto={auto_dma})")

    cfg = _load_effective_tensor_cfg(auto_path)
    if not cfg:
        return _fail(3, "[m34][P1] missing effective_config.json tensor_cfg for auto scenario")

    ch = _get_int(cfg, "tensor_dma_hbm_channels")
    interleave = _get_int(cfg, "tensor_dma_hbm_channel_interleave_bytes")
    if ch != 4:
        return _fail(3, f"[m34][P1] expected inferred tensor_dma_hbm_channels==4 (got {ch})")
    if interleave != 256:
        return _fail(3, f"[m34][P1] expected inferred tensor_dma_hbm_channel_interleave_bytes==256 (got {interleave})")

    prefix = f"[m34:{args.label}] " if args.label else "[m34] "
    print(f"{prefix}mem_bytes_read_total: {exp_r}")
    print(f"{prefix}program_dma_busy_cycles_total: {exp_dma}")
    print(f"{prefix}auto_inferred: tensor_dma_hbm_channels={ch} interleave_bytes={interleave}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

