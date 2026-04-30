#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m31_mem_latency_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m31_mem_latency_trends.py"


class ValidateTensorM31MemLatencyTrendsTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            simple = {
                "schema_version": 1,
                "tensor": {
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_mem_read_latency_cycles_total": 100,
                    "tensor_mem_read_latency_cycles_max": 10,
                    "tensor_mem_read_latency_samples_total": 10,
                },
            }
            ram2 = {
                "schema_version": 1,
                "tensor": {
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_mem_read_latency_cycles_total": 400,
                    "tensor_mem_read_latency_cycles_max": 40,
                    "tensor_mem_read_latency_samples_total": 10,
                },
            }
            simple_p = root / "simple.json"
            ram2_p = root / "ram2.json"
            simple_p.write_text(json.dumps(simple), encoding="utf-8")
            ram2_p.write_text(json.dumps(ram2), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--simple", str(simple_p), "--ram2", str(ram2_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m31:x]", out.stdout)

    def test_fails_when_not_slower(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            simple = {
                "schema_version": 1,
                "tensor": {
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_mem_read_latency_cycles_total": 200,
                    "tensor_mem_read_latency_cycles_max": 20,
                    "tensor_mem_read_latency_samples_total": 10,
                },
            }
            ram2 = {
                "schema_version": 1,
                "tensor": {
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_mem_read_latency_cycles_total": 200,
                    "tensor_mem_read_latency_cycles_max": 20,
                    "tensor_mem_read_latency_samples_total": 10,
                },
            }
            simple_p = root / "simple.json"
            ram2_p = root / "ram2.json"
            simple_p.write_text(json.dumps(simple), encoding="utf-8")
            ram2_p.write_text(json.dumps(ram2), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--simple", str(simple_p), "--ram2", str(ram2_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected avg mem read latency", out.stderr)


if __name__ == "__main__":
    unittest.main()

