#!/usr/bin/env python3
"""Validate M50 NoC fidelity proxy trends."""

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
    mesh_cfg = payload.get("mesh_cfg") if isinstance(payload.get("mesh_cfg"), dict) else {}
    tensor_cfg = payload.get("tensor_cfg") if isinstance(payload.get("tensor_cfg"), dict) else {}
    return {"mesh_cfg": mesh_cfg, "tensor_cfg": tensor_cfg}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--congest", required=True, help="congested summary json")
    ap.add_argument("--balanced", required=True, help="balanced summary json")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    congest_p = Path(args.congest).expanduser().resolve()
    balanced_p = Path(args.balanced).expanduser().resolve()

    if not congest_p.exists():
        return _fail(2, f"[m50][P0] missing --congest summary: {congest_p}")
    if not balanced_p.exists():
        return _fail(2, f"[m50][P0] missing --balanced summary: {balanced_p}")

    congest = _load_tensor(congest_p)
    balanced = _load_tensor(balanced_p)
    if congest is None or balanced is None:
        return _fail(2, "[m50][P0] invalid summary schema: missing tensor object")

    congest_collective = _to_int(congest.get("tensor_collective_bytes_sent_total"))
    balanced_collective = _to_int(balanced.get("tensor_collective_bytes_sent_total"))
    if congest_collective <= 0 or balanced_collective <= 0:
        return _fail(3, f"[m50][P1] expected collective bytes sent > 0 (congest={congest_collective}, balanced={balanced_collective})")

    congest_noc_stall = _to_int(congest.get("tensor_stall_noc_budget_cycles_total"))
    balanced_noc_stall = _to_int(balanced.get("tensor_stall_noc_budget_cycles_total"))
    if congest_noc_stall < balanced_noc_stall:
        return _fail(3, f"[m50][P1] expected congest noc stall >= balanced (congest={congest_noc_stall}, balanced={balanced_noc_stall})")

    congest_pending = _to_int(congest.get("tensor_collective_pending_cycles_total"))
    balanced_pending = _to_int(balanced.get("tensor_collective_pending_cycles_total"))
    if congest_pending < balanced_pending:
        return _fail(3, f"[m50][P1] expected congest collective pending >= balanced (congest={congest_pending}, balanced={balanced_pending})")

    c_cfg = _load_cfg(congest_p)
    b_cfg = _load_cfg(balanced_p)
    c_noc = str(c_cfg["mesh_cfg"].get("noc_type", "")).strip().lower()
    b_noc = str(b_cfg["mesh_cfg"].get("noc_type", "")).strip().lower()
    if c_noc != "merlin_mesh" or b_noc != "merlin_torus":
        return _fail(3, f"[m50][P1] expected noc types mesh/torus (congest={c_noc!r}, balanced={b_noc!r})")

    c_bw = _to_int(c_cfg["tensor_cfg"].get("tensor_noc_bandwidth_bytes_per_cycle"))
    b_bw = _to_int(b_cfg["tensor_cfg"].get("tensor_noc_bandwidth_bytes_per_cycle"))
    if c_bw <= 0:
        return _fail(3, f"[m50][P1] expected positive congest tensor_noc_bandwidth_bytes_per_cycle (got {c_bw})")
    if b_bw != 0:
        return _fail(3, f"[m50][P1] expected balanced tensor_noc_bandwidth_bytes_per_cycle=0 (got {b_bw})")

    prefix = f"[m50:{args.label}] " if args.label else "[m50] "
    print(f"{prefix}collective_bytes_sent congest={congest_collective} balanced={balanced_collective}")
    print(f"{prefix}stall_noc_budget congest={congest_noc_stall} balanced={balanced_noc_stall}")
    print(f"{prefix}collective_pending congest={congest_pending} balanced={balanced_pending}")
    print(f"{prefix}noc_type congest={c_noc} balanced={b_noc} noc_bw={c_bw}/{b_bw}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
