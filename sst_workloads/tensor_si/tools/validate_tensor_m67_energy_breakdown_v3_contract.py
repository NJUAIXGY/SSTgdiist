#!/usr/bin/env python3
"""Validate M67 energy breakdown v3 contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return float(default)
        if isinstance(value, (int, float)):
            return float(value)
        txt = str(value).strip()
        if not txt:
            return float(default)
        return float(txt)
    except Exception:
        return float(default)


def _load_tensor(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tensor = payload.get("tensor")
    return tensor if isinstance(tensor, dict) else None


def _energy_breakdown(tensor: Dict[str, Any]) -> Tuple[Dict[str, float], float, float]:
    core = _to_float(tensor.get("tensor_compute_cycles_total"), 0.0) + 0.2 * _to_float(
        tensor.get("tensor_compute_pipeline_cycles_total"), 0.0
    )
    dma = 0.5 * _to_float(tensor.get("tensor_dma_cycles_total"), 0.0) + 0.05 * _to_float(
        tensor.get("tensor_dma_stall_cycles_total"), 0.0
    )
    memory = 0.001 * (
        _to_float(tensor.get("tensor_mem_bytes_read_total"), 0.0)
        + _to_float(tensor.get("tensor_mem_bytes_write_total"), 0.0)
    ) + 0.2 * _to_float(tensor.get("tensor_mem_cmd_bus_wait_cycles_total"), 0.0) + 0.1 * _to_float(
        tensor.get("tensor_mem_bank_queue_wait_cycles_total"), 0.0
    )
    noc = 0.0005 * (
        _to_float(tensor.get("tensor_pkt_bytes_sent_total"), 0.0)
        + _to_float(tensor.get("tensor_pkt_bytes_recv_total"), 0.0)
    ) + 0.2 * (
        _to_float(tensor.get("tensor_stall_noc_budget_cycles_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_credit_stall_cycles_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_backpressure_stall_cycles_total"), 0.0)
    )

    parts = {
        "core": float(core),
        "dma": float(dma),
        "memory": float(memory),
        "noc": float(noc),
    }
    total = parts["core"] + parts["dma"] + parts["memory"] + parts["noc"]
    mac = max(1.0, _to_float(tensor.get("tensor_mac_ops_total"), 0.0))
    per_mac = total / mac
    return parts, float(total), float(per_mac)


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--efficiency", required=True)
    ap.add_argument("--fault", required=True)
    ap.add_argument("--recovery", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    eff_p = Path(args.efficiency).expanduser().resolve()
    fault_p = Path(args.fault).expanduser().resolve()
    rec_p = Path(args.recovery).expanduser().resolve()

    for p, name in ((eff_p, "efficiency"), (fault_p, "fault"), (rec_p, "recovery")):
        if not p.exists():
            return _fail(2, f"[m67][P0] missing --{name} summary: {p}")

    eff = _load_tensor(eff_p)
    fault = _load_tensor(fault_p)
    rec = _load_tensor(rec_p)
    if eff is None or fault is None or rec is None:
        return _fail(2, "[m67][P0] invalid summary schema: missing tensor object")

    e_parts, e_total, e_per_mac = _energy_breakdown(eff)
    f_parts, f_total, f_per_mac = _energy_breakdown(fault)
    r_parts, r_total, r_per_mac = _energy_breakdown(rec)

    if min(e_total, f_total, r_total) <= 0.0:
        return _fail(3, f"[m67][P1] expected total energy > 0 (eff={e_total:.3f}, fault={f_total:.3f}, recovery={r_total:.3f})")
    if f_total <= r_total or r_total <= e_total:
        return _fail(
            3,
            "[m67][P1] expected total ordering fault > recovery > efficiency "
            f"(eff={e_total:.3f}, fault={f_total:.3f}, recovery={r_total:.3f})",
        )
    if f_parts["memory"] <= e_parts["memory"]:
        return _fail(3, f"[m67][P1] expected fault memory_energy > efficiency (eff={e_parts['memory']:.3f}, fault={f_parts['memory']:.3f})")
    if f_parts["noc"] <= e_parts["noc"]:
        return _fail(3, f"[m67][P1] expected fault noc_energy > efficiency (eff={e_parts['noc']:.3f}, fault={f_parts['noc']:.3f})")
    if f_per_mac < r_per_mac or r_per_mac < e_per_mac:
        return _fail(
            3,
            "[m67][P1] expected per_mac ordering fault >= recovery >= efficiency "
            f"(eff={e_per_mac:.9f}, fault={f_per_mac:.9f}, recovery={r_per_mac:.9f})",
        )

    prefix = f"[m67:{args.label}] " if args.label else "[m67] "
    print(
        f"{prefix}total eff={e_total:.3f} fault={f_total:.3f} recovery={r_total:.3f} "
        f"per_mac eff={e_per_mac:.9f} fault={f_per_mac:.9f} recovery={r_per_mac:.9f}"
    )
    print(
        f"{prefix}memory_energy eff={e_parts['memory']:.3f} fault={f_parts['memory']:.3f} recovery={r_parts['memory']:.3f} "
        f"noc_energy eff={e_parts['noc']:.3f} fault={f_parts['noc']:.3f} recovery={r_parts['noc']:.3f}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
