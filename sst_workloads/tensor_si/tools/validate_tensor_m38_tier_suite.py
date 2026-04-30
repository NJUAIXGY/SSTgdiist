#!/usr/bin/env python3
"""Validate M38 tiered benchmark suite contract (operator/subgraph/e2e proxy)."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


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


def _to_float(value: Any) -> Tuple[bool, float]:
    try:
        if isinstance(value, bool):
            return False, 0.0
        if isinstance(value, (int, float)):
            f = float(value)
            return math.isfinite(f), f
        txt = str(value).strip()
        if not txt:
            return False, 0.0
        f = float(txt)
        return math.isfinite(f), f
    except Exception:
        return False, 0.0


def _load_summary(path: Path) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    try:
        payload = _load_json(path)
    except Exception:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    tensor = payload.get("tensor")
    readiness = payload.get("npu_tpu_readiness")
    if not isinstance(tensor, dict):
        return None, None
    if not isinstance(readiness, dict):
        readiness = {}
    return tensor, readiness


def _score_from_readiness_or_tensor(readiness: Dict[str, Any], tensor: Dict[str, Any]) -> Tuple[bool, float]:
    ok, v = _to_float(readiness.get("capability_score_total"))
    if ok:
        return True, v
    return _to_float(tensor.get("tensor_capability_score_total"))


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--operator", required=True, help="operator-tier summary path")
    ap.add_argument("--subgraph", required=True, help="subgraph-tier summary path")
    ap.add_argument("--e2e", required=True, help="e2e-proxy tier summary path")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    op_p = Path(args.operator).expanduser().resolve()
    sg_p = Path(args.subgraph).expanduser().resolve()
    e2e_p = Path(args.e2e).expanduser().resolve()

    for p in (op_p, sg_p, e2e_p):
        if not p.exists():
            return _fail(2, f"[m38][P0] missing summary: {p}")

    op_t, op_r = _load_summary(op_p)
    sg_t, sg_r = _load_summary(sg_p)
    e2e_t, e2e_r = _load_summary(e2e_p)
    if op_t is None or sg_t is None or e2e_t is None:
        return _fail(2, "[m38][P0] invalid summary schema: missing tensor object")

    ok_op, score_op = _score_from_readiness_or_tensor(op_r or {}, op_t)
    ok_sg, score_sg = _score_from_readiness_or_tensor(sg_r or {}, sg_t)
    ok_e2e, score_e2e = _score_from_readiness_or_tensor(e2e_r or {}, e2e_t)
    if not (ok_op and ok_sg and ok_e2e):
        return _fail(3, "[m38][P1] missing capability score in one or more summaries")

    for tag, score in (("operator", score_op), ("subgraph", score_sg), ("e2e", score_e2e)):
        if score < 0.0 or score > 100.0:
            return _fail(3, f"[m38][P1] capability score out of range for {tag}: {score}")

    op_ops = _to_int(op_t.get("tensor_program_ops_total"))
    sg_ops = _to_int(sg_t.get("tensor_program_ops_total"))
    e2e_ops = _to_int(e2e_t.get("tensor_program_ops_total"))
    if op_ops <= 0 or sg_ops <= 0 or e2e_ops <= 0:
        return _fail(3, f"[m38][P1] expected tensor_program_ops_total > 0 (op={op_ops}, sg={sg_ops}, e2e={e2e_ops})")
    if e2e_ops < op_ops:
        return _fail(3, f"[m38][P1] expected e2e_ops >= operator_ops (e2e={e2e_ops}, op={op_ops})")

    op_mxu_busy = _to_int(op_t.get("tensor_program_mxu_busy_cycles_total"))
    if op_mxu_busy <= 0:
        return _fail(3, f"[m38][P1] expected operator tier mxu busy > 0 (got {op_mxu_busy})")

    sg_dma_busy = _to_int(sg_t.get("tensor_program_dma_busy_cycles_total"))
    sg_coll_busy = _to_int(sg_t.get("tensor_program_coll_busy_cycles_total"))
    if sg_dma_busy <= 0 and sg_coll_busy <= 0:
        return _fail(
            3,
            "[m38][P1] expected subgraph tier to expose dma or collective activity "
            f"(dma={sg_dma_busy}, coll={sg_coll_busy})",
        )

    e2e_pkt = _to_int(e2e_t.get("tensor_pkt_bytes_sent_total")) + _to_int(e2e_t.get("tensor_pkt_bytes_recv_total"))
    e2e_coll = _to_int(e2e_t.get("tensor_program_coll_busy_cycles_total"))
    if e2e_pkt <= 0 and e2e_coll <= 0:
        return _fail(3, f"[m38][P1] expected e2e tier to expose collective/network activity (pkt={e2e_pkt}, coll={e2e_coll})")

    score_set = {round(score_op, 3), round(score_sg, 3), round(score_e2e, 3)}
    if len(score_set) < 2:
        return _fail(3, "[m38][P1] expected tier scores to show diversity (all tiers identical)")

    avg_score = (score_op + score_sg + score_e2e) / 3.0

    prefix = f"[m38:{args.label}] " if args.label else "[m38] "
    print(f"{prefix}scores: operator={score_op:.3f} subgraph={score_sg:.3f} e2e={score_e2e:.3f} avg={avg_score:.3f}")
    print(f"{prefix}ops_total: operator={op_ops} subgraph={sg_ops} e2e={e2e_ops}")
    print(
        f"{prefix}activity: operator_mxu={op_mxu_busy} "
        f"subgraph_dma={sg_dma_busy} subgraph_coll={sg_coll_busy} "
        f"e2e_pkt={e2e_pkt} e2e_coll={e2e_coll}"
    )
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
