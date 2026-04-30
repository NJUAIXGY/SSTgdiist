#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m67_energy_breakdown_v3_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m67_energy_breakdown_v3_contract.py"


class ValidateTensorM67EnergyBreakdownV3ContractTest(unittest.TestCase):
    def _summary(self, *, compute: int, pipe: int, dma: int, dma_stall: int, mem: int, cmd_wait: int, q_wait: int, pkt: int, noc_stall: int, coll_stall: int, mac: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_compute_cycles_total": compute,
                "tensor_compute_pipeline_cycles_total": pipe,
                "tensor_dma_cycles_total": dma,
                "tensor_dma_stall_cycles_total": dma_stall,
                "tensor_mem_bytes_read_total": mem,
                "tensor_mem_bytes_write_total": mem,
                "tensor_mem_cmd_bus_wait_cycles_total": cmd_wait,
                "tensor_mem_bank_queue_wait_cycles_total": q_wait,
                "tensor_pkt_bytes_sent_total": pkt,
                "tensor_pkt_bytes_recv_total": pkt,
                "tensor_stall_noc_budget_cycles_total": noc_stall,
                "tensor_collective_credit_stall_cycles_total": coll_stall,
                "tensor_collective_backpressure_stall_cycles_total": coll_stall,
                "tensor_mac_ops_total": mac,
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            eff = root / "eff.json"
            fault = root / "fault.json"
            rec = root / "rec.json"
            eff.write_text(json.dumps(self._summary(compute=1000, pipe=100, dma=200, dma_stall=20, mem=8192, cmd_wait=30, q_wait=20, pkt=256, noc_stall=10, coll_stall=0, mac=10000)), encoding="utf-8")
            rec.write_text(json.dumps(self._summary(compute=1300, pipe=140, dma=300, dma_stall=40, mem=12288, cmd_wait=80, q_wait=60, pkt=512, noc_stall=120, coll_stall=80, mac=10000)), encoding="utf-8")
            fault.write_text(json.dumps(self._summary(compute=1800, pipe=200, dma=700, dma_stall=80, mem=16384, cmd_wait=200, q_wait=160, pkt=2048, noc_stall=400, coll_stall=220, mac=10000)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--efficiency", str(eff), "--fault", str(fault), "--recovery", str(rec)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            eff = root / "eff.json"
            fault = root / "fault.json"
            rec = root / "rec.json"
            eff.write_text(json.dumps(self._summary(compute=1800, pipe=200, dma=700, dma_stall=80, mem=16384, cmd_wait=200, q_wait=160, pkt=2048, noc_stall=400, coll_stall=220, mac=10000)), encoding="utf-8")
            rec.write_text(json.dumps(self._summary(compute=1300, pipe=140, dma=300, dma_stall=40, mem=12288, cmd_wait=80, q_wait=60, pkt=512, noc_stall=120, coll_stall=80, mac=10000)), encoding="utf-8")
            fault.write_text(json.dumps(self._summary(compute=1000, pipe=100, dma=200, dma_stall=20, mem=8192, cmd_wait=30, q_wait=20, pkt=256, noc_stall=10, coll_stall=0, mac=10000)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--efficiency", str(eff), "--fault", str(fault), "--recovery", str(rec)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("fault > recovery > efficiency", out.stderr)


if __name__ == "__main__":
    unittest.main()
