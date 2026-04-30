#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m35_mapping_latency_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m35_mapping_latency_trends.py"


class ValidateTensorM35MappingLatencyTrendsTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            hot = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_mem_read_latency_cycles_total": 400,
                    "tensor_mem_read_latency_cycles_max": 40,
                    "tensor_mem_read_latency_samples_total": 10,
                    "tensor_program_dma_busy_cycles_total": 200,
                },
            }
            spread = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_mem_read_latency_cycles_total": 100,
                    "tensor_mem_read_latency_cycles_max": 20,
                    "tensor_mem_read_latency_samples_total": 10,
                    "tensor_program_dma_busy_cycles_total": 100,
                },
            }
            hot_p = root / "hot.json"
            spr_p = root / "spread.json"
            hot_p.write_text(json.dumps(hot), encoding="utf-8")
            spr_p.write_text(json.dumps(spread), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--hot", str(hot_p), "--spread", str(spr_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m35:x]", out.stdout)

    def test_fails_when_avg_not_higher(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            hot = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_mem_read_latency_cycles_total": 100,
                    "tensor_mem_read_latency_cycles_max": 10,
                    "tensor_mem_read_latency_samples_total": 10,
                    "tensor_program_dma_busy_cycles_total": 200,
                },
            }
            spread = {
                "schema_version": 1,
                "tensor": {
                    "tensor_program_iters_total": 1,
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_mem_read_latency_cycles_total": 100,
                    "tensor_mem_read_latency_cycles_max": 10,
                    "tensor_mem_read_latency_samples_total": 10,
                    "tensor_program_dma_busy_cycles_total": 100,
                },
            }
            hot_p = root / "hot.json"
            spr_p = root / "spread.json"
            hot_p.write_text(json.dumps(hot), encoding="utf-8")
            spr_p.write_text(json.dumps(spread), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--hot", str(hot_p), "--spread", str(spr_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected avg mem read latency(hot) > spread", out.stderr)


if __name__ == "__main__":
    unittest.main()

