#!/usr/bin/env python3
"""Validate M19 program-mode on-chip port/bank conflict trends.

M19 intent:
- Program mode DMA should be able to model on-chip UB port contention and UB bank
  conflicts (using existing on-chip knobs) so architectural bottlenecks become
  observable.
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
    ap.add_argument("--base", required=True, help="baseline summary json path (bank/port conflicts disabled)")
    ap.add_argument("--conflict", required=True, help="conflict summary json path (bank/port conflicts enabled)")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    base_path = Path(args.base).expanduser().resolve()
    conf_path = Path(args.conflict).expanduser().resolve()
    if not base_path.exists():
        return _fail(2, f"[m19][P0] missing --base summary: {base_path}")
    if not conf_path.exists():
        return _fail(2, f"[m19][P0] missing --conflict summary: {conf_path}")

    base_t = _load_tensor(base_path)
    conf_t = _load_tensor(conf_path)
    if base_t is None or conf_t is None:
        return _fail(2, "[m19][P0] invalid summary schema: missing tensor object")

    base_iters = _get_int(base_t, "tensor_program_iters_total")
    conf_iters = _get_int(conf_t, "tensor_program_iters_total")
    if base_iters <= 0 or conf_iters <= 0:
        return _fail(3, f"[m19][P1] expected program_iters_total > 0 (base={base_iters}, conflict={conf_iters})")

    base_cc = _get_int(base_t, "tensor_compute_cycles_total")
    conf_cc = _get_int(conf_t, "tensor_compute_cycles_total")
    if base_cc <= 0 or conf_cc <= 0:
        return _fail(3, f"[m19][P1] expected compute_cycles_total > 0 (base={base_cc}, conflict={conf_cc})")
    if base_cc != conf_cc:
        return _fail(3, f"[m19][P1] expected compute_cycles_total match (base={base_cc}, conflict={conf_cc})")

    base_mem = _get_int(base_t, "tensor_mem_bytes_read_total")
    conf_mem = _get_int(conf_t, "tensor_mem_bytes_read_total")
    if base_mem <= 0 or conf_mem <= 0:
        return _fail(3, f"[m19][P1] expected mem_bytes_read_total > 0 (base={base_mem}, conflict={conf_mem})")
    if base_mem != conf_mem:
        return _fail(3, f"[m19][P1] expected mem_bytes_read_total match (base={base_mem}, conflict={conf_mem})")

    base_port = _get_int(base_t, "tensor_stall_onchip_port_cycles_total")
    conf_port = _get_int(conf_t, "tensor_stall_onchip_port_cycles_total")
    base_bank = _get_int(base_t, "tensor_stall_onchip_bank_conflict_cycles_total")
    conf_bank = _get_int(conf_t, "tensor_stall_onchip_bank_conflict_cycles_total")

    if not ((conf_port > base_port) or (conf_bank > base_bank)):
        return _fail(
            3,
            "[m19][P1] expected on-chip stall counters increase in conflict scenario "
            f"(port base={base_port} conflict={conf_port}; bank base={base_bank} conflict={conf_bank})",
        )
    if (conf_port + conf_bank) <= 0:
        return _fail(3, "[m19][P1] expected at least one on-chip stall counter > 0 in conflict scenario")

    prefix = f"[m19:{args.label}] " if args.label else "[m19] "
    print(f"{prefix}compute_cycles_total: {base_cc}")
    print(f"{prefix}mem_bytes_read_total: {base_mem}")
    print(f"{prefix}stall_onchip_port_cycles_total: base={base_port} conflict={conf_port}")
    print(f"{prefix}stall_onchip_bank_conflict_cycles_total: base={base_bank} conflict={conf_bank}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

