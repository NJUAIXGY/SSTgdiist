#!/usr/bin/env python3
"""Validate M81 readiness->counter mapping contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


MAPPING_KEYS = ("scheduler", "dataflow", "memory", "parallelism", "scalability")


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(default)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        txt = str(value).strip()
        if not txt:
            return int(default)
        return int(float(txt))
    except Exception:
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return float(default)
        if isinstance(value, (int, float)):
            return float(value)
        txt = str(value).strip()
        if not txt:
            return float(default)
        return float(txt)
    except Exception:
        return float(default)


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _load_summary(path: Path) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None, Dict[str, Any] | None]:
    try:
        payload = _load_json(path)
    except Exception:
        return (None, None, None)
    if not isinstance(payload, dict):
        return (None, None, None)
    tensor = payload.get("tensor")
    readiness = payload.get("npu_tpu_readiness")
    cfg_path = path.parent / "effective_config.json"
    cfg_payload: Dict[str, Any] = {}
    if cfg_path.exists():
        try:
            cfg_payload = _load_json(cfg_path)
        except Exception:
            cfg_payload = {}
    tensor_cfg = cfg_payload.get("tensor_cfg") if isinstance(cfg_payload.get("tensor_cfg"), dict) else {}
    mesh_cfg = cfg_payload.get("mesh_cfg") if isinstance(cfg_payload.get("mesh_cfg"), dict) else {}
    return (
        tensor if isinstance(tensor, dict) else None,
        readiness if isinstance(readiness, dict) else None,
        {"tensor_cfg": tensor_cfg, "mesh_cfg": mesh_cfg},
    )


def _mapping_coverage(tensor: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, int]:
    tensor_cfg = cfg.get("tensor_cfg") if isinstance(cfg.get("tensor_cfg"), dict) else {}
    mesh_cfg = cfg.get("mesh_cfg") if isinstance(cfg.get("mesh_cfg"), dict) else {}

    coverage: Dict[str, int] = {
        "scheduler": 0,
        "dataflow": 0,
        "memory": 0,
        "parallelism": 0,
        "scalability": 0,
    }

    scheduler_signals = (
        _to_int(tensor.get("tensor_program_any_busy_cycles_total")),
        _to_int(tensor.get("tensor_program_fence_wait_cycles_total")),
        _to_int(tensor.get("tensor_program_ub_stall_cycles_total")),
        _to_int(tensor.get("tensor_program_mem_stall_cycles_total")),
    )
    if any(v > 0 for v in scheduler_signals):
        coverage["scheduler"] = 1

    dataflow_signals = (
        _to_int(tensor.get("tensor_compute_cycles_total")),
        _to_int(tensor.get("tensor_compute_pipeline_cycles_total")),
        _to_int(tensor.get("tensor_mxu_io_busy_cycles_total")),
        _to_int(tensor.get("tensor_stall_onchip_bank_conflict_cycles_total")),
    )
    if any(v > 0 for v in dataflow_signals):
        coverage["dataflow"] = 1

    memory_signals = (
        _to_int(tensor.get("tensor_mem_read_latency_samples_total")),
        _to_int(tensor.get("tensor_mem_write_latency_samples_total")),
        _to_int(tensor.get("tensor_mem_cmd_rdwr_total")),
        _to_int(tensor.get("tensor_mem_row_hit_total")),
        _to_int(tensor.get("tensor_mem_bank_queue_wait_cycles_total")),
        _to_int(tensor.get("tensor_mem_cmd_bus_wait_cycles_total")),
    )
    if any(v > 0 for v in memory_signals):
        coverage["memory"] = 1

    parallelism_signals = (
        _to_int(tensor.get("tensor_mac_ops_total")),
        _to_float(tensor.get("tensor_effective_mac_per_cycle")),
        _to_int(tensor.get("tensor_program_iters_total")),
        _to_int(tensor.get("tensor_dma_cycles_total")),
    )
    if any(v > 0 for v in parallelism_signals):
        coverage["parallelism"] = 1

    scalability_signals = (
        _to_int(mesh_cfg.get("mesh_size")),
        _to_int(mesh_cfg.get("network_num_vns")),
        _to_int(tensor_cfg.get("tensor_dma_hbm_channels")),
    )
    if all(v > 0 for v in scalability_signals):
        coverage["scalability"] = 1

    return coverage


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-only", required=True)
    ap.add_argument("--evidence-rich", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    cfg_p = Path(args.config_only).expanduser().resolve()
    rich_p = Path(args.evidence_rich).expanduser().resolve()

    if not cfg_p.exists():
        return _fail(2, f"[m81][P0] missing --config-only summary: {cfg_p}")
    if not rich_p.exists():
        return _fail(2, f"[m81][P0] missing --evidence-rich summary: {rich_p}")

    cfg_tensor, cfg_ready, cfg_cfg = _load_summary(cfg_p)
    rich_tensor, rich_ready, rich_cfg = _load_summary(rich_p)
    if cfg_tensor is None or cfg_ready is None or rich_tensor is None or rich_ready is None:
        return _fail(2, "[m81][P0] invalid summary schema: missing tensor/npu_tpu_readiness")

    cfg_profile = str(cfg_ready.get("capability_profile", "")).strip().lower()
    rich_profile = str(rich_ready.get("capability_profile", "")).strip().lower()
    if "readiness_mapping_v4" not in cfg_profile or "readiness_mapping_v4" not in rich_profile:
        return _fail(
            3,
            "[m81][P1] expected capability_profile contains readiness_mapping_v4 "
            f"(config_only={cfg_profile!r}, evidence_rich={rich_profile!r})",
        )

    cfg_breakdown = cfg_ready.get("capability_score_breakdown")
    rich_breakdown = rich_ready.get("capability_score_breakdown")
    if not isinstance(cfg_breakdown, dict) or not isinstance(rich_breakdown, dict):
        return _fail(3, "[m81][P1] missing capability_score_breakdown")

    for k in MAPPING_KEYS:
        if k not in cfg_breakdown or k not in rich_breakdown:
            return _fail(3, f"[m81][P1] missing readiness breakdown key: {k}")

    cfg_cov = _mapping_coverage(cfg_tensor, cfg_cfg or {})
    rich_cov = _mapping_coverage(rich_tensor, rich_cfg or {})

    for k in MAPPING_KEYS:
        if int(cfg_cov.get(k, 0)) <= 0:
            return _fail(3, f"[m81][P1] config_only missing counter mapping for dimension={k}")
        if int(rich_cov.get(k, 0)) <= 0:
            return _fail(3, f"[m81][P1] evidence_rich missing counter mapping for dimension={k}")

    cfg_score = _to_float(cfg_ready.get("capability_score_total"), 0.0)
    rich_score = _to_float(rich_ready.get("capability_score_total"), 0.0)
    cfg_ev = _to_float(cfg_ready.get("evidence_factor"), 0.0)
    rich_ev = _to_float(rich_ready.get("evidence_factor"), 0.0)
    cfg_conf = str(cfg_ready.get("calibration_confidence", "")).strip().lower() or "unverified"
    rich_conf = str(rich_ready.get("calibration_confidence", "")).strip().lower() or "unverified"

    if rich_score <= cfg_score:
        return _fail(3, f"[m81][P1] expected evidence_rich score > config_only (config_only={cfg_score:.3f}, evidence_rich={rich_score:.3f})")
    if cfg_conf not in {"unverified", "low"}:
        return _fail(3, f"[m81][P1] expected config_only calibration_confidence in {{unverified,low}} (got {cfg_conf!r})")
    if rich_conf not in {"medium", "high"}:
        return _fail(3, f"[m81][P1] expected evidence_rich calibration_confidence in {{medium,high}} (got {rich_conf!r})")

    prefix = f"[m81:{args.label}] " if args.label else "[m81] "
    print(f"{prefix}score config_only={cfg_score:.3f} evidence_rich={rich_score:.3f}")
    print(
        f"{prefix}evidence_factor config_only={cfg_ev:.3f} evidence_rich={rich_ev:.3f} "
        f"confidence config_only={cfg_conf} evidence_rich={rich_conf}"
    )
    print(f"{prefix}mapping_coverage config_only={cfg_cov} evidence_rich={rich_cov}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
