#!/usr/bin/env python3
"""Validate M51 trace replay contract (trace -> spec -> summary)."""

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


def _trace_ops(trace: Dict[str, Any]) -> List[str]:
    program = trace.get("program")
    if not isinstance(program, list):
        return []
    out: List[str] = []
    for item in program:
        if not isinstance(item, dict):
            continue
        name = str(item.get("op", "")).strip().lower()
        if name:
            out.append(name)
    return out


def _spec_ops(spec: Dict[str, Any]) -> List[str]:
    wl = spec.get("workload") if isinstance(spec.get("workload"), dict) else {}
    prg = wl.get("program") if isinstance(wl.get("program"), dict) else {}
    ops = prg.get("ops") if isinstance(prg.get("ops"), list) else []
    out: List[str] = []
    for item in ops:
        if not isinstance(item, dict):
            continue
        name = str(item.get("op_type", "")).strip().lower()
        if name:
            out.append(name)
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="trace input json")
    ap.add_argument("--spec", required=True, help="compiled spec json")
    ap.add_argument("--summary", required=True, help="run summary json")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    trace_p = Path(args.trace).expanduser().resolve()
    spec_p = Path(args.spec).expanduser().resolve()
    sum_p = Path(args.summary).expanduser().resolve()

    for p, flag in ((trace_p, "--trace"), (spec_p, "--spec"), (sum_p, "--summary")):
        if not p.exists():
            return _fail(2, f"[m51][P0] missing {flag}: {p}")

    try:
        trace = _load_json(trace_p)
        spec = _load_json(spec_p)
        summary = _load_json(sum_p)
    except Exception as exc:
        return _fail(2, f"[m51][P0] json parse failed: {exc}")

    trace_ops = _trace_ops(trace)
    spec_ops = _spec_ops(spec)
    if not trace_ops:
        return _fail(3, "[m51][P1] trace has no valid ops")
    if not spec_ops:
        return _fail(3, "[m51][P1] compiled spec has no valid workload.program.ops")
    if len(trace_ops) != len(spec_ops):
        return _fail(3, f"[m51][P1] op count mismatch trace={len(trace_ops)} spec={len(spec_ops)}")

    mapping = {"op": "op", "dma_read": "dma_read", "dma_write": "dma_write", "gemm_ub": "gemm_ub", "allreduce": "allreduce", "softmax": "softmax", "fence": "fence"}
    for i, (t, s) in enumerate(zip(trace_ops, spec_ops)):
        if mapping.get(t, t) != s:
            return _fail(3, f"[m51][P1] op[{i}] mismatch trace={t} spec={s}")

    tensor = summary.get("tensor") if isinstance(summary.get("tensor"), dict) else None
    if tensor is None:
        return _fail(3, "[m51][P1] summary missing tensor object")

    ops_total = _to_int(tensor.get("tensor_program_ops_total"))
    if ops_total <= 0:
        return _fail(3, f"[m51][P1] tensor_program_ops_total must be > 0 (got {ops_total})")

    if "allreduce" in trace_ops:
        coll = _to_int(tensor.get("tensor_collective_bytes_sent_total"))
        if coll <= 0:
            return _fail(3, f"[m51][P1] expected collective bytes > 0 for trace with allreduce (got {coll})")

    prefix = f"[m51:{args.label}] " if args.label else "[m51] "
    print(f"{prefix}ops={len(trace_ops)} tensor_program_ops_total={ops_total}")
    print(f"{prefix}allreduce_in_trace={1 if 'allreduce' in trace_ops else 0}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
