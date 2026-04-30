#!/usr/bin/env python3
"""Validate M88 energy/power v4 contract."""

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


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(default)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        txt = str(value).strip()
        if not txt:
            return int(default)
        return int(float(txt))
    except Exception:
        return int(default)


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
    ap.add_argument("--power-cap", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    eff_p = Path(args.efficiency).expanduser().resolve()
    cap_p = Path(args.power_cap).expanduser().resolve()

    if not eff_p.exists():
        return _fail(2, f"[m88][P0] missing --efficiency summary: {eff_p}")
    if not cap_p.exists():
        return _fail(2, f"[m88][P0] missing --power-cap summary: {cap_p}")

    eff = _load_tensor(eff_p)
    cap = _load_tensor(cap_p)
    if eff is None or cap is None:
        return _fail(2, "[m88][P0] invalid summary schema: missing tensor object")

    e_parts, e_total, e_per_mac = _energy_breakdown(eff)
    c_parts, c_total, c_per_mac = _energy_breakdown(cap)
    if min(e_total, c_total) <= 0.0:
        return _fail(3, f"[m88][P1] expected total energy > 0 (efficiency={e_total:.3f}, power_cap={c_total:.3f})")

    e_mac_eff = _to_float(eff.get("tensor_effective_mac_per_cycle"), 0.0)
    c_mac_eff = _to_float(cap.get("tensor_effective_mac_per_cycle"), 0.0)
    if e_mac_eff > 0.0 and c_mac_eff > 0.0 and c_mac_eff > e_mac_eff:
        return _fail(
            3,
            "[m88][P1] expected power_cap effective_mac_per_cycle <= efficiency "
            f"(efficiency={e_mac_eff:.6f}, power_cap={c_mac_eff:.6f})",
        )
    if c_per_mac < e_per_mac:
        return _fail(
            3,
            "[m88][P1] expected power_cap energy_per_mac >= efficiency "
            f"(efficiency={e_per_mac:.9f}, power_cap={c_per_mac:.9f})",
        )

    e_stall = _to_int(eff.get("tensor_stall_noc_budget_cycles_total")) + _to_int(
        eff.get("tensor_program_mem_stall_cycles_total")
    )
    c_stall = _to_int(cap.get("tensor_stall_noc_budget_cycles_total")) + _to_int(
        cap.get("tensor_program_mem_stall_cycles_total")
    )
    if c_stall < e_stall:
        return _fail(3, f"[m88][P1] expected power_cap stall_proxy >= efficiency (efficiency={e_stall}, power_cap={c_stall})")

    prefix = f"[m88:{args.label}] " if args.label else "[m88] "
    print(
        f"{prefix}energy_total efficiency={e_total:.3f} power_cap={c_total:.3f} "
        f"energy_per_mac efficiency={e_per_mac:.9f} power_cap={c_per_mac:.9f}"
    )
    print(
        f"{prefix}core_energy efficiency={e_parts['core']:.3f} power_cap={c_parts['core']:.3f} "
        f"memory_energy efficiency={e_parts['memory']:.3f} power_cap={c_parts['memory']:.3f} "
        f"noc_energy efficiency={e_parts['noc']:.3f} power_cap={c_parts['noc']:.3f}"
    )
    if e_mac_eff > 0.0 and c_mac_eff > 0.0:
        print(f"{prefix}effective_mac efficiency={e_mac_eff:.6f} power_cap={c_mac_eff:.6f}")
    print(f"{prefix}stall_proxy efficiency={e_stall} power_cap={c_stall}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
