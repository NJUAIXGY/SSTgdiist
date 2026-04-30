#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m49_mem_timing_trends.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m49_mem_timing_trends.py"


class ValidateTensorM49MemTimingTrendsTest(unittest.TestCase):
    def _summary(self, total: int, samples: int, queue: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_bytes_read_total": 8192,
                "tensor_mem_read_latency_cycles_total": total,
                "tensor_mem_read_latency_samples_total": samples,
                "tensor_stall_mem_outstanding_cycles_total": queue,
            },
        }

    def _cfg(self, profile: str, req: int) -> dict:
        return {"tensor_cfg": {"tensor_memory_hierarchy_profile": profile, "tensor_mem_req_bytes": req}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            edge_d = root / "edge"
            server_d = root / "server"
            edge_d.mkdir(parents=True, exist_ok=True)
            server_d.mkdir(parents=True, exist_ok=True)
            edge = edge_d / "summary.json"
            server = server_d / "summary.json"
            edge.write_text(json.dumps(self._summary(total=1000, samples=10, queue=40)), encoding="utf-8")
            server.write_text(json.dumps(self._summary(total=300, samples=10, queue=10)), encoding="utf-8")
            (edge_d / "effective_config.json").write_text(json.dumps(self._cfg("edge", 64)), encoding="utf-8")
            (server_d / "effective_config.json").write_text(json.dumps(self._cfg("server", 256)), encoding="utf-8")

            out = subprocess.run(["python3", str(SCRIPT), "--edge", str(edge), "--server", str(server), "--label", "x"], text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m49:x]", out.stdout)

    def test_fail_on_profile(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            edge_d = root / "edge"
            server_d = root / "server"
            edge_d.mkdir(parents=True, exist_ok=True)
            server_d.mkdir(parents=True, exist_ok=True)
            edge = edge_d / "summary.json"
            server = server_d / "summary.json"
            edge.write_text(json.dumps(self._summary(total=1000, samples=10, queue=40)), encoding="utf-8")
            server.write_text(json.dumps(self._summary(total=300, samples=10, queue=10)), encoding="utf-8")
            (edge_d / "effective_config.json").write_text(json.dumps(self._cfg("edge", 64)), encoding="utf-8")
            (server_d / "effective_config.json").write_text(json.dumps(self._cfg("edge", 256)), encoding="utf-8")

            out = subprocess.run(["python3", str(SCRIPT), "--edge", str(edge), "--server", str(server)], text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected edge/server profiles", out.stderr)


if __name__ == "__main__":
    unittest.main()
