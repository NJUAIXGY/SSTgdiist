#!/usr/bin/env python3
"""Validate M1 compute trend expectations for tensor precision profiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


PRECISION_IDS = {
    "fp16": 0,
    "bf16": 1,
    "fp32": 2,
    "tf32": 3,
    "int8": 4,
    "fp8": 5,
}


def _fail(msg: str) -> int:
    print(f"[m1] FAIL: {msg}")
    return 13


def _load_summary(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser().resolve()
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"summary root must be object: {p}")
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


def _effective_mac_per_math_cycle(tensor: Dict[str, Any]) -> float:
    v = _num(tensor, "tensor_effective_mac_per_cycle_math")
    if v > 0:
        return v
    mac = _num(tensor, "tensor_mac_ops_total")
    math_cycles = _num(tensor, "tensor_compute_math_cycles_total")
    if math_cycles <= 0:
        return 0.0
    return mac / math_cycles


def _validate_summary(summary: Dict[str, Any], expect_precision: str, label: str) -> Tuple[bool, str]:
    tensor = summary.get("tensor")
    if not isinstance(tensor, dict):
        return False, f"{label}: missing tensor section"

    required = (
        "tensor_compute_cycles_total",
        "tensor_compute_math_cycles_total",
        "tensor_compute_pipeline_cycles_total",
        "tensor_mac_ops_total",
    )
    for key in required:
        if key not in tensor:
            return False, f"{label}: missing key {key}"
        if _num(tensor, key) < 0:
            return False, f"{label}: negative key {key}"

    total_cycles = _num(tensor, "tensor_compute_cycles_total")
    math_cycles = _num(tensor, "tensor_compute_math_cycles_total")
    pipe_cycles = _num(tensor, "tensor_compute_pipeline_cycles_total")
    if abs(total_cycles - (math_cycles + pipe_cycles)) > 0.5:
        return False, (
            f"{label}: compute cycle breakdown mismatch "
            f"(total={total_cycles}, math={math_cycles}, pipeline={pipe_cycles})"
        )

    if _num(tensor, "tensor_mac_ops_total") <= 0:
        return False, f"{label}: tensor_mac_ops_total must be > 0"
    if math_cycles <= 0:
        return False, f"{label}: tensor_compute_math_cycles_total must be > 0"

    precision_name = str(tensor.get("tensor_precision_profile_name", "")).strip().lower()
    if precision_name and precision_name != expect_precision:
        return False, f"{label}: precision name mismatch (got {precision_name}, want {expect_precision})"
    precision_id = int(_num(tensor, "tensor_precision_profile_id"))
    expected_id = int(PRECISION_IDS[expect_precision])
    if precision_id != expected_id:
        return False, f"{label}: precision id mismatch (got {precision_id}, want {expected_id})"

    eff = _effective_mac_per_math_cycle(tensor)
    if eff <= 0:
        return False, f"{label}: effective MAC/math-cycle must be > 0"

    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bulk-fp16", required=True)
    ap.add_argument("--bulk-fp32", required=True)
    ap.add_argument("--bulk-int8", required=True)
    ap.add_argument("--tile-fp16", required=True)
    ap.add_argument("--tile-fp32", required=True)
    ap.add_argument("--tile-int8", required=True)
    args = ap.parse_args()

    datasets = {
        "bulk.fp16": (_load_summary(args.bulk_fp16), "fp16"),
        "bulk.fp32": (_load_summary(args.bulk_fp32), "fp32"),
        "bulk.int8": (_load_summary(args.bulk_int8), "int8"),
        "tile.fp16": (_load_summary(args.tile_fp16), "fp16"),
        "tile.fp32": (_load_summary(args.tile_fp32), "fp32"),
        "tile.int8": (_load_summary(args.tile_int8), "int8"),
    }

    for label, (summary, expect_precision) in datasets.items():
        ok, reason = _validate_summary(summary, expect_precision=expect_precision, label=label)
        if not ok:
            return _fail(reason)

    bulk_fp16_eff = _effective_mac_per_math_cycle(datasets["bulk.fp16"][0]["tensor"])
    bulk_fp32_eff = _effective_mac_per_math_cycle(datasets["bulk.fp32"][0]["tensor"])
    bulk_int8_eff = _effective_mac_per_math_cycle(datasets["bulk.int8"][0]["tensor"])
    tile_fp16_eff = _effective_mac_per_math_cycle(datasets["tile.fp16"][0]["tensor"])
    tile_fp32_eff = _effective_mac_per_math_cycle(datasets["tile.fp32"][0]["tensor"])
    tile_int8_eff = _effective_mac_per_math_cycle(datasets["tile.int8"][0]["tensor"])

    if not (bulk_fp32_eff < bulk_fp16_eff < bulk_int8_eff):
        return _fail(
            "bulk precision trend mismatch: expected fp32 < fp16 < int8 "
            f"but got fp32={bulk_fp32_eff:.6f}, fp16={bulk_fp16_eff:.6f}, int8={bulk_int8_eff:.6f}"
        )
    if not (tile_fp32_eff < tile_fp16_eff < tile_int8_eff):
        return _fail(
            "tile precision trend mismatch: expected fp32 < fp16 < int8 "
            f"but got fp32={tile_fp32_eff:.6f}, fp16={tile_fp16_eff:.6f}, int8={tile_int8_eff:.6f}"
        )

    print("[m1] PASS")
    print(
        "[m1] bulk_eff_mac_per_math_cycle:"
        f" fp32={bulk_fp32_eff:.6f} fp16={bulk_fp16_eff:.6f} int8={bulk_int8_eff:.6f}"
    )
    print(
        "[m1] tile_eff_mac_per_math_cycle:"
        f" fp32={tile_fp32_eff:.6f} fp16={tile_fp16_eff:.6f} int8={tile_int8_eff:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
