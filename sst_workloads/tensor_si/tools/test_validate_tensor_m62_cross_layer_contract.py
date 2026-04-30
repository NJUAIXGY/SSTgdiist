#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m62_cross_layer_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m62_cross_layer_contract.py"


class ValidateTensorM62CrossLayerContractTest(unittest.TestCase):
    def _summary(self, *, dominant: str, compute: float, memory: float, noc: float) -> dict:
        return {
            "schema_version": 1,
            "npu_tpu_readiness": {
                "cross_layer_attribution": {
                    "dominant_layer": dominant,
                    "layer_share": {"compute": compute, "memory": memory, "noc": noc},
                },
                "top_bottlenecks": [dominant, "memory"],
                "suggested_interventions": [
                    {"parameter": "x", "direction": "increase", "expected_effect": "y"}
                ],
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mem = root / "mem.json"
            noc = root / "noc.json"
            mem.write_text(json.dumps(self._summary(dominant="memory", compute=0.3, memory=0.5, noc=0.2)), encoding="utf-8")
            noc.write_text(json.dumps(self._summary(dominant="noc", compute=0.2, memory=0.3, noc=0.5)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--memory", str(mem), "--noc", str(noc)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mem = root / "mem.json"
            noc = root / "noc.json"
            mem.write_text(json.dumps(self._summary(dominant="memory", compute=0.3, memory=0.2, noc=0.5)), encoding="utf-8")
            noc.write_text(json.dumps(self._summary(dominant="noc", compute=0.2, memory=0.4, noc=0.4)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--memory", str(mem), "--noc", str(noc)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("memory scenario", out.stderr)

    def test_memory_dominant_noc_scenario_with_uplift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mem = root / "mem.json"
            noc = root / "noc.json"
            mem.write_text(json.dumps(self._summary(dominant="memory", compute=0.0, memory=1.0, noc=0.0)), encoding="utf-8")
            noc.write_text(json.dumps(self._summary(dominant="memory", compute=0.0, memory=0.95, noc=0.05)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--memory", str(mem), "--noc", str(noc)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)


if __name__ == "__main__":
    unittest.main()
