import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_GCSS_DIR = Path(__file__).resolve().parent
if str(TOOLS_GCSS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_GCSS_DIR))

import gen_gcss_valueonly_dstcore_vlf_premphf as base
import gen_gcss_valueonly_dstcore_vlf_premphf_plp as plp
import analyze_gcssplp_artifact_layout as analyzer


class HolProfileConstrainedV2Test(unittest.TestCase):
    def test_constrained_order_avoids_high_risk_tail_share_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(8):
                    writer.writerow({"pre_touch_order": "1 2"})
                writer.writerow({"pre_touch_order": "1 3"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for i in range(12):
                    writer.writerow(
                        {
                            "window_id": i,
                            "queue_policy": "locality_first",
                            "retire_seq": i,
                            "local_age_rank": 0,
                            "ordered_rank": 12,
                            "younger_ahead_depth": 128,
                            "post_local": 0,
                            "pre_global": 2,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 0,
                            "line_id": 0,
                        }
                    )
                writer.writerow(
                    {
                        "window_id": 99,
                        "queue_policy": "locality_first",
                        "retire_seq": 99,
                        "local_age_rank": 32,
                        "ordered_rank": 32,
                        "younger_ahead_depth": 0,
                        "post_local": 0,
                        "pre_global": 3,
                        "pre_rank": 0,
                        "count": 1,
                        "addr": 0,
                        "line_id": 0,
                    }
                )

            keys = [1, 2, 3]
            slot_keys = [1, 2, 3]
            pre_to_pairs = {
                1: [(0, 1.0)] * 15,
                2: [(0, 1.0)] * 4,
                3: [(0, 1.0)] * 4,
            }

            order, stats = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order, [1, 3, 2])
            self.assertEqual(stats.get("hol_profile_head_hits_total"), 12)


class HolProfileConstrainedV21Test(unittest.TestCase):
    def test_v21_p3c2a_relaxes_exact_full_with_spill_case(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(16):
                    writer.writerow({"pre_touch_order": "1 2"})
                for _ in range(2):
                    writer.writerow({"pre_touch_order": "1 3"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for pre in (2, 3):
                    for i in range(8):
                        writer.writerow(
                            {
                                "window_id": pre * 100 + i,
                                "queue_policy": "locality_first",
                                "retire_seq": pre * 100 + i,
                                "local_age_rank": 0,
                                "ordered_rank": 16,
                                "younger_ahead_depth": 64,
                                "post_local": 0,
                                "pre_global": pre,
                                "pre_rank": 0,
                                "count": 1,
                                "addr": 0,
                                "line_id": 0,
                            }
                        )

            keys = [1, 2, 3]
            slot_keys = [1, 2, 3]
            pre_to_pairs = {
                1: [(0, 1.0)] * 12,
                2: [(0, 1.0)] * 20,
                3: [(0, 1.0)] * 4,
            }

            order_v2, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_v21, order_v21_stats = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v2, [1, 2, 3])
            self.assertEqual(order_v21, [1, 3, 2])
            self.assertEqual(order_v21_stats.get("fat_tail_guard_eval_total"), 3)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_trigger_total"), 1)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_share_zero_total"), 1)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_seg_len_below_threshold_total"), 1)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_projected_fill_max"), 16)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_seg_len_max"), 20)

    def test_v21_prefers_shorter_segment_when_fat_tail_guard_triggers(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(16):
                    writer.writerow({"pre_touch_order": "1 2"})
                for _ in range(2):
                    writer.writerow({"pre_touch_order": "1 3"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for pre in (2, 3):
                    for i in range(8):
                        writer.writerow(
                            {
                                "window_id": pre * 100 + i,
                                "queue_policy": "locality_first",
                                "retire_seq": pre * 100 + i,
                                "local_age_rank": 0,
                                "ordered_rank": 16,
                                "younger_ahead_depth": 64,
                                "post_local": 0,
                                "pre_global": pre,
                                "pre_rank": 0,
                                "count": 1,
                                "addr": 0,
                                "line_id": 0,
                            }
                        )

            keys = [1, 2, 3]
            slot_keys = [1, 2, 3]
            pre_to_pairs = {
                1: [(0, 1.0)] * 15,
                2: [(0, 1.0)] * 40,
                3: [(0, 1.0)] * 4,
            }

            order_v2, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_v21, order_v21_stats = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v2, [1, 2, 3])
            self.assertEqual(order_v21, [1, 3, 2])
            self.assertEqual(order_v21_stats.get("fat_tail_guard_eval_total"), 3)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_trigger_total"), 2)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_seg_len_below_threshold_total"), 1)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_share_zero_total"), 0)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_risk_zero_total"), 0)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_fill_below_threshold_total"), 0)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_projected_fill_max"), 16)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_seg_len_max"), 40)

    def test_v21_penalizes_reachable_hot_tail_segment_at_p3c1_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(16):
                    writer.writerow({"pre_touch_order": "1 2"})
                for _ in range(2):
                    writer.writerow({"pre_touch_order": "1 3"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for pre in (2, 3):
                    for i in range(8):
                        writer.writerow(
                            {
                                "window_id": pre * 100 + i,
                                "queue_policy": "locality_first",
                                "retire_seq": pre * 100 + i,
                                "local_age_rank": 0,
                                "ordered_rank": 16,
                                "younger_ahead_depth": 64,
                                "post_local": 0,
                                "pre_global": pre,
                                "pre_rank": 0,
                                "count": 1,
                                "addr": 0,
                                "line_id": 0,
                            }
                        )

            keys = [1, 2, 3]
            slot_keys = [1, 2, 3]
            pre_to_pairs = {
                1: [(0, 1.0)] * 15,
                2: [(0, 1.0)] * 28,
                3: [(0, 1.0)] * 4,
            }

            order_v2, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_v21, order_v21_stats = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v2, [1, 2, 3])
            self.assertEqual(order_v21, [1, 3, 2])
            self.assertEqual(order_v21_stats.get("fat_tail_guard_eval_total"), 3)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_trigger_total"), 2)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_seg_len_below_threshold_total"), 1)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_projected_fill_max"), 16)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_seg_len_max"), 28)

    def test_v21_keeps_locality_choice_when_tail_guard_is_inactive(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(16):
                    writer.writerow({"pre_touch_order": "1 2"})
                for _ in range(2):
                    writer.writerow({"pre_touch_order": "1 3"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for pre in (2, 3):
                    for i in range(8):
                        writer.writerow(
                            {
                                "window_id": pre * 100 + i,
                                "queue_policy": "locality_first",
                                "retire_seq": pre * 100 + i,
                                "local_age_rank": 0,
                                "ordered_rank": 16,
                                "younger_ahead_depth": 64,
                                "post_local": 0,
                                "pre_global": pre,
                                "pre_rank": 0,
                                "count": 1,
                                "addr": 0,
                                "line_id": 0,
                            }
                        )

            keys = [1, 2, 3]
            slot_keys = [1, 2, 3]
            pre_to_pairs = {
                1: [(0, 1.0)] * 16,
                2: [(0, 1.0)] * 40,
                3: [(0, 1.0)] * 4,
            }

            order_v21, order_v21_stats = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v21, [1, 2, 3])
            self.assertEqual(order_v21_stats.get("fat_tail_guard_eval_total"), 3)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_trigger_total"), 0)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_share_zero_total"), 2)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_risk_zero_total"), 0)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_fill_below_threshold_total"), 1)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_reason_seg_len_below_threshold_total"), 0)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_projected_fill_max"), 12)
            self.assertEqual(order_v21_stats.get("fat_tail_guard_seg_len_max"), 40)


class RowBandStripeTest(unittest.TestCase):
    def test_rowband_stripe_repair_interleaves_microblocks_across_rows(self):
        order = [1, 2, 3, 4, 5, 6, 7, 8]
        pre_to_pairs = {pre: [(0, 1.0)] for pre in order}

        repaired, stats = plp._apply_rowband_stripe_repair(
            order,
            pre_to_pairs,
            block_values=1,
            row_values=4,
            stripe_rows=2,
        )

        self.assertEqual(repaired, [1, 5, 2, 6, 3, 7, 4, 8])
        self.assertEqual(stats.get("rowband_stripe_blocks_total"), 8)
        self.assertEqual(stats.get("rowband_stripe_groups_total"), 1)
        self.assertEqual(stats.get("rowband_stripe_blocks_per_row"), 4)
        self.assertEqual(stats.get("rowband_stripe_changed_pre_count"), 6)

    def test_rowband_stripe_repair_band_interleaves_rows_across_16kb_windows(self):
        order = list(range(1, 17))
        pre_to_pairs = {pre: [(0, 1.0)] for pre in order}

        repaired, stats = plp._apply_rowband_stripe_repair(
            order,
            pre_to_pairs,
            block_values=1,
            row_values=4,
            stripe_rows=4,
            band_values=8,
        )

        self.assertEqual(
            repaired,
            [1, 9, 5, 13, 2, 10, 6, 14, 3, 11, 7, 15, 4, 12, 8, 16],
        )
        self.assertEqual(stats.get("rowband_stripe_band_values"), 8)
        self.assertEqual(stats.get("rowband_stripe_rows_per_band"), 2)
        self.assertEqual(stats.get("rowband_stripe_changed_pre_count"), 14)

    def test_rowband_stripe_mode_applies_second_pass_after_v21(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                writer.writerow({"pre_touch_order": " ".join(str(i) for i in range(1, 33))})

            keys = list(range(1, 33))
            slot_keys = list(range(1, 33))
            pre_to_pairs = {pre: [(idx, 1.0) for idx in range(256)] for pre in keys}

            order_v21, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=None,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_v21_rowband, rowband_stats = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1_rowband_stripe_v1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=None,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v21, keys)
            self.assertEqual(
                order_v21_rowband,
                [
                    1,
                    9,
                    17,
                    25,
                    2,
                    10,
                    18,
                    26,
                    3,
                    11,
                    19,
                    27,
                    4,
                    12,
                    20,
                    28,
                    5,
                    13,
                    21,
                    29,
                    6,
                    14,
                    22,
                    30,
                    7,
                    15,
                    23,
                    31,
                    8,
                    16,
                    24,
                    32,
                ],
            )
            self.assertEqual(rowband_stats.get("rowband_stripe_enabled"), 1)
            self.assertEqual(rowband_stats.get("rowband_stripe_blocks_per_row"), 8)
            self.assertEqual(rowband_stats.get("rowband_stripe_groups_total"), 1)
            self.assertGreater(rowband_stats.get("rowband_stripe_changed_pre_count", 0), 0)

    def test_rowband_stripe_v2_mode_interleaves_rows_across_16kb_bands(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                writer.writerow({"pre_touch_order": " ".join(str(i) for i in range(1, 33))})

            keys = list(range(1, 33))
            slot_keys = list(range(1, 33))
            pre_to_pairs = {pre: [(idx, 1.0) for idx in range(256)] for pre in keys}

            order_v21_rowband_v2, rowband_v2_stats = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1_rowband_stripe_v2",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=None,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(
                order_v21_rowband_v2,
                [
                    1,
                    17,
                    9,
                    25,
                    2,
                    18,
                    10,
                    26,
                    3,
                    19,
                    11,
                    27,
                    4,
                    20,
                    12,
                    28,
                    5,
                    21,
                    13,
                    29,
                    6,
                    22,
                    14,
                    30,
                    7,
                    23,
                    15,
                    31,
                    8,
                    24,
                    16,
                    32,
                ],
            )
            self.assertEqual(rowband_v2_stats.get("rowband_stripe_band_values"), 4096)
            self.assertEqual(rowband_v2_stats.get("rowband_stripe_rows_per_band"), 2)
            self.assertEqual(rowband_v2_stats.get("rowband_stripe_groups_total"), 1)
            self.assertGreater(rowband_v2_stats.get("rowband_stripe_changed_pre_count", 0), 0)


class DualGuardShadowStatsTest(unittest.TestCase):
    def test_collect_dual_guard_shadow_observe_stats_tracks_explicit_penalties(self):
        order = [1, 2, 3, 4]
        pre_to_pairs = {
            1: [(0, 1.0)] * 15,
            2: [(0, 1.0)] * 4,
            3: [(0, 1.0)] * 4,
            4: [(0, 1.0)] * 4,
        }
        risk_stats = {
            2: {
                "head_hits": 2.0,
                "head_depth_avg": 120.0,
                "target_score": 240.0,
                "weak_neighbors": [4],
            },
            3: {
                "head_hits": 0.0,
                "head_depth_avg": 0.0,
                "target_score": 0.0,
            },
            4: {
                "head_hits": 0.0,
                "head_depth_avg": 0.0,
                "target_score": 0.0,
            },
        }

        stats = plp._collect_dual_guard_observe_stats(
            order,
            pre_to_pairs,
            risk_stats,
            prefix="hol_dual_guard_shadow",
        )

        self.assertEqual(stats["hol_dual_guard_shadow_observe_enabled"], 1)
        self.assertEqual(stats["hol_dual_guard_shadow_target_displacement_total"], 240.0)
        self.assertEqual(stats["hol_dual_guard_shadow_target_displacement_max"], 240.0)
        self.assertEqual(stats["hol_dual_guard_shadow_neighborhood_drift_total"], 244.0)
        self.assertEqual(stats["hol_dual_guard_shadow_neighborhood_drift_max"], 244.0)
        self.assertEqual(len(stats["hol_dual_guard_shadow_target_displacement_preview"]), 1)
        self.assertEqual(len(stats["hol_dual_guard_shadow_neighborhood_drift_preview"]), 1)
        self.assertEqual(stats["hol_dual_guard_shadow_scope_preview"][0]["cand"], 3)
        self.assertEqual(stats["hol_dual_guard_shadow_scope_preview"][1]["cand"], 2)
        self.assertGreater(stats["hol_dual_guard_shadow_scope_preview"][0]["neighborhood_drift_penalty"], 0.0)
        self.assertGreater(stats["hol_dual_guard_shadow_scope_preview"][1]["target_displacement_penalty"], 0.0)
        self.assertEqual(stats["hol_dual_guard_shadow_neighborhood_drift_preview"][0]["weak_hit_rank"], -1)

    def test_dual_guard_shadow_mode_keeps_v21_order_but_exposes_shadow_stats(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(10):
                    writer.writerow({"pre_touch_order": "1 2 4"})
                for _ in range(3):
                    writer.writerow({"pre_touch_order": "1 3 4"})
                writer.writerow({"pre_touch_order": "4 2 1"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for window_id, pre, depth, line_id in (
                    (1, 2, 120, 200),
                    (1, 4, 80, 200),
                    (2, 2, 110, 201),
                    (2, 4, 70, 201),
                    (3, 3, 40, 300),
                ):
                    writer.writerow(
                        {
                            "window_id": window_id,
                            "queue_policy": "locality_first",
                            "retire_seq": window_id,
                            "local_age_rank": 0,
                            "ordered_rank": depth,
                            "younger_ahead_depth": depth,
                            "post_local": 0,
                            "pre_global": pre,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 0,
                            "line_id": line_id,
                        }
                    )

            keys = [1, 2, 3, 4]
            slot_keys = [1, 2, 3, 4]
            pre_to_pairs = {
                1: [(0, 1.0)] * 15,
                2: [(0, 1.0)] * 20,
                3: [(0, 1.0)] * 4,
                4: [(0, 1.0)] * 6,
            }

            order_v21, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_shadow, stats_shadow = plp._choose_physical_order(
                order_mode="hol_profile_dual_guard_v3_shadow",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_shadow, order_v21)
            self.assertEqual(stats_shadow["hol_dual_guard_shadow_enabled"], 1)
            self.assertEqual(stats_shadow["hol_dual_guard_shadow_candidate_count"], 3)
            self.assertEqual(stats_shadow["hol_dual_guard_shadow_best_target_preview"], [2, 4, 3])
            self.assertEqual(stats_shadow["hol_dual_guard_shadow_best_neighbor_preview"]["2"], [4])
            self.assertEqual(stats_shadow["hol_dual_guard_shadow_observe_enabled"], 1)
            self.assertGreater(len(stats_shadow["hol_dual_guard_shadow_scope_preview"]), 0)
            self.assertIn("target_displacement_penalty", stats_shadow["hol_dual_guard_shadow_scope_preview"][0])
            self.assertIn("neighborhood_drift_penalty", stats_shadow["hol_dual_guard_shadow_scope_preview"][0])

    def test_load_hol_profile_risk_stats_exposes_high_risk_targets_and_neighbors(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                writer.writerow({"window_id": 1, "queue_policy": "locality_first", "retire_seq": 0, "local_age_rank": 0, "ordered_rank": 10, "younger_ahead_depth": 100, "post_local": 0, "pre_global": 10, "pre_rank": 0, "count": 1, "addr": 0, "line_id": 100})
                writer.writerow({"window_id": 1, "queue_policy": "locality_first", "retire_seq": 1, "local_age_rank": 1, "ordered_rank": 12, "younger_ahead_depth": 80, "post_local": 1, "pre_global": 20, "pre_rank": 0, "count": 1, "addr": 4, "line_id": 100})
                writer.writerow({"window_id": 1, "queue_policy": "locality_first", "retire_seq": 2, "local_age_rank": 9, "ordered_rank": 30, "younger_ahead_depth": 500, "post_local": 2, "pre_global": 30, "pre_rank": 0, "count": 1, "addr": 8, "line_id": 101})
                writer.writerow({"window_id": 2, "queue_policy": "locality_first", "retire_seq": 3, "local_age_rank": 0, "ordered_rank": 14, "younger_ahead_depth": 50, "post_local": 0, "pre_global": 10, "pre_rank": 0, "count": 1, "addr": 12, "line_id": 102})
                writer.writerow({"window_id": 2, "queue_policy": "locality_first", "retire_seq": 4, "local_age_rank": 2, "ordered_rank": 15, "younger_ahead_depth": 90, "post_local": 1, "pre_global": 20, "pre_rank": 0, "count": 1, "addr": 16, "line_id": 102})
                writer.writerow({"window_id": 2, "queue_policy": "locality_first", "retire_seq": 5, "local_age_rank": 0, "ordered_rank": 18, "younger_ahead_depth": 30, "post_local": 2, "pre_global": 40, "pre_rank": 0, "count": 1, "addr": 20, "line_id": 103})

            risk_stats, stats = plp._load_hol_profile_risk_stats(hol_path, head_k=4)

            self.assertEqual(risk_stats[20]["head_hits"], 2.0)
            self.assertEqual(risk_stats[20]["head_depth_sum"], 170.0)
            self.assertEqual(risk_stats[20]["head_depth_avg"], 85.0)
            self.assertEqual(risk_stats[20]["target_score"], 170.0)
            self.assertEqual(stats["hol_high_risk_target_count"], 3)
            self.assertEqual(stats["hol_high_risk_target_preview"], [20, 10, 40])
            self.assertEqual(stats["hol_weak_neighborhood_target_count"], 3)
            self.assertEqual(stats["hol_weak_neighborhood_edge_count"], 6)
            self.assertEqual(stats["hol_weak_neighborhood_max_degree"], 2)
            self.assertEqual(stats["hol_weak_neighborhood_preview"]["20"], [10, 40])

    def test_write_meta_json_includes_dual_guard_shadow_stats(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            meta_path = tmp / "core00.gcssplp.meta.json"
            order_stats = {
                "profile_windows": 2,
                "profile_unique_pres": 3,
                "profile_adjacent_pairs_total": 4,
                "hol_profile_rows": 6,
                "hol_profile_unique_pres": 4,
                "hol_profile_head_hits_total": 5,
                "hol_head_k": 256,
                "hol_head_bonus": 4,
                "hol_target_top_m": 32,
                "hol_neighbor_top_k": 8,
                "hol_high_risk_target_count": 3,
                "hol_high_risk_target_preview": [20, 10, 40],
                "hol_weak_neighborhood_target_count": 3,
                "hol_weak_neighborhood_edge_count": 6,
                "hol_weak_neighborhood_max_degree": 2,
                "hol_weak_neighborhood_preview": {"20": [10, 40]},
                "hol_dual_guard_shadow_enabled": 1,
                "hol_dual_guard_shadow_candidate_count": 3,
                "hol_dual_guard_shadow_best_target_preview": [20, 10, 40],
                "hol_dual_guard_shadow_best_neighbor_preview": {"20": [10, 40]},
                "hol_dual_guard_shadow_observe_enabled": 1,
                "hol_dual_guard_shadow_target_displacement_total": 240.0,
                "hol_dual_guard_shadow_target_displacement_max": 240.0,
                "hol_dual_guard_shadow_target_displacement_preview": [{"cand": 20, "penalty": 240.0}],
                "hol_dual_guard_shadow_neighborhood_drift_total": 244.0,
                "hol_dual_guard_shadow_neighborhood_drift_max": 244.0,
                "hol_dual_guard_shadow_neighborhood_drift_preview": [{"prev": 20, "cand": 10, "penalty": 244.0}],
                "hol_dual_guard_shadow_scope_preview": [{"step": 1, "cand": 20, "target_displacement_penalty": 240.0}],
            }
            result = base.BuildResult(
                seed=0,
                bucket_count=1,
                pre_count=3,
                edges_total=3,
                slot_base=[0, 1, 2],
                slot_len=[1, 1, 1],
                pilots=[],
                values=[1.0, 2.0, 3.0],
                slot_rank=[0, 1, 2],
            )

            plp._write_meta_json(
                meta_path,
                pe=0,
                core=0,
                epsilon=1e-8,
                shape={"rows": 1, "cols": 1, "br": 1, "bc": 1},
                result=result,
                bucket_target=3,
                idx_bytes=16,
                index_version=7,
                order_mode="hol_profile_constrained_v2_1",
                profile_path=None,
                hol_profile_path=None,
                profile_lookahead=2,
                order_stats=order_stats,
                layout_stats={"physical_line_count": 1.0, "lines_with_multi_pre": 0.0, "avg_pres_per_line": 1.0, "multi_pre_line_ratio": 0.0},
                profile_adjacent_pairs_same_line_est=0,
            )

            meta = __import__("json").loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["hol_target_top_m"], 32)
            self.assertEqual(meta["hol_neighbor_top_k"], 8)
            self.assertEqual(meta["hol_high_risk_target_preview"], [20, 10, 40])
            self.assertEqual(meta["hol_weak_neighborhood_preview"], {"20": [10, 40]})
            self.assertEqual(meta["hol_dual_guard_shadow_enabled"], 1)
            self.assertEqual(meta["hol_dual_guard_shadow_candidate_count"], 3)
            self.assertEqual(meta["hol_dual_guard_shadow_best_target_preview"], [20, 10, 40])
            self.assertEqual(meta["hol_dual_guard_shadow_best_neighbor_preview"], {"20": [10, 40]})
            self.assertEqual(meta["hol_dual_guard_shadow_observe_enabled"], 1)
            self.assertEqual(meta["hol_dual_guard_shadow_target_displacement_total"], 240.0)
            self.assertEqual(meta["hol_dual_guard_shadow_neighborhood_drift_total"], 244.0)
            self.assertEqual(meta["hol_dual_guard_shadow_target_displacement_preview"], [{"cand": 20, "penalty": 240.0}])
            self.assertEqual(meta["hol_dual_guard_shadow_scope_preview"], [{"step": 1, "cand": 20, "target_displacement_penalty": 240.0}])


class DualGuardSelectorTest(unittest.TestCase):
    def test_v3_prioritizes_high_risk_target_over_pure_locality(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(8):
                    writer.writerow({"pre_touch_order": "1 3"})
                writer.writerow({"pre_touch_order": "1 2"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for i in range(6):
                    writer.writerow(
                        {
                            "window_id": i,
                            "queue_policy": "locality_first",
                            "retire_seq": i,
                            "local_age_rank": 0,
                            "ordered_rank": 16,
                            "younger_ahead_depth": 120,
                            "post_local": 0,
                            "pre_global": 2,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 0,
                            "line_id": 200,
                        }
                    )

            keys = [1, 2, 3]
            slot_keys = [1, 2, 3]
            pre_to_pairs = {
                1: [(0, 1.0)] * 15,
                2: [(0, 1.0)] * 4,
                3: [(0, 1.0)] * 4,
            }

            order_v21, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_v3, stats_v3 = plp._choose_physical_order(
                order_mode="hol_profile_dual_guard_v3",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v21, [1, 3, 2])
            self.assertEqual(order_v3, [1, 2, 3])
            self.assertEqual(stats_v3["hol_dual_guard_enabled"], 1)

    def test_v3_preserves_weak_neighbor_of_current_target(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(10):
                    writer.writerow({"pre_touch_order": "2 3"})
                writer.writerow({"pre_touch_order": "2 4"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for window_id, pre, depth in (
                    (1, 2, 120),
                    (1, 4, 90),
                    (2, 2, 130),
                    (2, 4, 95),
                ):
                    writer.writerow(
                        {
                            "window_id": window_id,
                            "queue_policy": "locality_first",
                            "retire_seq": window_id,
                            "local_age_rank": 0,
                            "ordered_rank": 16,
                            "younger_ahead_depth": depth,
                            "post_local": 0,
                            "pre_global": pre,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 0,
                            "line_id": 300 + window_id,
                        }
                    )

            keys = [2, 3, 4]
            slot_keys = [2, 3, 4]
            pre_to_pairs = {
                2: [(0, 1.0)] * 15,
                3: [(0, 1.0)] * 4,
                4: [(0, 1.0)] * 4,
            }

            order_v21, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_v3, _ = plp._choose_physical_order(
                order_mode="hol_profile_dual_guard_v3",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v21, [2, 3, 4])
            self.assertEqual(order_v3, [2, 4, 3])

    def test_v4_numeric_softens_target_frontload_and_exposes_penalties(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(8):
                    writer.writerow({"pre_touch_order": "1 3"})
                writer.writerow({"pre_touch_order": "1 2"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for window_id in range(5):
                    writer.writerow(
                        {
                            "window_id": window_id,
                            "queue_policy": "locality_first",
                            "retire_seq": window_id,
                            "local_age_rank": 0,
                            "ordered_rank": 16,
                            "younger_ahead_depth": 120,
                            "post_local": 0,
                            "pre_global": 2,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 0,
                            "line_id": 200,
                        }
                    )

            keys = [1, 2, 3]
            slot_keys = [1, 2, 3]
            pre_to_pairs = {
                1: [(0, 1.0)] * 15,
                2: [(0, 1.0)] * 4,
                3: [(0, 1.0)] * 4,
            }

            order_v21, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_v4, stats_v4 = plp._choose_physical_order(
                order_mode="hol_profile_dual_guard_v4",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v21, [1, 3, 2])
            self.assertEqual(order_v4, [1, 3, 2])
            self.assertEqual(stats_v4["hol_dual_guard_enabled"], 1)
            self.assertEqual(stats_v4["hol_dual_guard_observe_enabled"], 1)
            self.assertGreater(stats_v4["hol_dual_guard_target_displacement_total"], 0.0)
            self.assertGreater(len(stats_v4["hol_dual_guard_scope_preview"]), 0)
            self.assertIn("target_displacement_penalty", stats_v4["hol_dual_guard_scope_preview"][0])
            self.assertIn("neighborhood_drift_penalty", stats_v4["hol_dual_guard_scope_preview"][0])

    def test_v4_numeric_still_preserves_weak_neighbor_of_current_target(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(10):
                    writer.writerow({"pre_touch_order": "2 3"})
                writer.writerow({"pre_touch_order": "2 4"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for window_id, pre, depth in (
                    (1, 2, 120),
                    (1, 4, 90),
                    (2, 2, 130),
                    (2, 4, 95),
                ):
                    writer.writerow(
                        {
                            "window_id": window_id,
                            "queue_policy": "locality_first",
                            "retire_seq": window_id,
                            "local_age_rank": 0,
                            "ordered_rank": 16,
                            "younger_ahead_depth": depth,
                            "post_local": 0,
                            "pre_global": pre,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 0,
                            "line_id": 300 + window_id,
                        }
                    )

            keys = [2, 3, 4]
            slot_keys = [2, 3, 4]
            pre_to_pairs = {
                2: [(0, 1.0)] * 15,
                3: [(0, 1.0)] * 4,
                4: [(0, 1.0)] * 4,
            }

            order_v4, _ = plp._choose_physical_order(
                order_mode="hol_profile_dual_guard_v4",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v4, [2, 4, 3])

    def test_v3_falls_back_to_v21_when_dual_guard_signal_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(4):
                    writer.writerow({"pre_touch_order": "1 2"})
                writer.writerow({"pre_touch_order": "1 3"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "window_id": 1,
                        "queue_policy": "locality_first",
                        "retire_seq": 1,
                        "local_age_rank": 99,
                        "ordered_rank": 0,
                        "younger_ahead_depth": 0,
                        "post_local": 0,
                        "pre_global": 3,
                        "pre_rank": 0,
                        "count": 1,
                        "addr": 0,
                        "line_id": 0,
                    }
                )

            keys = [1, 2, 3]
            slot_keys = [1, 2, 3]
            pre_to_pairs = {
                1: [(0, 1.0)] * 16,
                2: [(0, 1.0)] * 4,
                3: [(0, 1.0)] * 4,
            }

            order_v21, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_v3, _ = plp._choose_physical_order(
                order_mode="hol_profile_dual_guard_v3",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v3, order_v21)

    def test_v4_falls_back_to_v21_when_dual_guard_signal_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(4):
                    writer.writerow({"pre_touch_order": "1 2"})
                writer.writerow({"pre_touch_order": "1 3"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "window_id": 1,
                        "queue_policy": "locality_first",
                        "retire_seq": 1,
                        "local_age_rank": 99,
                        "ordered_rank": 0,
                        "younger_ahead_depth": 0,
                        "post_local": 0,
                        "pre_global": 3,
                        "pre_rank": 0,
                        "count": 1,
                        "addr": 0,
                        "line_id": 0,
                    }
                )

            keys = [1, 2, 3]
            slot_keys = [1, 2, 3]
            pre_to_pairs = {
                1: [(0, 1.0)] * 16,
                2: [(0, 1.0)] * 4,
                3: [(0, 1.0)] * 4,
            }

            order_v21, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_v4, _ = plp._choose_physical_order(
                order_mode="hol_profile_dual_guard_v4",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_v4, order_v21)

    def test_v3_meta_fields_are_written(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            meta_path = tmp / "core00.gcssplp.meta.json"
            order_stats = {
                "profile_windows": 2,
                "profile_unique_pres": 3,
                "profile_adjacent_pairs_total": 4,
                "hol_profile_rows": 6,
                "hol_profile_unique_pres": 4,
                "hol_profile_head_hits_total": 5,
                "hol_head_k": 256,
                "hol_head_bonus": 4,
                "hol_dual_guard_enabled": 1,
                "hol_dual_guard_candidate_count": 3,
                "hol_dual_guard_best_target_preview": [20, 10, 40],
                "hol_dual_guard_best_neighbor_preview": {"20": [10, 40]},
            }
            result = base.BuildResult(
                seed=0,
                bucket_count=1,
                pre_count=3,
                edges_total=3,
                slot_base=[0, 1, 2],
                slot_len=[1, 1, 1],
                pilots=[],
                values=[1.0, 2.0, 3.0],
                slot_rank=[0, 1, 2],
            )

            plp._write_meta_json(
                meta_path,
                pe=0,
                core=0,
                epsilon=1e-8,
                shape={"rows": 1, "cols": 1, "br": 1, "bc": 1},
                result=result,
                bucket_target=3,
                idx_bytes=16,
                index_version=7,
                order_mode="hol_profile_dual_guard_v3",
                profile_path=None,
                hol_profile_path=None,
                profile_lookahead=2,
                order_stats=order_stats,
                layout_stats={"physical_line_count": 1.0, "lines_with_multi_pre": 0.0, "avg_pres_per_line": 1.0, "multi_pre_line_ratio": 0.0},
                profile_adjacent_pairs_same_line_est=0,
            )

            meta = __import__("json").loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["hol_dual_guard_enabled"], 1)
            self.assertEqual(meta["hol_dual_guard_candidate_count"], 3)
            self.assertEqual(meta["hol_dual_guard_best_target_preview"], [20, 10, 40])
            self.assertEqual(meta["hol_dual_guard_best_neighbor_preview"], {"20": [10, 40]})
            self.assertEqual(meta["hol_objective_version"], "dual_guard_v3")

    def test_v4_meta_fields_are_written(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            meta_path = tmp / "core00.gcssplp.meta.json"
            order_stats = {
                "profile_windows": 2,
                "profile_unique_pres": 3,
                "profile_adjacent_pairs_total": 4,
                "hol_profile_rows": 6,
                "hol_profile_unique_pres": 4,
                "hol_profile_head_hits_total": 5,
                "hol_head_k": 256,
                "hol_head_bonus": 4,
                "hol_dual_guard_enabled": 1,
                "hol_dual_guard_candidate_count": 3,
                "hol_dual_guard_best_target_preview": [20, 10, 40],
                "hol_dual_guard_best_neighbor_preview": {"20": [10, 40]},
                "hol_dual_guard_observe_enabled": 1,
                "hol_dual_guard_target_displacement_total": 240.0,
                "hol_dual_guard_target_displacement_max": 240.0,
                "hol_dual_guard_target_displacement_preview": [{"cand": 20, "penalty": 240.0}],
                "hol_dual_guard_neighborhood_drift_total": 244.0,
                "hol_dual_guard_neighborhood_drift_max": 244.0,
                "hol_dual_guard_neighborhood_drift_preview": [{"prev": 20, "cand": 10, "penalty": 244.0}],
                "hol_dual_guard_scope_preview": [{"step": 1, "cand": 20, "target_displacement_penalty": 240.0}],
            }
            result = base.BuildResult(
                seed=0,
                bucket_count=1,
                pre_count=3,
                edges_total=3,
                slot_base=[0, 1, 2],
                slot_len=[1, 1, 1],
                pilots=[],
                values=[1.0, 2.0, 3.0],
                slot_rank=[0, 1, 2],
            )

            plp._write_meta_json(
                meta_path,
                pe=0,
                core=0,
                epsilon=1e-8,
                shape={"rows": 1, "cols": 1, "br": 1, "bc": 1},
                result=result,
                bucket_target=3,
                idx_bytes=16,
                index_version=7,
                order_mode="hol_profile_dual_guard_v4",
                profile_path=None,
                hol_profile_path=None,
                profile_lookahead=2,
                order_stats=order_stats,
                layout_stats={"physical_line_count": 1.0, "lines_with_multi_pre": 0.0, "avg_pres_per_line": 1.0, "multi_pre_line_ratio": 0.0},
                profile_adjacent_pairs_same_line_est=0,
            )

            meta = __import__("json").loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["hol_dual_guard_enabled"], 1)
            self.assertEqual(meta["hol_dual_guard_candidate_count"], 3)
            self.assertEqual(meta["hol_dual_guard_best_target_preview"], [20, 10, 40])
            self.assertEqual(meta["hol_dual_guard_best_neighbor_preview"], {"20": [10, 40]})
            self.assertEqual(meta["hol_dual_guard_observe_enabled"], 1)
            self.assertEqual(meta["hol_dual_guard_target_displacement_total"], 240.0)
            self.assertEqual(meta["hol_dual_guard_neighborhood_drift_total"], 244.0)
            self.assertEqual(meta["hol_dual_guard_target_displacement_preview"], [{"cand": 20, "penalty": 240.0}])
            self.assertEqual(meta["hol_dual_guard_scope_preview"], [{"step": 1, "cand": 20, "target_displacement_penalty": 240.0}])
            self.assertEqual(meta["hol_objective_version"], "dual_guard_v4")


class AnchorSeparatorShadowTest(unittest.TestCase):
    def test_merge_tiny_anchor_separator_communities_absorbs_tiny_anchor_into_best_neighbor(self):
        communities = [
            {"targets": {100}, "members": {100, 101}},
            {"targets": {200}, "members": {200}},
            {"targets": {300}, "members": {300, 301}},
        ]
        graph = {
            100: {101: 4, 200: 7},
            101: {100: 4, 200: 6},
            200: {100: 7, 101: 6},
            300: {301: 5},
            301: {300: 5},
        }
        risk_stats = {
            100: {"target_score": 120.0, "weak_neighbors": [101, 200]},
            200: {"target_score": 80.0, "weak_neighbors": [100]},
            300: {"target_score": 110.0, "weak_neighbors": [301]},
        }
        baseline_rank = {
            100: 0,
            101: 1,
            200: 2,
            300: 3,
            301: 4,
        }
        pre_to_pairs = {
            100: [(0, 1.0)] * 16,
            101: [(0, 1.0)] * 16,
            200: [(0, 1.0)] * 4,
            300: [(0, 1.0)] * 16,
            301: [(0, 1.0)] * 16,
        }

        merged = plp._merge_tiny_anchor_separator_communities(
            communities,
            keys_set={100, 101, 200, 300, 301},
            risk_stats=risk_stats,
            graph=graph,
            baseline_rank=baseline_rank,
            pre_to_pairs=pre_to_pairs,
        )

        merged_members = sorted(
            sorted(int(pre) for pre in row["members"])
            for row in merged
        )
        merged_targets = sorted(
            sorted(int(pre) for pre in row["targets"])
            for row in merged
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged_members, [[100, 101, 200], [300, 301]])
        self.assertEqual(merged_targets, [[100, 200], [300]])

    def test_merge_tiny_anchor_separator_communities_keeps_isolated_tiny_anchor(self):
        communities = [
            {"targets": {100}, "members": {100, 101}},
            {"targets": {200}, "members": {200}},
            {"targets": {300}, "members": {300, 301}},
        ]
        graph = {
            100: {101: 4},
            101: {100: 4},
            300: {301: 5},
            301: {300: 5},
        }
        risk_stats = {
            100: {"target_score": 120.0, "weak_neighbors": [101]},
            200: {"target_score": 80.0, "weak_neighbors": []},
            300: {"target_score": 110.0, "weak_neighbors": [301]},
        }
        baseline_rank = {
            100: 0,
            101: 1,
            200: 2,
            300: 3,
            301: 4,
        }
        pre_to_pairs = {
            100: [(0, 1.0)] * 16,
            101: [(0, 1.0)] * 16,
            200: [(0, 1.0)] * 4,
            300: [(0, 1.0)] * 16,
            301: [(0, 1.0)] * 16,
        }

        merged = plp._merge_tiny_anchor_separator_communities(
            communities,
            keys_set={100, 101, 200, 300, 301},
            risk_stats=risk_stats,
            graph=graph,
            baseline_rank=baseline_rank,
            pre_to_pairs=pre_to_pairs,
        )

        merged_members = sorted(
            sorted(int(pre) for pre in row["members"])
            for row in merged
        )
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged_members, [[100, 101], [200], [300, 301]])

    def test_build_anchor_separator_shadow_plan_groups_anchor_community_and_reports_cut_summary(self):
        keys = [1, 2, 3, 4, 5]
        baseline_order = [1, 2, 3, 4, 5]
        pre_to_pairs = {
            1: [(0, 1.0)] * 8,
            2: [(0, 1.0)] * 12,
            3: [(0, 1.0)] * 6,
            4: [(0, 1.0)] * 4,
            5: [(0, 1.0)] * 3,
        }
        freq = {1: 10, 2: 9, 3: 8, 4: 7, 5: 6}
        trans = {
            (2, 3): 9,
            (2, 4): 7,
            (1, 5): 2,
        }
        risk_stats = {
            2: {
                "head_hits": 2.0,
                "head_depth_avg": 120.0,
                "target_score": 240.0,
                "weak_neighbors": [4],
            },
            3: {
                "head_hits": 0.0,
                "head_depth_avg": 0.0,
                "target_score": 0.0,
            },
            4: {
                "head_hits": 0.0,
                "head_depth_avg": 0.0,
                "target_score": 0.0,
            },
        }

        plan = plp._build_anchor_separator_shadow_plan(
            keys,
            pre_to_pairs,
            freq=freq,
            trans=trans,
            risk_stats=risk_stats,
            baseline_order=baseline_order,
        )

        self.assertEqual(plan["cut_summary"]["anchor_community_count"], 1)
        self.assertEqual(plan["cut_summary"]["anchor_escape_count"], 0)
        self.assertEqual(plan["anchor_map"][0]["seed"], 2)
        self.assertEqual(plan["anchor_map"][0]["members_preview"], [2, 3, 4])
        self.assertGreaterEqual(plan["cut_summary"]["block_count"], 1)
        self.assertGreaterEqual(plan["cut_summary"]["cross_block_weak_edge_weight_ratio"], 0.0)

    def test_anchor_separator_shadow_mode_keeps_v21_order_but_exposes_plan_stats(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(10):
                    writer.writerow({"pre_touch_order": "2 3"})
                writer.writerow({"pre_touch_order": "2 4"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for window_id, pre, depth in (
                    (1, 2, 120),
                    (1, 4, 90),
                    (2, 2, 130),
                    (2, 4, 95),
                ):
                    writer.writerow(
                        {
                            "window_id": window_id,
                            "queue_policy": "locality_first",
                            "retire_seq": window_id,
                            "local_age_rank": 0,
                            "ordered_rank": 16,
                            "younger_ahead_depth": depth,
                            "post_local": 0,
                            "pre_global": pre,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 0,
                            "line_id": 300 + window_id,
                        }
                    )

            keys = [2, 3, 4]
            slot_keys = [2, 3, 4]
            pre_to_pairs = {
                2: [(0, 1.0)] * 15,
                3: [(0, 1.0)] * 4,
                4: [(0, 1.0)] * 4,
            }

            order_v21, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_shadow, stats_shadow = plp._choose_physical_order(
                order_mode="offline_anchor_separator_layout_v1_shadow",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(order_shadow, order_v21)
            self.assertEqual(stats_shadow["anchor_separator_shadow_enabled"], 1)
            self.assertEqual(stats_shadow["anchor_separator_shadow_anchor_community_count"], 1)
            self.assertGreater(len(stats_shadow["anchor_separator_shadow_anchor_preview"]), 0)
            self.assertGreater(len(stats_shadow["anchor_separator_shadow_block_plan_preview"]), 0)
            self.assertIn("kind", stats_shadow["anchor_separator_shadow_block_plan_preview"][0])

    def test_build_anchor_separator_layout_plan_closes_target_weak_neighbors_and_reduces_escape(self):
        keys = [10, 20, 30, 40, 50]
        pre_to_pairs = {pre: [(0, 1.0)] for pre in keys}
        freq = {pre: 1 for pre in keys}
        trans = {
            (10, 40): 10,
            (40, 10): 10,
        }
        risk_stats = {
            10: {"target_score": 100.0, "head_hits": 3.0, "head_depth_avg": 100.0, "weak_neighbors": [20]},
            40: {"target_score": 90.0, "head_hits": 2.0, "head_depth_avg": 90.0, "weak_neighbors": [30, 50]},
            20: {"target_score": 0.0},
            30: {"target_score": 0.0},
            50: {"target_score": 0.0},
        }
        baseline_order = [10, 20, 30, 40, 50]

        shadow_plan = plp._build_anchor_separator_shadow_plan(
            keys,
            pre_to_pairs,
            freq=freq,
            trans=trans,
            risk_stats=risk_stats,
            baseline_order=baseline_order,
        )
        layout_plan = plp._build_anchor_separator_layout_plan(
            keys,
            pre_to_pairs,
            freq=freq,
            trans=trans,
            risk_stats=risk_stats,
            baseline_order=baseline_order,
        )

        shadow_order = shadow_plan["plan_order"]
        layout_order = layout_plan["plan_order"]
        layout_members = sorted(
            pre
            for row in layout_plan["anchor_map"]
            for pre in row["members"]
        )
        self.assertGreater(len(shadow_order), len(set(shadow_order)))
        self.assertEqual(len(layout_order), len(set(layout_order)))
        self.assertIn(50, layout_members)
        self.assertLess(
            layout_plan["cut_summary"]["anchor_escape_count"],
            shadow_plan["cut_summary"]["anchor_escape_count"],
        )

    def test_anchor_separator_real_mode_uses_layout_plan_order(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                for _ in range(8):
                    writer.writerow({"pre_touch_order": "10 40"})
                writer.writerow({"pre_touch_order": "10 20"})
                writer.writerow({"pre_touch_order": "40 30"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for row in (
                    (1, 10, 0, 160, 500),
                    (1, 40, 0, 140, 500),
                    (2, 10, 0, 170, 501),
                    (2, 40, 0, 145, 501),
                ):
                    window_id, pre, local_age_rank, depth, line_id = row
                    writer.writerow(
                        {
                            "window_id": window_id,
                            "queue_policy": "locality_first",
                            "retire_seq": window_id,
                            "local_age_rank": local_age_rank,
                            "ordered_rank": 16,
                            "younger_ahead_depth": depth,
                            "post_local": 0,
                            "pre_global": pre,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 0,
                            "line_id": line_id,
                        }
                    )

            keys = [10, 20, 30, 40, 50]
            slot_keys = [10, 20, 30, 40, 50]
            pre_to_pairs = {pre: [(0, 1.0)] for pre in keys}

            order_v21, _ = plp._choose_physical_order(
                order_mode="hol_profile_constrained_v2_1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            order_real, stats_real = plp._choose_physical_order(
                order_mode="offline_anchor_separator_layout_v1",
                keys=keys,
                slot_keys=slot_keys,
                pre_to_pairs=pre_to_pairs,
                profile_path=profile_path,
                profile_lookahead=2,
                hol_profile_path=hol_path,
                hol_head_k=8,
                hol_head_bonus=4,
            )
            risk_stats, _ = plp._load_hol_profile_risk_stats(hol_path, head_k=8)
            freq, trans = plp._build_profile_graph(plp._load_profile_sequences(profile_path), lookahead=2)
            layout_plan = plp._build_anchor_separator_layout_plan(
                keys,
                pre_to_pairs,
                freq=freq,
                trans=trans,
                risk_stats=risk_stats,
                baseline_order=order_v21,
            )

            self.assertEqual(stats_real["anchor_separator_enabled"], 1)
            self.assertIn("anchor_separator_anchor_escape_count", stats_real)
            self.assertEqual(order_real, layout_plan["plan_order"])
            self.assertEqual(len(order_real), len(set(order_real)))
            self.assertEqual(sorted(order_real), sorted(keys))

    def test_write_anchor_separator_shadow_sidecars_persists_json_payloads(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pe_dir = tmp / "pe00"
            plan = {
                "anchor_map": [{"community_id": 0, "seed": 2, "members_preview": [2, 3, 4]}],
                "block_plan": [{"block_id": 0, "kind": "anchor", "members_preview": [2, 3, 4]}],
                "cut_summary": {"anchor_community_count": 1, "block_count": 1},
            }

            sidecars = plp._write_anchor_separator_shadow_sidecars(
                pe_dir,
                core=0,
                plan=plan,
            )

            self.assertTrue((pe_dir / sidecars["anchor_map_path"]).is_file())
            self.assertTrue((pe_dir / sidecars["block_plan_path"]).is_file())
            self.assertTrue((pe_dir / sidecars["cut_summary_path"]).is_file())
            payload = __import__("json").loads((pe_dir / sidecars["cut_summary_path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["anchor_community_count"], 1)

    def test_anchor_separator_shadow_meta_fields_are_written(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            meta_path = tmp / "core00.gcssplp.meta.json"
            order_stats = {
                "profile_windows": 2,
                "profile_unique_pres": 3,
                "profile_adjacent_pairs_total": 4,
                "hol_profile_rows": 6,
                "hol_profile_unique_pres": 4,
                "hol_profile_head_hits_total": 5,
                "hol_head_k": 256,
                "hol_head_bonus": 4,
                "anchor_separator_shadow_enabled": 1,
                "anchor_separator_shadow_anchor_community_count": 2,
                "anchor_separator_shadow_anchor_member_count": 5,
                "anchor_separator_shadow_separator_member_count": 7,
                "anchor_separator_shadow_block_count": 3,
                "anchor_separator_shadow_anchor_escape_count": 1,
                "anchor_separator_shadow_cross_block_weak_edge_weight_ratio": 0.25,
                "anchor_separator_shadow_anchor_preview": [{"seed": 20, "members_preview": [20, 10, 40]}],
                "anchor_separator_shadow_block_plan_preview": [{"block_id": 0, "kind": "anchor"}],
            }
            result = base.BuildResult(
                seed=0,
                bucket_count=1,
                pre_count=3,
                edges_total=3,
                slot_base=[0, 1, 2],
                slot_len=[1, 1, 1],
                pilots=[],
                values=[1.0, 2.0, 3.0],
                slot_rank=[0, 1, 2],
            )

            plp._write_meta_json(
                meta_path,
                pe=0,
                core=0,
                epsilon=1e-8,
                shape={"rows": 1, "cols": 1, "br": 1, "bc": 1},
                result=result,
                bucket_target=3,
                idx_bytes=16,
                index_version=7,
                order_mode="offline_anchor_separator_layout_v1_shadow",
                profile_path=None,
                hol_profile_path=None,
                profile_lookahead=2,
                order_stats=order_stats,
                layout_stats={"physical_line_count": 1.0, "lines_with_multi_pre": 0.0, "avg_pres_per_line": 1.0, "multi_pre_line_ratio": 0.0},
                profile_adjacent_pairs_same_line_est=0,
                extra_meta={
                    "anchor_separator_shadow_anchor_map_path": "core00.anchor_separator_shadow.anchor_map.json",
                    "anchor_separator_shadow_block_plan_path": "core00.anchor_separator_shadow.block_plan.json",
                    "anchor_separator_shadow_cut_summary_path": "core00.anchor_separator_shadow.cut_summary.json",
                },
            )

            meta = __import__("json").loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["anchor_separator_shadow_enabled"], 1)
            self.assertEqual(meta["anchor_separator_shadow_anchor_community_count"], 2)
            self.assertEqual(meta["anchor_separator_shadow_anchor_escape_count"], 1)
            self.assertEqual(meta["anchor_separator_shadow_block_plan_preview"], [{"block_id": 0, "kind": "anchor"}])
            self.assertEqual(meta["anchor_separator_shadow_anchor_map_path"], "core00.anchor_separator_shadow.anchor_map.json")
            self.assertEqual(meta["hol_objective_version"], "anchor_separator_v1_shadow")


class CanonicalArtifactAnalyzerTest(unittest.TestCase):
    def test_analyze_core_artifact_decodes_v7_layout_and_reports_canonical_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile_path = tmp / "core00.pre_windows.csv"
            hol_path = tmp / "core00.offline_layout_profile.csv"

            with profile_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["pre_touch_order"])
                writer.writeheader()
                writer.writerow({"pre_touch_order": "1 2"})
                writer.writerow({"pre_touch_order": "1 3"})
                writer.writerow({"pre_touch_order": "2 4"})

            with hol_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "window_id",
                        "queue_policy",
                        "retire_seq",
                        "local_age_rank",
                        "ordered_rank",
                        "younger_ahead_depth",
                        "post_local",
                        "pre_global",
                        "pre_rank",
                        "count",
                        "addr",
                        "line_id",
                    ],
                )
                writer.writeheader()
                for window_id in (1, 2):
                    writer.writerow(
                        {
                            "window_id": window_id,
                            "queue_policy": "locality_first",
                            "retire_seq": window_id * 10,
                            "local_age_rank": 0,
                            "ordered_rank": 16,
                            "younger_ahead_depth": 12,
                            "post_local": 0,
                            "pre_global": 2,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 0,
                            "line_id": 100 + window_id,
                        }
                    )
                    writer.writerow(
                        {
                            "window_id": window_id,
                            "queue_policy": "locality_first",
                            "retire_seq": window_id * 10 + 1,
                            "local_age_rank": 1,
                            "ordered_rank": 16,
                            "younger_ahead_depth": 10,
                            "post_local": 1,
                            "pre_global": 3,
                            "pre_rank": 0,
                            "count": 1,
                            "addr": 64,
                            "line_id": 100 + window_id,
                        }
                    )

            edges = (
                [base.Edge(pre=1, post=post, weight=1.0) for post in range(15)]
                + [base.Edge(pre=2, post=100 + post, weight=1.0) for post in range(4)]
                + [base.Edge(pre=3, post=200 + post, weight=1.0) for post in range(20)]
                + [base.Edge(pre=4, post=300 + post, weight=1.0) for post in range(4)]
            )
            result, _, keys, slot_keys, physical_pre_order, _, _ = plp._build_plp_result(
                edges,
                bucket_target=3,
                max_seed_tries=128,
                index_version=plp.INDEX_VERSION_V7,
                order_mode=plp.ORDER_PRE,
                profile_path=None,
                profile_lookahead=2,
                hol_profile_path=None,
                hol_head_k=8,
                hol_head_bonus=4,
            )

            self.assertEqual(physical_pre_order, [1, 2, 3, 4])

            pe_dir = tmp / "artifact" / "pe00"
            pe_dir.mkdir(parents=True, exist_ok=True)
            idx_path = pe_dir / "core00.gcssplp.idx.bin"
            meta_path = pe_dir / "core00.gcssplp.meta.json"
            plp._write_index_bin_v7(
                idx_path,
                result,
                3,
                keys=keys,
                physical_pre_order=physical_pre_order,
            )
            meta_path.write_text(
                json.dumps(
                    {
                        "index_magic": "GCSSVLFP",
                        "index_version": plp.INDEX_VERSION_V7,
                        "pre_count": result.pre_count,
                        "edges_total": result.edges_total,
                        "profile_path": str(profile_path),
                        "hol_profile_path": str(hol_path),
                        "profile_lookahead": 2,
                        "hol_head_k": 8,
                        "hol_head_bonus": 4,
                        "physical_order_mode": plp.ORDER_PRE,
                        "pe": 0,
                        "core": 0,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            decoded = analyzer._decode_gcssplp_v7_index_layout(idx_path)
            self.assertEqual(decoded["physical_pre_order"], [1, 2, 3, 4])
            self.assertEqual(decoded["len_by_pre"][1], 15)
            self.assertEqual(decoded["len_by_pre"][2], 4)
            self.assertEqual(decoded["len_by_pre"][3], 20)
            self.assertEqual(decoded["len_by_pre"][4], 4)

            report = analyzer.analyze_core_artifact(meta_path)
            self.assertEqual(report["profile_transition_weight_total"], 6)
            self.assertEqual(report["weak_edge_total"], 2)
            self.assertEqual(report["anchor_escape_count"], 0)
            self.assertAlmostEqual(report["same_line_rate"], 1.0 / 3.0, places=6)
            self.assertAlmostEqual(report["avg_line_gap"], 2.0 / 3.0, places=6)
            self.assertAlmostEqual(report["same_8KB_row_rate"], 1.0, places=6)
            self.assertAlmostEqual(report["avg_8KB_row_gap"], 0.0, places=6)
            self.assertAlmostEqual(report["same_16KB_window_rate"], 1.0, places=6)
            self.assertAlmostEqual(report["avg_16KB_window_gap"], 0.0, places=6)
            self.assertAlmostEqual(report["cross_block_weak_edge_weight_ratio"], 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
