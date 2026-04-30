#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m102_pipeline_scoreboard_v3_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m102_pipeline_scoreboard_v3_contract.py"


class ValidateTensorM102PipelineScoreboardV3ContractTest(unittest.TestCase):
    def _summary(self, *, hazard: int, any_busy: int, mac: float, compute: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_program_ops_total": 8,
                "tensor_stall_onchip_port_cycles_total": hazard // 3,
                "tensor_stall_onchip_bank_conflict_cycles_total": hazard // 3,
                "tensor_program_ub_stall_cycles_total": hazard // 3,
                "tensor_program_fence_wait_cycles_total": 0,
                "tensor_program_mem_stall_cycles_total": 0,
                "tensor_program_any_busy_cycles_total": any_busy,
                "tensor_effective_mac_per_cycle": mac,
                "tensor_compute_cycles_total": compute,
            },
        }

    def _cfg(self, *, issue: int, latency: int) -> dict:
        return {"tensor_cfg": {"tensor_program_issue_width": issue, "tensor_compute_pipeline_latency_cycles": latency}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b_d = root / "b"
            s_d = root / "s"
            b_d.mkdir(parents=True, exist_ok=True)
            s_d.mkdir(parents=True, exist_ok=True)
            (b_d / "s.json").write_text(json.dumps(self._summary(hazard=100, any_busy=1000, mac=2.0, compute=100)), encoding="utf-8")
            (s_d / "s.json").write_text(json.dumps(self._summary(hazard=300, any_busy=1400, mac=1.2, compute=180)), encoding="utf-8")
            (b_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=4, latency=1)), encoding="utf-8")
            (s_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, latency=8)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--baseline", str(b_d / "s.json"), "--stress", str(s_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_issue_width(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b_d = root / "b"
            s_d = root / "s"
            b_d.mkdir(parents=True, exist_ok=True)
            s_d.mkdir(parents=True, exist_ok=True)
            (b_d / "s.json").write_text(json.dumps(self._summary(hazard=100, any_busy=1000, mac=2.0, compute=100)), encoding="utf-8")
            (s_d / "s.json").write_text(json.dumps(self._summary(hazard=300, any_busy=1400, mac=1.2, compute=180)), encoding="utf-8")
            (b_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, latency=1)), encoding="utf-8")
            (s_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, latency=8)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--baseline", str(b_d / "s.json"), "--stress", str(s_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("issue_width", out.stderr)


if __name__ == "__main__":
    unittest.main()
