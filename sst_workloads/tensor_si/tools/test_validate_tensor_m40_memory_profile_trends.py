#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m40_memory_profile_trends.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m40_memory_profile_trends.py"


class ValidateTensorM40MemoryProfileTrendsTest(unittest.TestCase):
    def _mk_summary(self, dma_busy: int, lat_total: int, lat_samples: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_bytes_read_total": 8192,
                "tensor_mem_read_latency_cycles_total": lat_total,
                "tensor_mem_read_latency_samples_total": lat_samples,
                "tensor_program_dma_busy_cycles_total": dma_busy,
            },
        }

    def _mk_cfg(self, profile: str, channels: int) -> dict:
        return {"tensor_cfg": {"tensor_memory_hierarchy_profile": profile, "tensor_dma_hbm_channels": channels}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            edge_d = root / "edge"
            server_d = root / "server"
            edge_d.mkdir(parents=True, exist_ok=True)
            server_d.mkdir(parents=True, exist_ok=True)
            edge_p = edge_d / "summary.json"
            server_p = server_d / "summary.json"
            edge_p.write_text(json.dumps(self._mk_summary(dma_busy=200, lat_total=600, lat_samples=10)), encoding="utf-8")
            server_p.write_text(json.dumps(self._mk_summary(dma_busy=100, lat_total=300, lat_samples=10)), encoding="utf-8")
            (edge_d / "effective_config.json").write_text(json.dumps(self._mk_cfg("edge", 1)), encoding="utf-8")
            (server_d / "effective_config.json").write_text(json.dumps(self._mk_cfg("server", 4)), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--edge", str(edge_p), "--server", str(server_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m40:x]", out.stdout)

    def test_fail_when_channel_order_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            edge_d = root / "edge"
            server_d = root / "server"
            edge_d.mkdir(parents=True, exist_ok=True)
            server_d.mkdir(parents=True, exist_ok=True)
            edge_p = edge_d / "summary.json"
            server_p = server_d / "summary.json"
            edge_p.write_text(json.dumps(self._mk_summary(dma_busy=200, lat_total=600, lat_samples=10)), encoding="utf-8")
            server_p.write_text(json.dumps(self._mk_summary(dma_busy=100, lat_total=300, lat_samples=10)), encoding="utf-8")
            (edge_d / "effective_config.json").write_text(json.dumps(self._mk_cfg("edge", 4)), encoding="utf-8")
            (server_d / "effective_config.json").write_text(json.dumps(self._mk_cfg("server", 4)), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--edge", str(edge_p), "--server", str(server_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected edge channels < server channels", out.stderr)


if __name__ == "__main__":
    unittest.main()
