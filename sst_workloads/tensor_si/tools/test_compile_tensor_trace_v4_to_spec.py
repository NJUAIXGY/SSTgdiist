#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for compile_tensor_trace_v4_to_spec.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "compile_tensor_trace_v4_to_spec.py"


class CompileTensorTraceV4ToSpecTest(unittest.TestCase):
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
                        "metadata": {"tile_windows": 4, "barrier_count": 2, "resource_windows": 3},
                        "program_ops": [
                            {"op_type": "dma_read", "bytes": 4096, "resource": "dma"},
                            {
                                "op_type": "gemm_ub",
                                "cycles": 64,
                                "ub_read_bytes": 2048,
                                "ub_write_bytes": 1024,
                                "resource": "mxu",
                                "deps": [0],
                            },
                            {"op_type": "fence", "resource": "ctrl", "deps": [1]},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(["python3", str(SCRIPT), "--trace", str(trace), "--out", str(out_spec)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(out_spec.read_text(encoding="utf-8"))
            params = payload["workload"]["params"]
            self.assertEqual(params.get("tensor_trace_v4_version"), 4)
            self.assertGreater(params.get("tensor_trace_v4_dependency_edges", 0), 0)
            self.assertEqual(params.get("tensor_trace_v4_barrier_count"), 2)

    def test_compile_fail_bad_dep(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.json"
            out_spec = root / "spec.json"
            trace.write_text(
                json.dumps(
                    {
                        "program_ops": [
                            {"op_type": "dma_read", "bytes": 4096},
                            {"op_type": "fence", "deps": [9]},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(["python3", str(SCRIPT), "--trace", str(trace), "--out", str(out_spec)], text=True, capture_output=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("deps", proc.stderr)


if __name__ == "__main__":
    unittest.main()
