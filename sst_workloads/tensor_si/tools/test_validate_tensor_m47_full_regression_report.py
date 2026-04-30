#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m47_full_regression_report.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m47_full_regression_report.py"


class ValidateTensorM47FullRegressionReportTest(unittest.TestCase):
    def _report(self) -> dict:
        gates = [
            {"gate": f"m{n}", "status": "pass", "report_dir": f"/tmp/m{n}", "log": f"/tmp/m{n}.log"}
            for n in range(37, 47)
        ]
        return {
            "schema_version": 1,
            "status": "pass",
            "gate_count": 10,
            "pass_count": 10,
            "fail_count": 0,
            "gate_results": gates,
            "failures": [],
        }

    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "m47.json"
            report.write_text(json.dumps(self._report()), encoding="utf-8")
            proc = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--report",
                    str(report),
                    "--min-gates",
                    "10",
                    "--required-gate",
                    "m37",
                    "--required-gate",
                    "m46",
                    "--expect-pass",
                    "1",
                    "--label",
                    "x",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn("[m47:x]", proc.stdout)

    def test_fail_missing_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._report()
            payload["gate_results"] = payload["gate_results"][:-1]
            payload["gate_count"] = 9
            payload["pass_count"] = 9
            report = root / "m47.json"
            report.write_text(json.dumps(payload), encoding="utf-8")
            proc = subprocess.run(
                ["python3", str(SCRIPT), "--report", str(report), "--min-gates", "9", "--required-gate", "m46", "--expect-pass", "0"],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("missing required gate", proc.stderr)


if __name__ == "__main__":
    unittest.main()
