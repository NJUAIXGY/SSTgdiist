#!/usr/bin/env python3
"""Validate M7 (program-M7) trend expectations for tensor workload.

M7 focuses on explicit DMA + UB dependency + fence semantics in program mode.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _fail(msg: str) -> int:
    print(f"[m7] FAIL: {msg}")
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


def _tensor(summary: Dict[str, Any], label: str) -> Tuple[bool, str, Dict[str, Any]]:
    t = summary.get("tensor")
    if not isinstance(t, dict):
        return False, f"{label}: missing tensor section", {}

    required = (
        "tensor_mac_ops_total",
        "tensor_program_ops_total",
        "tensor_program_iters_total",
        "tensor_program_dma_busy_cycles_total",
        "tensor_program_mxu_busy_cycles_total",
        "tensor_program_ub_stall_cycles_total",
        "tensor_program_fence_count_total",
        "tensor_program_fence_wait_cycles_total",
    )
    for key in required:
        if key not in t:
            return False, f"{label}: missing key {key}", {}
        if _num(t, key) < 0:
            return False, f"{label}: negative key {key}", {}

    if _num(t, "tensor_mac_ops_total") <= 0:
        return False, f"{label}: tensor_mac_ops_total must be > 0", {}
    if _num(t, "tensor_program_ops_total") <= 0:
        return False, f"{label}: tensor_program_ops_total must be > 0", {}
    if _num(t, "tensor_program_iters_total") <= 0:
        return False, f"{label}: tensor_program_iters_total must be > 0", {}
    return True, "", t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ub-dep", required=True, help="M7 scenario: DMA->UB dependency causes UB stall")
    ap.add_argument("--fence-wait", required=True, help="M7 scenario: fence waits for in-flight DMA/mem")
    args = ap.parse_args()

    datasets = {
        "ub_dep": _load_summary(args.ub_dep),
        "fence_wait": _load_summary(args.fence_wait),
    }

    tensors: Dict[str, Dict[str, Any]] = {}
    for label, summary in datasets.items():
        ok, reason, tensor = _tensor(summary, label)
        if not ok:
            return _fail(reason)
        tensors[label] = tensor

    ub_dep = tensors["ub_dep"]
    fence_wait = tensors["fence_wait"]

    if _num(ub_dep, "tensor_program_dma_busy_cycles_total") <= 0:
        return _fail("ub_dep: expected program dma busy cycles > 0")
    if _num(ub_dep, "tensor_program_mxu_busy_cycles_total") <= 0:
        return _fail("ub_dep: expected program mxu busy cycles > 0")
    if _num(ub_dep, "tensor_program_ub_stall_cycles_total") <= 0:
        return _fail("ub_dep: expected program ub stall cycles > 0 (GemmUb blocked on DmaRead completion)")
    if _num(ub_dep, "tensor_program_fence_count_total") != 0:
        return _fail(
            "ub_dep: expected no fence count "
            f"but got {int(_num(ub_dep, 'tensor_program_fence_count_total'))}"
        )

    if _num(fence_wait, "tensor_program_dma_busy_cycles_total") <= 0:
        return _fail("fence_wait: expected program dma busy cycles > 0")
    if _num(fence_wait, "tensor_program_mxu_busy_cycles_total") <= 0:
        return _fail("fence_wait: expected program mxu busy cycles > 0")
    if _num(fence_wait, "tensor_program_fence_count_total") <= 0:
        return _fail("fence_wait: expected fence count > 0")
    if _num(fence_wait, "tensor_program_fence_wait_cycles_total") <= 0:
        return _fail("fence_wait: expected fence wait cycles > 0")

    print("[m7] PASS")
    print(
        "[m7] ub_dep:"
        f" ub_stall={int(_num(ub_dep, 'tensor_program_ub_stall_cycles_total'))}"
        f" dma_busy={int(_num(ub_dep, 'tensor_program_dma_busy_cycles_total'))}"
        f" mxu_busy={int(_num(ub_dep, 'tensor_program_mxu_busy_cycles_total'))}"
    )
    print(
        "[m7] fence_wait:"
        f" fence_count={int(_num(fence_wait, 'tensor_program_fence_count_total'))}"
        f" fence_wait={int(_num(fence_wait, 'tensor_program_fence_wait_cycles_total'))}"
        f" dma_busy={int(_num(fence_wait, 'tensor_program_dma_busy_cycles_total'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

