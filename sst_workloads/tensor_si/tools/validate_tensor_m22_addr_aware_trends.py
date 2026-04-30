#!/usr/bin/env python3
"""Validate M22 program-mode address-aware UB region trends.

M22 intent:
- Program mode UB dependencies should become region/address aware via ub_addr /
  ub_read_addr / ub_write_addr, so reads/writes target specific UB regions rather
  than a single bytes-only scratchpad.
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
    ap.add_argument("--bytes", required=True, help="bytes-only program summary json path")
    ap.add_argument("--addr", required=True, help="addr-aware program summary json path")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    bytes_path = Path(args.bytes).expanduser().resolve()
    addr_path = Path(args.addr).expanduser().resolve()
    if not bytes_path.exists():
        return _fail(2, f"[m22][P0] missing --bytes summary: {bytes_path}")
    if not addr_path.exists():
        return _fail(2, f"[m22][P0] missing --addr summary: {addr_path}")

    bytes_t = _load_tensor(bytes_path)
    addr_t = _load_tensor(addr_path)
    if bytes_t is None or addr_t is None:
        return _fail(2, "[m22][P0] invalid summary schema: missing tensor object")

    bytes_iters = _get_int(bytes_t, "tensor_program_iters_total")
    addr_iters = _get_int(addr_t, "tensor_program_iters_total")
    if bytes_iters <= 0 or addr_iters <= 0:
        return _fail(3, f"[m22][P1] expected program_iters_total > 0 (bytes={bytes_iters}, addr={addr_iters})")

    bytes_cc = _get_int(bytes_t, "tensor_compute_cycles_total")
    addr_cc = _get_int(addr_t, "tensor_compute_cycles_total")
    if bytes_cc <= 0 or addr_cc <= 0:
        return _fail(3, f"[m22][P1] expected compute_cycles_total > 0 (bytes={bytes_cc}, addr={addr_cc})")
    if bytes_cc != addr_cc:
        return _fail(3, f"[m22][P1] expected compute_cycles_total match (bytes={bytes_cc}, addr={addr_cc})")

    bytes_r = _get_int(bytes_t, "tensor_mem_bytes_read_total")
    addr_r = _get_int(addr_t, "tensor_mem_bytes_read_total")
    if bytes_r <= 0 or addr_r <= 0:
        return _fail(3, f"[m22][P1] expected mem_bytes_read_total > 0 (bytes={bytes_r}, addr={addr_r})")
    if bytes_r != addr_r:
        return _fail(3, f"[m22][P1] expected mem_bytes_read_total match (bytes={bytes_r}, addr={addr_r})")

    bytes_ub = _get_int(bytes_t, "tensor_program_ub_stall_cycles_total")
    addr_ub = _get_int(addr_t, "tensor_program_ub_stall_cycles_total")
    if addr_ub <= bytes_ub:
        return _fail(3, f"[m22][P1] expected ub_stall(addr) > bytes (bytes={bytes_ub}, addr={addr_ub})")
    if addr_ub <= 0:
        return _fail(3, "[m22][P1] expected ub_stall(addr) > 0")

    prefix = f"[m22:{args.label}] " if args.label else "[m22] "
    print(f"{prefix}compute_cycles_total: {bytes_cc}")
    print(f"{prefix}mem_bytes_read_total: {bytes_r}")
    print(f"{prefix}program_ub_stall_cycles_total: bytes={bytes_ub} addr={addr_ub}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

