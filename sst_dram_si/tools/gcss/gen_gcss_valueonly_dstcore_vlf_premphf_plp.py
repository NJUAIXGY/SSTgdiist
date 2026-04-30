#!/usr/bin/env python3
"""
Generate isolated GCSS-PLP artifacts from per-core BCSR files.

PLP = Profile-Guided Cross-Pre Line Packing.

Key contract:
- Exact `(pre_global, post_local) -> weight` mapping is preserved.
- Runtime still uses `lookup(pre) -> (base, len)` and `widx = base + pre_rank`.
- Only the physical order of pre segments inside values is changed.

Output layout:
  <out_dir>/peXX/coreYY.gcssplp.bin
  <out_dir>/peXX/coreYY.gcssplp.idx.bin
  <out_dir>/peXX/coreYY.gcssplp.meta.json
  <out_dir>/manifest.json

Implementation note:
- Arbitrary PLP reordering makes `slot_base[slot]` non-monotonic in MPHF slot order.
- `index_version=2` (direct EF over slot_base) is therefore invalid here.
- `index_version=1` remains available as the legacy slot-array fallback.
- `index_version=3` emits the compressed Rank+EF format: bitpacked `slot->rank` + EF `base_by_rank`.
- `index_version=4` emits bucket-block local-MPHF format: local pilots + bucket-local metadata.
- `index_version=5` preserves the v3 physical order and compresses `slot->rank` blockwise.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import struct
from collections import defaultdict
from pathlib import Path
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple

import gen_gcss_valueonly_dstcore_vlf_premphf as base


LINE_SIZE_BYTES = 64
VALUE_SIZE_BYTES = 4
VALUES_PER_LINE = LINE_SIZE_BYTES // VALUE_SIZE_BYTES
ORDER_SLOT = "slot_order"
ORDER_PRE = "pre_global_order"
ORDER_PROFILE = "profile_greedy"
ORDER_PROFILE_SIDRUN = "profile_greedy_sidrun_reg"
ORDER_HOL_PROFILE = "hol_profile_greedy"
ORDER_HOL_CONSTRAINED_V2 = "hol_profile_constrained_v2"
ORDER_HOL_CONSTRAINED_V2_1 = "hol_profile_constrained_v2_1"
ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V1 = "hol_profile_constrained_v2_1_rowband_stripe_v1"
ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V2 = "hol_profile_constrained_v2_1_rowband_stripe_v2"
ORDER_HOL_DUAL_GUARD_V3_SHADOW = "hol_profile_dual_guard_v3_shadow"
ORDER_HOL_DUAL_GUARD_V3 = "hol_profile_dual_guard_v3"
ORDER_HOL_DUAL_GUARD_V4 = "hol_profile_dual_guard_v4"
ORDER_OFFLINE_ANCHOR_SEPARATOR_V1 = "offline_anchor_separator_layout_v1"
ORDER_OFFLINE_ANCHOR_SEPARATOR_V1_SHADOW = "offline_anchor_separator_layout_v1_shadow"
ORDER_CHOICES = (
    ORDER_SLOT,
    ORDER_PRE,
    ORDER_PROFILE,
    ORDER_PROFILE_SIDRUN,
    ORDER_HOL_PROFILE,
    ORDER_HOL_CONSTRAINED_V2,
    ORDER_HOL_CONSTRAINED_V2_1,
    ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V1,
    ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V2,
    ORDER_HOL_DUAL_GUARD_V3_SHADOW,
    ORDER_HOL_DUAL_GUARD_V3,
    ORDER_HOL_DUAL_GUARD_V4,
    ORDER_OFFLINE_ANCHOR_SEPARATOR_V1,
    ORDER_OFFLINE_ANCHOR_SEPARATOR_V1_SHADOW,
)
INDEX_VERSION_V4 = 4
INDEX_VERSION_V5 = 5
INDEX_VERSION_V6 = 6
INDEX_VERSION_V7 = 7
V4_BLOCK_SPAN_DEFAULT = 64
V4_PILOT_BITS = 32
V4_PILOT_SEARCH_LIMIT = 1 << 20
V5_BLOCK_SIZE_DEFAULT = 64
V7_LEN_BLOCK_SIZE_DEFAULT = 64
SIDRUN_BLOCK_SIZE_DEFAULT = 2
HOL_HEAD_K_DEFAULT = 256
HOL_HEAD_BONUS_DEFAULT = 4
HOL_DUAL_GUARD_TARGET_TOP_M_DEFAULT = 32
HOL_DUAL_GUARD_NEIGHBOR_TOP_K_DEFAULT = 8
HOL_CONSTRAINED_NEIGHBOR_POOL_DEFAULT = 8
HOL_CONSTRAINED_FALLBACK_POOL_DEFAULT = 8
HOL_CONSTRAINED_FAT_TAIL_SEG_LEN_THRESHOLD_DEFAULT = VALUES_PER_LINE + (VALUES_PER_LINE // 2)
HOL_CONSTRAINED_FAT_TAIL_SEG_LEN_RELAXED_THRESHOLD_DEFAULT = VALUES_PER_LINE + (VALUES_PER_LINE // 4)
HOL_CONSTRAINED_FAT_TAIL_FILL_THRESHOLD_DEFAULT = VALUES_PER_LINE - 2
HOL_CONSTRAINED_FAT_TAIL_SPILL_THRESHOLD_DEFAULT = VALUES_PER_LINE // 4
ANCHOR_SEPARATOR_WEAK_TOP_K_DEFAULT = 8
ANCHOR_SEPARATOR_TRANS_EXPAND_TOP_N_DEFAULT = 4
ANCHOR_SEPARATOR_MERGE_JACCARD_DEFAULT = 0.5
ANCHOR_SEPARATOR_TINY_COMMUNITY_MEMBER_MAX_DEFAULT = 3
ANCHOR_SEPARATOR_TINY_COMMUNITY_LINE_MAX_DEFAULT = 3
ANCHOR_SEPARATOR_MICROBLOCK_VALUES_DEFAULT = 256
ANCHOR_SEPARATOR_MESOBLOCK_VALUES_DEFAULT = 1024
ANCHOR_SEPARATOR_MACROBLOCK_VALUES_DEFAULT = 4096
ANCHOR_SEPARATOR_ANCHOR_BAND_LINES_DEFAULT = 4
ANCHOR_SEPARATOR_SEPARATOR_SLACK_LINES_DEFAULT = 2
ROWBAND_STRIPE_BLOCK_VALUES_DEFAULT = 256
ROWBAND_STRIPE_ROW_VALUES_DEFAULT = 2048
ROWBAND_STRIPE_ROWS_DEFAULT = 4
ROWBAND_STRIPE_BAND_VALUES_DEFAULT = 4096


def _load_profile_sequences(profile_path: Path) -> List[List[int]]:
    if not profile_path.is_file():
        raise FileNotFoundError(f"profile file not found: {profile_path}")
    seqs: List[List[int]] = []
    with profile_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"empty profile csv: {profile_path}")
        for row in reader:
            raw = str(row.get("pre_touch_order", "") or "").strip()
            if not raw:
                seqs.append([])
                continue
            toks = [t for t in raw.replace(",", " ").split() if t]
            seqs.append([int(t) for t in toks])
    return seqs


def _build_profile_graph(
    seqs: Sequence[Sequence[int]],
    *,
    lookahead: int,
) -> Tuple[Dict[int, int], Dict[Tuple[int, int], int]]:
    freq: Dict[int, int] = defaultdict(int)
    trans: Dict[Tuple[int, int], int] = defaultdict(int)
    la = max(1, int(lookahead))
    for seq in seqs:
        if not seq:
            continue
        for pre in seq:
            freq[int(pre)] += 1
        n = len(seq)
        for i, src in enumerate(seq):
            for delta in range(1, la + 1):
                j = i + delta
                if j >= n:
                    break
                dst = int(seq[j])
                if dst == src:
                    continue
                trans[(int(src), dst)] += (la - delta + 1)
    return dict(freq), dict(trans)


def _load_hol_profile_head_stats(
    offline_profile_path: Optional[Path],
    *,
    head_k: int,
) -> Tuple[Dict[int, int], Dict[str, int]]:
    risk_stats, stats = _load_hol_profile_risk_stats(
        offline_profile_path,
        head_k=head_k,
    )
    head_hits = {int(pre): int(v.get("head_hits", 0)) for pre, v in risk_stats.items()}
    return head_hits, stats


def _load_hol_profile_risk_stats(
    offline_profile_path: Optional[Path],
    *,
    head_k: int,
) -> Tuple[Dict[int, Dict[str, float]], Dict[str, int]]:
    stats = {
        "hol_profile_rows": 0,
        "hol_profile_unique_pres": 0,
        "hol_profile_head_hits_total": 0,
        "hol_profile_head_depth_sum_total": 0,
        "hol_target_top_m": int(HOL_DUAL_GUARD_TARGET_TOP_M_DEFAULT),
        "hol_neighbor_top_k": int(HOL_DUAL_GUARD_NEIGHBOR_TOP_K_DEFAULT),
        "hol_high_risk_target_count": 0,
        "hol_high_risk_target_preview": [],
        "hol_weak_neighborhood_target_count": 0,
        "hol_weak_neighborhood_edge_count": 0,
        "hol_weak_neighborhood_max_degree": 0,
        "hol_weak_neighborhood_preview": {},
    }
    if offline_profile_path is None or not offline_profile_path.is_file():
        return {}, stats

    hk = max(1, int(head_k))
    target_top_m = int(HOL_DUAL_GUARD_TARGET_TOP_M_DEFAULT)
    neighbor_top_k = int(HOL_DUAL_GUARD_NEIGHBOR_TOP_K_DEFAULT)
    per_pre: Dict[int, Dict[str, float]] = defaultdict(
        lambda: {"head_hits": 0.0, "head_depth_sum": 0.0, "head_depth_avg": 0.0, "target_score": 0.0}
    )
    touched_pres: Dict[int, int] = defaultdict(int)
    window_head_pres: Dict[int, set[int]] = defaultdict(set)
    with offline_profile_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {}, stats
        for row in reader:
            try:
                pre = int(str(row.get("pre_global", "") or "").strip())
                local_age_rank = int(str(row.get("local_age_rank", "") or "").strip())
                younger_ahead_depth = int(str(row.get("younger_ahead_depth", "") or "0").strip())
                window_id = int(str(row.get("window_id", "") or "").strip())
            except Exception:
                continue
            touched_pres[pre] += 1
            stats["hol_profile_rows"] += 1
            if local_age_rank < hk:
                per_pre[pre]["head_hits"] += 1.0
                per_pre[pre]["head_depth_sum"] += float(max(0, younger_ahead_depth))
                stats["hol_profile_head_hits_total"] += 1
                stats["hol_profile_head_depth_sum_total"] += int(max(0, younger_ahead_depth))
                if max(0, younger_ahead_depth) > 0:
                    window_head_pres[int(window_id)].add(int(pre))

    stats["hol_profile_unique_pres"] = int(len(touched_pres))
    out: Dict[int, Dict[str, float]] = {}
    for pre, values in per_pre.items():
        hits = float(values.get("head_hits", 0.0))
        depth_sum = float(values.get("head_depth_sum", 0.0))
        target_score = float(depth_sum)
        out[int(pre)] = {
            "head_hits": hits,
            "head_depth_sum": depth_sum,
            "head_depth_avg": (depth_sum / hits) if hits > 0.0 else 0.0,
            "target_score": target_score,
        }

    ordered_targets = sorted(
        (
            int(pre)
            for pre, values in out.items()
            if float(values.get("target_score", 0.0)) > 0.0
        ),
        key=lambda pre: (
            -float(out[int(pre)].get("target_score", 0.0)),
            -float(out[int(pre)].get("head_hits", 0.0)),
            -float(out[int(pre)].get("head_depth_avg", 0.0)),
            int(pre),
        ),
    )
    top_targets = list(ordered_targets[:target_top_m])
    target_set = set(int(pre) for pre in top_targets)

    neighbor_counts: Dict[int, Dict[int, int]] = defaultdict(dict)
    for members in window_head_pres.values():
        scoped = sorted(int(pre) for pre in members if int(pre) in target_set)
        if len(scoped) <= 1:
            continue
        for src in scoped:
            for dst in scoped:
                if src == dst:
                    continue
                row = neighbor_counts[int(src)]
                row[int(dst)] = int(row.get(int(dst), 0) + 1)

    weak_preview: Dict[str, List[int]] = {}
    edge_count = 0
    max_degree = 0
    for src in top_targets:
        nbrs = neighbor_counts.get(int(src), {})
        ordered_nbrs = sorted(
            nbrs,
            key=lambda dst: (
                -int(nbrs[int(dst)]),
                -float(out.get(int(dst), {}).get("target_score", 0.0)),
                int(dst),
            ),
        )
        trimmed = [int(dst) for dst in ordered_nbrs[:neighbor_top_k]]
        if trimmed:
            weak_preview[str(int(src))] = trimmed
            edge_count += len(trimmed)
            max_degree = max(max_degree, len(trimmed))
        out.setdefault(int(src), {})
        out[int(src)]["weak_neighbors"] = list(trimmed)

    stats["hol_high_risk_target_count"] = int(len(top_targets))
    stats["hol_high_risk_target_preview"] = list(int(pre) for pre in top_targets)
    stats["hol_weak_neighborhood_target_count"] = int(len(weak_preview))
    stats["hol_weak_neighborhood_edge_count"] = int(edge_count)
    stats["hol_weak_neighborhood_max_degree"] = int(max_degree)
    stats["hol_weak_neighborhood_preview"] = weak_preview
    return out, stats


def _blend_profile_freq_with_hol_head_hits(
    freq: Dict[int, int],
    hol_head_hits: Dict[int, int],
    *,
    head_bonus: int,
) -> Dict[int, int]:
    if not hol_head_hits:
        return dict(freq)
    bonus = max(0, int(head_bonus))
    mixed: Dict[int, int] = dict(freq)
    if bonus == 0:
        return mixed
    for pre, hit in hol_head_hits.items():
        mixed[int(pre)] = int(mixed.get(int(pre), 0) + bonus * int(hit))
    return mixed


def _dual_guard_shadow_stats(
    stats: Dict[str, object],
) -> Dict[str, object]:
    preview = [int(pre) for pre in list(stats.get("hol_high_risk_target_preview", []))]
    weak_preview = {
        str(pre): [int(nbr) for nbr in list(neighbors)]
        for pre, neighbors in dict(stats.get("hol_weak_neighborhood_preview", {})).items()
    }
    return {
        "hol_dual_guard_shadow_enabled": 1,
        "hol_dual_guard_shadow_candidate_count": int(stats.get("hol_high_risk_target_count", 0)),
        "hol_dual_guard_shadow_best_target_preview": preview,
        "hol_dual_guard_shadow_best_neighbor_preview": weak_preview,
    }


def _ordered_dual_guard_targets(
    risk_stats: Dict[int, Dict[str, float]],
) -> List[int]:
    return sorted(
        (
            int(pre)
            for pre, values in risk_stats.items()
            if float(values.get("target_score", 0.0)) > 0.0
        ),
        key=lambda pre: (
            -float(risk_stats[int(pre)].get("target_score", 0.0)),
            -float(risk_stats[int(pre)].get("head_hits", 0.0)),
            -float(risk_stats[int(pre)].get("head_depth_avg", 0.0)),
            int(pre),
        ),
    )


def _build_dual_guard_state(
    risk_stats: Dict[int, Dict[str, float]],
) -> Dict[str, object]:
    targets = _ordered_dual_guard_targets(risk_stats)
    weak_map: Dict[int, List[int]] = {}
    for pre in targets:
        row = risk_stats.get(int(pre), {})
        raw_neighbors = row.get("weak_neighbors", [])
        if isinstance(raw_neighbors, list) and raw_neighbors:
            weak_map[int(pre)] = [int(v) for v in raw_neighbors]
    weak_rank = {
        int(src): {int(dst): idx for idx, dst in enumerate(neighbors)}
        for src, neighbors in weak_map.items()
    }
    return {
        "targets": list(int(pre) for pre in targets),
        "target_set": set(int(pre) for pre in targets),
        "weak_map": weak_map,
        "weak_rank": weak_rank,
    }


def _dual_guard_stats(
    dual_state: Dict[str, object],
) -> Dict[str, object]:
    targets = [int(pre) for pre in list(dual_state.get("targets", []))]
    weak_map = {
        str(pre): [int(nbr) for nbr in list(neighbors)]
        for pre, neighbors in dict(dual_state.get("weak_map", {})).items()
    }
    return {
        "hol_dual_guard_enabled": 1,
        "hol_dual_guard_candidate_count": int(len(targets)),
        "hol_dual_guard_best_target_preview": targets,
        "hol_dual_guard_best_neighbor_preview": weak_map,
    }


def _dual_guard_target_displacement_penalty(
    *,
    cursor: int,
    seg_len: int,
    cand_target_score: float,
    cand_is_target: bool,
) -> float:
    if not bool(cand_is_target) or float(cand_target_score) <= 0.0:
        return 0.0
    share = max(1, int(_tail_share_count(int(cursor), int(seg_len))))
    return float(cand_target_score) * float(share)


def _dual_guard_neighborhood_drift_penalty(
    *,
    prev_is_target: bool,
    weak_hit_rank: int,
    prev_target_score: float,
    cand_target_score: float,
    share: int,
) -> float:
    if not bool(prev_is_target):
        return 0.0
    if int(weak_hit_rank) < 1_000_000:
        return float(weak_hit_rank)
    return float(prev_target_score + cand_target_score + max(1, int(share)))


def _dual_guard_step_entry(
    *,
    prev: Optional[int],
    cand: int,
    cursor: int,
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    risk_stats: Dict[int, Dict[str, float]],
    target_set: set[int],
    weak_rank: Dict[int, Dict[int, int]],
    step: Optional[int] = None,
) -> Dict[str, object]:
    seg_len = int(len(pre_to_pairs.get(int(cand), [])))
    share = int(_tail_share_count(int(cursor), int(seg_len)))
    prev_is_target = prev is not None and int(prev) in target_set
    cand_is_target = int(cand) in target_set
    prev_target_score = float(risk_stats.get(int(prev), {}).get("target_score", 0.0)) if prev is not None else 0.0
    cand_target_score = float(risk_stats.get(int(cand), {}).get("target_score", 0.0))
    prev_risk = _hol_risk_value(risk_stats, int(prev)) if prev is not None else 0.0
    cand_risk = _hol_risk_value(risk_stats, int(cand))
    weak_cur_rank = (
        int(weak_rank.get(int(prev), {}).get(int(cand), 1_000_000))
        if prev is not None
        else 1_000_000
    )
    weak_rev_rank = (
        int(weak_rank.get(int(cand), {}).get(int(prev), 1_000_000))
        if prev is not None
        else 1_000_000
    )
    weak_hit_rank = int(min(weak_cur_rank, weak_rev_rank))
    target_penalty = _dual_guard_target_displacement_penalty(
        cursor=int(cursor),
        seg_len=int(seg_len),
        cand_target_score=float(cand_target_score),
        cand_is_target=bool(cand_is_target),
    )
    neighbor_penalty = _dual_guard_neighborhood_drift_penalty(
        prev_is_target=bool(prev_is_target),
        weak_hit_rank=int(weak_hit_rank),
        prev_target_score=float(prev_target_score),
        cand_target_score=float(cand_target_score),
        share=int(share),
    )
    shared_line_head_risk = float(share) * float(prev_risk + cand_risk) if prev is not None else 0.0
    entry = {
        "prev": -1 if prev is None else int(prev),
        "cand": int(cand),
        "cursor_before": int(cursor),
        "seg_len": int(seg_len),
        "tail_share": int(share),
        "prev_is_target": 1 if prev_is_target else 0,
        "cand_is_target": 1 if cand_is_target else 0,
        "weak_hit_rank_raw": int(weak_hit_rank),
        "weak_hit_rank": -1 if int(weak_hit_rank) >= 1_000_000 else int(weak_hit_rank),
        "target_score": float(cand_target_score),
        "prev_target_score": float(prev_target_score),
        "target_displacement_penalty": float(target_penalty),
        "neighborhood_drift_penalty": float(neighbor_penalty),
        "shared_line_head_risk": float(shared_line_head_risk),
        "cand_risk": float(cand_risk),
    }
    if step is not None:
        entry["step"] = int(step)
    return entry


def _collect_dual_guard_observe_stats(
    order: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    risk_stats: Dict[int, Dict[str, float]],
    *,
    prefix: str,
    preview_limit: int = 8,
) -> Dict[str, object]:
    dual_state = _build_dual_guard_state(risk_stats)
    target_set = set(int(pre) for pre in set(dual_state.get("target_set", set())))
    weak_rank = {
        int(src): {int(dst): int(rank) for dst, rank in dict(dst_map).items()}
        for src, dst_map in dict(dual_state.get("weak_rank", {})).items()
    }

    target_total = 0.0
    target_max = 0.0
    neighbor_total = 0.0
    neighbor_max = 0.0
    target_preview: List[Dict[str, object]] = []
    neighbor_preview: List[Dict[str, object]] = []
    scope_entries: List[Dict[str, object]] = []

    cursor = 0
    prev: Optional[int] = None
    max_preview = max(1, int(preview_limit))

    for step, cand in enumerate(int(v) for v in order):
        entry = _dual_guard_step_entry(
            prev=prev,
            cand=int(cand),
            cursor=int(cursor),
            pre_to_pairs=pre_to_pairs,
            risk_stats=risk_stats,
            target_set=target_set,
            weak_rank=weak_rank,
            step=int(step),
        )
        scope_entries.append(dict(entry))
        seg_len = int(entry.get("seg_len", 0))
        target_penalty = float(entry.get("target_displacement_penalty", 0.0))
        neighbor_penalty = float(entry.get("neighborhood_drift_penalty", 0.0))
        if float(target_penalty) > 0.0:
            target_total += float(target_penalty)
            target_max = max(float(target_max), float(target_penalty))
            target_preview.append(dict(entry))
        if float(neighbor_penalty) > 0.0:
            neighbor_total += float(neighbor_penalty)
            neighbor_max = max(float(neighbor_max), float(neighbor_penalty))
            neighbor_preview.append(dict(entry))
        cursor += int(seg_len)
        prev = int(cand)

    target_preview = sorted(
        target_preview,
        key=lambda row: (
            -float(row.get("target_displacement_penalty", 0.0)),
            int(row.get("step", 1 << 30)),
            int(row.get("cand", 1 << 30)),
        ),
    )[:max_preview]
    neighbor_preview = sorted(
        neighbor_preview,
        key=lambda row: (
            -float(row.get("neighborhood_drift_penalty", 0.0)),
            int(row.get("step", 1 << 30)),
            int(row.get("cand", 1 << 30)),
        ),
    )[:max_preview]
    scope_preview = sorted(
        scope_entries,
        key=lambda row: (
            -float(row.get("neighborhood_drift_penalty", 0.0)),
            -float(row.get("target_displacement_penalty", 0.0)),
            -float(row.get("shared_line_head_risk", 0.0)),
            -float(row.get("cand_risk", 0.0)),
            int(row.get("step", 1 << 30)),
            int(row.get("cand", 1 << 30)),
        ),
    )[:max_preview]

    return {
        f"{prefix}_observe_enabled": 1,
        f"{prefix}_target_displacement_total": float(target_total),
        f"{prefix}_target_displacement_max": float(target_max),
        f"{prefix}_target_displacement_preview": target_preview,
        f"{prefix}_neighborhood_drift_total": float(neighbor_total),
        f"{prefix}_neighborhood_drift_max": float(neighbor_max),
        f"{prefix}_neighborhood_drift_preview": neighbor_preview,
        f"{prefix}_scope_preview": scope_preview,
    }


def _chunk_pres_by_value_limit(
    pres: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    *,
    limit: int,
) -> List[List[int]]:
    chunks: List[List[int]] = []
    cur: List[int] = []
    cur_values = 0
    value_limit = max(1, int(limit))
    for pre in (int(v) for v in pres):
        seg_len = int(len(pre_to_pairs.get(int(pre), [])))
        if cur and cur_values + seg_len > value_limit:
            chunks.append(list(cur))
            cur = []
            cur_values = 0
        cur.append(int(pre))
        cur_values += int(seg_len)
    if cur:
        chunks.append(list(cur))
    return chunks


def _apply_rowband_stripe_repair(
    pres: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    *,
    block_values: int,
    row_values: int,
    stripe_rows: int,
    band_values: Optional[int] = None,
) -> Tuple[List[int], Dict[str, int]]:
    block_values = max(1, int(block_values))
    row_values = max(block_values, int(row_values))
    stripe_rows = max(1, int(stripe_rows))
    band_values = max(
        row_values,
        int(row_values if band_values is None else band_values),
    )
    blocks_per_row = max(1, row_values // block_values)
    group_blocks = max(1, blocks_per_row * stripe_rows)
    rows_per_band = max(1, band_values // row_values)
    original = [int(pre) for pre in pres]
    blocks = _chunk_pres_by_value_limit(
        original,
        pre_to_pairs,
        limit=block_values,
    )

    striped_blocks: List[List[int]] = []
    groups_total = 0
    for start in range(0, len(blocks), group_blocks):
        group = blocks[start : start + group_blocks]
        if not group:
            continue
        groups_total += 1
        group_rows = (len(group) + blocks_per_row - 1) // blocks_per_row
        band_count = (group_rows + rows_per_band - 1) // rows_per_band
        row_order: List[int] = []
        for phase in range(rows_per_band):
            for band in range(band_count):
                row_idx = band * rows_per_band + phase
                if row_idx < group_rows:
                    row_order.append(int(row_idx))
        for offset in range(blocks_per_row):
            for row_idx in row_order:
                idx = int(row_idx) * blocks_per_row + offset
                if idx < len(group):
                    striped_blocks.append(list(group[idx]))

    repaired = [int(pre) for block in striped_blocks for pre in block]
    changed_pre_count = sum(
        1
        for before, after in zip(original, repaired)
        if int(before) != int(after)
    )
    return repaired, {
        "rowband_stripe_enabled": 1,
        "rowband_stripe_block_values": int(block_values),
        "rowband_stripe_row_values": int(row_values),
        "rowband_stripe_band_values": int(band_values),
        "rowband_stripe_stripe_rows": int(stripe_rows),
        "rowband_stripe_rows_per_band": int(rows_per_band),
        "rowband_stripe_blocks_total": int(len(blocks)),
        "rowband_stripe_blocks_per_row": int(blocks_per_row),
        "rowband_stripe_group_blocks": int(group_blocks),
        "rowband_stripe_groups_total": int(groups_total),
        "rowband_stripe_changed_pre_count": int(changed_pre_count),
    }


def _apply_anchor_separator_target_closure(
    communities: Sequence[Dict[str, object]],
    *,
    keys_set: set[int],
    risk_stats: Dict[int, Dict[str, float]],
) -> List[Dict[str, object]]:
    expanded: List[Dict[str, object]] = [
        {
            "targets": set(int(v) for v in set(community.get("targets", set())) if int(v) in keys_set),
            "members": set(int(v) for v in set(community.get("members", set())) if int(v) in keys_set),
        }
        for community in communities
    ]
    claimed_members = {
        int(pre)
        for community in expanded
        for pre in set(community.get("members", set()))
    }
    weak_top_k = int(ANCHOR_SEPARATOR_WEAK_TOP_K_DEFAULT)
    requests: Dict[int, List[Tuple[float, int]]] = defaultdict(list)
    for community_id, community in enumerate(expanded):
        for target in sorted(int(v) for v in set(community.get("targets", set()))):
            target_score = float(risk_stats.get(int(target), {}).get("target_score", 0.0))
            raw_neighbors = list(risk_stats.get(int(target), {}).get("weak_neighbors", []))[:weak_top_k]
            for rank, raw_nbr in enumerate(raw_neighbors):
                nbr = int(raw_nbr)
                if nbr not in keys_set or nbr in claimed_members:
                    continue
                requests[int(nbr)].append(
                    (
                        float(target_score) - float(rank) * 0.25,
                        int(community_id),
                    )
                )

    for pre, choices in requests.items():
        if not choices:
            continue
        _, owner = max(
            choices,
            key=lambda item: (
                float(item[0]),
                -int(item[1]),
            ),
        )
        expanded[int(owner)]["members"].add(int(pre))

    return expanded


def _resolve_anchor_separator_unique_membership(
    communities: Sequence[Dict[str, object]],
    *,
    keys_set: set[int],
    risk_stats: Dict[int, Dict[str, float]],
) -> List[Dict[str, object]]:
    resolved: List[Dict[str, object]] = [
        {
            "targets": set(int(v) for v in set(community.get("targets", set())) if int(v) in keys_set),
            "members": set(),
        }
        for community in communities
    ]
    weak_top_k = int(ANCHOR_SEPARATOR_WEAK_TOP_K_DEFAULT)
    member_requests: Dict[int, List[Tuple[float, int]]] = defaultdict(list)
    for community_id, community in enumerate(communities):
        targets = set(int(v) for v in set(community.get("targets", set())) if int(v) in keys_set)
        members = set(int(v) for v in set(community.get("members", set())) if int(v) in keys_set)
        for pre in members:
            score = 0.0
            if int(pre) in targets:
                score += 1.0e12
            for target in targets:
                target_score = float(risk_stats.get(int(target), {}).get("target_score", 0.0))
                raw_neighbors = [int(v) for v in list(risk_stats.get(int(target), {}).get("weak_neighbors", []))[:weak_top_k]]
                if int(pre) in raw_neighbors:
                    score += float(target_score)
                    score += float(weak_top_k - raw_neighbors.index(int(pre))) * 0.25
                else:
                    score += float(target_score) * 0.01
            member_requests[int(pre)].append((float(score), int(community_id)))

    for pre, choices in member_requests.items():
        _, owner = max(
            choices,
            key=lambda item: (
                float(item[0]),
                -int(item[1]),
            ),
        )
        resolved[int(owner)]["members"].add(int(pre))

    return resolved


def _anchor_separator_community_gap(
    lhs_min: int,
    lhs_max: int,
    rhs_min: int,
    rhs_max: int,
) -> int:
    if int(lhs_max) < int(rhs_min):
        return int(rhs_min) - int(lhs_max)
    if int(rhs_max) < int(lhs_min):
        return int(lhs_min) - int(rhs_max)
    return 0


def _merge_tiny_anchor_separator_communities(
    communities: Sequence[Dict[str, object]],
    *,
    keys_set: set[int],
    risk_stats: Dict[int, Dict[str, float]],
    graph: Dict[int, Dict[int, int]],
    baseline_rank: Dict[int, int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
) -> List[Dict[str, object]]:
    normalized: List[Dict[str, object]] = [
        {
            "targets": set(int(v) for v in set(community.get("targets", set())) if int(v) in keys_set),
            "members": set(int(v) for v in set(community.get("members", set())) if int(v) in keys_set),
        }
        for community in communities
    ]
    if len(normalized) <= 1:
        return normalized

    weak_top_k = int(ANCHOR_SEPARATOR_WEAK_TOP_K_DEFAULT)
    tiny_member_max = int(ANCHOR_SEPARATOR_TINY_COMMUNITY_MEMBER_MAX_DEFAULT)
    tiny_line_max = int(ANCHOR_SEPARATOR_TINY_COMMUNITY_LINE_MAX_DEFAULT)

    def _summarize(community: Dict[str, object]) -> Dict[str, object]:
        members = set(int(v) for v in set(community.get("members", set())) if int(v) in keys_set)
        targets = set(int(v) for v in set(community.get("targets", set())) if int(v) in keys_set)
        total_values = int(sum(int(len(pre_to_pairs.get(int(pre), []))) for pre in members))
        baseline_min = int(min((baseline_rank.get(int(pre), 1 << 30) for pre in members), default=(1 << 30)))
        baseline_max = int(max((baseline_rank.get(int(pre), -1) for pre in members), default=-1))
        return {
            "targets": set(int(v) for v in targets),
            "members": set(int(v) for v in members),
            "member_count": int(len(members)),
            "line_total": int((total_values + VALUES_PER_LINE - 1) // VALUES_PER_LINE) if total_values > 0 else 0,
            "baseline_min": int(baseline_min),
            "baseline_max": int(baseline_max),
        }

    def _affinity(src: Dict[str, object], dst: Dict[str, object]) -> float:
        score = 0.0
        signal_count = 0
        src_members = set(int(v) for v in set(src["members"]))
        dst_members = set(int(v) for v in set(dst["members"]))
        for pre in src_members:
            for nbr, weight in dict(graph.get(int(pre), {})).items():
                if int(nbr) in dst_members:
                    score += float(weight)
                    signal_count += 1
        for target in set(int(v) for v in set(src["targets"])):
            target_score = float(risk_stats.get(int(target), {}).get("target_score", 0.0))
            raw_neighbors = [int(v) for v in list(risk_stats.get(int(target), {}).get("weak_neighbors", []))[:weak_top_k]]
            for rank, nbr in enumerate(raw_neighbors):
                if int(nbr) not in dst_members:
                    continue
                score += max(target_score, 1.0)
                score += float(weak_top_k - rank) * 0.25
                signal_count += 1
        for target in set(int(v) for v in set(dst["targets"])):
            target_score = float(risk_stats.get(int(target), {}).get("target_score", 0.0))
            raw_neighbors = [int(v) for v in list(risk_stats.get(int(target), {}).get("weak_neighbors", []))[:weak_top_k]]
            for rank, nbr in enumerate(raw_neighbors):
                if int(nbr) not in src_members:
                    continue
                score += max(target_score, 1.0)
                score += float(weak_top_k - rank) * 0.25
                signal_count += 1
        if signal_count <= 0:
            return 0.0
        gap = _anchor_separator_community_gap(
            int(src["baseline_min"]),
            int(src["baseline_max"]),
            int(dst["baseline_min"]),
            int(dst["baseline_max"]),
        )
        score += 1.0 / float(1 + max(0, int(gap)))
        return float(score)

    changed = True
    while changed and len(normalized) > 1:
        changed = False
        summaries = [_summarize(community) for community in normalized]
        order = sorted(
            range(len(summaries)),
            key=lambda idx: (
                int(summaries[idx]["baseline_min"]),
                int(summaries[idx]["member_count"]),
                idx,
            ),
        )
        for idx in order:
            src = summaries[idx]
            if src["member_count"] <= 0:
                continue
            if not (
                int(src["member_count"]) <= tiny_member_max
                and int(src["line_total"]) <= tiny_line_max
            ):
                continue
            best_idx = -1
            best_key: Optional[Tuple[float, int, int, int]] = None
            for jdx, dst in enumerate(summaries):
                if jdx == idx:
                    continue
                if (
                    int(dst["member_count"]) <= tiny_member_max
                    and int(dst["line_total"]) <= tiny_line_max
                    and int(dst["member_count"]) <= int(src["member_count"])
                    and int(dst["line_total"]) <= int(src["line_total"])
                ):
                    continue
                affinity = _affinity(src, dst)
                if affinity <= 0.0:
                    continue
                gap = _anchor_separator_community_gap(
                    int(src["baseline_min"]),
                    int(src["baseline_max"]),
                    int(dst["baseline_min"]),
                    int(dst["baseline_max"]),
                )
                key = (
                    float(affinity),
                    -int(gap),
                    int(dst["member_count"]),
                    -int(jdx),
                )
                if best_key is None or key > best_key:
                    best_key = key
                    best_idx = int(jdx)
            if best_idx < 0:
                continue
            normalized[best_idx]["targets"].update(int(v) for v in set(normalized[idx].get("targets", set())))
            normalized[best_idx]["members"].update(int(v) for v in set(normalized[idx].get("members", set())))
            del normalized[idx]
            changed = True
            break

    return normalized


def _build_anchor_separator_plan(
    keys: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    *,
    freq: Dict[int, int],
    trans: Dict[Tuple[int, int], int],
    risk_stats: Dict[int, Dict[str, float]],
    baseline_order: Sequence[int],
    enable_target_closure: bool,
) -> Dict[str, object]:
    keys_set = {int(v) for v in keys}
    if not keys_set:
        return {
            "anchor_map": [],
            "block_plan": [],
            "cut_summary": {
                "anchor_community_count": 0,
                "anchor_member_count": 0,
                "separator_member_count": 0,
                "block_count": 0,
                "anchor_escape_count": 0,
                "cross_block_weak_edge_weight_ratio": 0.0,
                "anchor_local_span_p95": 0,
                "block_slack_values_total": 0,
                "microblock_values": int(ANCHOR_SEPARATOR_MICROBLOCK_VALUES_DEFAULT),
                "mesoblock_values": int(ANCHOR_SEPARATOR_MESOBLOCK_VALUES_DEFAULT),
                "macroblock_values": int(ANCHOR_SEPARATOR_MACROBLOCK_VALUES_DEFAULT),
                "anchor_band_lines": int(ANCHOR_SEPARATOR_ANCHOR_BAND_LINES_DEFAULT),
                "separator_slack_lines": int(ANCHOR_SEPARATOR_SEPARATOR_SLACK_LINES_DEFAULT),
            },
            "plan_order": [],
        }

    baseline = [int(pre) for pre in baseline_order if int(pre) in keys_set]
    seen_baseline = set(baseline)
    baseline.extend(sorted(int(pre) for pre in keys_set if int(pre) not in seen_baseline))
    baseline_rank = {int(pre): idx for idx, pre in enumerate(baseline)}

    graph: Dict[int, Dict[int, int]] = defaultdict(dict)
    for (raw_src, raw_dst), raw_weight in trans.items():
        src = int(raw_src)
        dst = int(raw_dst)
        weight = int(raw_weight)
        if src == dst or weight <= 0 or src not in keys_set or dst not in keys_set:
            continue
        graph[src][dst] = int(graph[src].get(dst, 0) + weight)
        graph[dst][src] = int(graph[dst].get(src, 0) + weight)

    weak_top_k = int(ANCHOR_SEPARATOR_WEAK_TOP_K_DEFAULT)
    trans_expand_top_n = int(ANCHOR_SEPARATOR_TRANS_EXPAND_TOP_N_DEFAULT)
    merge_jaccard = float(ANCHOR_SEPARATOR_MERGE_JACCARD_DEFAULT)

    raw_communities: List[Dict[str, object]] = []
    target_top_m = int(HOL_DUAL_GUARD_TARGET_TOP_M_DEFAULT)
    for seed in _ordered_dual_guard_targets(risk_stats)[:target_top_m]:
        if int(seed) not in keys_set:
            continue
        members = {int(seed)}
        weak_neighbors = [
            int(nbr)
            for nbr in list(risk_stats.get(int(seed), {}).get("weak_neighbors", []))[:weak_top_k]
            if int(nbr) in keys_set
        ]
        members.update(int(nbr) for nbr in weak_neighbors)
        ranked_neighbors = sorted(
            (
                (int(dst), int(weight))
                for dst, weight in dict(graph.get(int(seed), {})).items()
                if int(dst) in keys_set and int(dst) not in members
            ),
            key=lambda item: (
                -int(item[1]),
                -int(freq.get(int(item[0]), 0)),
                -int(len(pre_to_pairs.get(int(item[0]), []))),
                int(item[0]),
            ),
        )
        for dst, _ in ranked_neighbors[:trans_expand_top_n]:
            members.add(int(dst))
        raw_communities.append(
            {
                "targets": {int(seed)},
                "members": set(int(pre) for pre in members),
            }
        )

    merged = list(raw_communities)
    changed = True
    while changed:
        changed = False
        next_communities: List[Dict[str, object]] = []
        used = [False] * len(merged)
        for idx, community in enumerate(merged):
            if used[idx]:
                continue
            cur_targets = set(int(v) for v in set(community.get("targets", set())))
            cur_members = set(int(v) for v in set(community.get("members", set())))
            used[idx] = True
            for jdx in range(idx + 1, len(merged)):
                if used[jdx]:
                    continue
                other_members = set(int(v) for v in set(merged[jdx].get("members", set())))
                union = len(cur_members | other_members)
                if union <= 0:
                    continue
                overlap = len(cur_members & other_members)
                if float(overlap) / float(union) < merge_jaccard:
                    continue
                cur_targets.update(int(v) for v in set(merged[jdx].get("targets", set())))
                cur_members.update(int(v) for v in other_members)
                used[jdx] = True
                changed = True
            next_communities.append({"targets": cur_targets, "members": cur_members})
        merged = next_communities

    if bool(enable_target_closure):
        merged = _resolve_anchor_separator_unique_membership(
            merged,
            keys_set=keys_set,
            risk_stats=risk_stats,
        )
        merged = _apply_anchor_separator_target_closure(
            merged,
            keys_set=keys_set,
            risk_stats=risk_stats,
        )
        merged = _merge_tiny_anchor_separator_communities(
            merged,
            keys_set=keys_set,
            risk_stats=risk_stats,
            graph=graph,
            baseline_rank=baseline_rank,
            pre_to_pairs=pre_to_pairs,
        )

    anchor_map: List[Dict[str, object]] = []
    for community_id, community in enumerate(merged):
        members = sorted(
            (int(pre) for pre in set(community.get("members", set())) if int(pre) in keys_set),
            key=lambda pre: (
                int(baseline_rank.get(int(pre), 1 << 30)),
                int(pre),
            ),
        )
        if not members:
            continue
        targets = sorted(
            (int(pre) for pre in set(community.get("targets", set())) if int(pre) in keys_set),
            key=lambda pre: (
                int(baseline_rank.get(int(pre), 1 << 30)),
                -float(risk_stats.get(int(pre), {}).get("target_score", 0.0)),
                int(pre),
            ),
        )
        seed = int(targets[0] if targets else members[0])
        total_values = int(sum(int(len(pre_to_pairs.get(int(pre), []))) for pre in members))
        anchor_map.append(
            {
                "community_id": int(community_id),
                "seed": int(seed),
                "targets": list(targets),
                "members": list(members),
                "members_preview": list(members[:16]),
                "member_count": int(len(members)),
                "total_values": int(total_values),
                "line_total": int((total_values + VALUES_PER_LINE - 1) // VALUES_PER_LINE),
                "baseline_rank_min": int(min(baseline_rank.get(int(pre), 1 << 30) for pre in members)),
                "baseline_rank_max": int(max(baseline_rank.get(int(pre), -1) for pre in members)),
            }
        )

    anchor_map = sorted(
        anchor_map,
        key=lambda row: (
            int(row.get("baseline_rank_min", 1 << 30)),
            int(row.get("seed", 1 << 30)),
        ),
    )
    community_index = {int(row["community_id"]): row for row in anchor_map}
    pre_to_community: Dict[int, int] = {}
    for row in anchor_map:
        for pre in list(row.get("members", [])):
            pre_to_community[int(pre)] = int(row["community_id"])

    blocks: List[Dict[str, object]] = []
    plan_order: List[int] = []
    block_assignment: Dict[int, int] = {}
    pending_separator: List[int] = []
    emitted_communities = set()
    block_id = 0

    def _emit_chunks(pres: Sequence[int], *, kind: str, community_id: int = -1, seed: int = -1) -> None:
        nonlocal block_id
        for part_index, chunk in enumerate(
            _chunk_pres_by_value_limit(
                pres,
                pre_to_pairs,
                limit=int(ANCHOR_SEPARATOR_MACROBLOCK_VALUES_DEFAULT),
            )
        ):
            if not chunk:
                continue
            values_total = int(sum(int(len(pre_to_pairs.get(int(pre), []))) for pre in chunk))
            line_total = int((values_total + VALUES_PER_LINE - 1) // VALUES_PER_LINE)
            row = {
                "block_id": int(block_id),
                "kind": str(kind),
                "community_id": int(community_id),
                "seed": int(seed),
                "part_index": int(part_index),
                "member_count": int(len(chunk)),
                "members_preview": list(int(pre) for pre in chunk[:16]),
                "values_total": int(values_total),
                "line_total": int(line_total),
                "baseline_rank_min": int(min(baseline_rank.get(int(pre), 1 << 30) for pre in chunk)),
                "baseline_rank_max": int(max(baseline_rank.get(int(pre), -1) for pre in chunk)),
            }
            blocks.append(row)
            for pre in chunk:
                plan_order.append(int(pre))
                block_assignment[int(pre)] = int(block_id)
            block_id += 1

    for pre in baseline:
        community_id = pre_to_community.get(int(pre))
        if community_id is None:
            pending_separator.append(int(pre))
            continue
        if int(community_id) in emitted_communities:
            continue
        if pending_separator:
            _emit_chunks(pending_separator, kind="separator")
            pending_separator = []
        row = community_index[int(community_id)]
        _emit_chunks(
            list(int(v) for v in list(row.get("members", []))),
            kind="anchor",
            community_id=int(community_id),
            seed=int(row.get("seed", -1)),
        )
        emitted_communities.add(int(community_id))

    if pending_separator:
        _emit_chunks(pending_separator, kind="separator")

    weak_edges_total = 0
    weak_edges_cross_block = 0
    anchor_escape_count = 0
    span_samples: List[int] = []
    plan_rank = {int(pre): idx for idx, pre in enumerate(plan_order)}
    for target in _ordered_dual_guard_targets(risk_stats):
        if int(target) not in keys_set:
            continue
        target_community = pre_to_community.get(int(target), -1)
        target_block = block_assignment.get(int(target), -1)
        target_rank = plan_rank.get(int(target))
        for nbr in [
            int(v)
            for v in list(risk_stats.get(int(target), {}).get("weak_neighbors", []))[:weak_top_k]
            if int(v) in keys_set
        ]:
            weak_edges_total += 1
            if int(pre_to_community.get(int(nbr), -2)) != int(target_community):
                anchor_escape_count += 1
            if int(block_assignment.get(int(nbr), -2)) != int(target_block):
                weak_edges_cross_block += 1
            nbr_rank = plan_rank.get(int(nbr))
            if target_rank is not None and nbr_rank is not None:
                span_samples.append(abs(int(nbr_rank) - int(target_rank)))

    span_samples = sorted(int(v) for v in span_samples)
    if span_samples:
        p95_idx = int(round(0.95 * float(len(span_samples) - 1)))
        anchor_local_span_p95 = int(span_samples[p95_idx])
    else:
        anchor_local_span_p95 = 0

    block_slack_values_total = int(
        sum(
            max(0, int(ANCHOR_SEPARATOR_MACROBLOCK_VALUES_DEFAULT) - int(row.get("values_total", 0)))
            for row in blocks
        )
    )
    anchor_member_set = {int(pre) for pre in pre_to_community}
    cut_summary = {
        "anchor_community_count": int(len(anchor_map)),
        "anchor_member_count": int(len(anchor_member_set)),
        "separator_member_count": int(len(keys_set - anchor_member_set)),
        "block_count": int(len(blocks)),
        "anchor_escape_count": int(anchor_escape_count),
        "cross_block_weak_edge_weight_ratio": (
            float(weak_edges_cross_block) / float(weak_edges_total) if weak_edges_total > 0 else 0.0
        ),
        "anchor_local_span_p95": int(anchor_local_span_p95),
        "block_slack_values_total": int(block_slack_values_total),
        "microblock_values": int(ANCHOR_SEPARATOR_MICROBLOCK_VALUES_DEFAULT),
        "mesoblock_values": int(ANCHOR_SEPARATOR_MESOBLOCK_VALUES_DEFAULT),
        "macroblock_values": int(ANCHOR_SEPARATOR_MACROBLOCK_VALUES_DEFAULT),
        "anchor_band_lines": int(ANCHOR_SEPARATOR_ANCHOR_BAND_LINES_DEFAULT),
        "separator_slack_lines": int(ANCHOR_SEPARATOR_SEPARATOR_SLACK_LINES_DEFAULT),
    }
    return {
        "anchor_map": anchor_map,
        "block_plan": blocks,
        "cut_summary": cut_summary,
        "plan_order": list(int(pre) for pre in plan_order),
        "plan_order_preview": list(int(pre) for pre in plan_order[:64]),
    }


def _build_anchor_separator_shadow_plan(
    keys: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    *,
    freq: Dict[int, int],
    trans: Dict[Tuple[int, int], int],
    risk_stats: Dict[int, Dict[str, float]],
    baseline_order: Sequence[int],
) -> Dict[str, object]:
    return _build_anchor_separator_plan(
        keys,
        pre_to_pairs,
        freq=freq,
        trans=trans,
        risk_stats=risk_stats,
        baseline_order=baseline_order,
        enable_target_closure=False,
    )


def _build_anchor_separator_layout_plan(
    keys: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    *,
    freq: Dict[int, int],
    trans: Dict[Tuple[int, int], int],
    risk_stats: Dict[int, Dict[str, float]],
    baseline_order: Sequence[int],
) -> Dict[str, object]:
    return _build_anchor_separator_plan(
        keys,
        pre_to_pairs,
        freq=freq,
        trans=trans,
        risk_stats=risk_stats,
        baseline_order=baseline_order,
        enable_target_closure=True,
    )


def _anchor_separator_plan_stats(
    plan: Dict[str, object],
) -> Dict[str, object]:
    cut_summary = dict(plan.get("cut_summary", {}))
    return {
        "anchor_separator_enabled": 1,
        "anchor_separator_anchor_community_count": int(cut_summary.get("anchor_community_count", 0)),
        "anchor_separator_anchor_member_count": int(cut_summary.get("anchor_member_count", 0)),
        "anchor_separator_separator_member_count": int(cut_summary.get("separator_member_count", 0)),
        "anchor_separator_block_count": int(cut_summary.get("block_count", 0)),
        "anchor_separator_anchor_escape_count": int(cut_summary.get("anchor_escape_count", 0)),
        "anchor_separator_cross_block_weak_edge_weight_ratio": float(
            cut_summary.get("cross_block_weak_edge_weight_ratio", 0.0)
        ),
        "anchor_separator_anchor_preview": list(plan.get("anchor_map", []))[:8],
        "anchor_separator_block_plan_preview": list(plan.get("block_plan", []))[:8],
        "anchor_separator_plan": plan,
    }


def _anchor_separator_shadow_stats(
    plan: Dict[str, object],
) -> Dict[str, object]:
    stats = _anchor_separator_plan_stats(plan)
    return {
        "anchor_separator_shadow_enabled": int(stats["anchor_separator_enabled"]),
        "anchor_separator_shadow_anchor_community_count": int(stats["anchor_separator_anchor_community_count"]),
        "anchor_separator_shadow_anchor_member_count": int(stats["anchor_separator_anchor_member_count"]),
        "anchor_separator_shadow_separator_member_count": int(stats["anchor_separator_separator_member_count"]),
        "anchor_separator_shadow_block_count": int(stats["anchor_separator_block_count"]),
        "anchor_separator_shadow_anchor_escape_count": int(stats["anchor_separator_anchor_escape_count"]),
        "anchor_separator_shadow_cross_block_weak_edge_weight_ratio": float(
            stats["anchor_separator_cross_block_weak_edge_weight_ratio"]
        ),
        "anchor_separator_shadow_anchor_preview": list(stats["anchor_separator_anchor_preview"]),
        "anchor_separator_shadow_block_plan_preview": list(stats["anchor_separator_block_plan_preview"]),
        "anchor_separator_shadow_plan": plan,
    }


def _write_anchor_separator_shadow_sidecars(
    pe_dir: Path,
    *,
    core: int,
    plan: Dict[str, object],
    stem_label: str = "anchor_separator_shadow",
) -> Dict[str, str]:
    pe_dir.mkdir(parents=True, exist_ok=True)
    stem = f"core{int(core):02d}.{str(stem_label)}"
    anchor_map_name = f"{stem}.anchor_map.json"
    block_plan_name = f"{stem}.block_plan.json"
    cut_summary_name = f"{stem}.cut_summary.json"
    (pe_dir / anchor_map_name).write_text(
        json.dumps({"anchor_map": list(plan.get("anchor_map", []))}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (pe_dir / block_plan_name).write_text(
        json.dumps(
            {
                "block_plan": list(plan.get("block_plan", [])),
                "plan_order_preview": list(plan.get("plan_order_preview", [])),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (pe_dir / cut_summary_name).write_text(
        json.dumps(dict(plan.get("cut_summary", {})), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "anchor_map_path": anchor_map_name,
        "block_plan_path": block_plan_name,
        "cut_summary_path": cut_summary_name,
    }


def _order_by_profile_sidrun_reg(
    keys: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    *,
    freq: Dict[int, int],
    trans: Dict[Tuple[int, int], int],
) -> List[int]:
    sorted_keys = [int(v) for v in sorted(int(k) for k in keys)]
    if not sorted_keys:
        return []

    block_size = int(SIDRUN_BLOCK_SIZE_DEFAULT)
    if block_size <= 1:
        return _order_by_profile_greedy(keys, pre_to_pairs, freq=freq, trans=trans)

    blocks: List[List[int]] = []
    pre_to_block: Dict[int, int] = {}
    for start in range(0, len(sorted_keys), block_size):
        blk = sorted_keys[start:start + block_size]
        bid = len(blocks)
        blocks.append(list(int(v) for v in blk))
        for pre in blk:
            pre_to_block[int(pre)] = int(bid)

    block_freq: Dict[int, int] = defaultdict(int)
    block_len: Dict[int, int] = defaultdict(int)
    for bid, blk in enumerate(blocks):
        for pre in blk:
            block_freq[int(bid)] += int(freq.get(int(pre), 0))
            block_len[int(bid)] += int(len(pre_to_pairs.get(int(pre), [])))

    block_trans: Dict[Tuple[int, int], int] = defaultdict(int)
    for (src, dst), weight in trans.items():
        bs = pre_to_block.get(int(src))
        bd = pre_to_block.get(int(dst))
        if bs is None or bd is None or bs == bd or weight <= 0:
            continue
        block_trans[(int(bs), int(bd))] += int(weight)

    remaining = {int(i) for i in range(len(blocks))}

    def _fallback_sort_key(block_id: int) -> Tuple[int, int, int]:
        blk = blocks[int(block_id)]
        return (
            -int(block_freq.get(int(block_id), 0)),
            -int(block_len.get(int(block_id), 0)),
            int(blk[0]) if blk else int(block_id),
        )

    nbr_weights: Dict[int, Dict[int, int]] = defaultdict(dict)
    for (src, dst), weight in block_trans.items():
        s = int(src)
        d = int(dst)
        w = int(weight)
        nbr_weights[s][d] = int(nbr_weights[s].get(d, 0) + w)
        nbr_weights[d][s] = int(nbr_weights[d].get(s, 0) + w)

    neighbor_order: Dict[int, List[int]] = {}
    for src, nbrs in nbr_weights.items():
        ordered = sorted(
            nbrs.items(),
            key=lambda kv: (
                -int(kv[1]),
                -int(block_freq.get(int(kv[0]), 0)),
                -int(block_len.get(int(kv[0]), 0)),
                int(blocks[int(kv[0])][0]) if blocks[int(kv[0])] else int(kv[0]),
            ),
        )
        neighbor_order[int(src)] = [int(dst) for dst, _ in ordered]

    fallback_order = sorted((int(i) for i in range(len(blocks))), key=_fallback_sort_key)
    fallback_idx = 0

    def _pop_best_fallback() -> int:
        nonlocal fallback_idx
        while fallback_idx < len(fallback_order):
            cand = int(fallback_order[fallback_idx])
            fallback_idx += 1
            if cand in remaining:
                return cand
        raise RuntimeError('fallback order exhausted before remaining became empty')

    neighbor_idx: Dict[int, int] = defaultdict(int)
    block_order: List[int] = []
    cur = _pop_best_fallback()
    block_order.append(int(cur))
    remaining.remove(int(cur))

    while remaining:
        cand: Optional[int] = None
        nbrs = neighbor_order.get(int(cur), [])
        idx = int(neighbor_idx.get(int(cur), 0))
        while idx < len(nbrs):
            nxt = int(nbrs[idx])
            idx += 1
            if nxt in remaining:
                cand = int(nxt)
                break
        neighbor_idx[int(cur)] = idx
        if cand is None:
            cand = _pop_best_fallback()
        block_order.append(int(cand))
        remaining.remove(int(cand))
        cur = int(cand)

    order: List[int] = []
    for bid in block_order:
        order.extend(blocks[int(bid)])
    return order


def _order_by_profile_greedy(
    keys: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    *,
    freq: Dict[int, int],
    trans: Dict[Tuple[int, int], int],
) -> List[int]:
    remaining = {int(k) for k in keys}
    if not remaining:
        return []

    def _fallback_sort_key(pre: int) -> Tuple[int, int, int]:
        return (
            -int(freq.get(pre, 0)),
            -int(len(pre_to_pairs.get(pre, []))),
            int(pre),
        )

    # Convert directional transitions into symmetric neighbor preference lists once,
    # then walk those lists lazily during the greedy chain growth. This preserves the
    # heuristic intent without the previous O(pre_count^2) full scan of `remaining`.
    nbr_weights: Dict[int, Dict[int, int]] = defaultdict(dict)
    for (src, dst), weight in trans.items():
        if src == dst or weight <= 0:
            continue
        s = int(src)
        d = int(dst)
        w = int(weight)
        nbr_weights[s][d] = int(nbr_weights[s].get(d, 0) + w)
        nbr_weights[d][s] = int(nbr_weights[d].get(s, 0) + w)

    neighbor_order: Dict[int, List[int]] = {}
    for src, nbrs in nbr_weights.items():
        ordered = sorted(
            nbrs.items(),
            key=lambda kv: (
                -int(kv[1]),
                -int(freq.get(int(kv[0]), 0)),
                -int(len(pre_to_pairs.get(int(kv[0]), []))),
                int(kv[0]),
            ),
        )
        neighbor_order[int(src)] = [int(dst) for dst, _ in ordered]

    fallback_order = sorted((int(k) for k in keys), key=_fallback_sort_key)
    fallback_idx = 0

    def _pop_best_fallback() -> int:
        nonlocal fallback_idx
        while fallback_idx < len(fallback_order):
            cand = int(fallback_order[fallback_idx])
            fallback_idx += 1
            if cand in remaining:
                return cand
        raise RuntimeError('fallback order exhausted before remaining became empty')

    neighbor_idx: Dict[int, int] = defaultdict(int)
    order: List[int] = []
    cur = _pop_best_fallback()
    order.append(int(cur))
    remaining.remove(int(cur))

    while remaining:
        cand: Optional[int] = None
        nbrs = neighbor_order.get(int(cur), [])
        idx = int(neighbor_idx.get(int(cur), 0))
        while idx < len(nbrs):
            nxt = int(nbrs[idx])
            idx += 1
            if nxt in remaining:
                cand = nxt
                break
        neighbor_idx[int(cur)] = idx
        if cand is None:
            cand = _pop_best_fallback()
        order.append(int(cand))
        remaining.remove(int(cand))
        cur = int(cand)
    return order


def _hol_risk_value(
    risk_stats: Dict[int, Dict[str, float]],
    pre: int,
) -> float:
    row = risk_stats.get(int(pre), {})
    if not row:
        return 0.0
    return float(row.get("head_depth_avg", 0.0)) + float(row.get("head_hits", 0.0))


def _tail_share_count(cursor: int, seg_len: int) -> int:
    pos = int(cursor) % int(VALUES_PER_LINE)
    if pos == 0:
        return 0
    remain = int(VALUES_PER_LINE) - pos
    return min(remain, int(seg_len))


def _fat_tail_guard(
    *,
    cursor: int,
    seg_len: int,
    shared_line_head_risk: float,
) -> Tuple[int, int, int]:
    guard_key, _, _, _ = _fat_tail_guard_state(
        cursor=cursor,
        seg_len=seg_len,
        shared_line_head_risk=shared_line_head_risk,
    )
    return guard_key


def _fat_tail_guard_state(
    *,
    cursor: int,
    seg_len: int,
    shared_line_head_risk: float,
) -> Tuple[Tuple[int, int, int], str, int, int]:
    share = int(_tail_share_count(cursor, seg_len))
    pos = int(cursor) % int(VALUES_PER_LINE)
    projected_fill = int(pos + share)
    carry_over = max(0, int(seg_len) - share)
    seg_len_threshold = int(HOL_CONSTRAINED_FAT_TAIL_SEG_LEN_THRESHOLD_DEFAULT)
    if share <= 0:
        return (0, 0, 0), "share_zero", int(projected_fill), int(seg_len)
    if float(shared_line_head_risk) <= 0.0:
        return (0, 0, 0), "risk_zero", int(projected_fill), int(seg_len)
    if projected_fill < int(HOL_CONSTRAINED_FAT_TAIL_FILL_THRESHOLD_DEFAULT):
        return (0, 0, 0), "fill_below_threshold", int(projected_fill), int(seg_len)
    if (
        projected_fill == int(VALUES_PER_LINE)
        and carry_over >= int(HOL_CONSTRAINED_FAT_TAIL_SPILL_THRESHOLD_DEFAULT)
    ):
        seg_len_threshold = int(HOL_CONSTRAINED_FAT_TAIL_SEG_LEN_RELAXED_THRESHOLD_DEFAULT)
    if int(seg_len) < seg_len_threshold:
        return (0, 0, 0), "seg_len_below_threshold", int(projected_fill), int(seg_len)
    return (1, int(projected_fill), int(seg_len)), "trigger", int(projected_fill), int(seg_len)


def _order_by_profile_constrained_greedy(
    keys: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    *,
    freq: Dict[int, int],
    trans: Dict[Tuple[int, int], int],
    risk_stats: Dict[int, Dict[str, float]],
    neighbor_pool: int,
    fallback_pool: int,
    enable_fat_tail_guard: bool,
) -> Tuple[List[int], Dict[str, int]]:
    diag_stats = {
        "fat_tail_guard_eval_total": 0,
        "fat_tail_guard_trigger_total": 0,
        "fat_tail_guard_reason_share_zero_total": 0,
        "fat_tail_guard_reason_risk_zero_total": 0,
        "fat_tail_guard_reason_fill_below_threshold_total": 0,
        "fat_tail_guard_reason_seg_len_below_threshold_total": 0,
        "fat_tail_guard_projected_fill_max": 0,
        "fat_tail_guard_seg_len_max": 0,
    }
    remaining = {int(k) for k in keys}
    if not remaining:
        return [], diag_stats

    def _fallback_sort_key(pre: int) -> Tuple[int, int, int]:
        return (
            -int(freq.get(pre, 0)),
            -int(len(pre_to_pairs.get(pre, []))),
            int(pre),
        )

    nbr_weights: Dict[int, Dict[int, int]] = defaultdict(dict)
    for (src, dst), weight in trans.items():
        if src == dst or weight <= 0:
            continue
        s = int(src)
        d = int(dst)
        w = int(weight)
        nbr_weights[s][d] = int(nbr_weights[s].get(d, 0) + w)
        nbr_weights[d][s] = int(nbr_weights[d].get(s, 0) + w)

    neighbor_order: Dict[int, List[int]] = {}
    for src, nbrs in nbr_weights.items():
        ordered = sorted(
            nbrs.items(),
            key=lambda kv: (
                -int(kv[1]),
                -int(freq.get(int(kv[0]), 0)),
                -int(len(pre_to_pairs.get(int(kv[0]), []))),
                int(kv[0]),
            ),
        )
        neighbor_order[int(src)] = [int(dst) for dst, _ in ordered]

    fallback_order = sorted((int(k) for k in keys), key=_fallback_sort_key)
    fallback_rank = {int(pre): idx for idx, pre in enumerate(fallback_order)}
    fallback_idx = 0

    def _pop_best_fallback() -> int:
        nonlocal fallback_idx
        while fallback_idx < len(fallback_order):
            cand = int(fallback_order[fallback_idx])
            fallback_idx += 1
            if cand in remaining:
                return cand
        raise RuntimeError("fallback order exhausted before remaining became empty")

    order: List[int] = []
    cur = _pop_best_fallback()
    order.append(int(cur))
    remaining.remove(int(cur))
    cursor = int(len(pre_to_pairs.get(int(cur), [])))

    while remaining:
        candidates: List[int] = []
        seen = set()

        for nxt in neighbor_order.get(int(cur), []):
            cand = int(nxt)
            if cand not in remaining or cand in seen:
                continue
            candidates.append(cand)
            seen.add(cand)
            if len(candidates) >= int(max(1, neighbor_pool)):
                break

        for cand in fallback_order:
            cand_i = int(cand)
            if cand_i not in remaining or cand_i in seen:
                continue
            candidates.append(cand_i)
            seen.add(cand_i)
            if len(candidates) >= int(max(1, neighbor_pool)) + int(max(1, fallback_pool)):
                break

        if not candidates:
            nxt = _pop_best_fallback()
            order.append(int(nxt))
            remaining.remove(int(nxt))
            cursor += int(len(pre_to_pairs.get(int(nxt), [])))
            cur = int(nxt)
            continue

        neighbor_rank = {int(pre): idx for idx, pre in enumerate(neighbor_order.get(int(cur), []))}
        prev_risk = _hol_risk_value(risk_stats, int(cur))

        def _candidate_key(pre: int) -> Tuple[float, float, int, Tuple[int, int, int]]:
            seg_len = int(len(pre_to_pairs.get(int(pre), [])))
            share = float(_tail_share_count(cursor, seg_len))
            cand_risk = _hol_risk_value(risk_stats, int(pre))
            shared_line_head_risk = share * (prev_risk + cand_risk)
            fat_tail_guard = (0, 0, 0)
            if bool(enable_fat_tail_guard):
                fat_tail_guard, reason, projected_fill, guard_seg_len = _fat_tail_guard_state(
                    cursor=int(cursor),
                    seg_len=int(seg_len),
                    shared_line_head_risk=float(shared_line_head_risk),
                )
                diag_stats["fat_tail_guard_eval_total"] += 1
                diag_stats["fat_tail_guard_projected_fill_max"] = max(
                    int(diag_stats["fat_tail_guard_projected_fill_max"]),
                    int(projected_fill),
                )
                diag_stats["fat_tail_guard_seg_len_max"] = max(
                    int(diag_stats["fat_tail_guard_seg_len_max"]),
                    int(guard_seg_len),
                )
                if reason == "trigger":
                    diag_stats["fat_tail_guard_trigger_total"] += 1
                elif reason == "share_zero":
                    diag_stats["fat_tail_guard_reason_share_zero_total"] += 1
                elif reason == "risk_zero":
                    diag_stats["fat_tail_guard_reason_risk_zero_total"] += 1
                elif reason == "fill_below_threshold":
                    diag_stats["fat_tail_guard_reason_fill_below_threshold_total"] += 1
                elif reason == "seg_len_below_threshold":
                    diag_stats["fat_tail_guard_reason_seg_len_below_threshold_total"] += 1
            return (
                fat_tail_guard,
                shared_line_head_risk,
                cand_risk,
                int(neighbor_rank.get(int(pre), 1_000_000 + fallback_rank.get(int(pre), 1_000_000))),
                _fallback_sort_key(int(pre)),
            )

        nxt = min(candidates, key=_candidate_key)
        order.append(int(nxt))
        remaining.remove(int(nxt))
        cursor += int(len(pre_to_pairs.get(int(nxt), [])))
        cur = int(nxt)

    return order, diag_stats


def _order_by_profile_dual_guard_greedy(
    keys: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    *,
    freq: Dict[int, int],
    trans: Dict[Tuple[int, int], int],
    risk_stats: Dict[int, Dict[str, float]],
    neighbor_pool: int,
    fallback_pool: int,
    enable_fat_tail_guard: bool,
    selector_mode: str = "hard_lex",
) -> Tuple[List[int], Dict[str, object]]:
    diag_stats: Dict[str, object] = {
        "fat_tail_guard_eval_total": 0,
        "fat_tail_guard_trigger_total": 0,
        "fat_tail_guard_reason_share_zero_total": 0,
        "fat_tail_guard_reason_risk_zero_total": 0,
        "fat_tail_guard_reason_fill_below_threshold_total": 0,
        "fat_tail_guard_reason_seg_len_below_threshold_total": 0,
        "fat_tail_guard_projected_fill_max": 0,
        "fat_tail_guard_seg_len_max": 0,
    }
    dual_state = _build_dual_guard_state(risk_stats)
    diag_stats.update(_dual_guard_stats(dual_state))

    remaining = {int(k) for k in keys}
    if not remaining:
        return [], diag_stats

    def _fallback_sort_key(pre: int) -> Tuple[int, int, int]:
        return (
            -int(freq.get(pre, 0)),
            -int(len(pre_to_pairs.get(pre, []))),
            int(pre),
        )

    nbr_weights: Dict[int, Dict[int, int]] = defaultdict(dict)
    for (src, dst), weight in trans.items():
        if src == dst or weight <= 0:
            continue
        s = int(src)
        d = int(dst)
        w = int(weight)
        nbr_weights[s][d] = int(nbr_weights[s].get(d, 0) + w)
        nbr_weights[d][s] = int(nbr_weights[d].get(s, 0) + w)

    neighbor_order: Dict[int, List[int]] = {}
    for src, nbrs in nbr_weights.items():
        ordered = sorted(
            nbrs.items(),
            key=lambda kv: (
                -int(kv[1]),
                -int(freq.get(int(kv[0]), 0)),
                -int(len(pre_to_pairs.get(int(kv[0]), []))),
                int(kv[0]),
            ),
        )
        neighbor_order[int(src)] = [int(dst) for dst, _ in ordered]

    fallback_order = sorted((int(k) for k in keys), key=_fallback_sort_key)
    fallback_rank = {int(pre): idx for idx, pre in enumerate(fallback_order)}
    fallback_idx = 0

    def _pop_best_fallback() -> int:
        nonlocal fallback_idx
        while fallback_idx < len(fallback_order):
            cand = int(fallback_order[fallback_idx])
            fallback_idx += 1
            if cand in remaining:
                return cand
        raise RuntimeError("fallback order exhausted before remaining became empty")

    weak_rank = dict(dual_state.get("weak_rank", {}))
    target_set = set(dual_state.get("target_set", set()))

    order: List[int] = []
    cur = _pop_best_fallback()
    order.append(int(cur))
    remaining.remove(int(cur))
    cursor = int(len(pre_to_pairs.get(int(cur), [])))

    while remaining:
        candidates: List[int] = []
        seen = set()

        for nxt in neighbor_order.get(int(cur), []):
            cand = int(nxt)
            if cand not in remaining or cand in seen:
                continue
            candidates.append(cand)
            seen.add(cand)
            if len(candidates) >= int(max(1, neighbor_pool)):
                break

        for cand in fallback_order:
            cand_i = int(cand)
            if cand_i not in remaining or cand_i in seen:
                continue
            candidates.append(cand_i)
            seen.add(cand_i)
            if len(candidates) >= int(max(1, neighbor_pool)) + int(max(1, fallback_pool)):
                break

        if not candidates:
            nxt = _pop_best_fallback()
            order.append(int(nxt))
            remaining.remove(int(nxt))
            cursor += int(len(pre_to_pairs.get(int(nxt), [])))
            cur = int(nxt)
            continue

        neighbor_rank = {int(pre): idx for idx, pre in enumerate(neighbor_order.get(int(cur), []))}
        prev_risk = _hol_risk_value(risk_stats, int(cur))
        prev_target_score = float(risk_stats.get(int(cur), {}).get("target_score", 0.0))
        prev_is_target = int(cur) in target_set

        def _candidate_key(pre: int) -> Tuple[object, ...]:
            entry = _dual_guard_step_entry(
                prev=int(cur),
                cand=int(pre),
                cursor=int(cursor),
                pre_to_pairs=pre_to_pairs,
                risk_stats=risk_stats,
                target_set=target_set,
                weak_rank=weak_rank,
            )
            seg_len = int(entry.get("seg_len", 0))
            cand_risk = float(entry.get("cand_risk", 0.0))
            cand_target_score = float(entry.get("target_score", 0.0))
            cand_is_target = bool(entry.get("cand_is_target", 0))
            weak_hit_rank = int(entry.get("weak_hit_rank_raw", 1_000_000))
            shared_line_head_risk = float(entry.get("shared_line_head_risk", 0.0))
            target_penalty = float(entry.get("target_displacement_penalty", 0.0))
            neighbor_penalty = float(entry.get("neighborhood_drift_penalty", 0.0))
            fat_tail_guard = (0, 0, 0)
            if bool(enable_fat_tail_guard):
                fat_tail_guard, reason, projected_fill, guard_seg_len = _fat_tail_guard_state(
                    cursor=int(cursor),
                    seg_len=int(seg_len),
                    shared_line_head_risk=float(shared_line_head_risk),
                )
                diag_stats["fat_tail_guard_eval_total"] = int(diag_stats["fat_tail_guard_eval_total"]) + 1
                diag_stats["fat_tail_guard_projected_fill_max"] = max(
                    int(diag_stats["fat_tail_guard_projected_fill_max"]),
                    int(projected_fill),
                )
                diag_stats["fat_tail_guard_seg_len_max"] = max(
                    int(diag_stats["fat_tail_guard_seg_len_max"]),
                    int(guard_seg_len),
                )
                if reason == "trigger":
                    diag_stats["fat_tail_guard_trigger_total"] = int(diag_stats["fat_tail_guard_trigger_total"]) + 1
                elif reason == "share_zero":
                    diag_stats["fat_tail_guard_reason_share_zero_total"] = int(diag_stats["fat_tail_guard_reason_share_zero_total"]) + 1
                elif reason == "risk_zero":
                    diag_stats["fat_tail_guard_reason_risk_zero_total"] = int(diag_stats["fat_tail_guard_reason_risk_zero_total"]) + 1
                elif reason == "fill_below_threshold":
                    diag_stats["fat_tail_guard_reason_fill_below_threshold_total"] = int(diag_stats["fat_tail_guard_reason_fill_below_threshold_total"]) + 1
                elif reason == "seg_len_below_threshold":
                    diag_stats["fat_tail_guard_reason_seg_len_below_threshold_total"] = int(diag_stats["fat_tail_guard_reason_seg_len_below_threshold_total"]) + 1

            neighbor_guard = (
                0 if prev_is_target and weak_hit_rank < 1_000_000 else 1,
                int(weak_hit_rank),
                -float(prev_target_score + cand_target_score),
            )
            target_guard = (
                0 if cand_is_target else 1,
                -float(cand_target_score),
                int(seg_len),
                int(cursor + seg_len),
            )
            if str(selector_mode) == "numeric_penalty":
                return (
                    fat_tail_guard,
                    float(neighbor_penalty),
                    float(target_penalty),
                    float(shared_line_head_risk),
                    float(cand_risk),
                    int(neighbor_rank.get(int(pre), 1_000_000 + fallback_rank.get(int(pre), 1_000_000))),
                    _fallback_sort_key(int(pre)),
                )
            return (
                fat_tail_guard,
                neighbor_guard,
                target_guard,
                float(shared_line_head_risk),
                float(cand_risk),
                int(neighbor_rank.get(int(pre), 1_000_000 + fallback_rank.get(int(pre), 1_000_000))),
                _fallback_sort_key(int(pre)),
            )

        nxt = min(candidates, key=_candidate_key)
        order.append(int(nxt))
        remaining.remove(int(nxt))
        cursor += int(len(pre_to_pairs.get(int(nxt), [])))
        cur = int(nxt)

    return order, diag_stats


def _choose_physical_order(
    *,
    order_mode: str,
    keys: Sequence[int],
    slot_keys: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    profile_path: Optional[Path],
    profile_lookahead: int,
    hol_profile_path: Optional[Path],
    hol_head_k: int,
    hol_head_bonus: int,
) -> Tuple[List[int], Dict[str, int]]:
    stats = {
        "profile_windows": 0,
        "profile_unique_pres": 0,
        "profile_adjacent_pairs_total": 0,
        "hol_profile_rows": 0,
        "hol_profile_unique_pres": 0,
        "hol_profile_head_hits_total": 0,
        "hol_profile_head_depth_sum_total": 0,
        "hol_head_k": int(hol_head_k),
        "hol_head_bonus": int(hol_head_bonus),
    }
    mode = str(order_mode)
    if mode == ORDER_SLOT:
        return [int(v) for v in slot_keys], stats
    if mode == ORDER_PRE:
        return sorted(int(v) for v in keys), stats
    if mode not in (
        ORDER_PROFILE,
        ORDER_PROFILE_SIDRUN,
        ORDER_HOL_PROFILE,
        ORDER_HOL_CONSTRAINED_V2,
        ORDER_HOL_CONSTRAINED_V2_1,
        ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V1,
        ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V2,
        ORDER_HOL_DUAL_GUARD_V3_SHADOW,
        ORDER_HOL_DUAL_GUARD_V3,
        ORDER_HOL_DUAL_GUARD_V4,
        ORDER_OFFLINE_ANCHOR_SEPARATOR_V1,
        ORDER_OFFLINE_ANCHOR_SEPARATOR_V1_SHADOW,
    ):
        raise ValueError(f"unsupported order_mode={mode}")
    if profile_path is None:
        raise ValueError(f"{mode} requires profile_path")

    seqs = _load_profile_sequences(profile_path)
    freq, trans = _build_profile_graph(seqs, lookahead=int(profile_lookahead))
    stats["profile_windows"] = int(len(seqs))
    stats["profile_unique_pres"] = int(len(freq))
    stats["profile_adjacent_pairs_total"] = int(sum(int(v) for v in trans.values()))
    if mode == ORDER_HOL_PROFILE:
        hol_head_hits, hol_stats = _load_hol_profile_head_stats(
            hol_profile_path,
            head_k=int(hol_head_k),
        )
        stats.update(hol_stats)
        blended_freq = _blend_profile_freq_with_hol_head_hits(
            freq,
            hol_head_hits,
            head_bonus=int(hol_head_bonus),
        )
        order = _order_by_profile_greedy(keys, pre_to_pairs, freq=blended_freq, trans=trans)
        return order, stats
    if mode in (
        ORDER_HOL_CONSTRAINED_V2,
        ORDER_HOL_CONSTRAINED_V2_1,
        ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V1,
        ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V2,
        ORDER_HOL_DUAL_GUARD_V3_SHADOW,
        ORDER_HOL_DUAL_GUARD_V3,
        ORDER_HOL_DUAL_GUARD_V4,
        ORDER_OFFLINE_ANCHOR_SEPARATOR_V1,
        ORDER_OFFLINE_ANCHOR_SEPARATOR_V1_SHADOW,
    ):
        risk_stats, hol_stats = _load_hol_profile_risk_stats(
            hol_profile_path,
            head_k=int(hol_head_k),
        )
        stats.update(hol_stats)
        if mode in (ORDER_HOL_DUAL_GUARD_V3, ORDER_HOL_DUAL_GUARD_V4):
            order, diag_stats = _order_by_profile_dual_guard_greedy(
                keys,
                pre_to_pairs,
                freq=freq,
                trans=trans,
                risk_stats=risk_stats,
                neighbor_pool=int(HOL_CONSTRAINED_NEIGHBOR_POOL_DEFAULT),
                fallback_pool=int(HOL_CONSTRAINED_FALLBACK_POOL_DEFAULT),
                enable_fat_tail_guard=True,
                selector_mode=("numeric_penalty" if mode == ORDER_HOL_DUAL_GUARD_V4 else "hard_lex"),
            )
        else:
            order, diag_stats = _order_by_profile_constrained_greedy(
                keys,
                pre_to_pairs,
                freq=freq,
                trans=trans,
                risk_stats=risk_stats,
                neighbor_pool=int(HOL_CONSTRAINED_NEIGHBOR_POOL_DEFAULT),
                fallback_pool=int(HOL_CONSTRAINED_FALLBACK_POOL_DEFAULT),
                enable_fat_tail_guard=(
                    mode in (
                        ORDER_HOL_CONSTRAINED_V2_1,
                        ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V1,
                        ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V2,
                        ORDER_HOL_DUAL_GUARD_V3_SHADOW,
                        ORDER_OFFLINE_ANCHOR_SEPARATOR_V1,
                        ORDER_OFFLINE_ANCHOR_SEPARATOR_V1_SHADOW,
                    )
                ),
            )
        stats.update(diag_stats)
        if mode in (
            ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V1,
            ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V2,
        ):
            order, repair_stats = _apply_rowband_stripe_repair(
                order,
                pre_to_pairs,
                block_values=int(ROWBAND_STRIPE_BLOCK_VALUES_DEFAULT),
                row_values=int(ROWBAND_STRIPE_ROW_VALUES_DEFAULT),
                stripe_rows=int(ROWBAND_STRIPE_ROWS_DEFAULT),
                band_values=(
                    int(ROWBAND_STRIPE_BAND_VALUES_DEFAULT)
                    if mode == ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V2
                    else int(ROWBAND_STRIPE_ROW_VALUES_DEFAULT)
                ),
            )
            stats.update(repair_stats)
        if mode == ORDER_HOL_DUAL_GUARD_V3_SHADOW:
            stats.update(_dual_guard_shadow_stats(stats))
            stats.update(
                _collect_dual_guard_observe_stats(
                    order,
                    pre_to_pairs,
                    risk_stats,
                    prefix="hol_dual_guard_shadow",
                )
            )
        elif mode == ORDER_HOL_DUAL_GUARD_V3:
            stats["hol_dual_guard_enabled"] = 1
        elif mode == ORDER_HOL_DUAL_GUARD_V4:
            stats["hol_dual_guard_enabled"] = 1
            stats.update(
                _collect_dual_guard_observe_stats(
                    order,
                    pre_to_pairs,
                    risk_stats,
                    prefix="hol_dual_guard",
                )
            )
        elif mode == ORDER_OFFLINE_ANCHOR_SEPARATOR_V1:
            plan = _build_anchor_separator_layout_plan(
                keys,
                pre_to_pairs,
                freq=freq,
                trans=trans,
                risk_stats=risk_stats,
                baseline_order=order,
            )
            stats.update(_anchor_separator_plan_stats(plan))
            return list(int(pre) for pre in plan.get("plan_order", [])), stats
        elif mode == ORDER_OFFLINE_ANCHOR_SEPARATOR_V1_SHADOW:
            plan = _build_anchor_separator_shadow_plan(
                keys,
                pre_to_pairs,
                freq=freq,
                trans=trans,
                risk_stats=risk_stats,
                baseline_order=order,
            )
            stats.update(_anchor_separator_shadow_stats(plan))
        return order, stats
    if mode == ORDER_PROFILE_SIDRUN:
        order = _order_by_profile_sidrun_reg(keys, pre_to_pairs, freq=freq, trans=trans)
    else:
        order = _order_by_profile_greedy(keys, pre_to_pairs, freq=freq, trans=trans)
    return order, stats


def _build_plp_result(
    edges: Sequence[base.Edge],
    *,
    bucket_target: int,
    max_seed_tries: int,
    index_version: int,
    order_mode: str,
    profile_path: Optional[Path],
    profile_lookahead: int,
    hol_profile_path: Optional[Path],
    hol_head_k: int,
    hol_head_bonus: int,
) -> Tuple[base.BuildResult, Dict[int, List[Tuple[int, float]]], List[int], List[int], List[int], Dict[str, int], Dict[str, object]]:
    premphf_result, pre_to_pairs, keys, slot_keys = base._build_premphf(
        edges,
        bucket_target=int(bucket_target),
        max_seed_tries=int(max_seed_tries),
    )
    if int(index_version) == INDEX_VERSION_V4:
        result, v4_extra = _build_plp_bucket_block_result(
            premphf_result=premphf_result,
            pre_to_pairs=pre_to_pairs,
            keys=keys,
            slot_keys=slot_keys,
        )
        physical_pre_order = list(int(v) for v in v4_extra.get('physical_pre_order', []))
        return result, pre_to_pairs, list(int(v) for v in keys), list(int(v) for v in slot_keys), physical_pre_order, {
            'profile_windows': 0,
            'profile_unique_pres': 0,
            'profile_adjacent_pairs_total': 0,
        }, v4_extra

    physical_pre_order, order_stats = _choose_physical_order(
        order_mode=str(order_mode),
        keys=keys,
        slot_keys=slot_keys,
        pre_to_pairs=pre_to_pairs,
        profile_path=profile_path,
        profile_lookahead=int(profile_lookahead),
        hol_profile_path=hol_profile_path,
        hol_head_k=int(hol_head_k),
        hol_head_bonus=int(hol_head_bonus),
    )

    expected = sorted(int(v) for v in keys)
    actual = sorted(int(v) for v in physical_pre_order)
    if actual != expected:
        raise ValueError(
            f"physical_pre_order mismatch: expected {len(expected)} pres, got {len(actual)} pres"
        )

    base_by_pre: Dict[int, int] = {}
    values: List[float] = []
    for pre in physical_pre_order:
        seq = pre_to_pairs.get(int(pre), [])
        base_by_pre[int(pre)] = len(values)
        for _, w in seq:
            values.append(float(w))

    slot_base: List[int] = [0] * len(slot_keys)
    slot_len: List[int] = [0] * len(slot_keys)
    for slot, pre in enumerate(slot_keys):
        seq = pre_to_pairs.get(int(pre), [])
        slot_base[slot] = int(base_by_pre[int(pre)])
        slot_len[slot] = int(len(seq))

    rank_by_pre: Dict[int, int] = {int(pre): idx for idx, pre in enumerate(physical_pre_order)}
    slot_rank: List[int] = [int(rank_by_pre[int(pre)]) for pre in slot_keys]

    result = base.BuildResult(
        seed=int(premphf_result.seed),
        bucket_count=int(premphf_result.bucket_count),
        pre_count=int(premphf_result.pre_count),
        edges_total=int(len(values)),
        slot_base=slot_base,
        slot_len=slot_len,
        pilots=list(int(v) for v in premphf_result.pilots),
        values=values,
        slot_rank=slot_rank,
    )
    return result, pre_to_pairs, list(int(v) for v in keys), list(int(v) for v in slot_keys), physical_pre_order, order_stats, {}


def _estimate_layout_stats(
    *,
    physical_pre_order: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    order_stats: Dict[str, int],
) -> Dict[str, float]:
    per_pre_line_range: Dict[int, Tuple[int, int]] = {}
    line_pres: Dict[int, set[int]] = defaultdict(set)
    cursor = 0
    for pre in physical_pre_order:
        seg_len = int(len(pre_to_pairs.get(int(pre), [])))
        if seg_len <= 0:
            continue
        start = cursor
        end = cursor + seg_len - 1
        start_line = start // VALUES_PER_LINE
        end_line = end // VALUES_PER_LINE
        per_pre_line_range[int(pre)] = (start_line, end_line)
        for line in range(start_line, end_line + 1):
            line_pres[line].add(int(pre))
        cursor += seg_len

    lines_with_multi_pre = 0
    pres_per_line_total = 0
    for pres in line_pres.values():
        cnt = len(pres)
        pres_per_line_total += cnt
        if cnt > 1:
            lines_with_multi_pre += 1

    same_line_est = 0
    adjacent_total = int(order_stats.get("profile_adjacent_pairs_total", 0))
    if adjacent_total > 0:
        # Rebuild a lightweight overlap score from the already chosen physical ranges.
        pass

    return {
        "line_size_bytes": float(LINE_SIZE_BYTES),
        "values_per_line": float(VALUES_PER_LINE),
        "physical_line_count": float(len(line_pres)),
        "lines_with_multi_pre": float(lines_with_multi_pre),
        "avg_pres_per_line": float(pres_per_line_total / len(line_pres)) if line_pres else 0.0,
        "multi_pre_line_ratio": float(lines_with_multi_pre / len(line_pres)) if line_pres else 0.0,
    }


def _estimate_profile_same_line(
    *,
    profile_path: Optional[Path],
    profile_lookahead: int,
    physical_pre_order: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
) -> int:
    if profile_path is None or not profile_path.is_file():
        return 0
    seqs = _load_profile_sequences(profile_path)
    _, trans = _build_profile_graph(seqs, lookahead=int(profile_lookahead))
    if not trans:
        return 0

    per_pre_line_range: Dict[int, Tuple[int, int]] = {}
    cursor = 0
    for pre in physical_pre_order:
        seg_len = int(len(pre_to_pairs.get(int(pre), [])))
        if seg_len <= 0:
            continue
        start = cursor
        end = cursor + seg_len - 1
        per_pre_line_range[int(pre)] = (start // VALUES_PER_LINE, end // VALUES_PER_LINE)
        cursor += seg_len

    same_line = 0
    for (src, dst), weight in trans.items():
        a = per_pre_line_range.get(int(src))
        b = per_pre_line_range.get(int(dst))
        if a is None or b is None:
            continue
        if max(a[0], b[0]) <= min(a[1], b[1]):
            same_line += int(weight)
    return int(same_line)


def _bits_for_max_value(max_value: int) -> int:
    v = int(max_value)
    if v <= 0:
        return 1
    return int(v.bit_length())


def _pack_fixed_u64(values: Sequence[int], bit_width: int) -> List[int]:
    bits = int(bit_width)
    if bits <= 0:
        raise ValueError(f"invalid bit_width={bit_width}")
    total_bits = len(values) * bits
    words: List[int] = [0] * ((total_bits + 63) // 64)
    for i, value in enumerate(values):
        base._pack_value_bits(words, i * bits, bits, int(value))
    return words


def _build_monotone_ef(values: Sequence[int], *, max_value: int) -> base.EfEncoded:
    seq = [int(v) for v in values]
    if not seq:
        return base.EfEncoded(l=0, low_words=[], high_words=[], select_step=int(base.EF_SELECT_STEP_DEFAULT), select_hints=[])
    for i, v in enumerate(seq):
        if v < 0:
            raise ValueError(f"negative monotone value at i={i}: {v}")
        if i > 0 and v < seq[i - 1]:
            raise ValueError(f"non-monotone sequence at i={i}: prev={seq[i-1]} now={v}")
    if seq[-1] != int(max_value):
        raise ValueError(f"terminal mismatch: last={seq[-1]} max_value={int(max_value)}")
    return base._build_ef_from_slot_base(seq[:-1], int(max_value), int(base.EF_SELECT_STEP_DEFAULT))


def _build_v6_sid_run_codec(
    *,
    result: base.BuildResult,
    keys: Sequence[int],
    physical_pre_order: Sequence[int],
) -> Dict[str, object]:
    n = int(result.pre_count)
    sorted_keys = [int(v) for v in keys]
    if len(sorted_keys) != n:
        raise ValueError(f"v6 key count mismatch: got={len(sorted_keys)} pre_count={n}")
    if n == 0:
        empty = base.EfEncoded(l=0, low_words=[], high_words=[], select_step=int(base.EF_SELECT_STEP_DEFAULT), select_hints=[])
        return {
            'key_max': 0,
            'keys_ef': empty,
            'run_count': 0,
            'run_rank_bits': 0,
            'run_rank_words': [],
            'run_ends_ef': empty,
            'base_ef': empty,
            'run_breaks': 0,
            'avg_run_len': 0.0,
            'max_run_len': 0,
        }

    rank_by_pre: Dict[int, int] = {int(pre): idx for idx, pre in enumerate(physical_pre_order)}
    sid_ranks: List[int] = []
    for pre in sorted_keys:
        rank = rank_by_pre.get(int(pre))
        if rank is None:
            raise ValueError(f"v6 missing physical rank for pre={pre}")
        sid_ranks.append(int(rank))

    run_ends: List[int] = []
    run_bases: List[int] = []
    run_lens: List[int] = []
    start = 0
    while start < n:
        end = start + 1
        base_rank = int(sid_ranks[start])
        while end < n and int(sid_ranks[end]) == int(sid_ranks[end - 1]) + 1:
            end += 1
        run_ends.append(int(end))
        run_bases.append(int(base_rank))
        run_lens.append(int(end - start))
        start = end

    base_by_rank = base._build_physical_base_by_rank(result)
    run_rank_bits = base._rank_bits_for_count(n)
    return {
        'key_max': int(sorted_keys[-1]),
        'keys_ef': _build_monotone_ef(sorted_keys, max_value=int(sorted_keys[-1])),
        'run_count': int(len(run_bases)),
        'run_rank_bits': int(run_rank_bits),
        'run_rank_words': _pack_fixed_u64(run_bases, int(run_rank_bits)) if run_bases else [],
        'run_ends_ef': _build_monotone_ef(run_ends, max_value=n),
        'base_ef': base._build_ef_from_slot_base(base_by_rank, int(result.edges_total), int(base.EF_SELECT_STEP_DEFAULT)),
        'run_breaks': int(max(0, len(run_bases) - 1)),
        'avg_run_len': float(sum(run_lens) / len(run_lens)) if run_lens else 0.0,
        'max_run_len': int(max(run_lens)) if run_lens else 0,
    }


def _build_v7_len_block_codec_from_lens(
    *,
    lens: Sequence[int],
    edges_total: int,
    block_size: int,
) -> Dict[str, object]:
    n = int(len(lens))
    bsz = int(block_size)
    if bsz <= 0:
        raise ValueError(f'invalid len block_size={block_size}')

    block_base_prefix: List[int] = []
    block_word_offset: List[int] = []
    block_mode: List[int] = []
    block_arg: List[int] = []
    payload_words: List[int] = []
    payload_bits_total = 0
    exc_total = 0
    block_count = (n + bsz - 1) // bsz
    prefix = 0

    for block in range(block_count):
        start = block * bsz
        end = min(n, start + bsz)
        blk = [int(v) for v in lens[start:end]]
        if not blk:
            raise ValueError(f'empty v7 len block={block}')
        block_base_prefix.append(int(prefix))
        block_word_offset.append(int(len(payload_words)))
        prefix += int(sum(blk))
        block_len = len(blk)
        max_len = max(blk)
        raw_bits = max(1, int(max_len.bit_length()))
        raw_total_bits = block_len * raw_bits

        if all(v == 1 for v in blk):
            block_mode.append(1)
            block_arg.append(0)
            continue

        exc_vals = [int(v) for v in blk if int(v) != 1]
        exc_bits = max(1, int(max(exc_vals).bit_length())) if exc_vals else 1
        bitmap_words = (block_len + 63) // 64
        bitmap_total_bits = bitmap_words * 64
        bitmap_total_bits += len(exc_vals) * exc_bits

        if bitmap_total_bits < raw_total_bits:
            block_mode.append(2)
            block_arg.append(int(exc_bits))
            bitmap: List[int] = [0] * bitmap_words
            packed_exc: List[int] = []
            for idx, v in enumerate(blk):
                if int(v) == 1:
                    continue
                word = idx >> 6
                bit = idx & 63
                bitmap[word] = (bitmap[word] | (1 << bit)) & 0xFFFFFFFFFFFFFFFF
                packed_exc.append(int(v))
            payload_words.extend(int(v) for v in bitmap)
            if packed_exc:
                payload_words.extend(int(v) for v in _pack_fixed_u64(packed_exc, int(exc_bits)))
            payload_bits_total += int(bitmap_total_bits)
            exc_total += int(len(exc_vals))
            continue

        block_mode.append(0)
        block_arg.append(int(raw_bits))
        payload_words.extend(int(v) for v in _pack_fixed_u64(blk, int(raw_bits)))
        payload_bits_total += int(raw_total_bits)

    if prefix != int(edges_total):
        raise ValueError(f'v7 len terminal mismatch: prefix={prefix} edges_total={int(edges_total)}')

    return {
        'block_size': int(bsz),
        'block_count': int(block_count),
        'block_base_prefix': block_base_prefix,
        'block_word_offset': block_word_offset,
        'block_mode': block_mode,
        'block_arg': block_arg,
        'payload_words': payload_words,
        'avg_payload_bits_per_pre': float(payload_bits_total / n) if n > 0 else 0.0,
        'exc_total': int(exc_total),
    }


def _build_v7_len_block_codec(
    *,
    result: base.BuildResult,
    physical_pre_order: Sequence[int],
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    block_size: int,
) -> Dict[str, object]:
    lens = [int(len(pre_to_pairs.get(int(pre), []))) for pre in physical_pre_order]
    if len(lens) != int(result.pre_count):
        raise ValueError(f'v7 len size mismatch: lens={len(lens)} pre_count={int(result.pre_count)}')
    return _build_v7_len_block_codec_from_lens(
        lens=lens,
        edges_total=int(result.edges_total),
        block_size=int(block_size),
    )


def _bucket_local_slot_pos(key: int, seed: int, bucket: int, pilot: int, nslots: int) -> int:
    if nslots <= 0:
        return 0
    bucket_seed = base._mix32(int(seed) ^ base._mix32(int(bucket) ^ 0x6D2B79F5))
    pilot_seed = (bucket_seed ^ (((int(pilot) + 1) * 0x9E3779B1) & 0xFFFFFFFF)) & 0xFFFFFFFF
    return int(base._h2(int(key), pilot_seed) % int(nslots))


def _search_bucket_local_pilot(pres: Sequence[int], *, seed: int, bucket: int) -> Tuple[int, List[int]]:
    s = int(len(pres))
    if s == 0:
        return 0, []
    if s == 1:
        return 0, [int(pres[0])]
    ordered = sorted(int(v) for v in pres)
    for limit in (256, 1 << int(base.PILOT_BITS), int(V4_PILOT_SEARCH_LIMIT)):
        start = 0 if limit == 256 else (256 if limit == (1 << int(base.PILOT_BITS)) else (1 << int(base.PILOT_BITS)))
        for pilot in range(start, limit):
            by_ord = [-1] * s
            ok = True
            for pre in ordered:
                ord_idx = int(_bucket_local_slot_pos(int(pre), int(seed), int(bucket), int(pilot), s))
                if by_ord[ord_idx] != -1:
                    ok = False
                    break
                by_ord[ord_idx] = int(pre)
            if ok and all(v != -1 for v in by_ord):
                return int(pilot), [int(v) for v in by_ord]
    raise ValueError(f"bucket-local pilot search failed size={s}")


def _build_v5_perm_codec(slot_rank: Sequence[int], *, block_size: int) -> Dict[str, object]:
    n = int(len(slot_rank))
    bsz = int(block_size)
    if bsz <= 0:
        raise ValueError(f"invalid block_size={block_size}")
    block_count = (n + bsz - 1) // bsz
    block_min_ranks: List[int] = []
    block_bits: List[int] = []
    block_word_offsets: List[int] = []
    payload_words: List[int] = []
    total_delta_bits = 0

    for block in range(block_count):
        start = block * bsz
        end = min(n, start + bsz)
        ranks = [int(v) for v in slot_rank[start:end]]
        if not ranks:
            raise ValueError(f"empty v5 rank block={block}")
        min_rank = min(ranks)
        max_rank = max(ranks)
        bits = 0 if max_rank == min_rank else _bits_for_max_value(max_rank - min_rank)
        block_min_ranks.append(int(min_rank))
        block_bits.append(int(bits))
        block_word_offsets.append(int(len(payload_words)))
        if bits > 0:
            deltas = [int(v) - int(min_rank) for v in ranks]
            words = _pack_fixed_u64(deltas, bits)
            payload_words.extend(int(v) for v in words)
            total_delta_bits += len(deltas) * int(bits)

    return {
        'block_size': int(bsz),
        'block_count': int(block_count),
        'block_min_ranks': [int(v) for v in block_min_ranks],
        'block_bits': [int(v) for v in block_bits],
        'block_word_offsets': [int(v) for v in block_word_offsets],
        'payload_words': [int(v) for v in payload_words],
        'avg_block_bits': float(total_delta_bits / n) if n > 0 else 0.0,
        'max_block_bits': int(max(block_bits) if block_bits else 0),
    }


def _write_index_bin_v6(
    path: Path,
    result: base.BuildResult,
    bucket_target: int,
    *,
    keys: Sequence[int],
    physical_pre_order: Sequence[int],
) -> Dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    codec = _build_v6_sid_run_codec(
        result=result,
        keys=keys,
        physical_pre_order=physical_pre_order,
    )
    keys_ef = codec['keys_ef']
    run_ends_ef = codec['run_ends_ef']
    base_ef = codec['base_ef']
    run_rank_words = list(int(v) for v in codec['run_rank_words'])

    header = struct.pack(
        '<8sIIIIIIIII',
        base.MAGIC,
        INDEX_VERSION_V6,
        int(result.pre_count),
        int(result.edges_total),
        int(bucket_target),
        0,
        int(base.HASH_KIND),
        int(base.FLAG_STRICT),
        0,
        0,
    )
    extra = struct.pack(
        '<' + 'I' * 20,
        int(codec['key_max']),
        int(keys_ef.l),
        int(len(keys_ef.low_words)),
        int(len(keys_ef.high_words)),
        int(keys_ef.select_step),
        int(len(keys_ef.select_hints)),
        int(codec['run_count']),
        int(codec['run_rank_bits']),
        int(len(run_rank_words)),
        int(run_ends_ef.l),
        int(len(run_ends_ef.low_words)),
        int(len(run_ends_ef.high_words)),
        int(run_ends_ef.select_step),
        int(len(run_ends_ef.select_hints)),
        int(base_ef.l),
        int(len(base_ef.low_words)),
        int(len(base_ef.high_words)),
        int(base_ef.select_step),
        int(len(base_ef.select_hints)),
        0,
    )

    with path.open('wb') as f:
        f.write(header)
        f.write(extra)
        if keys_ef.low_words:
            f.write(struct.pack('<' + 'Q' * len(keys_ef.low_words), *keys_ef.low_words))
        if keys_ef.high_words:
            f.write(struct.pack('<' + 'Q' * len(keys_ef.high_words), *keys_ef.high_words))
        if keys_ef.select_hints:
            f.write(struct.pack('<' + 'I' * len(keys_ef.select_hints), *keys_ef.select_hints))
        if run_rank_words:
            f.write(struct.pack('<' + 'Q' * len(run_rank_words), *run_rank_words))
        if run_ends_ef.low_words:
            f.write(struct.pack('<' + 'Q' * len(run_ends_ef.low_words), *run_ends_ef.low_words))
        if run_ends_ef.high_words:
            f.write(struct.pack('<' + 'Q' * len(run_ends_ef.high_words), *run_ends_ef.high_words))
        if run_ends_ef.select_hints:
            f.write(struct.pack('<' + 'I' * len(run_ends_ef.select_hints), *run_ends_ef.select_hints))
        if base_ef.low_words:
            f.write(struct.pack('<' + 'Q' * len(base_ef.low_words), *base_ef.low_words))
        if base_ef.high_words:
            f.write(struct.pack('<' + 'Q' * len(base_ef.high_words), *base_ef.high_words))
        if base_ef.select_hints:
            f.write(struct.pack('<' + 'I' * len(base_ef.select_hints), *base_ef.select_hints))

    idx_bytes = int(path.stat().st_size)
    key_bytes = int(len(keys_ef.low_words) * 8 + len(keys_ef.high_words) * 8 + len(keys_ef.select_hints) * 4)
    run_bytes = int(len(run_rank_words) * 8 + len(run_ends_ef.low_words) * 8 + len(run_ends_ef.high_words) * 8 + len(run_ends_ef.select_hints) * 4)
    base_bytes = int(len(base_ef.low_words) * 8 + len(base_ef.high_words) * 8 + len(base_ef.select_hints) * 4)
    return {
        'idx_bytes': idx_bytes,
        'key_bytes': key_bytes,
        'run_bytes': run_bytes,
        'base_bytes': base_bytes,
        'run_count': int(codec['run_count']),
        'run_breaks': int(codec['run_breaks']),
        'avg_run_len': float(codec['avg_run_len']),
        'max_run_len': int(codec['max_run_len']),
    }


def _write_index_bin_v7(
    path: Path,
    result: base.BuildResult,
    bucket_target: int,
    *,
    keys: Sequence[int],
    physical_pre_order: Sequence[int],
) -> Dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    codec = _build_v6_sid_run_codec(
        result=result,
        keys=keys,
        physical_pre_order=physical_pre_order,
    )
    # Rebuild exact lens from physical base so v7 stays strictly layout-preserving.
    base_by_rank = base._build_physical_base_by_rank(result)
    lens: List[int] = []
    for rank, cur in enumerate(base_by_rank):
        nxt = int(result.edges_total) if rank + 1 >= len(base_by_rank) else int(base_by_rank[rank + 1])
        lens.append(int(nxt - int(cur)))
    # Override len codec with exact base/rank-derived sequence.
    len_codec = _build_v7_len_block_codec_from_lens(
        lens=lens,
        edges_total=int(result.edges_total),
        block_size=int(V7_LEN_BLOCK_SIZE_DEFAULT),
    )

    keys_ef = codec['keys_ef']
    run_ends_ef = codec['run_ends_ef']
    run_rank_words = list(int(v) for v in codec['run_rank_words'])
    block_base_prefix = list(int(v) for v in len_codec['block_base_prefix'])
    block_word_offset = list(int(v) for v in len_codec['block_word_offset'])
    block_mode = list(int(v) for v in len_codec['block_mode'])
    block_arg = list(int(v) for v in len_codec['block_arg'])
    payload_words = list(int(v) for v in len_codec['payload_words'])
    block_base_bits = _bits_for_max_value(max(block_base_prefix) if block_base_prefix else 0)
    block_word_offset_bits = _bits_for_max_value(max(block_word_offset) if block_word_offset else 0)
    block_mode_bits = _bits_for_max_value(max(block_mode) if block_mode else 0)
    block_arg_bits = _bits_for_max_value(max(block_arg) if block_arg else 0)
    block_base_words = _pack_fixed_u64(block_base_prefix, int(block_base_bits))
    block_word_offset_words = _pack_fixed_u64(block_word_offset, int(block_word_offset_bits))
    block_mode_words = _pack_fixed_u64(block_mode, int(block_mode_bits))
    block_arg_words = _pack_fixed_u64(block_arg, int(block_arg_bits))

    header = struct.pack(
        '<8sIIIIIIIII',
        base.MAGIC,
        INDEX_VERSION_V7,
        int(result.pre_count),
        int(result.edges_total),
        int(bucket_target),
        0,
        int(base.HASH_KIND),
        int(base.FLAG_STRICT),
        0,
        0,
    )
    extra = struct.pack(
        '<' + 'I' * 26,
        int(codec['key_max']),
        int(keys_ef.l),
        int(len(keys_ef.low_words)),
        int(len(keys_ef.high_words)),
        int(keys_ef.select_step),
        int(len(keys_ef.select_hints)),
        int(codec['run_count']),
        int(codec['run_rank_bits']),
        int(len(run_rank_words)),
        int(run_ends_ef.l),
        int(len(run_ends_ef.low_words)),
        int(len(run_ends_ef.high_words)),
        int(run_ends_ef.select_step),
        int(len(run_ends_ef.select_hints)),
        int(len_codec['block_size']),
        int(len_codec['block_count']),
        int(block_base_bits),
        int(len(block_base_words)),
        int(block_word_offset_bits),
        int(len(block_word_offset_words)),
        int(block_mode_bits),
        int(len(block_mode_words)),
        int(block_arg_bits),
        int(len(block_arg_words)),
        int(len(payload_words)),
        0,
    )

    with path.open('wb') as f:
        f.write(header)
        f.write(extra)
        if keys_ef.low_words:
            f.write(struct.pack('<' + 'Q' * len(keys_ef.low_words), *keys_ef.low_words))
        if keys_ef.high_words:
            f.write(struct.pack('<' + 'Q' * len(keys_ef.high_words), *keys_ef.high_words))
        if keys_ef.select_hints:
            f.write(struct.pack('<' + 'I' * len(keys_ef.select_hints), *keys_ef.select_hints))
        if run_rank_words:
            f.write(struct.pack('<' + 'Q' * len(run_rank_words), *run_rank_words))
        if run_ends_ef.low_words:
            f.write(struct.pack('<' + 'Q' * len(run_ends_ef.low_words), *run_ends_ef.low_words))
        if run_ends_ef.high_words:
            f.write(struct.pack('<' + 'Q' * len(run_ends_ef.high_words), *run_ends_ef.high_words))
        if run_ends_ef.select_hints:
            f.write(struct.pack('<' + 'I' * len(run_ends_ef.select_hints), *run_ends_ef.select_hints))
        if block_base_words:
            f.write(struct.pack('<' + 'Q' * len(block_base_words), *block_base_words))
        if block_word_offset_words:
            f.write(struct.pack('<' + 'Q' * len(block_word_offset_words), *block_word_offset_words))
        if block_mode_words:
            f.write(struct.pack('<' + 'Q' * len(block_mode_words), *block_mode_words))
        if block_arg_words:
            f.write(struct.pack('<' + 'Q' * len(block_arg_words), *block_arg_words))
        if payload_words:
            f.write(struct.pack('<' + 'Q' * len(payload_words), *payload_words))

    idx_bytes = int(path.stat().st_size)
    key_bytes = int(len(keys_ef.low_words) * 8 + len(keys_ef.high_words) * 8 + len(keys_ef.select_hints) * 4)
    run_bytes = int(len(run_rank_words) * 8 + len(run_ends_ef.low_words) * 8 + len(run_ends_ef.high_words) * 8 + len(run_ends_ef.select_hints) * 4)
    base_bytes = int(len(block_base_words) * 8 + len(block_word_offset_words) * 8 + len(block_mode_words) * 8 + len(block_arg_words) * 8 + len(payload_words) * 8)
    return {
        'idx_bytes': idx_bytes,
        'key_bytes': key_bytes,
        'run_bytes': run_bytes,
        'base_bytes': base_bytes,
        'len_block_bytes': base_bytes,
        'len_block_size': int(len_codec['block_size']),
        'len_block_count': int(len_codec['block_count']),
        'len_avg_payload_bits_per_pre': float(len_codec['avg_payload_bits_per_pre']),
        'len_exc_total': int(len_codec['exc_total']),
        'run_count': int(codec['run_count']),
        'run_breaks': int(codec['run_breaks']),
        'avg_run_len': float(codec['avg_run_len']),
        'max_run_len': int(codec['max_run_len']),
    }


def _write_index_bin_v5(
    path: Path,
    result: base.BuildResult,
    bucket_target: int,
    *,
    block_size: int,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    codec = _build_v5_perm_codec(
        result.slot_rank if result.slot_rank else [int(i) for i in range(int(result.pre_count))],
        block_size=int(block_size),
    )
    base_by_rank = base._build_physical_base_by_rank(result)
    ef = base._build_ef_from_slot_base(base_by_rank, int(result.edges_total), int(base.EF_SELECT_STEP_DEFAULT))
    block_count = int(codec['block_count'])
    block_min_ranks = list(int(v) for v in codec['block_min_ranks'])
    block_bits = list(int(v) for v in codec['block_bits'])
    block_word_offsets = list(int(v) for v in codec['block_word_offsets'])
    payload_words = list(int(v) for v in codec['payload_words'])

    header = struct.pack(
        '<8sIIIIIIIII',
        base.MAGIC,
        INDEX_VERSION_V5,
        int(result.pre_count),
        int(result.edges_total),
        int(bucket_target),
        int(base.PILOT_BITS),
        int(base.HASH_KIND),
        int(base.FLAG_STRICT),
        int(result.seed),
        int(result.bucket_count),
    )
    extra = struct.pack(
        '<IIIIIIIII',
        int(codec['block_size']),
        int(block_count),
        int(block_count),
        int(len(payload_words)),
        int(ef.l),
        int(len(ef.low_words)),
        int(len(ef.high_words)),
        int(ef.select_step),
        int(len(ef.select_hints)),
    )

    with path.open('wb') as f:
        f.write(header)
        f.write(extra)
        for min_rank, bits, word_off in zip(block_min_ranks, block_bits, block_word_offsets):
            f.write(struct.pack('<III', int(min_rank), int(bits), int(word_off)))
        if payload_words:
            f.write(struct.pack('<' + 'Q' * len(payload_words), *payload_words))
        if ef.low_words:
            f.write(struct.pack('<' + 'Q' * len(ef.low_words), *ef.low_words))
        if ef.high_words:
            f.write(struct.pack('<' + 'Q' * len(ef.high_words), *ef.high_words))
        if ef.select_hints:
            f.write(struct.pack('<' + 'I' * len(ef.select_hints), *ef.select_hints))
        if result.pilots:
            f.write(struct.pack('<' + 'H' * len(result.pilots), *result.pilots))
    return path.stat().st_size


def _build_plp_bucket_block_result(
    *,
    premphf_result: base.BuildResult,
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    keys: Sequence[int],
    slot_keys: Sequence[int],
) -> Tuple[base.BuildResult, Dict[str, object]]:
    bucket_count = int(premphf_result.bucket_count)
    seed = int(premphf_result.seed)
    bucket_pres: List[List[int]] = [[] for _ in range(bucket_count)]
    for pre in keys:
        b = int(base._h1(int(pre), seed) % bucket_count)
        bucket_pres[b].append(int(pre))

    bucket_sizes: List[int] = [0] * bucket_count
    bucket_payloads: List[int] = [0] * bucket_count
    local_pilots: List[int] = [0] * bucket_count
    local_lens: List[int] = []
    values: List[float] = []
    physical_pre_order: List[int] = []
    base_by_pre: Dict[int, int] = {}
    local_ord_by_pre: Dict[int, int] = {}
    bucket_of_pre: Dict[int, int] = {}
    pilot_le255 = 0

    for bucket in range(bucket_count):
        pres = bucket_pres[bucket]
        bucket_sizes[bucket] = int(len(pres))
        if not pres:
            continue
        pilot, pres_by_ord = _search_bucket_local_pilot(pres, seed=seed, bucket=bucket)
        local_pilots[bucket] = int(pilot)
        if pilot <= 255:
            pilot_le255 += 1
        payload = 0
        for ord_idx, pre in enumerate(pres_by_ord):
            seq = pre_to_pairs.get(int(pre), [])
            physical_pre_order.append(int(pre))
            base_by_pre[int(pre)] = len(values)
            local_ord_by_pre[int(pre)] = int(ord_idx)
            bucket_of_pre[int(pre)] = int(bucket)
            ln = int(len(seq))
            local_lens.append(ln)
            bucket_payloads[bucket] += ln
            payload += ln
            for _, w in seq:
                values.append(float(w))
        if payload != bucket_payloads[bucket]:
            raise ValueError(f"payload mismatch bucket={bucket}")

    slot_base: List[int] = [0] * len(slot_keys)
    slot_len: List[int] = [0] * len(slot_keys)
    slot_rank: List[int] = [int(i) for i in range(len(slot_keys))]
    for slot, pre in enumerate(slot_keys):
        seq = pre_to_pairs.get(int(pre), [])
        slot_base[slot] = int(base_by_pre[int(pre)])
        slot_len[slot] = int(len(seq))
        bucket = int(bucket_of_pre[int(pre)])
        local_ord = int(local_ord_by_pre[int(pre)])
        _ = bucket
        _ = local_ord

    result = base.BuildResult(
        seed=int(seed),
        bucket_count=int(bucket_count),
        pre_count=int(premphf_result.pre_count),
        edges_total=int(len(values)),
        slot_base=slot_base,
        slot_len=slot_len,
        pilots=list(int(v) for v in local_pilots),
        values=values,
        slot_rank=slot_rank,
    )

    extra = {
        'bucket_sizes': [int(v) for v in bucket_sizes],
        'bucket_payloads': [int(v) for v in bucket_payloads],
        'local_lens': [int(v) for v in local_lens],
        'pilot_le255_count': int(pilot_le255),
        'pilot_overflow_count': int(bucket_count - pilot_le255),
        'max_bucket_size': int(max(bucket_sizes) if bucket_sizes else 0),
        'max_bucket_payload': int(max(bucket_payloads) if bucket_payloads else 0),
        'max_local_len': int(max(local_lens) if local_lens else 0),
        'physical_pre_order': [int(v) for v in physical_pre_order],
    }
    return result, extra



def _self_check_v4(
    *,
    result: base.BuildResult,
    pre_to_pairs: Dict[int, List[Tuple[int, float]]],
    keys: Sequence[int],
    bucket_sizes: Sequence[int],
    bucket_payloads: Sequence[int],
    local_lens: Sequence[int],
    core_tag: str,
) -> None:
    if len(result.pilots) != int(result.bucket_count):
        raise ValueError(f"[{core_tag}] pilots size mismatch")
    if len(bucket_sizes) != int(result.bucket_count):
        raise ValueError(f"[{core_tag}] bucket_sizes size mismatch")
    if len(bucket_payloads) != int(result.bucket_count):
        raise ValueError(f"[{core_tag}] bucket_payloads size mismatch")
    if len(local_lens) != int(result.pre_count):
        raise ValueError(f"[{core_tag}] local_lens size mismatch")

    entry_prefix: List[int] = []
    base_prefix: List[int] = []
    entry_acc = 0
    base_acc = 0
    for bucket in range(int(result.bucket_count)):
        entry_prefix.append(int(entry_acc))
        base_prefix.append(int(base_acc))
        entry_acc += int(bucket_sizes[bucket])
        base_acc += int(bucket_payloads[bucket])
    if entry_acc != int(result.pre_count):
        raise ValueError(f"[{core_tag}] pre_count mismatch in bucket_sizes")
    if base_acc != int(result.edges_total):
        raise ValueError(f"[{core_tag}] edges_total mismatch in bucket_payloads")

    seen_by_bucket: Dict[int, set] = defaultdict(set)
    for pre in keys:
        bucket = int(base._h1(int(pre), int(result.seed)) % int(result.bucket_count))
        bucket_size = int(bucket_sizes[bucket])
        if bucket_size <= 0:
            raise ValueError(f"[{core_tag}] empty bucket for pre={pre} bucket={bucket}")
        pilot = int(result.pilots[bucket])
        local_ord = int(_bucket_local_slot_pos(int(pre), int(result.seed), bucket, pilot, bucket_size))
        if local_ord < 0 or local_ord >= bucket_size:
            raise ValueError(f"[{core_tag}] local_ord oob pre={pre} bucket={bucket} ord={local_ord} size={bucket_size}")
        if local_ord in seen_by_bucket[bucket]:
            raise ValueError(f"[{core_tag}] duplicate local_ord bucket={bucket} ord={local_ord}")
        seen_by_bucket[bucket].add(local_ord)

        entry_idx = int(entry_prefix[bucket]) + local_ord
        if entry_idx < 0 or entry_idx >= len(local_lens):
            raise ValueError(f"[{core_tag}] local_lens idx oob pre={pre} idx={entry_idx}")
        ln = int(local_lens[entry_idx])
        if ln <= 0:
            raise ValueError(f"[{core_tag}] local len invalid pre={pre} idx={entry_idx} len={ln}")
        base_idx = int(base_prefix[bucket]) + sum(int(local_lens[int(entry_prefix[bucket]) + i]) for i in range(local_ord))
        exp_pairs = pre_to_pairs.get(int(pre), [])
        if ln != len(exp_pairs):
            raise ValueError(f"[{core_tag}] len mismatch pre={pre} got={ln} expect={len(exp_pairs)}")
        if base_idx < 0 or base_idx + ln > len(result.values):
            raise ValueError(f"[{core_tag}] base/len oob pre={pre} base={base_idx} len={ln}")
        for r, (_, w) in enumerate(exp_pairs):
            got = float(result.values[base_idx + r])
            if abs(got - float(w)) > 1e-8:
                raise ValueError(f"[{core_tag}] value mismatch pre={pre} rank={r} got={got} expect={w}")

    for bucket in range(int(result.bucket_count)):
        if len(seen_by_bucket.get(bucket, set())) != int(bucket_sizes[bucket]):
            raise ValueError(f"[{core_tag}] bucket coverage mismatch bucket={bucket}")
        start = int(entry_prefix[bucket])
        payload = sum(int(local_lens[start + i]) for i in range(int(bucket_sizes[bucket])))
        if payload != int(bucket_payloads[bucket]):
            raise ValueError(f"[{core_tag}] bucket payload mismatch bucket={bucket} got={payload} expect={bucket_payloads[bucket]}")


def _write_index_bin_v4(
    path: Path,
    result: base.BuildResult,
    bucket_target: int,
    *,
    bucket_sizes: Sequence[int],
    bucket_payloads: Sequence[int],
    local_lens: Sequence[int],
    block_span: int,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    bucket_count = int(result.bucket_count)
    if len(bucket_sizes) != bucket_count or len(bucket_payloads) != bucket_count:
        raise ValueError('bucket metadata size mismatch')
    if len(local_lens) != int(result.pre_count):
        raise ValueError('local_lens size mismatch')
    bucket_size_bits = _bits_for_max_value(max(bucket_sizes) if bucket_sizes else 0)
    bucket_payload_bits = _bits_for_max_value(max(bucket_payloads) if bucket_payloads else 0)
    local_len_bits = _bits_for_max_value(max(local_lens) if local_lens else 0)
    bucket_size_words = _pack_fixed_u64(bucket_sizes, bucket_size_bits)
    bucket_payload_words = _pack_fixed_u64(bucket_payloads, bucket_payload_bits)
    local_len_words = _pack_fixed_u64(local_lens, local_len_bits)

    span = int(block_span)
    if span <= 0:
        raise ValueError(f'invalid block_span={block_span}')
    block_count = (bucket_count + span - 1) // span
    entry_block_prefix: List[int] = []
    base_block_prefix: List[int] = []
    entry_acc = 0
    base_acc = 0
    for block in range(block_count):
        entry_block_prefix.append(int(entry_acc))
        base_block_prefix.append(int(base_acc))
        start = block * span
        end = min(bucket_count, start + span)
        for b in range(start, end):
            entry_acc += int(bucket_sizes[b])
            base_acc += int(bucket_payloads[b])

    pilot_u8: List[int] = [0] * bucket_count
    overflow_idx: List[int] = []
    overflow_val: List[int] = []
    for idx, pilot in enumerate(result.pilots):
        p = int(pilot)
        if p <= 255:
            pilot_u8[idx] = p
        else:
            pilot_u8[idx] = 255
            overflow_idx.append(int(idx))
            overflow_val.append(int(p))

    header = struct.pack(
        '<8sIIIIIIIII',
        base.MAGIC,
        INDEX_VERSION_V4,
        int(result.pre_count),
        int(result.edges_total),
        int(bucket_target),
        int(V4_PILOT_BITS),
        int(base.HASH_KIND),
        int(base.FLAG_STRICT),
        int(result.seed),
        int(result.bucket_count),
    )
    extra = struct.pack(
        '<IIIIIIIII',
        int(bucket_size_bits),
        int(len(bucket_size_words)),
        int(bucket_payload_bits),
        int(len(bucket_payload_words)),
        int(local_len_bits),
        int(len(local_len_words)),
        int(span),
        int(block_count),
        int(len(overflow_idx)),
    )

    with path.open('wb') as f:
        f.write(header)
        f.write(extra)
        if bucket_size_words:
            f.write(struct.pack('<' + 'Q' * len(bucket_size_words), *bucket_size_words))
        if bucket_payload_words:
            f.write(struct.pack('<' + 'Q' * len(bucket_payload_words), *bucket_payload_words))
        if local_len_words:
            f.write(struct.pack('<' + 'Q' * len(local_len_words), *local_len_words))
        if entry_block_prefix:
            f.write(struct.pack('<' + 'I' * len(entry_block_prefix), *entry_block_prefix))
        if base_block_prefix:
            f.write(struct.pack('<' + 'I' * len(base_block_prefix), *base_block_prefix))
        if pilot_u8:
            f.write(struct.pack('<' + 'B' * len(pilot_u8), *pilot_u8))
        if overflow_idx:
            f.write(struct.pack('<' + 'I' * len(overflow_idx), *overflow_idx))
        if overflow_val:
            f.write(struct.pack('<' + 'I' * len(overflow_val), *overflow_val))
    return path.stat().st_size


def _write_meta_json(
    path: Path,
    *,
    pe: int,
    core: int,
    epsilon: float,
    shape: Dict[str, int],
    result: base.BuildResult,
    bucket_target: int,
    idx_bytes: int,
    index_version: int,
    order_mode: str,
    profile_path: Optional[Path],
    hol_profile_path: Optional[Path],
    profile_lookahead: int,
    order_stats: Dict[str, int],
    layout_stats: Dict[str, float],
    profile_adjacent_pairs_same_line_est: int,
    extra_meta: Optional[Dict[str, object]] = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values_bytes = int(result.edges_total * VALUE_SIZE_BYTES)
    ratio = float(idx_bytes) / float(values_bytes) if values_bytes > 0 else 0.0
    bits_per_edge = float(idx_bytes * 8.0 / result.edges_total) if result.edges_total > 0 else 0.0
    if int(index_version) == INDEX_VERSION_V4:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v4_bucketblock"
    elif int(index_version) == INDEX_VERSION_V5:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v5_blockperm"
    elif int(index_version) == INDEX_VERSION_V6:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v6_oksr"
    elif int(index_version) == INDEX_VERSION_V7:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v7_lpbl"
    elif int(index_version) == int(base.VERSION_V3):
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v3_rankef"
    else:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v1_slotarrays"
    obj = {
        "schema_version": 1,
        "format": format_name,
        "index_magic": "GCSSVLFP",
        "index_version": int(index_version),
        "physical_order_mode": str(order_mode),
        "hol_objective_version": (
            "rowband_stripe_v1"
            if str(order_mode) == ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V1
            else (
                "rowband_stripe_v2"
                if str(order_mode) == ORDER_HOL_CONSTRAINED_V2_1_ROWBAND_STRIPE_V2
                else (
                    "dual_guard_v3"
                    if str(order_mode) == ORDER_HOL_DUAL_GUARD_V3
                    else (
                        "dual_guard_v3_shadow"
                        if str(order_mode) == ORDER_HOL_DUAL_GUARD_V3_SHADOW
                        else (
                            "dual_guard_v4"
                            if str(order_mode) == ORDER_HOL_DUAL_GUARD_V4
                            else (
                                "anchor_separator_v1"
                                if str(order_mode) == ORDER_OFFLINE_ANCHOR_SEPARATOR_V1
                                else ("anchor_separator_v1_shadow" if str(order_mode) == ORDER_OFFLINE_ANCHOR_SEPARATOR_V1_SHADOW else "")
                            )
                        )
                    )
                )
            )
        ),
        "profile_path": str(profile_path) if profile_path else "",
        "hol_profile_path": str(hol_profile_path) if hol_profile_path else "",
        "profile_lookahead": int(profile_lookahead),
        "pe": int(pe),
        "core": int(core),
        "epsilon": float(epsilon),
        "rows": int(shape["rows"]),
        "cols": int(shape["cols"]),
        "br": int(shape["br"]),
        "bc": int(shape["bc"]),
        "pre_count": int(result.pre_count),
        "edges_total": int(result.edges_total),
        "bucket_target": int(bucket_target),
        "bucket_count": int(result.bucket_count),
        "pilot_bits": 0 if int(index_version) in (INDEX_VERSION_V6, INDEX_VERSION_V7) else (int(V4_PILOT_BITS) if int(index_version) == INDEX_VERSION_V4 else int(base.PILOT_BITS)),
        "hash_kind": int(base.HASH_KIND),
        "flags": int(base.FLAG_STRICT),
        "seed": int(result.seed),
        "values_bytes": int(values_bytes),
        "index_bytes": int(idx_bytes),
        "index_to_values_ratio": float(ratio),
        "index_bits_per_edge": float(bits_per_edge),
        "profile_windows": int(order_stats.get("profile_windows", 0)),
        "profile_unique_pres": int(order_stats.get("profile_unique_pres", 0)),
        "profile_adjacent_pairs_total": int(order_stats.get("profile_adjacent_pairs_total", 0)),
        "profile_adjacent_pairs_same_line_est": int(profile_adjacent_pairs_same_line_est),
        "hol_profile_rows": int(order_stats.get("hol_profile_rows", 0)),
        "hol_profile_unique_pres": int(order_stats.get("hol_profile_unique_pres", 0)),
        "hol_profile_head_hits_total": int(order_stats.get("hol_profile_head_hits_total", 0)),
        "rowband_stripe_enabled": int(order_stats.get("rowband_stripe_enabled", 0)),
        "rowband_stripe_band_values": int(order_stats.get("rowband_stripe_band_values", 0)),
        "rowband_stripe_rows_per_band": int(order_stats.get("rowband_stripe_rows_per_band", 0)),
        "rowband_stripe_blocks_total": int(order_stats.get("rowband_stripe_blocks_total", 0)),
        "rowband_stripe_blocks_per_row": int(order_stats.get("rowband_stripe_blocks_per_row", 0)),
        "rowband_stripe_groups_total": int(order_stats.get("rowband_stripe_groups_total", 0)),
        "rowband_stripe_changed_pre_count": int(order_stats.get("rowband_stripe_changed_pre_count", 0)),
        "hol_head_k": int(order_stats.get("hol_head_k", 0)),
        "hol_head_bonus": int(order_stats.get("hol_head_bonus", 0)),
        "hol_target_top_m": int(order_stats.get("hol_target_top_m", 0)),
        "hol_neighbor_top_k": int(order_stats.get("hol_neighbor_top_k", 0)),
        "hol_high_risk_target_count": int(order_stats.get("hol_high_risk_target_count", 0)),
        "hol_high_risk_target_preview": list(order_stats.get("hol_high_risk_target_preview", [])),
        "hol_weak_neighborhood_target_count": int(order_stats.get("hol_weak_neighborhood_target_count", 0)),
        "hol_weak_neighborhood_edge_count": int(order_stats.get("hol_weak_neighborhood_edge_count", 0)),
        "hol_weak_neighborhood_max_degree": int(order_stats.get("hol_weak_neighborhood_max_degree", 0)),
        "hol_weak_neighborhood_preview": dict(order_stats.get("hol_weak_neighborhood_preview", {})),
        "hol_dual_guard_shadow_enabled": int(order_stats.get("hol_dual_guard_shadow_enabled", 0)),
        "hol_dual_guard_shadow_candidate_count": int(order_stats.get("hol_dual_guard_shadow_candidate_count", 0)),
        "hol_dual_guard_shadow_best_target_preview": list(order_stats.get("hol_dual_guard_shadow_best_target_preview", [])),
        "hol_dual_guard_shadow_best_neighbor_preview": dict(order_stats.get("hol_dual_guard_shadow_best_neighbor_preview", {})),
        "hol_dual_guard_shadow_observe_enabled": int(order_stats.get("hol_dual_guard_shadow_observe_enabled", 0)),
        "hol_dual_guard_shadow_target_displacement_total": float(order_stats.get("hol_dual_guard_shadow_target_displacement_total", 0.0)),
        "hol_dual_guard_shadow_target_displacement_max": float(order_stats.get("hol_dual_guard_shadow_target_displacement_max", 0.0)),
        "hol_dual_guard_shadow_target_displacement_preview": list(order_stats.get("hol_dual_guard_shadow_target_displacement_preview", [])),
        "hol_dual_guard_shadow_neighborhood_drift_total": float(order_stats.get("hol_dual_guard_shadow_neighborhood_drift_total", 0.0)),
        "hol_dual_guard_shadow_neighborhood_drift_max": float(order_stats.get("hol_dual_guard_shadow_neighborhood_drift_max", 0.0)),
        "hol_dual_guard_shadow_neighborhood_drift_preview": list(order_stats.get("hol_dual_guard_shadow_neighborhood_drift_preview", [])),
        "hol_dual_guard_shadow_scope_preview": list(order_stats.get("hol_dual_guard_shadow_scope_preview", [])),
        "hol_dual_guard_enabled": int(order_stats.get("hol_dual_guard_enabled", 0)),
        "hol_dual_guard_candidate_count": int(order_stats.get("hol_dual_guard_candidate_count", 0)),
        "hol_dual_guard_best_target_preview": list(order_stats.get("hol_dual_guard_best_target_preview", [])),
        "hol_dual_guard_best_neighbor_preview": dict(order_stats.get("hol_dual_guard_best_neighbor_preview", {})),
        "hol_dual_guard_observe_enabled": int(order_stats.get("hol_dual_guard_observe_enabled", 0)),
        "hol_dual_guard_target_displacement_total": float(order_stats.get("hol_dual_guard_target_displacement_total", 0.0)),
        "hol_dual_guard_target_displacement_max": float(order_stats.get("hol_dual_guard_target_displacement_max", 0.0)),
        "hol_dual_guard_target_displacement_preview": list(order_stats.get("hol_dual_guard_target_displacement_preview", [])),
        "hol_dual_guard_neighborhood_drift_total": float(order_stats.get("hol_dual_guard_neighborhood_drift_total", 0.0)),
        "hol_dual_guard_neighborhood_drift_max": float(order_stats.get("hol_dual_guard_neighborhood_drift_max", 0.0)),
        "hol_dual_guard_neighborhood_drift_preview": list(order_stats.get("hol_dual_guard_neighborhood_drift_preview", [])),
        "hol_dual_guard_scope_preview": list(order_stats.get("hol_dual_guard_scope_preview", [])),
        "anchor_separator_shadow_enabled": int(order_stats.get("anchor_separator_shadow_enabled", 0)),
        "anchor_separator_shadow_anchor_community_count": int(order_stats.get("anchor_separator_shadow_anchor_community_count", 0)),
        "anchor_separator_shadow_anchor_member_count": int(order_stats.get("anchor_separator_shadow_anchor_member_count", 0)),
        "anchor_separator_shadow_separator_member_count": int(order_stats.get("anchor_separator_shadow_separator_member_count", 0)),
        "anchor_separator_shadow_block_count": int(order_stats.get("anchor_separator_shadow_block_count", 0)),
        "anchor_separator_shadow_anchor_escape_count": int(order_stats.get("anchor_separator_shadow_anchor_escape_count", 0)),
        "anchor_separator_shadow_cross_block_weak_edge_weight_ratio": float(
            order_stats.get("anchor_separator_shadow_cross_block_weak_edge_weight_ratio", 0.0)
        ),
        "anchor_separator_shadow_anchor_preview": list(order_stats.get("anchor_separator_shadow_anchor_preview", [])),
        "anchor_separator_shadow_block_plan_preview": list(order_stats.get("anchor_separator_shadow_block_plan_preview", [])),
        "anchor_separator_enabled": int(order_stats.get("anchor_separator_enabled", 0)),
        "anchor_separator_anchor_community_count": int(order_stats.get("anchor_separator_anchor_community_count", 0)),
        "anchor_separator_anchor_member_count": int(order_stats.get("anchor_separator_anchor_member_count", 0)),
        "anchor_separator_separator_member_count": int(order_stats.get("anchor_separator_separator_member_count", 0)),
        "anchor_separator_block_count": int(order_stats.get("anchor_separator_block_count", 0)),
        "anchor_separator_anchor_escape_count": int(order_stats.get("anchor_separator_anchor_escape_count", 0)),
        "anchor_separator_cross_block_weak_edge_weight_ratio": float(
            order_stats.get("anchor_separator_cross_block_weak_edge_weight_ratio", 0.0)
        ),
        "anchor_separator_anchor_preview": list(order_stats.get("anchor_separator_anchor_preview", [])),
        "anchor_separator_block_plan_preview": list(order_stats.get("anchor_separator_block_plan_preview", [])),
        "fat_tail_guard_eval_total": int(order_stats.get("fat_tail_guard_eval_total", 0)),
        "fat_tail_guard_trigger_total": int(order_stats.get("fat_tail_guard_trigger_total", 0)),
        "fat_tail_guard_reason_share_zero_total": int(order_stats.get("fat_tail_guard_reason_share_zero_total", 0)),
        "fat_tail_guard_reason_risk_zero_total": int(order_stats.get("fat_tail_guard_reason_risk_zero_total", 0)),
        "fat_tail_guard_reason_fill_below_threshold_total": int(order_stats.get("fat_tail_guard_reason_fill_below_threshold_total", 0)),
        "fat_tail_guard_reason_seg_len_below_threshold_total": int(order_stats.get("fat_tail_guard_reason_seg_len_below_threshold_total", 0)),
        "fat_tail_guard_projected_fill_max": int(order_stats.get("fat_tail_guard_projected_fill_max", 0)),
        "fat_tail_guard_seg_len_max": int(order_stats.get("fat_tail_guard_seg_len_max", 0)),
        "physical_line_count": int(layout_stats.get("physical_line_count", 0.0)),
        "lines_with_multi_pre": int(layout_stats.get("lines_with_multi_pre", 0.0)),
        "avg_pres_per_line": float(layout_stats.get("avg_pres_per_line", 0.0)),
        "multi_pre_line_ratio": float(layout_stats.get("multi_pre_line_ratio", 0.0)),
    }
    if extra_meta:
        obj.update(extra_meta)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_manifest(
    path: Path,
    *,
    bcsr_dir: Path,
    out_dir: Path,
    epsilon: float,
    bucket_target: int,
    max_seed_tries: int,
    index_version: int,
    order_mode: str,
    profile_dir: Optional[Path],
    profile_lookahead: int,
    total_cores: int,
    total_pres: int,
    total_edges: int,
    values_total_bytes: int,
    index_total_bytes: int,
    total_profile_windows: int,
    total_profile_unique_pres: int,
    total_profile_adjacent_pairs: int,
    total_profile_adjacent_pairs_same_line_est: int,
    total_hol_profile_rows: int,
    total_hol_profile_unique_pres: int,
    total_hol_profile_head_hits: int,
    total_fat_tail_guard_eval: int,
    total_fat_tail_guard_trigger: int,
    total_fat_tail_guard_reason_share_zero: int,
    total_fat_tail_guard_reason_risk_zero: int,
    total_fat_tail_guard_reason_fill_below_threshold: int,
    total_fat_tail_guard_reason_seg_len_below_threshold: int,
    max_fat_tail_guard_projected_fill: int,
    max_fat_tail_guard_seg_len: int,
    hol_head_k: int,
    hol_head_bonus: int,
    total_physical_lines: int,
    total_lines_with_multi_pre: int,
    total_pres_per_line: float,
) -> None:
    ratio = float(index_total_bytes) / float(values_total_bytes) if values_total_bytes > 0 else 0.0
    bits_per_edge = float(index_total_bytes * 8.0 / total_edges) if total_edges > 0 else 0.0
    if int(index_version) == INDEX_VERSION_V4:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v4_bucketblock"
    elif int(index_version) == INDEX_VERSION_V5:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v5_blockperm"
    elif int(index_version) == INDEX_VERSION_V6:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v6_oksr"
    elif int(index_version) == INDEX_VERSION_V7:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v7_lpbl"
    elif int(index_version) == int(base.VERSION_V3):
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v3_rankef"
    else:
        format_name = "gcss_valueonly_dstcore_vlf_premphf_plp_v1_slotarrays"
    obj = {
        "schema_version": 1,
        "format": format_name,
        "bcsr_dir": str(bcsr_dir),
        "out_dir": str(out_dir),
        "epsilon": float(epsilon),
        "bucket_target": int(bucket_target),
        "pilot_bits": 0 if int(index_version) in (INDEX_VERSION_V6, INDEX_VERSION_V7) else (int(V4_PILOT_BITS) if int(index_version) == INDEX_VERSION_V4 else int(base.PILOT_BITS)),
        "hash_kind": int(base.HASH_KIND),
        "index_version": int(index_version),
        "magic": "GCSSVLFP",
        "max_seed_tries": int(max_seed_tries),
        "physical_order_mode": str(order_mode),
        "profile_dir": str(profile_dir) if profile_dir else "",
        "profile_lookahead": int(profile_lookahead),
        "hol_profile_rows_total": int(total_hol_profile_rows),
        "hol_profile_unique_pres_total": int(total_hol_profile_unique_pres),
        "hol_profile_head_hits_total": int(total_hol_profile_head_hits),
        "fat_tail_guard_eval_total": int(total_fat_tail_guard_eval),
        "fat_tail_guard_trigger_total": int(total_fat_tail_guard_trigger),
        "fat_tail_guard_reason_share_zero_total": int(total_fat_tail_guard_reason_share_zero),
        "fat_tail_guard_reason_risk_zero_total": int(total_fat_tail_guard_reason_risk_zero),
        "fat_tail_guard_reason_fill_below_threshold_total": int(total_fat_tail_guard_reason_fill_below_threshold),
        "fat_tail_guard_reason_seg_len_below_threshold_total": int(total_fat_tail_guard_reason_seg_len_below_threshold),
        "fat_tail_guard_projected_fill_max": int(max_fat_tail_guard_projected_fill),
        "fat_tail_guard_seg_len_max": int(max_fat_tail_guard_seg_len),
        "hol_head_k": int(hol_head_k),
        "hol_head_bonus": int(hol_head_bonus),
        "total_cores": int(total_cores),
        "total_pres": int(total_pres),
        "total_edges": int(total_edges),
        "values_total_bytes": int(values_total_bytes),
        "index_total_bytes": int(index_total_bytes),
        "index_to_values_ratio": float(ratio),
        "index_bits_per_edge": float(bits_per_edge),
        "profile_windows_total": int(total_profile_windows),
        "profile_unique_pres_total": int(total_profile_unique_pres),
        "profile_adjacent_pairs_total": int(total_profile_adjacent_pairs),
        "profile_adjacent_pairs_same_line_est": int(total_profile_adjacent_pairs_same_line_est),
        "physical_line_count_total": int(total_physical_lines),
        "lines_with_multi_pre_total": int(total_lines_with_multi_pre),
        "avg_pres_per_line_global": float(total_pres_per_line / total_physical_lines) if total_physical_lines > 0 else 0.0,
        "multi_pre_line_ratio_global": float(total_lines_with_multi_pre / total_physical_lines) if total_physical_lines > 0 else 0.0,
    }
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _process_core(task: Tuple[str, str, float, int, int, bool, int, str, str, int, int, int]) -> Dict[str, object]:
    (
        core_file_s,
        out_dir_s,
        epsilon,
        bucket_target,
        max_seed_tries,
        self_check,
        index_version,
        order_mode,
        profile_dir_s,
        profile_lookahead,
        hol_head_k,
        hol_head_bonus,
    ) = task
    p = Path(core_file_s)
    out_dir = Path(out_dir_s)
    pe, core = base._parse_core_id(p)
    profile_dir = Path(profile_dir_s) if profile_dir_s else None
    profile_path = None
    if profile_dir is not None:
        profile_path = profile_dir / f"pe{pe:02d}" / f"core{core:02d}.pre_windows.csv"
    hol_profile_path = None
    if profile_dir is not None:
        hol_profile_path = profile_dir / f"pe{pe:02d}" / f"core{core:02d}.offline_layout_profile.csv"

    edges, shape = base._parse_bcsr_edges(p, epsilon=float(epsilon))
    result, pre_to_pairs, keys, slot_keys, physical_pre_order, order_stats, v4_extra = _build_plp_result(
        edges,
        bucket_target=int(bucket_target),
        max_seed_tries=int(max_seed_tries),
        index_version=int(index_version),
        order_mode=str(order_mode),
        profile_path=profile_path,
        profile_lookahead=int(profile_lookahead),
        hol_profile_path=hol_profile_path,
        hol_head_k=int(hol_head_k),
        hol_head_bonus=int(hol_head_bonus),
    )

    if bool(self_check):
        if int(index_version) == INDEX_VERSION_V4:
            _self_check_v4(
                result=result,
                pre_to_pairs=pre_to_pairs,
                keys=keys,
                bucket_sizes=v4_extra.get('bucket_sizes', []),
                bucket_payloads=v4_extra.get('bucket_payloads', []),
                local_lens=v4_extra.get('local_lens', []),
                core_tag=f"pe{pe:02d}/core{core:02d}",
            )
        else:
            base._self_check(
                result=result,
                pre_to_pairs=pre_to_pairs,
                keys=keys,
                slot_keys=slot_keys,
                core_tag=f"pe{pe:02d}/core{core:02d}",
            )

    layout_stats = _estimate_layout_stats(
        physical_pre_order=physical_pre_order,
        pre_to_pairs=pre_to_pairs,
        order_stats=order_stats,
    )
    same_line_est = _estimate_profile_same_line(
        profile_path=profile_path,
        profile_lookahead=int(profile_lookahead),
        physical_pre_order=physical_pre_order,
        pre_to_pairs=pre_to_pairs,
    )

    pe_dir = out_dir / f"pe{pe:02d}"
    values_path = pe_dir / f"core{core:02d}.gcssplp.bin"
    idx_path = pe_dir / f"core{core:02d}.gcssplp.idx.bin"
    meta_path = pe_dir / f"core{core:02d}.gcssplp.meta.json"

    base._write_values_bin(values_path, result.values)
    extra_stats: Dict[str, object] = {}
    anchor_separator_plan = order_stats.get("anchor_separator_shadow_plan")
    if isinstance(anchor_separator_plan, dict):
        sidecars = _write_anchor_separator_shadow_sidecars(
            pe_dir,
            core=core,
            plan=anchor_separator_plan,
        )
        extra_stats.update(
            {
                "anchor_separator_shadow_anchor_map_path": str(sidecars["anchor_map_path"]),
                "anchor_separator_shadow_block_plan_path": str(sidecars["block_plan_path"]),
                "anchor_separator_shadow_cut_summary_path": str(sidecars["cut_summary_path"]),
            }
        )
    anchor_separator_real_plan = order_stats.get("anchor_separator_plan")
    if isinstance(anchor_separator_real_plan, dict):
        sidecars = _write_anchor_separator_shadow_sidecars(
            pe_dir,
            core=core,
            plan=anchor_separator_real_plan,
            stem_label="anchor_separator",
        )
        extra_stats.update(
            {
                "anchor_separator_anchor_map_path": str(sidecars["anchor_map_path"]),
                "anchor_separator_block_plan_path": str(sidecars["block_plan_path"]),
                "anchor_separator_cut_summary_path": str(sidecars["cut_summary_path"]),
            }
        )
    if int(index_version) == INDEX_VERSION_V4:
        idx_bytes = _write_index_bin_v4(
            idx_path,
            result,
            int(bucket_target),
            bucket_sizes=v4_extra['bucket_sizes'],
            bucket_payloads=v4_extra['bucket_payloads'],
            local_lens=v4_extra['local_lens'],
            block_span=V4_BLOCK_SPAN_DEFAULT,
        )
    elif int(index_version) == INDEX_VERSION_V5:
        idx_bytes = _write_index_bin_v5(
            idx_path,
            result,
            int(bucket_target),
            block_size=V5_BLOCK_SIZE_DEFAULT,
        )
    elif int(index_version) == INDEX_VERSION_V6:
        v6_stats = _write_index_bin_v6(
            idx_path,
            result,
            int(bucket_target),
            keys=keys,
            physical_pre_order=physical_pre_order,
        )
        idx_bytes = int(v6_stats['idx_bytes'])
        extra_stats.update(v6_stats)
    elif int(index_version) == INDEX_VERSION_V7:
        v7_stats = _write_index_bin_v7(
            idx_path,
            result,
            int(bucket_target),
            keys=keys,
            physical_pre_order=physical_pre_order,
        )
        idx_bytes = int(v7_stats['idx_bytes'])
        extra_stats.update(v7_stats)
    else:
        idx_bytes = base._write_index_bin(
            idx_path,
            result,
            int(bucket_target),
            index_version=int(index_version),
            ef_select_step=int(base.EF_SELECT_STEP_DEFAULT),
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
        order_mode=str(order_mode),
        profile_path=profile_path,
        hol_profile_path=hol_profile_path,
        profile_lookahead=int(profile_lookahead),
        order_stats=order_stats,
        layout_stats=layout_stats,
        profile_adjacent_pairs_same_line_est=int(same_line_est),
        extra_meta=extra_stats if extra_stats else None,
    )

    values_bytes = int(result.edges_total * VALUE_SIZE_BYTES)
    ratio = float(idx_bytes) / float(values_bytes) if values_bytes > 0 else 0.0
    bits_per_edge = float(idx_bytes * 8.0 / result.edges_total) if result.edges_total > 0 else 0.0
    log_line = (
        f"[gcssplp-gen] pe={pe:02d} core={core:02d} mode={order_mode} pres={result.pre_count} "
        f"edges={result.edges_total} values_bytes={values_bytes} idx_bytes={idx_bytes} "
        f"ratio={ratio:.6f} bits_per_edge={bits_per_edge:.4f} idx_ver={int(index_version)} "
        f"multi_pre_lines={int(layout_stats.get('lines_with_multi_pre', 0.0))} "
        f"profile_same_line_est={int(same_line_est)}"
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
        "profile_windows": int(order_stats.get("profile_windows", 0)),
        "profile_unique_pres": int(order_stats.get("profile_unique_pres", 0)),
        "profile_adjacent_pairs_total": int(order_stats.get("profile_adjacent_pairs_total", 0)),
        "profile_adjacent_pairs_same_line_est": int(same_line_est),
        "hol_profile_rows": int(order_stats.get("hol_profile_rows", 0)),
        "hol_profile_unique_pres": int(order_stats.get("hol_profile_unique_pres", 0)),
        "hol_profile_head_hits_total": int(order_stats.get("hol_profile_head_hits_total", 0)),
        "rowband_stripe_enabled": int(order_stats.get("rowband_stripe_enabled", 0)),
        "rowband_stripe_band_values": int(order_stats.get("rowband_stripe_band_values", 0)),
        "rowband_stripe_rows_per_band": int(order_stats.get("rowband_stripe_rows_per_band", 0)),
        "rowband_stripe_blocks_total": int(order_stats.get("rowband_stripe_blocks_total", 0)),
        "rowband_stripe_blocks_per_row": int(order_stats.get("rowband_stripe_blocks_per_row", 0)),
        "rowband_stripe_groups_total": int(order_stats.get("rowband_stripe_groups_total", 0)),
        "rowband_stripe_changed_pre_count": int(order_stats.get("rowband_stripe_changed_pre_count", 0)),
        "hol_dual_guard_shadow_enabled": int(order_stats.get("hol_dual_guard_shadow_enabled", 0)),
        "hol_dual_guard_shadow_candidate_count": int(order_stats.get("hol_dual_guard_shadow_candidate_count", 0)),
        "hol_dual_guard_shadow_observe_enabled": int(order_stats.get("hol_dual_guard_shadow_observe_enabled", 0)),
        "hol_dual_guard_shadow_target_displacement_total": float(order_stats.get("hol_dual_guard_shadow_target_displacement_total", 0.0)),
        "hol_dual_guard_shadow_neighborhood_drift_total": float(order_stats.get("hol_dual_guard_shadow_neighborhood_drift_total", 0.0)),
        "hol_dual_guard_enabled": int(order_stats.get("hol_dual_guard_enabled", 0)),
        "hol_dual_guard_candidate_count": int(order_stats.get("hol_dual_guard_candidate_count", 0)),
        "hol_dual_guard_observe_enabled": int(order_stats.get("hol_dual_guard_observe_enabled", 0)),
        "hol_dual_guard_target_displacement_total": float(order_stats.get("hol_dual_guard_target_displacement_total", 0.0)),
        "hol_dual_guard_neighborhood_drift_total": float(order_stats.get("hol_dual_guard_neighborhood_drift_total", 0.0)),
        "anchor_separator_shadow_enabled": int(order_stats.get("anchor_separator_shadow_enabled", 0)),
        "anchor_separator_shadow_anchor_community_count": int(order_stats.get("anchor_separator_shadow_anchor_community_count", 0)),
        "anchor_separator_shadow_block_count": int(order_stats.get("anchor_separator_shadow_block_count", 0)),
        "anchor_separator_shadow_anchor_escape_count": int(order_stats.get("anchor_separator_shadow_anchor_escape_count", 0)),
        "fat_tail_guard_eval_total": int(order_stats.get("fat_tail_guard_eval_total", 0)),
        "fat_tail_guard_trigger_total": int(order_stats.get("fat_tail_guard_trigger_total", 0)),
        "fat_tail_guard_reason_share_zero_total": int(order_stats.get("fat_tail_guard_reason_share_zero_total", 0)),
        "fat_tail_guard_reason_risk_zero_total": int(order_stats.get("fat_tail_guard_reason_risk_zero_total", 0)),
        "fat_tail_guard_reason_fill_below_threshold_total": int(order_stats.get("fat_tail_guard_reason_fill_below_threshold_total", 0)),
        "fat_tail_guard_reason_seg_len_below_threshold_total": int(order_stats.get("fat_tail_guard_reason_seg_len_below_threshold_total", 0)),
        "fat_tail_guard_projected_fill_max": int(order_stats.get("fat_tail_guard_projected_fill_max", 0)),
        "fat_tail_guard_seg_len_max": int(order_stats.get("fat_tail_guard_seg_len_max", 0)),
        "physical_line_count": int(layout_stats.get("physical_line_count", 0.0)),
        "lines_with_multi_pre": int(layout_stats.get("lines_with_multi_pre", 0.0)),
        "pres_per_line_total": float(layout_stats.get("avg_pres_per_line", 0.0) * layout_stats.get("physical_line_count", 0.0)),
        "log_line": log_line,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bcsr-dir", required=True, help="input BCSR directory")
    ap.add_argument("--out-dir", required=True, help="output directory for GCSS-PLP files")
    ap.add_argument("--epsilon", type=float, default=1e-8, help="abs(weight)<=epsilon is treated as zero edge")
    ap.add_argument("--bucket-target", type=int, default=3, help="target bucket size for pre-MPHF")
    ap.add_argument("--max-seed-tries", type=int, default=128, help="max global seed retries")
    ap.add_argument("--jobs", type=int, default=1, help="number of worker processes")
    ap.add_argument("--self-check", action="store_true", help="run strict consistency checks")
    ap.add_argument(
        "--order-mode",
        default=ORDER_SLOT,
        choices=ORDER_CHOICES,
        help="physical pre-segment ordering policy",
    )
    ap.add_argument(
        "--profile-dir",
        default="",
        help="directory containing exported pre-window profiles (required for profile_greedy/hol_profile_greedy)",
    )
    ap.add_argument(
        "--profile-lookahead",
        type=int,
        default=2,
        help="lookahead depth when building profile transition weights",
    )
    ap.add_argument(
        "--index-version",
        type=int,
        default=int(base.VERSION_V1),
        choices=[int(base.VERSION_V1), int(base.VERSION_V3), INDEX_VERSION_V4, INDEX_VERSION_V5, INDEX_VERSION_V6, INDEX_VERSION_V7],
        help="PLP index format: 1=legacy slot arrays, 3=rank-map + Elias-Fano base_by_rank, 4=bucket-block local-MPHF, 5=layout-preserving blockwise permutation codec, 6=ordered-key sid-run exact codec, 7=ordered-key sid-run + LPBL len blocks",
    )
    args = ap.parse_args()

    bcsr_dir = Path(args.bcsr_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    profile_dir = Path(args.profile_dir).resolve() if args.profile_dir else None

    if not bcsr_dir.is_dir():
        raise SystemExit(f"[gcssplp-gen] bcsr_dir not found: {bcsr_dir}")
    if args.bucket_target <= 0:
        raise SystemExit(f"[gcssplp-gen] invalid --bucket-target={args.bucket_target}, expected >0")
    if args.max_seed_tries <= 0:
        raise SystemExit(f"[gcssplp-gen] invalid --max-seed-tries={args.max_seed_tries}, expected >0")
    if args.jobs <= 0:
        raise SystemExit(f"[gcssplp-gen] invalid --jobs={args.jobs}, expected >0")
    if args.profile_lookahead <= 0:
        raise SystemExit(f"[gcssplp-gen] invalid --profile-lookahead={args.profile_lookahead}, expected >0")
    if args.order_mode in (ORDER_PROFILE, ORDER_HOL_PROFILE) and (profile_dir is None or not profile_dir.is_dir()):
        raise SystemExit(
            f"[gcssplp-gen] --order-mode={args.order_mode} requires a valid --profile-dir"
        )

    core_files = list(base._iter_core_bcsr_files(bcsr_dir))
    if not core_files:
        raise SystemExit(f"[gcssplp-gen] no core*.bcsr.bin found under: {bcsr_dir}")

    tasks: List[Tuple[str, str, float, int, int, bool, int, str, str, int, int, int]] = []
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
                str(args.order_mode),
                str(profile_dir) if profile_dir else "",
                int(args.profile_lookahead),
                int(HOL_HEAD_K_DEFAULT),
                int(HOL_HEAD_BONUS_DEFAULT),
            )
        )

    results: List[Dict[str, object]] = []
    if int(args.jobs) == 1:
        for t in tasks:
            r = _process_core(t)
            results.append(r)
            print(str(r["log_line"]))
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=int(args.jobs)) as ex:
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
    total_profile_windows = int(sum(int(r["profile_windows"]) for r in results))
    total_profile_unique_pres = int(sum(int(r["profile_unique_pres"]) for r in results))
    total_profile_adjacent_pairs = int(sum(int(r["profile_adjacent_pairs_total"]) for r in results))
    total_profile_adj_same_line = int(sum(int(r["profile_adjacent_pairs_same_line_est"]) for r in results))
    total_hol_profile_rows = int(sum(int(r["hol_profile_rows"]) for r in results))
    total_hol_profile_unique_pres = int(sum(int(r["hol_profile_unique_pres"]) for r in results))
    total_hol_profile_head_hits = int(sum(int(r["hol_profile_head_hits_total"]) for r in results))
    total_fat_tail_guard_eval = int(sum(int(r["fat_tail_guard_eval_total"]) for r in results))
    total_fat_tail_guard_trigger = int(sum(int(r["fat_tail_guard_trigger_total"]) for r in results))
    total_fat_tail_guard_reason_share_zero = int(sum(int(r["fat_tail_guard_reason_share_zero_total"]) for r in results))
    total_fat_tail_guard_reason_risk_zero = int(sum(int(r["fat_tail_guard_reason_risk_zero_total"]) for r in results))
    total_fat_tail_guard_reason_fill_below_threshold = int(sum(int(r["fat_tail_guard_reason_fill_below_threshold_total"]) for r in results))
    total_fat_tail_guard_reason_seg_len_below_threshold = int(sum(int(r["fat_tail_guard_reason_seg_len_below_threshold_total"]) for r in results))
    max_fat_tail_guard_projected_fill = max((int(r["fat_tail_guard_projected_fill_max"]) for r in results), default=0)
    max_fat_tail_guard_seg_len = max((int(r["fat_tail_guard_seg_len_max"]) for r in results), default=0)
    total_physical_lines = int(sum(int(r["physical_line_count"]) for r in results))
    total_lines_with_multi_pre = int(sum(int(r["lines_with_multi_pre"]) for r in results))
    total_pres_per_line = float(sum(float(r["pres_per_line_total"]) for r in results))

    _write_manifest(
        out_dir / "manifest.json",
        bcsr_dir=bcsr_dir,
        out_dir=out_dir,
        epsilon=float(args.epsilon),
        bucket_target=int(args.bucket_target),
        max_seed_tries=int(args.max_seed_tries),
        index_version=int(args.index_version),
        order_mode=str(args.order_mode),
        profile_dir=profile_dir,
        profile_lookahead=int(args.profile_lookahead),
        total_cores=len(core_files),
        total_pres=total_pres,
        total_edges=total_edges,
        values_total_bytes=total_values_bytes,
        index_total_bytes=total_index_bytes,
        total_profile_windows=total_profile_windows,
        total_profile_unique_pres=total_profile_unique_pres,
        total_profile_adjacent_pairs=total_profile_adjacent_pairs,
        total_profile_adjacent_pairs_same_line_est=total_profile_adj_same_line,
        total_hol_profile_rows=total_hol_profile_rows,
        total_hol_profile_unique_pres=total_hol_profile_unique_pres,
        total_hol_profile_head_hits=total_hol_profile_head_hits,
        total_fat_tail_guard_eval=total_fat_tail_guard_eval,
        total_fat_tail_guard_trigger=total_fat_tail_guard_trigger,
        total_fat_tail_guard_reason_share_zero=total_fat_tail_guard_reason_share_zero,
        total_fat_tail_guard_reason_risk_zero=total_fat_tail_guard_reason_risk_zero,
        total_fat_tail_guard_reason_fill_below_threshold=total_fat_tail_guard_reason_fill_below_threshold,
        total_fat_tail_guard_reason_seg_len_below_threshold=total_fat_tail_guard_reason_seg_len_below_threshold,
        max_fat_tail_guard_projected_fill=max_fat_tail_guard_projected_fill,
        max_fat_tail_guard_seg_len=max_fat_tail_guard_seg_len,
        hol_head_k=int(HOL_HEAD_K_DEFAULT),
        hol_head_bonus=int(HOL_HEAD_BONUS_DEFAULT),
        total_physical_lines=total_physical_lines,
        total_lines_with_multi_pre=total_lines_with_multi_pre,
        total_pres_per_line=total_pres_per_line,
    )

    ratio = float(total_index_bytes) / float(total_values_bytes) if total_values_bytes > 0 else 0.0
    bits_per_edge = float(total_index_bytes * 8.0 / total_edges) if total_edges > 0 else 0.0
    print(
        f"[gcssplp-gen] done: cores={len(core_files)} mode={args.order_mode} total_pres={total_pres} total_edges={total_edges} "
        f"values_total_bytes={total_values_bytes} index_total_bytes={total_index_bytes} "
        f"ratio={ratio:.6f} bits_per_edge={bits_per_edge:.4f} out_dir={out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
