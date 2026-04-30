#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m60_energy_ras_phase2_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m60_energy_ras_phase2_contract.py"


class ValidateTensorM60EnergyRasPhase2ContractTest(unittest.TestCase):
    def _summary(self, *, compute: int, dma: int, mem: int, pkt: int, mac: int, ras: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_compute_cycles_total": compute,
                "tensor_dma_cycles_total": dma,
                "tensor_mem_bytes_read_total": mem,
                "tensor_mem_bytes_write_total": mem,
                "tensor_pkt_bytes_sent_total": pkt,
                "tensor_pkt_bytes_recv_total": pkt,
                "tensor_mac_ops_total": mac,
                "tensor_stall_noc_budget_cycles_total": ras,
                "tensor_collective_backpressure_stall_cycles_total": 0,
                "tensor_collective_credit_stall_cycles_total": 0,
                "tensor_collective_credit_return_orphan_total": 0,
                "tensor_collective_credit_return_dup_total": 0,
                "tensor_program_mem_stall_cycles_total": 0,
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            eff = root / "eff.json"
            fault = root / "fault.json"
            rec = root / "rec.json"

            eff.write_text(json.dumps(self._summary(compute=1000, dma=200, mem=4096, pkt=64, mac=10000, ras=10)), encoding="utf-8")
            rec.write_text(json.dumps(self._summary(compute=1500, dma=400, mem=8192, pkt=256, mac=10000, ras=120)), encoding="utf-8")
            fault.write_text(json.dumps(self._summary(compute=2000, dma=700, mem=12288, pkt=512, mac=10000, ras=260)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--efficiency",
                    str(eff),
                    "--fault",
                    str(fault),
                    "--recovery",
                    str(rec),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_recovery_ras(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            eff = root / "eff.json"
            fault = root / "fault.json"
            rec = root / "rec.json"

            eff.write_text(json.dumps(self._summary(compute=1000, dma=200, mem=4096, pkt=64, mac=10000, ras=10)), encoding="utf-8")
            fault.write_text(json.dumps(self._summary(compute=2000, dma=700, mem=12288, pkt=512, mac=10000, ras=260)), encoding="utf-8")
            rec.write_text(json.dumps(self._summary(compute=1800, dma=600, mem=10000, pkt=300, mac=10000, ras=300)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--efficiency",
                    str(eff),
                    "--fault",
                    str(fault),
                    "--recovery",
                    str(rec),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected recovery ras < fault", out.stderr)


if __name__ == "__main__":
    unittest.main()
