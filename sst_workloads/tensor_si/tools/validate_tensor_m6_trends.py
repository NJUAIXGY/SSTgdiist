#!/usr/bin/env python3
"""Validate M6 program-mode trend expectations for tensor workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _fail(msg: str) -> int:
    print(f"[m6] FAIL: {msg}")
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
        "tensor_collective_bytes_sent_total",
        "tensor_collective_pending_cycles_total",
        "tensor_vector_cycles_total",
        "tensor_program_ops_total",
        "tensor_program_iters_total",
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
    ap.add_argument("--gemm-only", required=True)
    ap.add_argument("--mix-base", required=True)
    ap.add_argument("--softmax-heavy", required=True)
    ap.add_argument("--allreduce-more", required=True)
    ap.add_argument("--noc-capped", required=True)
    ap.add_argument("--loop-2iters", required=True)
    args = ap.parse_args()

    datasets = {
        "gemm_only": _load_summary(args.gemm_only),
        "mix_base": _load_summary(args.mix_base),
        "softmax_heavy": _load_summary(args.softmax_heavy),
        "allreduce_more": _load_summary(args.allreduce_more),
        "noc_capped": _load_summary(args.noc_capped),
        "loop_2iters": _load_summary(args.loop_2iters),
    }

    tensors: Dict[str, Dict[str, Any]] = {}
    for label, summary in datasets.items():
        ok, reason, tensor = _tensor(summary, label)
        if not ok:
            return _fail(reason)
        tensors[label] = tensor

    gemm_only = tensors["gemm_only"]
    mix = tensors["mix_base"]
    soft_heavy = tensors["softmax_heavy"]
    allreduce_more = tensors["allreduce_more"]
    noc_capped = tensors["noc_capped"]
    loop2 = tensors["loop_2iters"]

    if _num(gemm_only, "tensor_collective_bytes_sent_total") != 0:
        return _fail(
            "gemm_only: expected no collective bytes "
            f"but got {int(_num(gemm_only, 'tensor_collective_bytes_sent_total'))}"
        )
    if _num(gemm_only, "tensor_vector_cycles_total") != 0:
        return _fail(
            "gemm_only: expected no vector cycles "
            f"but got {int(_num(gemm_only, 'tensor_vector_cycles_total'))}"
        )

    if _num(mix, "tensor_collective_bytes_sent_total") <= 0:
        return _fail("mix_base: expected collective bytes > 0")
    if _num(mix, "tensor_vector_cycles_total") <= 0:
        return _fail("mix_base: expected vector cycles > 0")

    if _num(soft_heavy, "tensor_vector_cycles_total") <= _num(mix, "tensor_vector_cycles_total"):
        return _fail(
            "softmax_heavy: expected vector cycles > mix_base "
            f"but got heavy={int(_num(soft_heavy, 'tensor_vector_cycles_total'))} "
            f"base={int(_num(mix, 'tensor_vector_cycles_total'))}"
        )

    if _num(allreduce_more, "tensor_collective_bytes_sent_total") <= _num(mix, "tensor_collective_bytes_sent_total"):
        return _fail(
            "allreduce_more: expected collective bytes > mix_base "
            f"but got more={int(_num(allreduce_more, 'tensor_collective_bytes_sent_total'))} "
            f"base={int(_num(mix, 'tensor_collective_bytes_sent_total'))}"
        )

    if _num(noc_capped, "tensor_collective_pending_cycles_total") <= _num(mix, "tensor_collective_pending_cycles_total"):
        return _fail(
            "noc_capped: expected collective pending cycles > mix_base "
            f"but got capped={int(_num(noc_capped, 'tensor_collective_pending_cycles_total'))} "
            f"base={int(_num(mix, 'tensor_collective_pending_cycles_total'))}"
        )

    mix_iters = _num(mix, "tensor_program_iters_total")
    loop_iters = _num(loop2, "tensor_program_iters_total")
    if loop_iters < (mix_iters * 2.0 - 1.0):
        return _fail(
            "loop_2iters: expected program iters ~= 2x mix_base "
            f"but got loop={int(loop_iters)} base={int(mix_iters)}"
        )

    mix_ops = _num(mix, "tensor_program_ops_total")
    loop_ops = _num(loop2, "tensor_program_ops_total")
    if loop_ops < (mix_ops * 2.0 - 1.0):
        return _fail(
            "loop_2iters: expected program ops ~= 2x mix_base "
            f"but got loop={int(loop_ops)} base={int(mix_ops)}"
        )

    print("[m6] PASS")
    print(
        "[m6] program_ops/iters:"
        f" gemm_only(op/iter)={int(_num(gemm_only, 'tensor_program_ops_total'))}/{int(_num(gemm_only, 'tensor_program_iters_total'))}"
        f" mix_base(op/iter)={int(mix_ops)}/{int(mix_iters)}"
        f" loop_2iters(op/iter)={int(loop_ops)}/{int(loop_iters)}"
    )
    print(
        "[m6] vector_cycles:"
        f" base={int(_num(mix, 'tensor_vector_cycles_total'))}"
        f" heavy={int(_num(soft_heavy, 'tensor_vector_cycles_total'))}"
    )
    print(
        "[m6] collective_bytes_sent:"
        f" base={int(_num(mix, 'tensor_collective_bytes_sent_total'))}"
        f" more={int(_num(allreduce_more, 'tensor_collective_bytes_sent_total'))}"
    )
    print(
        "[m6] collective_pending_cycles:"
        f" base={int(_num(mix, 'tensor_collective_pending_cycles_total'))}"
        f" capped={int(_num(noc_capped, 'tensor_collective_pending_cycles_total'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
