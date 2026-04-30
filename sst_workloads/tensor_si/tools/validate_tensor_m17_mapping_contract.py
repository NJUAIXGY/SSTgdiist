#!/usr/bin/env python3
"""Validate M17 mapping->spec compilation contract.

M17 intent:
- A minimal mapping JSON can be compiled into a schema-v3 tensor spec.
- The compiled spec is runnable in SST-SnnDL program mode.

This validator checks:
1) mapping program ops -> compiled spec program ops (non-empty + preserved length)
2) compiled spec is schema-v3 tensor + exec_mode=program
3) run summary shows program progress (iters/ops > 0)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _get_int(d: Dict[str, Any], key: str) -> int:
    try:
        return int(d.get(key, 0) or 0)
    except Exception:
        return 0


def _load_tensor_summary(summary_path: Path) -> Dict[str, Any] | None:
    try:
        obj = _load_json(summary_path)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    t = obj.get("tensor", {})
    return t if isinstance(t, dict) else None


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapping", required=True, help="input mapping json path")
    ap.add_argument("--spec", required=True, help="compiled spec json path")
    ap.add_argument("--summary", required=True, help="essential_summary_tensor_mesh.json path")
    ap.add_argument("--label", default="", help="optional scenario label (for logs)")
    args = ap.parse_args(argv)

    mapping_path = Path(args.mapping).expanduser().resolve()
    spec_path = Path(args.spec).expanduser().resolve()
    summary_path = Path(args.summary).expanduser().resolve()
    if not mapping_path.exists():
        return _fail(2, f"[m17][P0] missing mapping: {mapping_path}")
    if not spec_path.exists():
        return _fail(2, f"[m17][P0] missing spec: {spec_path}")
    if not summary_path.exists():
        return _fail(2, f"[m17][P0] missing summary: {summary_path}")

    try:
        mapping = _load_json(mapping_path)
        spec = _load_json(spec_path)
    except Exception as exc:
        return _fail(2, f"[m17][P0] failed to load json: {exc}")
    if not isinstance(mapping, dict) or not isinstance(spec, dict):
        return _fail(2, "[m17][P0] mapping/spec json must be objects")

    # 1) Mapping program ops contract.
    map_prog = _as_dict(mapping.get("program"))
    map_ops = _as_list(map_prog.get("ops"))
    if len(map_ops) <= 0:
        return _fail(3, "[m17][P1] mapping.program.ops must be a non-empty list")

    # 2) Spec schema + program mode.
    if int(spec.get("schema_version", 0) or 0) != 3:
        return _fail(3, f"[m17][P1] expected spec.schema_version==3, got {spec.get('schema_version')}")
    if str(spec.get("model", "")) != "tensor":
        return _fail(3, f"[m17][P1] expected spec.model=='tensor', got {spec.get('model')!r}")
    wl = _as_dict(spec.get("workload"))
    if str(wl.get("type", "")) != "tensor":
        return _fail(3, f"[m17][P1] expected spec.workload.type=='tensor', got {wl.get('type')!r}")

    params = _as_dict(wl.get("params"))
    if str(params.get("tensor_exec_mode", "")) != "program":
        return _fail(
            3,
            f"[m17][P1] expected tensor_exec_mode='program', got {params.get('tensor_exec_mode')!r}",
        )

    spec_prog = _as_dict(wl.get("program"))
    spec_ops = _as_list(spec_prog.get("ops"))
    if len(spec_ops) != len(map_ops):
        return _fail(3, f"[m17][P1] expected compiled ops preserved (map={len(map_ops)} spec={len(spec_ops)})")
    if any(not isinstance(op, dict) or not str(op.get("op_type", "")).strip() for op in spec_ops):
        return _fail(3, "[m17][P1] compiled spec program ops must be objects with non-empty op_type")

    # 3) Run summary shows progress.
    t = _load_tensor_summary(summary_path)
    if t is None:
        return _fail(2, "[m17][P0] invalid summary schema: missing tensor object")
    iters = _get_int(t, "tensor_program_iters_total")
    ops = _get_int(t, "tensor_program_ops_total")
    if iters <= 0 or ops <= 0:
        return _fail(3, f"[m17][P1] expected program progress (iters={iters}, ops={ops})")

    prefix = f"[m17:{args.label}] " if args.label else "[m17] "
    print(f"{prefix}program_ops(map)={len(map_ops)} program_iters_total={iters} program_ops_total={ops}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

