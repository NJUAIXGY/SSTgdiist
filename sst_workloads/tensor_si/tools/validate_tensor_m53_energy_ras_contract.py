#!/usr/bin/env python3
"""Validate M53 energy proxy and RAS proxy contract."""

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


def _energy_ras_proxy(tensor: Dict[str, Any]) -> Tuple[float, float, float]:
    compute_cycles = _to_float(tensor.get("tensor_compute_cycles_total"), 0.0)
    dma_cycles = _to_float(tensor.get("tensor_dma_cycles_total"), 0.0)
    mem_bytes = _to_float(tensor.get("tensor_mem_bytes_read_total"), 0.0) + _to_float(
        tensor.get("tensor_mem_bytes_write_total"), 0.0
    )
    noc_bytes = _to_float(tensor.get("tensor_pkt_bytes_sent_total"), 0.0) + _to_float(
        tensor.get("tensor_pkt_bytes_recv_total"), 0.0
    )

    energy_total = compute_cycles + 0.5 * dma_cycles + 0.001 * mem_bytes + 0.0005 * noc_bytes
    mac_ops = max(1.0, _to_float(tensor.get("tensor_mac_ops_total"), 0.0))
    energy_per_mac = energy_total / mac_ops

    ras_total = (
        _to_float(tensor.get("tensor_stall_noc_budget_cycles_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_backpressure_stall_cycles_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_credit_stall_cycles_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_credit_return_orphan_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_credit_return_dup_total"), 0.0)
        + _to_float(tensor.get("tensor_program_mem_stall_cycles_total"), 0.0)
    )

    return float(energy_total), float(energy_per_mac), float(ras_total)


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--efficiency", required=True, help="efficiency scenario summary")
    ap.add_argument("--fault", required=True, help="fault scenario summary")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    eff_p = Path(args.efficiency).expanduser().resolve()
    fault_p = Path(args.fault).expanduser().resolve()

    if not eff_p.exists():
        return _fail(2, f"[m53][P0] missing --efficiency summary: {eff_p}")
    if not fault_p.exists():
        return _fail(2, f"[m53][P0] missing --fault summary: {fault_p}")

    eff = _load_tensor(eff_p)
    fault = _load_tensor(fault_p)
    if eff is None or fault is None:
        return _fail(2, "[m53][P0] invalid summary schema: missing tensor object")

    eff_energy_total, eff_energy_per_mac, eff_ras = _energy_ras_proxy(eff)
    fault_energy_total, fault_energy_per_mac, fault_ras = _energy_ras_proxy(fault)

    if eff_energy_total <= 0.0 or fault_energy_total <= 0.0:
        return _fail(3, f"[m53][P1] expected energy proxy > 0 (eff={eff_energy_total:.6f}, fault={fault_energy_total:.6f})")

    if fault_ras < eff_ras:
        return _fail(3, f"[m53][P1] expected fault RAS proxy >= efficiency (eff={eff_ras:.3f}, fault={fault_ras:.3f})")

    if fault_energy_per_mac < eff_energy_per_mac:
        return _fail(
            3,
            "[m53][P1] expected fault energy_per_mac >= efficiency "
            f"(eff={eff_energy_per_mac:.9f}, fault={fault_energy_per_mac:.9f})",
        )

    prefix = f"[m53:{args.label}] " if args.label else "[m53] "
    print(
        f"{prefix}energy_total eff={eff_energy_total:.3f} fault={fault_energy_total:.3f} "
        f"energy_per_mac eff={eff_energy_per_mac:.9f} fault={fault_energy_per_mac:.9f}"
    )
    print(f"{prefix}ras_proxy eff={eff_ras:.3f} fault={fault_ras:.3f}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
