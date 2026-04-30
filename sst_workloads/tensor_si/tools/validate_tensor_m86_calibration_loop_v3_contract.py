#!/usr/bin/env python3
"""Validate M86 calibration-loop v3 profile contract and determinism."""

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


def _avg(total: int, samples: int) -> float:
    if samples <= 0:
        return 0.0
    return float(total) / float(samples)


def _assert_close(name: str, got: float, exp: float, tol: float = 1e-6) -> Tuple[bool, str]:
    if abs(float(got) - float(exp)) > tol:
        return False, f"{name} mismatch: got={got:.9f}, expected={exp:.9f}"
    return True, ""


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _load_tensor(summary_path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(summary_path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tensor = payload.get("tensor")
    return tensor if isinstance(tensor, dict) else None


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--expect-pass", type=int, default=1)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    profile_p = Path(args.profile).expanduser().resolve()
    baseline_p = Path(args.baseline).expanduser().resolve()
    target_p = Path(args.target).expanduser().resolve()
    ref_p = Path(args.reference).expanduser().resolve()

    for p, flag in ((profile_p, "--profile"), (baseline_p, "--baseline"), (target_p, "--target"), (ref_p, "--reference")):
        if not p.exists():
            return _fail(2, f"[m86][P0] missing {flag}: {p}")

    try:
        profile = _load_json(profile_p)
    except Exception as exc:
        return _fail(2, f"[m86][P0] cannot parse profile json: {exc}")
    if not isinstance(profile, dict):
        return _fail(2, "[m86][P0] profile root must be object")

    factors = profile.get("factors")
    if not isinstance(factors, dict):
        return _fail(3, "[m86][P1] missing factors object")
    for key in ("read_latency_scale", "dma_busy_scale", "suggested_mem_bandwidth_scale"):
        ok, val = _to_float(factors.get(key))
        if not ok or val <= 0.0:
            return _fail(3, f"[m86][P1] invalid factor {key}: {factors.get(key)!r}")

    evidence = profile.get("evidence")
    if not isinstance(evidence, dict):
        return _fail(3, "[m86][P1] missing evidence object")
    status = str(evidence.get("status", "")).strip().lower()
    if status not in {"pass", "fail"}:
        return _fail(3, f"[m86][P1] invalid evidence.status={status!r}")
    ok_err, err_score = _to_float(evidence.get("error_score"))
    if not ok_err or err_score < 0.0:
        return _fail(3, f"[m86][P1] invalid evidence.error_score={evidence.get('error_score')!r}")

    conf = str(profile.get("confidence", "")).strip().lower()
    if conf not in {"low", "medium", "high"}:
        return _fail(3, f"[m86][P1] invalid confidence={conf!r}")
    if conf == "low":
        return _fail(3, "[m86][P1] expected confidence in {medium,high}")

    tag = str(profile.get("calibration_tag", "")).strip()
    if not tag:
        return _fail(3, "[m86][P1] calibration_tag must be non-empty")

    try:
        expected = build_profile(baseline=baseline_p, target=target_p, reference=ref_p, tag=tag)
    except Exception as exc:
        return _fail(3, f"[m86][P1] cannot recompute profile: {exc}")

    for key in ("read_latency_scale", "dma_busy_scale", "suggested_mem_bandwidth_scale"):
        ok_close, msg = _assert_close(key, float(factors.get(key)), float(expected["factors"][key]), tol=1e-6)
        if not ok_close:
            return _fail(3, f"[m86][P1] {msg}")
    ok_close, msg = _assert_close("error_score", float(evidence.get("error_score", 0.0)), float(expected["evidence"]["error_score"]), tol=1e-6)
    if not ok_close:
        return _fail(3, f"[m86][P1] {msg}")

    base_tensor = _load_tensor(baseline_p)
    target_tensor = _load_tensor(target_p)
    if base_tensor is None or target_tensor is None:
        return _fail(2, "[m86][P0] invalid baseline/target summary schema")

    base_lat = _avg(
        _to_int(base_tensor.get("tensor_mem_read_latency_cycles_total"), 0),
        _to_int(base_tensor.get("tensor_mem_read_latency_samples_total"), 0),
    )
    target_lat = _avg(
        _to_int(target_tensor.get("tensor_mem_read_latency_cycles_total"), 0),
        _to_int(target_tensor.get("tensor_mem_read_latency_samples_total"), 0),
    )
    if target_lat <= base_lat:
        return _fail(
            3,
            "[m86][P1] expected target avg_read_latency > baseline "
            f"(baseline={base_lat:.6f}, target={target_lat:.6f})",
        )

    if int(args.expect_pass) == 1 and status != "pass":
        return _fail(3, f"[m86][P1] expected pass but evidence.status={status} error_score={err_score:.6f}")

    prefix = f"[m86:{args.label}] " if args.label else "[m86] "
    print(
        f"{prefix}factors read_latency_scale={factors['read_latency_scale']} "
        f"dma_busy_scale={factors['dma_busy_scale']} "
        f"suggested_mem_bandwidth_scale={factors['suggested_mem_bandwidth_scale']}"
    )
    print(
        f"{prefix}evidence.status={status} error_score={err_score:.6f} confidence={conf} "
        f"avg_read_latency baseline={base_lat:.6f} target={target_lat:.6f}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
