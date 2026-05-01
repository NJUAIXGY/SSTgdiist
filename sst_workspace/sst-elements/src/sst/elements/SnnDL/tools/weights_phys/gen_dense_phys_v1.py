#!/usr/bin/env python3
"""
Generate a dense weights "physical layout" blob (phys_v1) for SnnDL.

Design goals:
- Default SnnDL memory semantics: cacheline-sized traffic (e.g., 64B).
- Avoid row-stride misalignment (e.g., 2000B) by padding each logical row to cacheline.
- Pack multiple logical rows into one DRAM row (dram_row_bytes) to keep rowIndex/bankIndex stable.

Output:
- weights_phys.bin: raw bytes to be written to memory at base_addr via WeightLoader(raw).
- weights_phys.bin.meta.json: sidecar metadata for reproducibility/debug (not consumed by runtime).

Runtime enable (Core params):
- dense_layout_mode=phys_v1
- dense_phys_dram_row_bytes=<same as generator>
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os
import struct
from typing import List, Optional


def is_pow2(v: int) -> bool:
    return v > 0 and (v & (v - 1)) == 0


def align_up(v: int, a: int) -> int:
    if a <= 0:
        return v
    return (v + (a - 1)) & ~(a - 1)


def read_floats_bin(path: str) -> List[float]:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0, os.SEEK_SET)
        if size <= 0 or (size % 4) != 0:
            raise ValueError(f"bin file size must be a positive multiple of 4 bytes: size={size} path={path}")
        n = size // 4
        arrf = array.array("f")
        arrf.fromfile(f, n)
        return list(arrf)


def read_floats_csv(path: str) -> List[float]:
    out: List[float] = []
    with open(path, "r", encoding="utf-8") as f:
        for tok in f.read().replace(",", " ").split():
            try:
                out.append(float(tok))
            except Exception:
                continue
    if not out:
        raise ValueError(f"csv parsed 0 floats: path={path}")
    return out


def build_values(rows: int, cols: int, pattern: str, fill: float, row_scale: int, src: Optional[List[float]]) -> List[float]:
    total = rows * cols
    if src is not None:
        # Row-major expected; pad with fill if needed.
        if len(src) < total:
            src = src + [fill] * (total - len(src))
        return src[:total]
    if pattern == "dense_rowcol_v1":
        vals: List[float] = [0.0] * total
        for r in range(rows):
            base = float(r * row_scale)
            off = r * cols
            for c in range(cols):
                vals[off + c] = base + float(c)
        return vals
    # const
    return [fill] * total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--cols", type=int, required=True)
    ap.add_argument("--line-bytes", type=int, default=64)
    ap.add_argument("--dram-row-bytes", type=int, default=8192)
    ap.add_argument("--in", dest="in_path", type=str, default="")
    ap.add_argument("--in-format", type=str, default="bin", choices=["bin", "csv"])
    ap.add_argument("--pattern", type=str, default="const", choices=["const", "dense_rowcol_v1"])
    ap.add_argument("--fill", type=float, default=0.5)
    ap.add_argument("--row-scale", type=int, default=1024)
    ap.add_argument("--out", dest="out_path", type=str, required=True)
    ap.add_argument("--meta", dest="meta_path", type=str, default="")
    args = ap.parse_args()

    rows = int(args.rows)
    cols = int(args.cols)
    line_bytes = int(args.line_bytes)
    dram_row_bytes = int(args.dram_row_bytes)

    if rows <= 0 or cols <= 0:
        raise SystemExit("rows/cols must be positive")
    if line_bytes <= 0 or not is_pow2(line_bytes):
        raise SystemExit("line-bytes must be a positive power-of-two (e.g., 64)")
    if dram_row_bytes <= 0 or not is_pow2(dram_row_bytes):
        raise SystemExit("dram-row-bytes must be a positive power-of-two (e.g., 8192)")
    if dram_row_bytes < line_bytes:
        raise SystemExit("dram-row-bytes must be >= line-bytes")

    src: Optional[List[float]] = None
    if args.in_path:
        src = read_floats_bin(args.in_path) if args.in_format == "bin" else read_floats_csv(args.in_path)

    vals = build_values(rows, cols, args.pattern, float(args.fill), int(args.row_scale), src)

    bytes_per_weight = 4
    logical_row_bytes = cols * bytes_per_weight
    row_stride_bytes = align_up(logical_row_bytes, line_bytes)

    if row_stride_bytes <= 0:
        raise SystemExit("invalid derived row_stride_bytes")

    if row_stride_bytes <= dram_row_bytes:
        rows_per_dram_row = max(1, dram_row_bytes // row_stride_bytes)
        group_stride_bytes = dram_row_bytes
    else:
        rows_per_dram_row = 1
        group_stride_bytes = align_up(row_stride_bytes, dram_row_bytes)

    groups = (rows + rows_per_dram_row - 1) // rows_per_dram_row
    total_bytes = groups * group_stride_bytes

    out = bytearray(total_bytes)
    for r in range(rows):
        group = r // rows_per_dram_row
        within = r % rows_per_dram_row
        base_off = group * group_stride_bytes + within * row_stride_bytes
        row_off = r * cols
        for c in range(cols):
            off = base_off + c * bytes_per_weight
            out[off : off + 4] = struct.pack("<f", float(vals[row_off + c]))

    os.makedirs(os.path.dirname(os.path.abspath(args.out_path)) or ".", exist_ok=True)
    with open(args.out_path, "wb") as f:
        f.write(out)

    meta_path = args.meta_path or (args.out_path + ".meta.json")
    meta = {
        "format": "dense_weights_phys_v1",
        "rows": rows,
        "cols": cols,
        "bytes_per_weight": bytes_per_weight,
        "line_bytes": line_bytes,
        "dram_row_bytes": dram_row_bytes,
        "logical_row_bytes": logical_row_bytes,
        "row_stride_bytes": row_stride_bytes,
        "rows_per_dram_row": rows_per_dram_row,
        "group_stride_bytes": group_stride_bytes,
        "groups": groups,
        "total_bytes": total_bytes,
        "logical_bytes": rows * cols * bytes_per_weight,
        "overhead_bytes": total_bytes - (rows * cols * bytes_per_weight),
        "pattern": args.pattern,
        "fill": float(args.fill),
        "row_scale": int(args.row_scale),
        "input": {
            "path": args.in_path,
            "format": args.in_format,
            "provided": bool(args.in_path),
        },
        # Scheduler-friendly suggestions (documented in SnnDL plan):
        "suggest_apply_bank_shift": int(math.log2(dram_row_bytes)),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"wrote: {args.out_path} bytes={total_bytes}")
    print(f"wrote: {meta_path}")


if __name__ == "__main__":
    main()

