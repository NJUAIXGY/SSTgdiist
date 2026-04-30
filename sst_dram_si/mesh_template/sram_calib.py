from __future__ import annotations

import json
import os
from typing import Any, Dict, Tuple


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_nonneg_int(value: Any, default: int) -> int:
    v = _to_int(value, default)
    return v if v >= 0 else int(default)


def _section(src: Dict[str, Any], key: str) -> Dict[str, Any]:
    v = src.get(key, {})
    return v if isinstance(v, dict) else {}


def load_sram_calib_json(path: str, *, strict: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Load and sanitize SRAM calibration JSON.

    Returned tuple:
      - calibrated: sanitized dict (may be empty)
      - meta: {"path","loaded","reason","error"}
    """
    meta: Dict[str, Any] = {
        "path": str(path or ""),
        "loaded": 0,
        "reason": "disabled",
        "error": "",
    }
    if not path:
        meta["reason"] = "path_empty"
        return {}, meta
    if not os.path.exists(path):
        msg = f"sram calib json not found: {path}"
        meta["reason"] = "not_found"
        meta["error"] = msg
        if strict:
            raise RuntimeError(msg)
        return {}, meta
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        msg = f"failed to parse sram calib json {path}: {e}"
        meta["reason"] = "parse_failed"
        meta["error"] = msg
        if strict:
            raise RuntimeError(msg)
        return {}, meta

    if not isinstance(raw, dict):
        msg = f"invalid sram calib json root type: {type(raw)}"
        meta["reason"] = "invalid_type"
        meta["error"] = msg
        if strict:
            raise RuntimeError(msg)
        return {}, meta

    idx = _section(raw, "weight_idx")
    l0 = _section(raw, "weight_l0")
    st = _section(raw, "state")
    layout = _section(raw, "layout")

    calibrated: Dict[str, Any] = {
        "weight_idx": {
            "capacity_bytes": _to_nonneg_int(idx.get("capacity_bytes", 0), 0),
            "banks": _to_nonneg_int(idx.get("banks", 16), 16),
            "ports_per_bank": _to_nonneg_int(idx.get("ports_per_bank", 1), 1),
            "bank_interleave_bytes": _to_nonneg_int(idx.get("bank_interleave_bytes", 4), 4),
            "t_read_cycles": _to_nonneg_int(idx.get("t_read_cycles", 1), 1),
            "t_write_cycles": _to_nonneg_int(idx.get("t_write_cycles", 1), 1),
            "sample_log2": _to_nonneg_int(idx.get("sample_log2", 0), 0),
        },
        "weight_l0": {
            "capacity_bytes": _to_nonneg_int(l0.get("capacity_bytes", 0), 0),
            "banks": _to_nonneg_int(l0.get("banks", 8), 8),
            "ports_per_bank": _to_nonneg_int(l0.get("ports_per_bank", 1), 1),
            "bank_interleave_bytes": _to_nonneg_int(l0.get("bank_interleave_bytes", 4), 4),
            "t_read_cycles": _to_nonneg_int(l0.get("t_read_cycles", 1), 1),
            "t_write_cycles": _to_nonneg_int(l0.get("t_write_cycles", 1), 1),
            "sample_log2": _to_nonneg_int(l0.get("sample_log2", 0), 0),
            "slots": _to_nonneg_int(l0.get("slots", 1 << 20), 1 << 20),
        },
        "state": {
            "enable": _to_nonneg_int(st.get("enable", 0), 0),
            "capacity_bytes": _to_nonneg_int(st.get("capacity_bytes", 0), 0),
            "banks": _to_nonneg_int(st.get("banks", 16), 16),
            "ports_per_bank": _to_nonneg_int(st.get("ports_per_bank", 1), 1),
            "bank_interleave_bytes": _to_nonneg_int(st.get("bank_interleave_bytes", 4), 4),
            "t_read_cycles": _to_nonneg_int(st.get("t_read_cycles", 1), 1),
            "t_write_cycles": _to_nonneg_int(st.get("t_write_cycles", 1), 1),
            "sample_log2": _to_nonneg_int(st.get("sample_log2", 0), 0),
        },
        "layout": {
            "weight_idx_base": _to_nonneg_int(layout.get("weight_idx_base", 0x100000000), 0x100000000),
            "weight_l0_base": _to_nonneg_int(layout.get("weight_l0_base", 0x200000000), 0x200000000),
            "state_vmem_base": _to_nonneg_int(layout.get("state_vmem_base", 0x300000000), 0x300000000),
            "state_refrac_base": _to_nonneg_int(layout.get("state_refrac_base", 0x400000000), 0x400000000),
            "state_last_spike_base": _to_nonneg_int(layout.get("state_last_spike_base", 0x500000000), 0x500000000),
        },
    }
    meta["loaded"] = 1
    meta["reason"] = "ok"
    return calibrated, meta

