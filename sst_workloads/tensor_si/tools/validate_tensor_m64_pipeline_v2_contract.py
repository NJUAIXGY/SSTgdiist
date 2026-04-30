#!/usr/bin/env python3
"""Validate M64 pipeline-v2 trends contract."""

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
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--stress", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    base_p = Path(args.baseline).expanduser().resolve()
    stress_p = Path(args.stress).expanduser().resolve()

    if not base_p.exists():
        return _fail(2, f"[m64][P0] missing --baseline summary: {base_p}")
    if not stress_p.exists():
        return _fail(2, f"[m64][P0] missing --stress summary: {stress_p}")

    base = _load_tensor(base_p)
    stress = _load_tensor(stress_p)
    if base is None or stress is None:
        return _fail(2, "[m64][P0] invalid summary schema: missing tensor object")

    b_mem = _to_int(base.get("tensor_mem_bytes_read_total"))
    s_mem = _to_int(stress.get("tensor_mem_bytes_read_total"))
    if b_mem <= 0 or s_mem <= 0:
        return _fail(3, f"[m64][P1] expected mem_bytes_read_total > 0 (baseline={b_mem}, stress={s_mem})")
    if b_mem != s_mem:
        return _fail(3, f"[m64][P1] expected mem_bytes_read_total match (baseline={b_mem}, stress={s_mem})")

    b_pipe = _to_int(base.get("tensor_compute_pipeline_cycles_total"))
    s_pipe = _to_int(stress.get("tensor_compute_pipeline_cycles_total"))
    b_eff = _to_float(base.get("tensor_effective_mac_per_cycle_math"))
    s_eff = _to_float(stress.get("tensor_effective_mac_per_cycle_math"))
    b_any = _to_int(base.get("tensor_program_any_busy_cycles_total"))
    s_any = _to_int(stress.get("tensor_program_any_busy_cycles_total"))
    b_dma = _to_int(base.get("tensor_program_dma_busy_cycles_total"))
    s_dma = _to_int(stress.get("tensor_program_dma_busy_cycles_total"))
    b_fence = _to_int(base.get("tensor_program_fence_wait_cycles_total"))
    s_fence = _to_int(stress.get("tensor_program_fence_wait_cycles_total"))

    if b_pipe > 0 or s_pipe > 0:
        if s_pipe <= b_pipe:
            return _fail(3, f"[m64][P1] expected stress pipeline_cycles > baseline (baseline={b_pipe}, stress={s_pipe})")
        pipe_signal = f"pipeline_cycles baseline={b_pipe} stress={s_pipe}"
    else:
        if b_eff > 0.0 and s_eff > 0.0 and s_eff < b_eff:
            pipe_signal = f"pipeline_proxy_effective_mac baseline={b_eff:.6f} stress={s_eff:.6f}"
        else:
            pressure_up = (s_any > b_any) or (s_dma > b_dma) or (s_fence > b_fence)
            if not pressure_up:
                if b_eff <= 0.0 or s_eff <= 0.0:
                    return _fail(3, "[m64][P1] missing pipeline signal: pipeline_cycles==0 and effective_mac invalid")
                return _fail(
                    3,
                    "[m64][P1] expected stress pressure signal when pipeline_cycles==0 "
                    f"(effective_mac baseline={b_eff:.6f}, stress={s_eff:.6f}; "
                    f"any_busy={b_any}/{s_any}, dma_busy={b_dma}/{s_dma}, fence_wait={b_fence}/{s_fence})",
                )
            pipe_signal = f"pipeline_proxy_busy any={b_any}/{s_any} dma={b_dma}/{s_dma} fence_wait={b_fence}/{s_fence}"

    if b_any > 0 and s_any > 0 and s_any < b_any:
        return _fail(3, f"[m64][P1] expected stress any_busy >= baseline (baseline={b_any}, stress={s_any})")
    if b_dma > 0 and s_dma > 0 and s_dma < b_dma:
        return _fail(3, f"[m64][P1] expected stress dma_busy >= baseline (baseline={b_dma}, stress={s_dma})")
    if s_fence < b_fence and s_any <= b_any and s_dma <= b_dma:
        return _fail(
            3,
            "[m64][P1] expected stress to expose at least one stronger pressure signal "
            f"(any_busy={b_any}/{s_any}, dma_busy={b_dma}/{s_dma}, fence_wait={b_fence}/{s_fence})",
        )

    base_cfg = _load_cfg(base_p)
    stress_cfg = _load_cfg(stress_p)
    b_issue = _to_int(base_cfg.get("tensor_program_issue_width"))
    s_issue = _to_int(stress_cfg.get("tensor_program_issue_width"))
    b_lat = _to_int(base_cfg.get("tensor_compute_pipeline_latency_cycles"))
    s_lat = _to_int(stress_cfg.get("tensor_compute_pipeline_latency_cycles"))
    if b_issue <= s_issue:
        return _fail(3, f"[m64][P1] expected baseline issue_width > stress (baseline={b_issue}, stress={s_issue})")
    if s_lat <= b_lat:
        return _fail(3, f"[m64][P1] expected stress pipeline latency > baseline (baseline={b_lat}, stress={s_lat})")

    prefix = f"[m64:{args.label}] " if args.label else "[m64] "
    print(f"{prefix}mem_bytes_read_total={b_mem}")
    print(f"{prefix}{pipe_signal}")
    print(f"{prefix}busy any={b_any}/{s_any} dma={b_dma}/{s_dma} fence_wait={b_fence}/{s_fence}")
    print(f"{prefix}issue_width baseline={b_issue} stress={s_issue} pipeline_latency={b_lat}/{s_lat}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
