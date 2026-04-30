#!/usr/bin/env python3
"""
Canonical artifact-decode analyzer for GCSS-PLP layout locality.

This tool decodes v7 GCSS-PLP index artifacts, reconstructs the exact
physical pre layout, and evaluates profile-weighted locality metrics plus
weak-neighborhood cut metrics for offline layout experiments.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple

import gen_gcss_valueonly_dstcore_vlf_premphf_plp as plp


V7_HEADER = struct.Struct("<8sIIIIIIIII")
V7_EXTRA = struct.Struct("<" + "I" * 26)
VALUES_PER_8KB_ROW = (8 * 1024) // plp.VALUE_SIZE_BYTES
VALUES_PER_16KB_WINDOW = (16 * 1024) // plp.VALUE_SIZE_BYTES


def _read_json(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"invalid json object: {path}")
    return obj


def _read_exact(path: Path, offset: int, size: int) -> bytes:
    if size < 0:
        raise ValueError(f"invalid size={size} for {path}")
    with path.open("rb") as f:
        f.seek(offset)
        payload = f.read(size)
    if len(payload) != size:
        raise ValueError(f"short read path={path} offset={offset} size={size} got={len(payload)}")
    return payload


def _replace_meta_suffix(meta_path: Path, replacement: str) -> Path:
    name = meta_path.name
    suffix = ".gcssplp.meta.json"
    if not name.endswith(suffix):
        raise ValueError(f"unexpected meta path: {meta_path}")
    stem = name[: -len(suffix)]
    return meta_path.with_name(f"{stem}.gcssplp{replacement}")


def _parse_core_spec(spec: str) -> Tuple[int, int]:
    raw = str(spec).strip()
    m = re.fullmatch(r"(?:pe)?(\d{2})[/:](?:core)?(\d{2})", raw)
    if not m:
        raise ValueError(f"invalid core spec: {spec}")
    return int(m.group(1)), int(m.group(2))


def _format_core_spec(pe: int, core: int) -> str:
    return f"pe{int(pe):02d}/core{int(core):02d}"


def _iter_default_meta_paths(artifact_dir: Path) -> Iterable[Path]:
    for path in sorted(artifact_dir.glob("pe*/core*.gcssplp.meta.json")):
        if path.is_file():
            yield path


def _unpack_value_bits(words: Sequence[int], bit_offset: int, bit_width: int) -> int:
    bits = int(bit_width)
    if bits <= 0:
        return 0
    word_index = int(bit_offset) >> 6
    shift = int(bit_offset) & 63
    value = int(words[word_index]) >> shift
    spill = shift + bits - 64
    if spill > 0:
        if word_index + 1 >= len(words):
            raise ValueError("bit unpack overflow")
        value |= int(words[word_index + 1]) << (bits - spill)
    mask = (1 << bits) - 1
    return int(value & mask)


def _decode_fixed_u64(words: Sequence[int], *, count: int, bit_width: int) -> List[int]:
    bits = int(bit_width)
    n = int(count)
    if n <= 0:
        return []
    if bits <= 0:
        return [0] * n
    return [_unpack_value_bits(words, idx * bits, bits) for idx in range(n)]


def _decode_monotone_ef(
    *,
    low_words: Sequence[int],
    high_words: Sequence[int],
    l: int,
    count: int,
) -> List[int]:
    n = int(count)
    low_bits = int(l)
    lows = _decode_fixed_u64(low_words, count=n, bit_width=low_bits)
    high_positions: List[int] = []
    for word_idx, word in enumerate(high_words):
        value = int(word)
        base_bit = word_idx * 64
        while value:
            lsb = value & -value
            bit = lsb.bit_length() - 1
            high_positions.append(base_bit + bit)
            if len(high_positions) >= n:
                break
            value ^= lsb
        if len(high_positions) >= n:
            break
    if len(high_positions) != n:
        raise ValueError(f"EF decode mismatch: expected {n} highs, got {len(high_positions)}")
    out: List[int] = []
    for idx, high_pos in enumerate(high_positions):
        high_value = int(high_pos - idx)
        out.append((high_value << low_bits) | int(lows[idx]))
    return out


def _decode_v7_lens(
    *,
    pre_count: int,
    edges_total: int,
    block_size: int,
    block_base_prefix: Sequence[int],
    block_word_offset: Sequence[int],
    block_mode: Sequence[int],
    block_arg: Sequence[int],
    payload_words: Sequence[int],
) -> List[int]:
    n = int(pre_count)
    bsz = int(block_size)
    if bsz <= 0:
        raise ValueError(f"invalid block_size={block_size}")
    if n <= 0:
        return []

    lens: List[int] = []
    prefix = 0
    block_count = (n + bsz - 1) // bsz
    if len(block_base_prefix) < block_count or len(block_word_offset) < block_count:
        raise ValueError("v7 len block header underflow")

    for block in range(block_count):
        start = block * bsz
        block_len = min(n - start, bsz)
        if block_len <= 0:
            break
        if int(block_base_prefix[block]) != int(prefix):
            raise ValueError(
                f"v7 len prefix mismatch block={block} expect={prefix} got={block_base_prefix[block]}"
            )
        word_offset = int(block_word_offset[block])
        mode = int(block_mode[block])
        arg = int(block_arg[block])

        if mode == 1:
            block_lens = [1] * block_len
        elif mode == 0:
            block_lens = [
                int(_unpack_value_bits(payload_words, word_offset * 64 + idx * arg, arg))
                for idx in range(block_len)
            ]
        elif mode == 2:
            bitmap_words = (block_len + 63) // 64
            bitmap = [int(v) for v in payload_words[word_offset : word_offset + bitmap_words]]
            exc_count = sum(int(word).bit_count() for word in bitmap)
            exc_values = [
                int(
                    _unpack_value_bits(
                        payload_words,
                        (word_offset + bitmap_words) * 64 + idx * arg,
                        arg,
                    )
                )
                for idx in range(exc_count)
            ]
            exc_idx = 0
            block_lens = []
            for idx in range(block_len):
                if (bitmap[idx >> 6] >> (idx & 63)) & 1:
                    block_lens.append(int(exc_values[exc_idx]))
                    exc_idx += 1
                else:
                    block_lens.append(1)
        else:
            raise ValueError(f"unsupported v7 len block mode={mode}")

        prefix += int(sum(block_lens))
        lens.extend(int(v) for v in block_lens)

    if len(lens) != n:
        raise ValueError(f"v7 len count mismatch: expected={n} got={len(lens)}")
    if int(prefix) != int(edges_total):
        raise ValueError(f"v7 len total mismatch: expected={edges_total} got={prefix}")
    return lens


def _decode_gcssplp_v7_index_layout(idx_path: Path) -> Dict[str, object]:
    header_raw = _read_exact(idx_path, 0, V7_HEADER.size)
    (
        magic,
        version,
        pre_count,
        edges_total,
        _bucket_target,
        _pilot_bits,
        _hash_kind,
        _flags,
        _seed,
        _bucket_count,
    ) = V7_HEADER.unpack(header_raw)
    if magic != b"GCSSVLFP":
        raise ValueError(f"unexpected index magic in {idx_path}: {magic!r}")
    if int(version) != int(plp.INDEX_VERSION_V7):
        raise ValueError(f"unsupported index version in {idx_path}: {version}")

    extra_raw = _read_exact(idx_path, V7_HEADER.size, V7_EXTRA.size)
    (
        _key_max,
        keys_l,
        keys_low_n,
        keys_high_n,
        _keys_select_step,
        keys_select_hints_n,
        run_count,
        run_rank_bits,
        run_rank_words_n,
        run_ends_l,
        run_ends_low_n,
        run_ends_high_n,
        _run_ends_select_step,
        run_ends_select_hints_n,
        len_block_size,
        len_block_count,
        block_base_bits,
        block_base_words_n,
        block_word_offset_bits,
        block_word_offset_words_n,
        block_mode_bits,
        block_mode_words_n,
        block_arg_bits,
        block_arg_words_n,
        payload_words_n,
        _reserved,
    ) = V7_EXTRA.unpack(extra_raw)

    offset = V7_HEADER.size + V7_EXTRA.size

    def _read_u64_words(count: int) -> List[int]:
        nonlocal offset
        size = int(count) * 8
        if size <= 0:
            return []
        raw = _read_exact(idx_path, offset, size)
        offset += size
        return [int(v) for v in struct.unpack("<" + "Q" * int(count), raw)]

    def _read_u32_words(count: int) -> List[int]:
        nonlocal offset
        size = int(count) * 4
        if size <= 0:
            return []
        raw = _read_exact(idx_path, offset, size)
        offset += size
        return [int(v) for v in struct.unpack("<" + "I" * int(count), raw)]

    keys_low_words = _read_u64_words(keys_low_n)
    keys_high_words = _read_u64_words(keys_high_n)
    _keys_select_hints = _read_u32_words(keys_select_hints_n)
    run_rank_words = _read_u64_words(run_rank_words_n)
    run_ends_low_words = _read_u64_words(run_ends_low_n)
    run_ends_high_words = _read_u64_words(run_ends_high_n)
    _run_ends_select_hints = _read_u32_words(run_ends_select_hints_n)
    block_base_words = _read_u64_words(block_base_words_n)
    block_word_offset_words = _read_u64_words(block_word_offset_words_n)
    block_mode_words = _read_u64_words(block_mode_words_n)
    block_arg_words = _read_u64_words(block_arg_words_n)
    payload_words = _read_u64_words(payload_words_n)

    keys_sorted = _decode_monotone_ef(
        low_words=keys_low_words,
        high_words=keys_high_words,
        l=int(keys_l),
        count=int(pre_count),
    )
    run_bases = _decode_fixed_u64(run_rank_words, count=int(run_count), bit_width=int(run_rank_bits))
    run_ends = _decode_monotone_ef(
        low_words=run_ends_low_words,
        high_words=run_ends_high_words,
        l=int(run_ends_l),
        count=int(run_count),
    )

    sid_ranks: List[int] = []
    prev_end = 0
    for run_base, run_end in zip(run_bases, run_ends):
        end = int(run_end)
        if end < prev_end:
            raise ValueError(f"run end regression in {idx_path}: prev={prev_end} now={end}")
        run_len = end - prev_end
        for delta in range(run_len):
            sid_ranks.append(int(run_base) + int(delta))
        prev_end = end
    if len(sid_ranks) != int(pre_count):
        raise ValueError(f"sid rank count mismatch: expected={pre_count} got={len(sid_ranks)}")

    block_base_prefix = _decode_fixed_u64(
        block_base_words,
        count=int(len_block_count),
        bit_width=int(block_base_bits),
    )
    block_word_offset = _decode_fixed_u64(
        block_word_offset_words,
        count=int(len_block_count),
        bit_width=int(block_word_offset_bits),
    )
    block_mode = _decode_fixed_u64(
        block_mode_words,
        count=int(len_block_count),
        bit_width=int(block_mode_bits),
    )
    block_arg = _decode_fixed_u64(
        block_arg_words,
        count=int(len_block_count),
        bit_width=int(block_arg_bits),
    )
    lens_by_rank = _decode_v7_lens(
        pre_count=int(pre_count),
        edges_total=int(edges_total),
        block_size=int(len_block_size),
        block_base_prefix=block_base_prefix,
        block_word_offset=block_word_offset,
        block_mode=block_mode,
        block_arg=block_arg,
        payload_words=payload_words,
    )

    physical_pre_order: List[int] = [-1] * int(pre_count)
    rank_by_pre: Dict[int, int] = {}
    for pre, rank in zip(keys_sorted, sid_ranks):
        r = int(rank)
        if r < 0 or r >= int(pre_count):
            raise ValueError(f"sid rank out of range pre={pre} rank={rank}")
        if physical_pre_order[r] != -1:
            raise ValueError(f"duplicate physical rank={r} in {idx_path}")
        physical_pre_order[r] = int(pre)
        rank_by_pre[int(pre)] = int(r)
    if any(int(pre) < 0 for pre in physical_pre_order):
        raise ValueError(f"incomplete physical order decode in {idx_path}")

    base_by_rank: List[int] = []
    cursor = 0
    for seg_len in lens_by_rank:
        base_by_rank.append(int(cursor))
        cursor += int(seg_len)
    if int(cursor) != int(edges_total):
        raise ValueError(f"decoded base mismatch: expected={edges_total} got={cursor}")

    base_by_pre = {int(pre): int(base_by_rank[rank_by_pre[int(pre)]]) for pre in keys_sorted}
    len_by_pre = {int(pre): int(lens_by_rank[rank_by_pre[int(pre)]]) for pre in keys_sorted}
    return {
        "pre_count": int(pre_count),
        "edges_total": int(edges_total),
        "keys_sorted": [int(v) for v in keys_sorted],
        "physical_pre_order": [int(v) for v in physical_pre_order],
        "rank_by_pre": {int(k): int(v) for k, v in rank_by_pre.items()},
        "base_by_rank": [int(v) for v in base_by_rank],
        "lens_by_rank": [int(v) for v in lens_by_rank],
        "base_by_pre": {int(k): int(v) for k, v in base_by_pre.items()},
        "len_by_pre": {int(k): int(v) for k, v in len_by_pre.items()},
    }


def _interval_gap(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    a0, a1 = int(a[0]), int(a[1])
    b0, b1 = int(b[0]), int(b[1])
    if a1 < b0:
        return int(b0 - a1)
    if b1 < a0:
        return int(a0 - b1)
    return 0


def _build_region_ranges(
    *,
    base_by_pre: Dict[int, int],
    len_by_pre: Dict[int, int],
    unit_values: int,
) -> Dict[int, Tuple[int, int]]:
    out: Dict[int, Tuple[int, int]] = {}
    scale = int(unit_values)
    if scale <= 0:
        raise ValueError(f"invalid unit_values={unit_values}")
    for pre, base_value in base_by_pre.items():
        seg_len = int(len_by_pre.get(int(pre), 0))
        if seg_len <= 0:
            continue
        start = int(base_value)
        end = start + seg_len - 1
        out[int(pre)] = (int(start // scale), int(end // scale))
    return out


def _analyze_transition_locality(
    *,
    trans: Dict[Tuple[int, int], int],
    base_by_pre: Dict[int, int],
    len_by_pre: Dict[int, int],
) -> Dict[str, float]:
    total_weight = 0
    same_line = 0
    same_row = 0
    same_window = 0
    line_gap_weighted = 0.0
    row_gap_weighted = 0.0
    window_gap_weighted = 0.0

    line_ranges = _build_region_ranges(
        base_by_pre=base_by_pre,
        len_by_pre=len_by_pre,
        unit_values=int(plp.VALUES_PER_LINE),
    )
    row_ranges = _build_region_ranges(
        base_by_pre=base_by_pre,
        len_by_pre=len_by_pre,
        unit_values=int(VALUES_PER_8KB_ROW),
    )
    window_ranges = _build_region_ranges(
        base_by_pre=base_by_pre,
        len_by_pre=len_by_pre,
        unit_values=int(VALUES_PER_16KB_WINDOW),
    )

    for (src, dst), raw_weight in trans.items():
        weight = int(raw_weight)
        if weight <= 0:
            continue
        a_line = line_ranges.get(int(src))
        b_line = line_ranges.get(int(dst))
        a_row = row_ranges.get(int(src))
        b_row = row_ranges.get(int(dst))
        a_window = window_ranges.get(int(src))
        b_window = window_ranges.get(int(dst))
        if a_line is None or b_line is None or a_row is None or b_row is None or a_window is None or b_window is None:
            continue

        total_weight += weight
        line_gap = _interval_gap(a_line, b_line)
        row_gap = _interval_gap(a_row, b_row)
        window_gap = _interval_gap(a_window, b_window)
        if line_gap == 0:
            same_line += weight
        if row_gap == 0:
            same_row += weight
        if window_gap == 0:
            same_window += weight
        line_gap_weighted += float(line_gap) * float(weight)
        row_gap_weighted += float(row_gap) * float(weight)
        window_gap_weighted += float(window_gap) * float(weight)

    if total_weight <= 0:
        return {
            "profile_transition_weight_total": 0,
            "same_line_rate": 0.0,
            "same_8KB_row_rate": 0.0,
            "same_16KB_window_rate": 0.0,
            "avg_line_gap": 0.0,
            "avg_8KB_row_gap": 0.0,
            "avg_16KB_window_gap": 0.0,
        }
    denom = float(total_weight)
    return {
        "profile_transition_weight_total": int(total_weight),
        "same_line_rate": float(same_line) / denom,
        "same_8KB_row_rate": float(same_row) / denom,
        "same_16KB_window_rate": float(same_window) / denom,
        "avg_line_gap": float(line_gap_weighted) / denom,
        "avg_8KB_row_gap": float(row_gap_weighted) / denom,
        "avg_16KB_window_gap": float(window_gap_weighted) / denom,
    }


def _build_dummy_pre_to_pairs(len_by_pre: Dict[int, int]) -> Dict[int, List[Tuple[int, float]]]:
    return {
        int(pre): [(0, 0.0)] * int(seg_len)
        for pre, seg_len in len_by_pre.items()
        if int(seg_len) > 0
    }


def _analyze_anchor_metrics(
    *,
    physical_pre_order: Sequence[int],
    base_by_pre: Dict[int, int],
    len_by_pre: Dict[int, int],
    freq: Dict[int, int],
    trans: Dict[Tuple[int, int], int],
    risk_stats: Dict[int, Dict[str, float]],
) -> Dict[str, float]:
    keys = [int(pre) for pre in physical_pre_order if int(pre) in len_by_pre]
    if not keys:
        return {
            "anchor_escape_count": 0,
            "cross_block_weak_edge_weight_ratio": 0.0,
            "weak_edge_total": 0,
        }

    shadow_plan = plp._build_anchor_separator_shadow_plan(
        keys,
        _build_dummy_pre_to_pairs(len_by_pre),
        freq=freq,
        trans=trans,
        risk_stats=risk_stats,
        baseline_order=physical_pre_order,
    )
    pre_to_community: Dict[int, int] = {}
    for row in list(shadow_plan.get("anchor_map", [])):
        community_id = int(row.get("community_id", -1))
        for pre in list(row.get("members", [])):
            pre_to_community[int(pre)] = int(community_id)

    macroblock_ranges = _build_region_ranges(
        base_by_pre=base_by_pre,
        len_by_pre=len_by_pre,
        unit_values=int(plp.ANCHOR_SEPARATOR_MACROBLOCK_VALUES_DEFAULT),
    )

    weak_edge_total = 0
    weak_edge_cross_block = 0
    for target in plp._ordered_dual_guard_targets(risk_stats):
        target_block = macroblock_ranges.get(int(target))
        if target_block is None:
            continue
        for nbr in [
            int(v)
            for v in list(risk_stats.get(int(target), {}).get("weak_neighbors", []))[
                : int(plp.ANCHOR_SEPARATOR_WEAK_TOP_K_DEFAULT)
            ]
            if int(v) in macroblock_ranges
        ]:
            weak_edge_total += 1
            if _interval_gap(target_block, macroblock_ranges[int(nbr)]) > 0:
                weak_edge_cross_block += 1

    return {
        "anchor_escape_count": int(shadow_plan.get("cut_summary", {}).get("anchor_escape_count", 0)),
        "cross_block_weak_edge_weight_ratio": (
            float(weak_edge_cross_block) / float(weak_edge_total) if weak_edge_total > 0 else 0.0
        ),
        "weak_edge_total": int(weak_edge_total),
        "anchor_community_count": int(shadow_plan.get("cut_summary", {}).get("anchor_community_count", 0)),
    }


def analyze_core_artifact(
    meta_path: Path,
    *,
    profile_path: Optional[Path] = None,
    hol_profile_path: Optional[Path] = None,
    profile_lookahead: Optional[int] = None,
    hol_head_k: Optional[int] = None,
) -> Dict[str, object]:
    meta = _read_json(meta_path)
    idx_path = _replace_meta_suffix(meta_path, ".idx.bin")
    decoded = _decode_gcssplp_v7_index_layout(idx_path)

    pe = int(meta.get("pe", 0))
    core = int(meta.get("core", 0))
    core_spec = _format_core_spec(pe, core)

    effective_profile_path = profile_path or Path(str(meta.get("profile_path", "") or ""))
    effective_hol_profile_path = hol_profile_path or Path(str(meta.get("hol_profile_path", "") or ""))
    effective_profile_lookahead = int(
        profile_lookahead if profile_lookahead is not None else int(meta.get("profile_lookahead", 0) or 0)
    )
    effective_hol_head_k = int(
        hol_head_k if hol_head_k is not None else int(meta.get("hol_head_k", 0) or 0)
    )

    if not effective_profile_path or not effective_profile_path.is_file():
        raise FileNotFoundError(f"profile path missing for {core_spec}: {effective_profile_path}")
    if not effective_hol_profile_path or not effective_hol_profile_path.is_file():
        raise FileNotFoundError(f"hol profile path missing for {core_spec}: {effective_hol_profile_path}")
    if effective_profile_lookahead <= 0:
        raise ValueError(f"invalid profile_lookahead for {core_spec}: {effective_profile_lookahead}")
    if effective_hol_head_k <= 0:
        raise ValueError(f"invalid hol_head_k for {core_spec}: {effective_hol_head_k}")

    seqs = plp._load_profile_sequences(effective_profile_path)
    freq, trans = plp._build_profile_graph(seqs, lookahead=effective_profile_lookahead)
    risk_stats, hol_stats = plp._load_hol_profile_risk_stats(
        effective_hol_profile_path,
        head_k=effective_hol_head_k,
    )
    locality = _analyze_transition_locality(
        trans=trans,
        base_by_pre=decoded["base_by_pre"],
        len_by_pre=decoded["len_by_pre"],
    )
    anchor = _analyze_anchor_metrics(
        physical_pre_order=decoded["physical_pre_order"],
        base_by_pre=decoded["base_by_pre"],
        len_by_pre=decoded["len_by_pre"],
        freq=freq,
        trans=trans,
        risk_stats=risk_stats,
    )

    return {
        "core": core_spec,
        "meta_path": str(meta_path),
        "idx_path": str(idx_path),
        "profile_path": str(effective_profile_path),
        "hol_profile_path": str(effective_hol_profile_path),
        "physical_order_mode": str(meta.get("physical_order_mode", "")),
        "index_version": int(meta.get("index_version", 0) or 0),
        "pre_count": int(decoded["pre_count"]),
        "edges_total": int(decoded["edges_total"]),
        "hol_high_risk_target_count": int(hol_stats.get("hol_high_risk_target_count", 0)),
        "profile_transition_weight_total": int(locality["profile_transition_weight_total"]),
        "same_line_rate": float(locality["same_line_rate"]),
        "same_8KB_row_rate": float(locality["same_8KB_row_rate"]),
        "same_16KB_window_rate": float(locality["same_16KB_window_rate"]),
        "avg_line_gap": float(locality["avg_line_gap"]),
        "avg_8KB_row_gap": float(locality["avg_8KB_row_gap"]),
        "avg_16KB_window_gap": float(locality["avg_16KB_window_gap"]),
        "anchor_escape_count": int(anchor["anchor_escape_count"]),
        "cross_block_weak_edge_weight_ratio": float(anchor["cross_block_weak_edge_weight_ratio"]),
        "weak_edge_total": int(anchor["weak_edge_total"]),
        "anchor_community_count": int(anchor["anchor_community_count"]),
    }


def aggregate_reports(reports: Sequence[Dict[str, object]]) -> Dict[str, object]:
    items = list(reports)
    total_transitions = int(sum(int(row.get("profile_transition_weight_total", 0)) for row in items))
    total_weak_edges = int(sum(int(row.get("weak_edge_total", 0)) for row in items))
    total_anchor_escape = int(sum(int(row.get("anchor_escape_count", 0)) for row in items))

    def _weighted_average(key: str, weight_key: str) -> float:
        total_weight = float(sum(float(row.get(weight_key, 0)) for row in items))
        if total_weight <= 0.0:
            return 0.0
        weighted_sum = sum(float(row.get(key, 0.0)) * float(row.get(weight_key, 0)) for row in items)
        return float(weighted_sum / total_weight)

    return {
        "core_count": int(len(items)),
        "profile_transition_weight_total": int(total_transitions),
        "weak_edge_total": int(total_weak_edges),
        "anchor_escape_count": int(total_anchor_escape),
        "same_line_rate": _weighted_average("same_line_rate", "profile_transition_weight_total"),
        "same_8KB_row_rate": _weighted_average("same_8KB_row_rate", "profile_transition_weight_total"),
        "same_16KB_window_rate": _weighted_average("same_16KB_window_rate", "profile_transition_weight_total"),
        "avg_line_gap": _weighted_average("avg_line_gap", "profile_transition_weight_total"),
        "avg_8KB_row_gap": _weighted_average("avg_8KB_row_gap", "profile_transition_weight_total"),
        "avg_16KB_window_gap": _weighted_average("avg_16KB_window_gap", "profile_transition_weight_total"),
        "cross_block_weak_edge_weight_ratio": _weighted_average(
            "cross_block_weak_edge_weight_ratio",
            "weak_edge_total",
        ),
    }


def _derive_profile_paths(profile_root: Path, pe: int, core: int) -> Tuple[Path, Path]:
    pe_dir = profile_root / f"pe{int(pe):02d}"
    return (
        pe_dir / f"core{int(core):02d}.pre_windows.csv",
        pe_dir / f"core{int(core):02d}.offline_layout_profile.csv",
    )


def _write_tsv(path: Path, reports: Sequence[Dict[str, object]]) -> None:
    fields = [
        "core",
        "physical_order_mode",
        "pre_count",
        "edges_total",
        "profile_transition_weight_total",
        "same_line_rate",
        "same_8KB_row_rate",
        "same_16KB_window_rate",
        "avg_line_gap",
        "avg_8KB_row_gap",
        "avg_16KB_window_gap",
        "anchor_escape_count",
        "weak_edge_total",
        "cross_block_weak_edge_weight_ratio",
    ]
    lines = ["\t".join(fields)]
    for row in reports:
        lines.append("\t".join(str(row.get(field, "")) for field in fields))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", required=True, help="GCSS-PLP artifact root containing peXX/coreYY.gcssplp.*")
    ap.add_argument(
        "--core",
        action="append",
        default=[],
        help="core spec like pe10/core11; repeatable. default: analyze all cores in artifact-dir",
    )
    ap.add_argument(
        "--profile-root",
        default="",
        help="optional profile root used to override meta-embedded profile paths",
    )
    ap.add_argument("--profile-lookahead", type=int, default=0, help="optional override for profile lookahead")
    ap.add_argument("--hol-head-k", type=int, default=0, help="optional override for HOL head-k")
    ap.add_argument("--out-json", default="", help="optional output json path")
    ap.add_argument("--out-tsv", default="", help="optional output tsv path")
    args = ap.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    profile_root = Path(args.profile_root).resolve() if args.profile_root else None
    profile_lookahead = int(args.profile_lookahead) if int(args.profile_lookahead) > 0 else None
    hol_head_k = int(args.hol_head_k) if int(args.hol_head_k) > 0 else None

    if args.core:
        meta_paths = []
        for spec in args.core:
            pe, core = _parse_core_spec(spec)
            meta_path = artifact_dir / f"pe{pe:02d}" / f"core{core:02d}.gcssplp.meta.json"
            if not meta_path.is_file():
                raise FileNotFoundError(f"meta not found for {spec}: {meta_path}")
            meta_paths.append(meta_path)
    else:
        meta_paths = list(_iter_default_meta_paths(artifact_dir))
        if not meta_paths:
            raise FileNotFoundError(f"no GCSS-PLP meta files found in {artifact_dir}")

    reports: List[Dict[str, object]] = []
    for meta_path in meta_paths:
        meta = _read_json(meta_path)
        pe = int(meta.get("pe", 0))
        core = int(meta.get("core", 0))
        if profile_root is not None:
            profile_path, hol_profile_path = _derive_profile_paths(profile_root, pe, core)
        else:
            profile_path = None
            hol_profile_path = None
        reports.append(
            analyze_core_artifact(
                meta_path,
                profile_path=profile_path,
                hol_profile_path=hol_profile_path,
                profile_lookahead=profile_lookahead,
                hol_head_k=hol_head_k,
            )
        )

    aggregate = aggregate_reports(reports)
    payload = {
        "artifact_dir": str(artifact_dir),
        "profile_root": str(profile_root) if profile_root is not None else "",
        "reports": reports,
        "aggregate": aggregate,
    }

    if args.out_json:
        out_json = Path(args.out_json).resolve()
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.out_tsv:
        _write_tsv(Path(args.out_tsv).resolve(), reports)

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
