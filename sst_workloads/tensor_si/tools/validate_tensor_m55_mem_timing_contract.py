#!/usr/bin/env python3
"""Validate M55 memory timing proxy-v2 contract.

M55 intent:
- Expose row/bank/queue timing observability beyond pure bandwidth/outstanding proxy.
- Keep compatibility-safe trend contracts across locality/conflict/parallel scenarios.
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


def _row_hit_ratio(tensor: Dict[str, Any]) -> float:
    hit = _to_int(tensor.get("tensor_mem_row_hit_total"))
    miss = _to_int(tensor.get("tensor_mem_row_miss_total"))
    conflict = _to_int(tensor.get("tensor_mem_row_conflict_total"))
    den = hit + miss + conflict
    if den <= 0:
        return 0.0
    return float(hit) / float(den)


def _avg_read_latency(tensor: Dict[str, Any]) -> float:
    return _avg(
        _to_int(tensor.get("tensor_mem_read_latency_cycles_total")),
        _to_int(tensor.get("tensor_mem_read_latency_samples_total")),
    )


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--locality", required=True, help="locality summary json")
    ap.add_argument("--conflict", required=True, help="conflict summary json")
    ap.add_argument("--parallel", required=True, help="parallel summary json")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    locality_p = Path(args.locality).expanduser().resolve()
    conflict_p = Path(args.conflict).expanduser().resolve()
    parallel_p = Path(args.parallel).expanduser().resolve()

    for path, flag in ((locality_p, "locality"), (conflict_p, "conflict"), (parallel_p, "parallel")):
        if not path.exists():
            return _fail(2, f"[m55][P0] missing --{flag} summary: {path}")

    locality = _load_tensor(locality_p)
    conflict = _load_tensor(conflict_p)
    parallel = _load_tensor(parallel_p)
    if locality is None or conflict is None or parallel is None:
        return _fail(2, "[m55][P0] invalid summary schema: missing tensor object")

    loc_cfg = _load_cfg(locality_p)
    con_cfg = _load_cfg(conflict_p)
    par_cfg = _load_cfg(parallel_p)

    loc_mode = str(loc_cfg.get("tensor_mem_timing_model", "")).strip().lower()
    con_mode = str(con_cfg.get("tensor_mem_timing_model", "")).strip().lower()
    par_mode = str(par_cfg.get("tensor_mem_timing_model", "")).strip().lower()
    if loc_mode != "proxy_v2" or con_mode != "proxy_v2" or par_mode != "proxy_v2":
        return _fail(
            3,
            "[m55][P1] expected tensor_mem_timing_model=proxy_v2 for all scenarios "
            f"(locality={loc_mode!r}, conflict={con_mode!r}, parallel={par_mode!r})",
        )

    loc_bytes = _to_int(locality.get("tensor_mem_bytes_read_total"))
    con_bytes = _to_int(conflict.get("tensor_mem_bytes_read_total"))
    par_bytes = _to_int(parallel.get("tensor_mem_bytes_read_total"))
    if min(loc_bytes, con_bytes, par_bytes) <= 0:
        return _fail(
            3,
            "[m55][P1] expected mem_bytes_read_total > 0 "
            f"(locality={loc_bytes}, conflict={con_bytes}, parallel={par_bytes})",
        )
    if not (loc_bytes == con_bytes == par_bytes):
        return _fail(
            3,
            "[m55][P1] expected mem_bytes_read_total match across scenarios "
            f"(locality={loc_bytes}, conflict={con_bytes}, parallel={par_bytes})",
        )

    loc_compute = _to_int(locality.get("tensor_compute_cycles_total"))
    con_compute = _to_int(conflict.get("tensor_compute_cycles_total"))
    par_compute = _to_int(parallel.get("tensor_compute_cycles_total"))
    if min(loc_compute, con_compute, par_compute) <= 0:
        return _fail(
            3,
            "[m55][P1] expected compute_cycles_total > 0 "
            f"(locality={loc_compute}, conflict={con_compute}, parallel={par_compute})",
        )
    if not (loc_compute == con_compute == par_compute):
        return _fail(
            3,
            "[m55][P1] expected compute_cycles_total match across scenarios "
            f"(locality={loc_compute}, conflict={con_compute}, parallel={par_compute})",
        )

    loc_mac = _to_int(locality.get("tensor_mac_ops_total"))
    con_mac = _to_int(conflict.get("tensor_mac_ops_total"))
    par_mac = _to_int(parallel.get("tensor_mac_ops_total"))
    if min(loc_mac, con_mac, par_mac) <= 0:
        return _fail(
            3,
            "[m55][P1] expected mac_ops_total > 0 "
            f"(locality={loc_mac}, conflict={con_mac}, parallel={par_mac})",
        )
    if not (loc_mac == con_mac == par_mac):
        return _fail(
            3,
            "[m55][P1] expected mac_ops_total match across scenarios "
            f"(locality={loc_mac}, conflict={con_mac}, parallel={par_mac})",
        )

    loc_issue = _to_int(loc_cfg.get("tensor_program_issue_width"))
    con_issue = _to_int(con_cfg.get("tensor_program_issue_width"))
    par_issue = _to_int(par_cfg.get("tensor_program_issue_width"))
    if not (loc_issue == con_issue == par_issue and loc_issue > 0):
        return _fail(
            3,
            "[m55][P1] expected equal positive issue_width across scenarios "
            f"(locality={loc_issue}, conflict={con_issue}, parallel={par_issue})",
        )

    loc_hit_ratio = _row_hit_ratio(locality)
    con_hit_ratio = _row_hit_ratio(conflict)
    par_hit_ratio = _row_hit_ratio(parallel)
    if loc_hit_ratio <= con_hit_ratio:
        return _fail(
            3,
            "[m55][P1] expected locality row_hit_ratio > conflict "
            f"(locality={loc_hit_ratio:.4f}, conflict={con_hit_ratio:.4f})",
        )
    if loc_hit_ratio < par_hit_ratio:
        return _fail(
            3,
            "[m55][P1] expected locality row_hit_ratio >= parallel "
            f"(locality={loc_hit_ratio:.4f}, parallel={par_hit_ratio:.4f})",
        )

    loc_conflicts = _to_int(locality.get("tensor_mem_row_conflict_total"))
    con_conflicts = _to_int(conflict.get("tensor_mem_row_conflict_total"))
    par_conflicts = _to_int(parallel.get("tensor_mem_row_conflict_total"))
    if con_conflicts <= loc_conflicts:
        return _fail(
            3,
            "[m55][P1] expected conflict row_conflict_total > locality "
            f"(locality={loc_conflicts}, conflict={con_conflicts})",
        )
    if con_conflicts <= par_conflicts:
        return _fail(
            3,
            "[m55][P1] expected conflict row_conflict_total > parallel "
            f"(parallel={par_conflicts}, conflict={con_conflicts})",
        )

    loc_fifo = _to_int(locality.get("tensor_mem_sched_fifo_pick_total"))
    loc_frfcfs = _to_int(locality.get("tensor_mem_sched_frfcfs_pick_total"))
    con_fifo = _to_int(conflict.get("tensor_mem_sched_fifo_pick_total"))
    con_frfcfs = _to_int(conflict.get("tensor_mem_sched_frfcfs_pick_total"))
    par_fifo = _to_int(parallel.get("tensor_mem_sched_fifo_pick_total"))
    par_frfcfs = _to_int(parallel.get("tensor_mem_sched_frfcfs_pick_total"))

    if loc_frfcfs <= 0 or loc_fifo != 0:
        return _fail(
            3,
            "[m55][P1] expected locality FRFCFS signature (frfcfs>0, fifo=0) "
            f"(fifo={loc_fifo}, frfcfs={loc_frfcfs})",
        )
    if con_fifo <= 0 or con_frfcfs != 0:
        return _fail(
            3,
            "[m55][P1] expected conflict FIFO signature (fifo>0, frfcfs=0) "
            f"(fifo={con_fifo}, frfcfs={con_frfcfs})",
        )
    if par_frfcfs <= 0 or par_fifo != 0:
        return _fail(
            3,
            "[m55][P1] expected parallel FRFCFS signature (frfcfs>0, fifo=0) "
            f"(fifo={par_fifo}, frfcfs={par_frfcfs})",
        )

    loc_queue_wait = _to_int(locality.get("tensor_mem_bank_queue_wait_cycles_total"))
    con_queue_wait = _to_int(conflict.get("tensor_mem_bank_queue_wait_cycles_total"))
    par_queue_wait = _to_int(parallel.get("tensor_mem_bank_queue_wait_cycles_total"))
    if loc_queue_wait <= con_queue_wait:
        return _fail(
            3,
            "[m55][P1] expected locality queue_wait > conflict "
            f"(locality={loc_queue_wait}, conflict={con_queue_wait})",
        )
    if con_queue_wait <= par_queue_wait:
        return _fail(
            3,
            "[m55][P1] expected conflict queue_wait > parallel "
            f"(conflict={con_queue_wait}, parallel={par_queue_wait})",
        )

    loc_proxy_delay = _to_int(locality.get("tensor_mem_proxy_delay_cycles_total"))
    con_proxy_delay = _to_int(conflict.get("tensor_mem_proxy_delay_cycles_total"))
    par_proxy_delay = _to_int(parallel.get("tensor_mem_proxy_delay_cycles_total"))
    if loc_proxy_delay <= con_proxy_delay:
        return _fail(
            3,
            "[m55][P1] expected locality proxy_delay_total > conflict "
            f"(locality={loc_proxy_delay}, conflict={con_proxy_delay})",
        )
    if con_proxy_delay <= par_proxy_delay:
        return _fail(
            3,
            "[m55][P1] expected conflict proxy_delay_total > parallel "
            f"(parallel={par_proxy_delay}, conflict={con_proxy_delay})",
        )

    loc_lat = _avg_read_latency(locality)
    con_lat = _avg_read_latency(conflict)
    par_lat = _avg_read_latency(parallel)
    if loc_lat <= par_lat:
        return _fail(
            3,
            "[m55][P1] expected locality avg_read_latency > parallel "
            f"(locality={loc_lat:.3f}, parallel={par_lat:.3f})",
        )
    if par_lat < con_lat:
        return _fail(
            3,
            "[m55][P1] expected parallel avg_read_latency >= conflict "
            f"(parallel={par_lat:.3f}, conflict={con_lat:.3f})",
        )

    loc_refresh = _to_int(locality.get("tensor_mem_refresh_block_cycles_total"))
    con_refresh = _to_int(conflict.get("tensor_mem_refresh_block_cycles_total"))
    par_refresh = _to_int(parallel.get("tensor_mem_refresh_block_cycles_total"))
    if con_refresh <= loc_refresh:
        return _fail(
            3,
            "[m55][P1] expected conflict refresh_block_cycles > locality "
            f"(locality={loc_refresh}, conflict={con_refresh})",
        )
    if con_refresh <= par_refresh:
        return _fail(
            3,
            "[m55][P1] expected conflict refresh_block_cycles > parallel "
            f"(parallel={par_refresh}, conflict={con_refresh})",
        )

    prefix = f"[m55:{args.label}] " if args.label else "[m55] "
    print(
        f"{prefix}mem_bytes_read_total={loc_bytes} compute_cycles_total={loc_compute} "
        f"mac_ops_total={loc_mac} issue_width={loc_issue}"
    )
    print(
        f"{prefix}row_hit_ratio locality={loc_hit_ratio:.4f} conflict={con_hit_ratio:.4f} parallel={par_hit_ratio:.4f} "
        f"row_conflict locality={loc_conflicts} conflict={con_conflicts} parallel={par_conflicts}"
    )
    print(
        f"{prefix}queue_wait locality={loc_queue_wait} conflict={con_queue_wait} parallel={par_queue_wait} "
        f"proxy_delay locality={loc_proxy_delay} conflict={con_proxy_delay} parallel={par_proxy_delay}"
    )
    print(
        f"{prefix}sched locality(fifo={loc_fifo},frfcfs={loc_frfcfs}) "
        f"conflict(fifo={con_fifo},frfcfs={con_frfcfs}) "
        f"parallel(fifo={par_fifo},frfcfs={par_frfcfs})"
    )
    print(
        f"{prefix}avg_read_latency locality={loc_lat:.3f} conflict={con_lat:.3f} parallel={par_lat:.3f} "
        f"refresh_block locality={loc_refresh} conflict={con_refresh} parallel={par_refresh}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
