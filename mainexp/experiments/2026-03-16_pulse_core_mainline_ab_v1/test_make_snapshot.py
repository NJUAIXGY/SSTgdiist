import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"


class MakeSnapshotTest(unittest.TestCase):
    def test_generates_compare_tsv_with_pulse_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            pulse_run = root / "pulse_run"
            baseline_run.mkdir()
            pulse_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10.0,
                memory_requests=20.0,
                memory_bytes=30.0,
                memctrl_req_total=40.0,
                apply_ns_avg=50.0,
                gather_ns_avg=60.0,
                scatter_ns_avg=70.0,
                memctrl_payload_utilization=0.5,
                neurons_fired_total=80.0,
                total_spikes_processed=90.0,
            )
            self._write_summary(
                pulse_run,
                sim_time_actual_ns=11.0,
                memory_requests=21.0,
                memory_bytes=31.0,
                memctrl_req_total=41.0,
                apply_ns_avg=51.0,
                gather_ns_avg=61.0,
                scatter_ns_avg=71.0,
                memctrl_payload_utilization=0.6,
                neurons_fired_total=81.0,
                total_spikes_processed=91.0,
            )

            (baseline_run / "validation.log").write_text(
                "[val] SUMMARY run_dir=/tmp/base fail=0 warn=0 strict=0\n",
                encoding="utf-8",
            )
            (pulse_run / "validation.log").write_text(
                "[val] SUMMARY run_dir=/tmp/pulse fail=1 warn=2 strict=0\n",
                encoding="utf-8",
            )

            self._write_stats(
                baseline_run / "mesh_stats.csv",
                [],
            )
            self._write_stats(
                pulse_run / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "pulse_ingress_packets_total",
                        "StatisticType": "Accumulator",
                        "Sum.u64": "100",
                        "Count.u64": "2",
                        "Max.u64": "60",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "pulse_ingress_packets_total",
                        "StatisticType": "Accumulator",
                        "Sum.u64": "80",
                        "Count.u64": "2",
                        "Max.u64": "50",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "pulse_correctness_ready_blocked_cycles_total",
                        "StatisticType": "Accumulator",
                        "Sum.u64": "12",
                        "Count.u64": "3",
                        "Max.u64": "8",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "pulse_correctness_ready_blocked_cycles_total",
                        "StatisticType": "Accumulator",
                        "Sum.u64": "7",
                        "Count.u64": "2",
                        "Max.u64": "4",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "pulse_correctness_scoreboard_occupancy_peak",
                        "StatisticType": "Accumulator",
                        "Sum.u64": "30",
                        "Count.u64": "3",
                        "Max.u64": "20",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "pulse_correctness_scoreboard_occupancy_peak",
                        "StatisticType": "Accumulator",
                        "Sum.u64": "40",
                        "Count.u64": "4",
                        "Max.u64": "25",
                    },
                ],
            )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "pulse_test",
                        "baseline_case": "baseline",
                        "cases": [
                            {"id": "baseline", "label": "baseline", "run_dir": str(baseline_run)},
                            {"id": "pulse", "label": "pulse", "run_dir": str(pulse_run)},
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
            self.assertEqual(rows["validation.fail"], ["0", "1", "1"])
            self.assertEqual(rows["validation.warn"], ["0", "2", "2"])
            self.assertEqual(rows["memory.memory_requests"], ["20.0", "21.0", "1.0"])
            self.assertEqual(rows["pulse_ingress_packets_total"], ["0", "110", "110"])
            self.assertEqual(rows["pulse_correctness_ready_blocked_cycles_total"], ["0", "19", "19"])
            self.assertEqual(rows["pulse_correctness_scoreboard_occupancy_peak"], ["0", "45", "45"])

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
        }
        (run_dir / "essential_summary_mesh.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def _write_stats(self, path, rows):
        fields = [
            "ComponentName",
            "StatisticName",
            "StatisticSubId",
            "StatisticType",
            "SimTime",
            "Rank",
            "Sum.u64",
            "SumSQ.u64",
            "Count.u64",
            "Min.u64",
            "Max.u64",
            "Sum.f64",
            "SumSQ.f64",
            "Min.f64",
            "Max.f64",
        ]
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                payload = {field: "" for field in fields}
                payload.update(
                    {
                        "StatisticSubId": "",
                        "SimTime": "0",
                        "Rank": "0",
                        "SumSQ.u64": "0",
                        "Min.u64": "0",
                        "Sum.f64": "0",
                        "SumSQ.f64": "0",
                        "Min.f64": "0",
                        "Max.f64": "0",
                    }
                )
                payload.update(row)
                writer.writerow(payload)

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
