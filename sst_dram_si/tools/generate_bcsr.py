#!/usr/bin/env python3
"""
Generate packed BCSR weight files for SnnDL.

Layout per core (little-endian, aligned to --align bytes):
  [rowptr uint32[n_block_rows+1]]
  [colidx uint{idx_bytes}[nnz_blocks]]
  [weights float32[nnz_blocks * br * bc]]
  [dst_ids uint32[nnz_blocks * br * bc]]

dst_ids 对应 (dst_id, weight) 需求：
  - dst_id = 全局 post 神经元 ID (base = block_row * br + rr)
  - 若 post 超出 rows 范围则写入 sentinel (默认 0xFFFFFFFF)
"""

import argparse
import json
import math
import os
import struct
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import random

SENTINEL_ID = 0xFFFFFFFF


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0:
        return value
    return ((value + alignment - 1) // alignment) * alignment


def choose_block_cols(row: int,
                      nbc: int,
                      pattern: str,
                      blocks_cfg: int,
                      seed: Optional[int] = None) -> List[int]:
    if nbc == 0:
        return []
    cols: List[int] = []
    if pattern == "fanout":
        target = max(0, min(blocks_cfg, nbc))
        if target == 0:
            cols = []
        elif target >= nbc:
            cols = list(range(nbc))
        else:
            rng = random.Random(seed if seed is not None else row)
            cols = rng.sample(range(nbc), target)
        cols.sort()
        return cols
    if blocks_cfg > 0:
        # 块列循环分布，覆盖整个列空间（确保 gcd(blocks_cfg, nbc)=1）
        for i in range(blocks_cfg):
            cols.append((row * blocks_cfg + i) % nbc)
    elif pattern == "full":
        cols = list(range(nbc))
    elif pattern == "diag":
        if row < nbc:
            cols = [row]
    cols = sorted(set(cols))
    return cols


def derive_blockscfg(fanout: int, bc: int, nbc: int) -> int:
    if fanout <= 0 or bc <= 0 or nbc == 0:
        return 0
    blocks = max(1, math.ceil(fanout / bc))
    # 确保 blocks 与 nbc 互质，提高列覆盖率
    while math.gcd(blocks, nbc) != 1 and blocks < nbc:
        blocks += 1
    return min(blocks, nbc)


def load_edges_map(edges_path: str,
                   cores: int,
                   rows_per_core: int,
                   cols: int) -> List[Dict[int, Set[int]]]:
    edges_per_core: List[Dict[int, Set[int]]] = [
        defaultdict(set) for _ in range(cores)
    ]
    if not edges_path:
        return edges_per_core
    with open(edges_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            src = int(parts[0])
            dst = int(parts[1])
            if src < 0 or dst < 0:
                continue
            core = dst // rows_per_core
            if core < 0 or core >= cores:
                continue
            post_local = dst - core * rows_per_core
            if post_local < 0 or post_local >= rows_per_core:
                continue
            if src >= cols:
                continue
            edges_per_core[core][post_local].add(src)
    return edges_per_core


def build_bcsr(rows: int,
               cols: int,
               br: int,
               bc: int,
               pattern: str,
               val: float,
               idx_bytes: int,
               fanout: int,
               row_base: int = 0,
               seed: Optional[int] = None,
               edges_map: Optional[Dict[int, Set[int]]] = None) -> Tuple[List[int], List[int], List[float], List[int]]:
    if rows <= 0 or cols <= 0:
        raise ValueError("rows/cols must be positive")
    if br <= 0 or bc <= 0:
        raise ValueError("br/bc must be positive")
    if idx_bytes not in (2, 4):
        raise ValueError("idx_bytes must be 2 or 4")

    n_block_rows = math.ceil(rows / br)
    n_block_cols = math.ceil(cols / bc)
    blocks_cfg = derive_blockscfg(fanout, bc, n_block_cols)
    if pattern == "full" or edges_map:
        blocks_cfg = 0

    rowptr: List[int] = [0] * (n_block_rows + 1)
    colidx: List[int] = []
    weights: List[float] = []
    dst_ids: List[int] = []

    acc_blocks = 0
    for br_idx in range(n_block_rows):
        rowptr[br_idx] = acc_blocks
        global_block_row = (row_base // br) + br_idx
        if edges_map is not None:
            block_cols: Set[int] = set()
            for rr in range(br):
                post = br_idx * br + rr
                if post >= rows:
                    break
                pre_set = edges_map.get(post)
                if not pre_set:
                    continue
                for pre in pre_set:
                    block_cols.add(pre // bc)
            cols_this_row = sorted(block_cols)
        else:
            cols_this_row = choose_block_cols(
                br_idx,
                n_block_cols,
                pattern,
                blocks_cfg,
                seed=None if seed is None else seed + global_block_row)
        acc_blocks += len(cols_this_row)
        for bc_idx in cols_this_row:
            if idx_bytes == 2 and bc_idx > 0xFFFF:
                raise ValueError("idx_bytes=2 不足以编码 block_col=%d, 请使用 --idx-bytes 4" % bc_idx)
            colidx.append(bc_idx)
            for rr in range(br):
                post = br_idx * br + rr
                for cc in range(bc):
                    global_col = bc_idx * bc + cc
                    if post >= rows or global_col >= cols:
                        weights.append(0.0)
                        dst_ids.append(SENTINEL_ID)
                    else:
                        if edges_map is not None:
                            pre_set = edges_map.get(post)
                            if pre_set and global_col in pre_set:
                                weights.append(val)
                                dst_ids.append(row_base + post)
                            else:
                                weights.append(0.0)
                                dst_ids.append(SENTINEL_ID)
                        else:
                            weights.append(val)
                            dst_ids.append(row_base + post)

    rowptr[n_block_rows] = acc_blocks
    return rowptr, colidx, weights, dst_ids


def pack_u32(values: List[int]) -> bytes:
    return struct.pack("<%dI" % len(values), *values)


def pack_u16(values: List[int]) -> bytes:
    return struct.pack("<%dH" % len(values), *values)


def pack_f32(values: List[float]) -> bytes:
    return struct.pack("<%df" % len(values), *values)


def write_core_file(path: str,
                    rows: int,
                    cols: int,
                    br: int,
                    bc: int,
                    pattern: str,
                    val: float,
                    idx_bytes: int,
                    val_bytes: int,
                    fanout: int,
                    align_bytes: int,
                    row_base: int,
                    seed: Optional[int],
                    edges_map: Optional[Dict[int, Set[int]]]) -> Tuple[int, int, int, int, int]:
    rowptr, colidx, weights, dst_ids = build_bcsr(
        rows, cols, br, bc, pattern, val, idx_bytes, fanout,
        row_base=row_base, seed=seed, edges_map=edges_map)
    if val_bytes != 4:
        raise ValueError("现阶段仅支持 float32 (val_bytes=4)")

    row_bytes = pack_u32(rowptr)
    if idx_bytes == 2:
        col_bytes = pack_u16(colidx)
    else:
        col_bytes = pack_u32(colidx)
    weight_bytes = pack_f32(weights)
    id_bytes = pack_u32(dst_ids)

    off_rowptr = 0
    off_colidx = align_up(len(row_bytes), align_bytes)
    off_weights = align_up(off_colidx + len(col_bytes), align_bytes)
    off_blockids = align_up(off_weights + len(weight_bytes), align_bytes)
    total_size = off_blockids + len(id_bytes)

    buf = bytearray(total_size)
    buf[off_rowptr:off_rowptr + len(row_bytes)] = row_bytes
    buf[off_colidx:off_colidx + len(col_bytes)] = col_bytes
    buf[off_weights:off_weights + len(weight_bytes)] = weight_bytes
    buf[off_blockids:off_blockids + len(id_bytes)] = id_bytes

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(buf)

    return (off_rowptr, off_colidx, off_weights, off_blockids, len(colidx))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--cols", type=int, required=True)
    ap.add_argument("--br", type=int, required=True, help="block rows")
    ap.add_argument("--bc", type=int, required=True, help="block cols")
    ap.add_argument("--cores", type=int, default=20)
    ap.add_argument("--pattern", choices=["diag", "full", "fanout"], default="diag")
    ap.add_argument("--fanout", type=int, default=0, help="approx fanout per neuron; 0=pattern controlled")
    ap.add_argument("--val", type=float, default=1.0, help="default weight value")
    ap.add_argument("--idx-bytes", type=int, choices=[2, 4], default=4)
    ap.add_argument("--val-bytes", type=int, default=4)
    ap.add_argument("--align", type=int, default=64)
    ap.add_argument("--seed", type=int, default=None, help="random seed for fanout pattern")
    ap.add_argument("--edges-file", type=str, default=None, help="optional src dst list to derive connectivity")
    ap.add_argument("--out", required=True, help="output template, supports {core} / {core:02d}")
    args = ap.parse_args()

    meta = {
        "rows": args.rows,
        "cols": args.cols,
        "br": args.br,
        "bc": args.bc,
        "idx_bytes": args.idx_bytes,
        "val_bytes": args.val_bytes,
        "cores": args.cores,
        "pattern": args.pattern,
        "fanout": args.fanout,
        "align": args.align,
        "seed": args.seed,
        "edges_file": args.edges_file,
        "files": [],
    }

    sample_offsets = None
    sample_blocks = None

    edges_per_core = None
    if args.edges_file:
        edges_per_core = load_edges_map(
            args.edges_file,
            args.cores,
            args.rows,
            args.cols)

    for core in range(args.cores):
        path = args.out.format(core=core)
        row_base = core * args.rows
        edge_map = None
        if edges_per_core is not None:
            edge_map = edges_per_core[core]
        offsets = write_core_file(
            path=path,
            rows=args.rows,
            cols=args.cols,
            br=args.br,
            bc=args.bc,
            pattern=args.pattern,
            val=args.val,
            idx_bytes=args.idx_bytes,
            val_bytes=args.val_bytes,
            fanout=args.fanout,
            align_bytes=args.align,
            row_base=row_base,
            seed=args.seed,
            edges_map=edge_map,
        )
        rp_off, ci_off, bd_off, ids_off, blocks = offsets
        meta["files"].append({
            "core": core,
            "path": path,
            "rowptr_offset": rp_off,
            "colidx_offset": ci_off,
            "blockdata_offset": bd_off,
            "blockids_offset": ids_off,
            "nnz_blocks": blocks,
        })
        sample_offsets = (rp_off, ci_off, bd_off, ids_off)
        sample_blocks = blocks
        print(f"[gen] core{core}: wrote {path}")

    rp_off, ci_off, bd_off, ids_off = sample_offsets
    print(f"[gen] offsets (bytes): rowptr={rp_off}, colidx={ci_off}, blockdata={bd_off}, blockids={ids_off}")
    print(f"[gen] nnz_blocks per core: {sample_blocks}")

    meta["offsets"] = {
        "rowptr_offset": rp_off,
        "colidx_offset": ci_off,
        "blockdata_offset": bd_off,
        "blockids_offset": ids_off,
    }
    meta["nnz_blocks_per_core"] = sample_blocks

    try:
        meta_path = args.out.format(core="meta") + ".json"
    except Exception:
        meta_path = args.out + ".meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[gen] meta written: {meta_path}")


if __name__ == "__main__":
    main()
