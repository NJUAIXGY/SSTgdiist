#!/usr/bin/env python3
"""Validate M57 memory command-lite contract."""

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
    row_hit = _to_int(tensor.get("tensor_mem_row_hit_total"))
    row_miss = _to_int(tensor.get("tensor_mem_row_miss_total"))
    row_conf = _to_int(tensor.get("tensor_mem_row_conflict_total"))
    row_total = row_hit + row_miss + row_conf

    cmd_act = _to_int(tensor.get("tensor_mem_cmd_act_total"))
    cmd_pre = _to_int(tensor.get("tensor_mem_cmd_pre_total"))
    cmd_rdwr = _to_int(tensor.get("tensor_mem_cmd_rdwr_total"))

    if cmd_rdwr != row_total:
        return (
            f"[m57][P1] {name}: expected cmd_rdwr == row_total "
            f"(cmd_rdwr={cmd_rdwr}, row_total={row_total})"
        )
    if cmd_act != (row_miss + row_conf):
        return (
            f"[m57][P1] {name}: expected cmd_act == row_miss+row_conflict "
            f"(cmd_act={cmd_act}, row_miss+row_conflict={row_miss + row_conf})"
        )
    if cmd_pre != row_conf:
        return (
            f"[m57][P1] {name}: expected cmd_pre == row_conflict "
            f"(cmd_pre={cmd_pre}, row_conflict={row_conf})"
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
            return _fail(2, f"[m57][P0] missing --{name} summary: {p}")

    loc = _load_tensor(loc_p)
    con = _load_tensor(con_p)
    par = _load_tensor(par_p)
    if loc is None or con is None or par is None:
        return _fail(2, "[m57][P0] invalid summary schema: missing tensor object")

    loc_mode = str(_load_cfg(loc_p).get("tensor_mem_timing_model", "")).strip().lower()
    con_mode = str(_load_cfg(con_p).get("tensor_mem_timing_model", "")).strip().lower()
    par_mode = str(_load_cfg(par_p).get("tensor_mem_timing_model", "")).strip().lower()
    if loc_mode != "proxy_v2" or con_mode != "proxy_v2" or par_mode != "proxy_v2":
        return _fail(
            3,
            "[m57][P1] expected tensor_mem_timing_model=proxy_v2 for all scenarios "
            f"(locality={loc_mode!r}, conflict={con_mode!r}, parallel={par_mode!r})",
        )

    for name, tensor in (("locality", loc), ("conflict", con), ("parallel", par)):
        read_samples = _to_int(tensor.get("tensor_mem_read_latency_samples_total"))
        if read_samples <= 0:
            return _fail(3, f"[m57][P1] {name}: expected read_latency_samples > 0")
        msg = _check_identity(name, tensor)
        if msg is not None:
            return _fail(3, msg)

    loc_pre = _to_int(loc.get("tensor_mem_cmd_pre_total"))
    con_pre = _to_int(con.get("tensor_mem_cmd_pre_total"))
    par_pre = _to_int(par.get("tensor_mem_cmd_pre_total"))

    loc_act = _to_int(loc.get("tensor_mem_cmd_act_total"))
    con_act = _to_int(con.get("tensor_mem_cmd_act_total"))

    loc_conflict = _to_int(loc.get("tensor_mem_row_conflict_total"))
    con_conflict = _to_int(con.get("tensor_mem_row_conflict_total"))
    par_conflict = _to_int(par.get("tensor_mem_row_conflict_total"))

    loc_row_service_avg = _to_float(loc.get("tensor_mem_row_service_avg_cycles"))
    con_row_service_avg = _to_float(con.get("tensor_mem_row_service_avg_cycles"))
    par_row_service_avg = _to_float(par.get("tensor_mem_row_service_avg_cycles"))

    if con_pre <= loc_pre:
        return _fail(3, f"[m57][P1] expected conflict cmd_pre > locality (locality={loc_pre}, conflict={con_pre})")
    if con_pre <= par_pre:
        return _fail(3, f"[m57][P1] expected conflict cmd_pre > parallel (parallel={par_pre}, conflict={con_pre})")
    if con_act <= loc_act:
        return _fail(3, f"[m57][P1] expected conflict cmd_act > locality (locality={loc_act}, conflict={con_act})")
    if con_conflict <= loc_conflict or con_conflict <= par_conflict:
        return _fail(
            3,
            "[m57][P1] expected conflict row_conflict dominance "
            f"(locality={loc_conflict}, conflict={con_conflict}, parallel={par_conflict})",
        )
    if con_row_service_avg <= loc_row_service_avg:
        return _fail(
            3,
            "[m57][P1] expected conflict row_service_avg > locality "
            f"(locality={loc_row_service_avg:.3f}, conflict={con_row_service_avg:.3f})",
        )

    prefix = f"[m57:{args.label}] " if args.label else "[m57] "
    print(
        f"{prefix}cmd_pre locality={loc_pre} conflict={con_pre} parallel={par_pre} "
        f"cmd_act locality={loc_act} conflict={con_act}"
    )
    print(
        f"{prefix}row_conflict locality={loc_conflict} conflict={con_conflict} parallel={par_conflict} "
        f"row_service_avg locality={loc_row_service_avg:.3f} conflict={con_row_service_avg:.3f} parallel={par_row_service_avg:.3f}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
