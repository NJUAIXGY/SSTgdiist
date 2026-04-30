#!/usr/bin/env python3
"""Validate M56 NoC pipeline/VC pressure contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        txt = str(value).strip()
        if not txt:
            return 0
        return int(float(txt))
    except Exception:
        return 0


def _load_tensor(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tensor = payload.get("tensor")
    return tensor if isinstance(tensor, dict) else None


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--pressure", required=True)
    ap.add_argument("--relaxed", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    base_p = Path(args.baseline).expanduser().resolve()
    pressure_p = Path(args.pressure).expanduser().resolve()
    relaxed_p = Path(args.relaxed).expanduser().resolve()

    for p, name in ((base_p, "baseline"), (pressure_p, "pressure"), (relaxed_p, "relaxed")):
        if not p.exists():
            return _fail(2, f"[m56][P0] missing --{name} summary: {p}")

    base = _load_tensor(base_p)
    pressure = _load_tensor(pressure_p)
    relaxed = _load_tensor(relaxed_p)
    if base is None or pressure is None or relaxed is None:
        return _fail(2, "[m56][P0] invalid summary schema: missing tensor object")

    for name, tensor in (("baseline", base), ("pressure", pressure), ("relaxed", relaxed)):
        compute = _to_int(tensor.get("tensor_compute_cycles_total"))
        mac = _to_int(tensor.get("tensor_mac_ops_total"))
        coll_bytes = _to_int(tensor.get("tensor_collective_bytes_sent_total"))
        if compute <= 0 or mac <= 0:
            return _fail(3, f"[m56][P1] expected {name} compute/mac > 0 (compute={compute}, mac={mac})")
        if coll_bytes <= 0:
            return _fail(3, f"[m56][P1] expected {name} collective_bytes_sent_total > 0 (got {coll_bytes})")

    b_credit = _to_int(base.get("tensor_collective_credit_stall_cycles_total"))
    p_credit = _to_int(pressure.get("tensor_collective_credit_stall_cycles_total"))
    r_credit = _to_int(relaxed.get("tensor_collective_credit_stall_cycles_total"))

    b_bp = _to_int(base.get("tensor_collective_backpressure_stall_cycles_total"))
    p_bp = _to_int(pressure.get("tensor_collective_backpressure_stall_cycles_total"))
    r_bp = _to_int(relaxed.get("tensor_collective_backpressure_stall_cycles_total"))

    b_noc = _to_int(base.get("tensor_stall_noc_budget_cycles_total"))
    p_noc = _to_int(pressure.get("tensor_stall_noc_budget_cycles_total"))
    r_noc = _to_int(relaxed.get("tensor_stall_noc_budget_cycles_total"))

    p_inflight = _to_int(pressure.get("tensor_collective_inflight_chunks_max"))
    r_inflight = _to_int(relaxed.get("tensor_collective_inflight_chunks_max"))

    if b_credit != 0:
        return _fail(3, f"[m56][P1] expected baseline credit_stall == 0 (got {b_credit})")
    if p_credit <= 0:
        return _fail(3, f"[m56][P1] expected pressure credit_stall > 0 (got {p_credit})")
    if p_credit <= r_credit:
        return _fail(3, f"[m56][P1] expected pressure credit_stall > relaxed (pressure={p_credit}, relaxed={r_credit})")
    if p_bp <= r_bp:
        return _fail(3, f"[m56][P1] expected pressure backpressure_stall > relaxed (pressure={p_bp}, relaxed={r_bp})")
    if p_noc <= r_noc:
        return _fail(3, f"[m56][P1] expected pressure noc_budget_stall > relaxed (pressure={p_noc}, relaxed={r_noc})")
    if r_inflight < p_inflight:
        return _fail(3, f"[m56][P1] expected relaxed inflight_chunks_max >= pressure (pressure={p_inflight}, relaxed={r_inflight})")

    prefix = f"[m56:{args.label}] " if args.label else "[m56] "
    print(f"{prefix}credit_stall base={b_credit} pressure={p_credit} relaxed={r_credit}")
    print(f"{prefix}backpressure_stall base={b_bp} pressure={p_bp} relaxed={r_bp}")
    print(f"{prefix}noc_budget_stall base={b_noc} pressure={p_noc} relaxed={r_noc}")
    print(f"{prefix}inflight_chunks_max pressure={p_inflight} relaxed={r_inflight}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
