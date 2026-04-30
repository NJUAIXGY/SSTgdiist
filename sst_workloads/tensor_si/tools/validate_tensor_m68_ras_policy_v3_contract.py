#!/usr/bin/env python3
"""Validate M68 RAS policy v3 contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


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


def _load_cfg(summary_path: Path) -> Dict[str, Any]:
    path = summary_path.parent / "effective_config.json"
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    cfg = payload.get("tensor_cfg")
    return cfg if isinstance(cfg, dict) else {}


def _ras_proxy(tensor: Dict[str, Any]) -> float:
    return float(
        _to_float(tensor.get("tensor_stall_noc_budget_cycles_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_backpressure_stall_cycles_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_credit_stall_cycles_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_credit_return_orphan_total"), 0.0)
        + _to_float(tensor.get("tensor_collective_credit_return_dup_total"), 0.0)
        + _to_float(tensor.get("tensor_program_mem_stall_cycles_total"), 0.0)
        + _to_float(tensor.get("tensor_mem_cmd_bus_wait_cycles_total"), 0.0)
    )


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retry", required=True)
    ap.add_argument("--throttle", required=True)
    ap.add_argument("--isolate", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    retry_p = Path(args.retry).expanduser().resolve()
    throttle_p = Path(args.throttle).expanduser().resolve()
    isolate_p = Path(args.isolate).expanduser().resolve()

    for p, name in ((retry_p, "retry"), (throttle_p, "throttle"), (isolate_p, "isolate")):
        if not p.exists():
            return _fail(2, f"[m68][P0] missing --{name} summary: {p}")

    retry = _load_tensor(retry_p)
    throttle = _load_tensor(throttle_p)
    isolate = _load_tensor(isolate_p)
    if retry is None or throttle is None or isolate is None:
        return _fail(2, "[m68][P0] invalid summary schema: missing tensor object")

    retry_policy = str(_load_cfg(retry_p).get("tensor_ras_policy", "")).strip().lower()
    throttle_policy = str(_load_cfg(throttle_p).get("tensor_ras_policy", "")).strip().lower()
    isolate_policy = str(_load_cfg(isolate_p).get("tensor_ras_policy", "")).strip().lower()
    if retry_policy != "retry" or throttle_policy != "throttle" or isolate_policy != "isolate":
        return _fail(
            3,
            "[m68][P1] expected policies retry/throttle/isolate "
            f"(retry={retry_policy!r}, throttle={throttle_policy!r}, isolate={isolate_policy!r})",
        )

    retry_ras = _ras_proxy(retry)
    throttle_ras = _ras_proxy(throttle)
    isolate_ras = _ras_proxy(isolate)

    if retry_ras <= throttle_ras or throttle_ras < isolate_ras:
        return _fail(
            3,
            "[m68][P1] expected RAS ordering retry > throttle >= isolate "
            f"(retry={retry_ras:.3f}, throttle={throttle_ras:.3f}, isolate={isolate_ras:.3f})",
        )

    retry_mac = _to_float(retry.get("tensor_effective_mac_per_cycle"), 0.0)
    throttle_mac = _to_float(throttle.get("tensor_effective_mac_per_cycle"), 0.0)
    isolate_mac = _to_float(isolate.get("tensor_effective_mac_per_cycle"), 0.0)
    if retry_mac > 0.0 and throttle_mac > 0.0 and isolate_mac > 0.0:
        if throttle_mac > retry_mac:
            return _fail(
                3,
                "[m68][P1] expected throttle effective_mac_per_cycle <= retry "
                f"(retry={retry_mac:.6f}, throttle={throttle_mac:.6f})",
            )
        if isolate_mac > throttle_mac:
            return _fail(
                3,
                "[m68][P1] expected isolate effective_mac_per_cycle <= throttle "
                f"(throttle={throttle_mac:.6f}, isolate={isolate_mac:.6f})",
            )

    prefix = f"[m68:{args.label}] " if args.label else "[m68] "
    print(
        f"{prefix}ras retry={retry_ras:.3f} throttle={throttle_ras:.3f} isolate={isolate_ras:.3f} "
        f"policy={retry_policy}/{throttle_policy}/{isolate_policy}"
    )
    if retry_mac > 0.0 and throttle_mac > 0.0 and isolate_mac > 0.0:
        print(f"{prefix}effective_mac retry={retry_mac:.6f} throttle={throttle_mac:.6f} isolate={isolate_mac:.6f}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
