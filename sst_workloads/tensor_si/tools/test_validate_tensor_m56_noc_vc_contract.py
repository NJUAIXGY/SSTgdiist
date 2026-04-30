#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m56_noc_vc_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m56_noc_vc_contract.py"


class ValidateTensorM56NocVcContractTest(unittest.TestCase):
    def _summary(self, *, credit: int, backpressure: int, noc_stall: int, inflight: int, coll_bytes: int = 1024) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_compute_cycles_total": 320,
                "tensor_mac_ops_total": 327680,
                "tensor_collective_bytes_sent_total": coll_bytes,
                "tensor_collective_credit_stall_cycles_total": credit,
                "tensor_collective_backpressure_stall_cycles_total": backpressure,
                "tensor_stall_noc_budget_cycles_total": noc_stall,
                "tensor_collective_inflight_chunks_max": inflight,
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = root / "b.json"
            p = root / "p.json"
            r = root / "r.json"
            b.write_text(json.dumps(self._summary(credit=0, backpressure=8, noc_stall=16, inflight=1)), encoding="utf-8")
            p.write_text(json.dumps(self._summary(credit=200, backpressure=300, noc_stall=400, inflight=1)), encoding="utf-8")
            r.write_text(json.dumps(self._summary(credit=40, backpressure=60, noc_stall=80, inflight=8)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline",
                    str(b),
                    "--pressure",
                    str(p),
                    "--relaxed",
                    str(r),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m56]", out.stdout)

    def test_fail_credit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = root / "b.json"
            p = root / "p.json"
            r = root / "r.json"
            b.write_text(json.dumps(self._summary(credit=0, backpressure=8, noc_stall=16, inflight=1)), encoding="utf-8")
            p.write_text(json.dumps(self._summary(credit=10, backpressure=20, noc_stall=30, inflight=1)), encoding="utf-8")
            r.write_text(json.dumps(self._summary(credit=20, backpressure=10, noc_stall=5, inflight=8)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline",
                    str(b),
                    "--pressure",
                    str(p),
                    "--relaxed",
                    str(r),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected pressure credit_stall > relaxed", out.stderr)


if __name__ == "__main__":
    unittest.main()
