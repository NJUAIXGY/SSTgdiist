#!/usr/bin/env python3
"""Validate M8 (2D torus + hierarchical allreduce) trend expectations for tensor workload.

M8 introduces:
- noc.type=merlin_torus with a configurable 2D shape (XxY)
- tensor_collective_algo=torus_2d_rs_ag (2D RS/AG staged allreduce)

This validator is trend/contract oriented (DSE-friendly), not cycle-accurate calibration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _fail(msg: str) -> int:
    print(f"[m8] FAIL: {msg}")
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


def _hop(dim: int) -> int:
    # Mirror C++: avoid a 0-hop stage when dim <= 1.
    return int(dim - 1) if int(dim) > 1 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ring", required=True, help="M8 scenario: ring_chunked baseline on torus")
    ap.add_argument("--torus-2d", required=True, help="M8 scenario: torus_2d_rs_ag baseline")
    ap.add_argument("--chunk64k", required=True, help="M8 scenario: torus_2d_rs_ag with larger chunk")
    ap.add_argument("--inflight4", required=True, help="M8 scenario: torus_2d_rs_ag with larger inflight window")
    args = ap.parse_args()

    datasets = {
        "ring": _load_summary(args.ring),
        "torus_2d": _load_summary(args.torus_2d),
        "chunk64k": _load_summary(args.chunk64k),
        "inflight4": _load_summary(args.inflight4),
    }

    tensors: Dict[str, Dict[str, Any]] = {}
    for label, summary in datasets.items():
        ok, reason, tensor = _tensor(summary, label)
        if not ok:
            return _fail(reason)
        tensors[label] = tensor

    ring = tensors["ring"]
    torus_2d = tensors["torus_2d"]
    chunk64k = tensors["chunk64k"]
    inflight4 = tensors["inflight4"]

    if int(_num(ring, "tensor_collective_algo_id")) != 1:
        return _fail("ring: expected tensor_collective_algo_id == 1 (ring_chunked)")
    if int(_num(torus_2d, "tensor_collective_algo_id")) != 2:
        return _fail("torus_2d: expected tensor_collective_algo_id == 2 (torus_2d_rs_ag)")
    if int(_num(chunk64k, "tensor_collective_algo_id")) != 2:
        return _fail("chunk64k: expected tensor_collective_algo_id == 2 (torus_2d_rs_ag)")
    if int(_num(inflight4, "tensor_collective_algo_id")) != 2:
        return _fail("inflight4: expected tensor_collective_algo_id == 2 (torus_2d_rs_ag)")

    # Baseline comparison: 2D staged allreduce should have fewer steps than global ring for the same chunking.
    ring_steps = int(_num(ring, "tensor_collective_ring_steps_total"))
    torus_steps = int(_num(torus_2d, "tensor_collective_ring_steps_total"))
    if ring_steps <= 0:
        return _fail("ring: expected tensor_collective_ring_steps_total > 0")
    if torus_steps <= 0:
        return _fail("torus_2d: expected tensor_collective_ring_steps_total > 0")
    if torus_steps >= ring_steps:
        return _fail(f"expected torus_2d steps < ring steps but got {torus_steps} >= {ring_steps}")

    # 2D staged steps must match the configured dims (exported via effective_config.json -> summary).
    dim_x = int(_num(torus_2d, "tensor_collective_2d_dim_x"))
    dim_y = int(_num(torus_2d, "tensor_collective_2d_dim_y"))
    if dim_x <= 0 or dim_y <= 0:
        return _fail("torus_2d: expected tensor_collective_2d_dim_x/y > 0")
    chunks = int(_num(torus_2d, "tensor_collective_chunk_groups_total"))
    if chunks <= 0:
        return _fail("torus_2d: expected tensor_collective_chunk_groups_total > 0")

    row_hop = _hop(dim_x)
    col_hop = _hop(dim_y)
    expected_steps_per_chunk = 2 * (row_hop + col_hop)
    expected_total_steps = expected_steps_per_chunk * chunks

    got_row_rs = int(_num(torus_2d, "tensor_collective_2d_row_rs_steps_total"))
    got_col_rs = int(_num(torus_2d, "tensor_collective_2d_col_rs_steps_total"))
    got_col_ag = int(_num(torus_2d, "tensor_collective_2d_col_ag_steps_total"))
    got_row_ag = int(_num(torus_2d, "tensor_collective_2d_row_ag_steps_total"))
    got_sum = got_row_rs + got_col_rs + got_col_ag + got_row_ag

    if got_row_rs != row_hop * chunks:
        return _fail(f"torus_2d: row_rs_steps mismatch: got {got_row_rs} expected {row_hop * chunks}")
    if got_col_rs != col_hop * chunks:
        return _fail(f"torus_2d: col_rs_steps mismatch: got {got_col_rs} expected {col_hop * chunks}")
    if got_col_ag != col_hop * chunks:
        return _fail(f"torus_2d: col_ag_steps mismatch: got {got_col_ag} expected {col_hop * chunks}")
    if got_row_ag != row_hop * chunks:
        return _fail(f"torus_2d: row_ag_steps mismatch: got {got_row_ag} expected {row_hop * chunks}")
    if got_sum != torus_steps:
        return _fail(f"torus_2d: expected sum(stage_steps) == ring_steps but got {got_sum} != {torus_steps}")
    if torus_steps != expected_total_steps:
        return _fail(f"torus_2d: expected ring_steps == {expected_total_steps} but got {torus_steps}")

    # Stage-by-stage byte attribution must sum to total collective bytes sent.
    bytes_sent = int(_num(torus_2d, "tensor_collective_bytes_sent_total"))
    stage_bytes = (
        int(_num(torus_2d, "tensor_collective_2d_row_rs_bytes_sent_total"))
        + int(_num(torus_2d, "tensor_collective_2d_col_rs_bytes_sent_total"))
        + int(_num(torus_2d, "tensor_collective_2d_col_ag_bytes_sent_total"))
        + int(_num(torus_2d, "tensor_collective_2d_row_ag_bytes_sent_total"))
    )
    if bytes_sent <= 0:
        return _fail("torus_2d: expected tensor_collective_bytes_sent_total > 0")
    if stage_bytes != bytes_sent:
        return _fail(f"torus_2d: stage bytes mismatch: {stage_bytes} != bytes_sent {bytes_sent}")

    # Chunk sweep: larger chunk should reduce chunk groups and total steps.
    chunks_64k = int(_num(chunk64k, "tensor_collective_chunk_groups_total"))
    steps_64k = int(_num(chunk64k, "tensor_collective_ring_steps_total"))
    if chunks_64k <= 0 or steps_64k <= 0:
        return _fail("chunk64k: expected chunk_groups_total and ring_steps_total > 0")
    if chunks_64k >= chunks:
        return _fail(f"chunk64k: expected fewer chunks than baseline but got {chunks_64k} >= {chunks}")
    if steps_64k >= torus_steps:
        return _fail(f"chunk64k: expected fewer steps than baseline but got {steps_64k} >= {torus_steps}")

    # Inflight sweep: increasing window should not increase credit stall (heuristic trend).
    stall_1 = int(_num(torus_2d, "tensor_collective_credit_stall_cycles_total"))
    stall_4 = int(_num(inflight4, "tensor_collective_credit_stall_cycles_total"))
    if stall_4 > stall_1:
        return _fail(f"inflight4: expected credit stall <= baseline but got {stall_4} > {stall_1}")

    # Sanity: ring baseline should not attribute any 2D stage steps.
    if int(_num(ring, "tensor_collective_2d_row_rs_steps_total")) != 0:
        return _fail("ring: expected no 2D stage steps (row_rs)")

    print("[m8] PASS")
    print(f"[m8] ring_steps={ring_steps} torus_2d_steps={torus_steps} chunks={chunks} dim={dim_x}x{dim_y}")
    print(f"[m8] chunk64k: chunks={chunks_64k} steps={steps_64k}")
    print(f"[m8] inflight: credit_stall baseline={stall_1} inflight4={stall_4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

