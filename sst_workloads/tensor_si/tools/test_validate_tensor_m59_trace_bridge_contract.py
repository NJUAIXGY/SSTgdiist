#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m59_trace_bridge_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m59_trace_bridge_contract.py"


class ValidateTensorM59TraceBridgeContractTest(unittest.TestCase):
    def _summary(self, *, ops: int, iters: int, mem: int, coll_bytes: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_program_ops_total": ops,
                "tensor_program_iters_total": iters,
                "tensor_mem_bytes_read_total": mem,
                "tensor_collective_bytes_sent_total": coll_bytes,
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "base.json"
            coll = root / "coll.json"
            base.write_text(json.dumps(self._summary(ops=4, iters=1, mem=32768, coll_bytes=0)), encoding="utf-8")
            coll.write_text(json.dumps(self._summary(ops=5, iters=1, mem=32768, coll_bytes=65536)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline",
                    str(base),
                    "--collective",
                    str(coll),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_collective_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "base.json"
            coll = root / "coll.json"
            base.write_text(json.dumps(self._summary(ops=4, iters=1, mem=32768, coll_bytes=0)), encoding="utf-8")
            coll.write_text(json.dumps(self._summary(ops=5, iters=1, mem=32768, coll_bytes=0)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline",
                    str(base),
                    "--collective",
                    str(coll),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("collective bytes_sent increase", out.stderr)


if __name__ == "__main__":
    unittest.main()
