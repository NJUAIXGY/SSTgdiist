#!/usr/bin/env python3
"""Validate M54 compute microarchitecture proxy contract.

M54 intent:
- Baseline / structural-hazard / dependency-hazard scenarios should expose
  separable compute-microstructure signals.
- Keep this stage proxy-based (no deep C++ pipeline model rewrite yet), but
  enforce stable trend constraints for next-phase realism convergence.
"""

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
    cfg = payload.get("tensor_cfg")
    return cfg if isinstance(cfg, dict) else {}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, help="baseline summary json")
    ap.add_argument("--structural", required=True, help="structural-hazard summary json")
    ap.add_argument("--dependency", required=True, help="dependency-hazard summary json")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    base_p = Path(args.baseline).expanduser().resolve()
    struct_p = Path(args.structural).expanduser().resolve()
    dep_p = Path(args.dependency).expanduser().resolve()

    for path, flag in ((base_p, "baseline"), (struct_p, "structural"), (dep_p, "dependency")):
        if not path.exists():
            return _fail(2, f"[m54][P0] missing --{flag} summary: {path}")

    base = _load_tensor(base_p)
    struct = _load_tensor(struct_p)
    dep = _load_tensor(dep_p)
    if base is None or struct is None or dep is None:
        return _fail(2, "[m54][P0] invalid summary schema: missing tensor object")

    base_bytes = _to_int(base.get("tensor_mem_bytes_read_total"))
    struct_bytes = _to_int(struct.get("tensor_mem_bytes_read_total"))
    dep_bytes = _to_int(dep.get("tensor_mem_bytes_read_total"))
    if base_bytes <= 0 or struct_bytes <= 0 or dep_bytes <= 0:
        return _fail(
            3,
            "[m54][P1] expected mem_bytes_read_total > 0 "
            f"(baseline={base_bytes}, structural={struct_bytes}, dependency={dep_bytes})",
        )

    base_compute = _to_int(base.get("tensor_compute_cycles_total"))
    struct_compute = _to_int(struct.get("tensor_compute_cycles_total"))
    dep_compute = _to_int(dep.get("tensor_compute_cycles_total"))
    if min(base_compute, struct_compute, dep_compute) <= 0:
        return _fail(
            3,
            "[m54][P1] expected compute_cycles_total > 0 "
            f"(baseline={base_compute}, structural={struct_compute}, dependency={dep_compute})",
        )
    if not (base_compute == struct_compute == dep_compute):
        return _fail(
            3,
            "[m54][P1] expected compute_cycles_total match across scenarios "
            f"(baseline={base_compute}, structural={struct_compute}, dependency={dep_compute})",
        )

    base_mac = _to_int(base.get("tensor_mac_ops_total"))
    struct_mac = _to_int(struct.get("tensor_mac_ops_total"))
    dep_mac = _to_int(dep.get("tensor_mac_ops_total"))
    if min(base_mac, struct_mac, dep_mac) <= 0:
        return _fail(
            3,
            "[m54][P1] expected mac_ops_total > 0 "
            f"(baseline={base_mac}, structural={struct_mac}, dependency={dep_mac})",
        )
    if not (base_mac == struct_mac == dep_mac):
        return _fail(
            3,
            "[m54][P1] expected mac_ops_total match across scenarios "
            f"(baseline={base_mac}, structural={struct_mac}, dependency={dep_mac})",
        )

    base_port = _to_int(base.get("tensor_stall_onchip_port_cycles_total"))
    base_bank = _to_int(base.get("tensor_stall_onchip_bank_conflict_cycles_total"))
    struct_port = _to_int(struct.get("tensor_stall_onchip_port_cycles_total"))
    struct_bank = _to_int(struct.get("tensor_stall_onchip_bank_conflict_cycles_total"))
    base_structural = base_port + base_bank
    struct_structural = struct_port + struct_bank
    if struct_structural <= base_structural:
        return _fail(
            3,
            "[m54][P1] expected structural stall increase "
            f"(baseline={base_structural}, structural={struct_structural})",
        )
    if struct_structural <= 0:
        return _fail(3, "[m54][P1] expected structural scenario structural stalls > 0")

    base_queue = _to_int(base.get("tensor_bank_queue_occupancy_max"))
    struct_queue = _to_int(struct.get("tensor_bank_queue_occupancy_max"))
    if struct_queue <= base_queue:
        return _fail(
            3,
            "[m54][P1] expected structural bank_queue_occupancy_max > baseline "
            f"(baseline={base_queue}, structural={struct_queue})",
        )

    base_ub = _to_int(base.get("tensor_program_ub_stall_cycles_total"))
    dep_ub = _to_int(dep.get("tensor_program_ub_stall_cycles_total"))
    if dep_ub <= base_ub:
        return _fail(
            3,
            "[m54][P1] expected dependency ub stall > baseline "
            f"(baseline={base_ub}, dependency={dep_ub})",
        )

    base_mem_stall = _to_int(base.get("tensor_program_mem_stall_cycles_total"))
    dep_mem_stall = _to_int(dep.get("tensor_program_mem_stall_cycles_total"))
    if dep_mem_stall <= base_mem_stall:
        return _fail(
            3,
            "[m54][P1] expected dependency mem stall > baseline "
            f"(baseline={base_mem_stall}, dependency={dep_mem_stall})",
        )

    base_any = _to_int(base.get("tensor_program_any_busy_cycles_total"))
    struct_any = _to_int(struct.get("tensor_program_any_busy_cycles_total"))
    dep_any = _to_int(dep.get("tensor_program_any_busy_cycles_total"))
    if struct_any < base_any:
        return _fail(
            3,
            "[m54][P1] expected structural any_busy_cycles >= baseline "
            f"(baseline={base_any}, structural={struct_any})",
        )
    if dep_any <= base_any:
        return _fail(
            3,
            "[m54][P1] expected dependency any_busy_cycles > baseline "
            f"(baseline={base_any}, dependency={dep_any})",
        )

    base_cfg = _load_cfg(base_p)
    struct_cfg = _load_cfg(struct_p)
    dep_cfg = _load_cfg(dep_p)
    base_issue = _to_int(base_cfg.get("tensor_program_issue_width"))
    struct_issue = _to_int(struct_cfg.get("tensor_program_issue_width"))
    dep_issue = _to_int(dep_cfg.get("tensor_program_issue_width"))
    if not (base_issue == struct_issue == dep_issue and base_issue > 0):
        return _fail(
            3,
            "[m54][P1] expected equal positive issue_width across scenarios "
            f"(baseline={base_issue}, structural={struct_issue}, dependency={dep_issue})",
        )

    prefix = f"[m54:{args.label}] " if args.label else "[m54] "
    print(f"{prefix}compute_cycles_total={base_compute} mac_ops_total={base_mac} issue_width={base_issue}")
    print(
        f"{prefix}structural_stall baseline={base_structural} structural={struct_structural} "
        f"bank_queue baseline={base_queue} structural={struct_queue}"
    )
    print(
        f"{prefix}dependency_stall ub baseline={base_ub} dependency={dep_ub} "
        f"mem baseline={base_mem_stall} dependency={dep_mem_stall}"
    )
    print(f"{prefix}program_any_busy baseline={base_any} structural={struct_any} dependency={dep_any}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
