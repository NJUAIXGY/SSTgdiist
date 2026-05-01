import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_grid_snapshot.py"
BASELINE_CASE = "pulse_shared_line_actual_mfb_gather_preband_dedup_off"


class MakeGridSnapshotTest(unittest.TestCase):
    def test_generates_grid_summary_with_derived_probe_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root = root / "runs"
            runs_root.mkdir()

            baseline_latest = self._make_case_run(
                runs_root,
                BASELINE_CASE,
                run_name="20260327-100000",
                cycle_cost=100.0,
                memory_requests=1000.0,
                issue_deferred=50,
                private_issue_avoided=40,
                service_elide=20,
                frontier_windows=0,
                frontier_base_items=0,
                frontier_base_consumers=0,
                frontier_band_items=0,
                frontier_band_consumers=0,
                rowdesc_join_live=0,
                rowdesc_join_ready=0,
                rowdesc_late_join=0,
                preband_no_trigger=0,
                preband_replay_enqueued=0,
                preband_replay_dropped_budget=0,
                mfb_gather_owner_lines_useful=0,
                mfb_gather_owner_lines_dead=0,
                mfb_gather_owner_lines_useful_head2=0,
                mfb_gather_owner_lines_useful_tail=0,
                mfb_gather_owner_lines_dead_head2=0,
                mfb_gather_owner_lines_dead_tail=0,
                mfb_gather_resident_hits=0,
                mfb_gather_launched_bands_dead=0,
                mfb_gather_launched_bands_single_useful=0,
                mfb_gather_launched_bands_multi_useful=0,
                mfb_gather_launched_bands_head2_useful=0,
                mfb_gather_launched_bands_tail_only_useful=0,
                mfb_gather_launched_bands_head2_dead=0,
                mfb_gather_launched_bands_multi_resident=0,
                mfb_gather_launched_bands_resident_hits=0,
                actual_observe_enable=0,
                actual_observe_band_slots=128,
                actual_preband_band_slots=None,
                actual_gather_window_budget=6,
            )
            self.assertTrue(baseline_latest.exists())

            legacy_latest = self._make_case_run(
                runs_root,
                "pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top32_band128",
                run_name="20260327-100100",
                cycle_cost=110.0,
                memory_requests=1000.0,
                issue_deferred=40,
                private_issue_avoided=40,
                service_elide=20,
                frontier_windows=320,
                frontier_base_items=10240,
                frontier_base_consumers=96868,
                frontier_band_items=320,
                frontier_band_consumers=3360,
                rowdesc_join_live=12,
                rowdesc_join_ready=8,
                rowdesc_late_join=4,
                preband_no_trigger=30,
                preband_replay_enqueued=20,
                preband_replay_dropped_budget=10,
                mfb_gather_owner_lines_useful=50,
                mfb_gather_owner_lines_dead=10,
                mfb_gather_owner_lines_useful_head2=30,
                mfb_gather_owner_lines_useful_tail=20,
                mfb_gather_owner_lines_dead_head2=6,
                mfb_gather_owner_lines_dead_tail=4,
                mfb_gather_resident_hits=60,
                mfb_gather_launched_bands_dead=8,
                mfb_gather_launched_bands_single_useful=5,
                mfb_gather_launched_bands_multi_useful=7,
                mfb_gather_launched_bands_head2_useful=4,
                mfb_gather_launched_bands_tail_only_useful=8,
                mfb_gather_launched_bands_head2_dead=5,
                mfb_gather_launched_bands_multi_resident=6,
                mfb_gather_launched_bands_resident_hits=9,
                actual_observe_enable=1,
                actual_observe_band_slots=128,
                actual_preband_band_slots=128,
                actual_gather_window_budget=6,
            )
            self.assertTrue(legacy_latest.exists())

            phase_probe_latest = self._make_case_run(
                runs_root,
                "pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top32_observe_band128_preband_band80_budget4",
                run_name="20260327-100200",
                cycle_cost=90.0,
                memory_requests=1000.0,
                issue_deferred=70,
                private_issue_avoided=60,
                service_elide=30,
                frontier_windows=320,
                frontier_base_items=10240,
                frontier_base_consumers=96868,
                frontier_band_items=320,
                frontier_band_consumers=3360,
                rowdesc_join_live=21,
                rowdesc_join_ready=9,
                rowdesc_late_join=7,
                preband_no_trigger=11,
                preband_replay_enqueued=25,
                preband_replay_dropped_budget=5,
                mfb_gather_owner_lines_useful=40,
                mfb_gather_owner_lines_dead=5,
                mfb_gather_owner_lines_useful_head2=22,
                mfb_gather_owner_lines_useful_tail=18,
                mfb_gather_owner_lines_dead_head2=3,
                mfb_gather_owner_lines_dead_tail=2,
                mfb_gather_resident_hits=55,
                mfb_gather_launched_bands_dead=4,
                mfb_gather_launched_bands_single_useful=6,
                mfb_gather_launched_bands_multi_useful=8,
                mfb_gather_launched_bands_head2_useful=5,
                mfb_gather_launched_bands_tail_only_useful=9,
                mfb_gather_launched_bands_head2_dead=3,
                mfb_gather_launched_bands_multi_resident=7,
                mfb_gather_launched_bands_resident_hits=10,
                actual_observe_enable=1,
                actual_observe_band_slots=128,
                actual_preband_band_slots=None,
                actual_gather_window_budget=6,
            )
            self.assertTrue(phase_probe_latest.exists())

            out_path = root / "snapshot" / "grid_summary.tsv"
            proc = subprocess.run(
                [
                    "python3",
                    str(SCRIPT_PATH),
                    "--runs-root",
                    str(runs_root),
                    "--out",
                    str(out_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertTrue(out_path.exists())

            rows = self._read_tsv(out_path)
            self.assertIn(BASELINE_CASE, rows)
            self.assertIn(
                "pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top32_band128",
                rows,
            )
            self.assertIn(
                "pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top32_observe_band128_preband_band80_budget4",
                rows,
            )

            top32_row = rows[
                "pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top32_band128"
            ]
            self.assertEqual(top32_row["delta_cycle_vs_baseline"], "10")
            self.assertEqual(top32_row["owner_deferred_to_elide_conversion_rate"], "0.5")
            self.assertEqual(top32_row["owner_private_to_elide_conversion_rate"], "0.5")
            self.assertEqual(top32_row["frontier_collect_cost"], "0.000099773")
            self.assertEqual(top32_row["frontier_collect_cost_per_item"], "0.00094697")
            self.assertEqual(top32_row["observe_band_slots"], "128")
            self.assertEqual(top32_row["preband_band_slots"], "128")
            self.assertEqual(top32_row["gather_window_budget"], "6")
            self.assertEqual(top32_row["actual_observe_enable"], "1")
            self.assertEqual(top32_row["actual_observe_band_slots"], "128")
            self.assertEqual(top32_row["actual_preband_band_slots"], "128")
            self.assertEqual(top32_row["actual_gather_window_budget"], "6")
            self.assertEqual(top32_row["observe_band_slots_mismatch"], "0")
            self.assertEqual(top32_row["preband_band_slots_mismatch"], "0")
            self.assertEqual(top32_row["gather_window_budget_mismatch"], "0")
            self.assertEqual(top32_row["config_drift_any"], "0")
            self.assertEqual(top32_row["rowdesc_join_live"], "12")
            self.assertEqual(top32_row["rowdesc_join_ready"], "8")
            self.assertEqual(top32_row["rowdesc_late_join"], "4")
            self.assertEqual(top32_row["preband_no_trigger"], "30")
            self.assertEqual(top32_row["preband_replay_enqueued"], "20")
            self.assertEqual(top32_row["preband_replay_dropped_budget"], "10")
            self.assertEqual(top32_row["mfb_gather_owner_lines_useful"], "50")
            self.assertEqual(top32_row["mfb_gather_owner_lines_dead"], "10")
            self.assertEqual(top32_row["mfb_gather_owner_lines_useful_head2"], "30")
            self.assertEqual(top32_row["mfb_gather_owner_lines_useful_tail"], "20")
            self.assertEqual(top32_row["mfb_gather_owner_lines_dead_head2"], "6")
            self.assertEqual(top32_row["mfb_gather_owner_lines_dead_tail"], "4")
            self.assertEqual(top32_row["mfb_gather_resident_hits"], "60")
            self.assertEqual(top32_row["mfb_gather_launched_bands_dead"], "8")
            self.assertEqual(top32_row["mfb_gather_launched_bands_single_useful"], "5")
            self.assertEqual(top32_row["mfb_gather_launched_bands_multi_useful"], "7")
            self.assertEqual(top32_row["mfb_gather_launched_bands_head2_useful"], "4")
            self.assertEqual(top32_row["mfb_gather_launched_bands_tail_only_useful"], "8")
            self.assertEqual(top32_row["mfb_gather_launched_bands_head2_dead"], "5")
            self.assertEqual(top32_row["mfb_gather_launched_bands_useful"], "12")
            self.assertEqual(top32_row["mfb_gather_launched_bands_useful_ratio"], "0.6")
            self.assertEqual(top32_row["mfb_gather_launched_bands_dead_ratio"], "0.4")
            self.assertEqual(top32_row["mfb_gather_launched_bands_head2_useful_ratio"], "0.2")
            self.assertEqual(top32_row["mfb_gather_launched_bands_tail_only_useful_ratio"], "0.4")
            self.assertEqual(top32_row["mfb_gather_launched_bands_head2_dead_ratio"], "0.25")
            self.assertEqual(top32_row["mfb_gather_owner_lines_useful_per_replay"], "2.5")
            self.assertEqual(top32_row["mfb_gather_resident_hits_per_replay"], "3")
            self.assertEqual(top32_row["mfb_gather_owner_lines_useful_head2_share"], "0.6")
            self.assertEqual(top32_row["mfb_gather_owner_lines_useful_tail_share"], "0.4")
            self.assertEqual(top32_row["mfb_gather_owner_lines_dead_head2_share"], "0.6")
            self.assertEqual(top32_row["mfb_gather_owner_lines_dead_tail_share"], "0.4")
            self.assertEqual(top32_row["rowdescriptor_service_elide_per_useful_owner_line"], "0.4")
            self.assertEqual(top32_row["rowdescriptor_service_elide_per_replay"], "1")

            phase_probe_row = rows[
                "pulse_shared_line_actual_mfb_gather_preband_dedup_off_metadata_frontier_top32_observe_band128_preband_band80_budget4"
            ]
            self.assertEqual(phase_probe_row["top_items"], "32")
            self.assertEqual(phase_probe_row["observe_band_slots"], "128")
            self.assertEqual(phase_probe_row["preband_band_slots"], "80")
            self.assertEqual(phase_probe_row["gather_window_budget"], "4")
            self.assertEqual(phase_probe_row["actual_observe_enable"], "1")
            self.assertEqual(phase_probe_row["actual_observe_band_slots"], "128")
            self.assertEqual(phase_probe_row["actual_preband_band_slots"], "None")
            self.assertEqual(phase_probe_row["actual_gather_window_budget"], "6")
            self.assertEqual(phase_probe_row["observe_band_slots_mismatch"], "0")
            self.assertEqual(phase_probe_row["preband_band_slots_mismatch"], "1")
            self.assertEqual(phase_probe_row["gather_window_budget_mismatch"], "1")
            self.assertEqual(phase_probe_row["config_drift_any"], "1")
            self.assertEqual(phase_probe_row["delta_cycle_vs_baseline"], "-10")
            self.assertEqual(phase_probe_row["rowdesc_join_live"], "21")
            self.assertEqual(phase_probe_row["rowdesc_join_ready"], "9")
            self.assertEqual(phase_probe_row["rowdesc_late_join"], "7")
            self.assertEqual(phase_probe_row["preband_no_trigger"], "11")
            self.assertEqual(phase_probe_row["preband_replay_enqueued"], "25")
            self.assertEqual(phase_probe_row["preband_replay_dropped_budget"], "5")
            self.assertEqual(phase_probe_row["mfb_gather_owner_lines_useful"], "40")
            self.assertEqual(phase_probe_row["mfb_gather_owner_lines_dead_head2"], "3")
            self.assertEqual(phase_probe_row["mfb_gather_owner_lines_dead_tail"], "2")
            self.assertEqual(phase_probe_row["mfb_gather_launched_bands_useful"], "14")
            self.assertEqual(phase_probe_row["mfb_gather_launched_bands_useful_ratio"], "0.56")
            self.assertEqual(phase_probe_row["mfb_gather_launched_bands_dead_ratio"], "0.16")
            self.assertEqual(phase_probe_row["mfb_gather_launched_bands_head2_useful"], "5")
            self.assertEqual(phase_probe_row["mfb_gather_launched_bands_tail_only_useful"], "9")
            self.assertEqual(phase_probe_row["mfb_gather_launched_bands_head2_dead"], "3")
            self.assertEqual(phase_probe_row["mfb_gather_launched_bands_head2_useful_ratio"], "0.2")
            self.assertEqual(phase_probe_row["mfb_gather_launched_bands_tail_only_useful_ratio"], "0.36")
            self.assertEqual(phase_probe_row["mfb_gather_launched_bands_head2_dead_ratio"], "0.12")
            self.assertEqual(phase_probe_row["mfb_gather_owner_lines_useful_per_replay"], "1.6")
            self.assertEqual(phase_probe_row["mfb_gather_resident_hits_per_replay"], "2.2")
            self.assertEqual(phase_probe_row["mfb_gather_owner_lines_useful_head2_share"], "0.55")
            self.assertEqual(phase_probe_row["mfb_gather_owner_lines_useful_tail_share"], "0.45")
            self.assertEqual(phase_probe_row["mfb_gather_owner_lines_dead_head2_share"], "0.6")
            self.assertEqual(phase_probe_row["mfb_gather_owner_lines_dead_tail_share"], "0.4")
            self.assertEqual(phase_probe_row["rowdescriptor_service_elide_per_useful_owner_line"], "0.75")
            self.assertEqual(phase_probe_row["rowdescriptor_service_elide_per_replay"], "1.2")

    def _make_case_run(
        self,
        runs_root: Path,
        case_id: str,
        *,
        run_name: str,
        cycle_cost: float,
        memory_requests: float,
        issue_deferred: int,
        private_issue_avoided: int,
        service_elide: int,
        frontier_windows: int,
        frontier_base_items: int,
        frontier_base_consumers: int,
        frontier_band_items: int,
        frontier_band_consumers: int,
        rowdesc_join_live: int,
        rowdesc_join_ready: int,
        rowdesc_late_join: int,
        preband_no_trigger: int,
        preband_replay_enqueued: int,
        preband_replay_dropped_budget: int,
        mfb_gather_owner_lines_useful: int,
        mfb_gather_owner_lines_dead: int,
        mfb_gather_owner_lines_useful_head2: int,
        mfb_gather_owner_lines_useful_tail: int,
        mfb_gather_owner_lines_dead_head2: int,
        mfb_gather_owner_lines_dead_tail: int,
        mfb_gather_resident_hits: int,
        mfb_gather_launched_bands_dead: int,
        mfb_gather_launched_bands_single_useful: int,
        mfb_gather_launched_bands_multi_useful: int,
        mfb_gather_launched_bands_head2_useful: int,
        mfb_gather_launched_bands_tail_only_useful: int,
        mfb_gather_launched_bands_head2_dead: int,
        mfb_gather_launched_bands_multi_resident: int,
        mfb_gather_launched_bands_resident_hits: int,
        actual_observe_enable,
        actual_observe_band_slots,
        actual_preband_band_slots,
        actual_gather_window_budget,
    ) -> Path:
        case_dir = runs_root / case_id
        run_dir = case_dir / run_name
        run_dir.mkdir(parents=True)
        summary = {
            "gas": {"cycle_cost": cycle_cost},
            "memory": {"memory_requests": memory_requests},
            "pulse": {
                "pulse_pod_rowdescriptor_owner_first_issue_deferred_total": issue_deferred,
                "pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total": private_issue_avoided,
                "pulse_pod_rowdescriptor_owner_first_service_elide_total": service_elide,
                "pulse_metadata_frontier_windows_total": frontier_windows,
                "pulse_metadata_frontier_base_items_exported_total": frontier_base_items,
                "pulse_metadata_frontier_base_consumer_count_sum_total": frontier_base_consumers,
                "pulse_metadata_frontier_band_items_exported_total": frontier_band_items,
                "pulse_metadata_frontier_band_consumer_count_sum_total": frontier_band_consumers,
                "pulse_rowdescriptor_owner_first_service_elide_join_live_total": rowdesc_join_live,
                "pulse_rowdescriptor_owner_first_service_elide_join_ready_total": rowdesc_join_ready,
                "pulse_rowdescriptor_owner_first_service_elide_late_join_total": rowdesc_late_join,
                "pulse_mfb_gather_preband_register_no_trigger_total": preband_no_trigger,
                "pulse_mfb_gather_preband_replay_enqueued_total": preband_replay_enqueued,
                "pulse_mfb_gather_preband_replay_dropped_budget_total": preband_replay_dropped_budget,
                "pulse_mfb_gather_owner_lines_useful_total": mfb_gather_owner_lines_useful,
                "pulse_mfb_gather_owner_lines_dead_total": mfb_gather_owner_lines_dead,
                "pulse_mfb_gather_owner_lines_useful_head2_total": mfb_gather_owner_lines_useful_head2,
                "pulse_mfb_gather_owner_lines_useful_tail_total": mfb_gather_owner_lines_useful_tail,
                "pulse_mfb_gather_owner_lines_dead_head2_total": mfb_gather_owner_lines_dead_head2,
                "pulse_mfb_gather_owner_lines_dead_tail_total": mfb_gather_owner_lines_dead_tail,
                "pulse_mfb_gather_resident_hits_total": mfb_gather_resident_hits,
                "pulse_mfb_gather_launched_bands_dead_total": mfb_gather_launched_bands_dead,
                "pulse_mfb_gather_launched_bands_single_useful_total": mfb_gather_launched_bands_single_useful,
                "pulse_mfb_gather_launched_bands_multi_useful_total": mfb_gather_launched_bands_multi_useful,
                "pulse_mfb_gather_launched_bands_head2_useful_total": mfb_gather_launched_bands_head2_useful,
                "pulse_mfb_gather_launched_bands_tail_only_useful_total": mfb_gather_launched_bands_tail_only_useful,
                "pulse_mfb_gather_launched_bands_head2_dead_total": mfb_gather_launched_bands_head2_dead,
                "pulse_mfb_gather_launched_bands_multi_resident_total": mfb_gather_launched_bands_multi_resident,
                "pulse_mfb_gather_launched_bands_resident_hits_total": mfb_gather_launched_bands_resident_hits,
            },
        }
        (run_dir / "essential_summary_mesh.json").write_text(
            json.dumps(summary),
            encoding="utf-8",
        )
        (run_dir / "effective_config.json").write_text(
            json.dumps(
                {
                    "pulse": {
                        "metadata_frontier_observe_enable": actual_observe_enable,
                        "metadata_frontier_band_slots": actual_observe_band_slots,
                        "mfb_preband_band_slots": actual_preband_band_slots,
                        "mfb_gather_window_budget": actual_gather_window_budget,
                    }
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "validation.log").write_text(
            "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
            encoding="utf-8",
        )
        latest = case_dir / "latest"
        latest.symlink_to(run_dir)
        return latest

    def _read_tsv(self, path: Path):
        rows = {}
        header = None
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if parts[0] == "case_id":
                    header = parts
                    continue
                self.assertIsNotNone(header)
                row = dict(zip(header, parts))
                rows[row["case_id"]] = row
        return rows


if __name__ == "__main__":
    unittest.main()
