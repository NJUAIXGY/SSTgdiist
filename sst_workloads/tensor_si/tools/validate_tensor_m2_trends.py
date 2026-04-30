#!/usr/bin/env python3
"""Validate M2 overlap/bandwidth trend expectations for tensor workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _fail(msg: str) -> int:
    print(f"[m2] FAIL: {msg}")
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
        "tensor_stall_noc_budget_cycles_total",
        "tensor_overlap_compute_collective_cycles_total",
        "tensor_stall_collective_cycles_total",
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
    if _num(t, "tensor_mac_ops_total") <= 0:
        return False, f"{label}: tensor_mac_ops_total must be > 0", {}
    return True, "", t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-compat", required=True)
    ap.add_argument("--noc-capped-overlap-on", required=True)
    ap.add_argument("--noc-capped-overlap-off", required=True)
    ap.add_argument("--noc-capped-heavy-collective", required=True)
    ap.add_argument("--noc-capped-payload-first", required=True)
    args = ap.parse_args()

    datasets = {
        "baseline_compat": _load_summary(args.baseline_compat),
        "noc_capped_overlap_on": _load_summary(args.noc_capped_overlap_on),
        "noc_capped_overlap_off": _load_summary(args.noc_capped_overlap_off),
        "noc_capped_heavy_collective": _load_summary(args.noc_capped_heavy_collective),
        "noc_capped_payload_first": _load_summary(args.noc_capped_payload_first),
    }

    tensors: Dict[str, Dict[str, Any]] = {}
    for label, summary in datasets.items():
        ok, reason, tensor = _tensor(summary, label)
        if not ok:
            return _fail(reason)
        tensors[label] = tensor

    overlap_on = _num(tensors["noc_capped_overlap_on"], "tensor_overlap_compute_collective_cycles_total")
    overlap_off = _num(tensors["noc_capped_overlap_off"], "tensor_overlap_compute_collective_cycles_total")
    if overlap_on <= 0:
        return _fail("noc_capped_overlap_on: expected overlap cycles > 0")
    if overlap_off != 0:
        return _fail(f"noc_capped_overlap_off: expected overlap cycles == 0, got {overlap_off}")

    stall_on = _num(tensors["noc_capped_overlap_on"], "tensor_stall_collective_cycles_total")
    stall_off = _num(tensors["noc_capped_overlap_off"], "tensor_stall_collective_cycles_total")
    if stall_off < stall_on:
        return _fail(
            "collective stall trend mismatch: expected overlap_off stall >= overlap_on stall "
            f"but got overlap_on={stall_on}, overlap_off={stall_off}"
        )

    heavy_pending = _num(tensors["noc_capped_heavy_collective"], "tensor_collective_pending_cycles_total")
    heavy_noc_stall = _num(tensors["noc_capped_heavy_collective"], "tensor_stall_noc_budget_cycles_total")
    if heavy_noc_stall <= 0:
        return _fail(
            "noc_capped_heavy_collective: expected noc budget stall > 0 "
            f"but got pending={heavy_pending}, noc_stall={heavy_noc_stall}"
        )

    payload_first = tensors["noc_capped_payload_first"]
    payload_collective_issue = _num(payload_first, "tensor_collective_issue_cycles_total")
    payload_pending = _num(payload_first, "tensor_collective_pending_cycles_total")
    payload_noc_stall = _num(payload_first, "tensor_stall_noc_budget_cycles_total")
    payload_pkt_bytes = _num(payload_first, "tensor_pkt_bytes_sent_total")
    payload_collective_bytes = _num(payload_first, "tensor_collective_bytes_sent_total")
    payload_comm_bytes = payload_pkt_bytes - payload_collective_bytes
    if payload_collective_issue > 0:
        return _fail(
            "noc_capped_payload_first: expected collective issue cycles == 0 under payload-first contention "
            f"but got collective_issue={payload_collective_issue}"
        )
    if payload_comm_bytes <= 0:
        return _fail(
            "noc_capped_payload_first: expected comm bytes > 0 "
            f"but got pkt={payload_pkt_bytes}, collective={payload_collective_bytes}, comm={payload_comm_bytes}"
        )
    if payload_pending <= 0:
        return _fail(
            "noc_capped_payload_first: expected pending activity "
            f"but got pending={payload_pending}, noc_stall={payload_noc_stall}"
        )

    print("[m2] PASS")
    print(
        "[m2] overlap_cycles:"
        f" on={overlap_on:.0f} off={overlap_off:.0f}"
    )
    print(
        "[m2] collective_stall_cycles:"
        f" on={stall_on:.0f} off={stall_off:.0f}"
    )
    print(
        "[m2] heavy_collective:"
        f" pending={heavy_pending:.0f} noc_stall={heavy_noc_stall:.0f}"
    )
    print(
        "[m2] payload_first:"
        f" collective_issue={payload_collective_issue:.0f}"
        f" pending={payload_pending:.0f}"
        f" noc_stall={payload_noc_stall:.0f}"
        f" comm_bytes={payload_comm_bytes:.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
