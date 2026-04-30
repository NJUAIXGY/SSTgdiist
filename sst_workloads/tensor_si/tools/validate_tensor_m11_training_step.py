#!/usr/bin/env python3
"""Validate M11 (training-step program: GEMM + Allreduce) for tensor workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict


def _fail(msg: str) -> int:
    print(f"[m11] FAIL: {msg}")
    return 13


def _load_summary(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser().resolve()
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"summary root must be object: {p}")
    return payload


def _num(d: Dict[str, Any], key: str) -> float:
    v = d.get(key, 0)
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except Exception:
            return 0.0
    return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True, help="essential_summary_tensor_mesh.json path")
    args = ap.parse_args()

    try:
        summary = _load_summary(args.summary)
    except Exception as exc:
        return _fail(f"cannot load summary: {exc}")

    tensor = summary.get("tensor")
    if not isinstance(tensor, dict):
        return _fail("missing tensor section")

    iters = int(_num(tensor, "tensor_program_iters_total"))
    ops = int(_num(tensor, "tensor_program_ops_total"))
    macs = int(_num(tensor, "tensor_mac_ops_total"))
    epochs_done = int(_num(tensor, "tensor_collective_epoch_done_total"))

    if iters <= 0:
        return _fail("expected tensor_program_iters_total > 0")
    if ops <= 0:
        return _fail("expected tensor_program_ops_total > 0")
    if macs <= 0:
        return _fail("expected tensor_mac_ops_total > 0 (GEMM must execute)")
    if epochs_done <= 0:
        return _fail("expected tensor_collective_epoch_done_total > 0 (Allreduce must complete)")

    # M11 gate workload: 2 ops per iter (gemm + allreduce)
    if ops != 2 * iters:
        return _fail(f"expected program_ops_total == 2*program_iters_total but got {ops} != {2 * iters}")

    bytes_sent = int(_num(tensor, "tensor_collective_bytes_sent_total"))
    bytes_recv = int(_num(tensor, "tensor_collective_bytes_recv_total"))
    if bytes_sent <= 0:
        return _fail("expected tensor_collective_bytes_sent_total > 0")
    if bytes_recv <= 0:
        return _fail("expected tensor_collective_bytes_recv_total > 0")

    print("[m11] PASS")
    print(f"[m11] iters={iters} ops={ops} macs={macs} epochs_done={epochs_done}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

