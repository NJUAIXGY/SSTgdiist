#!/usr/bin/env python3
"""Validate M52 evidence calibration profile contract and determinism."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fit_tensor_calibration_from_evidence import build_profile


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


def _assert_close(name: str, got: float, exp: float, tol: float = 1e-6) -> Tuple[bool, str]:
    if abs(float(got) - float(exp)) > tol:
        return False, f"{name} mismatch: got={got:.9f}, expected={exp:.9f}"
    return True, ""


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="evidence profile json")
    ap.add_argument("--baseline", required=True, help="baseline summary")
    ap.add_argument("--target", required=True, help="target summary")
    ap.add_argument("--reference", required=True, help="reference profile")
    ap.add_argument("--expect-pass", type=int, default=1, help="1=require evidence status pass")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    profile_p = Path(args.profile).expanduser().resolve()
    baseline_p = Path(args.baseline).expanduser().resolve()
    target_p = Path(args.target).expanduser().resolve()
    ref_p = Path(args.reference).expanduser().resolve()

    for p, flag in ((profile_p, "--profile"), (baseline_p, "--baseline"), (target_p, "--target"), (ref_p, "--reference")):
        if not p.exists():
            return _fail(2, f"[m52][P0] missing {flag}: {p}")

    try:
        profile = _load_json(profile_p)
    except Exception as exc:
        return _fail(2, f"[m52][P0] cannot parse profile json: {exc}")

    if not isinstance(profile, dict):
        return _fail(2, "[m52][P0] profile root must be object")

    factors = profile.get("factors")
    if not isinstance(factors, dict):
        return _fail(3, "[m52][P1] missing factors object")

    for key in ("read_latency_scale", "dma_busy_scale", "suggested_mem_bandwidth_scale"):
        ok, val = _to_float(factors.get(key))
        if not ok or val <= 0.0:
            return _fail(3, f"[m52][P1] invalid factor {key}: {factors.get(key)!r}")

    evidence = profile.get("evidence")
    if not isinstance(evidence, dict):
        return _fail(3, "[m52][P1] missing evidence object")

    status = str(evidence.get("status", "")).strip().lower()
    if status not in {"pass", "fail"}:
        return _fail(3, f"[m52][P1] invalid evidence.status={status!r}")

    ok_err, err_score = _to_float(evidence.get("error_score"))
    if not ok_err or err_score < 0.0:
        return _fail(3, f"[m52][P1] invalid evidence.error_score={evidence.get('error_score')!r}")

    conf = str(profile.get("confidence", "")).strip().lower()
    if conf not in {"low", "medium", "high"}:
        return _fail(3, f"[m52][P1] invalid confidence={conf!r}")

    tag = str(profile.get("calibration_tag", "")).strip()
    if not tag:
        return _fail(3, "[m52][P1] calibration_tag must be non-empty")

    try:
        expected = build_profile(baseline=baseline_p, target=target_p, reference=ref_p, tag=tag)
    except Exception as exc:
        return _fail(3, f"[m52][P1] cannot recompute profile: {exc}")

    for key in ("read_latency_scale", "dma_busy_scale", "suggested_mem_bandwidth_scale"):
        ok_close, msg = _assert_close(key, float(factors.get(key)), float(expected["factors"][key]), tol=1e-6)
        if not ok_close:
            return _fail(3, f"[m52][P1] {msg}")

    ok_close, msg = _assert_close("error_score", float(evidence.get("error_score", 0.0)), float(expected["evidence"]["error_score"]), tol=1e-6)
    if not ok_close:
        return _fail(3, f"[m52][P1] {msg}")

    if int(args.expect_pass) == 1 and status != "pass":
        return _fail(3, f"[m52][P1] expected pass but evidence.status={status} error_score={err_score:.6f}")

    prefix = f"[m52:{args.label}] " if args.label else "[m52] "
    print(
        f"{prefix}factors: read_latency_scale={factors['read_latency_scale']} "
        f"dma_busy_scale={factors['dma_busy_scale']} "
        f"suggested_mem_bandwidth_scale={factors['suggested_mem_bandwidth_scale']}"
    )
    print(f"{prefix}evidence.status={status} error_score={err_score:.6f} confidence={conf}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
