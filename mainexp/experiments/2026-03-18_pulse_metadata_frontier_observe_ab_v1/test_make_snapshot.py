import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"


class MakeSnapshotTest(unittest.TestCase):
    def test_generates_compare_tsv_with_metadata_frontier_metrics(self):
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
                memory_bytes=0.0,
                memctrl_req_total=150907.0,
                apply_ns_avg=0.0,
                gather_ns_avg=0.0,
                scatter_ns_avg=0.0,
                memctrl_payload_utilization=0.0,
                pulse={
                    "pulse_shared_service_hits_total": 612972,
                    "pulse_shared_service_misses_total": 150907,
                    "pulse_region_service_entries_peak": 64,
                    "pulse_ready_fanout_total": 763879,
                    "pulse_actual_gate_taken_total": 763879,
                },
            )
            self._write_summary(
                pulse_run,
                sim_time_actual_ns=224813.0,
                memory_requests=150907.0,
                memory_bytes=0.0,
                memctrl_req_total=150907.0,
                apply_ns_avg=0.0,
                gather_ns_avg=0.0,
                scatter_ns_avg=0.0,
                memctrl_payload_utilization=0.0,
                pulse={
                    "pulse_shared_service_hits_total": 612972,
                    "pulse_shared_service_misses_total": 150907,
                    "pulse_region_service_entries_peak": 64,
                    "pulse_ready_fanout_total": 763879,
                    "pulse_actual_gate_taken_total": 763879,
                    "pulse_metadata_frontier_windows_total": 12,
                    "pulse_metadata_frontier_base_items_exported_total": 96,
                    "pulse_metadata_frontier_base_overlap_items_total": 24,
                    "pulse_metadata_frontier_base_overlap_peer_total": 36,
                    "pulse_metadata_frontier_base_consumer_count_sum_total": 60,
                    "pulse_metadata_frontier_base_max_exported_per_window": 16,
                    "pulse_metadata_frontier_base_overlap_ratio": 0.25,
                    "pulse_metadata_frontier_base_avg_peer_overlap": 1.5,
                    "pulse_metadata_frontier_band_items_exported_total": 80,
                    "pulse_metadata_frontier_band_overlap_items_total": 28,
                    "pulse_metadata_frontier_band_overlap_peer_total": 49,
                    "pulse_metadata_frontier_band_consumer_count_sum_total": 77,
                    "pulse_metadata_frontier_band_max_exported_per_window": 14,
                    "pulse_metadata_frontier_band_overlap_ratio": 0.35,
                    "pulse_metadata_frontier_band_avg_peer_overlap": 1.75,
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
                        "experiment_id": "pulse_metadata_frontier_observe_test",
                        "baseline_case": "baseline",
                        "cases": [
                            {"id": "baseline", "label": "baseline", "run_dir": str(baseline_run)},
                            {"id": "metadata_frontier", "label": "metadata_frontier", "run_dir": str(pulse_run)},
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
            self.assertEqual(rows["model.sim_time_actual_ns"], ["224813.0", "224813.0", "0.0"])
            self.assertEqual(rows["memory.memory_requests"], ["150907.0", "150907.0", "0.0"])
            self.assertEqual(rows["pulse_shared_service_hits_total"], ["612972", "612972", "0"])
            self.assertEqual(rows["pulse_metadata_frontier_windows_total"], ["0", "12", "12"])
            self.assertEqual(rows["pulse_metadata_frontier_base_items_exported_total"], ["0", "96", "96"])
            self.assertEqual(rows["pulse_metadata_frontier_base_overlap_items_total"], ["0", "24", "24"])
            self.assertEqual(rows["pulse_metadata_frontier_base_overlap_peer_total"], ["0", "36", "36"])
            self.assertEqual(rows["pulse_metadata_frontier_base_consumer_count_sum_total"], ["0", "60", "60"])
            self.assertEqual(rows["pulse_metadata_frontier_base_max_exported_per_window"], ["0", "16", "16"])
            self.assertEqual(rows["pulse_metadata_frontier_base_overlap_ratio"], ["0", "0.25", "0.25"])
            self.assertEqual(rows["pulse_metadata_frontier_base_avg_peer_overlap"], ["0", "1.5", "1.5"])
            self.assertEqual(rows["pulse_metadata_frontier_band_items_exported_total"], ["0", "80", "80"])
            self.assertEqual(rows["pulse_metadata_frontier_band_overlap_items_total"], ["0", "28", "28"])
            self.assertEqual(rows["pulse_metadata_frontier_band_overlap_peer_total"], ["0", "49", "49"])
            self.assertEqual(rows["pulse_metadata_frontier_band_consumer_count_sum_total"], ["0", "77", "77"])
            self.assertEqual(rows["pulse_metadata_frontier_band_max_exported_per_window"], ["0", "14", "14"])
            self.assertEqual(rows["pulse_metadata_frontier_band_overlap_ratio"], ["0", "0.35", "0.35"])
            self.assertEqual(rows["pulse_metadata_frontier_band_avg_peer_overlap"], ["0", "1.75", "1.75"])

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
