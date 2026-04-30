#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m105_trace_v4_bridge_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m105_trace_v4_bridge_contract.py"


class ValidateTensorM105TraceV4BridgeContractTest(unittest.TestCase):
    def _summary(self, *, ops: int, iters: int, mem: int, coll: int, busy: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_program_ops_total": ops,
                "tensor_program_iters_total": iters,
                "tensor_mem_bytes_read_total": mem,
                "tensor_collective_bytes_sent_total": coll,
                "tensor_program_any_busy_cycles_total": busy,
            },
        }

    def _spec(self, *, op_count: int, dep_edges: int, tile_windows: int, barriers: int, resource_windows: int) -> dict:
        return {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "params": {
                    "tensor_trace_v4_op_count": op_count,
                    "tensor_trace_v4_dependency_edges": dep_edges,
                    "tensor_trace_v4_tile_windows": tile_windows,
                    "tensor_trace_v4_barrier_count": barriers,
                    "tensor_trace_v4_resource_windows": resource_windows,
                }
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b_sum = root / "b_sum.json"
            d_sum = root / "d_sum.json"
            b_spec = root / "b_spec.json"
            d_spec = root / "d_spec.json"
            b_sum.write_text(json.dumps(self._summary(ops=4, iters=1, mem=1024, coll=0, busy=100)), encoding="utf-8")
            d_sum.write_text(json.dumps(self._summary(ops=8, iters=2, mem=2048, coll=1024, busy=200)), encoding="utf-8")
            b_spec.write_text(json.dumps(self._spec(op_count=4, dep_edges=2, tile_windows=2, barriers=1, resource_windows=2)), encoding="utf-8")
            d_spec.write_text(json.dumps(self._spec(op_count=8, dep_edges=6, tile_windows=6, barriers=3, resource_windows=4)), encoding="utf-8")
            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline-summary",
                    str(b_sum),
                    "--dependency-summary",
                    str(d_sum),
                    "--baseline-spec",
                    str(b_spec),
                    "--dependency-spec",
                    str(d_spec),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_dep_edges(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b_sum = root / "b_sum.json"
            d_sum = root / "d_sum.json"
            b_spec = root / "b_spec.json"
            d_spec = root / "d_spec.json"
            b_sum.write_text(json.dumps(self._summary(ops=4, iters=1, mem=1024, coll=0, busy=100)), encoding="utf-8")
            d_sum.write_text(json.dumps(self._summary(ops=8, iters=2, mem=2048, coll=1024, busy=200)), encoding="utf-8")
            b_spec.write_text(json.dumps(self._spec(op_count=4, dep_edges=2, tile_windows=2, barriers=1, resource_windows=2)), encoding="utf-8")
            d_spec.write_text(json.dumps(self._spec(op_count=8, dep_edges=1, tile_windows=6, barriers=3, resource_windows=4)), encoding="utf-8")
            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline-summary",
                    str(b_sum),
                    "--dependency-summary",
                    str(d_sum),
                    "--baseline-spec",
                    str(b_spec),
                    "--dependency-spec",
                    str(d_spec),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("dep_edges", out.stderr)


if __name__ == "__main__":
    unittest.main()
