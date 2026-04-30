#!/usr/bin/env python3
"""Validate M105 trace-v4 compiler bridge contract."""

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


def _load_tensor(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tensor = payload.get("tensor")
    return tensor if isinstance(tensor, dict) else None


def _load_params(spec_path: Path) -> Dict[str, Any]:
    try:
        payload = _load_json(spec_path)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    workload = payload.get("workload")
    if not isinstance(workload, dict):
        return {}
    params = workload.get("params")
    return params if isinstance(params, dict) else {}


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-summary", required=True)
    ap.add_argument("--dependency-summary", required=True)
    ap.add_argument("--baseline-spec", required=True)
    ap.add_argument("--dependency-spec", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    b_sum_p = Path(args.baseline_summary).expanduser().resolve()
    d_sum_p = Path(args.dependency_summary).expanduser().resolve()
    b_spec_p = Path(args.baseline_spec).expanduser().resolve()
    d_spec_p = Path(args.dependency_spec).expanduser().resolve()

    for p, name in (
        (b_sum_p, "baseline-summary"),
        (d_sum_p, "dependency-summary"),
        (b_spec_p, "baseline-spec"),
        (d_spec_p, "dependency-spec"),
    ):
        if not p.exists():
            return _fail(2, f"[m105][P0] missing --{name}: {p}")

    b_sum = _load_tensor(b_sum_p)
    d_sum = _load_tensor(d_sum_p)
    if b_sum is None or d_sum is None:
        return _fail(2, "[m105][P0] invalid summary schema: missing tensor object")

    b_params = _load_params(b_spec_p)
    d_params = _load_params(d_spec_p)

    b_ops_cfg = _to_int(b_params.get("tensor_trace_v4_op_count"))
    d_ops_cfg = _to_int(d_params.get("tensor_trace_v4_op_count"))
    b_dep_edges = _to_int(b_params.get("tensor_trace_v4_dependency_edges"))
    d_dep_edges = _to_int(d_params.get("tensor_trace_v4_dependency_edges"))
    b_windows = _to_int(b_params.get("tensor_trace_v4_tile_windows"))
    d_windows = _to_int(d_params.get("tensor_trace_v4_tile_windows"))
    b_barriers = _to_int(b_params.get("tensor_trace_v4_barrier_count"))
    d_barriers = _to_int(d_params.get("tensor_trace_v4_barrier_count"))
    b_res_windows = _to_int(b_params.get("tensor_trace_v4_resource_windows"))
    d_res_windows = _to_int(d_params.get("tensor_trace_v4_resource_windows"))
    if min(b_ops_cfg, d_ops_cfg) <= 0:
        return _fail(3, f"[m105][P1] expected trace_v4 op_count > 0 (baseline={b_ops_cfg}, dependency={d_ops_cfg})")
    if d_ops_cfg <= b_ops_cfg:
        return _fail(3, f"[m105][P1] expected dependency op_count > baseline (baseline={b_ops_cfg}, dependency={d_ops_cfg})")
    if d_dep_edges <= b_dep_edges:
        return _fail(3, f"[m105][P1] expected dependency dep_edges > baseline (baseline={b_dep_edges}, dependency={d_dep_edges})")
    if d_windows <= b_windows or d_barriers <= b_barriers or d_res_windows <= b_res_windows:
        return _fail(
            3,
            "[m105][P1] expected dependency metadata windows/barriers/resource_windows > baseline "
            f"(tile_windows={b_windows}/{d_windows}, barrier={b_barriers}/{d_barriers}, resource_windows={b_res_windows}/{d_res_windows})",
        )

    b_prog_ops = _to_int(b_sum.get("tensor_program_ops_total"))
    d_prog_ops = _to_int(d_sum.get("tensor_program_ops_total"))
    b_prog_iters = _to_int(b_sum.get("tensor_program_iters_total"))
    d_prog_iters = _to_int(d_sum.get("tensor_program_iters_total"))
    b_busy = _to_int(b_sum.get("tensor_program_any_busy_cycles_total"))
    d_busy = _to_int(d_sum.get("tensor_program_any_busy_cycles_total"))
    b_mem = _to_int(b_sum.get("tensor_mem_bytes_read_total"))
    d_mem = _to_int(d_sum.get("tensor_mem_bytes_read_total"))
    b_coll = _to_int(b_sum.get("tensor_collective_bytes_sent_total"))
    d_coll = _to_int(d_sum.get("tensor_collective_bytes_sent_total"))

    if b_prog_ops <= 0 or d_prog_ops <= 0:
        return _fail(3, f"[m105][P1] expected program_ops_total > 0 (baseline={b_prog_ops}, dependency={d_prog_ops})")
    if d_mem <= b_mem:
        return _fail(3, f"[m105][P1] expected dependency mem_bytes_read_total > baseline (baseline={b_mem}, dependency={d_mem})")
    if d_coll <= b_coll:
        return _fail(3, f"[m105][P1] expected dependency collective_bytes_sent > baseline (baseline={b_coll}, dependency={d_coll})")
    if d_busy <= b_busy:
        return _fail(
            3,
            "[m105][P1] expected dependency any_busy_cycles > baseline "
            f"(baseline={b_busy}, dependency={d_busy})",
        )

    prefix = f"[m105:{args.label}] " if args.label else "[m105] "
    print(
        f"{prefix}trace_meta op_count baseline={b_ops_cfg} dependency={d_ops_cfg} "
        f"dep_edges baseline={b_dep_edges} dependency={d_dep_edges}"
    )
    print(
        f"{prefix}trace_windows tile baseline={b_windows} dependency={d_windows} "
        f"barrier baseline={b_barriers} dependency={d_barriers} "
        f"resource_windows baseline={b_res_windows} dependency={d_res_windows}"
    )
    print(
        f"{prefix}program_ops baseline={b_prog_ops} dependency={d_prog_ops} "
        f"program_iters baseline={b_prog_iters} dependency={d_prog_iters} "
        f"any_busy baseline={b_busy} dependency={d_busy}"
    )
    print(f"{prefix}mem_read_bytes baseline={b_mem} dependency={d_mem} collective_bytes baseline={b_coll} dependency={d_coll}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
