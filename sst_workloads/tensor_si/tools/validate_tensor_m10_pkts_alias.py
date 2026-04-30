#!/usr/bin/env python3
"""Validate M10 (pkts aliases for credit/inflight naming) for tensor workload specs.

M10 accepts:
  - tensor_collective_max_inflight_pkts (alias of tensor_collective_max_inflight_chunks)
  - tensor_collective_credit_window_pkts (alias of tensor_collective_credit_window_chunks)

This validator checks that pkts-alias specs resolve to canonical *_chunks keys in effective_config.json
and that credit-window tracking is active in the produced summary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict


def _fail(msg: str) -> int:
    print(f"[m10] FAIL: {msg}")
    return 13


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json root must be object: {path}")
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


def _require_int(cfg: Dict[str, Any], key: str, expected: int, label: str) -> int:
    try:
        got = int(cfg.get(key, 0) or 0)
    except Exception:
        got = 0
    if got != int(expected):
        raise ValueError(f"{label}: expected {key} == {expected} but got {got}")
    return got


def _validate_one(*, summary_path: str, label: str, expect_inflight: int, expect_window: int) -> Dict[str, Any]:
    summary_p = Path(summary_path).expanduser().resolve()
    summary = _load_json(summary_p)
    if not isinstance(summary.get("tensor"), dict):
        raise ValueError(f"{label}: missing tensor section")
    tensor = summary["tensor"]

    run_dir = Path(str(summary.get("run_dir", "") or "")).expanduser().resolve()
    if not run_dir.exists():
        raise ValueError(f"{label}: run_dir missing: {run_dir}")

    eff = _load_json(run_dir / "effective_config.json")
    mesh_cfg = eff.get("mesh_cfg") if isinstance(eff, dict) else None
    cfg = eff.get("tensor_cfg") if isinstance(eff, dict) else None
    node_limit_raw = eff.get("node_limit") if isinstance(eff, dict) else None
    if not isinstance(cfg, dict):
        raise ValueError(f"{label}: missing tensor_cfg in effective_config.json")

    _require_int(cfg, "tensor_collective_credit_enable", 1, label)
    _require_int(cfg, "tensor_collective_max_inflight_chunks", expect_inflight, label)
    _require_int(cfg, "tensor_collective_credit_window_chunks", expect_window, label)

    # Alias keys must not leak into effective config.
    if "tensor_collective_max_inflight_pkts" in cfg:
        raise ValueError(f"{label}: unexpected alias key present in tensor_cfg: tensor_collective_max_inflight_pkts")
    if "tensor_collective_credit_window_pkts" in cfg:
        raise ValueError(f"{label}: unexpected alias key present in tensor_cfg: tensor_collective_credit_window_pkts")

    inflight_max = int(_num(tensor, "tensor_collective_inflight_chunks_max"))
    if inflight_max <= 0:
        raise ValueError(f"{label}: expected tensor_collective_inflight_chunks_max > 0")
    # Note: tensor_collective_inflight_chunks_max is a per-core max counter, but mesh summary aggregates
    # by summing across cores/PEs. Bound against (window * total_cores) to avoid false negatives.
    try:
        node_limit = int(node_limit_raw or 0)
    except Exception:
        node_limit = 0
    try:
        cores_per_pe = int(mesh_cfg.get("num_cores_per_pe", 0) or 0) if isinstance(mesh_cfg, dict) else 0
    except Exception:
        cores_per_pe = 0
    total_cores = max(1, node_limit * max(1, cores_per_pe))
    if inflight_max > expect_window * total_cores:
        raise ValueError(
            f"{label}: expected inflight_chunks_max <= credit_window_chunks*total_cores "
            f"({inflight_max} > {expect_window}*{total_cores})"
        )

    return {
        "run_dir": str(run_dir),
        "inflight_max": inflight_max,
        "stall": int(_num(tensor, "tensor_collective_credit_stall_cycles_total")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", required=True, help="scenario using canonical *_chunks keys")
    ap.add_argument("--pkts-alias", required=True, help="scenario using *_pkts aliases")
    ap.add_argument("--expect-max-inflight", type=int, default=8, help="expected max inflight (canonical key value)")
    ap.add_argument("--expect-window", type=int, default=1, help="expected credit window (canonical key value)")
    args = ap.parse_args()

    try:
        chunks = _validate_one(
            summary_path=str(args.chunks),
            label="chunks",
            expect_inflight=int(args.expect_max_inflight),
            expect_window=int(args.expect_window),
        )
        pkts = _validate_one(
            summary_path=str(args.pkts_alias),
            label="pkts_alias",
            expect_inflight=int(args.expect_max_inflight),
            expect_window=int(args.expect_window),
        )
    except Exception as exc:
        return _fail(str(exc))

    print("[m10] PASS")
    print(f"[m10] chunks: run_dir={chunks['run_dir']} inflight_max={chunks['inflight_max']} stall={chunks['stall']}")
    print(f"[m10] pkts_alias: run_dir={pkts['run_dir']} inflight_max={pkts['inflight_max']} stall={pkts['stall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
