import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_stage_b_main_figure.py"


class MakeStageBMainFigureTest(unittest.TestCase):
    def test_generates_compact_stage_b_tsv_from_compare_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compare_path = root / "snapshot" / "compare.tsv"
            compare_path.parent.mkdir(parents=True, exist_ok=True)
            compare_path.write_text(
                "\n".join(
                    [
                        "# experiment_id\tpulse_domain_retire_shadow_ab_test",
                        "# baseline_case\tpulse_gcss_shared_line_actual_baseline",
                        "# profile\tpulse_domain_retire_shadow_stage_b",
                        "metric\tbaseline\tcandidate\tdelta",
                        "model.sim_time_actual_ns\t224813.0\t224813.0\t0.0",
                        "memory.memory_requests\t150907.0\t150907.0\t0.0",
                        "memhierarchy.memctrl.req_total\t150907.0\t150907.0\t0.0",
                        "pulse_domain_hol_recoverable_cycles_total\t0\t1234\t1234",
                        "pulse_domain_hol_recoverable_edges_total\t0\t9876\t9876",
                        "pulse_domain_ready_domains_peak\t0\t5\t5",
                        "pulse_domain_committable_edges_peak\t0\t31\t31",
                        "pulse_domain_hol_release_ratio\t0\t0.625\t0.625",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "stage_b_main.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--compare", str(compare_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            rows = self._read_tsv(out_path)
            self.assertEqual(rows["model.sim_time_actual_ns"], ["224813.0", "224813.0", "0.0", "0.0", "sim_time"])
            self.assertEqual(rows["pulse_domain_hol_recoverable_edges_total"], ["0", "9876", "9876", "NA", "recoverable_edges"])
            self.assertEqual(rows["pulse_domain_hol_release_ratio"], ["0", "0.625", "0.625", "NA", "hol_release_ratio"])

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
