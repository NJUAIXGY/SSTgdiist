#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m22_addr_aware_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m22_addr_aware_trends.py"


class ValidateTensorM22AddrAwareTrendsTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bytes_only = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 64,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_program_ub_stall_cycles_total": 10,
                },
            }
            addr = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 64,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_program_ub_stall_cycles_total": 50,
                },
            }
            bytes_p = root / "bytes.json"
            addr_p = root / "addr.json"
            bytes_p.write_text(json.dumps(bytes_only), encoding="utf-8")
            addr_p.write_text(json.dumps(addr), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--bytes", str(bytes_p), "--addr", str(addr_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m22:x]", out.stdout)

    def test_fails_when_no_increase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bytes_only = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 64,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_program_ub_stall_cycles_total": 50,
                },
            }
            addr = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 64,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_program_ub_stall_cycles_total": 50,
                },
            }
            bytes_p = root / "bytes.json"
            addr_p = root / "addr.json"
            bytes_p.write_text(json.dumps(bytes_only), encoding="utf-8")
            addr_p.write_text(json.dumps(addr), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--bytes", str(bytes_p), "--addr", str(addr_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("ub_stall(addr) > bytes", out.stderr)


if __name__ == "__main__":
    unittest.main()

