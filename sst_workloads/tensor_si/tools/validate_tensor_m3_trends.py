#!/usr/bin/env python3
"""Validate M3 on-chip + ring-chunked trend expectations for tensor workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _fail(msg: str) -> int:
    print(f"[m3] FAIL: {msg}")
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

    required = (
        "tensor_compute_cycles_total",
        "tensor_compute_math_cycles_total",
        "tensor_compute_pipeline_cycles_total",
        "tensor_mac_ops_total",
        "tensor_collective_pending_cycles_total",
        "tensor_collective_issue_cycles_total",
        "tensor_stall_onchip_capacity_cycles_total",
        "tensor_stall_onchip_port_cycles_total",
        "tensor_stall_spill_budget_cycles_total",
        "tensor_spill_bytes_total",
        "tensor_collective_chunk_groups_total",
        "tensor_collective_ring_steps_total",
        "tensor_collective_reduce_wait_cycles_total",
        "tensor_collective_algo_id",
        "tensor_collective_bytes_sent_total",
        "tensor_pkt_bytes_sent_total",
    )
    for key in required:
        if key not in t:
            return False, f"{label}: missing key {key}", {}
        if _num(t, key) < 0:
            return False, f"{label}: negative key {key}", {}

    total = _num(t, "tensor_compute_cycles_total")
    math = _num(t, "tensor_compute_math_cycles_total")
    pipe = _num(t, "tensor_compute_pipeline_cycles_total")
    if abs(total - (math + pipe)) > 0.5:
        return (
            False,
            (
                f"{label}: compute cycle breakdown mismatch "
                f"(total={total}, math={math}, pipeline={pipe})"
            ),
            {},
        )
    return True, "", t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-compat", required=True)
    ap.add_argument("--onchip-capacity-nospill", required=True)
    ap.add_argument("--onchip-capacity-spill", required=True)
    ap.add_argument("--ring-chunked", required=True)
    ap.add_argument("--ring-chunked-reduce-wait", required=True)
    ap.add_argument("--ring-chunked-payload-first", required=True)
    args = ap.parse_args()

    datasets = {
        "baseline_compat": _load_summary(args.baseline_compat),
        "onchip_capacity_nospill": _load_summary(args.onchip_capacity_nospill),
        "onchip_capacity_spill": _load_summary(args.onchip_capacity_spill),
        "ring_chunked": _load_summary(args.ring_chunked),
        "ring_chunked_reduce_wait": _load_summary(args.ring_chunked_reduce_wait),
        "ring_chunked_payload_first": _load_summary(args.ring_chunked_payload_first),
    }

    tensors: Dict[str, Dict[str, Any]] = {}
    for label, summary in datasets.items():
        ok, reason, tensor = _tensor(summary, label)
        if not ok:
            return _fail(reason)
        tensors[label] = tensor

    nospill = tensors["onchip_capacity_nospill"]
    spill = tensors["onchip_capacity_spill"]
    nospill_capacity = _num(nospill, "tensor_stall_onchip_capacity_cycles_total")
    spill_capacity = _num(spill, "tensor_stall_onchip_capacity_cycles_total")
    spill_bytes = _num(spill, "tensor_spill_bytes_total")

    if nospill_capacity <= 0:
        return _fail(
            "onchip_capacity_nospill: expected on-chip capacity stall > 0 "
            f"but got {nospill_capacity}"
        )
    if spill_bytes <= 0:
        return _fail(
            "onchip_capacity_spill: expected spill bytes > 0 "
            f"but got {spill_bytes}"
        )
    if spill_capacity > nospill_capacity:
        return _fail(
            "onchip capacity trend mismatch: expected spill stall <= nospill stall "
            f"but got nospill={nospill_capacity}, spill={spill_capacity}"
        )

    ring = tensors["ring_chunked"]
    ring_wait = tensors["ring_chunked_reduce_wait"]
    ring_algo_id = _num(ring, "tensor_collective_algo_id")
    ring_steps = _num(ring, "tensor_collective_ring_steps_total")
    ring_chunks = _num(ring, "tensor_collective_chunk_groups_total")
    ring_wait_cycles = _num(ring_wait, "tensor_collective_reduce_wait_cycles_total")

    if ring_algo_id <= 0:
        return _fail(f"ring_chunked: expected tensor_collective_algo_id > 0, got {ring_algo_id}")
    if ring_steps <= 0 or ring_chunks <= 0:
        return _fail(
            "ring_chunked: expected positive ring steps/chunks "
            f"but got steps={ring_steps}, chunks={ring_chunks}"
        )
    if ring_wait_cycles <= 0:
        return _fail(
            "ring_chunked_reduce_wait: expected reduce wait cycles > 0 "
            f"but got {ring_wait_cycles}"
        )

    payload_first = tensors["ring_chunked_payload_first"]
    payload_collective_issue = _num(payload_first, "tensor_collective_issue_cycles_total")
    payload_pending = _num(payload_first, "tensor_collective_pending_cycles_total")
    payload_pkt_bytes = _num(payload_first, "tensor_pkt_bytes_sent_total")
    payload_collective_bytes = _num(payload_first, "tensor_collective_bytes_sent_total")
    payload_comm_bytes = payload_pkt_bytes - payload_collective_bytes

    if payload_collective_issue > 0:
        return _fail(
            "ring_chunked_payload_first: expected collective issue cycles == 0 under payload-first contention "
            f"but got collective_issue={payload_collective_issue}"
        )
    if payload_pending <= 0:
        return _fail(
            "ring_chunked_payload_first: expected pending activity "
            f"but got pending={payload_pending}"
        )
    if payload_comm_bytes <= 0:
        return _fail(
            "ring_chunked_payload_first: expected comm bytes > 0 "
            f"but got pkt={payload_pkt_bytes}, collective={payload_collective_bytes}, comm={payload_comm_bytes}"
        )

    print("[m3] PASS")
    print(
        "[m3] onchip_capacity:"
        f" nospill={nospill_capacity:.0f} spill={spill_capacity:.0f} spill_bytes={spill_bytes:.0f}"
    )
    print(
        "[m3] ring_chunked:"
        f" steps={ring_steps:.0f} chunks={ring_chunks:.0f}"
        f" reduce_wait={ring_wait_cycles:.0f}"
    )
    print(
        "[m3] payload_first:"
        f" collective_issue={payload_collective_issue:.0f}"
        f" pending={payload_pending:.0f}"
        f" comm_bytes={payload_comm_bytes:.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
