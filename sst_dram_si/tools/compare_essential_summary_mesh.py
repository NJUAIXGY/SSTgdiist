#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compare two essential_summary_mesh.json with tolerant thresholds.

Usage:
  python3 tools/compare_essential_summary_mesh.py --a <run_dir_A> --b <run_dir_B>

Default: allow slight drift (rel_tol=1%, abs_tol=1). Exit 0 on pass, 1 on fail.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _get_path(d: Dict[str, Any], dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _as_number(v: Any, missing_is_zero: bool) -> float | None:
    if v is None:
        return 0.0 if missing_is_zero else None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _close(a: float, b: float, abs_tol: float, rel_tol: float) -> bool:
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    denom = max(abs(a), abs(b), 1.0)
    return (diff / denom) <= rel_tol


def _load_summary(run_dir: Path) -> Dict[str, Any]:
    return json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))


def _gate_offline_antiburial_tail(
    run_a: Path,
    run_b: Path,
) -> int:
    ja = _load_summary(run_a)
    jb = _load_summary(run_b)

    checks = [
        (
            "completion.global_steps_done",
            _get_path(jb, "gas.global_steps_done") == _get_path(ja, "gas.global_steps_done"),
            _get_path(ja, "gas.global_steps_done"),
            _get_path(jb, "gas.global_steps_done"),
            "candidate steps must match baseline",
        ),
        (
            "completion.windows_incomplete_zero",
            _get_path(jb, "gas.windows_incomplete") == 0,
            _get_path(ja, "gas.windows_incomplete"),
            _get_path(jb, "gas.windows_incomplete"),
            "candidate must fully drain all windows",
        ),
        (
            "completion.materialization_ratio",
            _get_path(jb, "retire_hol_attribution_core.frontend_ordering.completion_state.materialization_ratio") == 1.0,
            _get_path(ja, "retire_hol_attribution_core.frontend_ordering.completion_state.materialization_ratio"),
            _get_path(jb, "retire_hol_attribution_core.frontend_ordering.completion_state.materialization_ratio"),
            "candidate must preserve full materialization",
        ),
        (
            "completion.retire_drain_ratio",
            _get_path(jb, "retire_hol_attribution_core.frontend_ordering.completion_state.retire_drain_ratio") == 1.0,
            _get_path(ja, "retire_hol_attribution_core.frontend_ordering.completion_state.retire_drain_ratio"),
            _get_path(jb, "retire_hol_attribution_core.frontend_ordering.completion_state.retire_drain_ratio"),
            "candidate must preserve full retire/drain closure",
        ),
        (
            "tail.line_groups_p95",
            float(_get_path(jb, "retire_hol_attribution_core.frontend_ordering.queue_shape.window_line_groups_per_prepare_p95") or 0.0)
            <= float(_get_path(ja, "retire_hol_attribution_core.frontend_ordering.queue_shape.window_line_groups_per_prepare_p95") or 0.0),
            _get_path(ja, "retire_hol_attribution_core.frontend_ordering.queue_shape.window_line_groups_per_prepare_p95"),
            _get_path(jb, "retire_hol_attribution_core.frontend_ordering.queue_shape.window_line_groups_per_prepare_p95"),
            "candidate must not regress bad-window line-group tail",
        ),
        (
            "memory.memctrl_req_total",
            float(_get_path(jb, "memhierarchy.memctrl.req_total") or 0.0)
            <= float(_get_path(ja, "memhierarchy.memctrl.req_total") or 0.0),
            _get_path(ja, "memhierarchy.memctrl.req_total"),
            _get_path(jb, "memhierarchy.memctrl.req_total"),
            "candidate must not regress memory request count",
        ),
        (
            "tail.older_wait_max_p95",
            float(_get_path(jb, "retire_hol_attribution_core.frontend_ordering.older_head_wait.window_wait_cycles_max_p95") or 0.0)
            <= float(_get_path(ja, "retire_hol_attribution_core.frontend_ordering.older_head_wait.window_wait_cycles_max_p95") or 0.0),
            _get_path(ja, "retire_hol_attribution_core.frontend_ordering.older_head_wait.window_wait_cycles_max_p95"),
            _get_path(jb, "retire_hol_attribution_core.frontend_ordering.older_head_wait.window_wait_cycles_max_p95"),
            "candidate must not regress older-head max wait tail",
        ),
    ]
    depth_avg_base = float(_get_path(ja, "retire_hol_attribution_core.frontend_ordering.younger_ahead_depth.window_depth_avg_p99") or 0.0)
    depth_avg_cand = float(_get_path(jb, "retire_hol_attribution_core.frontend_ordering.younger_ahead_depth.window_depth_avg_p99") or 0.0)
    depth_max_base = float(_get_path(ja, "retire_hol_attribution_core.frontend_ordering.younger_ahead_depth.window_depth_max_p95") or 0.0)
    depth_max_cand = float(_get_path(jb, "retire_hol_attribution_core.frontend_ordering.younger_ahead_depth.window_depth_max_p95") or 0.0)
    depth_tail_ok = depth_avg_cand <= depth_avg_base or depth_max_cand <= depth_max_base
    checks.append(
        (
            "tail.depth_tail_or",
            depth_tail_ok,
            {"window_depth_avg_p99": depth_avg_base, "window_depth_max_p95": depth_max_base},
            {"window_depth_avg_p99": depth_avg_cand, "window_depth_max_p95": depth_max_cand},
            "candidate must improve at least one depth tail metric",
        )
    )

    ok = True
    print(f"[cmp-gate] profile=offline_antiburial_tail")
    print(f"[cmp-gate] baseline={run_a}")
    print(f"[cmp-gate] candidate={run_b}")
    for name, passed, base_v, cand_v, reason in checks:
        if not passed:
            ok = False
        print(
            f"[cmp-gate] {'PASS' if passed else 'FAIL'} {name}: "
            f"baseline={base_v} candidate={cand_v} reason={reason}"
        )
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", required=True, help="run dir A (contains essential_summary_mesh.json)")
    ap.add_argument("--b", required=True, help="run dir B (contains essential_summary_mesh.json)")
    ap.add_argument("--abs-tol", type=float, default=1.0, help="absolute tolerance (default: 1)")
    ap.add_argument("--rel-tol", type=float, default=0.01, help="relative tolerance (default: 0.01 == 1%%)")
    ap.add_argument("--missing-is-zero", action="store_true", default=True,
                    help="treat missing numeric fields as 0 (default: true)")
    ap.add_argument(
        "--gate-profile",
        choices=("none", "offline_antiburial_tail"),
        default="none",
        help="optional directional gate profile instead of symmetric numeric compare",
    )
    args = ap.parse_args()

    run_a = Path(args.a).resolve()
    run_b = Path(args.b).resolve()
    if args.gate_profile == "offline_antiburial_tail":
        return _gate_offline_antiburial_tail(run_a, run_b)
    ja = json.loads((run_a / "essential_summary_mesh.json").read_text(encoding="utf-8"))
    jb = json.loads((run_b / "essential_summary_mesh.json").read_text(encoding="utf-8"))

    keys = [
        "spike_activity.neurons_fired_total",
        "spike_activity.total_spikes_processed",
        "spike_activity.gas_scatter_spikes_emitted_total",
        "gas.gather_ns_p95",
        "gas.apply_ns_p95",
        "gas.scatter_ns_p95",
        "memory.memory_requests",
        "memory.memory_bytes",
        "nic.packets_sent",
        "nic.packets_recv",
        "stream.stream_mem_verify_fail_total",
        "stream.stream_mem_bytes_written_total",
        "stream.stream_mem_bytes_read_total",
        "stream.stream_pkt_sent_total",
        "stream.stream_pkt_recv_total",
    ]

    ok = True
    print(f"[cmp] A={run_a}")
    print(f"[cmp] B={run_b}")
    print(f"[cmp] abs_tol={args.abs_tol} rel_tol={args.rel_tol}")
    for k in keys:
        va = _as_number(_get_path(ja, k), args.missing_is_zero)
        vb = _as_number(_get_path(jb, k), args.missing_is_zero)
        if va is None or vb is None:
            print(f"[cmp] SKIP {k}: non-numeric (A={va} B={vb})")
            continue
        passed = _close(va, vb, args.abs_tol, args.rel_tol)
        if not passed:
            ok = False
        print(f"[cmp] {'OK' if passed else 'DIFF'} {k}: A={va} B={vb} Δ={abs(va - vb)}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
