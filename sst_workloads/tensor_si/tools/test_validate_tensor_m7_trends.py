#!/usr/bin/env python3
"""Unit tests for validate_tensor_m7_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m7_trends.py"


def _make_summary(
    *,
    mac_ops: int,
    program_ops: int,
    program_iters: int,
    dma_busy: int,
    mxu_busy: int,
    ub_stall: int,
    fence_count: int,
    fence_wait: int,
) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 5000,
        "tensor": {
            "tensor_mac_ops_total": mac_ops,
            "tensor_program_ops_total": program_ops,
            "tensor_program_iters_total": program_iters,
            "tensor_program_dma_busy_cycles_total": dma_busy,
            "tensor_program_mxu_busy_cycles_total": mxu_busy,
            "tensor_program_ub_stall_cycles_total": ub_stall,
            "tensor_program_fence_count_total": fence_count,
            "tensor_program_fence_wait_cycles_total": fence_wait,
        },
    }


class ValidateTensorM7TrendsTest(unittest.TestCase):
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
            ub_dep = self._write_summary(
                root,
                "ub_dep",
                _make_summary(
                    mac_ops=1024,
                    program_ops=2,
                    program_iters=1,
                    dma_busy=10,
                    mxu_busy=32,
                    ub_stall=5,
                    fence_count=0,
                    fence_wait=0,
                ),
            )
            fence_wait = self._write_summary(
                root,
                "fence_wait",
                _make_summary(
                    mac_ops=1024,
                    program_ops=3,
                    program_iters=1,
                    dma_busy=10,
                    mxu_busy=32,
                    ub_stall=0,
                    fence_count=1,
                    fence_wait=7,
                ),
            )
            out = self._run(ub_dep=str(ub_dep), fence_wait=str(fence_wait))
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m7] PASS", out.stdout)

    def test_fail_when_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ub_dep = self._write_summary(
                root,
                "ub_dep",
                {
                    "schema_version": 1,
                    "sim_time_ns": 5000,
                    "tensor": {"tensor_mac_ops_total": 1},
                },
            )
            fence_wait = self._write_summary(
                root,
                "fence_wait",
                _make_summary(
                    mac_ops=1024,
                    program_ops=3,
                    program_iters=1,
                    dma_busy=10,
                    mxu_busy=32,
                    ub_stall=0,
                    fence_count=1,
                    fence_wait=7,
                ),
            )
            out = self._run(ub_dep=str(ub_dep), fence_wait=str(fence_wait))
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("missing key", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()

