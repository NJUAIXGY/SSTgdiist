import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"


class MakeSnapshotTest(unittest.TestCase):
    def test_generates_compare_tsv_with_owner_first_and_frontier_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            combo_run = root / "combo_run"
            baseline_run.mkdir()
            combo_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=224963.0,
                memory_requests=150907.0,
                memory_bytes=9658048.0,
                memctrl_req_total=150907.0,
                apply_ns_avg=210210.0,
                gather_ns_avg=547.0,
                scatter_ns_avg=1.0,
                cycle_cost=224963.0,
                synapse_ops_step_total=1206784.0,
                pulse={
                    "pulse_mfb_gather_owner_first_rate": 0.9841269841269841,
                    "pulse_pod_rowdescriptor_owner_first_issue_deferred_total": 1153,
                    "pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total": 1153,
                    "pulse_pod_rowdescriptor_owner_first_service_elide_total": 189,
                    "pulse_rowdescriptor_owner_first_service_elide_join_live_total": 40,
                    "pulse_rowdescriptor_owner_first_service_elide_join_ready_total": 149,
                    "pulse_rowdescriptor_owner_first_service_elide_late_join_total": 17,
                    "pulse_mfb_gather_preband_register_no_trigger_total": 320,
                    "pulse_mfb_gather_preband_replay_enqueued_total": 140,
                    "pulse_mfb_gather_preband_replay_dropped_budget_total": 20,
                    "pulse_metadata_frontier_windows_total": 0,
                    "pulse_metadata_frontier_base_items_exported_total": 0,
                    "pulse_metadata_frontier_base_overlap_items_total": 0,
                    "pulse_metadata_frontier_base_overlap_peer_total": 0,
                    "pulse_metadata_frontier_base_consumer_count_sum_total": 0,
                    "pulse_metadata_frontier_band_items_exported_total": 0,
                    "pulse_metadata_frontier_band_overlap_items_total": 0,
                    "pulse_metadata_frontier_band_overlap_peer_total": 0,
                    "pulse_metadata_frontier_band_consumer_count_sum_total": 0,
                    "pulse_mfb_gather_owner_lines_useful_total": 40,
                    "pulse_mfb_gather_owner_lines_dead_total": 3,
                    "pulse_mfb_gather_owner_lines_useful_head2_total": 24,
                    "pulse_mfb_gather_owner_lines_useful_tail_total": 16,
                    "pulse_mfb_gather_owner_lines_dead_head2_total": 1,
                    "pulse_mfb_gather_owner_lines_dead_tail_total": 2,
                    "pulse_mfb_gather_resident_hits_total": 55,
                    "pulse_mfb_gather_launched_bands_dead_total": 4,
                    "pulse_mfb_gather_launched_bands_single_useful_total": 6,
                    "pulse_mfb_gather_launched_bands_multi_useful_total": 8,
                    "pulse_mfb_gather_launched_bands_head2_useful_total": 5,
                    "pulse_mfb_gather_launched_bands_tail_only_useful_total": 9,
                    "pulse_mfb_gather_launched_bands_head2_dead_total": 3,
                    "pulse_mfb_gather_launched_bands_multi_resident_total": 7,
                    "pulse_mfb_gather_launched_bands_resident_hits_total": 11,
                },
                effective_pulse={
                    "metadata_frontier_observe_enable": 0,
                    "metadata_frontier_band_slots": 128,
                    "mfb_preband_band_slots": None,
                    "mfb_gather_window_budget": 6,
                },
            )
            self._write_summary(
                combo_run,
                sim_time_actual_ns=224813.0,
                memory_requests=150907.0,
                memory_bytes=9658048.0,
                memctrl_req_total=150907.0,
                apply_ns_avg=210100.0,
                gather_ns_avg=547.0,
                scatter_ns_avg=1.0,
                cycle_cost=224813.0,
                synapse_ops_step_total=1206784.0,
                pulse={
                    "pulse_mfb_gather_owner_first_rate": 0.9841269841269841,
                    "pulse_pod_rowdescriptor_owner_first_issue_deferred_total": 1153,
                    "pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total": 1153,
                    "pulse_pod_rowdescriptor_owner_first_service_elide_total": 189,
                    "pulse_rowdescriptor_owner_first_service_elide_join_live_total": 52,
                    "pulse_rowdescriptor_owner_first_service_elide_join_ready_total": 137,
                    "pulse_rowdescriptor_owner_first_service_elide_late_join_total": 29,
                    "pulse_mfb_gather_preband_register_no_trigger_total": 210,
                    "pulse_mfb_gather_preband_replay_enqueued_total": 188,
                    "pulse_mfb_gather_preband_replay_dropped_budget_total": 46,
                    "pulse_metadata_frontier_windows_total": 320,
                    "pulse_metadata_frontier_base_items_exported_total": 20480,
                    "pulse_metadata_frontier_base_overlap_items_total": 19268,
                    "pulse_metadata_frontier_base_overlap_peer_total": 175028,
                    "pulse_metadata_frontier_base_consumer_count_sum_total": 195508,
                    "pulse_metadata_frontier_band_items_exported_total": 320,
                    "pulse_metadata_frontier_band_overlap_items_total": 304,
                    "pulse_metadata_frontier_band_overlap_peer_total": 3040,
                    "pulse_metadata_frontier_band_consumer_count_sum_total": 3360,
                    "pulse_mfb_gather_owner_lines_useful_total": 30,
                    "pulse_mfb_gather_owner_lines_dead_total": 5,
                    "pulse_mfb_gather_owner_lines_useful_head2_total": 18,
                    "pulse_mfb_gather_owner_lines_useful_tail_total": 12,
                    "pulse_mfb_gather_owner_lines_dead_head2_total": 3,
                    "pulse_mfb_gather_owner_lines_dead_tail_total": 2,
                    "pulse_mfb_gather_resident_hits_total": 45,
                    "pulse_mfb_gather_launched_bands_dead_total": 6,
                    "pulse_mfb_gather_launched_bands_single_useful_total": 4,
                    "pulse_mfb_gather_launched_bands_multi_useful_total": 9,
                    "pulse_mfb_gather_launched_bands_head2_useful_total": 3,
                    "pulse_mfb_gather_launched_bands_tail_only_useful_total": 10,
                    "pulse_mfb_gather_launched_bands_head2_dead_total": 5,
                    "pulse_mfb_gather_launched_bands_multi_resident_total": 8,
                    "pulse_mfb_gather_launched_bands_resident_hits_total": 10,
                },
                effective_pulse={
                    "metadata_frontier_observe_enable": 1,
                    "metadata_frontier_band_slots": 128,
                    "mfb_preband_band_slots": 80,
                    "mfb_gather_window_budget": 6,
                },
            )

            for run_dir in (baseline_run, combo_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "pulse_owner_first_frontier_combo_test",
                        "baseline_case": "dedup_off",
                        "cases": [
                            {"id": "dedup_off", "label": "dedup_off", "run_dir": str(baseline_run)},
                            {"id": "dedup_off_frontier_top64_band256", "label": "dedup_off_frontier_top64_band256", "run_dir": str(combo_run)},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertTrue(out_path.exists())

            rows = self._read_tsv(out_path)
            self.assertEqual(rows["validation.fail"], ["0", "0", "0"])
            self.assertEqual(rows["gas.cycle_cost"], ["224963.0", "224813.0", "-150.0"])
            self.assertEqual(
                rows["pulse_pod_rowdescriptor_owner_first_issue_deferred_total"],
                ["1153", "1153", "0"],
            )
            self.assertEqual(
                rows["pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total"],
                ["1153", "1153", "0"],
            )
            self.assertEqual(
                rows["pulse_pod_rowdescriptor_owner_first_service_elide_total"],
                ["189", "189", "0"],
            )
            self.assertEqual(
                rows["pulse_metadata_frontier_windows_total"],
                ["0", "320", "320"],
            )
            self.assertEqual(
                rows["pulse_metadata_frontier_base_items_exported_total"],
                ["0", "20480", "20480"],
            )
            self.assertEqual(
                rows["pulse_metadata_frontier_base_consumer_count_sum_total"],
                ["0", "195508", "195508"],
            )
            self.assertEqual(
                rows["pulse_metadata_frontier_band_items_exported_total"],
                ["0", "320", "320"],
            )
            self.assertEqual(
                rows["pulse_metadata_frontier_band_consumer_count_sum_total"],
                ["0", "3360", "3360"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_owner_first_service_elide_join_live_total"],
                ["40", "52", "12"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_owner_first_service_elide_join_ready_total"],
                ["149", "137", "-12"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_owner_first_service_elide_late_join_total"],
                ["17", "29", "12"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_preband_register_no_trigger_total"],
                ["320", "210", "-110"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_preband_replay_enqueued_total"],
                ["140", "188", "48"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_preband_replay_dropped_budget_total"],
                ["20", "46", "26"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_lines_useful_total"],
                ["40", "30", "-10"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_lines_dead_total"],
                ["3", "5", "2"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_lines_useful_head2_total"],
                ["24", "18", "-6"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_lines_useful_tail_total"],
                ["16", "12", "-4"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_lines_dead_head2_total"],
                ["1", "3", "2"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_lines_dead_tail_total"],
                ["2", "2", "0"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_resident_hits_total"],
                ["55", "45", "-10"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_launched_bands_dead_total"],
                ["4", "6", "2"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_launched_bands_single_useful_total"],
                ["6", "4", "-2"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_launched_bands_multi_useful_total"],
                ["8", "9", "1"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_launched_bands_head2_useful_total"],
                ["5", "3", "-2"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_launched_bands_tail_only_useful_total"],
                ["9", "10", "1"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_launched_bands_head2_dead_total"],
                ["3", "5", "2"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_launched_bands_multi_resident_total"],
                ["7", "8", "1"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_launched_bands_resident_hits_total"],
                ["11", "10", "-1"],
            )
            self.assertEqual(
                rows["effective.pulse.metadata_frontier_observe_enable"],
                ["0", "1", "1"],
            )
            self.assertEqual(
                rows["effective.pulse.metadata_frontier_band_slots"],
                ["128", "128", "0"],
            )
            self.assertEqual(
                rows["effective.pulse.mfb_preband_band_slots"],
                ["None", "80", "NA"],
            )
            self.assertEqual(
                rows["effective.pulse.mfb_gather_window_budget"],
                ["6", "6", "0"],
            )

    def _write_summary(
        self,
        run_dir,
        *,
        sim_time_actual_ns,
        memory_requests,
        memory_bytes,
        memctrl_req_total,
        apply_ns_avg,
        gather_ns_avg,
        scatter_ns_avg,
        cycle_cost,
        synapse_ops_step_total,
        pulse,
        effective_pulse,
    ):
        payload = {
            "model": {"sim_time_actual_ns": sim_time_actual_ns},
            "memory": {
                "memory_requests": memory_requests,
                "memory_bytes": memory_bytes,
            },
            "memhierarchy": {"memctrl": {"req_total": memctrl_req_total}},
            "gas": {
                "apply_ns_avg": apply_ns_avg,
                "gather_ns_avg": gather_ns_avg,
                "scatter_ns_avg": scatter_ns_avg,
                "cycle_cost": cycle_cost,
                "synapse_ops_step_total": synapse_ops_step_total,
            },
            "pulse": pulse,
        }
        (run_dir / "essential_summary_mesh.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        (run_dir / "effective_config.json").write_text(
            json.dumps({"pulse": effective_pulse}),
            encoding="utf-8",
        )

    def _read_tsv(self, path):
        rows = {}
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                metric, baseline, pulse, delta = line.split("\t")
                rows[metric] = [baseline, pulse, delta]
        return rows


if __name__ == "__main__":
    unittest.main()
