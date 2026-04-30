#!/usr/bin/env python3
"""Validate M33 MXU per-cycle IO consumption trends (program mode).

M33 intent:
- MXU feed/drain should be modeled as per-cycle byte consumption rather than
  a one-shot lower-bound adjustment at issue time.
- Expose a direct, explainable signal: tensor_mxu_io_busy_cycles_total.
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
    ap.add_argument("--base", required=True, help="baseline summary json path (high MXU bpc)")
    ap.add_argument("--throttled", required=True, help="throttled summary json path (low MXU bpc)")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    base_path = Path(args.base).expanduser().resolve()
    thr_path = Path(args.throttled).expanduser().resolve()
    if not base_path.exists():
        return _fail(2, f"[m33][P0] missing --base summary: {base_path}")
    if not thr_path.exists():
        return _fail(2, f"[m33][P0] missing --throttled summary: {thr_path}")

    base_t = _load_tensor(base_path)
    thr_t = _load_tensor(thr_path)
    if base_t is None or thr_t is None:
        return _fail(2, "[m33][P0] invalid summary schema: missing tensor object")

    base_iters = _get_int(base_t, "tensor_program_iters_total")
    thr_iters = _get_int(thr_t, "tensor_program_iters_total")
    if base_iters <= 0 or thr_iters <= 0:
        return _fail(3, f"[m33][P1] expected program_iters_total > 0 (base={base_iters}, throttled={thr_iters})")

    base_r = _get_int(base_t, "tensor_mem_bytes_read_total")
    thr_r = _get_int(thr_t, "tensor_mem_bytes_read_total")
    if base_r <= 0 or thr_r <= 0:
        return _fail(3, f"[m33][P1] expected mem_bytes_read_total > 0 (base={base_r}, throttled={thr_r})")
    if base_r != thr_r:
        return _fail(3, f"[m33][P1] expected mem_bytes_read_total match (base={base_r}, throttled={thr_r})")

    base_cc = _get_int(base_t, "tensor_compute_cycles_total")
    thr_cc = _get_int(thr_t, "tensor_compute_cycles_total")
    if base_cc <= 0 or thr_cc <= 0:
        return _fail(3, f"[m33][P1] expected compute_cycles_total > 0 (base={base_cc}, throttled={thr_cc})")
    if thr_cc <= base_cc:
        return _fail(3, f"[m33][P1] expected compute_cycles(throttled) > base (base={base_cc}, throttled={thr_cc})")

    base_io = _get_int(base_t, "tensor_mxu_io_busy_cycles_total")
    thr_io = _get_int(thr_t, "tensor_mxu_io_busy_cycles_total")
    if base_io <= 0 or thr_io <= 0:
        return _fail(3, f"[m33][P1] expected mxu_io_busy_cycles_total > 0 (base={base_io}, throttled={thr_io})")
    if thr_io <= base_io:
        return _fail(3, f"[m33][P1] expected mxu_io_busy_cycles(throttled) > base (base={base_io}, throttled={thr_io})")
    if thr_io > thr_cc:
        return _fail(3, f"[m33][P1] expected mxu_io_busy_cycles_total <= compute_cycles_total (io={thr_io}, compute={thr_cc})")

    prefix = f"[m33:{args.label}] " if args.label else "[m33] "
    print(f"{prefix}mem_bytes_read_total: {base_r}")
    print(f"{prefix}compute_cycles_total: base={base_cc} throttled={thr_cc}")
    print(f"{prefix}mxu_io_busy_cycles_total: base={base_io} throttled={thr_io}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
