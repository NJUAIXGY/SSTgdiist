#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m100_phase6_report.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m100_phase6_report.py"


class ValidateTensorM100Phase6ReportTest(unittest.TestCase):
    def _report(self) -> dict:
        gates = [{"gate": f"m{n}", "status": "pass", "report_dir": f"/tmp/m{n}", "log": f"/tmp/m{n}.log"} for n in range(91, 100)]
        return {
            "schema_version": 1,
            "phase": "phase6",
            "status": "pass",
            "gate_count": 9,
            "pass_count": 9,
            "fail_count": 0,
            "gate_results": gates,
            "failures": [],
        }

    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "m100.json"
            report.write_text(json.dumps(self._report()), encoding="utf-8")
            proc = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--report",
                    str(report),
                    "--min-gates",
                    "9",
                    "--required-gate",
                    "m91",
                    "--required-gate",
                    "m99",
                    "--expect-pass",
                    "1",
                    "--label",
                    "x",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn("[m100:x]", proc.stdout)

    def test_fail_missing_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._report()
            payload["gate_results"] = payload["gate_results"][:-1]
            payload["gate_count"] = 8
            payload["pass_count"] = 8
            report = root / "m100.json"
            report.write_text(json.dumps(payload), encoding="utf-8")
            proc = subprocess.run(
                ["python3", str(SCRIPT), "--report", str(report), "--min-gates", "8", "--required-gate", "m99", "--expect-pass", "0"],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("missing required gate", proc.stderr)


if __name__ == "__main__":
    unittest.main()
