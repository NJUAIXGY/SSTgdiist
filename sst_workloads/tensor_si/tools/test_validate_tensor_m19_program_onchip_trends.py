#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m19_program_onchip_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m19_program_onchip_trends.py"


class ValidateTensorM19ProgramOnchipTrendsTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 32,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_stall_onchip_port_cycles_total": 0,
                    "tensor_stall_onchip_bank_conflict_cycles_total": 0,
                },
            }
            conf = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 32,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_stall_onchip_port_cycles_total": 0,
                    "tensor_stall_onchip_bank_conflict_cycles_total": 10,
                },
            }
            base_p = root / "base.json"
            conf_p = root / "conf.json"
            base_p.write_text(json.dumps(base), encoding="utf-8")
            conf_p.write_text(json.dumps(conf), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--base", str(base_p), "--conflict", str(conf_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m19:x]", out.stdout)

    def test_fails_when_no_increase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 32,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_stall_onchip_port_cycles_total": 5,
                    "tensor_stall_onchip_bank_conflict_cycles_total": 1,
                },
            }
            conf = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_compute_cycles_total": 32,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_stall_onchip_port_cycles_total": 5,
                    "tensor_stall_onchip_bank_conflict_cycles_total": 1,
                },
            }
            base_p = root / "base.json"
            conf_p = root / "conf.json"
            base_p.write_text(json.dumps(base), encoding="utf-8")
            conf_p.write_text(json.dumps(conf), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--base", str(base_p), "--conflict", str(conf_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected on-chip stall counters increase", out.stderr)


if __name__ == "__main__":
    unittest.main()

