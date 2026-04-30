#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m25_ramulator2_backend_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m25_ramulator2_backend_trends.py"


class ValidateTensorM25Ramulator2BackendTrendsTest(unittest.TestCase):
    def _write_run(self, root: Path, name: str, *, backend: str, dma_busy: int) -> Path:
        run_dir = root / name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "effective_config.json").write_text(
            json.dumps(
                {
                    "mesh_cfg": {
                        "mem_backend": backend,
                        "mem_backend_params": {"configFile": "x.cfg"} if backend == "ramulator2" else {},
                    }
                }
            ),
            encoding="utf-8",
        )
        summary = run_dir / "essential_summary_tensor_mesh.json"
        summary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "tensor": {
                        "tensor_program_iters_total": 1,
                        "tensor_mem_bytes_read_total": 8192,
                        "tensor_program_dma_busy_cycles_total": dma_busy,
                    },
                }
            ),
            encoding="utf-8",
        )
        return summary

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            simple = self._write_run(root, "simple", backend="simple", dma_busy=100)
            ram2 = self._write_run(root, "ram2", backend="ramulator2", dma_busy=200)

            cmd = ["python3", str(SCRIPT), "--simple", str(simple), "--ram2", str(ram2), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m25:x]", out.stdout)

    def test_fails_when_ram2_not_slower(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            simple = self._write_run(root, "simple", backend="simple", dma_busy=200)
            ram2 = self._write_run(root, "ram2", backend="ramulator2", dma_busy=200)

            cmd = ["python3", str(SCRIPT), "--simple", str(simple), "--ram2", str(ram2)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("dma_busy(ram2) > simple", out.stderr)


if __name__ == "__main__":
    unittest.main()

