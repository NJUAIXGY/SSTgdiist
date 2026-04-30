#!/usr/bin/env python3
"""Validate M84 cross-layer causal contract (memory-first vs noc-first)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _load_ready(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    ready = payload.get("npu_tpu_readiness")
    return ready if isinstance(ready, dict) else None


def _dominant_layer(ready: Dict[str, Any]) -> str:
    attr = ready.get("cross_layer_attribution")
    if not isinstance(attr, dict):
        return ""
    return str(attr.get("dominant_layer", "")).strip().lower()


def _signals(ready: Dict[str, Any]) -> Dict[str, int]:
    attr = ready.get("cross_layer_attribution")
    if not isinstance(attr, dict):
        return {}
    signals = attr.get("signals")
    if not isinstance(signals, dict):
        return {}
    return {str(k): _to_int(v, 0) for k, v in signals.items()}


def _layer_share(ready: Dict[str, Any], key: str) -> float:
    attr = ready.get("cross_layer_attribution")
    if not isinstance(attr, dict):
        return 0.0
    share = attr.get("layer_share")
    if not isinstance(share, dict):
        return 0.0
    try:
        return float(share.get(key, 0.0) or 0.0)
    except Exception:
        return 0.0


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", required=True)
    ap.add_argument("--noc", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    mem_p = Path(args.memory).expanduser().resolve()
    noc_p = Path(args.noc).expanduser().resolve()

    if not mem_p.exists():
        return _fail(2, f"[m84][P0] missing --memory summary: {mem_p}")
    if not noc_p.exists():
        return _fail(2, f"[m84][P0] missing --noc summary: {noc_p}")

    mem = _load_ready(mem_p)
    noc = _load_ready(noc_p)
    if mem is None or noc is None:
        return _fail(2, "[m84][P0] invalid summary schema: missing npu_tpu_readiness")

    mem_dom = _dominant_layer(mem)
    noc_dom = _dominant_layer(noc)
    if mem_dom != "memory":
        return _fail(3, f"[m84][P1] expected memory scenario dominant_layer=memory (got {mem_dom!r})")
    if noc_dom not in {"memory", "noc"}:
        return _fail(3, f"[m84][P1] expected noc scenario dominant_layer in {{memory,noc}} (got {noc_dom!r})")

    mem_sig = _signals(mem)
    noc_sig = _signals(noc)
    mem_pressure = _to_int(mem_sig.get("tensor_mem_cmd_bus_wait_cycles_total")) + _to_int(
        mem_sig.get("tensor_mem_bank_queue_wait_cycles_total")
    )
    mem_noc_pressure = _to_int(mem_sig.get("tensor_stall_noc_budget_cycles_total")) + _to_int(
        mem_sig.get("tensor_collective_credit_stall_cycles_total")
    ) + _to_int(mem_sig.get("tensor_collective_backpressure_stall_cycles_total"))
    noc_pressure = _to_int(noc_sig.get("tensor_stall_noc_budget_cycles_total")) + _to_int(
        noc_sig.get("tensor_collective_credit_stall_cycles_total")
    ) + _to_int(noc_sig.get("tensor_collective_backpressure_stall_cycles_total"))
    noc_mem_pressure = _to_int(noc_sig.get("tensor_mem_cmd_bus_wait_cycles_total")) + _to_int(
        noc_sig.get("tensor_mem_bank_queue_wait_cycles_total")
    )

    if mem_pressure <= mem_noc_pressure:
        return _fail(
            3,
            "[m84][P1] expected memory scenario memory_pressure > noc_pressure "
            f"(memory={mem_pressure}, noc={mem_noc_pressure})",
        )
    if noc_pressure <= mem_noc_pressure:
        return _fail(
            3,
            "[m84][P1] expected noc scenario noc_pressure > memory-scenario noc_pressure "
            f"(memory_scenario_noc={mem_noc_pressure}, noc_scenario_noc={noc_pressure})",
        )

    mem_noc_share = _layer_share(mem, "noc")
    noc_noc_share = _layer_share(noc, "noc")
    if noc_noc_share <= mem_noc_share:
        return _fail(
            3,
            "[m84][P1] expected noc layer_share increase in noc scenario "
            f"(memory_scenario_noc_share={mem_noc_share:.6f}, noc_scenario_noc_share={noc_noc_share:.6f})",
        )

    prefix = f"[m84:{args.label}] " if args.label else "[m84] "
    print(
        f"{prefix}dominant memory_scenario={mem_dom} noc_scenario={noc_dom} "
        f"memory_pressure(mem)={mem_pressure} noc_pressure(mem)={mem_noc_pressure}"
    )
    print(
        f"{prefix}noc_pressure(noc)={noc_pressure} memory_pressure(noc)={noc_mem_pressure} "
        f"noc_share memory_scenario={mem_noc_share:.6f} noc_scenario={noc_noc_share:.6f}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
