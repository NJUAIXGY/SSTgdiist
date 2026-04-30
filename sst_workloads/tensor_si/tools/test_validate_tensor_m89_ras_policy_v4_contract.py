#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m89_ras_policy_v4_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m89_ras_policy_v4_contract.py"


class ValidateTensorM89RasPolicyV4ContractTest(unittest.TestCase):
    def _summary(self, ras: int, mac: float) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_stall_noc_budget_cycles_total": ras,
                "tensor_collective_backpressure_stall_cycles_total": 0,
                "tensor_collective_credit_stall_cycles_total": 0,
                "tensor_collective_credit_return_orphan_total": 0,
                "tensor_collective_credit_return_dup_total": 0,
                "tensor_program_mem_stall_cycles_total": 0,
                "tensor_mem_cmd_bus_wait_cycles_total": 0,
                "tensor_effective_mac_per_cycle": mac,
            },
        }

    def _cfg(self, policy: str) -> dict:
        return {"tensor_cfg": {"tensor_ras_policy": policy}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d_retry = root / "retry"
            d_throttle = root / "throttle"
            d_isolate = root / "isolate"
            d_hybrid = root / "hybrid"
            for d in (d_retry, d_throttle, d_isolate, d_hybrid):
                d.mkdir(parents=True, exist_ok=True)

            (d_retry / "s.json").write_text(json.dumps(self._summary(400, 1.0)), encoding="utf-8")
            (d_throttle / "s.json").write_text(json.dumps(self._summary(220, 1.2)), encoding="utf-8")
            (d_isolate / "s.json").write_text(json.dumps(self._summary(100, 1.8)), encoding="utf-8")
            (d_hybrid / "s.json").write_text(json.dumps(self._summary(180, 1.5)), encoding="utf-8")
            (d_retry / "effective_config.json").write_text(json.dumps(self._cfg("retry")), encoding="utf-8")
            (d_throttle / "effective_config.json").write_text(json.dumps(self._cfg("throttle")), encoding="utf-8")
            (d_isolate / "effective_config.json").write_text(json.dumps(self._cfg("isolate")), encoding="utf-8")
            (d_hybrid / "effective_config.json").write_text(json.dumps(self._cfg("hybrid")), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--retry",
                    str(d_retry / "s.json"),
                    "--throttle",
                    str(d_throttle / "s.json"),
                    "--isolate",
                    str(d_isolate / "s.json"),
                    "--hybrid",
                    str(d_hybrid / "s.json"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d_retry = root / "retry"
            d_throttle = root / "throttle"
            d_isolate = root / "isolate"
            d_hybrid = root / "hybrid"
            for d in (d_retry, d_throttle, d_isolate, d_hybrid):
                d.mkdir(parents=True, exist_ok=True)

            (d_retry / "s.json").write_text(json.dumps(self._summary(400, 1.0)), encoding="utf-8")
            (d_throttle / "s.json").write_text(json.dumps(self._summary(220, 1.2)), encoding="utf-8")
            (d_isolate / "s.json").write_text(json.dumps(self._summary(100, 1.8)), encoding="utf-8")
            (d_hybrid / "s.json").write_text(json.dumps(self._summary(180, 1.5)), encoding="utf-8")
            (d_retry / "effective_config.json").write_text(json.dumps(self._cfg("retry")), encoding="utf-8")
            (d_throttle / "effective_config.json").write_text(json.dumps(self._cfg("bad")), encoding="utf-8")
            (d_isolate / "effective_config.json").write_text(json.dumps(self._cfg("isolate")), encoding="utf-8")
            (d_hybrid / "effective_config.json").write_text(json.dumps(self._cfg("hybrid")), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--retry",
                    str(d_retry / "s.json"),
                    "--throttle",
                    str(d_throttle / "s.json"),
                    "--isolate",
                    str(d_isolate / "s.json"),
                    "--hybrid",
                    str(d_hybrid / "s.json"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected policies", out.stderr)


if __name__ == "__main__":
    unittest.main()
