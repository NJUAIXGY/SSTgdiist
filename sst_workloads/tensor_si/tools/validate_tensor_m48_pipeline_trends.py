#!/usr/bin/env python3
"""Validate M48 pipeline fidelity proxy trends."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        txt = str(value).strip()
        if not txt:
            return 0
        return int(float(txt))
    except Exception:
        return 0


def _to_float(value: Any) -> float:
    try:
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        txt = str(value).strip()
        if not txt:
            return 0.0
        return float(txt)
    except Exception:
        return 0.0


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


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, help="baseline summary json")
    ap.add_argument("--stress", required=True, help="stress summary json")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    base_p = Path(args.baseline).expanduser().resolve()
    stress_p = Path(args.stress).expanduser().resolve()

    if not base_p.exists():
        return _fail(2, f"[m48][P0] missing --baseline summary: {base_p}")
    if not stress_p.exists():
        return _fail(2, f"[m48][P0] missing --stress summary: {stress_p}")

    base = _load_tensor(base_p)
    stress = _load_tensor(stress_p)
    if base is None or stress is None:
        return _fail(2, "[m48][P0] invalid summary schema: missing tensor object")

    base_bytes = _to_int(base.get("tensor_mem_bytes_read_total"))
    stress_bytes = _to_int(stress.get("tensor_mem_bytes_read_total"))
    if base_bytes <= 0 or stress_bytes <= 0:
        return _fail(3, f"[m48][P1] expected mem_bytes_read_total > 0 (baseline={base_bytes}, stress={stress_bytes})")
    if base_bytes != stress_bytes:
        return _fail(3, f"[m48][P1] expected mem_bytes_read_total match (baseline={base_bytes}, stress={stress_bytes})")

    base_pipe = _to_int(base.get("tensor_compute_pipeline_cycles_total"))
    stress_pipe = _to_int(stress.get("tensor_compute_pipeline_cycles_total"))
    pipeline_signal = ""
    if base_pipe > 0 or stress_pipe > 0:
        if stress_pipe <= base_pipe:
            return _fail(3, f"[m48][P1] expected stress pipeline cycles > baseline (baseline={base_pipe}, stress={stress_pipe})")
        pipeline_signal = f"pipeline_cycles baseline={base_pipe} stress={stress_pipe}"
    else:
        base_eff = _to_float(base.get("tensor_effective_mac_per_cycle_math"))
        stress_eff = _to_float(stress.get("tensor_effective_mac_per_cycle_math"))
        if base_eff <= 0.0 or stress_eff <= 0.0:
            return _fail(
                3,
                (
                    "[m48][P1] missing pipeline fidelity signal: both pipeline_cycles are zero "
                    f"and effective_mac_per_cycle invalid (baseline={base_eff}, stress={stress_eff})"
                ),
            )
        if stress_eff >= base_eff:
            return _fail(
                3,
                (
                    "[m48][P1] expected stress effective_mac_per_cycle < baseline "
                    f"(baseline={base_eff}, stress={stress_eff})"
                ),
            )
        pipeline_signal = f"pipeline_proxy_effective_mac baseline={base_eff:.6f} stress={stress_eff:.6f}"

    base_any = _to_int(base.get("tensor_program_any_busy_cycles_total"))
    stress_any = _to_int(stress.get("tensor_program_any_busy_cycles_total"))
    base_dma = _to_int(base.get("tensor_program_dma_busy_cycles_total"))
    stress_dma = _to_int(stress.get("tensor_program_dma_busy_cycles_total"))
    busy_signal = ""
    if base_any > 0 and stress_any > 0:
        if stress_any < base_any:
            return _fail(
                3,
                f"[m48][P1] expected stress any_busy_cycles >= baseline (baseline={base_any}, stress={stress_any})",
            )
        busy_signal = f"program_any_busy baseline={base_any} stress={stress_any}"
    elif base_dma > 0 and stress_dma > 0:
        if stress_dma < base_dma:
            return _fail(
                3,
                f"[m48][P1] expected stress dma_busy_cycles >= baseline (baseline={base_dma}, stress={stress_dma})",
            )
        busy_signal = f"program_dma_busy baseline={base_dma} stress={stress_dma}"
    else:
        return _fail(
            3,
            (
                "[m48][P1] missing busy-cycle signal: "
                f"any_busy baseline/stress={base_any}/{stress_any}, "
                f"dma_busy baseline/stress={base_dma}/{stress_dma}"
            ),
        )

    base_cfg = _load_cfg(base_p)
    stress_cfg = _load_cfg(stress_p)
    base_issue = _to_int(base_cfg.get("tensor_program_issue_width"))
    stress_issue = _to_int(stress_cfg.get("tensor_program_issue_width"))
    if base_issue <= stress_issue:
        return _fail(3, f"[m48][P1] expected baseline issue_width > stress (baseline={base_issue}, stress={stress_issue})")

    base_lat = _to_int(base_cfg.get("tensor_compute_pipeline_latency_cycles"))
    stress_lat = _to_int(stress_cfg.get("tensor_compute_pipeline_latency_cycles"))
    if stress_lat <= base_lat:
        return _fail(3, f"[m48][P1] expected stress pipeline latency > baseline (baseline={base_lat}, stress={stress_lat})")

    prefix = f"[m48:{args.label}] " if args.label else "[m48] "
    print(f"{prefix}mem_bytes_read_total={base_bytes}")
    print(f"{prefix}{pipeline_signal}")
    print(f"{prefix}{busy_signal}")
    print(f"{prefix}issue_width baseline={base_issue} stress={stress_issue} pipeline_latency={base_lat}/{stress_lat}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
