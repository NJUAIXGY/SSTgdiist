#!/usr/bin/env python3
"""
Generate GCSSIDX2 files (row-major values + row-MPHF index) from per-core BCSR files.

Input layout:
  <bcsr_dir>/peXX/coreYY.bcsr.bin
  <bcsr_dir>/peXX/coreYY.bcsr.bin.meta.json

Output layout:
  <out_dir>/peXX/coreYY.gcss2.bin
  <out_dir>/peXX/coreYY.gcss2.idx.bin
  <out_dir>/peXX/coreYY.gcss2.meta.json
  <out_dir>/manifest.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple


MAGIC = b"GCSSIDX2"
VERSION = 1
HASH_KIND = 1
PILOT_BITS = 8
FLAG_STRICT = 1


@dataclass(frozen=True)
class Edge:
    pre: int
    post: int
    weight: float


@dataclass(frozen=True)
class RowBuildResult:
    row_len: int
    seed: int
    bucket_count: int
    pilots: List[int]
    row_values: List[float]
    row_pres: List[int]


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


def _mix32(x: int) -> int:
    x &= 0xFFFFFFFF
    x ^= (x >> 16)
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= (x >> 15)
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    x ^= (x >> 16)
    return x & 0xFFFFFFFF


def _h1(key: int, seed: int) -> int:
    return _mix32((key & 0xFFFFFFFF) ^ _mix32(seed ^ 0xA24BAED5))


def _h2(key: int, seed: int) -> int:
    return _mix32((key & 0xFFFFFFFF) ^ _mix32(seed ^ 0x9FB21C65))


def _slot_pos(key: int, seed: int, pilot: int, row_len: int) -> int:
    # Pilot must alter the hash function itself (not only +pilot shift),
    # otherwise some collision patterns are unsatisfiable for all pilots.
    pilot_seed = (seed ^ (((int(pilot) + 1) * 0x9E3779B1) & 0xFFFFFFFF)) & 0xFFFFFFFF
    return int(_h2(int(key), pilot_seed) % int(row_len))


def _build_row_mphf(
    row_pairs: Sequence[Tuple[int, float]],
    *,
    bucket_target: int,
    seed_base: int,
    max_seed_tries: int,
) -> RowBuildResult:
    row_len = len(row_pairs)
    if row_len == 0:
        return RowBuildResult(
            row_len=0,
            seed=0,
            bucket_count=0,
            pilots=[],
            row_values=[],
            row_pres=[],
        )

    # Enforce unique (pre -> weight) per row.
    dedup: Dict[int, float] = {}
    for pre, w in row_pairs:
        if pre in dedup:
            old = float(dedup[pre])
            if abs(old - float(w)) > 1e-12:
                raise ValueError(
                    f"duplicate pre with mismatched weight in row: pre={pre} old={old} new={w}"
                )
            raise ValueError(f"duplicate pre in row: pre={pre}")
        dedup[int(pre)] = float(w)
    if len(dedup) != row_len:
        raise ValueError("row dedup size mismatch")

    keys = sorted(dedup.keys())
    key_to_weight = dedup
    row_len = len(keys)
    bucket_count = int(math.ceil(row_len / float(bucket_target)))
    bucket_count = max(1, bucket_count)

    for seed_add in range(max_seed_tries):
        seed = (seed_base + seed_add) & 0xFFFFFFFF
        buckets: List[List[int]] = [[] for _ in range(bucket_count)]
        for k in keys:
            b = _h1(k, seed) % bucket_count
            buckets[b].append(k)

        order = sorted(range(bucket_count), key=lambda i: (-len(buckets[i]), i))
        occupied = [-1] * row_len
        pilots = [0] * bucket_count
        ok_all = True

        for b in order:
            ks = buckets[b]
            if not ks:
                pilots[b] = 0
                continue

            found = False
            for p in range(256):
                local_pos: List[int] = []
                local_set = set()
                collision = False
                for k in ks:
                    pos = _slot_pos(k, seed, p, row_len)
                    if pos in local_set:
                        collision = True
                        break
                    if occupied[pos] != -1:
                        collision = True
                        break
                    local_set.add(pos)
                    local_pos.append(pos)
                if collision:
                    continue
                pilots[b] = p
                for idx, pos in enumerate(local_pos):
                    occupied[pos] = ks[idx]
                found = True
                break

            if not found:
                ok_all = False
                break

        if not ok_all:
            continue
        if any(v == -1 for v in occupied):
            raise ValueError("internal row-mphf build error: uncovered slot")

        row_values = [0.0] * row_len
        row_pres = [0] * row_len
        for pos, k in enumerate(occupied):
            row_pres[pos] = int(k)
            row_values[pos] = float(key_to_weight[k])

        return RowBuildResult(
            row_len=row_len,
            seed=seed,
            bucket_count=bucket_count,
            pilots=pilots,
            row_values=row_values,
            row_pres=row_pres,
        )

    raise ValueError(
        f"row-mphf seed search failed: row_len={row_len} bucket_target={bucket_target} max_seed_tries={max_seed_tries}"
    )


def _build_idx2_from_edges(
    edges: Sequence[Edge],
    *,
    rows_per_core: int,
    bucket_target: int,
    max_seed_tries: int,
) -> Dict[str, object]:
    if rows_per_core <= 0:
        raise ValueError(f"invalid rows_per_core={rows_per_core}")

    by_row: List[List[Tuple[int, float]]] = [[] for _ in range(rows_per_core)]
    for e in edges:
        if e.post < 0 or e.post >= rows_per_core:
            raise ValueError(f"post_local out of range: {e.post} rows={rows_per_core}")
        by_row[e.post].append((e.pre, e.weight))

    row_base: List[int] = [0] * (rows_per_core + 1)
    row_len: List[int] = [0] * rows_per_core
    row_seed: List[int] = [0] * rows_per_core
    row_bucket_count: List[int] = [0] * rows_per_core
    row_bucket_off: List[int] = [0] * (rows_per_core + 1)
    pilots_all: List[int] = []
    values_all: List[float] = []
    row_slot_pres: List[List[int]] = []
    row_slot_w: List[List[float]] = []

    values_cursor = 0
    pilots_cursor = 0
    seed_salt = 0x13579BDF
    for r in range(rows_per_core):
        row_pairs = by_row[r]
        built = _build_row_mphf(
            row_pairs,
            bucket_target=bucket_target,
            seed_base=((r * 0x9E3779B1) ^ seed_salt) & 0xFFFFFFFF,
            max_seed_tries=max_seed_tries,
        )

        l = built.row_len
        b = built.bucket_count
        if l > 0xFFFF:
            raise ValueError(f"row_len over uint16: row={r} len={l}")
        if b > 0xFFFF:
            raise ValueError(f"row_bucket_count over uint16: row={r} buckets={b}")

        row_base[r] = values_cursor
        row_len[r] = l
        row_seed[r] = int(built.seed)
        row_bucket_count[r] = b
        row_bucket_off[r] = pilots_cursor

        values_all.extend(built.row_values)
        row_slot_pres.append(list(built.row_pres))
        row_slot_w.append(list(built.row_values))
        values_cursor += l

        pilots_all.extend(int(p) for p in built.pilots)
        pilots_cursor += len(built.pilots)

    row_base[rows_per_core] = values_cursor
    row_bucket_off[rows_per_core] = pilots_cursor
    edges_total = values_cursor

    if edges_total != len(edges):
        raise ValueError(
            f"edges_total mismatch: built={edges_total} parsed={len(edges)}"
        )

    return {
        "row_base": row_base,
        "row_len": row_len,
        "row_seed": row_seed,
        "row_bucket_count": row_bucket_count,
        "row_bucket_off": row_bucket_off,
        "pilots": pilots_all,
        "values": values_all,
        "edges_total": edges_total,
        "row_slot_pres": row_slot_pres,
        "row_slot_w": row_slot_w,
        "bucket_target": int(bucket_target),
    }


def _write_values_bin(path: Path, values: Sequence[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        if values:
            f.write(struct.pack("<" + "f" * len(values), *values))


def _write_index_bin(path: Path, idx: Dict[str, object]) -> int:
    row_base = list(idx["row_base"])
    row_len = list(idx["row_len"])
    row_seed = list(idx["row_seed"])
    row_bucket_count = list(idx["row_bucket_count"])
    row_bucket_off = list(idx["row_bucket_off"])
    pilots = list(idx["pilots"])
    edges_total = int(idx["edges_total"])
    bucket_target = int(idx["bucket_target"])

    rows_per_core = len(row_len)
    if len(row_base) != rows_per_core + 1:
        raise ValueError("row_base length mismatch")
    if len(row_seed) != rows_per_core:
        raise ValueError("row_seed length mismatch")
    if len(row_bucket_count) != rows_per_core:
        raise ValueError("row_bucket_count length mismatch")
    if len(row_bucket_off) != rows_per_core + 1:
        raise ValueError("row_bucket_off length mismatch")
    if row_base[-1] != edges_total:
        raise ValueError("row_base tail != edges_total")
    if row_bucket_off[-1] != len(pilots):
        raise ValueError("row_bucket_off tail != pilots length")

    header = struct.pack(
        "<8sIIIIIII",
        MAGIC,
        VERSION,
        rows_per_core,
        edges_total,
        bucket_target,
        PILOT_BITS,
        HASH_KIND,
        FLAG_STRICT,
    )

    with path.open("wb") as f:
        f.write(header)
        if row_base:
            f.write(struct.pack("<" + "I" * len(row_base), *row_base))
        if row_len:
            f.write(struct.pack("<" + "H" * len(row_len), *row_len))
        if row_seed:
            f.write(struct.pack("<" + "I" * len(row_seed), *row_seed))
        if row_bucket_count:
            f.write(struct.pack("<" + "H" * len(row_bucket_count), *row_bucket_count))
        if row_bucket_off:
            f.write(struct.pack("<" + "I" * len(row_bucket_off), *row_bucket_off))
        if pilots:
            f.write(struct.pack("<" + "B" * len(pilots), *pilots))

    return path.stat().st_size


def _lookup_pos_no_membership(
    *,
    pre: int,
    row: int,
    row_len: Sequence[int],
    row_seed: Sequence[int],
    row_bucket_count: Sequence[int],
    row_bucket_off: Sequence[int],
    pilots: Sequence[int],
) -> int:
    l = int(row_len[row])
    if l <= 0:
        raise ValueError(f"invalid lookup on empty row={row}")
    bcount = int(row_bucket_count[row])
    if bcount <= 0:
        raise ValueError(f"invalid bucket_count on row={row}")
    seed = int(row_seed[row]) & 0xFFFFFFFF
    b = _h1(int(pre), seed) % bcount
    pidx = int(row_bucket_off[row]) + b
    if pidx < 0 or pidx >= len(pilots):
        raise ValueError(f"pilot index oob row={row} pidx={pidx}")
    pilot = int(pilots[pidx]) & 0xFF
    pos = _slot_pos(int(pre), seed, pilot, l)
    return int(pos)


def _self_check_idx2(
    *,
    idx: Dict[str, object],
    rows_per_core: int,
    row_source_pairs: Sequence[Sequence[Tuple[int, float]]],
    core_tag: str,
) -> None:
    row_base = list(idx["row_base"])
    row_len = list(idx["row_len"])
    row_seed = list(idx["row_seed"])
    row_bucket_count = list(idx["row_bucket_count"])
    row_bucket_off = list(idx["row_bucket_off"])
    pilots = list(idx["pilots"])
    values = list(idx["values"])

    if len(row_source_pairs) != rows_per_core:
        raise ValueError(f"[{core_tag}] self-check row count mismatch")

    # Occupancy check (exactly row_len unique slots filled by source keys).
    for r in range(rows_per_core):
        src = list(row_source_pairs[r])
        l = int(row_len[r])
        if l != len(src):
            raise ValueError(f"[{core_tag}] row_len mismatch row={r} idx={l} src={len(src)}")
        if l == 0:
            continue
        seen = set()
        for pre, w in src:
            pos = _lookup_pos_no_membership(
                pre=pre,
                row=r,
                row_len=row_len,
                row_seed=row_seed,
                row_bucket_count=row_bucket_count,
                row_bucket_off=row_bucket_off,
                pilots=pilots,
            )
            if pos in seen:
                raise ValueError(f"[{core_tag}] collision row={r} pos={pos} pre={pre}")
            seen.add(pos)
            global_idx = int(row_base[r]) + pos
            if global_idx < 0 or global_idx >= len(values):
                raise ValueError(f"[{core_tag}] value index oob row={r} idx={global_idx}")
            got = float(values[global_idx])
            if abs(got - float(w)) > 1e-8:
                raise ValueError(
                    f"[{core_tag}] value mismatch row={r} pre={pre} pos={pos} got={got} expect={w}"
                )
        if len(seen) != l:
            raise ValueError(f"[{core_tag}] occupancy mismatch row={r} seen={len(seen)} len={l}")


def _write_meta_json(
    path: Path,
    *,
    pe: int,
    core: int,
    epsilon: float,
    shape: Dict[str, int],
    idx: Dict[str, object],
    idx_bytes: int,
) -> None:
    edges_total = int(idx["edges_total"])
    values_bytes = int(edges_total * 4)
    ratio = float(idx_bytes) / float(values_bytes) if values_bytes > 0 else 0.0
    bits_per_edge = float(idx_bytes * 8.0 / edges_total) if edges_total > 0 else 0.0

    obj = {
        "schema_version": 1,
        "format": "gcss_valueonly_dstcore_idx2_rowmphf_v1",
        "magic": "GCSSIDX2",
        "version": VERSION,
        "pe": pe,
        "core": core,
        "epsilon": float(epsilon),
        "rows": int(shape["rows"]),
        "cols": int(shape["cols"]),
        "br": int(shape["br"]),
        "bc": int(shape["bc"]),
        "edges_total": edges_total,
        "bucket_target": int(idx["bucket_target"]),
        "pilot_bits": PILOT_BITS,
        "hash_kind": HASH_KIND,
        "flags": FLAG_STRICT,
        "values_bytes": values_bytes,
        "index_bytes": int(idx_bytes),
        "index_to_values_ratio": float(ratio),
        "index_bits_per_edge": float(bits_per_edge),
    }
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_manifest(
    path: Path,
    *,
    bcsr_dir: Path,
    out_dir: Path,
    epsilon: float,
    bucket_target: int,
    max_seed_tries: int,
    total_cores: int,
    total_edges: int,
    values_total_bytes: int,
    index_total_bytes: int,
) -> None:
    ratio = float(index_total_bytes) / float(values_total_bytes) if values_total_bytes > 0 else 0.0
    bits_per_edge = float(index_total_bytes * 8.0 / total_edges) if total_edges > 0 else 0.0
    obj = {
        "schema_version": 1,
        "format": "gcss_valueonly_dstcore_idx2_rowmphf_v1",
        "bcsr_dir": str(bcsr_dir),
        "out_dir": str(out_dir),
        "epsilon": float(epsilon),
        "bucket_target": int(bucket_target),
        "pilot_bits": PILOT_BITS,
        "hash_kind": HASH_KIND,
        "max_seed_tries": int(max_seed_tries),
        "total_cores": int(total_cores),
        "total_edges": int(total_edges),
        "values_total_bytes": int(values_total_bytes),
        "index_total_bytes": int(index_total_bytes),
        "index_to_values_ratio": float(ratio),
        "index_bits_per_edge": float(bits_per_edge),
    }
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _process_core(task: Tuple[str, str, float, int, int, bool]) -> Dict[str, object]:
    core_file_s, out_dir_s, epsilon, bucket_target, max_seed_tries, self_check = task
    p = Path(core_file_s)
    out_dir = Path(out_dir_s)
    pe, core = _parse_core_id(p)
    edges, shape = _parse_bcsr_edges(p, epsilon=float(epsilon))
    rows = int(shape["rows"])
    idx = _build_idx2_from_edges(
        edges,
        rows_per_core=rows,
        bucket_target=int(bucket_target),
        max_seed_tries=int(max_seed_tries),
    )

    if bool(self_check):
        row_src: List[List[Tuple[int, float]]] = [[] for _ in range(rows)]
        for e in edges:
            row_src[e.post].append((e.pre, e.weight))
        _self_check_idx2(
            idx=idx,
            rows_per_core=rows,
            row_source_pairs=row_src,
            core_tag=f"pe{pe:02d}/core{core:02d}",
        )

    pe_dir = out_dir / f"pe{pe:02d}"
    values_path = pe_dir / f"core{core:02d}.gcss2.bin"
    idx_path = pe_dir / f"core{core:02d}.gcss2.idx.bin"
    meta_path = pe_dir / f"core{core:02d}.gcss2.meta.json"

    _write_values_bin(values_path, list(idx["values"]))
    idx_bytes = _write_index_bin(idx_path, idx)
    _write_meta_json(
        meta_path,
        pe=pe,
        core=core,
        epsilon=float(epsilon),
        shape=shape,
        idx=idx,
        idx_bytes=idx_bytes,
    )

    edges_total = int(idx["edges_total"])
    values_bytes = int(edges_total * 4)
    ratio = (float(idx_bytes) / float(values_bytes)) if values_bytes > 0 else 0.0
    bits_per_edge = (float(idx_bytes * 8.0 / edges_total)) if edges_total > 0 else 0.0
    log_line = (
        f"[gcss2-gen] pe={pe:02d} core={core:02d} "
        f"edges={edges_total} values_bytes={values_bytes} idx_bytes={idx_bytes} "
        f"ratio={ratio:.6f} bits_per_edge={bits_per_edge:.4f}"
    )
    return {
        "pe": pe,
        "core": core,
        "edges_total": edges_total,
        "values_bytes": values_bytes,
        "idx_bytes": idx_bytes,
        "ratio": ratio,
        "bits_per_edge": bits_per_edge,
        "log_line": log_line,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bcsr-dir", required=True, help="input BCSR directory, e.g. weights/bcsr_global_16pe_fanout256_10k")
    ap.add_argument("--out-dir", required=True, help="output directory for GCSSIDX2 files")
    ap.add_argument("--epsilon", type=float, default=1e-8, help="abs(weight)<=epsilon is treated as zero edge")
    ap.add_argument("--bucket-target", type=int, default=3, help="target bucket size for row-mphf")
    ap.add_argument("--max-seed-tries", type=int, default=4096, help="max per-row seed retries")
    ap.add_argument("--jobs", type=int, default=1, help="number of worker processes (per-core parallel)")
    ap.add_argument("--self-check", action="store_true", help="run strict row-mphf/values consistency checks")
    args = ap.parse_args()

    bcsr_dir = Path(args.bcsr_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not bcsr_dir.is_dir():
        raise SystemExit(f"[gcss2-gen] bcsr_dir not found: {bcsr_dir}")
    if args.bucket_target <= 0:
        raise SystemExit(f"[gcss2-gen] invalid --bucket-target={args.bucket_target}, expected >0")
    if args.max_seed_tries <= 0:
        raise SystemExit(f"[gcss2-gen] invalid --max-seed-tries={args.max_seed_tries}, expected >0")
    if args.jobs <= 0:
        raise SystemExit(f"[gcss2-gen] invalid --jobs={args.jobs}, expected >0")

    core_files = list(_iter_core_bcsr_files(bcsr_dir))
    if not core_files:
        raise SystemExit(f"[gcss2-gen] no core*.bcsr.bin found under: {bcsr_dir}")

    total_edges = 0
    total_values_bytes = 0
    total_index_bytes = 0

    jobs = int(args.jobs)
    tasks: List[Tuple[str, str, float, int, int, bool]] = []
    for p in core_files:
        tasks.append(
            (
                str(p),
                str(out_dir),
                float(args.epsilon),
                int(args.bucket_target),
                int(args.max_seed_tries),
                bool(args.self_check),
            )
        )

    results: List[Dict[str, object]] = []
    if jobs == 1:
        for t in tasks:
            r = _process_core(t)
            results.append(r)
            print(str(r["log_line"]))
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as ex:
            futs = [ex.submit(_process_core, t) for t in tasks]
            for fut in concurrent.futures.as_completed(futs):
                r = fut.result()
                results.append(r)
                print(str(r["log_line"]))

    results.sort(key=lambda x: (int(x["pe"]), int(x["core"])))
    for r in results:
        total_edges += int(r["edges_total"])
        total_values_bytes += int(r["values_bytes"])
        total_index_bytes += int(r["idx_bytes"])

    _write_manifest(
        out_dir / "manifest.json",
        bcsr_dir=bcsr_dir,
        out_dir=out_dir,
        epsilon=float(args.epsilon),
        bucket_target=int(args.bucket_target),
        max_seed_tries=int(args.max_seed_tries),
        total_cores=len(core_files),
        total_edges=total_edges,
        values_total_bytes=total_values_bytes,
        index_total_bytes=total_index_bytes,
    )

    ratio = (float(total_index_bytes) / float(total_values_bytes)) if total_values_bytes > 0 else 0.0
    bits_per_edge = (float(total_index_bytes * 8.0 / total_edges)) if total_edges > 0 else 0.0
    print(
        f"[gcss2-gen] done: cores={len(core_files)} total_edges={total_edges} "
        f"values_total_bytes={total_values_bytes} index_total_bytes={total_index_bytes} "
        f"ratio={ratio:.6f} bits_per_edge={bits_per_edge:.4f} out_dir={out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
