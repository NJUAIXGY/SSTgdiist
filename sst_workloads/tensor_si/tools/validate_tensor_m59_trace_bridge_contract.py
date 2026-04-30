#!/usr/bin/env python3
"""Validate M59 trace->spec bridge contract."""

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


def _load_tensor(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tensor = payload.get("tensor")
    return tensor if isinstance(tensor, dict) else None


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--collective", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    base_p = Path(args.baseline).expanduser().resolve()
    coll_p = Path(args.collective).expanduser().resolve()

    if not base_p.exists():
        return _fail(2, f"[m59][P0] missing --baseline summary: {base_p}")
    if not coll_p.exists():
        return _fail(2, f"[m59][P0] missing --collective summary: {coll_p}")

    base = _load_tensor(base_p)
    coll = _load_tensor(coll_p)
    if base is None or coll is None:
        return _fail(2, "[m59][P0] invalid summary schema: missing tensor object")

    b_ops = _to_int(base.get("tensor_program_ops_total"))
    c_ops = _to_int(coll.get("tensor_program_ops_total"))
    b_iters = _to_int(base.get("tensor_program_iters_total"))
    c_iters = _to_int(coll.get("tensor_program_iters_total"))

    b_mem = _to_int(base.get("tensor_mem_bytes_read_total"))
    c_mem = _to_int(coll.get("tensor_mem_bytes_read_total"))

    b_coll_bytes = _to_int(base.get("tensor_collective_bytes_sent_total"))
    c_coll_bytes = _to_int(coll.get("tensor_collective_bytes_sent_total"))

    if b_ops <= 0 or c_ops <= 0:
        return _fail(3, f"[m59][P1] expected program_ops_total > 0 (baseline={b_ops}, collective={c_ops})")
    if b_iters <= 0 or c_iters <= 0:
        return _fail(3, f"[m59][P1] expected program_iters_total > 0 (baseline={b_iters}, collective={c_iters})")
    if c_ops <= b_ops:
        return _fail(3, f"[m59][P1] expected collective ops_total > baseline (baseline={b_ops}, collective={c_ops})")
    if b_mem <= 0 or c_mem <= 0:
        return _fail(3, f"[m59][P1] expected mem_bytes_read_total > 0 (baseline={b_mem}, collective={c_mem})")
    if c_coll_bytes <= b_coll_bytes:
        return _fail(
            3,
            "[m59][P1] expected collective bytes_sent increase after trace bridge "
            f"(baseline={b_coll_bytes}, collective={c_coll_bytes})",
        )

    prefix = f"[m59:{args.label}] " if args.label else "[m59] "
    print(f"{prefix}program_ops baseline={b_ops} collective={c_ops} program_iters baseline={b_iters} collective={c_iters}")
    print(f"{prefix}mem_read_bytes baseline={b_mem} collective={c_mem}")
    print(f"{prefix}collective_bytes_sent baseline={b_coll_bytes} collective={c_coll_bytes}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
