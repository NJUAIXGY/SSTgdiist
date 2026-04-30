#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for compile_trace_json_to_tensor_spec.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "compile_trace_json_to_tensor_spec.py"


class CompileTraceJsonToTensorSpecTest(unittest.TestCase):
    def _trace(self, op_name: str = "gemm_ub") -> dict:
        return {
            "schema_version": 1,
            "name": "demo",
            "platform": {"mesh_size": 2, "simulation_time": "20us"},
            "program": [
                {"op": "dma_read", "bytes": 4096},
                {"op": op_name, "cycles": 64, "ub_read_bytes": 4096, "ub_write_bytes": 2048},
                {"op": "dma_write", "bytes": 2048},
                {"op": "fence"},
            ],
        }

    def test_compile_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.json"
            schema = root / "schema.json"
            out = root / "spec.json"
            trace.write_text(json.dumps(self._trace()), encoding="utf-8")
            schema.write_text(json.dumps({"allowed_ops": ["dma_read", "dma_write", "gemm_ub", "fence"]}), encoding="utf-8")

            proc = subprocess.run(
                ["python3", str(SCRIPT), "--trace", str(trace), "--schema", str(schema), "--out", str(out)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 3)
            self.assertEqual(len(payload["workload"]["program"]["ops"]), 4)

    def test_fail_unknown_op(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.json"
            schema = root / "schema.json"
            out = root / "spec.json"
            trace.write_text(json.dumps(self._trace(op_name="unknown_op")), encoding="utf-8")
            schema.write_text(json.dumps({"allowed_ops": ["dma_read", "dma_write", "gemm_ub", "fence"]}), encoding="utf-8")

            proc = subprocess.run(
                ["python3", str(SCRIPT), "--trace", str(trace), "--schema", str(schema), "--out", str(out)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("invalid trace input", proc.stderr)


if __name__ == "__main__":
    unittest.main()
