from __future__ import annotations

import glob
import json
import os
from typing import Any, Dict, List, Tuple

from .utils import align_up


def _is_valid_bcsr_root(root: str) -> bool:
    if not root:
        return False
    pe0 = os.path.join(root, "pe00")
    meta = os.path.join(pe0, "core00.bcsr.bin.meta.json")
    data = os.path.join(pe0, "core00.bcsr.bin")
    return os.path.exists(meta) and os.path.exists(data)


def resolve_global_bcsr_dir(weights_dir: str) -> str:
    default_10k = os.path.join(weights_dir, "bcsr_global_16pe_fanout256_10k")
    default_100k = os.path.join(weights_dir, "bcsr_global_16pe_fanout256")

    env = os.environ.get("MESH_BCSR_DIR", "").strip()
    if env:
        env_abs = os.path.abspath(env)
        if _is_valid_bcsr_root(env_abs):
            return env_abs
        return env_abs

    if _is_valid_bcsr_root(default_10k):
        return default_10k
    if _is_valid_bcsr_root(default_100k):
        return default_100k

    pattern = os.path.join(weights_dir, "*", "pe00", "core00.bcsr.bin.meta.json")
    for meta_path in sorted(glob.glob(pattern)):
        root = os.path.dirname(os.path.dirname(meta_path))
        if _is_valid_bcsr_root(root):
            return root
    return default_100k


def scan_all_bcsr_meta_files(base_dir: str) -> List[Tuple[str, Dict[str, Any]]]:
    if not base_dir or not os.path.exists(base_dir):
        return []
    pat = os.path.join(base_dir, "pe??", "core??.bcsr.bin.meta.json")
    metas: List[Tuple[str, Dict[str, Any]]] = []
    for mp in sorted(glob.glob(pat)):
        try:
            with open(mp, "r", encoding="utf-8") as mf:
                meta = json.load(mf)
            if isinstance(meta, dict):
                metas.append((mp, meta))
        except Exception:
            continue
    return metas


def load_core_bcsr_meta(bcsr_dir: str, pe_id: int, core_idx: int) -> Dict[str, Any]:
    meta_path = os.path.join(bcsr_dir, f"pe{pe_id:02d}", f"core{core_idx:02d}.bcsr.bin.meta.json")
    if not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as mf:
            meta = json.load(mf)
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


def load_global_bcsr_catalog(bcsr_dir: str) -> Dict[str, Any]:
    meta_path = os.path.join(bcsr_dir, "pe00", "core00.bcsr.bin.meta.json")
    if not os.path.exists(meta_path):
        return {
            "available": False,
            "meta_path": meta_path,
            "meta": {},
            "all_meta": scan_all_bcsr_meta_files(bcsr_dir),
            "max_file_size": 0,
            "offsets": {},
        }

    try:
        with open(meta_path, "r", encoding="utf-8") as mf:
            meta = json.load(mf)
        meta = meta if isinstance(meta, dict) else {}
    except Exception:
        return {
            "available": False,
            "meta_path": meta_path,
            "meta": {},
            "all_meta": scan_all_bcsr_meta_files(bcsr_dir),
            "max_file_size": 0,
            "offsets": {},
        }

    all_meta = scan_all_bcsr_meta_files(bcsr_dir)
    sizes: List[int] = []
    try:
        sizes.append(int(meta.get("file_size", 0)))
    except Exception:
        sizes.append(0)
    for _, m in all_meta:
        try:
            sizes.append(int(m.get("file_size", 0)))
        except Exception:
            continue
    max_file_size = max(sizes) if sizes else 0

    offsets = {
        "rowptr_offset": int(meta.get("rowptr_offset", 0) or 0),
        "colidx_offset": int(meta.get("colidx_offset", 0) or 0),
        "blockdata_offset": int(meta.get("blockdata_offset", 0) or 0),
        "blockids_offset": int(meta.get("blockids_offset", 0) or 0),
        "layout_mode": str(meta.get("layout_mode", "flat") or "flat"),
        "colidx_row_stride_bytes": int(meta.get("colidx_row_stride_bytes", 0) or 0),
        "blockdata_row_stride_bytes": int(meta.get("blockdata_row_stride_bytes", 0) or 0),
        "blockids_row_stride_bytes": int(meta.get("blockids_row_stride_bytes", 0) or 0),
        "br": int(meta.get("br", 1) or 1),
        "bc": int(meta.get("bc", 16) or 16),
        "idx_bytes": int(meta.get("idx_bytes", 4) or 4),
        "val_bytes": int(meta.get("val_bytes", 4) or 4),
    }

    return {
        "available": True,
        "meta_path": meta_path,
        "meta": meta,
        "all_meta": all_meta,
        "max_file_size": max_file_size,
        "offsets": offsets,
    }


def _scan_max_file_size(base_dir: str, pattern: str) -> int:
    if not base_dir or not os.path.exists(base_dir):
        return 0
    sizes: List[int] = []
    for fp in glob.glob(os.path.join(base_dir, pattern)):
        try:
            sizes.append(int(os.path.getsize(fp)))
        except Exception:
            continue
    return max(sizes) if sizes else 0


def resolve_weight_layout_for_mode(
    *,
    synapse_weight_mode: str,
    gcssnt_dir: str,
    bcsr_core_file_size: int,
    num_cores_per_pe: int,
    row_align_bytes: int = 8192,
    base_addr_shift_env_key: str = "MESH_BASE_ADDR_SHIFT",
) -> Dict[str, Any]:
    core_file_size = int(bcsr_core_file_size or 0)
    layout_source = "bcsr"

    if core_file_size <= 0:
        core_file_size = 1 << 20

    per_core_weight_stride = align_up(core_file_size, row_align_bytes)
    pe_weight_region_stride = per_core_weight_stride * int(num_cores_per_pe)

    base_addr_global_shift = per_core_weight_stride
    env = os.environ.get(base_addr_shift_env_key, "").strip()
    if env:
        try:
            base_addr_global_shift = int(env, 0)
        except Exception:
            base_addr_global_shift = per_core_weight_stride

    base_addr_aligned_from = None
    if base_addr_global_shift % row_align_bytes != 0:
        base_addr_aligned_from = base_addr_global_shift
        base_addr_global_shift = align_up(base_addr_global_shift, row_align_bytes)

    return {
        "layout_source": layout_source,
        "core_file_size": core_file_size,
        "per_core_weight_stride": per_core_weight_stride,
        "pe_weight_region_stride": pe_weight_region_stride,
        "base_addr_global_shift": base_addr_global_shift,
        "base_addr_aligned_from": base_addr_aligned_from,
        "row_align_bytes": row_align_bytes,
    }


def resolve_global_bcsr_runtime(
    *,
    weights_dir: str,
    total_nodes: int,
    num_cores_per_pe: int,
    neurons_per_core: int,
    row_align_bytes: int = 8192,
    base_addr_shift_env_key: str = "MESH_BASE_ADDR_SHIFT",
) -> Dict[str, Any]:
    """
    Resolve the "global BCSR" runtime contract used by test_mesh_4x4.py.

    Returns a dict that includes:
    - bcsr_dir/catalog/meta/offsets
    - columns override from meta
    - optional neurons_per_core override from meta["rows"]
    - core_file_size + aligned per-core stride + per-PE region stride
    - base_addr_global_shift (aligned to row_align_bytes)

    Important: this function does NOT mutate caller state; it only computes.
    """

    bcsr_dir = resolve_global_bcsr_dir(weights_dir)
    catalog = load_global_bcsr_catalog(bcsr_dir)

    available = bool(catalog.get("available", False))
    meta = catalog.get("meta", {}) or {}
    offsets = catalog.get("offsets", {}) or {}

    global_weights_cols = total_nodes * (num_cores_per_pe * neurons_per_core)
    if available:
        try:
            global_weights_cols = int(meta.get("cols", global_weights_cols))
        except Exception:
            pass

    neurons_per_core_override = neurons_per_core
    if available:
        try:
            rows_meta = int(meta.get("rows", 0) or 0)
            if rows_meta > 0:
                neurons_per_core_override = rows_meta
        except Exception:
            pass

    layout = resolve_weight_layout_for_mode(
        synapse_weight_mode="bcsr_gas",
        gcssnt_dir="",
        bcsr_core_file_size=int(catalog.get("max_file_size", 0) or 0),
        num_cores_per_pe=num_cores_per_pe,
        row_align_bytes=row_align_bytes,
        base_addr_shift_env_key=base_addr_shift_env_key,
    )

    return {
        "available": available,
        "bcsr_dir": bcsr_dir,
        "catalog": catalog,
        "meta_path": catalog.get("meta_path"),
        "meta": meta,
        "all_meta": catalog.get("all_meta", []),
        "offsets": offsets,
        "global_weights_cols": global_weights_cols,
        "neurons_per_core_override": neurons_per_core_override,
        "core_file_size": int(layout["core_file_size"]),
        "per_core_weight_stride": int(layout["per_core_weight_stride"]),
        "pe_weight_region_stride": int(layout["pe_weight_region_stride"]),
        "base_addr_global_shift": int(layout["base_addr_global_shift"]),
        "base_addr_aligned_from": layout.get("base_addr_aligned_from"),
        "row_align_bytes": row_align_bytes,
        "layout_source": str(layout.get("layout_source", "bcsr") or "bcsr"),
    }


def apply_step_activation_bcsr_defaults_from_global_offsets(
    *,
    state: Dict[str, Any],
    global_offsets: Dict[str, Any],
) -> None:
    """
    Fill STEP_ACTIVATION_BCSR_* defaults from global offsets when they are None.

    Mutates `state` in-place (caller typically passes globals()).
    """

    def _set_if_none(key: str, value: Any) -> None:
        if state.get(key) is None:
            state[key] = value

    _set_if_none("STEP_ACTIVATION_BCSR_ROWPTR_OFFSET", global_offsets.get("rowptr_offset", 0))
    _set_if_none("STEP_ACTIVATION_BCSR_COLIDX_OFFSET", global_offsets.get("colidx_offset", 0))
    _set_if_none("STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET", global_offsets.get("blockdata_offset", 0))
    _set_if_none("STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET", global_offsets.get("blockids_offset", 0))

    _set_if_none("STEP_ACTIVATION_BCSR_BR", global_offsets.get("br", 16))
    _set_if_none("STEP_ACTIVATION_BCSR_BC", global_offsets.get("bc", 16))
    _set_if_none("STEP_ACTIVATION_BCSR_IDX_BYTES", global_offsets.get("idx_bytes", 2))
    _set_if_none("STEP_ACTIVATION_BCSR_VAL_BYTES", global_offsets.get("val_bytes", 4))
