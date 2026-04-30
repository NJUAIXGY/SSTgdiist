#!/usr/bin/env python3
"""Validate M107 scale-out v2 contract."""

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


def _to_float(value: Any) -> float:
    try:
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        txt = str(value).strip()
        if not txt:
            return 0.0
        return float(txt)
    except Exception:
        return 0.0


def _load_tensor(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tensor = payload.get("tensor")
    return tensor if isinstance(tensor, dict) else None


def _load_mesh_cfg(summary_path: Path) -> Dict[str, Any]:
    path = summary_path.parent / "effective_config.json"
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    cfg = payload.get("mesh_cfg")
    return cfg if isinstance(cfg, dict) else {}


def _load_readiness(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    ready = payload.get("npu_tpu_readiness")
    return ready if isinstance(ready, dict) else None


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--single", required=True)
    ap.add_argument("--multi", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    single_p = Path(args.single).expanduser().resolve()
    multi_p = Path(args.multi).expanduser().resolve()

    if not single_p.exists():
        return _fail(2, f"[m107][P0] missing --single summary: {single_p}")
    if not multi_p.exists():
        return _fail(2, f"[m107][P0] missing --multi summary: {multi_p}")

    single = _load_tensor(single_p)
    multi = _load_tensor(multi_p)
    s_mesh = _to_int(_load_mesh_cfg(single_p).get("mesh_size"))
    m_mesh = _to_int(_load_mesh_cfg(multi_p).get("mesh_size"))
    s_ready = _load_readiness(single_p)
    m_ready = _load_readiness(multi_p)

    if single is None or multi is None or s_ready is None or m_ready is None:
        return _fail(2, "[m107][P0] invalid summary schema")
    if m_mesh <= s_mesh:
        return _fail(3, f"[m107][P1] expected multi mesh_size > single (single={s_mesh}, multi={m_mesh})")

    s_coll = _to_int(single.get("tensor_collective_bytes_sent_total"))
    m_coll = _to_int(multi.get("tensor_collective_bytes_sent_total"))
    s_pkt = _to_int(single.get("tensor_pkt_bytes_sent_total"))
    m_pkt = _to_int(multi.get("tensor_pkt_bytes_sent_total"))
    if m_coll <= s_coll:
        return _fail(3, f"[m107][P1] expected multi collective_bytes_sent > single (single={s_coll}, multi={m_coll})")
    if m_pkt <= s_pkt:
        return _fail(3, f"[m107][P1] expected multi pkt_bytes_sent > single (single={s_pkt}, multi={m_pkt})")

    s_scale = _to_float(_to_float(s_ready.get("capability_score_breakdown", {}).get("scalability")))
    m_scale = _to_float(_to_float(m_ready.get("capability_score_breakdown", {}).get("scalability")))
    if m_scale < s_scale:
        return _fail(3, f"[m107][P1] expected multi scalability score >= single (single={s_scale:.3f}, multi={m_scale:.3f})")

    s_noc_stall = _to_int(single.get("tensor_stall_noc_budget_cycles_total")) + _to_int(
        single.get("tensor_collective_backpressure_stall_cycles_total")
    )
    m_noc_stall = _to_int(multi.get("tensor_stall_noc_budget_cycles_total")) + _to_int(
        multi.get("tensor_collective_backpressure_stall_cycles_total")
    )
    if m_noc_stall <= s_noc_stall:
        return _fail(3, f"[m107][P1] expected multi noc_stall_proxy > single (single={s_noc_stall}, multi={m_noc_stall})")

    prefix = f"[m107:{args.label}] " if args.label else "[m107] "
    print(
        f"{prefix}mesh_size single={s_mesh} multi={m_mesh} "
        f"collective_bytes single={s_coll} multi={m_coll} pkt_bytes single={s_pkt} multi={m_pkt}"
    )
    print(
        f"{prefix}scalability_score single={s_scale:.3f} multi={m_scale:.3f} "
        f"noc_stall_proxy single={s_noc_stall} multi={m_noc_stall}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
