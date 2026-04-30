#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m33_mxu_io_busy_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m33_mxu_io_busy_trends.py"


class ValidateTensorM33MxuIoBusyTrendsTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_compute_cycles_total": 64,
                    "tensor_mxu_io_busy_cycles_total": 1,
                },
            }
            thr = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_compute_cycles_total": 256,
                    "tensor_mxu_io_busy_cycles_total": 256,
                },
            }
            base_p = root / "base.json"
            thr_p = root / "thr.json"
            base_p.write_text(json.dumps(base), encoding="utf-8")
            thr_p.write_text(json.dumps(thr), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--base", str(base_p), "--throttled", str(thr_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m33:x]", out.stdout)

    def test_fails_when_io_not_higher(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_compute_cycles_total": 64,
                    "tensor_mxu_io_busy_cycles_total": 10,
                },
            }
            thr = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_compute_cycles_total": 256,
                    "tensor_mxu_io_busy_cycles_total": 10,
                },
            }
            base_p = root / "base.json"
            thr_p = root / "thr.json"
            base_p.write_text(json.dumps(base), encoding="utf-8")
            thr_p.write_text(json.dumps(thr), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--base", str(base_p), "--throttled", str(thr_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected mxu_io_busy_cycles(throttled) > base", out.stderr)


if __name__ == "__main__":
    unittest.main()

