#!/usr/bin/env python3
"""Validate M36 dashboard contract for essential_summary_tensor_mesh.json.

M36 intent:
- Stabilize a minimal set of summary metrics that downstream dashboards can rely on.
- Include derived fields (e.g., avg latency) and ensure they are self-consistent.

This validator is intentionally "required subset" rather than "exact schema":
- It checks presence + basic invariants for a curated metric set.
- It does not constrain extra keys or future extensions.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


REQUIRED_TENSOR_KEYS = (
    # Core cycles.
    "tensor_compute_cycles_total",
    "tensor_compute_math_cycles_total",
    "tensor_compute_pipeline_cycles_total",
    "tensor_dma_cycles_total",
    "tensor_dma_stall_cycles_total",
    # Memory traffic + latency observability.
    "tensor_mem_reads_issued_total",
    "tensor_mem_bytes_read_total",
    "tensor_mem_writes_issued_total",
    "tensor_mem_bytes_write_total",
    "tensor_mem_read_latency_cycles_total",
    "tensor_mem_read_latency_cycles_max",
    "tensor_mem_read_latency_samples_total",
    "tensor_mem_read_latency_cycles_avg",
    "tensor_mem_write_latency_cycles_total",
    "tensor_mem_write_latency_cycles_max",
    "tensor_mem_write_latency_samples_total",
    "tensor_mem_write_latency_cycles_avg",
    # Program busy breakdown for bottleneck explanation.
    "tensor_program_any_busy_cycles_total",
    "tensor_program_dma_busy_cycles_total",
    "tensor_program_mxu_busy_cycles_total",
    "tensor_program_vec_busy_cycles_total",
    "tensor_program_coll_busy_cycles_total",
    "tensor_vector_cycles_total",
    "tensor_collective_cycles_total",
    # NoC traffic.
    "tensor_pkt_sent_total",
    "tensor_pkt_recv_total",
    "tensor_pkt_bytes_sent_total",
    "tensor_pkt_bytes_recv_total",
    # On-chip modeling signals (may be 0 in many runs, but should be present).
    "tensor_mxu_io_busy_cycles_total",
    "tensor_stall_onchip_port_cycles_total",
    "tensor_stall_onchip_bank_conflict_cycles_total",
)


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _to_int(value: Any) -> Tuple[bool, int]:
    if isinstance(value, bool):
        return False, 0
    if isinstance(value, int):
        return True, value
    if isinstance(value, float):
        if not math.isfinite(value):
            return False, 0
        return True, int(value)
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return False, 0
        try:
            f = float(txt)
        except Exception:
            return False, 0
        if not math.isfinite(f):
            return False, 0
        return True, int(f)
    return False, 0


def _to_float(value: Any) -> Tuple[bool, float]:
    if isinstance(value, bool):
        return False, 0.0
    if isinstance(value, (int, float)):
        f = float(value)
        return (math.isfinite(f)), f
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return False, 0.0
        try:
            f = float(txt)
        except Exception:
            return False, 0.0
        return (math.isfinite(f)), f
    return False, 0.0


def _get_int(d: Dict[str, Any], key: str) -> Tuple[bool, int]:
    return _to_int(d.get(key))


def _get_float(d: Dict[str, Any], key: str) -> Tuple[bool, float]:
    return _to_float(d.get(key))


def _require_keys(tensor: Dict[str, Any]) -> Tuple[bool, str]:
    for k in REQUIRED_TENSOR_KEYS:
        if k not in tensor:
            return False, k
    return True, ""


def _check_latency_group(
    tensor: Dict[str, Any],
    prefix: str,
    issued_key: str,
    total_key: str,
    max_key: str,
    samples_key: str,
    avg_key: str,
) -> Tuple[bool, str]:
    ok_issued, issued = _get_int(tensor, issued_key)
    ok_total, total = _get_int(tensor, total_key)
    ok_max, maxv = _get_int(tensor, max_key)
    ok_samples, samples = _get_int(tensor, samples_key)
    ok_avg, avg = _get_float(tensor, avg_key)
    if not (ok_issued and ok_total and ok_max and ok_samples and ok_avg):
        return False, f"[{prefix}][P0] invalid numeric fields in latency group"

    if issued < 0 or total < 0 or maxv < 0 or samples < 0:
        return False, f"[{prefix}][P1] latency group fields must be non-negative"

    if samples > issued:
        return False, f"[{prefix}][P1] expected {samples_key} <= {issued_key} (samples={samples}, issued={issued})"

    if total < maxv:
        return False, f"[{prefix}][P1] expected {total_key} >= {max_key} (total={total}, max={maxv})"

    if samples == 0:
        if total != 0 or maxv != 0:
            return False, f"[{prefix}][P1] expected zero total/max when samples==0 (total={total}, max={maxv})"
        if abs(avg) > 1e-12:
            return False, f"[{prefix}][P1] expected avg==0.0 when samples==0 (avg={avg})"
        return True, ""

    if total <= 0 or maxv <= 0:
        return False, f"[{prefix}][P1] expected positive total/max when samples>0 (total={total}, max={maxv})"

    expected = float(total) / float(samples)
    if abs(avg - expected) > 1e-9:
        return False, f"[{prefix}][P1] avg mismatch: got {avg:.12g}, expected {expected:.12g}"

    return True, ""


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True, help="essential_summary_tensor_mesh.json path")
    ap.add_argument("--label", default="", help="optional label for logs")
    args = ap.parse_args(argv)

    summary_path = Path(args.summary).expanduser().resolve()
    if not summary_path.exists():
        return _fail(2, f"[m36][P0] missing --summary: {summary_path}")

    try:
        payload = _load_json(summary_path)
    except Exception as exc:
        return _fail(2, f"[m36][P0] cannot parse summary json: {exc}")
    if not isinstance(payload, dict):
        return _fail(2, "[m36][P0] summary root must be an object")

    tensor = payload.get("tensor", {})
    if not isinstance(tensor, dict):
        return _fail(2, "[m36][P0] missing tensor object in summary")

    ok_keys, missing = _require_keys(tensor)
    if not ok_keys:
        return _fail(3, f"[m36][P1] missing required tensor metric: {missing}")

    ok_cc, cc = _get_int(tensor, "tensor_compute_cycles_total")
    ok_math, math_cc = _get_int(tensor, "tensor_compute_math_cycles_total")
    ok_pipe, pipe_cc = _get_int(tensor, "tensor_compute_pipeline_cycles_total")
    if not (ok_cc and ok_math and ok_pipe):
        return _fail(3, "[m36][P1] invalid compute cycle fields")
    if cc < 0 or math_cc < 0 or pipe_cc < 0:
        return _fail(3, "[m36][P1] compute cycle fields must be non-negative")
    if math_cc > cc:
        return _fail(3, f"[m36][P1] expected compute_math_cycles_total <= compute_cycles_total (math={math_cc}, total={cc})")
    if pipe_cc > cc:
        return _fail(
            3, f"[m36][P1] expected compute_pipeline_cycles_total <= compute_cycles_total (pipe={pipe_cc}, total={cc})"
        )

    ok_dma, dma_cc = _get_int(tensor, "tensor_dma_cycles_total")
    ok_dma_stall, dma_stall = _get_int(tensor, "tensor_dma_stall_cycles_total")
    if not (ok_dma and ok_dma_stall):
        return _fail(3, "[m36][P1] invalid dma cycle fields")
    if dma_cc < 0 or dma_stall < 0:
        return _fail(3, "[m36][P1] dma cycle fields must be non-negative")
    if dma_stall > dma_cc:
        return _fail(3, f"[m36][P1] expected dma_stall <= dma_cycles (stall={dma_stall}, total={dma_cc})")

    ok_any, any_busy = _get_int(tensor, "tensor_program_any_busy_cycles_total")
    ok_dma_b, dma_busy = _get_int(tensor, "tensor_program_dma_busy_cycles_total")
    ok_mxu_b, mxu_busy = _get_int(tensor, "tensor_program_mxu_busy_cycles_total")
    ok_vec_b, vec_busy = _get_int(tensor, "tensor_program_vec_busy_cycles_total")
    ok_coll_b, coll_busy = _get_int(tensor, "tensor_program_coll_busy_cycles_total")
    if not (ok_any and ok_dma_b and ok_mxu_b and ok_vec_b and ok_coll_b):
        return _fail(3, "[m36][P1] invalid program busy breakdown fields")
    if any(v < 0 for v in (any_busy, dma_busy, mxu_busy, vec_busy, coll_busy)):
        return _fail(3, "[m36][P1] program busy breakdown fields must be non-negative")

    ok_vec_total, vec_total = _get_int(tensor, "tensor_vector_cycles_total")
    ok_coll_total, coll_total = _get_int(tensor, "tensor_collective_cycles_total")
    if not (ok_vec_total and ok_coll_total):
        return _fail(3, "[m36][P1] invalid vector/collective cycle totals")
    if vec_total < 0 or coll_total < 0:
        return _fail(3, "[m36][P1] vector/collective cycle totals must be non-negative")
    if dma_busy > dma_cc:
        return _fail(3, f"[m36][P1] expected program_dma_busy <= dma_cycles_total (busy={dma_busy}, dma={dma_cc})")
    if mxu_busy > cc:
        return _fail(3, f"[m36][P1] expected program_mxu_busy <= compute_cycles_total (busy={mxu_busy}, compute={cc})")
    if vec_busy > vec_total:
        return _fail(3, f"[m36][P1] expected program_vec_busy <= vector_cycles_total (busy={vec_busy}, vec={vec_total})")
    if coll_busy > coll_total:
        return _fail(
            3, f"[m36][P1] expected program_coll_busy <= collective_cycles_total (busy={coll_busy}, coll={coll_total})"
        )

    ok_io, io_busy = _get_int(tensor, "tensor_mxu_io_busy_cycles_total")
    if not ok_io:
        return _fail(3, "[m36][P1] invalid tensor_mxu_io_busy_cycles_total")
    if io_busy < 0:
        return _fail(3, "[m36][P1] mxu_io_busy must be non-negative")
    if io_busy > cc:
        return _fail(3, f"[m36][P1] expected mxu_io_busy <= compute_cycles_total (io={io_busy}, compute={cc})")

    ok_port, port_stall = _get_int(tensor, "tensor_stall_onchip_port_cycles_total")
    ok_bank, bank_stall = _get_int(tensor, "tensor_stall_onchip_bank_conflict_cycles_total")
    if not (ok_port and ok_bank):
        return _fail(3, "[m36][P1] invalid on-chip stall fields")
    if port_stall < 0 or bank_stall < 0:
        return _fail(3, "[m36][P1] on-chip stall fields must be non-negative")
    if port_stall > cc:
        return _fail(3, f"[m36][P1] expected onchip_port_stall <= compute_cycles_total (stall={port_stall}, compute={cc})")
    if bank_stall > cc:
        return _fail(3, f"[m36][P1] expected onchip_bank_stall <= compute_cycles_total (stall={bank_stall}, compute={cc})")

    ok_r, msg_r = _check_latency_group(
        tensor,
        "m36:mem_read",
        "tensor_mem_reads_issued_total",
        "tensor_mem_read_latency_cycles_total",
        "tensor_mem_read_latency_cycles_max",
        "tensor_mem_read_latency_samples_total",
        "tensor_mem_read_latency_cycles_avg",
    )
    if not ok_r:
        return _fail(3, f"[m36][P1] {msg_r}")

    ok_w, msg_w = _check_latency_group(
        tensor,
        "m36:mem_write",
        "tensor_mem_writes_issued_total",
        "tensor_mem_write_latency_cycles_total",
        "tensor_mem_write_latency_cycles_max",
        "tensor_mem_write_latency_samples_total",
        "tensor_mem_write_latency_cycles_avg",
    )
    if not ok_w:
        return _fail(3, f"[m36][P1] {msg_w}")

    prefix = f"[m36:{args.label}] " if args.label else "[m36] "
    ok_avg_r, avg_r = _get_float(tensor, "tensor_mem_read_latency_cycles_avg")
    ok_avg_w, avg_w = _get_float(tensor, "tensor_mem_write_latency_cycles_avg")
    if ok_avg_r and ok_avg_w:
        print(f"{prefix}mem_latency_avg_cycles: read={avg_r:.3f} write={avg_w:.3f}")
    print(f"{prefix}compute_cycles_total: {cc} (math={math_cc}, pipe={pipe_cc})")
    print(
        f"{prefix}program_any_busy_cycles_total: {any_busy} "
        f"(dma={dma_busy}, mxu={mxu_busy}, vec={vec_busy}, coll={coll_busy})"
    )
    print(f"{prefix}mxu_io_busy_cycles_total: {io_busy}")
    print(f"{prefix}onchip_stall_cycles_total: port={port_stall} bank_conflict={bank_stall}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
