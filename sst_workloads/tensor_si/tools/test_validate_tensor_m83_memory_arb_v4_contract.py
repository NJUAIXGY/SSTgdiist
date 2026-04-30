#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m83_memory_arb_v4_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m83_memory_arb_v4_contract.py"


class ValidateTensorM83MemoryArbV4ContractTest(unittest.TestCase):
    def _summary(self, *, lat_total: int, lat_samples: int, queue_wait: int, bus_wait: int, mac: float, conflict: int, refresh: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_read_latency_cycles_total": lat_total,
                "tensor_mem_read_latency_samples_total": lat_samples,
                "tensor_mem_bank_queue_wait_cycles_total": queue_wait,
                "tensor_mem_cmd_bus_wait_cycles_total": bus_wait,
                "tensor_effective_mac_per_cycle": mac,
                "tensor_mem_row_conflict_total": conflict,
                "tensor_mem_refresh_block_cycles_total": refresh,
            },
        }

    def _cfg(self, *, policy: str, depth: int) -> dict:
        return {"tensor_cfg": {"tensor_mem_sched_policy": policy, "tensor_mem_bank_queue_depth": depth}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f_d = root / "fair"
            u_d = root / "unfair"
            f_d.mkdir(parents=True, exist_ok=True)
            u_d.mkdir(parents=True, exist_ok=True)

            (f_d / "s.json").write_text(
                json.dumps(self._summary(lat_total=1000, lat_samples=100, queue_wait=50, bus_wait=20, mac=2.0, conflict=10, refresh=0)),
                encoding="utf-8",
            )
            (u_d / "s.json").write_text(
                json.dumps(self._summary(lat_total=3000, lat_samples=100, queue_wait=200, bus_wait=80, mac=1.0, conflict=100, refresh=10)),
                encoding="utf-8",
            )
            (f_d / "effective_config.json").write_text(json.dumps(self._cfg(policy="frfcfs", depth=16)), encoding="utf-8")
            (u_d / "effective_config.json").write_text(json.dumps(self._cfg(policy="fifo", depth=1)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--fair", str(f_d / "s.json"), "--unfair", str(u_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_sched(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f_d = root / "fair"
            u_d = root / "unfair"
            f_d.mkdir(parents=True, exist_ok=True)
            u_d.mkdir(parents=True, exist_ok=True)

            (f_d / "s.json").write_text(
                json.dumps(self._summary(lat_total=1000, lat_samples=100, queue_wait=50, bus_wait=20, mac=2.0, conflict=10, refresh=0)),
                encoding="utf-8",
            )
            (u_d / "s.json").write_text(
                json.dumps(self._summary(lat_total=3000, lat_samples=100, queue_wait=200, bus_wait=80, mac=1.0, conflict=100, refresh=10)),
                encoding="utf-8",
            )
            (f_d / "effective_config.json").write_text(json.dumps(self._cfg(policy="fifo", depth=16)), encoding="utf-8")
            (u_d / "effective_config.json").write_text(json.dumps(self._cfg(policy="fifo", depth=1)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--fair", str(f_d / "s.json"), "--unfair", str(u_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("sched policy", out.stderr)


if __name__ == "__main__":
    unittest.main()
