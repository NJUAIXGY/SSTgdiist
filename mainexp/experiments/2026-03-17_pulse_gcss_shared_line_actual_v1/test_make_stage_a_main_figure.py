import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_stage_a_main_figure.py"


class MakeStageAMainFigureTest(unittest.TestCase):
    def test_generates_compact_stage_a_tsv_from_compare_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compare_path = root / "snapshot" / "compare.tsv"
            compare_path.parent.mkdir(parents=True, exist_ok=True)
            compare_path.write_text(
                "\n".join(
                    [
                        "# experiment_id\t2026-03-17_pulse_gcss_shared_line_actual_v1",
                        "# baseline_case\tbaseline_step1_seed_only_frac003",
                        "# profile\tpulse_gcss_shared_line_actual_stage_a",
                        "metric\tbaseline\tpulse\tdelta",
                        "model.sim_time_actual_ns\t257453\t224813\t-32640",
                        "memory.memory_requests\t763879.0\t150907.0\t-612972.0",
                        "memhierarchy.memctrl.req_total\t150907.0\t150907.0\t0.0",
                        "pulse_actual_gate_taken_total\t0\t763879\t763879",
                        "pulse_shared_service_misses_total\t0\t150907\t150907",
                        "pulse_shared_service_hits_total\t0\t612972\t612972",
                        "pulse_service_hit_ratio\t0\t0.8024464607614556\t0.8024464607614556",
                        "pulse_service_owner_ratio\t0\t0.19755353923854432\t0.19755353923854432",
                        "pulse_service_request_compaction\t0\t5.061918930202045\t5.061918930202045",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "stage_a_main.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--compare", str(compare_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(out_path.exists())

            rows = self._read_tsv(out_path)
            self.assertEqual(
                rows["model.sim_time_actual_ns"],
                ["257453", "224813", "-32640", "-12.678042205761827", "sim_time"],
            )
            self.assertEqual(
                rows["memory.memory_requests"],
                ["763879.0", "150907.0", "-612972.0", "-80.24464607614557", "runtime_requests"],
            )
            self.assertEqual(
                rows["memhierarchy.memctrl.req_total"],
                ["150907.0", "150907.0", "0.0", "0.0", "dram_requests"],
            )
            self.assertEqual(
                rows["pulse_service_request_compaction"],
                ["0", "5.061918930202045", "5.061918930202045", "NA", "compaction"],
            )

    def _read_tsv(self, path: Path):
        rows = {}
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                metric, baseline, candidate, delta_abs, delta_pct, note = line.split("\t")
                rows[metric] = [baseline, candidate, delta_abs, delta_pct, note]
        return rows


if __name__ == "__main__":
    unittest.main()
