#!/usr/bin/env python3
"""Validate M16 wavefront (fill/drain) trends.

M16 intent:
- When wavefront model is enabled, extra MXU cycles should be charged beyond
  the macs/peak-throughput baseline.
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
    ap.add_argument("--off", required=True, help="wavefront disabled summary json path")
    ap.add_argument("--on", required=True, help="wavefront enabled summary json path")
    ap.add_argument("--label", default="", help="optional baseline label (for logs)")
    args = ap.parse_args(argv)

    off_path = Path(args.off).expanduser().resolve()
    on_path = Path(args.on).expanduser().resolve()
    if not off_path.exists():
        return _fail(2, f"[m16][P0] missing --off summary: {off_path}")
    if not on_path.exists():
        return _fail(2, f"[m16][P0] missing --on summary: {on_path}")

    off_t = _load_tensor(off_path)
    on_t = _load_tensor(on_path)
    if off_t is None or on_t is None:
        return _fail(2, "[m16][P0] invalid summary schema: missing tensor object")

    off_mac = _get_int(off_t, "tensor_mac_ops_total")
    on_mac = _get_int(on_t, "tensor_mac_ops_total")
    if off_mac <= 0 or on_mac <= 0:
        return _fail(3, f"[m16][P1] expected mac_ops_total > 0 (off={off_mac}, on={on_mac})")

    off_wf = _get_int(off_t, "tensor_mxu_wavefront_cycles_total")
    on_wf = _get_int(on_t, "tensor_mxu_wavefront_cycles_total")
    if off_wf != 0:
        return _fail(3, f"[m16][P1] expected off wavefront_cycles_total == 0, got {off_wf}")
    if on_wf <= 0:
        return _fail(3, f"[m16][P1] expected on wavefront_cycles_total > 0, got {on_wf}")

    off_cc = _get_int(off_t, "tensor_compute_cycles_total")
    on_cc = _get_int(on_t, "tensor_compute_cycles_total")
    if on_cc <= off_cc:
        return _fail(3, f"[m16][P1] expected compute_cycles_total(on) > off (off={off_cc}, on={on_cc})")

    prefix = f"[m16:{args.label}] " if args.label else "[m16] "
    print(f"{prefix}compute_cycles_total: off={off_cc} on={on_cc}")
    print(f"{prefix}wavefront_cycles_total: off={off_wf} on={on_wf}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

