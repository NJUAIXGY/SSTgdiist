#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
EXP_ROOT = THIS_FILE.parents[1]
RUN_CASE = EXP_ROOT / "tools" / "run_case.py"


class RunCaseTests(unittest.TestCase):
    def _load_module(self):
        spec = importlib.util.spec_from_file_location("snndl_thing_exp_run_case", RUN_CASE)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_resolve_case_context_uses_experiment_scoped_paths(self) -> None:
        module = self._load_module()
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td)
            exp_root = repo_root / "snndl-thing-exp"
            case_dir = exp_root / "cases" / "sram_timing_smoke"
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "case.json").write_text(
                '{"case_id":"sram_timing_smoke","spec":"spec.json","env":{"MESH_SST_NPROC":"1"}}',
                encoding="utf-8",
            )
            (case_dir / "spec.json").write_text('{"schema_version":3}', encoding="utf-8")

            ctx = module.resolve_case_context(repo_root=repo_root, exp_root=exp_root, case_id="sram_timing_smoke")

            self.assertEqual(ctx.case_id, "sram_timing_smoke")
            self.assertEqual(ctx.spec_path, case_dir / "spec.json")
            self.assertEqual(ctx.run_root, exp_root / "runs" / "sram_timing_smoke")
            self.assertEqual(ctx.env["MESH_RUN_ROOT"], str(exp_root / "runs" / "sram_timing_smoke"))
            self.assertEqual(ctx.env["MESH_VALIDATE_PROFILE"], "dev")
            self.assertTrue(str(ctx.run_root).startswith(str(exp_root)))

    def test_build_command_uses_spec_first_runner(self) -> None:
        module = self._load_module()
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td)
            exp_root = repo_root / "snndl-thing-exp"
            case_dir = exp_root / "cases" / "sram_timing_smoke"
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "case.json").write_text('{"case_id":"sram_timing_smoke","spec":"spec.json"}', encoding="utf-8")
            (case_dir / "spec.json").write_text('{"schema_version":3}', encoding="utf-8")
            runner = repo_root / "sst_dram_si" / "tools"
            runner.mkdir(parents=True, exist_ok=True)
            (runner / "run_mesh_with_time.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            ctx = module.resolve_case_context(repo_root=repo_root, exp_root=exp_root, case_id="sram_timing_smoke")
            cmd = module.build_command(ctx)

            self.assertEqual(cmd[-2:], ["--spec", str(case_dir / "spec.json")])
            self.assertIn("run_mesh_with_time.sh", cmd[0])


if __name__ == "__main__":
    unittest.main()
