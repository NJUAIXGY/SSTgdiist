#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m88_energy_power_v4_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m88_energy_power_v4_contract.py"


class ValidateTensorM88EnergyPowerV4ContractTest(unittest.TestCase):
    def _summary(self, *, compute: int, dma: int, mem: int, pkt: int, cmd_wait: int, q_wait: int, noc_stall: int, mem_stall: int, mac: int, eff_mac: float) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_compute_cycles_total": compute,
                "tensor_compute_pipeline_cycles_total": 0,
                "tensor_dma_cycles_total": dma,
                "tensor_dma_stall_cycles_total": 0,
                "tensor_mem_bytes_read_total": mem,
                "tensor_mem_bytes_write_total": mem,
                "tensor_mem_cmd_bus_wait_cycles_total": cmd_wait,
                "tensor_mem_bank_queue_wait_cycles_total": q_wait,
                "tensor_pkt_bytes_sent_total": pkt,
                "tensor_pkt_bytes_recv_total": pkt,
                "tensor_stall_noc_budget_cycles_total": noc_stall,
                "tensor_collective_credit_stall_cycles_total": 0,
                "tensor_collective_backpressure_stall_cycles_total": 0,
                "tensor_program_mem_stall_cycles_total": mem_stall,
                "tensor_mac_ops_total": mac,
                "tensor_effective_mac_per_cycle": eff_mac,
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            eff = root / "eff.json"
            cap = root / "cap.json"
            eff.write_text(
                json.dumps(
                    self._summary(
                        compute=1000,
                        dma=200,
                        mem=4096,
                        pkt=128,
                        cmd_wait=10,
                        q_wait=10,
                        noc_stall=10,
                        mem_stall=20,
                        mac=10000,
                        eff_mac=2.0,
                    )
                ),
                encoding="utf-8",
            )
            cap.write_text(
                json.dumps(
                    self._summary(
                        compute=2000,
                        dma=400,
                        mem=8192,
                        pkt=512,
                        cmd_wait=40,
                        q_wait=40,
                        noc_stall=80,
                        mem_stall=120,
                        mac=10000,
                        eff_mac=1.0,
                    )
                ),
                encoding="utf-8",
            )
            out = subprocess.run(
                ["python3", str(SCRIPT), "--efficiency", str(eff), "--power-cap", str(cap)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_energy_per_mac(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            eff = root / "eff.json"
            cap = root / "cap.json"
            eff.write_text(
                json.dumps(
                    self._summary(
                        compute=2000,
                        dma=400,
                        mem=8192,
                        pkt=512,
                        cmd_wait=40,
                        q_wait=40,
                        noc_stall=80,
                        mem_stall=120,
                        mac=10000,
                        eff_mac=2.0,
                    )
                ),
                encoding="utf-8",
            )
            cap.write_text(
                json.dumps(
                    self._summary(
                        compute=1000,
                        dma=200,
                        mem=4096,
                        pkt=128,
                        cmd_wait=10,
                        q_wait=10,
                        noc_stall=10,
                        mem_stall=20,
                        mac=10000,
                        eff_mac=1.0,
                    )
                ),
                encoding="utf-8",
            )
            out = subprocess.run(
                ["python3", str(SCRIPT), "--efficiency", str(eff), "--power-cap", str(cap)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("energy_per_mac", out.stderr)


if __name__ == "__main__":
    unittest.main()
