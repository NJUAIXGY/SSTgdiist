import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class SramPhase1CasesTests(unittest.TestCase):
    def test_phase1_cases_exist_with_minimal_contract(self):
        repo_root = Path(__file__).resolve().parents[2]
        exp_root = repo_root / "snndl-thing-exp"
        for case_id in ("state_sram_debug", "weight_idx_sram_debug", "weight_l0_fill_smoke", "sram_mixed_smoke"):
            case_dir = exp_root / "cases" / case_id
            self.assertTrue((case_dir / "case.json").exists(), msg=str(case_dir / "case.json"))
            self.assertTrue((case_dir / "spec.json").exists(), msg=str(case_dir / "spec.json"))
            case_obj = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
            self.assertEqual(case_obj.get("case_id"), case_id)

    def test_phase1_cases_support_validate_only(self):
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "snndl-thing-exp" / "tools" / "run_case.py"
        for case_id in ("state_sram_debug", "weight_idx_sram_debug", "weight_l0_fill_smoke", "sram_mixed_smoke"):
            proc = subprocess.run(
                ["python3", str(script), case_id, "--validate-only"],
                cwd=str(repo_root),
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
