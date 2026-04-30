#!/usr/bin/env python3
"""Validate M12 trend expectations for PE-shared DMA budget in tensor workload.

M12 introduces an optional PE-local shared DMA/HBM bandwidth budget
(tensor_dma_shared_bandwidth_bytes_per_cycle). When enabled, aggregate
progress should slow down relative to the per-core DMA budget baseline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _fail(msg: str) -> int:
    print(f"[m12] FAIL: {msg}")
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
        "tensor_dram_bytes_total",
        "tensor_iter_cycles_total",
        "tensor_dma_cycles_total",
        "tensor_mem_bytes_read_total",
        "tensor_mem_bytes_write_total",
        "tensor_stall_mem_outstanding_cycles_total",
    )
    for key in required:
        if key not in t:
            return False, f"{label}: missing key {key}", {}
        if _num(t, key) < 0:
            return False, f"{label}: negative key {key}", {}

    if _num(t, "tensor_dram_bytes_total") <= 0:
        return False, f"{label}: tensor_dram_bytes_total must be > 0", {}
    if _num(t, "tensor_iter_cycles_total") <= 0:
        return False, f"{label}: tensor_iter_cycles_total must be > 0", {}
    return True, "", t


def _eff_dram_bytes_per_cycle(t: Dict[str, Any]) -> float:
    it = _num(t, "tensor_iter_cycles_total")
    if it <= 0:
        return 0.0
    return _num(t, "tensor_dram_bytes_total") / it


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-core", required=True, help="baseline: per-core DMA budget summary")
    ap.add_argument("--shared", required=True, help="variant: PE-shared DMA budget summary")
    args = ap.parse_args()

    per_core_summary = _load_summary(args.per_core)
    shared_summary = _load_summary(args.shared)

    ok, reason, per_core = _tensor(per_core_summary, "per_core")
    if not ok:
        return _fail(reason)
    ok, reason, shared = _tensor(shared_summary, "shared")
    if not ok:
        return _fail(reason)

    # Basic sanity: same bytes moved (same microbench). Require exact match to catch partial runs.
    dram_per = int(_num(per_core, "tensor_dram_bytes_total"))
    dram_shared = int(_num(shared, "tensor_dram_bytes_total"))
    if dram_per != dram_shared:
        return _fail(f"expected equal dram bytes but got per_core={dram_per} shared={dram_shared}")

    dma_per = float(_num(per_core, "tensor_dma_cycles_total"))
    dma_shared = float(_num(shared, "tensor_dma_cycles_total"))
    if dma_shared <= dma_per * 1.50:
        return _fail(
            "expected shared dma cycles to be noticeably larger than per-core "
            f"but got per_core={int(dma_per)} shared={int(dma_shared)}"
        )

    out_per = float(_num(per_core, "tensor_stall_mem_outstanding_cycles_total"))
    out_shared = float(_num(shared, "tensor_stall_mem_outstanding_cycles_total"))
    if out_per <= 0:
        return _fail(
            "expected per-core scenario to experience some mem_outstanding stalls "
            f"but got per_core={int(out_per)}"
        )
    if out_shared >= out_per:
        return _fail(
            "expected shared scenario to reduce mem_outstanding stalls "
            f"but got per_core={int(out_per)} shared={int(out_shared)}"
        )

    eff_per = _eff_dram_bytes_per_cycle(per_core)
    eff_shared = _eff_dram_bytes_per_cycle(shared)

    print("[m12] PASS")
    print(
        "[m12] per_core:"
        f" dma_cycles={int(dma_per)}"
        f" mem_out_stall={int(out_per)}"
        f" eff_dram_B/cyc={eff_per:.4f}"
    )
    print(
        "[m12] shared:"
        f" dma_cycles={int(dma_shared)}"
        f" mem_out_stall={int(out_shared)}"
        f" eff_dram_B/cyc={eff_shared:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
