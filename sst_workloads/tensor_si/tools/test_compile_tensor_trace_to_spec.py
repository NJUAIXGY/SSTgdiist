#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for compile_tensor_trace_to_spec.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "compile_tensor_trace_to_spec.py"


class CompileTensorTraceToSpecTest(unittest.TestCase):
    def test_compile_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.json"
            out_spec = root / "spec.json"
            trace.write_text(
                json.dumps(
                    {
                        "platform": {"mesh_size": 2, "simulation_time": "20us"},
                        "tensor_params": {"tensor_program_issue_width": 4},
                        "program_ops": [
                            {"op_type": "dma_read", "bytes": 8192},
                            {"op_type": "gemm_ub", "cycles": 128, "ub_read_bytes": 4096, "ub_write_bytes": 2048},
                            {"op_type": "fence"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                ["python3", str(SCRIPT), "--trace", str(trace), "--out", str(out_spec)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(out_spec.exists())

            payload = json.loads(out_spec.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("schema_version"), 3)
            self.assertEqual(payload.get("model"), "tensor")

    def test_compile_fail_empty_ops(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.json"
            out_spec = root / "spec.json"
            trace.write_text(json.dumps({"program_ops": []}), encoding="utf-8")

            proc = subprocess.run(
                ["python3", str(SCRIPT), "--trace", str(trace), "--out", str(out_spec)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("program_ops", proc.stderr)


if __name__ == "__main__":
    unittest.main()
