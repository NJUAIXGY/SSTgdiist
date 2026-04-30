#!/usr/bin/env python3
"""Unit tests for validate_tensor_m9_collective_completion.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m9_collective_completion.py"


def _make_summary(*, tensor: Dict[str, object]) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 50000,
        "tensor": dict(tensor),
    }


class ValidateTensorM9CollectiveCompletionTest(unittest.TestCase):
    def _write_summary(self, directory: Path, name: str, payload: Dict[str, object]) -> Path:
        path = directory / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _run(self, **kwargs: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(SCRIPT)]
        for key, value in kwargs.items():
            cmd.extend([f"--{key.replace('_', '-')}", value])
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_pass_when_epochs_complete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            ring = self._write_summary(
                root,
                "ring",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 1,
                        "tensor_program_ops_total": 16,
                        "tensor_program_iters_total": 16,
                        "tensor_collective_epoch_done_total": 16,
                        "tensor_collective_epoch_latency_cycles_total": 1600,
                        "tensor_collective_epoch_latency_cycles_max": 200,
                        "tensor_collective_bytes_sent_total": 1024,
                        "tensor_collective_bytes_recv_total": 1024,
                    }
                ),
            )

            torus_2d = self._write_summary(
                root,
                "torus_2d",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 2,
                        "tensor_program_ops_total": 16,
                        "tensor_program_iters_total": 16,
                        "tensor_collective_epoch_done_total": 16,
                        "tensor_collective_epoch_latency_cycles_total": 2000,
                        "tensor_collective_epoch_latency_cycles_max": 300,
                        "tensor_collective_bytes_sent_total": 2048,
                        "tensor_collective_bytes_recv_total": 2048,
                    }
                ),
            )

            out = self._run(ring=str(ring), torus_2d=str(torus_2d))
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m9] PASS", out.stdout)

    def test_fail_when_epoch_done_is_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            ring = self._write_summary(
                root,
                "ring",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 1,
                        "tensor_program_ops_total": 16,
                        "tensor_program_iters_total": 16,
                        "tensor_collective_epoch_done_total": 0,
                        "tensor_collective_bytes_sent_total": 1024,
                        "tensor_collective_bytes_recv_total": 1024,
                    }
                ),
            )

            torus_2d = self._write_summary(
                root,
                "torus_2d",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 2,
                        "tensor_program_ops_total": 16,
                        "tensor_program_iters_total": 16,
                        "tensor_collective_epoch_done_total": 16,
                        "tensor_collective_bytes_sent_total": 2048,
                        "tensor_collective_bytes_recv_total": 2048,
                    }
                ),
            )

            out = self._run(ring=str(ring), torus_2d=str(torus_2d))
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("epoch_done_total", out.stdout)


if __name__ == "__main__":
    unittest.main()

