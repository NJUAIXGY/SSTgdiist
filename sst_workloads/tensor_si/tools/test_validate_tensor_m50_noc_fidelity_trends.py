#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m50_noc_fidelity_trends.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m50_noc_fidelity_trends.py"


class ValidateTensorM50NocFidelityTrendsTest(unittest.TestCase):
    def _summary(self, coll: int, noc_stall: int, pending: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_collective_bytes_sent_total": coll,
                "tensor_stall_noc_budget_cycles_total": noc_stall,
                "tensor_collective_pending_cycles_total": pending,
            },
        }

    def _cfg(self, noc_type: str, bw: int) -> dict:
        return {"mesh_cfg": {"noc_type": noc_type}, "tensor_cfg": {"tensor_noc_bandwidth_bytes_per_cycle": bw}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            c_d = root / "c"
            b_d = root / "b"
            c_d.mkdir(parents=True, exist_ok=True)
            b_d.mkdir(parents=True, exist_ok=True)
            c = c_d / "summary.json"
            b = b_d / "summary.json"
            c.write_text(json.dumps(self._summary(coll=1000, noc_stall=200, pending=300)), encoding="utf-8")
            b.write_text(json.dumps(self._summary(coll=900, noc_stall=50, pending=80)), encoding="utf-8")
            (c_d / "effective_config.json").write_text(json.dumps(self._cfg("merlin_mesh", 32)), encoding="utf-8")
            (b_d / "effective_config.json").write_text(json.dumps(self._cfg("merlin_torus", 0)), encoding="utf-8")

            out = subprocess.run(["python3", str(SCRIPT), "--congest", str(c), "--balanced", str(b), "--label", "x"], text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m50:x]", out.stdout)

    def test_fail_on_bw(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            c_d = root / "c"
            b_d = root / "b"
            c_d.mkdir(parents=True, exist_ok=True)
            b_d.mkdir(parents=True, exist_ok=True)
            c = c_d / "summary.json"
            b = b_d / "summary.json"
            c.write_text(json.dumps(self._summary(coll=1000, noc_stall=200, pending=300)), encoding="utf-8")
            b.write_text(json.dumps(self._summary(coll=900, noc_stall=50, pending=80)), encoding="utf-8")
            (c_d / "effective_config.json").write_text(json.dumps(self._cfg("merlin_mesh", 0)), encoding="utf-8")
            (b_d / "effective_config.json").write_text(json.dumps(self._cfg("merlin_torus", 0)), encoding="utf-8")

            out = subprocess.run(["python3", str(SCRIPT), "--congest", str(c), "--balanced", str(b)], text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected positive congest", out.stderr)


if __name__ == "__main__":
    unittest.main()
