#!/usr/bin/env python3
"""Validate M72 pipeline-scoreboard v3 contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


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


def _load_tensor(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tensor = payload.get("tensor")
    return tensor if isinstance(tensor, dict) else None


def _load_cfg(summary_path: Path) -> Dict[str, Any]:
    path = summary_path.parent / "effective_config.json"
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    cfg = payload.get("tensor_cfg")
    return cfg if isinstance(cfg, dict) else {}


def _hazard_proxy(tensor: Dict[str, Any]) -> int:
    structural = _to_int(tensor.get("tensor_stall_onchip_port_cycles_total")) + _to_int(
        tensor.get("tensor_stall_onchip_bank_conflict_cycles_total")
    )
    dependency = _to_int(tensor.get("tensor_program_ub_stall_cycles_total")) + _to_int(
        tensor.get("tensor_program_fence_wait_cycles_total")
    )
    memory_wait = _to_int(tensor.get("tensor_program_mem_stall_cycles_total"))
    return max(0, structural + dependency + memory_wait)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--stress", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    base_p = Path(args.baseline).expanduser().resolve()
    stress_p = Path(args.stress).expanduser().resolve()

    if not base_p.exists():
        return _fail(2, f"[m72][P0] missing --baseline summary: {base_p}")
    if not stress_p.exists():
        return _fail(2, f"[m72][P0] missing --stress summary: {stress_p}")

    base = _load_tensor(base_p)
    stress = _load_tensor(stress_p)
    if base is None or stress is None:
        return _fail(2, "[m72][P0] invalid summary schema: missing tensor object")

    base_cfg = _load_cfg(base_p)
    stress_cfg = _load_cfg(stress_p)
    b_issue = _to_int(base_cfg.get("tensor_program_issue_width"), 0)
    s_issue = _to_int(stress_cfg.get("tensor_program_issue_width"), 0)
    b_lat = _to_int(base_cfg.get("tensor_compute_pipeline_latency_cycles"), 0)
    s_lat = _to_int(stress_cfg.get("tensor_compute_pipeline_latency_cycles"), 0)
    if b_issue <= s_issue:
        return _fail(3, f"[m72][P1] expected baseline issue_width > stress (baseline={b_issue}, stress={s_issue})")
    if s_lat <= b_lat:
        return _fail(3, f"[m72][P1] expected stress pipeline_latency > baseline (baseline={b_lat}, stress={s_lat})")

    b_ops = _to_int(base.get("tensor_program_ops_total"))
    s_ops = _to_int(stress.get("tensor_program_ops_total"))
    if b_ops <= 0 or s_ops <= 0:
        return _fail(3, f"[m72][P1] expected program_ops_total > 0 (baseline={b_ops}, stress={s_ops})")

    b_busy = _to_int(base.get("tensor_program_any_busy_cycles_total"))
    s_busy = _to_int(stress.get("tensor_program_any_busy_cycles_total"))
    if s_busy <= b_busy:
        return _fail(3, f"[m72][P1] expected stress any_busy_cycles > baseline (baseline={b_busy}, stress={s_busy})")

    b_compute = _to_int(base.get("tensor_compute_cycles_total"))
    s_compute = _to_int(stress.get("tensor_compute_cycles_total"))
    if s_compute <= b_compute:
        return _fail(
            3,
            "[m72][P1] expected stress compute_cycles_total > baseline "
            f"(baseline={b_compute}, stress={s_compute})",
        )

    b_hazard = _hazard_proxy(base)
    s_hazard = _hazard_proxy(stress)

    prefix = f"[m72:{args.label}] " if args.label else "[m72] "
    print(
        f"{prefix}issue_width baseline={b_issue} stress={s_issue} "
        f"pipeline_latency baseline={b_lat} stress={s_lat}"
    )
    print(
        f"{prefix}hazard_proxy baseline={b_hazard} stress={s_hazard} "
        f"any_busy baseline={b_busy} stress={s_busy} "
        f"compute_cycles baseline={b_compute} stress={s_compute}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
