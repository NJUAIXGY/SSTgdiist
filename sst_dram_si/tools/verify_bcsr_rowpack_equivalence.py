#!/usr/bin/env python3
"""
Byte-exact equivalence checker for BCSR datasets:

- flat layout (.bcsr.bin + .meta.json)
- rowpack_v1 layout (.bcsr.bin + .meta.json)

Goal: prove that rowpack_v1 is a pure *physical layout* transform and preserves the exact matrix
content (rowptr/colidx/blockdata/blockids), so any behavioral drift must come from loaders/parsers.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional, Tuple


def _align_up(x: int, a: int) -> int:
    if a <= 0:
        return x
    return ((x + a - 1) // a) * a


@dataclass(frozen=True)
class BcsrMeta:
    rows: int
    cols: int
    br: int
    bc: int
    idx_bytes: int
    val_bytes: int
    rowptr_offset: int
    colidx_offset: int
    blockdata_offset: int
    blockids_offset: int
    file_size: int
    total_blocks: int
    layout_mode: str
    colidx_row_stride_bytes: int
    blockdata_row_stride_bytes: int
    blockids_row_stride_bytes: int


def _load_meta(meta_path: Path) -> BcsrMeta:
    j = json.loads(meta_path.read_text(encoding="utf-8"))
    def gi(k: str, default: int = 0) -> int:
        v = j.get(k, default)
        try:
            return int(v)
        except Exception:
            return default
    def gs(k: str, default: str = "") -> str:
        v = j.get(k, default)
        return str(v or default)
    return BcsrMeta(
        rows=gi("rows"),
        cols=gi("cols"),
        br=gi("br") or 16,
        bc=gi("bc") or 16,
        idx_bytes=gi("idx_bytes") or 2,
        val_bytes=gi("val_bytes") or 4,
        rowptr_offset=gi("rowptr_offset"),
        colidx_offset=gi("colidx_offset"),
        blockdata_offset=gi("blockdata_offset"),
        blockids_offset=gi("blockids_offset"),
        file_size=gi("file_size"),
        total_blocks=gi("total_blocks"),
        layout_mode=gs("layout_mode", "flat").strip().lower(),
        colidx_row_stride_bytes=gi("colidx_row_stride_bytes"),
        blockdata_row_stride_bytes=gi("blockdata_row_stride_bytes"),
        blockids_row_stride_bytes=gi("blockids_row_stride_bytes"),
    )


def _resolve_core_file(path_or_dataset: Path, pe: int, core: int) -> Path:
    if path_or_dataset.is_dir():
        return path_or_dataset / f"pe{pe:02d}" / f"core{core:02d}.bcsr.bin"
    return path_or_dataset


def _read_exact(f: BinaryIO, off: int, n: int) -> bytes:
    f.seek(off, os.SEEK_SET)
    b = f.read(n)
    if len(b) != n:
        raise IOError(f"short read: off={off} need={n} got={len(b)}")
    return b


def _first_diff(a: bytes, b: bytes) -> Optional[int]:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return None


def _num_block_rows(rows: int, br: int) -> int:
    if br <= 0:
        return 0
    return (rows + br - 1) // br


def _parse_u32_le(data: bytes) -> Tuple[int, ...]:
    if len(data) % 4 != 0:
        raise ValueError("u32 buffer not multiple of 4")
    n = len(data) // 4
    return struct.unpack(f"<{n}I", data)


def _row_colidx_off(meta: BcsrMeta, block_row: int, start_index: int) -> int:
    if meta.layout_mode == "rowpack_v1":
        if meta.colidx_row_stride_bytes <= 0:
            raise ValueError("rowpack_v1 but colidx_row_stride_bytes=0")
        return meta.colidx_offset + block_row * meta.colidx_row_stride_bytes
    return meta.colidx_offset + start_index * meta.idx_bytes


def _row_blockdata_off(meta: BcsrMeta, block_row: int, start_index: int, bytes_per_block: int) -> int:
    if meta.layout_mode == "rowpack_v1":
        if meta.blockdata_row_stride_bytes <= 0:
            raise ValueError("rowpack_v1 but blockdata_row_stride_bytes=0")
        return meta.blockdata_offset + block_row * meta.blockdata_row_stride_bytes
    return meta.blockdata_offset + start_index * bytes_per_block


def _row_blockids_off(meta: BcsrMeta, block_row: int, start_elem: int, bytes_per_elem: int) -> int:
    if meta.layout_mode == "rowpack_v1" and meta.blockids_row_stride_bytes > 0:
        return meta.blockids_offset + block_row * meta.blockids_row_stride_bytes
    return meta.blockids_offset + start_elem * bytes_per_elem


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flat", required=True, help="flat dataset dir OR core file path")
    ap.add_argument("--rowpack", required=True, help="rowpack_v1 dataset dir OR core file path")
    ap.add_argument("--pe", type=int, default=0, help="PE index (used when --flat/--rowpack are dirs)")
    ap.add_argument("--core", type=int, default=0, help="Core index (used when --flat/--rowpack are dirs)")
    ap.add_argument("--no-blockids", action="store_true", help="Skip blockids byte-compare (faster)")
    args = ap.parse_args()

    flat_path = _resolve_core_file(Path(args.flat), args.pe, args.core)
    rowpack_path = _resolve_core_file(Path(args.rowpack), args.pe, args.core)
    if not flat_path.exists():
        raise SystemExit(f"flat core file not found: {flat_path}")
    if not rowpack_path.exists():
        raise SystemExit(f"rowpack core file not found: {rowpack_path}")

    flat_meta = _load_meta(Path(str(flat_path) + ".meta.json"))
    row_meta = _load_meta(Path(str(rowpack_path) + ".meta.json"))

    # Basic shape invariants.
    for k in ("rows", "cols", "br", "bc", "idx_bytes", "val_bytes"):
        fv = getattr(flat_meta, k)
        rv = getattr(row_meta, k)
        if fv != rv:
            print(f"[bcsr-eq] FAIL: meta mismatch {k}: flat={fv} rowpack={rv}")
            return 2
    if flat_meta.layout_mode != "flat":
        print(f"[bcsr-eq] WARN: flat meta layout_mode={flat_meta.layout_mode!r} (expected 'flat')")
    if row_meta.layout_mode != "rowpack_v1":
        print(f"[bcsr-eq] FAIL: rowpack meta layout_mode={row_meta.layout_mode!r} (expected 'rowpack_v1')")
        return 2

    n_block_rows = _num_block_rows(flat_meta.rows, flat_meta.br)
    bytes_per_block = flat_meta.br * flat_meta.bc * flat_meta.val_bytes
    bytes_per_blockids_elem = 4  # uint32
    blockids_elems_per_block = flat_meta.br * flat_meta.bc
    bytes_per_blockids_block = blockids_elems_per_block * bytes_per_blockids_elem

    # Read and compare rowptr.
    rowptr_bytes = (n_block_rows + 1) * 4
    with flat_path.open("rb") as ff, rowpack_path.open("rb") as rf:
        flat_rowptr = _read_exact(ff, flat_meta.rowptr_offset, rowptr_bytes)
        row_rowptr = _read_exact(rf, row_meta.rowptr_offset, rowptr_bytes)
        if flat_rowptr != row_rowptr:
            di = _first_diff(flat_rowptr, row_rowptr)
            print(f"[bcsr-eq] FAIL: rowptr bytes differ at byte={di}")
            return 3
        rowptr = _parse_u32_le(flat_rowptr)
        derived_blocks = int(rowptr[-1])
        if flat_meta.total_blocks and int(flat_meta.total_blocks) != derived_blocks:
            print(f"[bcsr-eq] FAIL: flat total_blocks mismatch meta={flat_meta.total_blocks} derived={derived_blocks}")
            return 3
        if row_meta.total_blocks and int(row_meta.total_blocks) != derived_blocks:
            print(f"[bcsr-eq] FAIL: rowpack total_blocks mismatch meta={row_meta.total_blocks} derived={derived_blocks}")
            return 3

        # Compare per-row segments exactly.
        for br_i in range(n_block_rows):
            start = int(rowptr[br_i])
            end = int(rowptr[br_i + 1])
            cnt = max(0, end - start)
            if cnt == 0:
                continue

            # colidx
            flat_col_off = _row_colidx_off(flat_meta, br_i, start)
            row_col_off = _row_colidx_off(row_meta, br_i, start)
            need_col = cnt * flat_meta.idx_bytes
            flat_col = _read_exact(ff, flat_col_off, need_col)
            row_col = _read_exact(rf, row_col_off, need_col)
            if flat_col != row_col:
                di = _first_diff(flat_col, row_col)
                item = (di // flat_meta.idx_bytes) if di is not None else -1
                print(f"[bcsr-eq] FAIL: colidx mismatch block_row={br_i} item={item} byte={di}")
                return 4

            # blockdata
            flat_data_off = _row_blockdata_off(flat_meta, br_i, start, bytes_per_block)
            row_data_off = _row_blockdata_off(row_meta, br_i, start, bytes_per_block)
            need_data = cnt * bytes_per_block
            flat_data = _read_exact(ff, flat_data_off, need_data)
            row_data = _read_exact(rf, row_data_off, need_data)
            if flat_data != row_data:
                di = _first_diff(flat_data, row_data)
                blk = (di // bytes_per_block) if di is not None else -1
                print(f"[bcsr-eq] FAIL: blockdata mismatch block_row={br_i} block_in_row={blk} byte={di}")
                return 5

            # blockids (flat in rowpack_v1 by generator contract)
            if not args.no_blockids and flat_meta.blockids_offset and row_meta.blockids_offset:
                start_elem = start * blockids_elems_per_block
                need_ids = cnt * bytes_per_blockids_block
                flat_ids_off = _row_blockids_off(flat_meta, br_i, start_elem, bytes_per_blockids_elem)
                row_ids_off = _row_blockids_off(row_meta, br_i, start_elem, bytes_per_blockids_elem)
                flat_ids = _read_exact(ff, flat_ids_off, need_ids)
                row_ids = _read_exact(rf, row_ids_off, need_ids)
                if flat_ids != row_ids:
                    di = _first_diff(flat_ids, row_ids)
                    blk = (di // bytes_per_blockids_block) if di is not None else -1
                    print(f"[bcsr-eq] FAIL: blockids mismatch block_row={br_i} block_in_row={blk} byte={di}")
                    return 6

    print(f"[bcsr-eq] PASS: flat == rowpack_v1 (pe={args.pe} core={args.core})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

