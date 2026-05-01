import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"


class MakeSnapshotTest(unittest.TestCase):
    def test_generates_compare_tsv_with_stage_a_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            pulse_run = root / "pulse_run"
            baseline_run.mkdir()
            pulse_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=257453.0,
                memory_requests=763879.0,
                memory_bytes=0.0,
                memctrl_req_total=150907.0,
                apply_ns_avg=0.0,
                gather_ns_avg=0.0,
                scatter_ns_avg=0.0,
                memctrl_payload_utilization=0.0,
                neurons_fired_total=0.0,
                total_spikes_processed=0.0,
                pulse={},
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
                neurons_fired_total=0.0,
                total_spikes_processed=0.0,
                pulse={
                    "pulse_shared_service_hits_total": 612972,
                    "pulse_shared_service_misses_total": 150907,
                    "pulse_ready_fanout_total": 763879,
                    "pulse_actual_gate_enable_false_total": 0,
                    "pulse_actual_gate_window_zero_total": 0,
                    "pulse_actual_gate_line_too_small_total": 0,
                    "pulse_actual_gate_taken_total": 763879,
                    "pulse_ready_fanout_avg": 763879.0 / 150907.0,
                    "pulse_service_hit_ratio": 612972.0 / 763879.0,
                    "pulse_service_owner_ratio": 150907.0 / 763879.0,
                    "pulse_service_request_compaction": 763879.0 / 150907.0,
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
                        "experiment_id": "pulse_gcss_shared_line_actual_test",
                        "baseline_case": "baseline",
                        "cases": [
                            {"id": "baseline", "label": "baseline", "run_dir": str(baseline_run)},
                            {"id": "pulse_actual", "label": "pulse_actual", "run_dir": str(pulse_run)},
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
            self.assertEqual(rows["model.sim_time_actual_ns"], ["257453.0", "224813.0", "-32640.0"])
            self.assertEqual(rows["memory.memory_requests"], ["763879.0", "150907.0", "-612972.0"])
            self.assertEqual(rows["memhierarchy.memctrl.req_total"], ["150907.0", "150907.0", "0.0"])
            self.assertEqual(rows["pulse_shared_service_hits_total"], ["0", "612972", "612972"])
            self.assertEqual(rows["pulse_shared_service_misses_total"], ["0", "150907", "150907"])
            self.assertEqual(rows["pulse_actual_gate_taken_total"], ["0", "763879", "763879"])
            self.assertEqual(rows["pulse_ready_fanout_total"], ["0", "763879", "763879"])
            self.assertEqual(rows["pulse_service_request_compaction"], ["0", str(763879.0 / 150907.0), str(763879.0 / 150907.0)])

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
