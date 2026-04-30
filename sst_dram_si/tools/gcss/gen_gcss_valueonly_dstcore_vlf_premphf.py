#!/usr/bin/env python3
"""
Generate GCSS-VLF pre-MPHF files from per-core BCSR files.

Input layout:
  <bcsr_dir>/peXX/coreYY.bcsr.bin
  <bcsr_dir>/peXX/coreYY.bcsr.bin.meta.json

Output layout:
  <out_dir>/peXX/coreYY.gcssvlf.bin
  <out_dir>/peXX/coreYY.gcssvlf.idx.bin
  <out_dir>/peXX/coreYY.gcssvlf.meta.json
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
from typing import Sequence
from typing import Tuple


MAGIC = b"GCSSVLFP"
VERSION_V1 = 1
VERSION_V2 = 2
VERSION_V3 = 3
HASH_KIND = 1
PILOT_BITS = 16
FLAG_STRICT = 1
EF_SELECT_STEP_DEFAULT = 256


@dataclass(frozen=True)
class Edge:
    pre: int
    post: int
    weight: float


@dataclass(frozen=True)
class BuildResult:
    seed: int
    bucket_count: int
    pre_count: int
    edges_total: int
    slot_base: List[int]
    slot_len: List[int]
    pilots: List[int]
    values: List[float]
    slot_rank: List[int]


@dataclass(frozen=True)
class EfEncoded:
    l: int
    low_words: List[int]
    high_words: List[int]
    select_step: int
    select_hints: List[int]


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


def _slot_pos(key: int, seed: int, pilot: int, nslots: int) -> int:
    if nslots <= 0:
        return 0
    pilot_seed = (seed ^ (((int(pilot) + 1) * 0x9E3779B1) & 0xFFFFFFFF)) & 0xFFFFFFFF
    return int(_h2(int(key), pilot_seed) % int(nslots))


def _build_premphf(
    edges: Sequence[Edge],
    *,
    bucket_target: int,
    max_seed_tries: int,
) -> Tuple[BuildResult, Dict[int, List[Tuple[int, float]]], List[int], List[int]]:
    by_pre: Dict[int, List[Tuple[int, float]]] = {}
    for e in edges:
        by_pre.setdefault(int(e.pre), []).append((int(e.post), float(e.weight)))

    pre_to_pairs: Dict[int, List[Tuple[int, float]]] = {}
    keys = sorted(by_pre.keys())
    for pre in keys:
        pairs = by_pre[pre]
        pairs.sort(key=lambda x: x[0])
        dedup_pairs: List[Tuple[int, float]] = []
        last_post = None
        for post, w in pairs:
            if last_post is not None and post == last_post:
                prev_w = dedup_pairs[-1][1]
                if abs(prev_w - w) > 1e-12:
                    raise ValueError(
                        f"duplicate (pre,post) with mismatched weight pre={pre} post={post} old={prev_w} new={w}"
                    )
                continue
            dedup_pairs.append((post, w))
            last_post = post
        pre_to_pairs[pre] = dedup_pairs

    n = len(keys)
    if n == 0:
        result = BuildResult(
            seed=0,
            bucket_count=0,
            pre_count=0,
            edges_total=0,
            slot_base=[],
            slot_len=[],
            pilots=[],
            values=[],
            slot_rank=[],
        )
        return result, pre_to_pairs, [], []

    if bucket_target <= 0:
        raise ValueError(f"invalid bucket_target={bucket_target}")
    bucket_count = max(1, int(math.ceil(n / float(bucket_target))))

    slot_keys: List[int] = []
    pilots: List[int] = []
    seed_found = -1
    seed_salt = 0x13579BDF

    for seed_try in range(max_seed_tries):
        seed = (seed_salt + seed_try) & 0xFFFFFFFF
        buckets: List[List[int]] = [[] for _ in range(bucket_count)]
        for k in keys:
            b = _h1(k, seed) % bucket_count
            buckets[b].append(k)

        order = sorted(range(bucket_count), key=lambda i: (-len(buckets[i]), i))
        occupied = [-1] * n
        pilots_try = [0] * bucket_count
        ok_all = True

        for b in order:
            ks = buckets[b]
            if not ks:
                pilots_try[b] = 0
                continue

            found = False
            for p in range(1 << PILOT_BITS):
                local_pos: List[int] = []
                local_set = set()
                collision = False
                for k in ks:
                    pos = _slot_pos(k, seed, p, n)
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
                pilots_try[b] = p
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
            raise ValueError("internal premphf build error: uncovered slot")

        slot_keys = [int(v) for v in occupied]
        pilots = [int(p) for p in pilots_try]
        seed_found = int(seed)
        break

    if seed_found < 0:
        raise ValueError(
            f"premphf seed search failed: pre_count={n} bucket_target={bucket_target} max_seed_tries={max_seed_tries}"
        )

    slot_base: List[int] = [0] * n
    slot_len: List[int] = [0] * n
    values: List[float] = []
    for slot, pre in enumerate(slot_keys):
        seq = pre_to_pairs.get(int(pre), [])
        slot_base[slot] = len(values)
        slot_len[slot] = len(seq)
        for _, w in seq:
            values.append(float(w))

    edges_total = len(values)
    result = BuildResult(
        seed=seed_found,
        bucket_count=bucket_count,
        pre_count=n,
        edges_total=edges_total,
        slot_base=slot_base,
        slot_len=slot_len,
        pilots=pilots,
        values=values,
        slot_rank=[int(i) for i in range(n)],
    )
    return result, pre_to_pairs, keys, slot_keys


def _self_check(
    *,
    result: BuildResult,
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    keys: Sequence[int],
    slot_keys: Sequence[int],
    core_tag: str,
) -> None:
    if result.pre_count == 0:
        return

    if len(slot_keys) != result.pre_count:
        raise ValueError(f"[{core_tag}] slot_keys size mismatch")
    if len(result.slot_base) != result.pre_count:
        raise ValueError(f"[{core_tag}] slot_base size mismatch")
    if len(result.slot_len) != result.pre_count:
        raise ValueError(f"[{core_tag}] slot_len size mismatch")
    if len(result.pilots) != result.bucket_count:
        raise ValueError(f"[{core_tag}] pilots size mismatch")
    if result.slot_rank and len(result.slot_rank) != result.pre_count:
        raise ValueError(f"[{core_tag}] slot_rank size mismatch")
    if result.slot_rank:
        seen_ranks = set()
        for slot, rank in enumerate(result.slot_rank):
            r = int(rank)
            if r < 0 or r >= result.pre_count:
                raise ValueError(f"[{core_tag}] slot_rank oob slot={slot} rank={r}")
            if r in seen_ranks:
                raise ValueError(f"[{core_tag}] duplicate slot_rank={r}")
            seen_ranks.add(r)
        if len(seen_ranks) != result.pre_count:
            raise ValueError(f"[{core_tag}] slot_rank coverage mismatch")

    seen_slots = set()
    for pre in keys:
        b = _h1(int(pre), int(result.seed)) % int(result.bucket_count)
        if PILOT_BITS <= 8:
            pilot = int(result.pilots[b]) & 0xFF
        else:
            pilot = int(result.pilots[b]) & 0xFFFF
        slot = _slot_pos(int(pre), int(result.seed), pilot, int(result.pre_count))
        if slot in seen_slots:
            raise ValueError(f"[{core_tag}] duplicate slot for known keys: pre={pre} slot={slot}")
        seen_slots.add(slot)
        slot_pre = int(slot_keys[slot])
        if slot_pre != int(pre):
            raise ValueError(
                f"[{core_tag}] known-key lookup mismatch: pre={pre} slot={slot} slot_pre={slot_pre}"
            )

        base = int(result.slot_base[slot])
        ln = int(result.slot_len[slot])
        exp_pairs = pre_to_pairs.get(int(pre), [])
        if ln != len(exp_pairs):
            raise ValueError(
                f"[{core_tag}] len mismatch pre={pre} got={ln} expect={len(exp_pairs)}"
            )
        if base < 0 or base + ln > len(result.values):
            raise ValueError(f"[{core_tag}] base/len oob pre={pre} base={base} len={ln}")
        for r, (_, w) in enumerate(exp_pairs):
            got = float(result.values[base + r])
            if abs(got - float(w)) > 1e-8:
                raise ValueError(
                    f"[{core_tag}] value mismatch pre={pre} rank={r} got={got} expect={w}"
                )

    if len(seen_slots) != result.pre_count:
        raise ValueError(f"[{core_tag}] known-key coverage mismatch")


def _pack_value_bits(words: List[int], bit_offset: int, bit_width: int, value: int) -> None:
    if bit_width <= 0:
        return
    mask = (1 << bit_width) - 1
    v = int(value) & mask
    w = bit_offset >> 6
    s = bit_offset & 63
    words[w] = (words[w] | ((v << s) & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
    spill = (s + bit_width) - 64
    if spill > 0:
        if w + 1 >= len(words):
            raise ValueError("internal pack_value_bits overflow")
        words[w + 1] = (words[w + 1] | (v >> (bit_width - spill))) & 0xFFFFFFFFFFFFFFFF


def _rank_bits_for_count(pre_count: int) -> int:
    n = int(pre_count)
    if n <= 1:
        return 1
    return int((n - 1).bit_length())


def _build_rank_words(slot_rank: Sequence[int], pre_count: int) -> Tuple[int, List[int]]:
    n = int(pre_count)
    if len(slot_rank) != n:
        raise ValueError(f"slot_rank size mismatch: got={len(slot_rank)} pre_count={n}")
    rank_bits = _rank_bits_for_count(n)
    total_bits = n * rank_bits
    words: List[int] = [0] * ((total_bits + 63) // 64)
    for i, rank in enumerate(slot_rank):
        r = int(rank)
        if r < 0 or r >= n:
            raise ValueError(f"slot_rank out of range at slot={i}: rank={r} pre_count={n}")
        _pack_value_bits(words, i * rank_bits, rank_bits, r)
    return int(rank_bits), words


def _build_physical_base_by_rank(result: BuildResult) -> List[int]:
    n = int(result.pre_count)
    slot_rank = list(int(v) for v in result.slot_rank) if result.slot_rank else [int(i) for i in range(n)]
    if len(slot_rank) != n:
        raise ValueError(f"slot_rank size mismatch: got={len(slot_rank)} pre_count={n}")
    base_by_rank: List[int] = [0] * n
    seen = [False] * n
    for slot in range(n):
        rank = int(slot_rank[slot])
        if rank < 0 or rank >= n:
            raise ValueError(f"slot_rank out of range at slot={slot}: rank={rank} pre_count={n}")
        if seen[rank]:
            raise ValueError(f"duplicate rank in slot_rank: rank={rank}")
        seen[rank] = True
        base_by_rank[rank] = int(result.slot_base[slot])
    if n > 0 and not all(seen):
        raise ValueError("slot_rank missing rank entries")
    return base_by_rank


def _build_ef_from_slot_base(slot_base: Sequence[int], edges_total: int, select_step: int) -> EfEncoded:
    n = int(len(slot_base)) + 1
    if n <= 0:
        raise ValueError("invalid EF base length")
    if select_step <= 0:
        raise ValueError(f"invalid ef_select_step={select_step}")

    bases: List[int] = [int(v) for v in slot_base] + [int(edges_total)]
    for i, b in enumerate(bases):
        if b < 0:
            raise ValueError(f"negative base value at i={i}: {b}")
        if i > 0 and b < bases[i - 1]:
            raise ValueError(f"non-monotonic base sequence at i={i}: prev={bases[i-1]} now={b}")
    if bases[-1] != int(edges_total):
        raise ValueError(
            f"EF base terminal mismatch: last={bases[-1]} edges_total={int(edges_total)}"
        )

    U = int(edges_total)
    l = 0
    if U > 0 and n > 0:
        q = U // n
        if q > 0:
            l = int(q.bit_length() - 1)
    if l < 0:
        l = 0
    if l > 31:
        l = 31

    low_bits_total = n * l
    low_words_n = (low_bits_total + 63) // 64
    low_words: List[int] = [0] * low_words_n
    low_mask = (1 << l) - 1 if l > 0 else 0
    if l > 0:
        for i, b in enumerate(bases):
            low = int(b) & low_mask
            _pack_value_bits(low_words, i * l, l, low)

    high_bits_len = (U >> l) + n
    if high_bits_len <= 0:
        high_bits_len = n
    high_words_n = (high_bits_len + 63) // 64
    high_words: List[int] = [0] * high_words_n
    high_positions: List[int] = []
    for i, b in enumerate(bases):
        hi = int(b) >> l
        pos = hi + i
        if pos < 0 or pos >= high_bits_len:
            raise ValueError(
                f"EF high position out of range: i={i} base={b} l={l} pos={pos} high_bits_len={high_bits_len}"
            )
        high_positions.append(pos)
        w = pos >> 6
        s = pos & 63
        high_words[w] = (high_words[w] | (1 << s)) & 0xFFFFFFFFFFFFFFFF

    select_hints: List[int] = []
    for i in range(0, n, select_step):
        select_hints.append(int(high_positions[i]))
    if not select_hints:
        select_hints = [0]

    return EfEncoded(
        l=int(l),
        low_words=low_words,
        high_words=high_words,
        select_step=int(select_step),
        select_hints=select_hints,
    )


def _write_values_bin(path: Path, values: Sequence[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        if values:
            f.write(struct.pack("<" + "f" * len(values), *values))


def _write_index_bin(
    path: Path,
    result: BuildResult,
    bucket_target: int,
    *,
    index_version: int,
    ef_select_step: int,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("wb") as f:
        if int(index_version) == VERSION_V1:
            header = struct.pack(
                "<8sIIIIIIIII",
                MAGIC,
                VERSION_V1,
                int(result.pre_count),
                int(result.edges_total),
                int(bucket_target),
                PILOT_BITS,
                HASH_KIND,
                FLAG_STRICT,
                int(result.seed),
                int(result.bucket_count),
            )
            f.write(header)
            if result.slot_base:
                f.write(struct.pack("<" + "I" * len(result.slot_base), *result.slot_base))
            if result.slot_len:
                f.write(struct.pack("<" + "I" * len(result.slot_len), *result.slot_len))
        elif int(index_version) == VERSION_V2:
            ef = _build_ef_from_slot_base(
                result.slot_base, int(result.edges_total), int(ef_select_step)
            )
            header = struct.pack(
                "<8sIIIIIIIIIIIIII",
                MAGIC,
                VERSION_V2,
                int(result.pre_count),
                int(result.edges_total),
                int(bucket_target),
                PILOT_BITS,
                HASH_KIND,
                FLAG_STRICT,
                int(result.seed),
                int(result.bucket_count),
                int(ef.l),
                int(len(ef.low_words)),
                int(len(ef.high_words)),
                int(ef.select_step),
                int(len(ef.select_hints)),
            )
            f.write(header)
            if ef.low_words:
                f.write(struct.pack("<" + "Q" * len(ef.low_words), *ef.low_words))
            if ef.high_words:
                f.write(struct.pack("<" + "Q" * len(ef.high_words), *ef.high_words))
            if ef.select_hints:
                f.write(struct.pack("<" + "I" * len(ef.select_hints), *ef.select_hints))
        elif int(index_version) == VERSION_V3:
            base_by_rank = _build_physical_base_by_rank(result)
            ef = _build_ef_from_slot_base(base_by_rank, int(result.edges_total), int(ef_select_step))
            rank_bits, rank_words = _build_rank_words(
                result.slot_rank if result.slot_rank else [int(i) for i in range(int(result.pre_count))],
                int(result.pre_count),
            )
            header = struct.pack(
                "<8sIIIIIIIII",
                MAGIC,
                VERSION_V3,
                int(result.pre_count),
                int(result.edges_total),
                int(bucket_target),
                PILOT_BITS,
                HASH_KIND,
                FLAG_STRICT,
                int(result.seed),
                int(result.bucket_count),
            )
            extra = struct.pack(
                "<IIIIIII",
                int(rank_bits),
                int(len(rank_words)),
                int(ef.l),
                int(len(ef.low_words)),
                int(len(ef.high_words)),
                int(ef.select_step),
                int(len(ef.select_hints)),
            )
            f.write(header)
            f.write(extra)
            if rank_words:
                f.write(struct.pack("<" + "Q" * len(rank_words), *rank_words))
            if ef.low_words:
                f.write(struct.pack("<" + "Q" * len(ef.low_words), *ef.low_words))
            if ef.high_words:
                f.write(struct.pack("<" + "Q" * len(ef.high_words), *ef.high_words))
            if ef.select_hints:
                f.write(struct.pack("<" + "I" * len(ef.select_hints), *ef.select_hints))
        else:
            raise ValueError(f"unsupported index_version={index_version}")

        if result.pilots:
            if PILOT_BITS <= 8:
                f.write(struct.pack("<" + "B" * len(result.pilots), *result.pilots))
            else:
                f.write(struct.pack("<" + "H" * len(result.pilots), *result.pilots))

    return path.stat().st_size


def _write_meta_json(
    path: Path,
    *,
    pe: int,
    core: int,
    epsilon: float,
    shape: Dict[str, int],
    result: BuildResult,
    bucket_target: int,
    idx_bytes: int,
    index_version: int,
    ef_select_step: int,
) -> None:
    values_bytes = int(result.edges_total * 4)
    ratio = float(idx_bytes) / float(values_bytes) if values_bytes > 0 else 0.0
    bits_per_edge = float(idx_bytes * 8.0 / result.edges_total) if result.edges_total > 0 else 0.0
    fmt = "gcss_valueonly_dstcore_vlf_premphf_v1"
    if int(index_version) == VERSION_V2:
        fmt = "gcss_valueonly_dstcore_vlf_premphf_v2_efbase"

    obj = {
        "schema_version": 1,
        "format": fmt,
        "magic": "GCSSVLFP",
        "version": int(index_version),
        "pe": pe,
        "core": core,
        "epsilon": float(epsilon),
        "rows": int(shape["rows"]),
        "cols": int(shape["cols"]),
        "br": int(shape["br"]),
        "bc": int(shape["bc"]),
        "pre_count": int(result.pre_count),
        "edges_total": int(result.edges_total),
        "bucket_target": int(bucket_target),
        "bucket_count": int(result.bucket_count),
        "pilot_bits": PILOT_BITS,
        "hash_kind": HASH_KIND,
        "flags": FLAG_STRICT,
        "seed": int(result.seed),
        "values_bytes": values_bytes,
        "index_bytes": int(idx_bytes),
        "index_to_values_ratio": float(ratio),
        "index_bits_per_edge": float(bits_per_edge),
    }
    if int(index_version) == VERSION_V2:
        obj["ef_select_step"] = int(ef_select_step)
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
    total_pres: int,
    total_edges: int,
    values_total_bytes: int,
    index_total_bytes: int,
    index_version: int,
    ef_select_step: int,
) -> None:
    ratio = float(index_total_bytes) / float(values_total_bytes) if values_total_bytes > 0 else 0.0
    bits_per_edge = float(index_total_bytes * 8.0 / total_edges) if total_edges > 0 else 0.0
    fmt = "gcss_valueonly_dstcore_vlf_premphf_v1"
    if int(index_version) == VERSION_V2:
        fmt = "gcss_valueonly_dstcore_vlf_premphf_v2_efbase"
    obj = {
        "schema_version": 1,
        "format": fmt,
        "bcsr_dir": str(bcsr_dir),
        "out_dir": str(out_dir),
        "epsilon": float(epsilon),
        "bucket_target": int(bucket_target),
        "pilot_bits": PILOT_BITS,
        "hash_kind": HASH_KIND,
        "index_version": int(index_version),
        "magic": "GCSSVLFP",
        "max_seed_tries": int(max_seed_tries),
        "total_cores": int(total_cores),
        "total_pres": int(total_pres),
        "total_edges": int(total_edges),
        "values_total_bytes": int(values_total_bytes),
        "index_total_bytes": int(index_total_bytes),
        "index_to_values_ratio": float(ratio),
        "index_bits_per_edge": float(bits_per_edge),
    }
    if int(index_version) == VERSION_V2:
        obj["ef_select_step"] = int(ef_select_step)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _process_core(task: Tuple[str, str, float, int, int, bool, int, int]) -> Dict[str, object]:
    (
        core_file_s,
        out_dir_s,
        epsilon,
        bucket_target,
        max_seed_tries,
        self_check,
        index_version,
        ef_select_step,
    ) = task
    p = Path(core_file_s)
    out_dir = Path(out_dir_s)
    pe, core = _parse_core_id(p)

    edges, shape = _parse_bcsr_edges(p, epsilon=float(epsilon))
    result, pre_to_pairs, keys, slot_keys = _build_premphf(
        edges,
        bucket_target=int(bucket_target),
        max_seed_tries=int(max_seed_tries),
    )

    if bool(self_check):
        _self_check(
            result=result,
            pre_to_pairs=pre_to_pairs,
            keys=keys,
            slot_keys=slot_keys,
            core_tag=f"pe{pe:02d}/core{core:02d}",
        )

    pe_dir = out_dir / f"pe{pe:02d}"
    values_path = pe_dir / f"core{core:02d}.gcssvlf.bin"
    idx_path = pe_dir / f"core{core:02d}.gcssvlf.idx.bin"
    meta_path = pe_dir / f"core{core:02d}.gcssvlf.meta.json"

    _write_values_bin(values_path, result.values)
    idx_bytes = _write_index_bin(
        idx_path,
        result,
        int(bucket_target),
        index_version=int(index_version),
        ef_select_step=int(ef_select_step),
    )
    _write_meta_json(
        meta_path,
        pe=pe,
        core=core,
        epsilon=float(epsilon),
        shape=shape,
        result=result,
        bucket_target=int(bucket_target),
        idx_bytes=idx_bytes,
        index_version=int(index_version),
        ef_select_step=int(ef_select_step),
    )

    values_bytes = int(result.edges_total * 4)
    ratio = float(idx_bytes) / float(values_bytes) if values_bytes > 0 else 0.0
    bits_per_edge = float(idx_bytes * 8.0 / result.edges_total) if result.edges_total > 0 else 0.0
    log_line = (
        f"[gcssvlf-gen] pe={pe:02d} core={core:02d} pres={result.pre_count} "
        f"edges={result.edges_total} values_bytes={values_bytes} "
        f"idx_bytes={idx_bytes} ratio={ratio:.6f} bits_per_edge={bits_per_edge:.4f} "
        f"idx_ver={int(index_version)}"
    )

    return {
        "pe": pe,
        "core": core,
        "pre_count": int(result.pre_count),
        "edges_total": int(result.edges_total),
        "values_bytes": int(values_bytes),
        "idx_bytes": int(idx_bytes),
        "ratio": float(ratio),
        "bits_per_edge": float(bits_per_edge),
        "log_line": log_line,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bcsr-dir", required=True, help="input BCSR directory, e.g. weights/bcsr_global_16pe_fanout256_10k")
    ap.add_argument("--out-dir", required=True, help="output directory for GCSS-VLF files")
    ap.add_argument("--epsilon", type=float, default=1e-8, help="abs(weight)<=epsilon is treated as zero edge")
    ap.add_argument("--bucket-target", type=int, default=3, help="target bucket size for pre-MPHF")
    ap.add_argument("--max-seed-tries", type=int, default=128, help="max global seed retries")
    ap.add_argument("--jobs", type=int, default=1, help="number of worker processes (per-core parallel)")
    ap.add_argument("--self-check", action="store_true", help="run strict consistency checks")
    ap.add_argument(
        "--index-version",
        type=int,
        default=VERSION_V1,
        choices=[VERSION_V1, VERSION_V2, VERSION_V3],
        help="index format version: 1=legacy slot_base/slot_len, 2=Elias-Fano slot_base, 3=rank-map + Elias-Fano base_by_rank",
    )
    ap.add_argument(
        "--ef-select-step",
        type=int,
        default=EF_SELECT_STEP_DEFAULT,
        help="sampling interval for Elias-Fano select hints (v2)",
    )
    args = ap.parse_args()

    bcsr_dir = Path(args.bcsr_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    if not bcsr_dir.is_dir():
        raise SystemExit(f"[gcssvlf-gen] bcsr_dir not found: {bcsr_dir}")
    if args.bucket_target <= 0:
        raise SystemExit(f"[gcssvlf-gen] invalid --bucket-target={args.bucket_target}, expected >0")
    if args.max_seed_tries <= 0:
        raise SystemExit(f"[gcssvlf-gen] invalid --max-seed-tries={args.max_seed_tries}, expected >0")
    if args.jobs <= 0:
        raise SystemExit(f"[gcssvlf-gen] invalid --jobs={args.jobs}, expected >0")
    if args.ef_select_step <= 0:
        raise SystemExit(f"[gcssvlf-gen] invalid --ef-select-step={args.ef_select_step}, expected >0")

    core_files = list(_iter_core_bcsr_files(bcsr_dir))
    if not core_files:
        raise SystemExit(f"[gcssvlf-gen] no core*.bcsr.bin found under: {bcsr_dir}")

    tasks: List[Tuple[str, str, float, int, int, bool, int, int]] = []
    for p in core_files:
        tasks.append(
            (
                str(p),
                str(out_dir),
                float(args.epsilon),
                int(args.bucket_target),
                int(args.max_seed_tries),
                bool(args.self_check),
                int(args.index_version),
                int(args.ef_select_step),
            )
        )

    results: List[Dict[str, object]] = []
    jobs = int(args.jobs)
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

    total_pres = int(sum(int(r["pre_count"]) for r in results))
    total_edges = int(sum(int(r["edges_total"]) for r in results))
    total_values_bytes = int(sum(int(r["values_bytes"]) for r in results))
    total_index_bytes = int(sum(int(r["idx_bytes"]) for r in results))

    _write_manifest(
        out_dir / "manifest.json",
        bcsr_dir=bcsr_dir,
        out_dir=out_dir,
        epsilon=float(args.epsilon),
        bucket_target=int(args.bucket_target),
        max_seed_tries=int(args.max_seed_tries),
        total_cores=len(core_files),
        total_pres=total_pres,
        total_edges=total_edges,
        values_total_bytes=total_values_bytes,
        index_total_bytes=total_index_bytes,
        index_version=int(args.index_version),
        ef_select_step=int(args.ef_select_step),
    )

    ratio = float(total_index_bytes) / float(total_values_bytes) if total_values_bytes > 0 else 0.0
    bits_per_edge = float(total_index_bytes * 8.0 / total_edges) if total_edges > 0 else 0.0
    print(
        f"[gcssvlf-gen] done: cores={len(core_files)} total_pres={total_pres} total_edges={total_edges} "
        f"values_total_bytes={total_values_bytes} index_total_bytes={total_index_bytes} "
        f"ratio={ratio:.6f} bits_per_edge={bits_per_edge:.4f} "
        f"idx_ver={int(args.index_version)} out_dir={out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
