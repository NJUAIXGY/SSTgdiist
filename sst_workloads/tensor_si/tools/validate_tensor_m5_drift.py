#!/usr/bin/env python3
"""Validate M5 event_hard summary drift against a baseline summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict


def _fail(msg: str) -> int:
    print(f"[m5][drift] FAIL: {msg}")
    return 14


def _load_summary(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser().resolve()
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"summary root must be object: {p}")
    tensor = payload.get("tensor")
    if not isinstance(tensor, dict):
        raise ValueError(f"missing tensor section: {p}")
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


def _rel_diff(cur: float, base: float) -> float:
    denom = abs(base)
    if denom < 1.0:
        denom = 1.0
    return abs(cur - base) / denom


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True, help="current event_hard summary path")
    ap.add_argument("--baseline", required=True, help="baseline event_hard summary path")
    ap.add_argument(
        "--threshold",
        type=float,
        default=0.30,
        help="max allowed relative drift ratio (default: 0.30)",
    )
    args = ap.parse_args()

    if args.threshold < 0:
        return _fail(f"threshold must be >= 0 but got {args.threshold}")

    cur = _load_summary(args.current).get("tensor", {})
    base = _load_summary(args.baseline).get("tensor", {})

    metrics = (
        "tensor_collective_bytes_sent_total",
        "tensor_collective_pending_cycles_total",
        "tensor_collective_credit_stall_cycles_total",
        "tensor_collective_inflight_chunks_max",
        "tensor_collective_credit_return_pkts_recv_total",
        "tensor_collective_credit_return_pkts_sent_total",
    )

    failures = []
    for key in metrics:
        cur_v = _num(cur, key)
        base_v = _num(base, key)

        # Protect against silent 0->nonzero regressions.
        if base_v == 0.0 and cur_v == 0.0:
            continue
        if base_v == 0.0 and cur_v != 0.0:
            failures.append(
                f"{key}: baseline=0 current={cur_v:.3f} (relative drift undefined)"
            )
            continue

        drift = _rel_diff(cur_v, base_v)
        if drift > args.threshold:
            failures.append(
                f"{key}: current={cur_v:.3f} baseline={base_v:.3f} drift={drift:.4f} > threshold={args.threshold:.4f}"
            )

    if failures:
        print("[m5][drift] DETAILS:")
        for line in failures:
            print(f"[m5][drift] {line}")
        return _fail(f"{len(failures)} metric(s) exceeded threshold")

    print("[m5][drift] PASS")
    print(
        "[m5][drift] checked_metrics="
        + ",".join(metrics)
        + f" threshold={args.threshold:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
