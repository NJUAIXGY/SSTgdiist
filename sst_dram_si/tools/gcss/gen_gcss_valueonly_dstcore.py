#!/usr/bin/env python3
"""
Generate GCSS value-only files (dst_core resident) from existing per-core BCSR files.

Input layout:
  <bcsr_dir>/peXX/coreYY.bcsr.bin
  <bcsr_dir>/peXX/coreYY.bcsr.bin.meta.json

Output layout:
  <out_dir>/peXX/coreYY.gcss.bin
  <out_dir>/peXX/coreYY.gcss.idx.bin
  <out_dir>/peXX/coreYY.gcss.meta.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


MAGIC = b"GCSSIDX1"


@dataclass(frozen=True)
class Edge:
    pre: int
    post: int
    weight: float


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"invalid json object: {path}")
    return obj


def _read_exact(path: Path, offset: int, size: int) -> bytes:
    if size < 0:
        raise ValueError(f"invalid read size={size} path={path}")
    with path.open("rb") as f:
        f.seek(offset, os.SEEK_SET)
        b = f.read(size)
    if len(b) != size:
        raise ValueError(
            f"short read path={path} offset={offset} size={size} got={len(b)}"
        )
    return b


def _parse_core_id(path: Path) -> Tuple[int, int]:
    m = re.search(r"/pe(\d{2})/core(\d{2})\.bcsr\.bin$", str(path).replace("\\", "/"))
    if not m:
        raise ValueError(f"unexpected core path format: {path}")
    return int(m.group(1)), int(m.group(2))


def _iter_core_bcsr_files(bcsr_dir: Path) -> Iterable[Path]:
    for p in sorted(bcsr_dir.glob("pe*/core*.bcsr.bin")):
        if p.is_file():
            yield p


def _parse_bcsr_edges(bin_path: Path, epsilon: float) -> Tuple[List[Edge], Dict[str, int]]:
    meta_path = Path(str(bin_path) + ".meta.json")
    meta = _read_json(meta_path)
    rows = int(meta.get("rows", 0) or 0)
    cols = int(meta.get("cols", 0) or 0)
    br = int(meta.get("br", 0) or 0)
    bc = int(meta.get("bc", 0) or 0)
    idx_bytes = int(meta.get("idx_bytes", 0) or 0)
    val_bytes = int(meta.get("val_bytes", 0) or 0)
    rowptr_off = int(meta.get("rowptr_offset", 0) or 0)
    colidx_off = int(meta.get("colidx_offset", 0) or 0)
    blockdata_off = int(meta.get("blockdata_offset", 0) or 0)
    if rows <= 0 or cols <= 0 or br <= 0 or bc <= 0:
        raise ValueError(f"invalid shape in meta: {meta_path}")
    if idx_bytes not in (2, 4):
        raise ValueError(f"unsupported idx_bytes={idx_bytes} in {meta_path}")
    if val_bytes != 4:
        raise ValueError(f"only float32 val_bytes=4 supported, got {val_bytes} in {meta_path}")

    n_block_rows = int(math.ceil(rows / br))
    rowptr_n = n_block_rows + 1
    rowptr_raw = _read_exact(bin_path, rowptr_off, rowptr_n * 4)
    rowptr = list(struct.unpack("<" + "I" * rowptr_n, rowptr_raw))
    total_blocks = int(rowptr[-1]) if rowptr else 0
    if total_blocks < 0:
        raise ValueError(f"negative total_blocks from rowptr in {bin_path}")

    colidx_raw = _read_exact(bin_path, colidx_off, total_blocks * idx_bytes)
    if idx_bytes == 2:
        colidx = [int(v) for v in struct.unpack("<" + "H" * total_blocks, colidx_raw)]
    else:
        colidx = [int(v) for v in struct.unpack("<" + "I" * total_blocks, colidx_raw)]

    vals_per_block = br * bc
    total_vals = total_blocks * vals_per_block
    vals_raw = _read_exact(bin_path, blockdata_off, total_vals * 4)
    values = struct.unpack("<" + "f" * total_vals, vals_raw)

    edges: List[Edge] = []
    eps = abs(float(epsilon))
    for block_row in range(n_block_rows):
        start = int(rowptr[block_row])
        end = int(rowptr[block_row + 1])
        if end <= start:
            continue
        for j in range(start, end):
            block_col = int(colidx[j])
            block_base = j * vals_per_block
            for rr in range(br):
                post_local = block_row * br + rr
                if post_local >= rows:
                    break
                row_base = block_base + rr * bc
                for cc in range(bc):
                    pre_global = block_col * bc + cc
                    if pre_global >= cols:
                        break
                    w = float(values[row_base + cc])
                    if abs(w) <= eps:
                        continue
                    edges.append(Edge(pre=pre_global, post=post_local, weight=w))

    shape = {
        "rows": rows,
        "cols": cols,
        "br": br,
        "bc": bc,
        "idx_bytes": idx_bytes,
        "val_bytes": val_bytes,
        "total_blocks": total_blocks,
    }
    return edges, shape


def _order_edges(edges: Sequence[Edge], sort_mode: str) -> List[Edge]:
    if sort_mode == "pre_post":
        return sorted(edges, key=lambda e: (e.pre, e.post))
    if sort_mode == "scan":
        return list(edges)
    raise ValueError(f"unsupported sort_mode={sort_mode!r}")


def _build_index_arrays(edges: Sequence[Edge]) -> Tuple[List[int], List[int], List[int], List[int], List[int], List[int]]:
    # pre -> [(post, widx), ...] preserving edge order
    pre_map: Dict[int, List[Tuple[int, int]]] = {}
    for widx, e in enumerate(edges):
        pre_map.setdefault(e.pre, []).append((e.post, widx))

    pre_keys = sorted(pre_map.keys())
    base_widx: List[int] = []
    post_counts: List[int] = []
    post_offsets: List[int] = []
    posts: List[int] = []
    widxs: List[int] = []
    cursor = 0
    for pre in pre_keys:
        lst = pre_map[pre]
        if not lst:
            continue
        base_widx.append(min(w for _, w in lst))
        post_counts.append(len(lst))
        post_offsets.append(cursor)
        for post_local, widx in lst:
            posts.append(post_local)
            widxs.append(widx)
            cursor += 1
    return pre_keys, base_widx, post_counts, post_offsets, posts, widxs


def _write_values_bin(path: Path, edges: Sequence[Edge]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        for e in edges:
            f.write(struct.pack("<f", float(e.weight)))


def _write_index_bin(path: Path, rows_per_core: int, edges_total: int, arrays: Tuple[List[int], List[int], List[int], List[int], List[int], List[int]]) -> None:
    pre_keys, base_widx, post_counts, post_offsets, posts, widxs = arrays
    if not (len(pre_keys) == len(base_widx) == len(post_counts) == len(post_offsets)):
        raise ValueError("index arrays length mismatch")
    if len(posts) != len(widxs):
        raise ValueError("posts/widxs length mismatch")
    for p in posts:
        if p < 0 or p > 0xFFFF:
            raise ValueError(f"post_local out of uint16 range: {p}")
    for c in post_counts:
        if c < 0 or c > 0xFFFF:
            raise ValueError(f"post_count out of uint16 range: {c}")

    header = struct.pack(
        "<8sIIIIIII",
        MAGIC,
        1,  # version
        int(rows_per_core),
        int(edges_total),
        int(len(pre_keys)),
        int(len(posts)),
        0,  # flags
        0,  # reserved0
    )

    with path.open("wb") as f:
        f.write(header)
        if pre_keys:
            f.write(struct.pack("<" + "I" * len(pre_keys), *pre_keys))
            f.write(struct.pack("<" + "I" * len(base_widx), *base_widx))
            f.write(struct.pack("<" + "H" * len(post_counts), *post_counts))
            f.write(struct.pack("<" + "I" * len(post_offsets), *post_offsets))
        if posts:
            f.write(struct.pack("<" + "H" * len(posts), *posts))
            f.write(struct.pack("<" + "I" * len(widxs), *widxs))


def _write_meta_json(path: Path, pe: int, core: int, sort_mode: str, epsilon: float, shape: Dict[str, int], edges: Sequence[Edge], arrays: Tuple[List[int], List[int], List[int], List[int], List[int], List[int]]) -> None:
    pre_keys, _, _, _, posts, _ = arrays
    obj = {
        "schema_version": 1,
        "format": "gcss_valueonly_dstcore_v1",
        "pe": pe,
        "core": core,
        "sort_mode": sort_mode,
        "epsilon": float(epsilon),
        "rows": int(shape["rows"]),
        "cols": int(shape["cols"]),
        "br": int(shape["br"]),
        "bc": int(shape["bc"]),
        "edges_total": int(len(edges)),
        "distinct_pres": int(len(pre_keys)),
        "posts_total": int(len(posts)),
    }
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bcsr-dir", required=True, help="input BCSR directory, e.g. weights/bcsr_global_16pe_fanout256_10k")
    ap.add_argument("--out-dir", required=True, help="output directory for GCSS files")
    ap.add_argument("--sort-mode", choices=("scan", "pre_post"), default="pre_post")
    ap.add_argument("--epsilon", type=float, default=1e-8, help="abs(weight)<=epsilon is treated as zero edge")
    args = ap.parse_args()

    bcsr_dir = Path(args.bcsr_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not bcsr_dir.is_dir():
        raise SystemExit(f"[gcss-gen] bcsr_dir not found: {bcsr_dir}")

    core_files = list(_iter_core_bcsr_files(bcsr_dir))
    if not core_files:
        raise SystemExit(f"[gcss-gen] no core*.bcsr.bin found under: {bcsr_dir}")

    total_edges = 0
    for p in core_files:
        pe, core = _parse_core_id(p)
        edges_scan, shape = _parse_bcsr_edges(p, epsilon=float(args.epsilon))
        edges = _order_edges(edges_scan, sort_mode=args.sort_mode)
        arrays = _build_index_arrays(edges)

        pe_dir = out_dir / f"pe{pe:02d}"
        values_path = pe_dir / f"core{core:02d}.gcss.bin"
        idx_path = pe_dir / f"core{core:02d}.gcss.idx.bin"
        meta_path = pe_dir / f"core{core:02d}.gcss.meta.json"
        _write_values_bin(values_path, edges)
        _write_index_bin(idx_path, rows_per_core=int(shape["rows"]), edges_total=len(edges), arrays=arrays)
        _write_meta_json(meta_path, pe=pe, core=core, sort_mode=args.sort_mode, epsilon=float(args.epsilon), shape=shape, edges=edges, arrays=arrays)

        total_edges += len(edges)
        print(
            f"[gcss-gen] pe={pe:02d} core={core:02d} edges={len(edges)} "
            f"values={values_path} idx={idx_path}"
        )

    print(f"[gcss-gen] done: cores={len(core_files)} total_edges={total_edges} out_dir={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

