#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import struct
from pathlib import Path
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple


EXPERIMENT_DIR = Path(__file__).resolve().parent
DEFAULT_P3C1_DIR = Path(
    "/home/xgy/remote/sst_dram_si/weights/"
    "gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_hol_constrained_v2_1_p3c1_formal_j4"
)
DEFAULT_P3C2A_DIR = Path(
    "/home/xgy/remote/sst_dram_si/weights/"
    "gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_hol_constrained_v2_1_p3c2a_formal_j4"
)
DEFAULT_OUTPUT_DIR = EXPERIMENT_DIR / "snapshot"
DEFAULT_BANDS: Tuple[Tuple[int, int], ...] = ((0, 256), (256, 512), (512, 768))
DEFAULT_NEIGHBORHOOD_RADIUS = 256
DEFAULT_TOP_CORE_COUNT = 8
V7_HEADER_FMT = "<8sIIIIIIIII"
V7_EXTRA_FMT = "<" + "I" * 26
MAGIC = b"GCSSVLFP"


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"invalid json object: {path}")
    return obj


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _normalize_preview_list(value: object) -> List[int]:
    if not isinstance(value, list):
        return []
    return [_as_int(v, -1) for v in value if _as_int(v, -1) >= 0]


def _normalize_preview_map(value: object) -> Dict[int, List[int]]:
    if not isinstance(value, dict):
        return {}
    out: Dict[int, List[int]] = {}
    for raw_key, raw_list in value.items():
        key = _as_int(raw_key, -1)
        if key < 0:
            continue
        vals = _normalize_preview_list(raw_list)
        if vals:
            out[int(key)] = vals
    return out


def compute_meta_preview_overlap(meta1: Dict[str, object], meta2: Dict[str, object]) -> Dict[str, object]:
    targets1 = set(_normalize_preview_list(meta1.get("hol_high_risk_target_preview", [])))
    targets2 = set(_normalize_preview_list(meta2.get("hol_high_risk_target_preview", [])))
    target_overlap = sorted(int(v) for v in (targets1 & targets2))

    weak1 = _normalize_preview_map(meta1.get("hol_weak_neighborhood_preview", {}))
    weak2 = _normalize_preview_map(meta2.get("hol_weak_neighborhood_preview", {}))
    pairs1 = {(int(src), int(dst)) for src, nbrs in weak1.items() for dst in nbrs}
    pairs2 = {(int(src), int(dst)) for src, nbrs in weak2.items() for dst in nbrs}
    pair_overlap = sorted((int(src), int(dst)) for src, dst in (pairs1 & pairs2))

    return {
        "baseline_target_count": int(len(targets1)),
        "candidate_target_count": int(len(targets2)),
        "target_overlap_count": int(len(target_overlap)),
        "target_overlap_preview": list(target_overlap[:16]),
        "baseline_neighbor_pair_count": int(len(pairs1)),
        "candidate_neighbor_pair_count": int(len(pairs2)),
        "neighbor_pair_overlap_count": int(len(pair_overlap)),
        "neighbor_pair_overlap_preview": [f"{src}->{dst}" for src, dst in pair_overlap[:16]],
    }


def _resolve_meta_sidecar_path(meta_path: Path, raw_path: object) -> Optional[Path]:
    if not isinstance(raw_path, str):
        return None
    text = raw_path.strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = meta_path.parent / path
    return path


def load_anchor_shadow_bundle(meta_path: Path, meta: Dict[str, object]) -> Dict[str, object]:
    anchor_map_path = _resolve_meta_sidecar_path(meta_path, meta.get("anchor_separator_shadow_anchor_map_path"))
    block_plan_path = _resolve_meta_sidecar_path(meta_path, meta.get("anchor_separator_shadow_block_plan_path"))
    cut_summary_path = _resolve_meta_sidecar_path(meta_path, meta.get("anchor_separator_shadow_cut_summary_path"))

    anchor_map: List[Dict[str, object]] = []
    block_plan: List[Dict[str, object]] = []
    cut_summary: Dict[str, object] = {}

    if anchor_map_path is not None and anchor_map_path.is_file():
        anchor_map_obj = _read_json(anchor_map_path)
        anchor_map = list(anchor_map_obj.get("anchor_map", [])) if isinstance(anchor_map_obj.get("anchor_map", []), list) else []
    if block_plan_path is not None and block_plan_path.is_file():
        block_plan_obj = _read_json(block_plan_path)
        block_plan = list(block_plan_obj.get("block_plan", [])) if isinstance(block_plan_obj.get("block_plan", []), list) else []
    if cut_summary_path is not None and cut_summary_path.is_file():
        cut_summary_obj = _read_json(cut_summary_path)
        cut_summary = dict(cut_summary_obj)

    anchor_preview = meta.get("anchor_separator_shadow_anchor_preview", [])
    if not isinstance(anchor_preview, list) or not anchor_preview:
        anchor_preview = list(anchor_map[:8])
    block_plan_preview = meta.get("anchor_separator_shadow_block_plan_preview", [])
    if not isinstance(block_plan_preview, list) or not block_plan_preview:
        block_plan_preview = list(block_plan[:8])

    block_kind_counts: Dict[str, int] = {}
    for row in block_plan:
        kind = str(row.get("kind", "unknown"))
        block_kind_counts[kind] = int(block_kind_counts.get(kind, 0) + 1)

    return {
        "enabled": int(meta.get("anchor_separator_shadow_enabled", 0) or 0),
        "anchor_community_count": _as_int(
            meta.get("anchor_separator_shadow_anchor_community_count"),
            _as_int(cut_summary.get("anchor_community_count"), 0),
        ),
        "block_count": _as_int(
            meta.get("anchor_separator_shadow_block_count"),
            _as_int(cut_summary.get("block_count"), 0),
        ),
        "anchor_escape_count": _as_int(
            meta.get("anchor_separator_shadow_anchor_escape_count"),
            _as_int(cut_summary.get("anchor_escape_count"), 0),
        ),
        "cross_block_weak_edge_weight_ratio": _as_float(
            meta.get("anchor_separator_shadow_cross_block_weak_edge_weight_ratio"),
            _as_float(cut_summary.get("cross_block_weak_edge_weight_ratio"), 0.0),
        ),
        "anchor_local_span_p95": _as_int(cut_summary.get("anchor_local_span_p95"), 0),
        "anchor_preview": list(anchor_preview),
        "block_plan_preview": list(block_plan_preview),
        "anchor_map_path": "" if anchor_map_path is None else str(anchor_map_path),
        "block_plan_path": "" if block_plan_path is None else str(block_plan_path),
        "cut_summary_path": "" if cut_summary_path is None else str(cut_summary_path),
        "anchor_map": list(anchor_map),
        "block_plan": list(block_plan),
        "cut_summary": dict(cut_summary),
        "block_kind_counts": dict(block_kind_counts),
    }


def _read_u64_array(blob: bytes, offset: int, count: int) -> Tuple[List[int], int]:
    n = int(count)
    if n <= 0:
        return [], offset
    size = n * 8
    vals = list(struct.unpack_from("<" + "Q" * n, blob, offset))
    return vals, offset + size


def _read_u32_array(blob: bytes, offset: int, count: int) -> Tuple[List[int], int]:
    n = int(count)
    if n <= 0:
        return [], offset
    size = n * 4
    vals = list(struct.unpack_from("<" + "I" * n, blob, offset))
    return vals, offset + size


def _fixed_bits_at(words: Sequence[int], idx: int, bits: int) -> int:
    if bits <= 0 or bits > 32:
        raise ValueError(f"invalid fixed bits={bits}")
    bit_pos = int(idx) * int(bits)
    word_idx = bit_pos >> 6
    shift = bit_pos & 63
    if word_idx >= len(words):
        raise IndexError(f"fixed_bits_at out of bounds idx={idx} word_idx={word_idx}")
    value = int(words[word_idx]) >> shift
    if shift + bits > 64:
        if word_idx + 1 >= len(words):
            raise IndexError(f"fixed_bits_at spill out of bounds idx={idx} word_idx={word_idx}")
        value |= int(words[word_idx + 1]) << (64 - shift)
    mask = 0xFFFFFFFF if bits >= 32 else ((1 << bits) - 1)
    return int(value & mask)


def _fixed_bits_at_bit_pos(words: Sequence[int], bit_pos: int, bits: int) -> int:
    if bits <= 0 or bits > 32:
        raise ValueError(f"invalid fixed bits={bits}")
    word_idx = int(bit_pos) >> 6
    shift = int(bit_pos) & 63
    if word_idx >= len(words):
        raise IndexError(f"fixed_bits_at_bit_pos out of bounds bit_pos={bit_pos}")
    value = int(words[word_idx]) >> shift
    if shift + bits > 64:
        if word_idx + 1 >= len(words):
            raise IndexError(f"fixed_bits_at_bit_pos spill out of bounds bit_pos={bit_pos}")
        value |= int(words[word_idx + 1]) << (64 - shift)
    mask = 0xFFFFFFFF if bits >= 32 else ((1 << bits) - 1)
    return int(value & mask)


def _ef_read_low(words: Sequence[int], l_bits: int, idx: int) -> int:
    if l_bits == 0:
        return 0
    bit_pos = int(idx) * int(l_bits)
    word_idx = bit_pos >> 6
    shift = bit_pos & 63
    if word_idx >= len(words):
        raise IndexError(f"ef_read_low out of bounds idx={idx}")
    value = int(words[word_idx]) >> shift
    if shift + l_bits > 64:
        if word_idx + 1 >= len(words):
            raise IndexError(f"ef_read_low spill out of bounds idx={idx}")
        value |= int(words[word_idx + 1]) << (64 - shift)
    mask = 0xFFFFFFFF if l_bits >= 32 else ((1 << l_bits) - 1)
    return int(value & mask)


def _ef_select1(high_words: Sequence[int], select_samples: Sequence[int], select_step: int, value_count: int, one_idx: int) -> int:
    if one_idx < 0 or one_idx >= value_count:
        raise IndexError(f"ef_select1 invalid one_idx={one_idx} value_count={value_count}")
    if select_step <= 0:
        raise ValueError("ef_select1 requires select_step > 0")
    sample_idx = one_idx // select_step
    rank = sample_idx * select_step
    pos = int(select_samples[sample_idx])
    if rank == one_idx:
        return pos

    remain = one_idx - rank
    scan_pos = pos + 1
    word_idx = scan_pos >> 6
    offset = scan_pos & 63
    if word_idx >= len(high_words):
        raise IndexError(f"ef_select1 scan out of bounds one_idx={one_idx}")
    word = int(high_words[word_idx])
    if offset > 0:
        word &= (~0 << offset) & 0xFFFFFFFFFFFFFFFF

    while True:
        pop = int(word.bit_count())
        if pop >= remain:
            tmp = int(word)
            for _ in range(remain - 1):
                tmp &= tmp - 1
            bit = (tmp & -tmp).bit_length() - 1
            return int(word_idx * 64 + bit)
        remain -= pop
        word_idx += 1
        if word_idx >= len(high_words):
            raise IndexError(f"ef_select1 exhausted high words one_idx={one_idx}")
        word = int(high_words[word_idx])


def _ef_value_at(low_words: Sequence[int], high_words: Sequence[int], select_samples: Sequence[int], l_bits: int, select_step: int, value_count: int, idx: int) -> int:
    high_pos = _ef_select1(high_words, select_samples, select_step, value_count, idx)
    if high_pos < idx:
        raise ValueError(f"ef_value_at invalid high_pos={high_pos} idx={idx}")
    high = high_pos - idx
    low = _ef_read_low(low_words, l_bits, idx)
    return int((high << int(l_bits)) | low)


def load_v7_mapping(index_path: Path) -> Dict[int, Dict[str, int]]:
    blob = index_path.read_bytes()
    header_size = struct.calcsize(V7_HEADER_FMT)
    extra_size = struct.calcsize(V7_EXTRA_FMT)
    if len(blob) < header_size + extra_size:
        raise ValueError(f"index too small: {index_path}")

    header = struct.unpack_from(V7_HEADER_FMT, blob, 0)
    magic = header[0]
    version = int(header[1])
    pre_count = int(header[2])
    edges_total = int(header[3])
    if magic != MAGIC:
        raise ValueError(f"bad magic in {index_path}")
    if version != 7:
        raise ValueError(f"expected v7 index, got version={version} path={index_path}")

    extra = struct.unpack_from(V7_EXTRA_FMT, blob, header_size)
    offset = header_size + extra_size

    key_max = int(extra[0])
    key_ef_l = int(extra[1])
    key_ef_low_word_count = int(extra[2])
    key_ef_high_word_count = int(extra[3])
    key_ef_select_step = int(extra[4])
    key_ef_select_count = int(extra[5])
    run_count = int(extra[6])
    run_rank_bits = int(extra[7])
    run_rank_word_count = int(extra[8])
    run_ef_l = int(extra[9])
    run_ef_low_word_count = int(extra[10])
    run_ef_high_word_count = int(extra[11])
    run_ef_select_step = int(extra[12])
    run_ef_select_count = int(extra[13])
    len_block_size = int(extra[14])
    len_block_count = int(extra[15])
    len_block_base_bits = int(extra[16])
    len_block_base_word_count = int(extra[17])
    len_block_word_offset_bits = int(extra[18])
    len_block_word_offset_word_count = int(extra[19])
    len_block_mode_bits = int(extra[20])
    len_block_mode_word_count = int(extra[21])
    len_block_arg_bits = int(extra[22])
    len_block_arg_word_count = int(extra[23])
    len_payload_word_count = int(extra[24])

    key_ef_low_words, offset = _read_u64_array(blob, offset, key_ef_low_word_count)
    key_ef_high_words, offset = _read_u64_array(blob, offset, key_ef_high_word_count)
    key_ef_select_samples, offset = _read_u32_array(blob, offset, key_ef_select_count)
    sid_run_rank_words, offset = _read_u64_array(blob, offset, run_rank_word_count)
    run_ef_low_words, offset = _read_u64_array(blob, offset, run_ef_low_word_count)
    run_ef_high_words, offset = _read_u64_array(blob, offset, run_ef_high_word_count)
    run_ef_select_samples, offset = _read_u32_array(blob, offset, run_ef_select_count)
    len_block_base_words, offset = _read_u64_array(blob, offset, len_block_base_word_count)
    len_block_word_offset_words, offset = _read_u64_array(blob, offset, len_block_word_offset_word_count)
    len_block_mode_words, offset = _read_u64_array(blob, offset, len_block_mode_word_count)
    len_block_arg_words, offset = _read_u64_array(blob, offset, len_block_arg_word_count)
    len_payload_words, offset = _read_u64_array(blob, offset, len_payload_word_count)

    if offset != len(blob):
        raise ValueError(f"unexpected trailing bytes in {index_path}: offset={offset} size={len(blob)}")

    block_base_prefix = [_fixed_bits_at(len_block_base_words, i, len_block_base_bits) for i in range(len_block_count)]
    block_word_offset = [_fixed_bits_at(len_block_word_offset_words, i, len_block_word_offset_bits) for i in range(len_block_count)]
    block_mode = [_fixed_bits_at(len_block_mode_words, i, len_block_mode_bits) for i in range(len_block_count)]
    block_arg = [_fixed_bits_at(len_block_arg_words, i, len_block_arg_bits) for i in range(len_block_count)]

    def key_at_sid(sid: int) -> int:
        return _ef_value_at(
            key_ef_low_words,
            key_ef_high_words,
            key_ef_select_samples,
            key_ef_l,
            key_ef_select_step,
            pre_count,
            sid,
        )

    def run_end_at(run_idx: int) -> int:
        return _ef_value_at(
            run_ef_low_words,
            run_ef_high_words,
            run_ef_select_samples,
            run_ef_l,
            run_ef_select_step,
            run_count,
            run_idx,
        )

    def rank_at_sid(sid: int) -> int:
        lo = 0
        hi = run_count
        while lo < hi:
            mid = lo + ((hi - lo) >> 1)
            run_end = run_end_at(mid)
            if sid < run_end:
                hi = mid
            else:
                lo = mid + 1
        if lo >= run_count:
            raise IndexError(f"sid out of runs sid={sid}")
        run_end = run_end_at(lo)
        run_start = 0 if lo == 0 else run_end_at(lo - 1)
        base_rank = _fixed_bits_at(sid_run_rank_words, lo, run_rank_bits)
        return int(base_rank + sid - run_start)

    def lpbl_len_at_rank(rank: int) -> int:
        if len_block_size <= 0:
            raise ValueError("invalid len_block_size")
        block = rank // len_block_size
        block_start = block * len_block_size
        block_len = min(len_block_size, pre_count - block_start)
        off = rank - block_start
        mode = block_mode[block]
        arg = block_arg[block]
        word_off = block_word_offset[block]
        if mode == 1:
            return 1
        if mode == 0:
            return _fixed_bits_at_bit_pos(len_payload_words, word_off * 64 + off * arg, arg)
        if mode == 2:
            bitmap_words = (block_len + 63) // 64
            bitmap_idx = word_off + (off >> 6)
            bitmap_word = len_payload_words[bitmap_idx]
            bit = off & 63
            if ((bitmap_word >> bit) & 1) == 0:
                return 1
            exc_idx = 0
            for wi in range(off >> 6):
                exc_idx += int(len_payload_words[word_off + wi]).bit_count()
            mask = 0 if bit == 0 else ((1 << bit) - 1)
            exc_idx += int(bitmap_word & mask).bit_count()
            return _fixed_bits_at_bit_pos(len_payload_words, (word_off + bitmap_words) * 64 + exc_idx * arg, arg)
        raise ValueError(f"unsupported lpbl mode={mode}")

    lens = [lpbl_len_at_rank(rank) for rank in range(pre_count)]
    bases: List[int] = []
    cur = 0
    for ln in lens:
        bases.append(cur)
        cur += int(ln)
    if cur != edges_total:
        raise ValueError(f"terminal edge total mismatch path={index_path} got={cur} expect={edges_total}")

    mapping: Dict[int, Dict[str, int]] = {}
    for sid in range(pre_count):
        pre = key_at_sid(sid)
        rank = rank_at_sid(sid)
        mapping[int(pre)] = {
            "sid": int(sid),
            "rank": int(rank),
            "base": int(bases[rank]),
            "len": int(lens[rank]),
        }

    if mapping and max(mapping) != key_max:
        raise ValueError(f"key_max mismatch path={index_path} decoded={max(mapping)} expect={key_max}")
    return mapping


def load_profile_rows(profile_path: Path, *, window_id: Optional[int] = None, post_local: Optional[int] = None) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    with profile_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                if window_id is not None and int(row.get("window_id", "-1")) != int(window_id):
                    continue
                if post_local is not None and int(row.get("post_local", "-1")) != int(post_local):
                    continue
            except Exception:
                continue
            out.append(dict(row))
    return out


def summarize_band_metrics(rows: Sequence[Dict[str, str]], mapping: Dict[int, Dict[str, int]], *, bands: Sequence[Tuple[int, int]]) -> Dict[Tuple[int, int], Dict[str, int]]:
    tmp: Dict[Tuple[int, int], Dict[str, object]] = {
        tuple(band): {"rows": 0, "weighted_count": 0, "pres": set(), "lines": set()}
        for band in bands
    }
    for row in rows:
        try:
            pre = int(row["pre_global"])
        except Exception:
            continue
        rec = mapping.get(pre)
        if rec is None:
            continue
        rank = int(rec["rank"])
        band_key = None
        for band in bands:
            lo, hi = int(band[0]), int(band[1])
            if lo <= rank < hi:
                band_key = (lo, hi)
                break
        if band_key is None:
            continue
        entry = tmp[band_key]
        entry["rows"] = int(entry["rows"]) + 1
        entry["weighted_count"] = int(entry["weighted_count"]) + int(row.get("count", "1") or 1)
        entry["pres"].add(pre)
        try:
            entry["lines"].add(int(row.get("line_id", "-1")))
        except Exception:
            pass

    out: Dict[Tuple[int, int], Dict[str, int]] = {}
    for band, values in tmp.items():
        out[band] = {
            "rows": int(values["rows"]),
            "weighted_count": int(values["weighted_count"]),
            "unique_pres": int(len(values["pres"])),
            "unique_lines": int(len(values["lines"])),
        }
    return out


def select_target_profile_row(rows: Sequence[Dict[str, str]]) -> Optional[Dict[str, str]]:
    if not rows:
        return None
    ranked = sorted(
        rows,
        key=lambda row: (
            _as_int(row.get("local_age_rank"), 1 << 30),
            -_as_int(row.get("younger_ahead_depth"), 0),
            _as_int(row.get("retire_seq"), 1 << 30),
            _as_int(row.get("post_local"), 1 << 30),
            _as_int(row.get("pre_global"), 1 << 30),
        ),
    )
    return dict(ranked[0])


def _aggregate_profile_rows(rows: Sequence[Dict[str, str]]) -> Dict[int, Dict[str, object]]:
    out: Dict[int, Dict[str, object]] = {}
    for row in rows:
        pre = _as_int(row.get("pre_global"), -1)
        if pre < 0:
            continue
        entry = out.setdefault(
            pre,
            {
                "profile_occurrences": 0,
                "profile_weighted_count": 0,
                "line_ids": set(),
                "min_local_age_rank": None,
                "min_ordered_rank": None,
                "max_younger_ahead_depth": None,
            },
        )
        entry["profile_occurrences"] = int(entry["profile_occurrences"]) + 1
        entry["profile_weighted_count"] = int(entry["profile_weighted_count"]) + _as_int(row.get("count"), 1)
        line_id = _as_int(row.get("line_id"), -1)
        if line_id >= 0:
            entry["line_ids"].add(line_id)

        local_age_rank = _as_int(row.get("local_age_rank"), 1 << 30)
        ordered_rank = _as_int(row.get("ordered_rank"), 1 << 30)
        younger_ahead_depth = _as_int(row.get("younger_ahead_depth"), 0)

        cur_min_local = entry["min_local_age_rank"]
        if cur_min_local is None or local_age_rank < int(cur_min_local):
            entry["min_local_age_rank"] = local_age_rank

        cur_min_ordered = entry["min_ordered_rank"]
        if cur_min_ordered is None or ordered_rank < int(cur_min_ordered):
            entry["min_ordered_rank"] = ordered_rank

        cur_max_yad = entry["max_younger_ahead_depth"]
        if cur_max_yad is None or younger_ahead_depth > int(cur_max_yad):
            entry["max_younger_ahead_depth"] = younger_ahead_depth
    return out


def build_target_neighborhood_rows(
    *,
    target_pre: int,
    rows: Sequence[Dict[str, str]],
    mapping1: Dict[int, Dict[str, int]],
    mapping2: Dict[int, Dict[str, int]],
    radius: int,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    target1 = mapping1.get(int(target_pre))
    target2 = mapping2.get(int(target_pre))
    if target1 is None or target2 is None:
        return [], {
            "target_pre": int(target_pre),
            "radius": int(radius),
            "missing_target": True,
        }

    profile_by_pre = _aggregate_profile_rows(rows)
    target_line_ids = sorted(int(x) for x in profile_by_pre.get(int(target_pre), {}).get("line_ids", set()))
    union_pres = set()
    for pre, rec in mapping1.items():
        if abs(int(rec["rank"]) - int(target1["rank"])) <= int(radius):
            union_pres.add(int(pre))
    for pre, rec in mapping2.items():
        if abs(int(rec["rank"]) - int(target2["rank"])) <= int(radius):
            union_pres.add(int(pre))

    neighborhood_rows: List[Dict[str, object]] = []
    profile_pres_in_union = 0
    profile_rows_in_union = 0
    profile_weighted_count_in_union = 0
    same_line_pres_in_union = 0
    moved_pres_count = 0
    large_shift_64_count = 0
    large_shift_128_count = 0

    for pre in sorted(union_pres):
        rec1 = mapping1.get(pre)
        rec2 = mapping2.get(pre)
        prof = profile_by_pre.get(pre, {})
        line_ids = sorted(int(x) for x in prof.get("line_ids", set()))
        same_line = 1 if target_line_ids and set(line_ids) & set(target_line_ids) else 0
        rank_delta = ""
        if rec1 is not None and rec2 is not None:
            rank_delta = int(rec2["rank"]) - int(rec1["rank"])
            if rank_delta != 0:
                moved_pres_count += 1
            if abs(int(rank_delta)) >= 64:
                large_shift_64_count += 1
            if abs(int(rank_delta)) >= 128:
                large_shift_128_count += 1

        profile_occurrences = int(prof.get("profile_occurrences", 0) or 0)
        profile_weighted_count = int(prof.get("profile_weighted_count", 0) or 0)
        if profile_occurrences > 0:
            profile_pres_in_union += 1
            profile_rows_in_union += profile_occurrences
            profile_weighted_count_in_union += profile_weighted_count
        if same_line:
            same_line_pres_in_union += 1

        neighborhood_rows.append(
            {
                "pre_global": pre,
                "in_profile_window": 1 if profile_occurrences > 0 else 0,
                "profile_occurrences": profile_occurrences,
                "profile_weighted_count": profile_weighted_count,
                "profile_line_ids": ";".join(str(x) for x in line_ids),
                "same_line_as_target": same_line,
                "profile_min_local_age_rank": prof.get("min_local_age_rank", ""),
                "profile_min_ordered_rank": prof.get("min_ordered_rank", ""),
                "profile_max_younger_ahead_depth": prof.get("max_younger_ahead_depth", ""),
                "p3c1_rank": "" if rec1 is None else int(rec1["rank"]),
                "p3c1_rank_offset_to_target": "" if rec1 is None else int(rec1["rank"]) - int(target1["rank"]),
                "p3c1_base": "" if rec1 is None else int(rec1["base"]),
                "p3c1_len": "" if rec1 is None else int(rec1["len"]),
                "p3c2a_rank": "" if rec2 is None else int(rec2["rank"]),
                "p3c2a_rank_offset_to_target": "" if rec2 is None else int(rec2["rank"]) - int(target2["rank"]),
                "p3c2a_base": "" if rec2 is None else int(rec2["base"]),
                "p3c2a_len": "" if rec2 is None else int(rec2["len"]),
                "rank_delta_p3c2a_minus_p3c1": rank_delta,
            }
        )

    neighborhood_rows.sort(
        key=lambda row: (
            abs(_as_int(row.get("p3c1_rank_offset_to_target"), 1 << 30)),
            abs(_as_int(row.get("p3c2a_rank_offset_to_target"), 1 << 30)),
            _as_int(row.get("pre_global"), 1 << 30),
        )
    )

    summary = {
        "target_pre": int(target_pre),
        "radius": int(radius),
        "p3c1_target_rank": int(target1["rank"]),
        "p3c2a_target_rank": int(target2["rank"]),
        "union_pre_count": len(neighborhood_rows),
        "profile_pres_in_union": int(profile_pres_in_union),
        "profile_rows_in_union": int(profile_rows_in_union),
        "profile_weighted_count_in_union": int(profile_weighted_count_in_union),
        "same_line_pres_in_union": int(same_line_pres_in_union),
        "moved_pres_count": int(moved_pres_count),
        "large_shift_abs_ge_64_count": int(large_shift_64_count),
        "large_shift_abs_ge_128_count": int(large_shift_128_count),
        "target_line_ids": target_line_ids,
    }
    return neighborhood_rows, summary


def _iter_meta_paths(root: Path) -> Iterable[Path]:
    for path in sorted(root.glob("pe*/core*.gcssplp.meta.json")):
        if path.is_file():
            yield path


def _load_global_meta_compare(p3c1_dir: Path, p3c2a_dir: Path) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    sum_keys = [
        "fat_tail_guard_trigger_total",
        "fat_tail_guard_reason_share_zero_total",
        "fat_tail_guard_reason_risk_zero_total",
        "fat_tail_guard_reason_fill_below_threshold_total",
        "fat_tail_guard_reason_seg_len_below_threshold_total",
        "lines_with_multi_pre",
        "physical_line_count",
        "index_bytes",
    ]
    sums = {
        "p3c1": {k: 0 for k in sum_keys},
        "p3c2a": {k: 0 for k in sum_keys},
    }
    anchor_shadow_core_count = 0
    anchor_shadow_escape_sum = 0
    anchor_shadow_cross_block_ratio_sum = 0.0
    anchor_shadow_cross_block_ratio_count = 0
    anchor_shadow_local_span_p95_max = 0
    for meta1 in _iter_meta_paths(p3c1_dir):
        rel = meta1.relative_to(p3c1_dir)
        meta2 = p3c2a_dir / rel
        if not meta2.is_file():
            continue
        obj1 = _read_json(meta1)
        obj2 = _read_json(meta2)
        shadow1 = load_anchor_shadow_bundle(meta1, obj1)
        shadow2 = load_anchor_shadow_bundle(meta2, obj2)
        row = {
            "pe": int(obj1.get("pe", -1)),
            "core": int(obj1.get("core", -1)),
        }
        for key in sum_keys:
            v1 = int(obj1.get(key, 0) or 0)
            v2 = int(obj2.get(key, 0) or 0)
            row[f"p3c1_{key}"] = v1
            row[f"p3c2a_{key}"] = v2
            row[f"delta_{key}"] = v2 - v1
            sums["p3c1"][key] += v1
            sums["p3c2a"][key] += v2
        shadow_scalar_keys = (
            "enabled",
            "anchor_community_count",
            "block_count",
            "anchor_escape_count",
            "anchor_local_span_p95",
        )
        for key in shadow_scalar_keys:
            v1 = _as_int(shadow1.get(key), 0)
            v2 = _as_int(shadow2.get(key), 0)
            row[f"p3c1_anchor_separator_shadow_{key}"] = v1
            row[f"p3c2a_anchor_separator_shadow_{key}"] = v2
            row[f"delta_anchor_separator_shadow_{key}"] = v2 - v1

        ratio1 = _as_float(shadow1.get("cross_block_weak_edge_weight_ratio"), 0.0)
        ratio2 = _as_float(shadow2.get("cross_block_weak_edge_weight_ratio"), 0.0)
        row["p3c1_anchor_separator_shadow_cross_block_weak_edge_weight_ratio"] = ratio1
        row["p3c2a_anchor_separator_shadow_cross_block_weak_edge_weight_ratio"] = ratio2
        row["delta_anchor_separator_shadow_cross_block_weak_edge_weight_ratio"] = ratio2 - ratio1

        row["p3c1_anchor_separator_shadow_anchor_map_path"] = str(shadow1.get("anchor_map_path", ""))
        row["p3c1_anchor_separator_shadow_block_plan_path"] = str(shadow1.get("block_plan_path", ""))
        row["p3c1_anchor_separator_shadow_cut_summary_path"] = str(shadow1.get("cut_summary_path", ""))
        row["p3c2a_anchor_separator_shadow_anchor_map_path"] = str(shadow2.get("anchor_map_path", ""))
        row["p3c2a_anchor_separator_shadow_block_plan_path"] = str(shadow2.get("block_plan_path", ""))
        row["p3c2a_anchor_separator_shadow_cut_summary_path"] = str(shadow2.get("cut_summary_path", ""))

        if _as_int(shadow1.get("enabled"), 0) > 0 or _as_int(shadow2.get("enabled"), 0) > 0:
            anchor_shadow_core_count += 1
        if _as_int(shadow2.get("enabled"), 0) > 0:
            anchor_shadow_escape_sum += _as_int(shadow2.get("anchor_escape_count"), 0)
            anchor_shadow_cross_block_ratio_sum += ratio2
            anchor_shadow_cross_block_ratio_count += 1
            anchor_shadow_local_span_p95_max = max(
                int(anchor_shadow_local_span_p95_max),
                _as_int(shadow2.get("anchor_local_span_p95"), 0),
            )
        rows.append(row)
    summary = {
        "core_count": len(rows),
        "sums": sums,
        "delta": {k: int(sums["p3c2a"][k] - sums["p3c1"][k]) for k in sum_keys},
        "anchor_shadow_core_count": int(anchor_shadow_core_count),
        "anchor_shadow_escape_sum": int(anchor_shadow_escape_sum),
        "anchor_shadow_avg_cross_block_weak_edge_weight_ratio": (
            float(anchor_shadow_cross_block_ratio_sum) / float(anchor_shadow_cross_block_ratio_count)
            if anchor_shadow_cross_block_ratio_count > 0
            else 0.0
        ),
        "anchor_shadow_max_anchor_local_span_p95": int(anchor_shadow_local_span_p95_max),
    }
    return rows, summary


def _write_tsv(path: Path, rows: Sequence[Dict[str, object]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _band_to_label(band: Tuple[int, int]) -> str:
    return f"{int(band[0])}-{int(band[1])}"


def _choose_top_abnormal_cores(global_meta_rows: Sequence[Dict[str, object]], top_count: int) -> List[Tuple[int, int]]:
    use_fat_tail_delta = any(_as_int(row.get("delta_fat_tail_guard_trigger_total"), 0) != 0 for row in global_meta_rows)
    if use_fat_tail_delta:
        ranked = sorted(
            global_meta_rows,
            key=lambda row: (
                -_as_int(row.get("delta_fat_tail_guard_trigger_total"), 0),
                _as_int(row.get("pe"), 1 << 30),
                _as_int(row.get("core"), 1 << 30),
            ),
        )
    else:
        ranked = sorted(
            global_meta_rows,
            key=lambda row: (
                -_as_int(row.get("p3c2a_anchor_separator_shadow_anchor_escape_count"), 0),
                -_as_float(row.get("p3c2a_anchor_separator_shadow_cross_block_weak_edge_weight_ratio"), 0.0),
                -_as_int(row.get("p3c2a_anchor_separator_shadow_anchor_local_span_p95"), 0),
                -_as_int(row.get("p3c2a_anchor_separator_shadow_block_count"), 0),
                _as_int(row.get("pe"), 1 << 30),
                _as_int(row.get("core"), 1 << 30),
            ),
        )
    out: List[Tuple[int, int]] = []
    for row in ranked[: max(int(top_count), 0)]:
        out.append((_as_int(row.get("pe"), -1), _as_int(row.get("core"), -1)))
    return out


def run_analysis(
    *,
    p3c1_dir: Path,
    p3c2a_dir: Path,
    pe: int,
    core: int,
    window_id: int,
    post_local: int,
    target_pre: int,
    output_dir: Path,
    bands: Sequence[Tuple[int, int]],
    neighborhood_radius: int,
    top_core_count: int,
) -> Dict[str, object]:
    meta1_path = p3c1_dir / f"pe{pe:02d}" / f"core{core:02d}.gcssplp.meta.json"
    meta2_path = p3c2a_dir / f"pe{pe:02d}" / f"core{core:02d}.gcssplp.meta.json"
    meta1 = _read_json(meta1_path)
    meta2 = _read_json(meta2_path)
    shadow1 = load_anchor_shadow_bundle(meta1_path, meta1)
    shadow2 = load_anchor_shadow_bundle(meta2_path, meta2)
    meta_preview_overlap = compute_meta_preview_overlap(meta1, meta2)
    mapping1 = load_v7_mapping(p3c1_dir / f"pe{pe:02d}" / f"core{core:02d}.gcssplp.idx.bin")
    mapping2 = load_v7_mapping(p3c2a_dir / f"pe{pe:02d}" / f"core{core:02d}.gcssplp.idx.bin")
    profile_path = Path(str(meta1["hol_profile_path"]))

    rows = load_profile_rows(profile_path, window_id=window_id, post_local=post_local)
    compare_rows: List[Dict[str, object]] = []
    for row in rows:
        try:
            pre = int(row["pre_global"])
        except Exception:
            continue
        rec1 = mapping1.get(pre)
        rec2 = mapping2.get(pre)
        compare_rows.append(
            {
                "pre_global": pre,
                "pre_rank": int(row.get("pre_rank", "0") or 0),
                "count": int(row.get("count", "0") or 0),
                "line_id": int(row.get("line_id", "0") or 0),
                "ordered_rank": int(row.get("ordered_rank", "0") or 0),
                "younger_ahead_depth": int(row.get("younger_ahead_depth", "0") or 0),
                "p3c1_rank": "" if rec1 is None else int(rec1["rank"]),
                "p3c1_base": "" if rec1 is None else int(rec1["base"]),
                "p3c1_len": "" if rec1 is None else int(rec1["len"]),
                "p3c2a_rank": "" if rec2 is None else int(rec2["rank"]),
                "p3c2a_base": "" if rec2 is None else int(rec2["base"]),
                "p3c2a_len": "" if rec2 is None else int(rec2["len"]),
                "rank_delta_p3c2a_minus_p3c1": ""
                if rec1 is None or rec2 is None
                else int(rec2["rank"]) - int(rec1["rank"]),
            }
        )
    compare_rows.sort(key=lambda x: (int(x["ordered_rank"]), int(x["pre_global"])))

    band_rows: List[Dict[str, object]] = []
    for artifact_name, mapping in (("p3c1", mapping1), ("p3c2a", mapping2)):
        summary = summarize_band_metrics(rows, mapping, bands=bands)
        for band in bands:
            values = summary[tuple(band)]
            band_rows.append(
                {
                    "artifact": artifact_name,
                    "band": _band_to_label(tuple(band)),
                    **values,
                }
            )

    target_summary = {
        "target_pre": int(target_pre),
        "window_id": int(window_id),
        "post_local": int(post_local),
        "target_rows_in_profile": [row for row in compare_rows if int(row["pre_global"]) == int(target_pre)],
        "p3c1": mapping1.get(int(target_pre), {}),
        "p3c2a": mapping2.get(int(target_pre), {}),
        "meta_preview_overlap": meta_preview_overlap,
        "p3c1_anchor_shadow": shadow1,
        "p3c2a_anchor_shadow": shadow2,
    }
    if mapping1.get(int(target_pre)) and mapping2.get(int(target_pre)):
        target_summary["rank_delta_p3c2a_minus_p3c1"] = int(mapping2[int(target_pre)]["rank"]) - int(mapping1[int(target_pre)]["rank"])

    global_meta_rows, global_meta_summary = _load_global_meta_compare(p3c1_dir, p3c2a_dir)
    neighborhood_rows, neighborhood_summary = build_target_neighborhood_rows(
        target_pre=int(target_pre),
        rows=rows,
        mapping1=mapping1,
        mapping2=mapping2,
        radius=int(neighborhood_radius),
    )

    top_core_rows: List[Dict[str, object]] = []
    top_core_dir = output_dir / "top_abnormal_cores"
    for abnormal_pe, abnormal_core in _choose_top_abnormal_cores(global_meta_rows, top_core_count):
        abnormal_meta1_path = p3c1_dir / f"pe{abnormal_pe:02d}" / f"core{abnormal_core:02d}.gcssplp.meta.json"
        abnormal_meta2_path = p3c2a_dir / f"pe{abnormal_pe:02d}" / f"core{abnormal_core:02d}.gcssplp.meta.json"
        abnormal_meta1 = _read_json(abnormal_meta1_path)
        abnormal_meta2 = _read_json(abnormal_meta2_path)
        abnormal_shadow1 = load_anchor_shadow_bundle(abnormal_meta1_path, abnormal_meta1)
        abnormal_shadow2 = load_anchor_shadow_bundle(abnormal_meta2_path, abnormal_meta2)
        abnormal_mapping1 = load_v7_mapping(p3c1_dir / f"pe{abnormal_pe:02d}" / f"core{abnormal_core:02d}.gcssplp.idx.bin")
        abnormal_mapping2 = load_v7_mapping(p3c2a_dir / f"pe{abnormal_pe:02d}" / f"core{abnormal_core:02d}.gcssplp.idx.bin")
        abnormal_preview_overlap = compute_meta_preview_overlap(abnormal_meta1, abnormal_meta2)
        abnormal_rows = load_profile_rows(
            Path(str(abnormal_meta1["hol_profile_path"])),
            window_id=window_id,
            post_local=None,
        )
        target_row = select_target_profile_row(abnormal_rows)
        if target_row is None:
            continue
        abnormal_target_pre = _as_int(target_row.get("pre_global"), -1)
        abnormal_neighborhood_rows, abnormal_neighborhood_summary = build_target_neighborhood_rows(
            target_pre=abnormal_target_pre,
            rows=abnormal_rows,
            mapping1=abnormal_mapping1,
            mapping2=abnormal_mapping2,
            radius=int(neighborhood_radius),
        )
        _write_tsv(
            top_core_dir / f"pe{abnormal_pe:02d}_core{abnormal_core:02d}_target_pre{abnormal_target_pre}_neighborhood.tsv",
            abnormal_neighborhood_rows,
            [
                "pre_global",
                "in_profile_window",
                "profile_occurrences",
                "profile_weighted_count",
                "profile_line_ids",
                "same_line_as_target",
                "profile_min_local_age_rank",
                "profile_min_ordered_rank",
                "profile_max_younger_ahead_depth",
                "p3c1_rank",
                "p3c1_rank_offset_to_target",
                "p3c1_base",
                "p3c1_len",
                "p3c2a_rank",
                "p3c2a_rank_offset_to_target",
                "p3c2a_base",
                "p3c2a_len",
                "rank_delta_p3c2a_minus_p3c1",
            ],
        )
        core_delta = next(
            (
                row
                for row in global_meta_rows
                if _as_int(row.get("pe"), -1) == abnormal_pe and _as_int(row.get("core"), -1) == abnormal_core
            ),
            {},
        )
        top_core_rows.append(
            {
                "pe": abnormal_pe,
                "core": abnormal_core,
                "target_pre": abnormal_target_pre,
                "target_post_local": _as_int(target_row.get("post_local"), -1),
                "target_local_age_rank": _as_int(target_row.get("local_age_rank"), -1),
                "target_retire_seq": _as_int(target_row.get("retire_seq"), -1),
                "target_ordered_rank": _as_int(target_row.get("ordered_rank"), -1),
                "target_younger_ahead_depth": _as_int(target_row.get("younger_ahead_depth"), -1),
                "p3c1_target_rank": abnormal_mapping1.get(abnormal_target_pre, {}).get("rank", ""),
                "p3c2a_target_rank": abnormal_mapping2.get(abnormal_target_pre, {}).get("rank", ""),
                "rank_delta_p3c2a_minus_p3c1": ""
                if abnormal_target_pre not in abnormal_mapping1 or abnormal_target_pre not in abnormal_mapping2
                else int(abnormal_mapping2[abnormal_target_pre]["rank"]) - int(abnormal_mapping1[abnormal_target_pre]["rank"]),
                "delta_fat_tail_guard_trigger_total": _as_int(core_delta.get("delta_fat_tail_guard_trigger_total"), 0),
                "delta_lines_with_multi_pre": _as_int(core_delta.get("delta_lines_with_multi_pre"), 0),
                "delta_index_bytes": _as_int(core_delta.get("delta_index_bytes"), 0),
                "neighborhood_union_pre_count": _as_int(abnormal_neighborhood_summary.get("union_pre_count"), 0),
                "neighborhood_profile_pres_in_union": _as_int(abnormal_neighborhood_summary.get("profile_pres_in_union"), 0),
                "neighborhood_same_line_pres_in_union": _as_int(abnormal_neighborhood_summary.get("same_line_pres_in_union"), 0),
                "neighborhood_moved_pres_count": _as_int(abnormal_neighborhood_summary.get("moved_pres_count"), 0),
                "neighborhood_large_shift_abs_ge_64_count": _as_int(abnormal_neighborhood_summary.get("large_shift_abs_ge_64_count"), 0),
                "neighborhood_large_shift_abs_ge_128_count": _as_int(abnormal_neighborhood_summary.get("large_shift_abs_ge_128_count"), 0),
                "target_preview_overlap_count": _as_int(abnormal_preview_overlap.get("target_overlap_count"), 0),
                "neighbor_pair_overlap_count": _as_int(abnormal_preview_overlap.get("neighbor_pair_overlap_count"), 0),
                "p3c1_anchor_separator_shadow_enabled": _as_int(abnormal_shadow1.get("enabled"), 0),
                "p3c2a_anchor_separator_shadow_enabled": _as_int(abnormal_shadow2.get("enabled"), 0),
                "p3c1_anchor_separator_shadow_anchor_community_count": _as_int(abnormal_shadow1.get("anchor_community_count"), 0),
                "p3c2a_anchor_separator_shadow_anchor_community_count": _as_int(abnormal_shadow2.get("anchor_community_count"), 0),
                "p3c1_anchor_separator_shadow_block_count": _as_int(abnormal_shadow1.get("block_count"), 0),
                "p3c2a_anchor_separator_shadow_block_count": _as_int(abnormal_shadow2.get("block_count"), 0),
                "p3c1_anchor_separator_shadow_anchor_escape_count": _as_int(abnormal_shadow1.get("anchor_escape_count"), 0),
                "p3c2a_anchor_separator_shadow_anchor_escape_count": _as_int(abnormal_shadow2.get("anchor_escape_count"), 0),
                "p3c1_anchor_separator_shadow_anchor_local_span_p95": _as_int(abnormal_shadow1.get("anchor_local_span_p95"), 0),
                "p3c2a_anchor_separator_shadow_anchor_local_span_p95": _as_int(abnormal_shadow2.get("anchor_local_span_p95"), 0),
                "p3c1_anchor_separator_shadow_cross_block_weak_edge_weight_ratio": _as_float(abnormal_shadow1.get("cross_block_weak_edge_weight_ratio"), 0.0),
                "p3c2a_anchor_separator_shadow_cross_block_weak_edge_weight_ratio": _as_float(abnormal_shadow2.get("cross_block_weak_edge_weight_ratio"), 0.0),
                "p3c2a_anchor_separator_shadow_anchor_map_path": str(abnormal_shadow2.get("anchor_map_path", "")),
                "p3c2a_anchor_separator_shadow_block_plan_path": str(abnormal_shadow2.get("block_plan_path", "")),
                "p3c2a_anchor_separator_shadow_cut_summary_path": str(abnormal_shadow2.get("cut_summary_path", "")),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_tsv(
        output_dir / f"pe{pe:02d}_core{core:02d}_post{post_local}_window{window_id}_compare.tsv",
        compare_rows,
        [
            "pre_global",
            "pre_rank",
            "count",
            "line_id",
            "ordered_rank",
            "younger_ahead_depth",
            "p3c1_rank",
            "p3c1_base",
            "p3c1_len",
            "p3c2a_rank",
            "p3c2a_base",
            "p3c2a_len",
            "rank_delta_p3c2a_minus_p3c1",
        ],
    )
    _write_tsv(
        output_dir / f"pe{pe:02d}_core{core:02d}_post{post_local}_window{window_id}_band_summary.tsv",
        band_rows,
        ["artifact", "band", "rows", "weighted_count", "unique_pres", "unique_lines"],
    )
    _write_tsv(
        output_dir / f"pe{pe:02d}_core{core:02d}_target_pre{target_pre}_neighborhood.tsv",
        neighborhood_rows,
        [
            "pre_global",
            "in_profile_window",
            "profile_occurrences",
            "profile_weighted_count",
            "profile_line_ids",
            "same_line_as_target",
            "profile_min_local_age_rank",
            "profile_min_ordered_rank",
            "profile_max_younger_ahead_depth",
            "p3c1_rank",
            "p3c1_rank_offset_to_target",
            "p3c1_base",
            "p3c1_len",
            "p3c2a_rank",
            "p3c2a_rank_offset_to_target",
            "p3c2a_base",
            "p3c2a_len",
            "rank_delta_p3c2a_minus_p3c1",
        ],
    )
    _write_tsv(
        output_dir / "global_meta_compare.tsv",
        global_meta_rows,
        list(global_meta_rows[0].keys()) if global_meta_rows else ["pe", "core"],
    )
    _write_tsv(
        output_dir / "top_abnormal_core_summary.tsv",
        top_core_rows,
        list(top_core_rows[0].keys()) if top_core_rows else ["pe", "core", "target_pre"],
    )
    (output_dir / f"pe{pe:02d}_core{core:02d}_target_pre{target_pre}.json").write_text(
        json.dumps(
            {
                **target_summary,
                "neighborhood_summary": neighborhood_summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "global_meta_summary.json").write_text(
        json.dumps(global_meta_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "top_abnormal_core_summary.json").write_text(
        json.dumps(
            {
                "top_core_count": len(top_core_rows),
                "radius": int(neighborhood_radius),
                "cores": top_core_rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "compare_row_count": len(compare_rows),
        "band_row_count": len(band_rows),
        "neighborhood_row_count": len(neighborhood_rows),
        "top_abnormal_core_count": len(top_core_rows),
        "global_meta_core_count": len(global_meta_rows),
        "target_summary": target_summary,
        "neighborhood_summary": neighborhood_summary,
        "global_meta_summary": global_meta_summary,
        "output_dir": str(output_dir),
    }


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Static diff for P3-C1 vs P3-C2a GCSS-PLP artifacts")
    parser.add_argument("--p3c1-dir", type=Path, default=DEFAULT_P3C1_DIR)
    parser.add_argument("--p3c2a-dir", type=Path, default=DEFAULT_P3C2A_DIR)
    parser.add_argument("--baseline-dir", type=Path, default=None)
    parser.add_argument("--candidate-dir", type=Path, default=None)
    parser.add_argument("--pe", type=int, default=0)
    parser.add_argument("--core", type=int, default=0)
    parser.add_argument("--window-id", type=int, default=1)
    parser.add_argument("--post-local", type=int, default=0)
    parser.add_argument("--target-pre", type=int, default=3438)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--neighborhood-radius", type=int, default=DEFAULT_NEIGHBORHOOD_RADIUS)
    parser.add_argument("--top-core-count", type=int, default=DEFAULT_TOP_CORE_COUNT)
    args = parser.parse_args(argv)
    if args.baseline_dir is not None:
        args.p3c1_dir = Path(args.baseline_dir)
    if args.candidate_dir is not None:
        args.p3c2a_dir = Path(args.candidate_dir)
    return args


def main() -> int:
    args = _parse_args()
    result = run_analysis(
        p3c1_dir=args.p3c1_dir,
        p3c2a_dir=args.p3c2a_dir,
        pe=int(args.pe),
        core=int(args.core),
        window_id=int(args.window_id),
        post_local=int(args.post_local),
        target_pre=int(args.target_pre),
        output_dir=args.output_dir,
        bands=DEFAULT_BANDS,
        neighborhood_radius=int(args.neighborhood_radius),
        top_core_count=int(args.top_core_count),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
