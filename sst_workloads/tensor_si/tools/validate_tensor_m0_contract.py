#!/usr/bin/env python3
"""Validate M0 baseline contract for tensor runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


REQUIRED_ARTIFACTS = (
    "effective_config.json",
    "essential_summary_tensor_mesh.json",
    "validation.log",
    "mesh_stats.csv",
    "tensor_mesh_run.log",
    "time.txt",
)

REQUIRED_TENSOR_METRICS = (
    "tensor_mem_reads_issued_total",
    "tensor_mem_bytes_read_total",
    "tensor_compute_cycles_total",
    "tensor_mac_ops_total",
    "tensor_dma_cycles_total",
    "tensor_dma_stall_cycles_total",
    "tensor_stall_dma_budget_cycles_total",
    "tensor_stall_mem_outstanding_cycles_total",
    "tensor_stall_wait_read_cycles_total",
    "tensor_collective_bytes_sent_total",
    "tensor_pkt_bytes_sent_total",
)


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_non_negative_number(value: Any) -> Tuple[bool, float]:
    if isinstance(value, bool):
        return False, 0.0
    if isinstance(value, (int, float)):
        f = float(value)
        return (f >= 0.0), f
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return False, 0.0
        try:
            f = float(txt)
        except Exception:
            return False, 0.0
        return (f >= 0.0), f
    return False, 0.0


def _fail(code: int, msg: str) -> int:
    print(msg)
    return code


def _resolve_run_dir(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


def _check_artifacts(run_dir: Path) -> Tuple[bool, List[str]]:
    missing: List[str] = []
    for rel in REQUIRED_ARTIFACTS:
        if not (run_dir / rel).exists():
            missing.append(rel)
    return (len(missing) == 0), missing


def _collective_activity(tensor: Dict[str, Any]) -> float:
    total = 0.0
    for key in (
        "tensor_collective_bytes_sent_total",
        "tensor_collective_bytes_recv_total",
        "tensor_collective_pkts_sent_total",
        "tensor_collective_pkts_recv_total",
        "tensor_collective_cycles_total",
    ):
        ok, val = _to_non_negative_number(tensor.get(key))
        if ok:
            total += val
    return total


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="run output directory")
    ap.add_argument("--scenario", default="", help="scenario label (for logs)")
    ap.add_argument("--expect-tile", action="store_true", help="require tensor_exec_mode=tile")
    ap.add_argument("--expect-collective", action="store_true", help="require collective counters to be active")
    ap.add_argument(
        "--allow-zero-mac",
        action="store_true",
        help="allow tensor_mac_ops_total==0 (useful for pure-collective program runs)",
    )
    args = ap.parse_args(argv)

    scenario = str(args.scenario).strip() or "unknown"
    run_dir = _resolve_run_dir(args.run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        return _fail(12, f"[m0][P2][{scenario}] run_dir missing or invalid: {run_dir}")

    ok, missing = _check_artifacts(run_dir)
    if not ok:
        return _fail(12, f"[m0][P2][{scenario}] missing artifacts: {', '.join(missing)}")

    validation_log = (run_dir / "validation.log").read_text(encoding="utf-8", errors="ignore")
    if "[tensor_mesh] PASS" not in validation_log:
        return _fail(11, f"[m0][P1][{scenario}] validation.log does not contain PASS")

    summary_path = run_dir / "essential_summary_tensor_mesh.json"
    try:
        summary = _load_json(summary_path)
    except Exception as exc:
        return _fail(13, f"[m0][P3][{scenario}] cannot parse summary json: {exc}")
    if not isinstance(summary, dict):
        return _fail(13, f"[m0][P3][{scenario}] summary root must be an object")

    sim_ok, sim_time = _to_non_negative_number(summary.get("sim_time_ns"))
    if not sim_ok or sim_time <= 0:
        return _fail(13, f"[m0][P3][{scenario}] invalid sim_time_ns={summary.get('sim_time_ns')!r}")

    summary_run_dir = Path(str(summary.get("run_dir", ""))).expanduser().resolve()
    if summary_run_dir != run_dir:
        return _fail(
            13,
            f"[m0][P3][{scenario}] summary.run_dir mismatch: got {summary_run_dir}, expected {run_dir}",
        )

    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, dict):
        return _fail(13, f"[m0][P3][{scenario}] missing artifacts object in summary")
    mesh_stats_csv = Path(str(artifacts.get("mesh_stats_csv", ""))).expanduser()
    if not mesh_stats_csv.exists():
        return _fail(13, f"[m0][P3][{scenario}] artifacts.mesh_stats_csv not found: {mesh_stats_csv}")

    tensor = summary.get("tensor")
    if not isinstance(tensor, dict):
        return _fail(13, f"[m0][P3][{scenario}] missing tensor object in summary")
    for key in REQUIRED_TENSOR_METRICS:
        if key not in tensor:
            return _fail(13, f"[m0][P3][{scenario}] missing tensor metric: {key}")
        metric_ok, metric_val = _to_non_negative_number(tensor.get(key))
        if not metric_ok:
            return _fail(13, f"[m0][P3][{scenario}] invalid metric {key}={tensor.get(key)!r}")
        if metric_val < 0:
            return _fail(13, f"[m0][P3][{scenario}] metric must be non-negative: {key}={metric_val}")

    mac_ok, mac_ops = _to_non_negative_number(tensor.get("tensor_mac_ops_total"))
    if not mac_ok:
        return _fail(13, f"[m0][P3][{scenario}] invalid tensor_mac_ops_total")
    if not args.allow_zero_mac and mac_ops <= 0:
        return _fail(13, f"[m0][P3][{scenario}] tensor_mac_ops_total must be > 0")

    cfg_path = run_dir / "effective_config.json"
    try:
        cfg = _load_json(cfg_path)
    except Exception as exc:
        return _fail(13, f"[m0][P3][{scenario}] cannot parse effective_config.json: {exc}")
    tensor_cfg = cfg.get("tensor_cfg") if isinstance(cfg, dict) else None
    if not isinstance(tensor_cfg, dict):
        return _fail(13, f"[m0][P3][{scenario}] missing tensor_cfg in effective_config.json")
    if str(tensor_cfg.get("workload_impl", "")).strip().lower() != "tensor":
        return _fail(13, f"[m0][P3][{scenario}] tensor_cfg.workload_impl must be 'tensor'")

    if args.expect_tile:
        if str(tensor_cfg.get("tensor_exec_mode", "")).strip().lower() != "tile":
            return _fail(13, f"[m0][P3][{scenario}] expected tensor_exec_mode=tile")
        for key in ("tensor_tile_m", "tensor_tile_n", "tensor_tile_k"):
            ok_tile, val_tile = _to_non_negative_number(tensor_cfg.get(key))
            if (not ok_tile) or val_tile <= 0:
                return _fail(13, f"[m0][P3][{scenario}] expected {key} > 0 for tile mode")

    if args.expect_collective:
        ctype = str(tensor_cfg.get("tensor_collective_type", "")).strip().lower()
        if not ctype or ctype == "none":
            return _fail(13, f"[m0][P3][{scenario}] expected tensor_collective_type != none")
        if _collective_activity(tensor) <= 0:
            return _fail(13, f"[m0][P3][{scenario}] collective expected but no collective activity counters")

    print(f"[m0][{scenario}] contract PASS: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
