#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m48_pipeline_trends.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m48_pipeline_trends.py"


class ValidateTensorM48PipelineTrendsTest(unittest.TestCase):
    def _summary(self, pipe: int, mem_stall: int, eff_mac: float = 0.0, any_busy: int = 0, dma_busy: int = 0) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_bytes_read_total": 8192,
                "tensor_compute_pipeline_cycles_total": pipe,
                "tensor_program_mem_stall_cycles_total": mem_stall,
                "tensor_effective_mac_per_cycle_math": eff_mac,
                "tensor_program_any_busy_cycles_total": any_busy,
                "tensor_program_dma_busy_cycles_total": dma_busy,
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
            base = base_d / "summary.json"
            stress = stress_d / "summary.json"
            base.write_text(json.dumps(self._summary(pipe=100, mem_stall=10, eff_mac=1024.0, any_busy=100, dma_busy=100)), encoding="utf-8")
            stress.write_text(json.dumps(self._summary(pipe=200, mem_stall=20, eff_mac=512.0, any_busy=120, dma_busy=120)), encoding="utf-8")
            (base_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=4, lat=1)), encoding="utf-8")
            (stress_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, lat=8)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--baseline", str(base), "--stress", str(stress), "--label", "x"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m48:x]", out.stdout)

    def test_happy_path_with_pipeline_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_d = root / "base"
            stress_d = root / "stress"
            base_d.mkdir(parents=True, exist_ok=True)
            stress_d.mkdir(parents=True, exist_ok=True)
            base = base_d / "summary.json"
            stress = stress_d / "summary.json"
            base.write_text(json.dumps(self._summary(pipe=0, mem_stall=10, eff_mac=1024.0, any_busy=587, dma_busy=747)), encoding="utf-8")
            stress.write_text(json.dumps(self._summary(pipe=0, mem_stall=0, eff_mac=512.0, any_busy=641, dma_busy=791)), encoding="utf-8")
            (base_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=4, lat=1)), encoding="utf-8")
            (stress_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, lat=10)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--baseline", str(base), "--stress", str(stress), "--label", "proxy"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("pipeline_proxy_effective_mac", out.stdout)

    def test_fail_on_issue_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_d = root / "base"
            stress_d = root / "stress"
            base_d.mkdir(parents=True, exist_ok=True)
            stress_d.mkdir(parents=True, exist_ok=True)
            base = base_d / "summary.json"
            stress = stress_d / "summary.json"
            base.write_text(json.dumps(self._summary(pipe=100, mem_stall=10, eff_mac=1024.0, any_busy=100, dma_busy=100)), encoding="utf-8")
            stress.write_text(json.dumps(self._summary(pipe=200, mem_stall=20, eff_mac=512.0, any_busy=120, dma_busy=120)), encoding="utf-8")
            (base_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, lat=1)), encoding="utf-8")
            (stress_d / "effective_config.json").write_text(json.dumps(self._cfg(issue=1, lat=8)), encoding="utf-8")

            out = subprocess.run(["python3", str(SCRIPT), "--baseline", str(base), "--stress", str(stress)], text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected baseline issue_width > stress", out.stderr)


if __name__ == "__main__":
    unittest.main()
