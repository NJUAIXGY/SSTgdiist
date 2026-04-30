#!/usr/bin/env python3
"""Validate M4 bank-aware + collective-credit trend expectations for tensor workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _fail(msg: str) -> int:
    print(f"[m4] FAIL: {msg}")
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
        "tensor_collective_bytes_sent_total",
        "tensor_pkt_bytes_sent_total",
        "tensor_stall_onchip_bank_conflict_cycles_total",
        "tensor_collective_credit_stall_cycles_total",
        "tensor_collective_backpressure_stall_cycles_total",
        "tensor_collective_inflight_chunks_max",
        "tensor_bank_queue_occupancy_max",
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
    ap.add_argument("--bank-conflict-heavy", required=True)
    ap.add_argument("--bank-conflict-relaxed", required=True)
    ap.add_argument("--bank-conflict-queue-limited", required=True)
    ap.add_argument("--collective-credit-off", required=True)
    ap.add_argument("--collective-credit-hard", required=True)
    ap.add_argument("--collective-credit-soft", required=True)
    ap.add_argument("--collective-credit-payload-first", required=True)
    args = ap.parse_args()

    datasets = {
        "baseline_compat": _load_summary(args.baseline_compat),
        "bank_conflict_heavy": _load_summary(args.bank_conflict_heavy),
        "bank_conflict_relaxed": _load_summary(args.bank_conflict_relaxed),
        "bank_conflict_queue_limited": _load_summary(args.bank_conflict_queue_limited),
        "collective_credit_off": _load_summary(args.collective_credit_off),
        "collective_credit_hard": _load_summary(args.collective_credit_hard),
        "collective_credit_soft": _load_summary(args.collective_credit_soft),
        "collective_credit_payload_first": _load_summary(args.collective_credit_payload_first),
    }

    tensors: Dict[str, Dict[str, Any]] = {}
    for label, summary in datasets.items():
        ok, reason, tensor = _tensor(summary, label)
        if not ok:
            return _fail(reason)
        tensors[label] = tensor

    bank_heavy = tensors["bank_conflict_heavy"]
    bank_relaxed = tensors["bank_conflict_relaxed"]
    bank_queue = tensors["bank_conflict_queue_limited"]

    heavy_mac = _num(bank_heavy, "tensor_mac_ops_total")
    relaxed_mac = _num(bank_relaxed, "tensor_mac_ops_total")
    queue_mac = _num(bank_queue, "tensor_mac_ops_total")
    heavy_conflict = _num(bank_heavy, "tensor_stall_onchip_bank_conflict_cycles_total")
    relaxed_conflict = _num(bank_relaxed, "tensor_stall_onchip_bank_conflict_cycles_total")
    queue_conflict = _num(bank_queue, "tensor_stall_onchip_bank_conflict_cycles_total")
    heavy_queue_occ = _num(bank_heavy, "tensor_bank_queue_occupancy_max")
    queue_occ = _num(bank_queue, "tensor_bank_queue_occupancy_max")

    if heavy_queue_occ <= 0:
        return _fail(
            "bank_conflict_heavy: expected bank queue occupancy max > 0 "
            f"but got {heavy_queue_occ}"
        )
    if relaxed_conflict > heavy_conflict:
        return _fail(
            "bank conflict trend mismatch: expected relaxed <= heavy "
            f"but got relaxed={relaxed_conflict}, heavy={heavy_conflict}"
        )
    if relaxed_mac < heavy_mac:
        return _fail(
            "bank conflict throughput trend mismatch: expected relaxed MAC >= heavy MAC "
            f"but got relaxed={relaxed_mac}, heavy={heavy_mac}"
        )
    if queue_mac > relaxed_mac:
        return _fail(
            "bank queue-limited throughput trend mismatch: expected queue-limited MAC <= relaxed MAC "
            f"but got queue_limited={queue_mac}, relaxed={relaxed_mac}"
        )
    if queue_occ <= 0:
        return _fail(
            "bank_conflict_queue_limited: expected bank queue occupancy max > 0 "
            f"but got {queue_occ}"
        )

    credit_off = tensors["collective_credit_off"]
    credit_hard = tensors["collective_credit_hard"]
    credit_soft = tensors["collective_credit_soft"]
    payload_first = tensors["collective_credit_payload_first"]

    off_credit_stall = _num(credit_off, "tensor_collective_credit_stall_cycles_total")
    hard_credit_stall = _num(credit_hard, "tensor_collective_credit_stall_cycles_total")
    hard_backpressure = _num(credit_hard, "tensor_collective_backpressure_stall_cycles_total")
    hard_inflight_max = _num(credit_hard, "tensor_collective_inflight_chunks_max")

    if off_credit_stall != 0:
        return _fail(
            "collective_credit_off: expected credit stall == 0 "
            f"but got {off_credit_stall}"
        )
    if hard_credit_stall <= 0:
        return _fail(
            "collective_credit_hard: expected credit stall > 0 "
            f"but got {hard_credit_stall}"
        )
    if hard_backpressure <= 0:
        return _fail(
            "collective_credit_hard: expected backpressure stall > 0 "
            f"but got {hard_backpressure}"
        )
    if hard_inflight_max <= 0:
        return _fail(
            "collective_credit_hard: expected inflight_chunks_max > 0 "
            f"but got {hard_inflight_max}"
        )

    soft_credit_stall = _num(credit_soft, "tensor_collective_credit_stall_cycles_total")
    soft_sent = _num(credit_soft, "tensor_collective_bytes_sent_total")
    hard_sent = _num(credit_hard, "tensor_collective_bytes_sent_total")
    if soft_credit_stall <= 0:
        return _fail(
            "collective_credit_soft: expected credit stall > 0 "
            f"but got {soft_credit_stall}"
        )
    if soft_sent < hard_sent:
        return _fail(
            "collective_credit_soft: expected sent bytes >= hard mode "
            f"but got soft={soft_sent}, hard={hard_sent}"
        )

    payload_issue = _num(payload_first, "tensor_collective_issue_cycles_total")
    payload_pending = _num(payload_first, "tensor_collective_pending_cycles_total")
    payload_pkt_bytes = _num(payload_first, "tensor_pkt_bytes_sent_total")
    payload_collective_bytes = _num(payload_first, "tensor_collective_bytes_sent_total")
    payload_comm_bytes = payload_pkt_bytes - payload_collective_bytes

    if payload_issue > 0:
        return _fail(
            "collective_credit_payload_first: expected collective_issue_cycles == 0 under payload-first contention "
            f"but got {payload_issue}"
        )
    if payload_pending <= 0:
        return _fail(
            "collective_credit_payload_first: expected pending activity "
            f"but got {payload_pending}"
        )
    if payload_comm_bytes <= 0:
        return _fail(
            "collective_credit_payload_first: expected comm bytes > 0 "
            f"but got pkt={payload_pkt_bytes}, collective={payload_collective_bytes}, comm={payload_comm_bytes}"
        )

    print("[m4] PASS")
    print(
        "[m4] bank_conflict:"
        f" heavy={heavy_conflict:.0f} relaxed={relaxed_conflict:.0f}"
        f" queue_limited={queue_conflict:.0f} queue_occ_max={queue_occ:.0f}"
        f" mac(heavy/relaxed/queue)={heavy_mac:.0f}/{relaxed_mac:.0f}/{queue_mac:.0f}"
    )
    print(
        "[m4] collective_credit:"
        f" off_credit={off_credit_stall:.0f} hard_credit={hard_credit_stall:.0f}"
        f" hard_backpressure={hard_backpressure:.0f} inflight_max={hard_inflight_max:.0f}"
    )
    print(
        "[m4] soft_vs_hard:"
        f" soft_sent={soft_sent:.0f} hard_sent={hard_sent:.0f}"
    )
    print(
        "[m4] payload_first:"
        f" collective_issue={payload_issue:.0f}"
        f" pending={payload_pending:.0f}"
        f" comm_bytes={payload_comm_bytes:.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
