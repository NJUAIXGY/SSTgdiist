import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"


class MakeSnapshotTest(unittest.TestCase):
    def test_generates_compare_tsv_with_stage_b_shadow_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            shadow_run = root / "shadow_run"
            baseline_run.mkdir()
            shadow_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=224813.0,
                memory_requests=150907.0,
                memctrl_req_total=150907.0,
                pulse={
                    "pulse_shared_service_hits_total": 612972,
                    "pulse_shared_service_misses_total": 150907,
                    "pulse_actual_gate_taken_total": 763879,
                },
            )
            self._write_summary(
                shadow_run,
                sim_time_actual_ns=224813.0,
                memory_requests=150907.0,
                memctrl_req_total=150907.0,
                pulse={
                    "pulse_shared_service_hits_total": 612972,
                    "pulse_shared_service_misses_total": 150907,
                    "pulse_actual_gate_taken_total": 763879,
                    "pulse_domain_hol_recoverable_cycles_total": 1234,
                    "pulse_domain_hol_recoverable_edges_total": 9876,
                    "pulse_domain_ready_domains_peak": 5,
                    "pulse_domain_committable_edges_peak": 31,
                    "pulse_domain_hol_release_ratio": 0.625,
                },
            )

            (baseline_run / "validation.log").write_text(
                "[val] SUMMARY run_dir=/tmp/base fail=0 warn=0 strict=0\n",
                encoding="utf-8",
            )
            (shadow_run / "validation.log").write_text(
                "[val] SUMMARY run_dir=/tmp/shadow fail=0 warn=0 strict=0\n",
                encoding="utf-8",
            )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "pulse_domain_retire_shadow_ab_test",
                        "baseline_case": "pulse_gcss_shared_line_actual_baseline",
                        "cases": [
                            {"id": "pulse_gcss_shared_line_actual_baseline", "run_dir": str(baseline_run)},
                            {"id": "pulse_domain_retire_shadow", "run_dir": str(shadow_run)},
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
            rows = self._read_tsv(out_path)
            self.assertEqual(rows["model.sim_time_actual_ns"], ["224813.0", "224813.0", "0.0"])
            self.assertEqual(rows["pulse_domain_hol_recoverable_cycles_total"], ["0", "1234", "1234"])
            self.assertEqual(rows["pulse_domain_hol_recoverable_edges_total"], ["0", "9876", "9876"])
            self.assertEqual(rows["pulse_domain_hol_release_ratio"], ["0", "0.625", "0.625"])

    def _write_summary(self, run_dir: Path, *, sim_time_actual_ns: float, memory_requests: float, memctrl_req_total: float, pulse: dict) -> None:
        payload = {
            "model": {"sim_time_actual_ns": sim_time_actual_ns},
            "memory": {"memory_requests": memory_requests, "memory_bytes": 0.0},
            "memhierarchy": {"memctrl": {"req_total": memctrl_req_total}},
            "gas": {
                "apply_ns_avg": 0.0,
                "gather_ns_avg": 0.0,
                "scatter_ns_avg": 0.0,
                "memctrl_payload_utilization": 0.0,
            },
            "spike_activity": {
                "neurons_fired_total": 0.0,
                "total_spikes_processed": 0.0,
            },
            "pulse": pulse,
        }
        (run_dir / "essential_summary_mesh.json").write_text(json.dumps(payload), encoding="utf-8")

    def _read_tsv(self, path: Path):
        rows = {}
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                metric, baseline, candidate, delta = line.split("\t")
                rows[metric] = [baseline, candidate, delta]
        return rows


if __name__ == "__main__":
    unittest.main()
