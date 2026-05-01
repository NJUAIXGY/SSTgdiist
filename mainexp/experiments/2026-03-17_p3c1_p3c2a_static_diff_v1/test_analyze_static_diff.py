import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
TOOLS_GCSS_DIR = Path("/home/xgy/remote/sst_dram_si/tools/gcss")

for p in (EXPERIMENT_DIR, TOOLS_GCSS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import gen_gcss_valueonly_dstcore_vlf_premphf as base
import gen_gcss_valueonly_dstcore_vlf_premphf_plp as plp
import analyze_static_diff as mod


class AnalyzeStaticDiffTest(unittest.TestCase):
    def test_load_v7_mapping_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            idx_path = tmp / "core00.gcssplp.idx.bin"

            keys = [10, 20, 30, 40]
            physical_pre_order = [20, 10, 40, 30]
            lengths = {10: 2, 20: 3, 30: 1, 40: 4}

            values = []
            base_by_pre = {}
            for pre in physical_pre_order:
                base_by_pre[pre] = len(values)
                values.extend([float(pre)] * lengths[pre])

            slot_keys = list(keys)
            result = base.BuildResult(
                seed=0,
                bucket_count=0,
                pre_count=len(keys),
                edges_total=len(values),
                slot_base=[base_by_pre[pre] for pre in slot_keys],
                slot_len=[lengths[pre] for pre in slot_keys],
                pilots=[],
                values=values,
                slot_rank=[physical_pre_order.index(pre) for pre in slot_keys],
            )

            plp._write_index_bin_v7(
                idx_path,
                result,
                bucket_target=3,
                keys=keys,
                physical_pre_order=physical_pre_order,
            )

            mapping = mod.load_v7_mapping(idx_path)

            self.assertEqual(mapping[10]["sid"], 0)
            self.assertEqual(mapping[10]["rank"], 1)
            self.assertEqual(mapping[10]["base"], 3)
            self.assertEqual(mapping[10]["len"], 2)

            self.assertEqual(mapping[20]["sid"], 1)
            self.assertEqual(mapping[20]["rank"], 0)
            self.assertEqual(mapping[20]["base"], 0)
            self.assertEqual(mapping[20]["len"], 3)

            self.assertEqual(mapping[30]["sid"], 2)
            self.assertEqual(mapping[30]["rank"], 3)
            self.assertEqual(mapping[30]["base"], 9)
            self.assertEqual(mapping[30]["len"], 1)

            self.assertEqual(mapping[40]["sid"], 3)
            self.assertEqual(mapping[40]["rank"], 2)
            self.assertEqual(mapping[40]["base"], 5)
            self.assertEqual(mapping[40]["len"], 4)

    def test_summarize_band_metrics_counts_rows_pres_and_lines(self):
        rows = [
            {"pre_global": "10", "line_id": "100", "count": "2"},
            {"pre_global": "20", "line_id": "100", "count": "1"},
            {"pre_global": "30", "line_id": "200", "count": "4"},
            {"pre_global": "40", "line_id": "300", "count": "1"},
        ]
        mapping = {
            10: {"rank": 10},
            20: {"rank": 120},
            30: {"rank": 300},
            40: {"rank": 520},
        }

        out = mod.summarize_band_metrics(
            rows,
            mapping,
            bands=((0, 256), (256, 512), (512, 768)),
        )

        self.assertEqual(out[(0, 256)]["rows"], 2)
        self.assertEqual(out[(0, 256)]["weighted_count"], 3)
        self.assertEqual(out[(0, 256)]["unique_pres"], 2)
        self.assertEqual(out[(0, 256)]["unique_lines"], 1)

        self.assertEqual(out[(256, 512)]["rows"], 1)
        self.assertEqual(out[(256, 512)]["weighted_count"], 4)
        self.assertEqual(out[(256, 512)]["unique_pres"], 1)
        self.assertEqual(out[(256, 512)]["unique_lines"], 1)

        self.assertEqual(out[(512, 768)]["rows"], 1)
        self.assertEqual(out[(512, 768)]["weighted_count"], 1)
        self.assertEqual(out[(512, 768)]["unique_pres"], 1)
        self.assertEqual(out[(512, 768)]["unique_lines"], 1)

    def test_select_target_profile_row_prefers_oldest_then_more_buried(self):
        rows = [
            {
                "pre_global": "10",
                "local_age_rank": "1",
                "younger_ahead_depth": "900",
                "retire_seq": "1",
                "post_local": "0",
            },
            {
                "pre_global": "20",
                "local_age_rank": "0",
                "younger_ahead_depth": "100",
                "retire_seq": "0",
                "post_local": "0",
            },
            {
                "pre_global": "30",
                "local_age_rank": "0",
                "younger_ahead_depth": "500",
                "retire_seq": "2",
                "post_local": "1",
            },
        ]

        picked = mod.select_target_profile_row(rows)

        self.assertIsNotNone(picked)
        self.assertEqual(picked["pre_global"], "30")

    def test_build_target_neighborhood_rows_collects_union_and_profile_stats(self):
        rows = [
            {
                "pre_global": "20",
                "count": "2",
                "line_id": "100",
                "local_age_rank": "0",
                "ordered_rank": "500",
                "younger_ahead_depth": "500",
            },
            {
                "pre_global": "10",
                "count": "1",
                "line_id": "100",
                "local_age_rank": "1",
                "ordered_rank": "700",
                "younger_ahead_depth": "699",
            },
            {
                "pre_global": "40",
                "count": "3",
                "line_id": "300",
                "local_age_rank": "2",
                "ordered_rank": "900",
                "younger_ahead_depth": "898",
            },
        ]
        mapping1 = {
            10: {"rank": 8, "base": 0, "len": 2},
            20: {"rank": 10, "base": 2, "len": 2},
            30: {"rank": 15, "base": 4, "len": 1},
            40: {"rank": 20, "base": 5, "len": 3},
        }
        mapping2 = {
            10: {"rank": 14, "base": 0, "len": 2},
            20: {"rank": 12, "base": 2, "len": 2},
            30: {"rank": 18, "base": 4, "len": 1},
            40: {"rank": 22, "base": 5, "len": 3},
        }

        neighborhood_rows, summary = mod.build_target_neighborhood_rows(
            target_pre=20,
            rows=rows,
            mapping1=mapping1,
            mapping2=mapping2,
            radius=6,
        )

        self.assertEqual(summary["union_pre_count"], 3)
        self.assertEqual(summary["profile_pres_in_union"], 2)
        self.assertEqual(summary["same_line_pres_in_union"], 2)
        self.assertEqual(summary["moved_pres_count"], 3)
        self.assertEqual(summary["large_shift_abs_ge_64_count"], 0)

        by_pre = {row["pre_global"]: row for row in neighborhood_rows}
        self.assertEqual(sorted(by_pre), [10, 20, 30])
        self.assertEqual(by_pre[20]["same_line_as_target"], 1)
        self.assertEqual(by_pre[10]["same_line_as_target"], 1)
        self.assertEqual(by_pre[30]["in_profile_window"], 0)
        self.assertEqual(by_pre[20]["rank_delta_p3c2a_minus_p3c1"], 2)
        self.assertEqual(by_pre[10]["profile_weighted_count"], 1)

    def test_compute_meta_preview_overlap_counts_shared_targets_and_neighbors(self):
        meta1 = {
            "hol_high_risk_target_preview": [20, 10, 40],
            "hol_weak_neighborhood_preview": {"20": [10, 40], "10": [20]},
        }
        meta2 = {
            "hol_high_risk_target_preview": [30, 20, 10],
            "hol_weak_neighborhood_preview": {"20": [10, 30], "30": [20]},
        }

        summary = mod.compute_meta_preview_overlap(meta1, meta2)

        self.assertEqual(summary["baseline_target_count"], 3)
        self.assertEqual(summary["candidate_target_count"], 3)
        self.assertEqual(summary["target_overlap_count"], 2)
        self.assertEqual(summary["target_overlap_preview"], [10, 20])
        self.assertEqual(summary["neighbor_pair_overlap_count"], 1)
        self.assertEqual(summary["neighbor_pair_overlap_preview"], ["20->10"])

    def test_load_anchor_shadow_bundle_reads_meta_and_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pe_dir = tmp / "pe00"
            pe_dir.mkdir(parents=True)
            meta_path = pe_dir / "core00.gcssplp.meta.json"
            anchor_map_path = pe_dir / "core00.anchor_separator_shadow.anchor_map.json"
            block_plan_path = pe_dir / "core00.anchor_separator_shadow.block_plan.json"
            cut_summary_path = pe_dir / "core00.anchor_separator_shadow.cut_summary.json"

            meta = {
                "anchor_separator_shadow_enabled": 1,
                "anchor_separator_shadow_anchor_community_count": 2,
                "anchor_separator_shadow_block_count": 3,
                "anchor_separator_shadow_anchor_escape_count": 7,
                "anchor_separator_shadow_cross_block_weak_edge_weight_ratio": 0.375,
                "anchor_separator_shadow_anchor_preview": [{"seed": 20, "members_preview": [20, 10, 40]}],
                "anchor_separator_shadow_block_plan_preview": [{"block_id": 0, "kind": "anchor"}],
                "anchor_separator_shadow_anchor_map_path": anchor_map_path.name,
                "anchor_separator_shadow_block_plan_path": block_plan_path.name,
                "anchor_separator_shadow_cut_summary_path": cut_summary_path.name,
            }
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            anchor_map_path.write_text(
                json.dumps({"anchor_map": [{"community_id": 0, "seed": 20}, {"community_id": 1, "seed": 50}]}),
                encoding="utf-8",
            )
            block_plan_path.write_text(
                json.dumps({"block_plan": [{"block_id": 0, "kind": "anchor"}, {"block_id": 1, "kind": "separator"}]}),
                encoding="utf-8",
            )
            cut_summary_path.write_text(
                json.dumps(
                    {
                        "anchor_community_count": 2,
                        "block_count": 3,
                        "anchor_escape_count": 7,
                        "cross_block_weak_edge_weight_ratio": 0.375,
                        "anchor_local_span_p95": 42,
                    }
                ),
                encoding="utf-8",
            )

            bundle = mod.load_anchor_shadow_bundle(meta_path, meta)

            self.assertEqual(bundle["enabled"], 1)
            self.assertEqual(bundle["anchor_community_count"], 2)
            self.assertEqual(bundle["block_count"], 3)
            self.assertEqual(bundle["anchor_escape_count"], 7)
            self.assertEqual(bundle["cross_block_weak_edge_weight_ratio"], 0.375)
            self.assertEqual(bundle["anchor_local_span_p95"], 42)
            self.assertEqual(bundle["anchor_map_path"], str(anchor_map_path))
            self.assertEqual(bundle["block_plan_path"], str(block_plan_path))
            self.assertEqual(bundle["cut_summary_path"], str(cut_summary_path))
            self.assertEqual(bundle["anchor_map"][0]["seed"], 20)
            self.assertEqual(bundle["block_plan"][1]["kind"], "separator")

    def test_load_global_meta_compare_includes_anchor_shadow_fields(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            baseline_dir = tmp / "baseline"
            candidate_dir = tmp / "candidate"
            for root in (baseline_dir, candidate_dir):
                (root / "pe00").mkdir(parents=True)

            baseline_meta = {
                "pe": 0,
                "core": 0,
                "fat_tail_guard_trigger_total": 0,
                "fat_tail_guard_reason_share_zero_total": 0,
                "fat_tail_guard_reason_risk_zero_total": 0,
                "fat_tail_guard_reason_fill_below_threshold_total": 0,
                "fat_tail_guard_reason_seg_len_below_threshold_total": 0,
                "lines_with_multi_pre": 4,
                "physical_line_count": 10,
                "index_bytes": 128,
            }
            candidate_meta = {
                **baseline_meta,
                "anchor_separator_shadow_enabled": 1,
                "anchor_separator_shadow_anchor_community_count": 3,
                "anchor_separator_shadow_block_count": 5,
                "anchor_separator_shadow_anchor_escape_count": 11,
                "anchor_separator_shadow_cross_block_weak_edge_weight_ratio": 0.625,
                "anchor_separator_shadow_anchor_map_path": "core00.anchor_separator_shadow.anchor_map.json",
                "anchor_separator_shadow_block_plan_path": "core00.anchor_separator_shadow.block_plan.json",
                "anchor_separator_shadow_cut_summary_path": "core00.anchor_separator_shadow.cut_summary.json",
            }
            (baseline_dir / "pe00" / "core00.gcssplp.meta.json").write_text(json.dumps(baseline_meta), encoding="utf-8")
            (candidate_dir / "pe00" / "core00.gcssplp.meta.json").write_text(json.dumps(candidate_meta), encoding="utf-8")
            (candidate_dir / "pe00" / "core00.anchor_separator_shadow.anchor_map.json").write_text(
                json.dumps({"anchor_map": [{"community_id": 0, "seed": 20}]}),
                encoding="utf-8",
            )
            (candidate_dir / "pe00" / "core00.anchor_separator_shadow.block_plan.json").write_text(
                json.dumps({"block_plan": [{"block_id": 0, "kind": "anchor"}]}),
                encoding="utf-8",
            )
            (candidate_dir / "pe00" / "core00.anchor_separator_shadow.cut_summary.json").write_text(
                json.dumps({"anchor_local_span_p95": 77}),
                encoding="utf-8",
            )

            rows, summary = mod._load_global_meta_compare(baseline_dir, candidate_dir)

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["p3c2a_anchor_separator_shadow_anchor_community_count"], 3)
            self.assertEqual(row["p3c2a_anchor_separator_shadow_block_count"], 5)
            self.assertEqual(row["p3c2a_anchor_separator_shadow_anchor_escape_count"], 11)
            self.assertEqual(row["p3c2a_anchor_separator_shadow_anchor_local_span_p95"], 77)
            self.assertEqual(row["p3c2a_anchor_separator_shadow_cut_summary_path"], str(candidate_dir / "pe00" / "core00.anchor_separator_shadow.cut_summary.json"))
            self.assertEqual(summary["anchor_shadow_core_count"], 1)
            self.assertEqual(summary["anchor_shadow_escape_sum"], 11)

    def test_choose_top_abnormal_cores_falls_back_to_anchor_shadow_metrics(self):
        rows = [
            {
                "pe": 0,
                "core": 1,
                "delta_fat_tail_guard_trigger_total": 0,
                "p3c2a_anchor_separator_shadow_anchor_escape_count": 4,
                "p3c2a_anchor_separator_shadow_cross_block_weak_edge_weight_ratio": 0.9,
                "p3c2a_anchor_separator_shadow_anchor_local_span_p95": 80,
            },
            {
                "pe": 0,
                "core": 0,
                "delta_fat_tail_guard_trigger_total": 0,
                "p3c2a_anchor_separator_shadow_anchor_escape_count": 9,
                "p3c2a_anchor_separator_shadow_cross_block_weak_edge_weight_ratio": 0.3,
                "p3c2a_anchor_separator_shadow_anchor_local_span_p95": 30,
            },
            {
                "pe": 1,
                "core": 0,
                "delta_fat_tail_guard_trigger_total": 0,
                "p3c2a_anchor_separator_shadow_anchor_escape_count": 9,
                "p3c2a_anchor_separator_shadow_cross_block_weak_edge_weight_ratio": 0.7,
                "p3c2a_anchor_separator_shadow_anchor_local_span_p95": 20,
            },
        ]

        picked = mod._choose_top_abnormal_cores(rows, top_count=3)

        self.assertEqual(picked, [(1, 0), (0, 0), (0, 1)])

    def test_parse_args_accepts_baseline_candidate_aliases(self):
        args = mod._parse_args(
            [
                "--baseline-dir",
                "/tmp/base",
                "--candidate-dir",
                "/tmp/cand",
                "--pe",
                "2",
            ]
        )

        self.assertEqual(str(args.p3c1_dir), "/tmp/base")
        self.assertEqual(str(args.p3c2a_dir), "/tmp/cand")
        self.assertEqual(args.pe, 2)


if __name__ == "__main__":
    unittest.main()
