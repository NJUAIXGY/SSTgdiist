#!/usr/bin/env python3
"""Validate M41 calibration profile contract and determinism."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from calibrate_tensor_memory_profile import build_profile


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any) -> Tuple[bool, float]:
    try:
        if isinstance(value, bool):
            return False, 0.0
        if isinstance(value, (int, float)):
            return True, float(value)
        txt = str(value).strip()
        if not txt:
            return False, 0.0
        return True, float(txt)
    except Exception:
        return False, 0.0


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _assert_close(name: str, got: float, exp: float, tol: float = 1e-6) -> Tuple[bool, str]:
    if abs(float(got) - float(exp)) > tol:
        return False, f"{name} mismatch: got={got:.9f}, expected={exp:.9f}"
    return True, ""


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="calibration profile json")
    ap.add_argument("--baseline", required=True, help="baseline summary json")
    ap.add_argument("--target", required=True, help="target summary json")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    profile_p = Path(args.profile).expanduser().resolve()
    baseline_p = Path(args.baseline).expanduser().resolve()
    target_p = Path(args.target).expanduser().resolve()

    for p, flag in ((profile_p, "--profile"), (baseline_p, "--baseline"), (target_p, "--target")):
        if not p.exists():
            return _fail(2, f"[m41][P0] missing {flag}: {p}")

    try:
        profile = _load_json(profile_p)
    except Exception as exc:
        return _fail(2, f"[m41][P0] cannot parse profile json: {exc}")
    if not isinstance(profile, dict):
        return _fail(2, "[m41][P0] profile root must be object")

    factors = profile.get("factors")
    if not isinstance(factors, dict):
        return _fail(3, "[m41][P1] missing factors object")

    for key in ("read_latency_scale", "dma_busy_scale", "suggested_mem_bandwidth_scale"):
        ok, v = _to_float(factors.get(key))
        if not ok or v <= 0.0:
            return _fail(3, f"[m41][P1] invalid factor {key}: {factors.get(key)!r}")

    conf = str(profile.get("confidence", "")).strip().lower()
    if conf not in {"low", "medium", "high"}:
        return _fail(3, f"[m41][P1] invalid confidence: {conf!r}")

    tag = str(profile.get("calibration_tag", "")).strip()
    if not tag:
        return _fail(3, "[m41][P1] calibration_tag must be non-empty")

    try:
        expected = build_profile(baseline=baseline_p, target=target_p, tag=tag)
    except Exception as exc:
        return _fail(3, f"[m41][P1] cannot recompute calibration profile: {exc}")

    for key in ("read_latency_scale", "dma_busy_scale", "suggested_mem_bandwidth_scale"):
        got = float(factors.get(key))
        exp = float(expected["factors"][key])
        ok_close, msg = _assert_close(key, got, exp, tol=1e-6)
        if not ok_close:
            return _fail(3, f"[m41][P1] {msg}")

    prefix = f"[m41:{args.label}] " if args.label else "[m41] "
    print(
        f"{prefix}factors: read_latency_scale={factors['read_latency_scale']} "
        f"dma_busy_scale={factors['dma_busy_scale']} "
        f"suggested_mem_bandwidth_scale={factors['suggested_mem_bandwidth_scale']}"
    )
    print(f"{prefix}confidence={conf} calibration_tag={tag}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
