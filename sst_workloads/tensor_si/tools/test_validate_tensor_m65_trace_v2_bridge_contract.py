#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m65_trace_v2_bridge_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m65_trace_v2_bridge_contract.py"


class ValidateTensorM65TraceV2BridgeContractTest(unittest.TestCase):
    def _summary(self, *, ops: int, fence_wait: int, coll: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_program_ops_total": ops,
                "tensor_program_fence_wait_cycles_total": fence_wait,
                "tensor_collective_bytes_sent_total": coll,
            },
        }

    def _spec(self, *, op_count: int, deps: int, kinds: int) -> dict:
        return {
            "schema_version": 3,
            "workload": {
                "params": {
                    "tensor_trace_v2_op_count": op_count,
                    "tensor_trace_v2_dependency_edges": deps,
                    "tensor_trace_v2_resource_kinds": kinds,
                }
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bsum = root / "bsum.json"
            dsum = root / "dsum.json"
            bspec = root / "bspec.json"
            dspec = root / "dspec.json"
            bsum.write_text(json.dumps(self._summary(ops=4, fence_wait=10, coll=0)), encoding="utf-8")
            dsum.write_text(json.dumps(self._summary(ops=8, fence_wait=20, coll=65536)), encoding="utf-8")
            bspec.write_text(json.dumps(self._spec(op_count=4, deps=2, kinds=2)), encoding="utf-8")
            dspec.write_text(json.dumps(self._spec(op_count=8, deps=6, kinds=3)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline-summary",
                    str(bsum),
                    "--dependency-summary",
                    str(dsum),
                    "--baseline-spec",
                    str(bspec),
                    "--dependency-spec",
                    str(dspec),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_dep_edges(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bsum = root / "bsum.json"
            dsum = root / "dsum.json"
            bspec = root / "bspec.json"
            dspec = root / "dspec.json"
            bsum.write_text(json.dumps(self._summary(ops=4, fence_wait=10, coll=0)), encoding="utf-8")
            dsum.write_text(json.dumps(self._summary(ops=8, fence_wait=20, coll=65536)), encoding="utf-8")
            bspec.write_text(json.dumps(self._spec(op_count=4, deps=2, kinds=2)), encoding="utf-8")
            dspec.write_text(json.dumps(self._spec(op_count=8, deps=1, kinds=3)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline-summary",
                    str(bsum),
                    "--dependency-summary",
                    str(dsum),
                    "--baseline-spec",
                    str(bspec),
                    "--dependency-spec",
                    str(dspec),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("dependency edges", out.stderr)

    def test_equal_program_ops_allowed_when_collective_increases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bsum = root / "bsum.json"
            dsum = root / "dsum.json"
            bspec = root / "bspec.json"
            dspec = root / "dspec.json"
            bsum.write_text(json.dumps(self._summary(ops=16, fence_wait=600, coll=0)), encoding="utf-8")
            dsum.write_text(json.dumps(self._summary(ops=16, fence_wait=0, coll=24000)), encoding="utf-8")
            bspec.write_text(json.dumps(self._spec(op_count=4, deps=2, kinds=2)), encoding="utf-8")
            dspec.write_text(json.dumps(self._spec(op_count=8, deps=6, kinds=3)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline-summary",
                    str(bsum),
                    "--dependency-summary",
                    str(dsum),
                    "--baseline-spec",
                    str(bspec),
                    "--dependency-spec",
                    str(dspec),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)


if __name__ == "__main__":
    unittest.main()
