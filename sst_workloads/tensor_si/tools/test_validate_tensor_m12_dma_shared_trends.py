#!/usr/bin/env python3
"""Unit tests for validate_tensor_m12_dma_shared_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m12_dma_shared_trends.py"


def _make_summary(*, dram_bytes: int, iter_cycles: int) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 5000,
        "tensor": {
            "tensor_dram_bytes_total": dram_bytes,
            "tensor_iter_cycles_total": iter_cycles,
            "tensor_dma_cycles_total": max(0, iter_cycles // 2),
            "tensor_mem_bytes_read_total": max(0, dram_bytes // 2),
            "tensor_mem_bytes_write_total": max(0, dram_bytes // 2),
            "tensor_stall_mem_outstanding_cycles_total": 0,
        },
    }


class ValidateTensorM12TrendsTest(unittest.TestCase):
    def _write_summary(self, directory: Path, name: str, payload: Dict[str, object]) -> Path:
        path = directory / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _run(self, **kwargs: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(SCRIPT)]
        for key, value in kwargs.items():
            cmd.extend([f"--{key.replace('_', '-')}", value])
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            per_payload = _make_summary(dram_bytes=1024, iter_cycles=100)
            shared_payload = _make_summary(dram_bytes=1024, iter_cycles=200)
            per_payload["tensor"]["tensor_dma_cycles_total"] = 100
            shared_payload["tensor"]["tensor_dma_cycles_total"] = 250
            per_payload["tensor"]["tensor_stall_mem_outstanding_cycles_total"] = 10
            shared_payload["tensor"]["tensor_stall_mem_outstanding_cycles_total"] = 1
            per_core = self._write_summary(root, "per_core", per_payload)
            shared = self._write_summary(root, "shared", shared_payload)
            out = self._run(per_core=str(per_core), shared=str(shared))
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m12] PASS", out.stdout)

    def test_fail_when_bytes_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            per_payload = _make_summary(dram_bytes=1024, iter_cycles=100)
            shared_payload = _make_summary(dram_bytes=2048, iter_cycles=200)
            per_payload["tensor"]["tensor_dma_cycles_total"] = 100
            shared_payload["tensor"]["tensor_dma_cycles_total"] = 250
            per_payload["tensor"]["tensor_stall_mem_outstanding_cycles_total"] = 10
            shared_payload["tensor"]["tensor_stall_mem_outstanding_cycles_total"] = 1
            per_core = self._write_summary(root, "per_core", per_payload)
            shared = self._write_summary(root, "shared", shared_payload)
            out = self._run(per_core=str(per_core), shared=str(shared))
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected equal dram bytes", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
