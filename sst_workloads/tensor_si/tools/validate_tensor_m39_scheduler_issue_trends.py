#!/usr/bin/env python3
"""Validate M39 scheduler/issue semantics trends."""

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


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _load_summary(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tensor = payload.get("tensor")
    if not isinstance(tensor, dict):
        return None
    return tensor


def _load_effective_cfg(summary_path: Path) -> Dict[str, Any]:
    path = summary_path.parent / "effective_config.json"
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aggressive", required=True, help="aggressive scheduler summary json")
    ap.add_argument("--conservative", required=True, help="conservative scheduler summary json")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    aggr_p = Path(args.aggressive).expanduser().resolve()
    cons_p = Path(args.conservative).expanduser().resolve()
    if not aggr_p.exists():
        return _fail(2, f"[m39][P0] missing --aggressive summary: {aggr_p}")
    if not cons_p.exists():
        return _fail(2, f"[m39][P0] missing --conservative summary: {cons_p}")

    aggr = _load_summary(aggr_p)
    cons = _load_summary(cons_p)
    if aggr is None or cons is None:
        return _fail(2, "[m39][P0] invalid summary schema: missing tensor object")

    aggr_bytes = _to_int(aggr.get("tensor_mem_bytes_read_total"))
    cons_bytes = _to_int(cons.get("tensor_mem_bytes_read_total"))
    if aggr_bytes <= 0 or cons_bytes <= 0:
        return _fail(3, f"[m39][P1] expected mem_bytes_read_total > 0 (aggr={aggr_bytes}, cons={cons_bytes})")
    if aggr_bytes != cons_bytes:
        return _fail(3, f"[m39][P1] expected mem_bytes_read_total match (aggr={aggr_bytes}, cons={cons_bytes})")

    aggr_dma_busy = _to_int(aggr.get("tensor_program_dma_busy_cycles_total"))
    cons_dma_busy = _to_int(cons.get("tensor_program_dma_busy_cycles_total"))
    if aggr_dma_busy <= 0 or cons_dma_busy <= 0:
        return _fail(3, f"[m39][P1] expected program_dma_busy_cycles_total > 0 (aggr={aggr_dma_busy}, cons={cons_dma_busy})")
    if aggr_dma_busy > cons_dma_busy:
        return _fail(3, f"[m39][P1] expected aggressive dma busy <= conservative (aggr={aggr_dma_busy}, cons={cons_dma_busy})")

    aggr_any = _to_int(aggr.get("tensor_program_any_busy_cycles_total"))
    cons_any = _to_int(cons.get("tensor_program_any_busy_cycles_total"))
    if aggr_any <= 0 or cons_any <= 0:
        return _fail(3, f"[m39][P1] expected program_any_busy_cycles_total > 0 (aggr={aggr_any}, cons={cons_any})")
    if aggr_any > cons_any:
        return _fail(3, f"[m39][P1] expected aggressive any busy <= conservative (aggr={aggr_any}, cons={cons_any})")

    aggr_cfg = _load_effective_cfg(aggr_p)
    cons_cfg = _load_effective_cfg(cons_p)
    aggr_tensor_cfg = aggr_cfg.get("tensor_cfg") if isinstance(aggr_cfg.get("tensor_cfg"), dict) else {}
    cons_tensor_cfg = cons_cfg.get("tensor_cfg") if isinstance(cons_cfg.get("tensor_cfg"), dict) else {}

    aggr_model = str(aggr_tensor_cfg.get("tensor_scheduler_model", "")).strip()
    cons_model = str(cons_tensor_cfg.get("tensor_scheduler_model", "")).strip()
    if not aggr_model or not cons_model:
        return _fail(3, "[m39][P1] missing tensor_scheduler_model in effective config")
    if aggr_model == cons_model:
        return _fail(3, f"[m39][P1] expected distinct scheduler models (got both {aggr_model!r})")

    aggr_issue = _to_int(aggr_tensor_cfg.get("tensor_program_issue_width"))
    cons_issue = _to_int(cons_tensor_cfg.get("tensor_program_issue_width"))
    if aggr_issue <= cons_issue:
        return _fail(3, f"[m39][P1] expected aggressive issue_width > conservative (aggr={aggr_issue}, cons={cons_issue})")

    prefix = f"[m39:{args.label}] " if args.label else "[m39] "
    print(f"{prefix}mem_bytes_read_total={aggr_bytes}")
    print(f"{prefix}program_dma_busy_cycles_total: aggressive={aggr_dma_busy} conservative={cons_dma_busy}")
    print(f"{prefix}program_any_busy_cycles_total: aggressive={aggr_any} conservative={cons_any}")
    print(f"{prefix}scheduler_model: aggressive={aggr_model} conservative={cons_model} issue_width={aggr_issue}/{cons_issue}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
