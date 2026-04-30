#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m68_ras_policy_v3_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m68_ras_policy_v3_contract.py"


class ValidateTensorM68RasPolicyV3ContractTest(unittest.TestCase):
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
            retry_d = root / "retry"
            throttle_d = root / "throttle"
            isolate_d = root / "isolate"
            retry_d.mkdir(parents=True, exist_ok=True)
            throttle_d.mkdir(parents=True, exist_ok=True)
            isolate_d.mkdir(parents=True, exist_ok=True)

            (retry_d / "s.json").write_text(json.dumps(self._summary(300, 2.0)), encoding="utf-8")
            (throttle_d / "s.json").write_text(json.dumps(self._summary(200, 1.8)), encoding="utf-8")
            (isolate_d / "s.json").write_text(json.dumps(self._summary(100, 1.6)), encoding="utf-8")

            (retry_d / "effective_config.json").write_text(json.dumps(self._cfg("retry")), encoding="utf-8")
            (throttle_d / "effective_config.json").write_text(json.dumps(self._cfg("throttle")), encoding="utf-8")
            (isolate_d / "effective_config.json").write_text(json.dumps(self._cfg("isolate")), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--retry",
                    str(retry_d / "s.json"),
                    "--throttle",
                    str(throttle_d / "s.json"),
                    "--isolate",
                    str(isolate_d / "s.json"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            retry_d = root / "retry"
            throttle_d = root / "throttle"
            isolate_d = root / "isolate"
            retry_d.mkdir(parents=True, exist_ok=True)
            throttle_d.mkdir(parents=True, exist_ok=True)
            isolate_d.mkdir(parents=True, exist_ok=True)

            (retry_d / "s.json").write_text(json.dumps(self._summary(300, 2.0)), encoding="utf-8")
            (throttle_d / "s.json").write_text(json.dumps(self._summary(200, 1.8)), encoding="utf-8")
            (isolate_d / "s.json").write_text(json.dumps(self._summary(100, 1.6)), encoding="utf-8")

            (retry_d / "effective_config.json").write_text(json.dumps(self._cfg("retry")), encoding="utf-8")
            (throttle_d / "effective_config.json").write_text(json.dumps(self._cfg("bad")), encoding="utf-8")
            (isolate_d / "effective_config.json").write_text(json.dumps(self._cfg("isolate")), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--retry",
                    str(retry_d / "s.json"),
                    "--throttle",
                    str(throttle_d / "s.json"),
                    "--isolate",
                    str(isolate_d / "s.json"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected policies", out.stderr)


if __name__ == "__main__":
    unittest.main()
