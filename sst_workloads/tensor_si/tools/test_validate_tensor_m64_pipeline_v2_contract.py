#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m64_pipeline_v2_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m64_pipeline_v2_contract.py"


class ValidateTensorM64PipelineV2ContractTest(unittest.TestCase):
    def _summary(self, *, pipe: int, eff: float, any_busy: int, dma_busy: int, fence_wait: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_bytes_read_total": 65536,
                "tensor_compute_pipeline_cycles_total": pipe,
                "tensor_effective_mac_per_cycle_math": eff,
                "tensor_program_any_busy_cycles_total": any_busy,
                "tensor_program_dma_busy_cycles_total": dma_busy,
                "tensor_program_fence_wait_cycles_total": fence_wait,
            },
        }

    def _cfg(self, issue: int, lat: int) -> dict:
        return {"tensor_cfg": {"tensor_program_issue_width": issue, "tensor_compute_pipeline_latency_cycles": lat}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_d = root / "base"
            stress_d = root / "stress"
            base_d.mkdir(parents=True, exist_ok=True)
            stress_d.mkdir(parents=True, exist_ok=True)
            (base_d / "s.json").write_text(json.dumps(self._summary(pipe=120, eff=1000.0, any_busy=500, dma_busy=300, fence_wait=40)), encoding="utf-8")
            (stress_d / "s.json").write_text(json.dumps(self._summary(pipe=240, eff=700.0, any_busy=650, dma_busy=320, fence_wait=60)), encoding="utf-8")
            (base_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=4, lat=1)), encoding="utf-8")
            (stress_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, lat=8)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--baseline", str(base_d / "s.json"), "--stress", str(stress_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_issue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_d = root / "base"
            stress_d = root / "stress"
            base_d.mkdir(parents=True, exist_ok=True)
            stress_d.mkdir(parents=True, exist_ok=True)
            (base_d / "s.json").write_text(json.dumps(self._summary(pipe=120, eff=1000.0, any_busy=500, dma_busy=300, fence_wait=40)), encoding="utf-8")
            (stress_d / "s.json").write_text(json.dumps(self._summary(pipe=240, eff=700.0, any_busy=650, dma_busy=320, fence_wait=60)), encoding="utf-8")
            (base_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, lat=1)), encoding="utf-8")
            (stress_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, lat=8)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--baseline", str(base_d / "s.json"), "--stress", str(stress_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("issue_width", out.stderr)

    def test_zero_pipeline_uses_busy_pressure_signal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_d = root / "base"
            stress_d = root / "stress"
            base_d.mkdir(parents=True, exist_ok=True)
            stress_d.mkdir(parents=True, exist_ok=True)
            (base_d / "s.json").write_text(
                json.dumps(self._summary(pipe=0, eff=1024.0, any_busy=500, dma_busy=300, fence_wait=40)),
                encoding="utf-8",
            )
            (stress_d / "s.json").write_text(
                json.dumps(self._summary(pipe=0, eff=1024.0, any_busy=650, dma_busy=320, fence_wait=60)),
                encoding="utf-8",
            )
            (base_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=4, lat=1)), encoding="utf-8")
            (stress_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, lat=8)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--baseline", str(base_d / "s.json"), "--stress", str(stress_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fence_can_drop_when_other_busy_signals_increase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_d = root / "base"
            stress_d = root / "stress"
            base_d.mkdir(parents=True, exist_ok=True)
            stress_d.mkdir(parents=True, exist_ok=True)
            (base_d / "s.json").write_text(
                json.dumps(self._summary(pipe=0, eff=1024.0, any_busy=9000, dma_busy=10000, fence_wait=5000)),
                encoding="utf-8",
            )
            (stress_d / "s.json").write_text(
                json.dumps(self._summary(pipe=0, eff=1024.0, any_busy=9100, dma_busy=10100, fence_wait=1200)),
                encoding="utf-8",
            )
            (base_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=4, lat=1)), encoding="utf-8")
            (stress_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, lat=8)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--baseline", str(base_d / "s.json"), "--stress", str(stress_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)


if __name__ == "__main__":
    unittest.main()
