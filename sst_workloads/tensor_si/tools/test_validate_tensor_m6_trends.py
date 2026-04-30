#!/usr/bin/env python3
"""Unit tests for validate_tensor_m6_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m6_trends.py"


def _make_summary(
    *,
    mac_ops: int,
    collective_bytes_sent: int,
    collective_pending: int,
    vector_cycles: int,
    program_ops: int,
    program_iters: int,
) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 5000,
        "tensor": {
            "tensor_mac_ops_total": mac_ops,
            "tensor_collective_bytes_sent_total": collective_bytes_sent,
            "tensor_collective_pending_cycles_total": collective_pending,
            "tensor_vector_cycles_total": vector_cycles,
            "tensor_program_ops_total": program_ops,
            "tensor_program_iters_total": program_iters,
        },
    }


class ValidateTensorM6TrendsTest(unittest.TestCase):
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
            paths = {
                "gemm_only": self._write_summary(
                    root,
                    "gemm_only",
                    _make_summary(
                        mac_ops=1024,
                        collective_bytes_sent=0,
                        collective_pending=0,
                        vector_cycles=0,
                        program_ops=16,
                        program_iters=16,
                    ),
                ),
                "mix_base": self._write_summary(
                    root,
                    "mix_base",
                    _make_summary(
                        mac_ops=2048,
                        collective_bytes_sent=4096,
                        collective_pending=100,
                        vector_cycles=1024,
                        program_ops=48,
                        program_iters=16,
                    ),
                ),
                "softmax_heavy": self._write_summary(
                    root,
                    "softmax_heavy",
                    _make_summary(
                        mac_ops=2048,
                        collective_bytes_sent=4096,
                        collective_pending=100,
                        vector_cycles=8192,
                        program_ops=48,
                        program_iters=16,
                    ),
                ),
                "allreduce_more": self._write_summary(
                    root,
                    "allreduce_more",
                    _make_summary(
                        mac_ops=2048,
                        collective_bytes_sent=16384,
                        collective_pending=120,
                        vector_cycles=1024,
                        program_ops=48,
                        program_iters=16,
                    ),
                ),
                "noc_capped": self._write_summary(
                    root,
                    "noc_capped",
                    _make_summary(
                        mac_ops=2048,
                        collective_bytes_sent=4096,
                        collective_pending=200,
                        vector_cycles=1024,
                        program_ops=48,
                        program_iters=16,
                    ),
                ),
                "loop_2iters": self._write_summary(
                    root,
                    "loop_2iters",
                    _make_summary(
                        mac_ops=4096,
                        collective_bytes_sent=8192,
                        collective_pending=200,
                        vector_cycles=2048,
                        program_ops=96,
                        program_iters=32,
                    ),
                ),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m6] PASS", out.stdout)

    def test_fail_when_gemm_only_has_collective(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = {
                "gemm_only": self._write_summary(
                    root,
                    "gemm_only",
                    _make_summary(
                        mac_ops=1024,
                        collective_bytes_sent=1,
                        collective_pending=0,
                        vector_cycles=0,
                        program_ops=16,
                        program_iters=16,
                    ),
                ),
                "mix_base": self._write_summary(
                    root,
                    "mix_base",
                    _make_summary(
                        mac_ops=2048,
                        collective_bytes_sent=4096,
                        collective_pending=100,
                        vector_cycles=1024,
                        program_ops=48,
                        program_iters=16,
                    ),
                ),
                "softmax_heavy": self._write_summary(
                    root,
                    "softmax_heavy",
                    _make_summary(
                        mac_ops=2048,
                        collective_bytes_sent=4096,
                        collective_pending=100,
                        vector_cycles=8192,
                        program_ops=48,
                        program_iters=16,
                    ),
                ),
                "allreduce_more": self._write_summary(
                    root,
                    "allreduce_more",
                    _make_summary(
                        mac_ops=2048,
                        collective_bytes_sent=16384,
                        collective_pending=120,
                        vector_cycles=1024,
                        program_ops=48,
                        program_iters=16,
                    ),
                ),
                "noc_capped": self._write_summary(
                    root,
                    "noc_capped",
                    _make_summary(
                        mac_ops=2048,
                        collective_bytes_sent=4096,
                        collective_pending=200,
                        vector_cycles=1024,
                        program_ops=48,
                        program_iters=16,
                    ),
                ),
                "loop_2iters": self._write_summary(
                    root,
                    "loop_2iters",
                    _make_summary(
                        mac_ops=4096,
                        collective_bytes_sent=8192,
                        collective_pending=200,
                        vector_cycles=2048,
                        program_ops=96,
                        program_iters=32,
                    ),
                ),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("gemm_only", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
