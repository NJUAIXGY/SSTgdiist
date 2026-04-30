#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for aggregate_tensor_phase4_regression.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "aggregate_tensor_phase4_regression.py"


class AggregateTensorPhase4RegressionTest(unittest.TestCase):
    def test_pass_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            results = root / "results.tsv"
            out = root / "report.json"
            results.write_text("m71\tpass\t/tmp/m71\t/tmp/m71.log\nm72\tpass\t/tmp/m72\t/tmp/m72.log\n", encoding="utf-8")

            proc = subprocess.run(["python3", str(SCRIPT), "--results-file", str(results), "--out", str(out), "--label", "x"], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["phase"], "phase4")
            self.assertEqual(payload["gate_count"], 2)
            self.assertIn("[m80:x]", proc.stdout)

    def test_fail_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            results = root / "results.tsv"
            out = root / "report.json"
            results.write_text("m71\tpass\t/tmp/m71\t/tmp/m71.log\nm72\tfail\t\t/tmp/m72.log\n", encoding="utf-8")

            proc = subprocess.run(["python3", str(SCRIPT), "--results-file", str(results), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["fail_count"], 1)


if __name__ == "__main__":
    unittest.main()
