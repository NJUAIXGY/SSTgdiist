#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m18_prefetch_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m18_prefetch_trends.py"


class ValidateTensorM18PrefetchTrendsTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            off = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 256,
                    "tensor_program_any_busy_cycles_total": 400,
                    "tensor_program_ub_occupancy_bytes_max": 1000,
                },
            }
            on = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 256,
                    "tensor_program_any_busy_cycles_total": 350,
                    "tensor_program_ub_occupancy_bytes_max": 2000,
                },
            }
            off_p = root / "off.json"
            on_p = root / "on.json"
            off_p.write_text(json.dumps(off), encoding="utf-8")
            on_p.write_text(json.dumps(on), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--off", str(off_p), "--on", str(on_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m18:x]", out.stdout)

    def test_fails_when_on_not_faster(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            off = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 256,
                    "tensor_program_any_busy_cycles_total": 300,
                },
            }
            on = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 256,
                    "tensor_program_any_busy_cycles_total": 300,
                },
            }
            off_p = root / "off.json"
            on_p = root / "on.json"
            off_p.write_text(json.dumps(off), encoding="utf-8")
            on_p.write_text(json.dumps(on), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--off", str(off_p), "--on", str(on_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("busy(on) < off", out.stderr)


if __name__ == "__main__":
    unittest.main()

