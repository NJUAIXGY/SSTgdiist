#!/usr/bin/env python3
"""Validate M13 split weight-pool trends (unified UB vs split weights).

M13 intent:
- When tensor_weight_bytes > 0, ReadB reservations consume weight pool instead of UB.
- With spill enabled and UB sized to fit A but not B:
  - unified model should spill B (spill_bytes_total > 0)
  - split model should avoid spill (spill_bytes_total == 0)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_int(d: Dict[str, Any], key: str) -> int:
    try:
        return int(d.get(key, 0) or 0)
    except Exception:
        return 0


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unified", required=True, help="unified-UB summary json path")
    ap.add_argument("--split", required=True, help="split-weight-pool summary json path")
    args = ap.parse_args(argv)

    unified_path = Path(args.unified).expanduser().resolve()
    split_path = Path(args.split).expanduser().resolve()
    if not unified_path.exists():
        return _fail(2, f"[m13][P0] missing --unified summary: {unified_path}")
    if not split_path.exists():
        return _fail(2, f"[m13][P0] missing --split summary: {split_path}")

    try:
        unified = _load_json(unified_path)
        split = _load_json(split_path)
    except Exception as exc:
        return _fail(2, f"[m13][P0] failed to load summary json: {exc}")

    unified_tensor = unified.get("tensor", {}) if isinstance(unified, dict) else {}
    split_tensor = split.get("tensor", {}) if isinstance(split, dict) else {}
    if not isinstance(unified_tensor, dict) or not isinstance(split_tensor, dict):
        return _fail(2, "[m13][P0] invalid summary schema: missing tensor object")

    unified_mac = _get_int(unified_tensor, "tensor_mac_ops_total")
    split_mac = _get_int(split_tensor, "tensor_mac_ops_total")
    if unified_mac <= 0 or split_mac <= 0:
        return _fail(
            3,
            f"[m13][P1] expected mac_ops_total > 0 (unified={unified_mac}, split={split_mac})",
        )

    unified_spill = _get_int(unified_tensor, "tensor_spill_bytes_total")
    split_spill = _get_int(split_tensor, "tensor_spill_bytes_total")
    if unified_spill <= 0:
        return _fail(3, f"[m13][P1] expected unified spill_bytes_total > 0, got {unified_spill}")
    if split_spill != 0:
        return _fail(3, f"[m13][P1] expected split spill_bytes_total == 0, got {split_spill}")

    print(f"[m13] unified spill_bytes_total={unified_spill}")
    print(f"[m13] split spill_bytes_total={split_spill}")
    print("[m13] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

