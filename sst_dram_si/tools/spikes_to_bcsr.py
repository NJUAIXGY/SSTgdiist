#!/usr/bin/env python3
"""
Convert spike (src, dst, timestamp) text into packed BCSR weight files.

Each unique (src -> dst) pair accumulates a weight (default = occurrence count),
and the final sparse matrix is emitted in the same layout as generate_bcsr.py:
  [rowptr uint32[n_block_rows+1]]
  [colidx uint{idx_bytes}[nnz_blocks]]
  [weights float32[nnz_blocks * br * bc]]
  [dst_ids uint32[nnz_blocks * br * bc]]  (post global IDs or sentinel)

The matrix is organised per MultiCorePE: rows = neurons_per_core (=rows_per_core),
columns = total neurons (cols_total). Block rows/cols follow br/bc parameters.
"""

import argparse
import json
import math
import os
import struct
from collections import defaultdict
from typing import Dict, List, Tuple

SENTINEL_ID = 0xFFFFFFFF


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0:
        return value
    return ((value + alignment - 1) // alignment) * alignment


def parse_spike_file(path: str) -> List[Tuple[int, int]]:
    """Return list of (src, dst) from spike text (ignoring timestamp)."""
    pairs: List[Tuple[int, int]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                src = int(parts[0])
                dst = int(parts[1])
            except ValueError:
                continue
            pairs.append((src, dst))
    return pairs


def accumulate_weights(pairs: List[Tuple[int, int]],
                       rows_per_core: int,
                       cores: int,
                       cols_total: int,
                       weight_scale: float) -> List[Dict[int, Dict[int, float]]]:
    """
    Aggregate spike pairs into per-core sparse matrix:
      result[core][post_global][pre_global] = weight
    """
    matrices: List[Dict[int, Dict[int, float]]] = [
        defaultdict(dict) for _ in range(cores)
    ]
    for src, dst in pairs:
        if src < 0 or src >= cols_total or dst < 0:
            continue
        core = dst // rows_per_core
        if core < 0 or core >= cores:
            continue
        post_global = dst
        pre_global = src
        row_map = matrices[core].setdefault(post_global, {})
        row_map[pre_global] = row_map.get(pre_global, 0.0) + weight_scale
    return matrices


def build_blocks(rows_per_core: int,
                 br: int,
                 bc: int,
                 core_weights: Dict[int, Dict[int, float]],
                 core_base: int,
                 cols_total: int) -> Tuple[List[int], List[int], List[float], List[int]]:
    """Construct BCSR arrays (rowptr, colidx, blockdata, dst_ids) for a single core."""
    n_block_rows = math.ceil(rows_per_core / br)
    weights_blocks: Dict[Tuple[int, int], List[float]] = {}
    block_cols_per_row: Dict[int, set] = defaultdict(set)

    for post_global, pre_dict in core_weights.items():
        post_local = post_global - core_base
        if post_local < 0 or post_local >= rows_per_core:
            continue
        block_row = post_local // br
        rr = post_local % br
        for pre_global, weight in pre_dict.items():
            if pre_global < 0 or pre_global >= cols_total:
                continue
            block_col = pre_global // bc
            cc = pre_global % bc
            key = (block_row, block_col)
            block_cols_per_row[block_row].add(block_col)
            blk = weights_blocks.get(key)
            if blk is None:
                blk = [0.0] * (br * bc)
                weights_blocks[key] = blk
            blk[rr * bc + cc] += weight

    rowptr: List[int] = [0] * (n_block_rows + 1)
    colidx: List[int] = []
    blockdata: List[float] = []
    blockids: List[int] = []

    for block_row in range(n_block_rows):
        cols = sorted(block_cols_per_row.get(block_row, []))
        rowptr[block_row] = len(colidx)
        for block_col in cols:
            colidx.append(block_col)
            blk = weights_blocks.get((block_row, block_col))
            if blk is None:
                blk = [0.0] * (br * bc)
            blockdata.extend(blk)
            base_post = block_row * br
            for rr in range(br):
                post_local = base_post + rr
                post_global = core_base + post_local
                for cc in range(bc):
                    if 0 <= post_local < rows_per_core:
                        blockids.append(post_global)
                    else:
                        blockids.append(SENTINEL_ID)
    rowptr[n_block_rows] = len(colidx)

    return rowptr, colidx, blockdata, blockids


def write_bcsr_file(path: str,
                    rowptr: List[int],
                    colidx: List[int],
                    blockdata: List[float],
                    blockids: List[int],
                    idx_bytes: int,
                    align: int) -> Tuple[int, int, int, int]:
    """Write BCSR sections with alignment. Return offsets (rowptr,colidx,blockdata,blockids)."""
    row_bytes = struct.pack(f"<{len(rowptr)}I", *rowptr)
    if idx_bytes == 2:
        ci_fmt = f"<{len(colidx)}H"
        col_bytes = struct.pack(ci_fmt, *[min(0xFFFF, x) for x in colidx])
    else:
        ci_fmt = f"<{len(colidx)}I"
        col_bytes = struct.pack(ci_fmt, *colidx)
    weight_bytes = struct.pack(f"<{len(blockdata)}f", *blockdata)
    ids_bytes = struct.pack(f"<{len(blockids)}I", *blockids)

    off_rowptr = 0
    off_colidx = align_up(len(row_bytes), align)
    off_blockdata = align_up(off_colidx + len(col_bytes), align)
    off_blockids = align_up(off_blockdata + len(weight_bytes), align)
    total_size = off_blockids + len(ids_bytes)

    buf = bytearray(total_size)
    buf[off_rowptr:off_rowptr + len(row_bytes)] = row_bytes
    buf[off_colidx:off_colidx + len(col_bytes)] = col_bytes
    buf[off_blockdata:off_blockdata + len(weight_bytes)] = weight_bytes
    buf[off_blockids:off_blockids + len(ids_bytes)] = ids_bytes

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(buf)
    return off_rowptr, off_colidx, off_blockdata, off_blockids


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate spike src-dst into BCSR weights.")
    ap.add_argument("--spike-file", required=True)
    ap.add_argument("--cores", type=int, required=True)
    ap.add_argument("--rows-per-core", type=int, required=True)
    ap.add_argument("--cols-total", type=int, required=True)
    ap.add_argument("--br", type=int, default=16)
    ap.add_argument("--bc", type=int, default=16)
    ap.add_argument("--idx-bytes", type=int, choices=[2, 4], default=2)
    ap.add_argument("--align", type=int, default=64)
    ap.add_argument("--weight-scale", type=float, default=1.0,
                    help="Scale applied per spike occurrence (default=1.0).")
    ap.add_argument("--out-template", required=True,
                    help="Output path template, supports {core} or {core:02d}.")
    ap.add_argument("--meta-path", type=str, default=None,
                    help="Optional explicit path for meta JSON (default derived from template).")
    args = ap.parse_args()

    pairs = parse_spike_file(args.spike_file)
    matrices = accumulate_weights(pairs,
                                  args.rows_per_core,
                                  args.cores,
                                  args.cols_total,
                                  args.weight_scale)

    meta = {
        "rows": args.rows_per_core,
        "cols": args.cols_total,
        "br": args.br,
        "bc": args.bc,
        "idx_bytes": args.idx_bytes,
        "val_bytes": 4,
        "cores": args.cores,
        "pattern": "from_spikes",
        "weight_scale": args.weight_scale,
        "source_spike_file": args.spike_file,
        "align": args.align,
        "files": []
    }

    sample_offsets = None
    total_blocks = None
    per_core_stride = None

    for core in range(args.cores):
        path = args.out_template.format(core=core)
        core_base = core * args.rows_per_core
        rowptr, colidx, blockdata, blockids = build_blocks(
            args.rows_per_core,
            args.br,
            args.bc,
            matrices[core],
            core_base,
            args.cols_total
        )
        offsets = write_bcsr_file(path,
                                  rowptr,
                                  colidx,
                                  blockdata,
                                  blockids,
                                  args.idx_bytes,
                                  args.align)
        rp_off, ci_off, bd_off, ids_off = offsets
        meta["files"].append({
            "core": core,
            "path": path,
            "rowptr_offset": rp_off,
            "colidx_offset": ci_off,
            "blockdata_offset": bd_off,
            "blockids_offset": ids_off,
            "nnz_blocks": len(colidx),
        })
        sample_offsets = offsets
        total_blocks = len(colidx)
        per_core_stride = align_up(ids_off + len(blockids) * 4, args.align)
        print(f"[spikes2bcsr] core{core:02d}: blocks={total_blocks}, file={path}")

    if sample_offsets:
        rp_off, ci_off, bd_off, ids_off = sample_offsets
        meta["offsets"] = {
            "rowptr_offset": rp_off,
            "colidx_offset": ci_off,
            "blockdata_offset": bd_off,
            "blockids_offset": ids_off,
        }
        meta["nnz_blocks_per_core"] = total_blocks
        meta["per_core_stride_estimate"] = per_core_stride

    meta_path = args.meta_path
    if not meta_path:
        try:
            meta_path = args.out_template.format(core="meta") + ".json"
        except Exception:
            meta_path = args.out_template + ".meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"[spikes2bcsr] meta written: {meta_path}")


if __name__ == "__main__":
    main()
