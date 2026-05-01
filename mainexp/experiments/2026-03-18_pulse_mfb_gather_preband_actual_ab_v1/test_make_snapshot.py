import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"


class MakeSnapshotTest(unittest.TestCase):
    def test_generates_compare_tsv_with_gather_and_reference_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            gather_run = root / "gather_run"
            reference_run = root / "reference_run"
            baseline_run.mkdir()
            gather_run.mkdir()
            reference_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=224813.0,
                memory_requests=150907.0,
                memory_bytes=9658048.0,
                memctrl_req_total=150907.0,
                apply_ns_avg=210210.75,
                gather_ns_avg=547.0,
                scatter_ns_avg=1.0,
                memctrl_payload_utilization=1.0,
                neurons_fired_total=1939.0,
                total_spikes_processed=1206784.0,
                pulse={},
            )
            self._write_summary(
                gather_run,
                sim_time_actual_ns=223950.0,
                memory_requests=150500.0,
                memory_bytes=9632000.0,
                memctrl_req_total=150500.0,
                apply_ns_avg=209950.0,
                gather_ns_avg=547.0,
                scatter_ns_avg=1.0,
                memctrl_payload_utilization=1.0,
                neurons_fired_total=1939.0,
                total_spikes_processed=1206784.0,
                pulse={
                    "pulse_shared_service_hits_total": 613100,
                    "pulse_shared_service_misses_total": 150500,
                    "pulse_region_service_entries_peak": 20480,
                    "pulse_ready_fanout_total": 764000,
                    "pulse_ready_fanout_avg": 5.07,
                    "pulse_actual_gate_taken_total": 763700,
                    "pulse_mfb_gather_owner_eligible_total": 90,
                    "pulse_mfb_gather_owner_launched_total": 54,
                    "pulse_mfb_gather_preband_candidates_total": 42,
                    "pulse_mfb_gather_preband_lines_selected_total": 126,
                    "pulse_mfb_gather_preband_lines_owner_total": 81,
                    "pulse_mfb_gather_preband_lines_join_only_total": 27,
                    "pulse_mfb_gather_head_distance_sum_total": 162,
                    "pulse_mfb_gather_head_distance_samples_total": 27,
                    "pulse_mfb_gather_head_distance_avg": 6.0,
                    "pulse_mfb_gather_seed_to_first_demand_cycles_total": 486,
                    "pulse_mfb_gather_seed_to_first_demand_samples_total": 27,
                    "pulse_mfb_gather_seed_to_first_demand_cycles_avg": 18.0,
                    "pulse_mfb_gather_seed_ready_before_demand_total": 36,
                    "pulse_mfb_gather_seed_inflight_join_total": 9,
                    "pulse_mfb_gather_owner_lines_useful_total": 45,
                    "pulse_mfb_gather_owner_lines_dead_total": 36,
                    "pulse_mfb_gather_owner_lines_useful_ratio": 45.0 / 81.0,
                    "pulse_mfb_gather_owner_lines_dead_ratio": 36.0 / 81.0,
                    "pulse_mfb_gather_owner_first_rate": 0.6,
                    "pulse_mfb_gather_ready_before_demand_ratio": 0.4444444444,
                },
            )
            self._write_summary(
                reference_run,
                sim_time_actual_ns=224020.0,
                memory_requests=150610.0,
                memory_bytes=9639040.0,
                memctrl_req_total=150610.0,
                apply_ns_avg=210020.0,
                gather_ns_avg=547.0,
                scatter_ns_avg=1.0,
                memctrl_payload_utilization=1.0,
                neurons_fired_total=1939.0,
                total_spikes_processed=1206784.0,
                pulse={
                    "pulse_shared_service_hits_total": 613500,
                    "pulse_shared_service_misses_total": 150610,
                    "pulse_region_service_entries_peak": 20480,
                    "pulse_ready_fanout_total": 764100,
                    "pulse_ready_fanout_avg": 5.08,
                    "pulse_actual_gate_taken_total": 763400,
                    "pulse_mfb_owner_eligible_total": 120,
                    "pulse_mfb_owner_launched_total": 60,
                    "pulse_mfb_preband_candidates_total": 48,
                    "pulse_mfb_preband_lines_selected_total": 144,
                    "pulse_mfb_preband_lines_owner_total": 108,
                    "pulse_mfb_preband_lines_join_only_total": 36,
                    "pulse_mfb_head_distance_sum_total": 120,
                    "pulse_mfb_head_distance_samples_total": 24,
                    "pulse_mfb_head_distance_avg": 5.0,
                    "pulse_mfb_seed_to_first_demand_cycles_total": 360,
                    "pulse_mfb_seed_to_first_demand_samples_total": 30,
                    "pulse_mfb_seed_to_first_demand_cycles_avg": 12.0,
                    "pulse_mfb_seed_ready_before_demand_total": 18,
                    "pulse_mfb_seed_inflight_join_total": 12,
                    "pulse_mfb_owner_first_rate": 0.5,
                },
            )

            for run_dir in (baseline_run, gather_run, reference_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "pulse_mfb_gather_preband_actual_test",
                        "baseline_case": "baseline",
                        "cases": [
                            {"id": "baseline", "label": "baseline", "run_dir": str(baseline_run)},
                            {"id": "gather_preband", "label": "gather_preband", "run_dir": str(gather_run)},
                            {"id": "mfb_preband_ref", "label": "mfb_preband_ref", "run_dir": str(reference_run)},
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
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(out_path.exists())

            rows = self._read_tsv(out_path)
            self.assertEqual(
                rows["model.sim_time_actual_ns"],
                ["224813.0", "223950.0", "-863.0", "224020.0", "-793.0"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_eligible_total"],
                ["0", "90", "90", "0", "0"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_seed_ready_before_demand_total"],
                ["0", "36", "36", "0", "0"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_ready_before_demand_ratio"],
                ["0", "0.4444444444", "0.4444444444", "0", "0"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_lines_useful_total"],
                ["0", "45", "45", "0", "0"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_lines_dead_total"],
                ["0", "36", "36", "0", "0"],
            )
            self.assertEqual(
                rows["pulse_mfb_preband_candidates_total"],
                ["0", "0", "0", "48", "48"],
            )
            self.assertEqual(
                rows["pulse_mfb_owner_first_rate"],
                ["0", "0", "0", "0.5", "0.5"],
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
        memctrl_payload_utilization,
        neurons_fired_total,
        total_spikes_processed,
        pulse,
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
                "memctrl_payload_utilization": memctrl_payload_utilization,
            },
            "spike_activity": {
                "neurons_fired_total": neurons_fired_total,
                "total_spikes_processed": total_spikes_processed,
            },
            "pulse": pulse,
        }
        (run_dir / "essential_summary_mesh.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def _read_tsv(self, path):
        rows = {}
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                rows[parts[0]] = parts[1:]
        return rows


if __name__ == "__main__":
    unittest.main()
