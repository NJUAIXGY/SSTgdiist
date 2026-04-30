#!/usr/bin/env python3
"""Validate M65 trace-v2 compiler bridge contract."""

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


def _load_spec_params(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    workload = payload.get("workload")
    if not isinstance(workload, dict):
        return None
    params = workload.get("params")
    return params if isinstance(params, dict) else None


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

    bsum_p = Path(args.baseline_summary).expanduser().resolve()
    dsum_p = Path(args.dependency_summary).expanduser().resolve()
    bspec_p = Path(args.baseline_spec).expanduser().resolve()
    dspec_p = Path(args.dependency_spec).expanduser().resolve()

    for p, name in ((bsum_p, "baseline-summary"), (dsum_p, "dependency-summary"), (bspec_p, "baseline-spec"), (dspec_p, "dependency-spec")):
        if not p.exists():
            return _fail(2, f"[m65][P0] missing --{name}: {p}")

    bsum = _load_tensor(bsum_p)
    dsum = _load_tensor(dsum_p)
    bparams = _load_spec_params(bspec_p)
    dparams = _load_spec_params(dspec_p)
    if bsum is None or dsum is None or bparams is None or dparams is None:
        return _fail(2, "[m65][P0] invalid summary/spec schema")

    b_ops_cfg = _to_int(bparams.get("tensor_trace_v2_op_count"))
    d_ops_cfg = _to_int(dparams.get("tensor_trace_v2_op_count"))
    b_dep_edges = _to_int(bparams.get("tensor_trace_v2_dependency_edges"))
    d_dep_edges = _to_int(dparams.get("tensor_trace_v2_dependency_edges"))
    b_res_kinds = _to_int(bparams.get("tensor_trace_v2_resource_kinds"))
    d_res_kinds = _to_int(dparams.get("tensor_trace_v2_resource_kinds"))

    if b_ops_cfg <= 0 or d_ops_cfg <= 0:
        return _fail(3, f"[m65][P1] expected trace_v2_op_count > 0 (baseline={b_ops_cfg}, dependency={d_ops_cfg})")
    if d_ops_cfg <= b_ops_cfg:
        return _fail(3, f"[m65][P1] expected dependency op_count > baseline (baseline={b_ops_cfg}, dependency={d_ops_cfg})")
    if d_dep_edges <= b_dep_edges:
        return _fail(3, f"[m65][P1] expected dependency edges > baseline (baseline={b_dep_edges}, dependency={d_dep_edges})")
    if d_res_kinds < b_res_kinds:
        return _fail(3, f"[m65][P1] expected dependency resource_kinds >= baseline (baseline={b_res_kinds}, dependency={d_res_kinds})")

    b_ops_sum = _to_int(bsum.get("tensor_program_ops_total"))
    d_ops_sum = _to_int(dsum.get("tensor_program_ops_total"))
    b_fence_wait = _to_int(bsum.get("tensor_program_fence_wait_cycles_total"))
    d_fence_wait = _to_int(dsum.get("tensor_program_fence_wait_cycles_total"))
    b_coll = _to_int(bsum.get("tensor_collective_bytes_sent_total"))
    d_coll = _to_int(dsum.get("tensor_collective_bytes_sent_total"))

    if b_ops_sum <= 0 or d_ops_sum <= 0:
        return _fail(3, f"[m65][P1] expected program_ops_total > 0 (baseline={b_ops_sum}, dependency={d_ops_sum})")
    if d_ops_sum < b_ops_sum:
        return _fail(3, f"[m65][P1] expected dependency program_ops_total >= baseline (baseline={b_ops_sum}, dependency={d_ops_sum})")
    if d_coll <= b_coll:
        return _fail(3, f"[m65][P1] expected dependency collective_bytes_sent > baseline (baseline={b_coll}, dependency={d_coll})")

    prefix = f"[m65:{args.label}] " if args.label else "[m65] "
    print(
        f"{prefix}trace_v2 op_count baseline={b_ops_cfg} dependency={d_ops_cfg} "
        f"dep_edges baseline={b_dep_edges} dependency={d_dep_edges} resource_kinds baseline={b_res_kinds} dependency={d_res_kinds}"
    )
    print(
        f"{prefix}program_ops baseline={b_ops_sum} dependency={d_ops_sum} "
        f"fence_wait baseline={b_fence_wait} dependency={d_fence_wait} collective_bytes baseline={b_coll} dependency={d_coll}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
