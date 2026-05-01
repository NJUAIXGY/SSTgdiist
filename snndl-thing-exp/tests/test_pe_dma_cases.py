import importlib.util
import json
import subprocess
import unittest
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
EXP_ROOT = THIS_FILE.parents[1]
RUN_CASE = EXP_ROOT / "tools" / "run_case.py"
CASE_IDS = (
    "pe_dma_ab_smoke",
    "pe_dma_budget_throttle",
    "pe_dma_stage_gate_prefetch",
)


class PeDmaCasesTests(unittest.TestCase):
    def _load_module(self):
        spec = importlib.util.spec_from_file_location("snndl_thing_exp_run_case", RUN_CASE)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_dma_cases_exist_and_can_be_discovered(self) -> None:
        repo_root = THIS_FILE.parents[2]
        exp_root = repo_root / "snndl-thing-exp"
        module = self._load_module()

        for case_id in CASE_IDS:
            case_dir = exp_root / "cases" / case_id
            case_json = case_dir / "case.json"
            spec_json = case_dir / "spec.json"

            self.assertTrue(case_json.is_file(), msg=str(case_json))
            self.assertTrue(spec_json.is_file(), msg=str(spec_json))

            case_obj = json.loads(case_json.read_text(encoding="utf-8"))
            spec_obj = json.loads(spec_json.read_text(encoding="utf-8"))

            self.assertEqual(case_obj.get("case_id"), case_id)
            self.assertEqual(case_obj.get("spec"), "spec.json")
            self.assertIsInstance(spec_obj, dict)
            self.assertEqual(spec_obj.get("schema_version"), 3)

            ctx = module.resolve_case_context(repo_root=repo_root, exp_root=exp_root, case_id=case_id)
            self.assertEqual(ctx.case_id, case_id)
            self.assertEqual(ctx.case_dir, case_dir)
            self.assertEqual(ctx.case_json, case_json)
            self.assertEqual(ctx.spec_path, spec_json)

    def test_dma_cases_support_validate_only(self) -> None:
        repo_root = THIS_FILE.parents[2]
        for case_id in CASE_IDS:
            proc = subprocess.run(
                ["python3", str(RUN_CASE), case_id, "--validate-only"],
                cwd=str(repo_root),
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
