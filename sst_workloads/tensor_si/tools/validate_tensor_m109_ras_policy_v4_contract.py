#!/usr/bin/env python3
"""Validate M109 RAS policy v4 contract."""

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
    ap.add_argument("--hybrid", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    retry_p = Path(args.retry).expanduser().resolve()
    throttle_p = Path(args.throttle).expanduser().resolve()
    isolate_p = Path(args.isolate).expanduser().resolve()
    hybrid_p = Path(args.hybrid).expanduser().resolve()

    for p, name in ((retry_p, "retry"), (throttle_p, "throttle"), (isolate_p, "isolate"), (hybrid_p, "hybrid")):
        if not p.exists():
            return _fail(2, f"[m109][P0] missing --{name} summary: {p}")

    retry = _load_tensor(retry_p)
    throttle = _load_tensor(throttle_p)
    isolate = _load_tensor(isolate_p)
    hybrid = _load_tensor(hybrid_p)
    if retry is None or throttle is None or isolate is None or hybrid is None:
        return _fail(2, "[m109][P0] invalid summary schema: missing tensor object")

    retry_policy = str(_load_cfg(retry_p).get("tensor_ras_policy", "")).strip().lower()
    throttle_policy = str(_load_cfg(throttle_p).get("tensor_ras_policy", "")).strip().lower()
    isolate_policy = str(_load_cfg(isolate_p).get("tensor_ras_policy", "")).strip().lower()
    hybrid_policy = str(_load_cfg(hybrid_p).get("tensor_ras_policy", "")).strip().lower()
    if retry_policy != "retry" or throttle_policy != "throttle" or isolate_policy != "isolate" or hybrid_policy != "hybrid":
        return _fail(
            3,
            "[m109][P1] expected policies retry/throttle/isolate/hybrid "
            f"(retry={retry_policy!r}, throttle={throttle_policy!r}, isolate={isolate_policy!r}, hybrid={hybrid_policy!r})",
        )

    retry_ras = _ras_proxy(retry)
    throttle_ras = _ras_proxy(throttle)
    isolate_ras = _ras_proxy(isolate)
    hybrid_ras = _ras_proxy(hybrid)

    if retry_ras <= throttle_ras or retry_ras <= hybrid_ras or retry_ras <= isolate_ras:
        return _fail(
            3,
            "[m109][P1] expected retry as worst-case ras proxy "
            f"(retry={retry_ras:.3f}, throttle={throttle_ras:.3f}, isolate={isolate_ras:.3f}, hybrid={hybrid_ras:.3f})",
        )
    if isolate_ras >= throttle_ras or isolate_ras >= hybrid_ras:
        return _fail(
            3,
            "[m109][P1] expected isolate as lowest ras proxy "
            f"(retry={retry_ras:.3f}, throttle={throttle_ras:.3f}, isolate={isolate_ras:.3f}, hybrid={hybrid_ras:.3f})",
        )
    if not (isolate_ras <= hybrid_ras <= retry_ras):
        return _fail(
            3,
            "[m109][P1] expected hybrid ras proxy between isolate and retry "
            f"(retry={retry_ras:.3f}, isolate={isolate_ras:.3f}, hybrid={hybrid_ras:.3f})",
        )

    retry_mac = _to_float(retry.get("tensor_effective_mac_per_cycle"), 0.0)
    throttle_mac = _to_float(throttle.get("tensor_effective_mac_per_cycle"), 0.0)
    isolate_mac = _to_float(isolate.get("tensor_effective_mac_per_cycle"), 0.0)
    hybrid_mac = _to_float(hybrid.get("tensor_effective_mac_per_cycle"), 0.0)
    if retry_mac > 0.0 and throttle_mac > 0.0 and isolate_mac > 0.0 and hybrid_mac > 0.0:
        if isolate_mac < hybrid_mac:
            return _fail(
                3,
                "[m109][P1] expected isolate effective_mac_per_cycle >= hybrid "
                f"(isolate={isolate_mac:.6f}, hybrid={hybrid_mac:.6f})",
            )
        if hybrid_mac < throttle_mac:
            return _fail(
                3,
                "[m109][P1] expected hybrid effective_mac_per_cycle >= throttle "
                f"(hybrid={hybrid_mac:.6f}, throttle={throttle_mac:.6f})",
            )

    prefix = f"[m109:{args.label}] " if args.label else "[m109] "
    print(
        f"{prefix}ras retry={retry_ras:.3f} throttle={throttle_ras:.3f} "
        f"isolate={isolate_ras:.3f} hybrid={hybrid_ras:.3f}"
    )
    if retry_mac > 0.0 and throttle_mac > 0.0 and isolate_mac > 0.0 and hybrid_mac > 0.0:
        print(
            f"{prefix}effective_mac retry={retry_mac:.6f} throttle={throttle_mac:.6f} "
            f"isolate={isolate_mac:.6f} hybrid={hybrid_mac:.6f}"
        )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
