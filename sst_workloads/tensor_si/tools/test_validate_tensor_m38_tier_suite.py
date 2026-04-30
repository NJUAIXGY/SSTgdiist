#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m38_tier_suite.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m38_tier_suite.py"


class ValidateTensorM38TierSuiteTest(unittest.TestCase):
    def _mk(self, score: float, ops: int, mxu: int, dma: int, coll: int, pkt: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_program_ops_total": ops,
                "tensor_program_mxu_busy_cycles_total": mxu,
                "tensor_program_dma_busy_cycles_total": dma,
                "tensor_program_coll_busy_cycles_total": coll,
                "tensor_pkt_bytes_sent_total": pkt,
                "tensor_pkt_bytes_recv_total": pkt,
                "tensor_capability_score_total": score,
            },
            "npu_tpu_readiness": {"capability_score_total": score},
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            op = self._mk(55.0, ops=4, mxu=80, dma=20, coll=0, pkt=0)
            sg = self._mk(63.0, ops=8, mxu=120, dma=60, coll=10, pkt=128)
            e2e = self._mk(71.0, ops=12, mxu=100, dma=80, coll=50, pkt=512)
            op_p = root / "op.json"
            sg_p = root / "sg.json"
            e2e_p = root / "e2e.json"
            op_p.write_text(json.dumps(op), encoding="utf-8")
            sg_p.write_text(json.dumps(sg), encoding="utf-8")
            e2e_p.write_text(json.dumps(e2e), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--operator",
                str(op_p),
                "--subgraph",
                str(sg_p),
                "--e2e",
                str(e2e_p),
                "--label",
                "x",
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m38:x]", out.stdout)

    def test_fail_when_e2e_no_network_activity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            op = self._mk(55.0, ops=4, mxu=80, dma=20, coll=0, pkt=0)
            sg = self._mk(63.0, ops=8, mxu=120, dma=60, coll=10, pkt=128)
            e2e = self._mk(71.0, ops=12, mxu=100, dma=80, coll=0, pkt=0)
            op_p = root / "op.json"
            sg_p = root / "sg.json"
            e2e_p = root / "e2e.json"
            op_p.write_text(json.dumps(op), encoding="utf-8")
            sg_p.write_text(json.dumps(sg), encoding="utf-8")
            e2e_p.write_text(json.dumps(e2e), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--operator", str(op_p), "--subgraph", str(sg_p), "--e2e", str(e2e_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected e2e tier to expose collective/network activity", out.stderr)


if __name__ == "__main__":
    unittest.main()
