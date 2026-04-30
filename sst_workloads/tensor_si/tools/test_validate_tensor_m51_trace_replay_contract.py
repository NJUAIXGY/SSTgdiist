#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m51_trace_replay_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m51_trace_replay_contract.py"


class ValidateTensorM51TraceReplayContractTest(unittest.TestCase):
    def _trace(self) -> dict:
        return {
            "schema_version": 1,
            "name": "demo",
            "program": [
                {"op": "dma_read", "bytes": 4096},
                {"op": "gemm_ub", "cycles": 64, "ub_read_bytes": 4096, "ub_write_bytes": 2048},
                {"op": "allreduce", "bytes": 1024, "blocking": True},
                {"op": "fence"},
            ],
        }

    def _spec(self) -> dict:
        return {
            "schema_version": 3,
            "workload": {
                "program": {
                    "ops": [
                        {"op_type": "dma_read", "bytes": 4096},
                        {"op_type": "gemm_ub", "cycles": 64, "ub_read_bytes": 4096, "ub_write_bytes": 2048},
                        {"op_type": "allreduce", "bytes": 1024, "blocking": True},
                        {"op_type": "fence"},
                    ]
                }
            },
        }

    def _summary(self, coll: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_program_ops_total": 8,
                "tensor_collective_bytes_sent_total": coll,
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.json"
            spec = root / "spec.json"
            summary = root / "summary.json"
            trace.write_text(json.dumps(self._trace()), encoding="utf-8")
            spec.write_text(json.dumps(self._spec()), encoding="utf-8")
            summary.write_text(json.dumps(self._summary(coll=2048)), encoding="utf-8")

            proc = subprocess.run(
                ["python3", str(SCRIPT), "--trace", str(trace), "--spec", str(spec), "--summary", str(summary), "--label", "x"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn("[m51:x]", proc.stdout)

    def test_fail_without_collective_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.json"
            spec = root / "spec.json"
            summary = root / "summary.json"
            trace.write_text(json.dumps(self._trace()), encoding="utf-8")
            spec.write_text(json.dumps(self._spec()), encoding="utf-8")
            summary.write_text(json.dumps(self._summary(coll=0)), encoding="utf-8")

            proc = subprocess.run(
                ["python3", str(SCRIPT), "--trace", str(trace), "--spec", str(spec), "--summary", str(summary)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("expected collective bytes > 0", proc.stderr)


if __name__ == "__main__":
    unittest.main()
