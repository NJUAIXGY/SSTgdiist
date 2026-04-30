#!/usr/bin/env python3
"""Validate M15 residency semantics trends (keep-a/keep-b).

M15 intent (TPU-like scratchpad residency):
- keep-a (IS + schedule=mkn): A tile should be resident across the inner N sweep.
- keep-b (WS + schedule=nkm): B tile should be resident across the inner M sweep.

We validate via observability stats exported by TensorWorkload:
- tensor_onchip_a_resident_tiles_max
- tensor_onchip_b_resident_tiles_max
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
    ap.add_argument("--keep-a-on", required=True, help="keep-a enabled summary json path")
    ap.add_argument("--keep-a-off", required=True, help="keep-a disabled summary json path")
    ap.add_argument("--keep-b-on", required=True, help="keep-b enabled summary json path")
    ap.add_argument("--keep-b-off", required=True, help="keep-b disabled summary json path")
    ap.add_argument("--label", default="", help="optional baseline label (for logs)")
    args = ap.parse_args(argv)

    paths = {
        "keep_a_on": Path(args.keep_a_on).expanduser().resolve(),
        "keep_a_off": Path(args.keep_a_off).expanduser().resolve(),
        "keep_b_on": Path(args.keep_b_on).expanduser().resolve(),
        "keep_b_off": Path(args.keep_b_off).expanduser().resolve(),
    }
    for k, p in paths.items():
        if not p.exists():
            return _fail(2, f"[m15][P0] missing {k} summary: {p}")

    tensors: Dict[str, Dict[str, Any]] = {}
    for k, p in paths.items():
        t = _load_tensor(p)
        if t is None:
            return _fail(2, f"[m15][P0] invalid summary schema (missing tensor object): {p}")
        tensors[k] = t

    # Sanity: MACs should be non-zero in all scenarios.
    for k, t in tensors.items():
        mac = _get_int(t, "tensor_mac_ops_total")
        if mac <= 0:
            return _fail(3, f"[m15][P1] expected mac_ops_total > 0 for {k}, got {mac}")

    a_on = _get_int(tensors["keep_a_on"], "tensor_onchip_a_resident_tiles_max")
    a_off = _get_int(tensors["keep_a_off"], "tensor_onchip_a_resident_tiles_max")
    if a_on <= 0:
        return _fail(3, f"[m15][P1] expected keep-a-on a_resident_tiles_max > 0, got {a_on}")
    if a_off != 0:
        return _fail(3, f"[m15][P1] expected keep-a-off a_resident_tiles_max == 0, got {a_off}")

    b_on = _get_int(tensors["keep_b_on"], "tensor_onchip_b_resident_tiles_max")
    b_off = _get_int(tensors["keep_b_off"], "tensor_onchip_b_resident_tiles_max")
    if b_on <= 0:
        return _fail(3, f"[m15][P1] expected keep-b-on b_resident_tiles_max > 0, got {b_on}")
    if b_off != 0:
        return _fail(3, f"[m15][P1] expected keep-b-off b_resident_tiles_max == 0, got {b_off}")

    prefix = f"[m15:{args.label}] " if args.label else "[m15] "
    print(f"{prefix}a_resident_tiles_max(on)={a_on} off={a_off}")
    print(f"{prefix}b_resident_tiles_max(on)={b_on} off={b_off}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

