import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"


class MakeSnapshotTest(unittest.TestCase):
    def test_generates_compare_tsv_with_prebase_lookup_metrics(self):
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
                memctrl_req_total=150907.0,
                weight_idx_lookup_total=763879.0,
                weight_idx_predicted_extra_cycles_total=4200.0,
                weight_bank_conflict_ticks_total=800.0,
                pulse={},
            )
            self._write_summary(
                pulse_run,
                sim_time_actual_ns=223700.0,
                memory_requests=150907.0,
                memctrl_req_total=150907.0,
                weight_idx_lookup_total=521000.0,
                weight_idx_predicted_extra_cycles_total=2500.0,
                weight_bank_conflict_ticks_total=510.0,
                pulse={
                    "pulse_prebase_lookup_owner_fill_total": 120,
                    "pulse_prebase_lookup_shared_hits_total": 240,
                    "pulse_prebase_lookup_entries_peak": 32,
                    "pulse_prebase_lookup_hit_ratio": 240.0 / 360.0,
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
                        "experiment_id": "pulse_prebase_shared_lookup_sram_test",
                        "baseline_case": "baseline",
                        "cases": [
                            {"id": "baseline", "label": "baseline", "run_dir": str(baseline_run)},
                            {"id": "prebase_lookup", "label": "prebase_lookup", "run_dir": str(pulse_run)},
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
            self.assertEqual(rows["model.sim_time_actual_ns"], ["224813.0", "223700.0", "-1113.0"])
            self.assertEqual(rows["memory.memory_requests"], ["150907.0", "150907.0", "0.0"])
            self.assertEqual(rows["memhierarchy.memctrl.req_total"], ["150907.0", "150907.0", "0.0"])
            self.assertEqual(rows["sram.weight_idx.lookup_total"], ["763879.0", "521000.0", "-242879.0"])
            self.assertEqual(rows["sram.weight_idx.predicted_extra_cycles_total"], ["4200.0", "2500.0", "-1700.0"])
            self.assertEqual(rows["sram.weight.bank_conflict_ticks_total"], ["800.0", "510.0", "-290.0"])
            self.assertEqual(rows["pulse_prebase_lookup_owner_fill_total"], ["0", "120", "120"])
            self.assertEqual(rows["pulse_prebase_lookup_shared_hits_total"], ["0", "240", "240"])
            self.assertEqual(rows["pulse_prebase_lookup_entries_peak"], ["0", "32", "32"])
            self.assertEqual(
                rows["pulse_prebase_lookup_hit_ratio"],
                ["0", str(240.0 / 360.0), str(240.0 / 360.0)],
            )

    def _write_summary(
        self,
        run_dir,
        *,
        sim_time_actual_ns,
        memory_requests,
        memctrl_req_total,
        weight_idx_lookup_total,
        weight_idx_predicted_extra_cycles_total,
        weight_bank_conflict_ticks_total,
        pulse,
    ):
        payload = {
            "model": {"sim_time_actual_ns": sim_time_actual_ns},
            "memory": {"memory_requests": memory_requests},
            "memhierarchy": {"memctrl": {"req_total": memctrl_req_total}},
            "sram": {
                "weight_idx": {
                    "lookup_total": weight_idx_lookup_total,
                    "predicted_extra_cycles_total": weight_idx_predicted_extra_cycles_total,
                },
                "weight": {
                    "bank_conflict_ticks_total": weight_bank_conflict_ticks_total,
                },
            },
            "pulse": pulse,
        }
        (run_dir / "essential_summary_mesh.json").write_text(json.dumps(payload), encoding="utf-8")

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
