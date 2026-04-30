#!/usr/bin/env python3
"""Validate M61 memory command proxy_v3 contract."""

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


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _check_identity(name: str, tensor: Dict[str, Any]) -> str | None:
    cmd_rdwr = _to_int(tensor.get("tensor_mem_cmd_rdwr_total"))
    cmd_act = _to_int(tensor.get("tensor_mem_cmd_act_total"))
    cmd_pre = _to_int(tensor.get("tensor_mem_cmd_pre_total"))
    cmd_issue = _to_int(tensor.get("tensor_mem_cmd_issue_total"))
    expected_issue = cmd_rdwr + cmd_act + cmd_pre
    if cmd_issue != expected_issue:
        return (
            f"[m61][P1] {name}: expected cmd_issue == cmd_rdwr+cmd_act+cmd_pre "
            f"(cmd_issue={cmd_issue}, expected={expected_issue})"
        )
    return None


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--locality", required=True)
    ap.add_argument("--conflict", required=True)
    ap.add_argument("--parallel", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    loc_p = Path(args.locality).expanduser().resolve()
    con_p = Path(args.conflict).expanduser().resolve()
    par_p = Path(args.parallel).expanduser().resolve()

    for p, name in ((loc_p, "locality"), (con_p, "conflict"), (par_p, "parallel")):
        if not p.exists():
            return _fail(2, f"[m61][P0] missing --{name} summary: {p}")

    loc = _load_tensor(loc_p)
    con = _load_tensor(con_p)
    par = _load_tensor(par_p)
    if loc is None or con is None or par is None:
        return _fail(2, "[m61][P0] invalid summary schema: missing tensor object")

    loc_mode = str(_load_cfg(loc_p).get("tensor_mem_timing_model", "")).strip().lower()
    con_mode = str(_load_cfg(con_p).get("tensor_mem_timing_model", "")).strip().lower()
    par_mode = str(_load_cfg(par_p).get("tensor_mem_timing_model", "")).strip().lower()
    if loc_mode != "proxy_v3" or con_mode != "proxy_v3" or par_mode != "proxy_v3":
        return _fail(
            3,
            "[m61][P1] expected tensor_mem_timing_model=proxy_v3 for all scenarios "
            f"(locality={loc_mode!r}, conflict={con_mode!r}, parallel={par_mode!r})",
        )

    for name, tensor in (("locality", loc), ("conflict", con), ("parallel", par)):
        read_samples = _to_int(tensor.get("tensor_mem_read_latency_samples_total"))
        cmd_issue = _to_int(tensor.get("tensor_mem_cmd_issue_total"))
        if read_samples <= 0:
            return _fail(3, f"[m61][P1] {name}: expected read_latency_samples > 0")
        if cmd_issue <= 0:
            return _fail(3, f"[m61][P1] {name}: expected cmd_issue_total > 0")
        msg = _check_identity(name, tensor)
        if msg is not None:
            return _fail(3, msg)

    loc_bus_wait = _to_int(loc.get("tensor_mem_cmd_bus_wait_cycles_total"))
    con_bus_wait = _to_int(con.get("tensor_mem_cmd_bus_wait_cycles_total"))
    par_bus_wait = _to_int(par.get("tensor_mem_cmd_bus_wait_cycles_total"))

    loc_queue_slots_avg = _to_float(loc.get("tensor_mem_cmd_queue_slots_avg"))
    con_queue_slots_avg = _to_float(con.get("tensor_mem_cmd_queue_slots_avg"))
    par_queue_slots_avg = _to_float(par.get("tensor_mem_cmd_queue_slots_avg"))

    loc_qmax = _to_int(loc.get("tensor_mem_cmd_queue_depth_max"))
    con_qmax = _to_int(con.get("tensor_mem_cmd_queue_depth_max"))
    par_qmax = _to_int(par.get("tensor_mem_cmd_queue_depth_max"))

    loc_proxy_avg = _to_float(loc.get("tensor_mem_proxy_delay_avg_cycles"))
    con_proxy_avg = _to_float(con.get("tensor_mem_proxy_delay_avg_cycles"))
    par_proxy_avg = _to_float(par.get("tensor_mem_proxy_delay_avg_cycles"))

    loc_fill = loc_queue_slots_avg / max(1.0, float(loc_qmax))
    con_fill = con_queue_slots_avg / max(1.0, float(con_qmax))
    par_fill = par_queue_slots_avg / max(1.0, float(par_qmax))

    if con_bus_wait <= loc_bus_wait:
        return _fail(3, f"[m61][P1] expected conflict cmd_bus_wait > locality (locality={loc_bus_wait}, conflict={con_bus_wait})")
    if con_fill < loc_fill:
        return _fail(
            3,
            "[m61][P1] expected conflict normalized_queue_fill >= locality "
            f"(locality={loc_fill:.6f}, conflict={con_fill:.6f})",
        )
    if con_proxy_avg <= loc_proxy_avg:
        return _fail(
            3,
            "[m61][P1] expected conflict proxy_delay_avg > locality "
            f"(locality={loc_proxy_avg:.3f}, conflict={con_proxy_avg:.3f})",
        )
    if par_bus_wait >= con_bus_wait:
        return _fail(
            3,
            "[m61][P1] expected parallel cmd_bus_wait < conflict "
            f"(parallel={par_bus_wait}, conflict={con_bus_wait})",
        )
    if par_proxy_avg >= con_proxy_avg:
        return _fail(
            3,
            "[m61][P1] expected parallel proxy_delay_avg < conflict "
            f"(parallel={par_proxy_avg:.3f}, conflict={con_proxy_avg:.3f})",
        )

    prefix = f"[m61:{args.label}] " if args.label else "[m61] "
    print(
        f"{prefix}cmd_bus_wait locality={loc_bus_wait} conflict={con_bus_wait} parallel={par_bus_wait} "
        f"queue_slots_avg locality={loc_queue_slots_avg:.3f} conflict={con_queue_slots_avg:.3f} parallel={par_queue_slots_avg:.3f}"
    )
    print(
        f"{prefix}queue_depth_max locality={loc_qmax} conflict={con_qmax} parallel={par_qmax} "
        f"normalized_fill locality={loc_fill:.6f} conflict={con_fill:.6f} parallel={par_fill:.6f}"
    )
    print(
        f"{prefix}proxy_delay_avg locality={loc_proxy_avg:.3f} "
        f"conflict={con_proxy_avg:.3f} parallel={par_proxy_avg:.3f}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
