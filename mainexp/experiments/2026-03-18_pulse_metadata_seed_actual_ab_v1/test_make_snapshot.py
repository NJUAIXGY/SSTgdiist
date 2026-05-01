import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"


class MakeSnapshotTest(unittest.TestCase):
    def test_generates_compare_tsv_with_metadata_seed_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            pulse_run = root / "pulse_run"
            baseline_run.mkdir()
            pulse_run.mkdir()

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
                pulse={
                    "pulse_shared_service_hits_total": 612972,
                    "pulse_shared_service_misses_total": 150907,
                    "pulse_region_service_entries_peak": 20480,
                    "pulse_ready_fanout_total": 763879,
                    "pulse_ready_fanout_avg": 5.062081542241049,
                    "pulse_actual_gate_taken_total": 763879,
                },
            )
            self._write_summary(
                pulse_run,
                sim_time_actual_ns=223910.0,
                memory_requests=150400.0,
                memory_bytes=9625600.0,
                memctrl_req_total=150400.0,
                apply_ns_avg=209800.0,
                gather_ns_avg=547.0,
                scatter_ns_avg=1.0,
                memctrl_payload_utilization=1.0,
                neurons_fired_total=1939.0,
                total_spikes_processed=1206784.0,
                pulse={
                    "pulse_shared_service_hits_total": 613500,
                    "pulse_shared_service_misses_total": 150400,
                    "pulse_region_service_entries_peak": 20480,
                    "pulse_ready_fanout_total": 764100,
                    "pulse_ready_fanout_avg": 5.0800,
                    "pulse_actual_gate_taken_total": 763400,
                    "pulse_metadata_seed_candidates_total": 320,
                    "pulse_mfb_owner_eligible_total": 120,
                    "pulse_mfb_owner_launched_total": 60,
                    "pulse_mfb_preband_candidates_total": 48,
                    "pulse_mfb_preband_lines_selected_total": 144,
                    "pulse_mfb_preband_lines_owner_total": 108,
                    "pulse_mfb_preband_lines_join_only_total": 36,
                    "pulse_metadata_seed_prefetch_owner_total": 96,
                    "pulse_metadata_seed_prefetch_issue_deferred_total": 12,
                    "pulse_metadata_seed_join_only_total": 24,
                    "pulse_metadata_seed_owner_already_exists_total": 24,
                    "pulse_metadata_seed_resident_hits_total": 288,
                    "pulse_metadata_seed_useful_total": 72,
                    "pulse_metadata_seed_resident_lines_peak": 18,
                    "pulse_mfb_owner_first_rate": 0.5,
                    "pulse_metadata_seed_usefulness_ratio": 0.75,
                    "pulse_metadata_seed_avg_hits_per_useful_seed": 4.0,
                },
            )

            (baseline_run / "validation.log").write_text(
                "[val] SUMMARY run_dir=/tmp/base fail=0 warn=0 strict=0\n",
                encoding="utf-8",
            )
            (pulse_run / "validation.log").write_text(
                "[val] SUMMARY run_dir=/tmp/pulse fail=0 warn=0 strict=0\n",
                encoding="utf-8",
            )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "pulse_metadata_seed_actual_test",
                        "baseline_case": "baseline",
                        "cases": [
                            {"id": "baseline", "label": "baseline", "run_dir": str(baseline_run)},
                            {"id": "metadata_seed", "label": "metadata_seed", "run_dir": str(pulse_run)},
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
            self.assertEqual(rows["validation.fail"], ["0", "0", "0"])
            self.assertEqual(rows["validation.warn"], ["0", "0", "0"])
            self.assertEqual(rows["validation.strict"], ["0", "0", "0"])
            self.assertEqual(rows["model.sim_time_actual_ns"], ["224813.0", "223910.0", "-903.0"])
            self.assertEqual(rows["memory.memory_requests"], ["150907.0", "150400.0", "-507.0"])
            self.assertEqual(rows["pulse_shared_service_hits_total"], ["612972", "613500", "528"])
            self.assertEqual(rows["pulse_metadata_seed_candidates_total"], ["0", "320", "320"])
            self.assertEqual(rows["pulse_mfb_owner_eligible_total"], ["0", "120", "120"])
            self.assertEqual(rows["pulse_mfb_owner_launched_total"], ["0", "60", "60"])
            self.assertEqual(rows["pulse_mfb_preband_candidates_total"], ["0", "48", "48"])
            self.assertEqual(rows["pulse_mfb_preband_lines_selected_total"], ["0", "144", "144"])
            self.assertEqual(rows["pulse_mfb_preband_lines_owner_total"], ["0", "108", "108"])
            self.assertEqual(rows["pulse_mfb_preband_lines_join_only_total"], ["0", "36", "36"])
            self.assertEqual(rows["pulse_metadata_seed_prefetch_owner_total"], ["0", "96", "96"])
            self.assertEqual(rows["pulse_metadata_seed_prefetch_issue_deferred_total"], ["0", "12", "12"])
            self.assertEqual(rows["pulse_metadata_seed_join_only_total"], ["0", "24", "24"])
            self.assertEqual(rows["pulse_metadata_seed_owner_already_exists_total"], ["0", "24", "24"])
            self.assertEqual(rows["pulse_metadata_seed_resident_hits_total"], ["0", "288", "288"])
            self.assertEqual(rows["pulse_metadata_seed_useful_total"], ["0", "72", "72"])
            self.assertEqual(rows["pulse_metadata_seed_resident_lines_peak"], ["0", "18", "18"])
            self.assertEqual(rows["pulse_mfb_owner_first_rate"], ["0", "0.5", "0.5"])
            self.assertEqual(rows["pulse_metadata_seed_usefulness_ratio"], ["0", "0.75", "0.75"])
            self.assertEqual(rows["pulse_metadata_seed_avg_hits_per_useful_seed"], ["0", "4.0", "4.0"])

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
                metric, baseline, pulse, delta = line.split("\t")
                rows[metric] = [baseline, pulse, delta]
        return rows


if __name__ == "__main__":
    unittest.main()
