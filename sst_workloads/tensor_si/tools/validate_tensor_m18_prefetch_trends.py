#!/usr/bin/env python3
"""Validate M18 program-mode prefetch/double-buffer trends.

M18 intent:
- With multiple UB buffers (ping-pong) and explicit program scheduling, we can
  prefetch the next tile while computing the current tile, reducing program
  busy cycles.
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
    ap.add_argument("--off", required=True, help="prefetch disabled summary json path")
    ap.add_argument("--on", required=True, help="prefetch enabled summary json path")
    ap.add_argument("--label", default="", help="optional baseline label (for logs)")
    args = ap.parse_args(argv)

    off_path = Path(args.off).expanduser().resolve()
    on_path = Path(args.on).expanduser().resolve()
    if not off_path.exists():
        return _fail(2, f"[m18][P0] missing --off summary: {off_path}")
    if not on_path.exists():
        return _fail(2, f"[m18][P0] missing --on summary: {on_path}")

    off_t = _load_tensor(off_path)
    on_t = _load_tensor(on_path)
    if off_t is None or on_t is None:
        return _fail(2, "[m18][P0] invalid summary schema: missing tensor object")

    off_iters = _get_int(off_t, "tensor_program_iters_total")
    on_iters = _get_int(on_t, "tensor_program_iters_total")
    if off_iters <= 0 or on_iters <= 0:
        return _fail(3, f"[m18][P1] expected program_iters_total > 0 (off={off_iters}, on={on_iters})")

    off_cc = _get_int(off_t, "tensor_compute_cycles_total")
    on_cc = _get_int(on_t, "tensor_compute_cycles_total")
    if off_cc <= 0 or on_cc <= 0:
        return _fail(3, f"[m18][P1] expected compute_cycles_total > 0 (off={off_cc}, on={on_cc})")
    if on_cc != off_cc:
        return _fail(3, f"[m18][P1] expected compute_cycles_total match (off={off_cc}, on={on_cc})")

    off_busy = _get_int(off_t, "tensor_program_any_busy_cycles_total")
    on_busy = _get_int(on_t, "tensor_program_any_busy_cycles_total")
    if off_busy <= 0 or on_busy <= 0:
        return _fail(3, f"[m18][P1] expected program_any_busy_cycles_total > 0 (off={off_busy}, on={on_busy})")
    if on_busy >= off_busy:
        return _fail(3, f"[m18][P1] expected busy(on) < off (off={off_busy}, on={on_busy})")

    # Optional observability (only check if present).
    off_occ = _get_int(off_t, "tensor_program_ub_occupancy_bytes_max")
    on_occ = _get_int(on_t, "tensor_program_ub_occupancy_bytes_max")
    if off_occ > 0 and on_occ > 0 and on_occ <= off_occ:
        return _fail(3, f"[m18][P1] expected ub_occupancy_max(on) > off (off={off_occ}, on={on_occ})")

    prefix = f"[m18:{args.label}] " if args.label else "[m18] "
    print(f"{prefix}compute_cycles_total: {off_cc}")
    print(f"{prefix}program_any_busy_cycles_total: off={off_busy} on={on_busy}")
    if off_occ > 0 or on_occ > 0:
        print(f"{prefix}program_ub_occupancy_bytes_max: off={off_occ} on={on_occ}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

