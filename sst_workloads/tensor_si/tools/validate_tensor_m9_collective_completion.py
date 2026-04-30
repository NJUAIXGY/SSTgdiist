#!/usr/bin/env python3
"""Validate M9 (collective completion) expectations for tensor workload.

M9 adds a notion of blocking-collective epoch completion (for ring_chunked / torus_2d_rs_ag),
exported via:
  - tensor_collective_epoch_done_total
  - tensor_collective_epoch_latency_cycles_{total,max}

This validator is contract-oriented: it only checks that a blocking allreduce program
reaches completion and the epoch counters are non-zero/stable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _fail(msg: str) -> int:
    print(f"[m9] FAIL: {msg}")
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


def _tensor(summary: Dict[str, Any], label: str) -> Tuple[bool, str, Dict[str, Any]]:
    t = summary.get("tensor")
    if not isinstance(t, dict):
        return False, f"{label}: missing tensor section", {}
    return True, "", t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ring", required=True, help="M9 scenario: ring_chunked blocking allreduce completion")
    ap.add_argument("--torus-2d", required=True, help="M9 scenario: torus_2d_rs_ag blocking allreduce completion")
    args = ap.parse_args()

    datasets = {
        "ring": _load_summary(args.ring),
        "torus_2d": _load_summary(args.torus_2d),
    }

    tensors: Dict[str, Dict[str, Any]] = {}
    for label, summary in datasets.items():
        ok, reason, tensor = _tensor(summary, label)
        if not ok:
            return _fail(reason)
        tensors[label] = tensor

    ring = tensors["ring"]
    torus = tensors["torus_2d"]

    if int(_num(ring, "tensor_collective_algo_id")) != 1:
        return _fail("ring: expected tensor_collective_algo_id == 1 (ring_chunked)")
    if int(_num(torus, "tensor_collective_algo_id")) != 2:
        return _fail("torus_2d: expected tensor_collective_algo_id == 2 (torus_2d_rs_ag)")

    for label, t in (("ring", ring), ("torus_2d", torus)):
        iters = int(_num(t, "tensor_program_iters_total"))
        ops = int(_num(t, "tensor_program_ops_total"))
        done = int(_num(t, "tensor_collective_epoch_done_total"))

        if iters <= 0:
            return _fail(f"{label}: expected tensor_program_iters_total > 0")
        if ops <= 0:
            return _fail(f"{label}: expected tensor_program_ops_total > 0")
        if done <= 0:
            return _fail(f"{label}: expected tensor_collective_epoch_done_total > 0")

        # For the M9 gate workload (single blocking allreduce op per program iteration),
        # these totals should match under PE aggregation.
        if done != iters:
            return _fail(f"{label}: expected epoch_done_total == program_iters_total but got {done} != {iters}")
        if ops != iters:
            return _fail(f"{label}: expected program_ops_total == program_iters_total but got {ops} != {iters}")

        bytes_sent = int(_num(t, "tensor_collective_bytes_sent_total"))
        bytes_recv = int(_num(t, "tensor_collective_bytes_recv_total"))
        if bytes_sent <= 0:
            return _fail(f"{label}: expected tensor_collective_bytes_sent_total > 0")
        if bytes_recv <= 0:
            return _fail(f"{label}: expected tensor_collective_bytes_recv_total > 0")

    print("[m9] PASS")
    print(
        "[m9] ring:"
        f" iters={int(_num(ring, 'tensor_program_iters_total'))}"
        f" epochs_done={int(_num(ring, 'tensor_collective_epoch_done_total'))}"
        f" epoch_lat_total={int(_num(ring, 'tensor_collective_epoch_latency_cycles_total'))}"
        f" epoch_lat_max={int(_num(ring, 'tensor_collective_epoch_latency_cycles_max'))}"
    )
    print(
        "[m9] torus_2d:"
        f" iters={int(_num(torus, 'tensor_program_iters_total'))}"
        f" epochs_done={int(_num(torus, 'tensor_collective_epoch_done_total'))}"
        f" epoch_lat_total={int(_num(torus, 'tensor_collective_epoch_latency_cycles_total'))}"
        f" epoch_lat_max={int(_num(torus, 'tensor_collective_epoch_latency_cycles_max'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

