#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m70_phase3_report.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m70_phase3_report.py"


class ValidateTensorM70Phase3ReportTest(unittest.TestCase):
    def _report(self) -> dict:
        gates = [{"gate": f"m{n}", "status": "pass", "report_dir": f"/tmp/m{n}", "log": f"/tmp/m{n}.log"} for n in range(61, 70)]
        return {
            "schema_version": 1,
            "status": "pass",
            "gate_count": 9,
            "pass_count": 9,
            "fail_count": 0,
            "gate_results": gates,
            "failures": [],
        }

    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m70.json"
            p.write_text(json.dumps(self._report()), encoding="utf-8")
            proc = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--report",
                    str(p),
                    "--min-gates",
                    "9",
                    "--required-gate",
                    "m61",
                    "--required-gate",
                    "m69",
                    "--expect-pass",
                    "1",
                    "--label",
                    "x",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn("[m70:x]", proc.stdout)

    def test_fail_missing_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = self._report()
            payload["gate_results"] = payload["gate_results"][:-1]
            payload["gate_count"] = 8
            payload["pass_count"] = 8
            p = Path(td) / "m70.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            proc = subprocess.run(["python3", str(SCRIPT), "--report", str(p), "--min-gates", "8", "--required-gate", "m69", "--expect-pass", "0"], text=True, capture_output=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("missing required gate", proc.stderr)


if __name__ == "__main__":
    unittest.main()
