#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m29_dma_micro_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m29_dma_micro_trends.py"


class ValidateTensorM29DmaMicroTrendsTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slow = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 65536,
                    "tensor_program_dma_busy_cycles_total": 2000,
                },
            }
            fast = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 65536,
                    "tensor_program_dma_busy_cycles_total": 500,
                },
            }
            slow_p = root / "slow.json"
            fast_p = root / "fast.json"
            slow_p.write_text(json.dumps(slow), encoding="utf-8")
            fast_p.write_text(json.dumps(fast), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--slow", str(slow_p), "--fast", str(fast_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m29:x]", out.stdout)

    def test_fails_when_not_slower(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slow = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 65536,
                    "tensor_program_dma_busy_cycles_total": 500,
                },
            }
            fast = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 65536,
                    "tensor_program_dma_busy_cycles_total": 500,
                },
            }
            slow_p = root / "slow.json"
            fast_p = root / "fast.json"
            slow_p.write_text(json.dumps(slow), encoding="utf-8")
            fast_p.write_text(json.dumps(fast), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--slow", str(slow_p), "--fast", str(fast_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected dma_busy(slow) > fast", out.stderr)


if __name__ == "__main__":
    unittest.main()

