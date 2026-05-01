import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_repeat_summary.py"
BASELINE_CASE = "pulse_shared_line_actual_mfb_gather_preband_dedup_off"
TARGET_CASE = (
    "pulse_shared_line_actual_mfb_gather_preband_dedup_off_"
    "metadata_frontier_top32_observe_band128_preband_band96_budget6"
)


class MakeRepeatSummaryTest(unittest.TestCase):
    def test_generates_repeat_summary_with_mean_min_max_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root = root / "runs"
            runs_root.mkdir()

            self._make_run(
                runs_root / BASELINE_CASE / "20260327-100000",
                cycle_cost=224963.0,
                issue_deferred=1153,
                service_elide=189,
                rowdesc_join_live=40,
                rowdesc_join_ready=149,
                rowdesc_late_join=17,
                preband_no_trigger=320,
                preband_replay_enqueued=140,
                preband_replay_dropped_budget=20,
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
                elapsed="6:22.04",
                exit_status=0,
                actual_observe_enable=0,
                actual_observe_band_slots=128,
                actual_preband_band_slots=None,
                actual_gather_window_budget=6,
            )
            self._make_run(
                runs_root / TARGET_CASE / "20260327-110000",
                cycle_cost=224867.0,
                issue_deferred=1426,
                service_elide=194,
                rowdesc_join_live=53,
                rowdesc_join_ready=141,
                rowdesc_late_join=19,
                preband_no_trigger=260,
                preband_replay_enqueued=20,
                preband_replay_dropped_budget=3,
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
                elapsed="6:20.10",
                exit_status=0,
                actual_observe_enable=1,
                actual_observe_band_slots=128,
                actual_preband_band_slots=None,
                actual_gather_window_budget=6,
            )
            self._make_run(
                runs_root / TARGET_CASE / "20260327-120000",
                cycle_cost=224900.0,
                issue_deferred=1400,
                service_elide=193,
                rowdesc_join_live=51,
                rowdesc_join_ready=142,
                rowdesc_late_join=21,
                preband_no_trigger=255,
                preband_replay_enqueued=25,
                preband_replay_dropped_budget=4,
                mfb_gather_owner_lines_useful=60,
                mfb_gather_owner_lines_dead=15,
                mfb_gather_owner_lines_useful_head2=36,
                mfb_gather_owner_lines_useful_tail=24,
                mfb_gather_owner_lines_dead_head2=9,
                mfb_gather_owner_lines_dead_tail=6,
                mfb_gather_resident_hits=70,
                mfb_gather_launched_bands_dead=10,
                mfb_gather_launched_bands_single_useful=6,
                mfb_gather_launched_bands_multi_useful=9,
                mfb_gather_launched_bands_head2_useful=6,
                mfb_gather_launched_bands_tail_only_useful=9,
                mfb_gather_launched_bands_head2_dead=7,
                mfb_gather_launched_bands_multi_resident=8,
                mfb_gather_launched_bands_resident_hits=11,
                elapsed="6:21.50",
                exit_status=0,
                actual_observe_enable=1,
                actual_observe_band_slots=128,
                actual_preband_band_slots=96,
                actual_gather_window_budget=6,
            )

            out_path = root / "snapshot" / "repeat_summary.tsv"
            proc = subprocess.run(
                [
                    "python3",
                    str(SCRIPT_PATH),
                    "--runs-root",
                    str(runs_root),
                    "--case-id",
                    TARGET_CASE,
                    "--out",
                    str(out_path),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertTrue(out_path.exists())

            text = out_path.read_text(encoding="utf-8")
            self.assertIn("# repeat_count\t2", text)
            self.assertIn("# delta_cycle_mean\t-79.5", text)
            self.assertIn("# delta_cycle_min\t-96", text)
            self.assertIn("# delta_cycle_max\t-63", text)

            rows = self._read_tsv(out_path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["run_name"], "20260327-110000")
            self.assertEqual(rows[0]["delta_cycle_vs_baseline"], "-96")
            self.assertEqual(rows[0]["rowdesc_join_live"], "53")
            self.assertEqual(rows[0]["rowdesc_join_ready"], "141")
            self.assertEqual(rows[0]["rowdesc_late_join"], "19")
            self.assertEqual(rows[0]["preband_no_trigger"], "260")
            self.assertEqual(rows[0]["preband_replay_enqueued"], "20")
            self.assertEqual(rows[0]["preband_replay_dropped_budget"], "3")
            self.assertEqual(rows[0]["mfb_gather_owner_lines_useful"], "50")
            self.assertEqual(rows[0]["mfb_gather_owner_lines_dead"], "10")
            self.assertEqual(rows[0]["mfb_gather_owner_lines_dead_head2"], "6")
            self.assertEqual(rows[0]["mfb_gather_owner_lines_dead_tail"], "4")
            self.assertEqual(rows[0]["mfb_gather_launched_bands_useful"], "12")
            self.assertEqual(rows[0]["mfb_gather_launched_bands_useful_ratio"], "0.6")
            self.assertEqual(rows[0]["mfb_gather_launched_bands_dead_ratio"], "0.4")
            self.assertEqual(rows[0]["mfb_gather_launched_bands_head2_useful"], "4")
            self.assertEqual(rows[0]["mfb_gather_launched_bands_tail_only_useful"], "8")
            self.assertEqual(rows[0]["mfb_gather_launched_bands_head2_dead"], "5")
            self.assertEqual(rows[0]["mfb_gather_launched_bands_head2_useful_ratio"], "0.2")
            self.assertEqual(rows[0]["mfb_gather_launched_bands_tail_only_useful_ratio"], "0.4")
            self.assertEqual(rows[0]["mfb_gather_launched_bands_head2_dead_ratio"], "0.25")
            self.assertEqual(rows[0]["mfb_gather_owner_lines_useful_per_replay"], "2.5")
            self.assertEqual(rows[0]["mfb_gather_resident_hits_per_replay"], "3")
            self.assertEqual(rows[0]["mfb_gather_owner_lines_dead_head2_share"], "0.6")
            self.assertEqual(rows[0]["mfb_gather_owner_lines_dead_tail_share"], "0.4")
            self.assertEqual(rows[0]["rowdescriptor_service_elide_per_useful_owner_line"], "3.88")
            self.assertEqual(rows[0]["rowdescriptor_service_elide_per_replay"], "9.7")
            self.assertEqual(rows[0]["actual_observe_enable"], "1")
            self.assertEqual(rows[0]["actual_observe_band_slots"], "128")
            self.assertEqual(rows[0]["actual_preband_band_slots"], "None")
            self.assertEqual(rows[0]["actual_gather_window_budget"], "6")
            self.assertEqual(rows[0]["observe_band_slots_mismatch"], "0")
            self.assertEqual(rows[0]["preband_band_slots_mismatch"], "1")
            self.assertEqual(rows[0]["gather_window_budget_mismatch"], "0")
            self.assertEqual(rows[0]["config_drift_any"], "1")
            self.assertEqual(rows[0]["elapsed_wall"], "6:20.10")
            self.assertEqual(rows[1]["run_name"], "20260327-120000")
            self.assertEqual(rows[1]["delta_cycle_vs_baseline"], "-63")
            self.assertEqual(rows[1]["preband_replay_dropped_budget"], "4")
            self.assertEqual(rows[1]["mfb_gather_launched_bands_useful"], "15")
            self.assertEqual(rows[1]["mfb_gather_launched_bands_useful_ratio"], "0.6")
            self.assertEqual(rows[1]["mfb_gather_launched_bands_head2_useful"], "6")
            self.assertEqual(rows[1]["mfb_gather_launched_bands_tail_only_useful"], "9")
            self.assertEqual(rows[1]["mfb_gather_launched_bands_head2_dead"], "7")
            self.assertEqual(rows[1]["mfb_gather_owner_lines_dead_head2_share"], "0.6")
            self.assertEqual(rows[1]["actual_preband_band_slots"], "96")
            self.assertEqual(rows[1]["preband_band_slots_mismatch"], "0")
            self.assertEqual(rows[1]["config_drift_any"], "0")

    def _make_run(
        self,
        run_dir: Path,
        *,
        cycle_cost: float,
        issue_deferred: int,
        service_elide: int,
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
        elapsed: str,
        exit_status: int,
        actual_observe_enable,
        actual_observe_band_slots,
        actual_preband_band_slots,
        actual_gather_window_budget,
    ) -> None:
        run_dir.mkdir(parents=True)
        summary = {
            "gas": {"cycle_cost": cycle_cost},
            "memory": {"memory_requests": 150907.0},
            "pulse": {
                "pulse_pod_rowdescriptor_owner_first_issue_deferred_total": issue_deferred,
                "pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total": issue_deferred,
                "pulse_pod_rowdescriptor_owner_first_service_elide_total": service_elide,
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
        (run_dir / "essential_summary_mesh.json").write_text(json.dumps(summary), encoding="utf-8")
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
        (run_dir / "time.txt").write_text(
            "\n".join(
                [
                    f"Elapsed (wall clock) time (h:mm:ss or m:ss): {elapsed}",
                    f"Exit status: {exit_status}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def _read_tsv(self, path: Path):
        header = None
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] == "run_name":
                header = parts
                continue
            self.assertIsNotNone(header)
            rows.append(dict(zip(header, parts)))
        return rows


if __name__ == "__main__":
    unittest.main()
