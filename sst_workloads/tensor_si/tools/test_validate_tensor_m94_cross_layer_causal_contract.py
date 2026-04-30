#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m94_cross_layer_causal_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m94_cross_layer_causal_contract.py"


class ValidateTensorM94CrossLayerCausalContractTest(unittest.TestCase):
    def _ready(self, *, dom: str, mem_cmd: int, mem_q: int, noc_budget: int, coll: int, noc_share: float) -> dict:
        return {
            "schema_version": 1,
            "npu_tpu_readiness": {
                "cross_layer_attribution": {
                    "dominant_layer": dom,
                    "layer_share": {"compute": 0.0, "memory": 1.0 - float(noc_share), "noc": float(noc_share)},
                    "signals": {
                        "tensor_mem_cmd_bus_wait_cycles_total": mem_cmd,
                        "tensor_mem_bank_queue_wait_cycles_total": mem_q,
                        "tensor_stall_noc_budget_cycles_total": noc_budget,
                        "tensor_collective_credit_stall_cycles_total": coll,
                        "tensor_collective_backpressure_stall_cycles_total": 0,
                    },
                }
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mem = root / "mem.json"
            noc = root / "noc.json"
            mem.write_text(json.dumps(self._ready(dom="memory", mem_cmd=200, mem_q=100, noc_budget=20, coll=5, noc_share=0.01)), encoding="utf-8")
            noc.write_text(json.dumps(self._ready(dom="noc", mem_cmd=20, mem_q=10, noc_budget=300, coll=150, noc_share=0.25)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--memory", str(mem), "--noc", str(noc)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_dominant(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mem = root / "mem.json"
            noc = root / "noc.json"
            mem.write_text(json.dumps(self._ready(dom="noc", mem_cmd=200, mem_q=100, noc_budget=20, coll=5, noc_share=0.01)), encoding="utf-8")
            noc.write_text(json.dumps(self._ready(dom="noc", mem_cmd=20, mem_q=10, noc_budget=300, coll=150, noc_share=0.25)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--memory", str(mem), "--noc", str(noc)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("dominant_layer", out.stderr)


if __name__ == "__main__":
    unittest.main()
