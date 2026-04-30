#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m21_gemmub_cycles0_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m21_gemmub_cycles0_trends.py"


class ValidateTensorM21GemmUbCycles0TrendsTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fast = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_program_mxu_busy_cycles_total": 100,
                    "tensor_compute_cycles_total": 100,
                },
            }
            slow = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_program_mxu_busy_cycles_total": 200,
                    "tensor_compute_cycles_total": 200,
                },
            }
            fast_p = root / "fast.json"
            slow_p = root / "slow.json"
            fast_p.write_text(json.dumps(fast), encoding="utf-8")
            slow_p.write_text(json.dumps(slow), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--fast", str(fast_p), "--slow", str(slow_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m21:x]", out.stdout)

    def test_fails_when_slow_not_slower(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fast = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_program_mxu_busy_cycles_total": 200,
                    "tensor_compute_cycles_total": 200,
                },
            }
            slow = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_program_mxu_busy_cycles_total": 200,
                    "tensor_compute_cycles_total": 200,
                },
            }
            fast_p = root / "fast.json"
            slow_p = root / "slow.json"
            fast_p.write_text(json.dumps(fast), encoding="utf-8")
            slow_p.write_text(json.dumps(slow), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--fast", str(fast_p), "--slow", str(slow_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("mxu_busy(slow) > fast", out.stderr)


if __name__ == "__main__":
    unittest.main()

