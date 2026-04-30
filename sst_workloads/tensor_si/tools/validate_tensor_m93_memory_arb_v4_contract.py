#!/usr/bin/env python3
"""Validate M93 memory arbitration v4 contract."""

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


def _avg(total: int, samples: int) -> float:
    if samples <= 0:
        return 0.0
    return float(total) / float(samples)


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


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


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fair", required=True)
    ap.add_argument("--unfair", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    fair_p = Path(args.fair).expanduser().resolve()
    unfair_p = Path(args.unfair).expanduser().resolve()

    if not fair_p.exists():
        return _fail(2, f"[m93][P0] missing --fair summary: {fair_p}")
    if not unfair_p.exists():
        return _fail(2, f"[m93][P0] missing --unfair summary: {unfair_p}")

    fair = _load_tensor(fair_p)
    unfair = _load_tensor(unfair_p)
    if fair is None or unfair is None:
        return _fail(2, "[m93][P0] invalid summary schema: missing tensor object")

    fair_cfg = _load_cfg(fair_p)
    unfair_cfg = _load_cfg(unfair_p)

    fair_sched = str(fair_cfg.get("tensor_mem_sched_policy", "")).strip().lower()
    unfair_sched = str(unfair_cfg.get("tensor_mem_sched_policy", "")).strip().lower()
    if fair_sched != "frfcfs" or unfair_sched != "fifo":
        return _fail(
            3,
            "[m93][P1] expected sched policy fair=frfcfs and unfair=fifo "
            f"(fair={fair_sched!r}, unfair={unfair_sched!r})",
        )

    fair_qdepth = _to_int(fair_cfg.get("tensor_mem_bank_queue_depth"), 0)
    unfair_qdepth = _to_int(unfair_cfg.get("tensor_mem_bank_queue_depth"), 0)
    if fair_qdepth <= unfair_qdepth:
        return _fail(
            3,
            "[m93][P1] expected fair bank_queue_depth > unfair "
            f"(fair={fair_qdepth}, unfair={unfair_qdepth})",
        )

    fair_read_samples = _to_int(fair.get("tensor_mem_read_latency_samples_total"), 0)
    unfair_read_samples = _to_int(unfair.get("tensor_mem_read_latency_samples_total"), 0)
    if fair_read_samples <= 0 or unfair_read_samples <= 0:
        return _fail(
            3,
            "[m93][P1] expected read latency samples > 0 "
            f"(fair={fair_read_samples}, unfair={unfair_read_samples})",
        )

    fair_lat = _avg(
        _to_int(fair.get("tensor_mem_read_latency_cycles_total"), 0),
        fair_read_samples,
    )
    unfair_lat = _avg(
        _to_int(unfair.get("tensor_mem_read_latency_cycles_total"), 0),
        unfair_read_samples,
    )
    if unfair_lat <= fair_lat:
        return _fail(3, f"[m93][P1] expected unfair avg_read_latency > fair (fair={fair_lat:.3f}, unfair={unfair_lat:.3f})")

    fair_bus_wait = _to_int(fair.get("tensor_mem_cmd_bus_wait_cycles_total"), 0)
    unfair_bus_wait = _to_int(unfair.get("tensor_mem_cmd_bus_wait_cycles_total"), 0)
    if unfair_bus_wait <= fair_bus_wait:
        return _fail(
            3,
            "[m93][P1] expected unfair cmd_bus_wait > fair "
            f"(fair={fair_bus_wait}, unfair={unfair_bus_wait})",
        )

    fair_conflict = _to_int(fair.get("tensor_mem_row_conflict_total"), 0)
    unfair_conflict = _to_int(unfair.get("tensor_mem_row_conflict_total"), 0)
    if unfair_conflict <= fair_conflict:
        return _fail(
            3,
            "[m93][P1] expected unfair row_conflict > fair "
            f"(fair={fair_conflict}, unfair={unfair_conflict})",
        )

    fair_refresh = _to_int(fair.get("tensor_mem_refresh_block_cycles_total"), 0)
    unfair_refresh = _to_int(unfair.get("tensor_mem_refresh_block_cycles_total"), 0)
    if unfair_refresh <= fair_refresh:
        return _fail(
            3,
            "[m93][P1] expected unfair refresh_block_cycles > fair "
            f"(fair={fair_refresh}, unfair={unfair_refresh})",
        )

    fair_mac = _to_float(fair.get("tensor_effective_mac_per_cycle"), 0.0)
    unfair_mac = _to_float(unfair.get("tensor_effective_mac_per_cycle"), 0.0)
    if fair_mac > 0.0 and unfair_mac > 0.0 and unfair_mac > fair_mac:
        return _fail(
            3,
            "[m93][P1] expected unfair effective_mac_per_cycle <= fair "
            f"(fair={fair_mac:.6f}, unfair={unfair_mac:.6f})",
        )

    prefix = f"[m93:{args.label}] " if args.label else "[m93] "
    print(
        f"{prefix}sched fair={fair_sched} unfair={unfair_sched} "
        f"queue_depth fair={fair_qdepth} unfair={unfair_qdepth}"
    )
    print(
        f"{prefix}avg_read_latency fair={fair_lat:.3f} unfair={unfair_lat:.3f} "
        f"cmd_bus_wait fair={fair_bus_wait} unfair={unfair_bus_wait} "
        f"row_conflict fair={fair_conflict} unfair={unfair_conflict} "
        f"refresh_block fair={fair_refresh} unfair={unfair_refresh}"
    )
    if fair_mac > 0.0 and unfair_mac > 0.0:
        print(f"{prefix}effective_mac fair={fair_mac:.6f} unfair={unfair_mac:.6f}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
