#!/usr/bin/env python3
"""Unit tests for validate_tensor_m13_weight_pool_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m13_weight_pool_trends.py"


def _make_summary(*, mac_ops: int, spill_bytes: int) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 5000,
        "tensor": {
            "tensor_mac_ops_total": mac_ops,
            "tensor_spill_bytes_total": spill_bytes,
            "tensor_mem_bytes_read_total": 123,
            "tensor_mem_bytes_write_total": 456,
        },
    }


class ValidateTensorM13TrendsTest(unittest.TestCase):
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
            unified = self._write_summary(root, "unified", _make_summary(mac_ops=10, spill_bytes=1024))
            split = self._write_summary(root, "split", _make_summary(mac_ops=10, spill_bytes=0))
            out = self._run(unified=str(unified), split=str(split))
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m13] PASS", out.stdout)

    def test_fail_when_split_spills(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            unified = self._write_summary(root, "unified", _make_summary(mac_ops=10, spill_bytes=1024))
            split = self._write_summary(root, "split", _make_summary(mac_ops=10, spill_bytes=64))
            out = self._run(unified=str(unified), split=str(split))
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected split spill_bytes_total == 0", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()

