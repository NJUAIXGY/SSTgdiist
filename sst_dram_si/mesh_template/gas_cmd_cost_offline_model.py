from __future__ import annotations

import os
from typing import Any, Dict, Tuple


# Ramulator2 org/timing presets used for offline cmd-cost derivation.
# The values are copied from upstream ramulator2 preset definitions.
_ORG_PRESETS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "DDR5": {
        "DDR5_8Gb_x4": {"dq": 4, "geometry": {"channel": 1, "rank": 1, "bankgroup": 8, "bank": 2, "row": 1 << 16, "column": 1 << 11}},
        "DDR5_8Gb_x8": {"dq": 8, "geometry": {"channel": 1, "rank": 1, "bankgroup": 8, "bank": 2, "row": 1 << 16, "column": 1 << 10}},
        "DDR5_8Gb_x16": {"dq": 16, "geometry": {"channel": 1, "rank": 1, "bankgroup": 4, "bank": 2, "row": 1 << 16, "column": 1 << 10}},
        "DDR5_16Gb_x4": {"dq": 4, "geometry": {"channel": 1, "rank": 1, "bankgroup": 8, "bank": 4, "row": 1 << 16, "column": 1 << 11}},
        "DDR5_16Gb_x8": {"dq": 8, "geometry": {"channel": 1, "rank": 1, "bankgroup": 8, "bank": 4, "row": 1 << 16, "column": 1 << 10}},
        "DDR5_16Gb_x16": {"dq": 16, "geometry": {"channel": 1, "rank": 1, "bankgroup": 4, "bank": 4, "row": 1 << 16, "column": 1 << 10}},
        "DDR5_32Gb_x4": {"dq": 4, "geometry": {"channel": 1, "rank": 1, "bankgroup": 8, "bank": 4, "row": 1 << 17, "column": 1 << 11}},
        "DDR5_32Gb_x8": {"dq": 8, "geometry": {"channel": 1, "rank": 1, "bankgroup": 8, "bank": 4, "row": 1 << 17, "column": 1 << 10}},
        "DDR5_32Gb_x16": {"dq": 16, "geometry": {"channel": 1, "rank": 1, "bankgroup": 4, "bank": 4, "row": 1 << 17, "column": 1 << 10}},
    },
    "HBM2": {
        "HBM2_2Gb": {"dq": 128, "geometry": {"channel": 1, "pseudochannel": 2, "bankgroup": 4, "bank": 2, "row": 1 << 14, "column": 1 << 6}},
        "HBM2_4Gb": {"dq": 128, "geometry": {"channel": 1, "pseudochannel": 2, "bankgroup": 4, "bank": 4, "row": 1 << 14, "column": 1 << 6}},
        "HBM2_8Gb": {"dq": 128, "geometry": {"channel": 1, "pseudochannel": 2, "bankgroup": 4, "bank": 4, "row": 1 << 15, "column": 1 << 6}},
    },
}

_TIMING_PRESETS: Dict[str, Dict[str, Dict[str, int]]] = {
    "DDR5": {
        "DDR5_3200AN": {"rate": 3200, "nBL": 8, "nCL": 24, "nRCD": 24, "nRP": 24, "nRAS": 52, "tCK_ps": 625},
        "DDR5_3200BN": {"rate": 3200, "nBL": 8, "nCL": 26, "nRCD": 26, "nRP": 26, "nRAS": 52, "tCK_ps": 625},
        "DDR5_3200C": {"rate": 3200, "nBL": 8, "nCL": 28, "nRCD": 28, "nRP": 28, "nRAS": 52, "tCK_ps": 625},
    },
    "HBM2": {
        "HBM2_2Gbps": {"rate": 2000, "nBL": 4, "nCL": 7, "nRCD": 7, "nRP": 7, "nRAS": 17, "tCK_ps": 1000},
    },
}


def _strip_inline_comment(line: str) -> str:
    if "#" in line:
        line = line.split("#", 1)[0]
    return line.rstrip()


def _parse_simple_cfg_tree(cfg_path: str) -> Dict[Tuple[str, ...], str]:
    kv: Dict[Tuple[str, ...], str] = {}
    stack: list[Tuple[int, str]] = []
    with open(cfg_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = _strip_inline_comment(raw)
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.lstrip(" ")
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            while stack and indent <= stack[-1][0]:
                stack.pop()
            if not value:
                stack.append((indent, key))
                continue
            path = tuple([x[1] for x in stack] + [key])
            kv[path] = value
    return kv


def _as_int(value: str, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def derive_dram_cmd_cost_from_ramulator2_cfg(
    *,
    ramulator2_cfg_file: str,
    line_bytes: int = 64,
) -> Dict[str, Any]:
    if not ramulator2_cfg_file:
        raise ValueError("ramulator2 cfg path is empty")
    if not os.path.isfile(ramulator2_cfg_file):
        raise ValueError(f"ramulator2 cfg not found: {ramulator2_cfg_file}")

    cfg = _parse_simple_cfg_tree(ramulator2_cfg_file)
    dram_impl = str(cfg.get(("MemorySystem", "DRAM", "impl"), "")).strip()
    org_preset = str(cfg.get(("MemorySystem", "DRAM", "org", "preset"), "")).strip()
    timing_preset = str(cfg.get(("MemorySystem", "DRAM", "timing", "preset"), "")).strip()
    channel_override = _as_int(str(cfg.get(("MemorySystem", "DRAM", "org", "channel"), "")).strip(), 0)
    rank_override = _as_int(str(cfg.get(("MemorySystem", "DRAM", "org", "rank"), "")).strip(), 0)

    if dram_impl not in _ORG_PRESETS or dram_impl not in _TIMING_PRESETS:
        raise ValueError(f"unsupported DRAM.impl={dram_impl!r} for offline cmd-cost model")
    if org_preset not in _ORG_PRESETS[dram_impl]:
        raise ValueError(f"unsupported org preset for {dram_impl}: {org_preset!r}")
    if timing_preset not in _TIMING_PRESETS[dram_impl]:
        raise ValueError(f"unsupported timing preset for {dram_impl}: {timing_preset!r}")

    org = _ORG_PRESETS[dram_impl][org_preset]
    timing = _TIMING_PRESETS[dram_impl][timing_preset]

    geometry = dict(org["geometry"])
    if channel_override > 0:
        geometry["channel"] = channel_override
    if rank_override > 0:
        geometry["rank"] = rank_override
    if "rank" not in geometry:
        geometry["rank"] = 1

    n_cl = int(timing["nCL"])
    n_bl = int(timing["nBL"])
    n_rcd = int(timing["nRCD"])
    n_rp = int(timing["nRP"])
    n_ras = int(timing["nRAS"])
    t_ck_ps = int(timing["tCK_ps"])
    rate_mt = int(timing["rate"])

    hit_cycles = n_cl + n_bl
    miss_extra_cycles = n_rcd + n_rp + n_ras
    miss_cycles = hit_cycles + miss_extra_cycles

    t_row_hit_ns = max(1, int(round((hit_cycles * t_ck_ps) / 1000.0)))
    t_row_miss_ns = max(t_row_hit_ns, int(round((miss_cycles * t_ck_ps) / 1000.0)))

    line_bytes_eff = int(line_bytes) if int(line_bytes) > 0 else 64
    k_lines = max(0, (t_row_miss_ns - t_row_hit_ns) // t_row_hit_ns)
    k_bytes = k_lines * line_bytes_eff

    channels = int(geometry.get("channel", 1))
    pseudochannels = int(geometry.get("pseudochannel", 1))
    dq = int(org["dq"])
    peak_bw_bytes_per_ns = (rate_mt * dq * channels * pseudochannels) / (8.0 * 1000.0)

    bankgroup = int(geometry.get("bankgroup", 1))
    bank = int(geometry.get("bank", 1))
    rank = int(geometry.get("rank", 1))
    total_banks = channels * pseudochannels * rank * bankgroup * bank

    row = int(geometry.get("row", 0))
    column = int(geometry.get("column", 0))
    row_bytes_per_bank = int(column * dq // 8) if column > 0 else 0

    return {
        "model": "offline_preset_v1",
        "ramulator2_cfg_file": ramulator2_cfg_file,
        "dram_impl": dram_impl,
        "org_preset": org_preset,
        "timing_preset": timing_preset,
        "line_bytes": line_bytes_eff,
        "timing_cycles": {
            "nCL": n_cl,
            "nBL": n_bl,
            "nRCD": n_rcd,
            "nRP": n_rp,
            "nRAS": n_ras,
            "tCK_ps": t_ck_ps,
            "hit_cycles": hit_cycles,
            "miss_cycles": miss_cycles,
            "miss_extra_cycles": miss_extra_cycles,
        },
        "derived_cmd_cost": {
            "t_row_hit_ns": t_row_hit_ns,
            "t_row_miss_ns": t_row_miss_ns,
            "k_lines": k_lines,
            "k_bytes": k_bytes,
        },
        "geometry": {
            "channel": channels,
            "pseudochannel": pseudochannels,
            "rank": rank,
            "bankgroup": bankgroup,
            "bank": bank,
            "row": row,
            "column": column,
            "total_banks": total_banks,
            "dq": dq,
            "row_bytes_per_bank": row_bytes_per_bank,
        },
        "bandwidth": {
            "rate_mt": rate_mt,
            "peak_bw_bytes_per_ns": peak_bw_bytes_per_ns,
        },
    }
