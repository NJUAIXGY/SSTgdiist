#!/usr/bin/env python3
"""Generate BCSR weights for multi-PE mesh with global neuron IDs.

Each Processing Element (PE) owns "neurons_per_pe" postsynaptic neurons but
columns (presynaptic IDs) span the full global space (num_pes * neurons_per_pe).

Connections:
  * Every post neuron has a fixed "fanout" outgoing synapses.
  * A configurable ratio of those synapses (local_ratio) targets neurons inside
    the same PE; the rest target other PEs uniformly.
  * Weights are written in packed BCSR format (rowptr / colidx / blockdata /
    blockids). blockids keep the destination post_global for the random
    activation reachability loader.

Usage example (quick sample of PE0/core0 only):
  python3 tools/gen_bcsr_global_mesh.py \
      --out-dir weights/bcsr_globalN1p6M \
      --only-pe 0 --cores-per-pe 1 --rows-per-core 64 \
      --sample-rows-per-core 64

Full generation (16 PEs, 20 cores each, 100k per PE):
  python3 tools/gen_bcsr_global_mesh.py \
      --out-dir weights/bcsr_globalN1p6M
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import struct
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

SENTINEL_ID = 0xFFFFFFFF


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0:
        return value
    return ((value + alignment - 1) // alignment) * alignment


def pick_presynaptic_set(
    rng: random.Random,
    total_neurons: int,
    local_start: int,
    neurons_per_pe: int,
    fanout: int,
    local_ratio: float,
) -> Set[int]:
    local_end = local_start + neurons_per_pe
    local_target = min(int(round(fanout * local_ratio)), fanout)
    local_target = min(local_target, neurons_per_pe)
    pres: Set[int] = set()
    if local_target >= neurons_per_pe:
        pres.update(range(local_start, local_end))
    elif local_target > 0:
        pres.update(rng.sample(range(local_start, local_end), local_target))

    while len(pres) < fanout:
        val = rng.randrange(total_neurons)
        if local_start <= val < local_end:
            continue
        pres.add(val)
    return pres


def build_edges_map_incoming(
    pe_id: int,
    core_id: int,
    rows_this_core: int,
    params: argparse.Namespace,
) -> Dict[int, Set[int]]:
    total_neurons = params.num_pes * params.neurons_per_pe
    local_start = pe_id * params.neurons_per_pe
    core_row_base = core_id * params.rows_per_core
    global_post_base = local_start + core_row_base
    edges: Dict[int, Set[int]] = {}
    rng_seed_base = params.seed ^ (pe_id << 32) ^ (core_id << 16)
    for row in range(rows_this_core):
        global_post = global_post_base + row
        rng = random.Random(rng_seed_base + global_post)
        pres = pick_presynaptic_set(
            rng=rng,
            total_neurons=total_neurons,
            local_start=local_start,
            neurons_per_pe=params.neurons_per_pe,
            fanout=params.fanout,
            local_ratio=params.local_ratio,
        )
        edges[row] = pres
    return edges


def build_edges_maps_outgoing(params: argparse.Namespace) -> Dict[Tuple[int, int], Dict[int, Set[int]]]:
    """构建基于“每个pre固定fanout”的全局出边，然后按 post 归并为每PE/core的入边集合。
    返回：{(pe, core) -> {post_local_row -> set(pre_global)}}"""
    total_neurons = params.num_pes * params.neurons_per_pe
    neurons_per_pe = params.neurons_per_pe
    rows_per_core = params.rows_per_core
    cores_per_pe = params.cores_per_pe
    # 初始化每 (pe,core) 的入边map
    maps: Dict[Tuple[int, int], Dict[int, Set[int]]] = {}
    for pe in range(params.num_pes):
        for core in range(cores_per_pe):
            maps[(pe, core)] = {}
    # 为每个 pre_global 选择 fanout 个 post_global（85%本地、15%跨PE均匀）
    for pre_global in range(total_neurons):
        pre_pe = pre_global // neurons_per_pe
        rng = random.Random(params.seed ^ (pre_global + 0x9e3779b97f4a7c15))
        # 本地 posts
        local_target = min(int(round(params.fanout * params.local_ratio)), params.fanout)
        local_target = min(local_target, neurons_per_pe)
        local_posts: Set[int] = set()
        local_start = pre_pe * neurons_per_pe
        local_end = local_start + neurons_per_pe
        if local_target >= neurons_per_pe:
            local_posts.update(range(local_start, local_end))
        elif local_target > 0:
            local_posts.update(rng.sample(range(local_start, local_end), local_target))
        # 跨PE posts
        remaining = params.fanout - len(local_posts)
        while remaining > 0:
            post = rng.randrange(total_neurons)
            if post >= local_start and post < local_end:
                continue
            if post in local_posts:
                continue
            local_posts.add(post)  # 复用集合，仅表示已选post集合
            remaining = params.fanout - len(local_posts)
        # 将选中的 posts 归并到各自 (pe, core) 的入边集合
        for post_global in local_posts:
            post_pe = post_global // neurons_per_pe
            post_in_pe = post_global - post_pe * neurons_per_pe
            post_core = post_in_pe // rows_per_core
            post_local_row = post_in_pe - post_core * rows_per_core
            m = maps[(post_pe, post_core)]
            s = m.get(post_local_row)
            if s is None:
                s = set()
                m[post_local_row] = s
            s.add(pre_global)
    return maps


def build_bcsr(
    edges_map: Dict[int, Set[int]],
    rows: int,
    cols: int,
    br: int,
    bc: int,
    idx_bytes: int,
    weight_value: float,
    global_post_base: int,
) -> Tuple[List[int], List[int], List[float], List[int]]:
    if idx_bytes not in (2, 4):
        raise ValueError("idx_bytes must be 2 or 4")
    n_block_rows = math.ceil(rows / br)
    rowptr = [0] * (n_block_rows + 1)
    colidx: List[int] = []
    weights: List[float] = []
    blockids: List[int] = []
    blocks_so_far = 0

    for br_idx in range(n_block_rows):
        rowptr[br_idx] = blocks_so_far
        block_cols: Set[int] = set()
        row_begin = br_idx * br
        for rr in range(br):
            row = row_begin + rr
            if row >= rows:
                continue
            pres = edges_map.get(row)
            if not pres:
                continue
            for pre in pres:
                block_cols.add(pre // bc)
        block_list = sorted(block_cols)
        blocks_so_far += len(block_list)
        for block_col in block_list:
            if idx_bytes == 2 and block_col > 0xFFFF:
                raise ValueError(
                    f"block_col {block_col} exceeds uint16 range; use --idx-bytes 4"
                )
            colidx.append(block_col)
            for rr in range(br):
                row = row_begin + rr
                post_global = global_post_base + row
                row_edges = edges_map.get(row)
                for cc in range(bc):
                    global_col = block_col * bc + cc
                    if (
                        row < rows
                        and global_col < cols
                        and row_edges
                        and global_col in row_edges
                    ):
                        weights.append(weight_value)
                        blockids.append(post_global)
                    else:
                        weights.append(0.0)
                        blockids.append(SENTINEL_ID)
    rowptr[n_block_rows] = blocks_so_far
    return rowptr, colidx, weights, blockids


def pack_u32(values: Sequence[int]) -> bytes:
    return struct.pack(f"<{len(values)}I", *values)


def pack_u16(values: Sequence[int]) -> bytes:
    return struct.pack(f"<{len(values)}H", *values)


def pack_f32(values: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def write_core_file(
    path: Path,
    rowptr: Sequence[int],
    colidx: Sequence[int],
    weights: Sequence[float],
    blockids: Sequence[int],
    idx_bytes: int,
    align: int,
    layout: str,
    br: int,
    bc: int,
    val_bytes: int,
) -> Dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    offsets: Dict[str, int] = {}
    layout_mode = (layout or "flat").strip().lower()
    offset = 0

    rowptr_bytes = pack_u32(rowptr)
    with path.open("wb") as f:
        offsets["rowptr_offset"] = offset
        f.write(rowptr_bytes)
        offset += len(rowptr_bytes)
        pad = (align_up(offset, align) - offset)
        if pad:
            f.write(b"\x00" * pad)
        offset = align_up(offset, align)

        if layout_mode == "rowpack_v1":
            n_block_rows = max(0, len(rowptr) - 1)
            max_blocks_per_row = 0
            for r in range(n_block_rows):
                cnt = int(rowptr[r + 1]) - int(rowptr[r])
                if cnt > max_blocks_per_row:
                    max_blocks_per_row = cnt
            block_bytes = int(br) * int(bc) * int(val_bytes)
            colidx_row_stride = align_up(max_blocks_per_row * idx_bytes, align)
            blockdata_row_stride = align_up(max_blocks_per_row * block_bytes, align)

            offsets["colidx_offset"] = offset
            for r in range(n_block_rows):
                start = int(rowptr[r])
                end = int(rowptr[r + 1])
                row_cols = colidx[start:end]
                if idx_bytes == 2:
                    row_bytes = pack_u16(row_cols) if row_cols else b""
                else:
                    row_bytes = pack_u32(row_cols) if row_cols else b""
                if len(row_bytes) > colidx_row_stride:
                    raise ValueError(f"rowpack_v1 colidx row overflow: row={r} bytes={len(row_bytes)} stride={colidx_row_stride}")
                f.write(row_bytes)
                if colidx_row_stride > len(row_bytes):
                    f.write(b"\x00" * (colidx_row_stride - len(row_bytes)))
            offset += n_block_rows * colidx_row_stride

            offsets["blockdata_offset"] = offset
            block_elem = int(br) * int(bc)
            for r in range(n_block_rows):
                start = int(rowptr[r])
                end = int(rowptr[r + 1])
                row_block_count = max(0, end - start)
                start_elem = start * block_elem
                end_elem = end * block_elem
                row_block_vals = weights[start_elem:end_elem]
                row_bytes = pack_f32(row_block_vals) if row_block_vals else b""
                if len(row_bytes) > blockdata_row_stride:
                    raise ValueError(
                        f"rowpack_v1 blockdata row overflow: row={r} bytes={len(row_bytes)} stride={blockdata_row_stride} blocks={row_block_count}"
                    )
                f.write(row_bytes)
                if blockdata_row_stride > len(row_bytes):
                    f.write(b"\x00" * (blockdata_row_stride - len(row_bytes)))
            offset += n_block_rows * blockdata_row_stride

            # Keep blockids in legacy flat layout for compatibility with route/reachability loaders.
            offsets["blockids_offset"] = offset
            blockids_bytes = pack_u32(blockids)
            f.write(blockids_bytes)
            offset += len(blockids_bytes)

            offsets["layout_mode"] = "rowpack_v1"
            offsets["colidx_row_stride_bytes"] = colidx_row_stride
            offsets["blockdata_row_stride_bytes"] = blockdata_row_stride
            offsets["blockids_row_stride_bytes"] = 0
        else:
            offsets["colidx_offset"] = offset
            if idx_bytes == 2:
                colidx_bytes = pack_u16(colidx)
            else:
                colidx_bytes = pack_u32(colidx)
            f.write(colidx_bytes)
            offset += len(colidx_bytes)
            pad = (align_up(offset, align) - offset)
            if pad:
                f.write(b"\x00" * pad)
            offset = align_up(offset, align)

            offsets["blockdata_offset"] = offset
            blockdata_bytes = pack_f32(weights)
            f.write(blockdata_bytes)
            offset += len(blockdata_bytes)
            pad = (align_up(offset, align) - offset)
            if pad:
                f.write(b"\x00" * pad)
            offset = align_up(offset, align)

            offsets["blockids_offset"] = offset
            blockids_bytes = pack_u32(blockids)
            f.write(blockids_bytes)
            offset += len(blockids_bytes)

            offsets["layout_mode"] = "flat"
            offsets["colidx_row_stride_bytes"] = 0
            offsets["blockdata_row_stride_bytes"] = 0
            offsets["blockids_row_stride_bytes"] = 0
    offsets["file_size"] = offset
    offsets["total_blocks"] = len(colidx)
    return offsets


def write_meta(meta_path: Path, meta: Dict[str, object]) -> None:
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def iter_target_pes(args: argparse.Namespace) -> Iterable[int]:
    if args.only_pe:
        return sorted(set(args.only_pe))
    return range(args.num_pes)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--num-pes", type=int, default=16)
    ap.add_argument("--neurons-per-pe", type=int, default=100_000)
    ap.add_argument("--cores-per-pe", type=int, default=20)
    ap.add_argument("--rows-per-core", type=int, default=5_000)
    ap.add_argument("--fanout", type=int, default=256)
    ap.add_argument("--local-ratio", type=float, default=0.85)
    ap.add_argument("--br", type=int, default=1)
    ap.add_argument("--bc", type=int, default=16)
    ap.add_argument("--idx-bytes", type=int, default=4)
    ap.add_argument("--val-bytes", type=int, default=4)
    ap.add_argument("--weights-cols", type=int, default=0,
                    help="总列数（默认=num_pes*neurons_per_pe）")
    ap.add_argument("--weight-value", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=271828)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--align", type=int, default=64)
    ap.add_argument("--layout", choices=["flat", "rowpack_v1"], default="flat",
                    help="BCSR data layout for colidx/blockdata/blockids regions")
    ap.add_argument("--mode", choices=["incoming", "outgoing"], default="outgoing",
                    help="incoming: 为每个post选择pres (入度=fanout); outgoing: 为每个pre选择posts (出度=fanout, 推荐)")
    ap.add_argument("--only-pe", type=int, action="append",
                    help="仅生成指定 pe_id，可重复指定")
    ap.add_argument("--sample-rows-per-core", type=int, default=0,
                    help="仅生成每 core 前 N 行用于快速验证")
    args = ap.parse_args()

    if args.weights_cols <= 0:
        args.weights_cols = args.num_pes * args.neurons_per_pe

    if args.rows_per_core * args.cores_per_pe < args.neurons_per_pe:
        raise ValueError("rows_per_core * cores_per_pe must cover neurons_per_pe")

    if args.val_bytes != 4:
        raise ValueError("val_bytes other than 4 not supported (float32 only)")

    out_root = Path(args.out_dir)
    print(f"[INFO] Generating BCSR weights under {out_root}")
    outgoing_maps = None
    if args.mode == "outgoing":
        print("[INFO] Mode=outgoing: fanout按pre定义，目标本地/跨PE比例=%.0f%%/%.0f%%" % (args.local_ratio*100, (1.0-args.local_ratio)*100))
        outgoing_maps = build_edges_maps_outgoing(args)
    for pe_id in iter_target_pes(args):
        if pe_id < 0 or pe_id >= args.num_pes:
            raise ValueError(f"pe_id {pe_id} out of range")
        print(f"[PE {pe_id:02d}] start")
        global_post_pe_base = pe_id * args.neurons_per_pe
        for core in range(args.cores_per_pe):
            core_rows = min(
                args.rows_per_core,
                args.neurons_per_pe - core * args.rows_per_core,
            )
            if core_rows <= 0:
                continue
            effective_rows = core_rows
            if args.sample_rows_per_core and args.sample_rows_per_core < core_rows:
                effective_rows = args.sample_rows_per_core
            if args.mode == "outgoing":
                edges = outgoing_maps[(pe_id, core)]
                if effective_rows < core_rows:
                    # 截断到采样行数
                    edges = {row: pres for row, pres in edges.items() if row < effective_rows}
            else:
                edges = build_edges_map_incoming(pe_id, core, effective_rows, args)
            global_post_base = global_post_pe_base + core * args.rows_per_core
            rowptr, colidx, weights, blockids = build_bcsr(
                edges_map=edges,
                rows=effective_rows,
                cols=args.weights_cols,
                br=args.br,
                bc=args.bc,
                idx_bytes=args.idx_bytes,
                weight_value=args.weight_value,
                global_post_base=global_post_base,
            )
            core_dir = out_root / f"pe{pe_id:02d}"
            core_name = f"core{core:02d}.bcsr.bin"
            file_path = core_dir / core_name
            offsets = write_core_file(
                file_path,
                rowptr,
                colidx,
                weights,
                blockids,
                idx_bytes=args.idx_bytes,
                align=args.align,
                layout=args.layout,
                br=args.br,
                bc=args.bc,
                val_bytes=args.val_bytes,
            )
            meta = {
                "pe": pe_id,
                "core": core,
                "rows": effective_rows,
                "cols": args.weights_cols,
                "br": args.br,
                "bc": args.bc,
                "idx_bytes": args.idx_bytes,
                "val_bytes": args.val_bytes,
                "fanout": args.fanout,
                "local_ratio": args.local_ratio,
                **offsets,
            }
            meta_path = core_dir / f"{core_name}.meta.json"
            write_meta(meta_path, meta)
            print(
                f"  [core {core:02d}] rows={effective_rows} blocks={offsets['total_blocks']}"
                f" size={offsets['file_size']/1024/1024:.2f} MiB"
            )
    print("[DONE] Generation finished")


if __name__ == "__main__":
    main()
