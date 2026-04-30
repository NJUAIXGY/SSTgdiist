#!/usr/bin/env python3
"""Validate M5 collective credit-return trend expectations for tensor workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _fail(msg: str) -> int:
    print(f"[m5] FAIL: {msg}")
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
        "tensor_collective_credit_stall_cycles_total",
        "tensor_collective_backpressure_stall_cycles_total",
        "tensor_collective_inflight_chunks_max",
        "tensor_collective_credit_return_pkts_sent_total",
        "tensor_collective_credit_return_pkts_recv_total",
        "tensor_collective_credit_return_orphan_total",
        "tensor_collective_credit_return_dup_total",
        "tensor_collective_credit_return_latency_cycles_total",
        "tensor_collective_credit_return_latency_cycles_max",
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

    latency_total = _num(t, "tensor_collective_credit_return_latency_cycles_total")
    latency_max = _num(t, "tensor_collective_credit_return_latency_cycles_max")
    if latency_total < latency_max:
        return (
            False,
            (
                f"{label}: expected latency_total >= latency_max "
                f"but got total={latency_total}, max={latency_max}"
            ),
            {},
        )

    return True, "", t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-tick", required=True)
    ap.add_argument("--event-hard", required=True)
    ap.add_argument("--event-soft", required=True)
    ap.add_argument("--event-payload-first", required=True)
    ap.add_argument("--event-uncapped", required=True)
    ap.add_argument("--event-stress", required=True)
    args = ap.parse_args()

    datasets = {
        "legacy_tick": _load_summary(args.legacy_tick),
        "event_hard": _load_summary(args.event_hard),
        "event_soft": _load_summary(args.event_soft),
        "event_payload_first": _load_summary(args.event_payload_first),
        "event_uncapped": _load_summary(args.event_uncapped),
        "event_stress": _load_summary(args.event_stress),
    }

    tensors: Dict[str, Dict[str, Any]] = {}
    for label, summary in datasets.items():
        ok, reason, tensor = _tensor(summary, label)
        if not ok:
            return _fail(reason)
        tensors[label] = tensor

    legacy = tensors["legacy_tick"]
    hard = tensors["event_hard"]
    soft = tensors["event_soft"]
    payload = tensors["event_payload_first"]
    uncapped = tensors["event_uncapped"]
    stress = tensors["event_stress"]

    legacy_return_recv = _num(legacy, "tensor_collective_credit_return_pkts_recv_total")
    legacy_return_sent = _num(legacy, "tensor_collective_credit_return_pkts_sent_total")
    if legacy_return_recv != 0 or legacy_return_sent != 0:
        return _fail(
            "legacy_tick: expected no credit-return control packets "
            f"but got sent={legacy_return_sent}, recv={legacy_return_recv}"
        )

    hard_return_recv = _num(hard, "tensor_collective_credit_return_pkts_recv_total")
    hard_return_sent = _num(hard, "tensor_collective_credit_return_pkts_sent_total")
    hard_orphan = _num(hard, "tensor_collective_credit_return_orphan_total")
    hard_dup = _num(hard, "tensor_collective_credit_return_dup_total")
    hard_credit_stall = _num(hard, "tensor_collective_credit_stall_cycles_total")
    hard_backpressure = _num(hard, "tensor_collective_backpressure_stall_cycles_total")
    hard_inflight_max = _num(hard, "tensor_collective_inflight_chunks_max")

    if hard_return_recv <= 0 or hard_return_sent <= 0:
        return _fail(
            "event_hard: expected credit-return packet activity "
            f"but got sent={hard_return_sent}, recv={hard_return_recv}"
        )
    if hard_orphan != 0 or hard_dup != 0:
        return _fail(
            "event_hard: expected orphan/dup == 0 "
            f"but got orphan={hard_orphan}, dup={hard_dup}"
        )
    if hard_credit_stall <= 0 or hard_backpressure <= 0:
        return _fail(
            "event_hard: expected positive credit/backpressure stall "
            f"but got credit={hard_credit_stall}, backpressure={hard_backpressure}"
        )
    if hard_inflight_max <= 0:
        return _fail(f"event_hard: expected inflight_chunks_max > 0 but got {hard_inflight_max}")
    soft_return_recv = _num(soft, "tensor_collective_credit_return_pkts_recv_total")
    soft_orphan = _num(soft, "tensor_collective_credit_return_orphan_total")
    soft_dup = _num(soft, "tensor_collective_credit_return_dup_total")
    soft_credit_stall = _num(soft, "tensor_collective_credit_stall_cycles_total")
    soft_sent = _num(soft, "tensor_collective_bytes_sent_total")
    hard_sent = _num(hard, "tensor_collective_bytes_sent_total")

    if soft_return_recv <= 0:
        return _fail(f"event_soft: expected credit-return recv > 0 but got {soft_return_recv}")
    if soft_orphan != 0 or soft_dup != 0:
        return _fail(
            "event_soft: expected orphan/dup == 0 "
            f"but got orphan={soft_orphan}, dup={soft_dup}"
        )
    if soft_credit_stall <= 0:
        return _fail(f"event_soft: expected credit stall > 0 but got {soft_credit_stall}")
    if soft_sent < hard_sent:
        return _fail(
            "event_soft: expected sent bytes >= event_hard "
            f"but got soft={soft_sent}, hard={hard_sent}"
        )

    payload_issue = _num(payload, "tensor_collective_issue_cycles_total")
    payload_pending = _num(payload, "tensor_collective_pending_cycles_total")
    payload_pkt_bytes = _num(payload, "tensor_pkt_bytes_sent_total")
    payload_collective_bytes = _num(payload, "tensor_collective_bytes_sent_total")
    payload_comm_bytes = payload_pkt_bytes - payload_collective_bytes
    payload_return_recv = _num(payload, "tensor_collective_credit_return_pkts_recv_total")

    if payload_issue > 0:
        return _fail(
            "event_payload_first: expected collective_issue_cycles == 0 "
            f"but got {payload_issue}"
        )
    if payload_pending <= 0:
        return _fail(
            "event_payload_first: expected pending activity "
            f"but got {payload_pending}"
        )
    if payload_comm_bytes <= 0:
        return _fail(
            "event_payload_first: expected comm bytes > 0 "
            f"but got pkt={payload_pkt_bytes}, collective={payload_collective_bytes}, comm={payload_comm_bytes}"
        )
    if payload_return_recv != 0:
        return _fail(
            "event_payload_first: expected no credit return when collective issue is fully suppressed "
            f"but got recv={payload_return_recv}"
        )

    uncapped_return_recv = _num(uncapped, "tensor_collective_credit_return_pkts_recv_total")
    uncapped_orphan = _num(uncapped, "tensor_collective_credit_return_orphan_total")
    uncapped_dup = _num(uncapped, "tensor_collective_credit_return_dup_total")
    if uncapped_return_recv <= 0:
        return _fail(f"event_uncapped: expected credit-return recv > 0 but got {uncapped_return_recv}")
    if uncapped_orphan != 0 or uncapped_dup != 0:
        return _fail(
            "event_uncapped: expected orphan/dup == 0 "
            f"but got orphan={uncapped_orphan}, dup={uncapped_dup}"
        )

    stress_return_recv = _num(stress, "tensor_collective_credit_return_pkts_recv_total")
    stress_credit_stall = _num(stress, "tensor_collective_credit_stall_cycles_total")
    stress_pending = _num(stress, "tensor_collective_pending_cycles_total")
    if stress_return_recv <= 0:
        return _fail(f"event_stress: expected credit-return recv > 0 but got {stress_return_recv}")
    if stress_credit_stall <= 0:
        return _fail(f"event_stress: expected credit stall > 0 but got {stress_credit_stall}")
    if stress_pending < _num(hard, "tensor_collective_pending_cycles_total"):
        return _fail(
            "event_stress: expected pending cycles >= event_hard "
            f"but got stress={stress_pending}, hard={_num(hard, 'tensor_collective_pending_cycles_total')}"
        )

    print("[m5] PASS")
    print(
        "[m5] legacy_vs_event:"
        f" legacy_return(sent/recv)={legacy_return_sent:.0f}/{legacy_return_recv:.0f}"
        f" hard_return(sent/recv)={hard_return_sent:.0f}/{hard_return_recv:.0f}"
    )
    print(
        "[m5] hard_vs_soft:"
        f" hard_credit={hard_credit_stall:.0f} hard_backpressure={hard_backpressure:.0f}"
        f" soft_credit={soft_credit_stall:.0f}"
        f" sent(hard/soft)={hard_sent:.0f}/{soft_sent:.0f}"
    )
    print(
        "[m5] payload_first:"
        f" issue={payload_issue:.0f}"
        f" pending={payload_pending:.0f}"
        f" comm_bytes={payload_comm_bytes:.0f}"
    )
    print(
        "[m5] stress:"
        f" pending={stress_pending:.0f}"
        f" credit_stall={stress_credit_stall:.0f}"
        f" return_recv={stress_return_recv:.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
