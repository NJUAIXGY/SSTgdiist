#!/usr/bin/env python3
"""Unit tests for validate_tensor_m11_training_step.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m11_training_step.py"


def _make_summary(*, tensor: Dict[str, object]) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 50000,
        "tensor": dict(tensor),
    }


class ValidateTensorM11TrainingStepTest(unittest.TestCase):
    def _run(self, summary: Path) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(SCRIPT), "--summary", str(summary)]
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.json"
            p.write_text(
                json.dumps(
                    _make_summary(
                        tensor={
                            "tensor_program_iters_total": 16,
                            "tensor_program_ops_total": 32,
                            "tensor_mac_ops_total": 123,
                            "tensor_collective_epoch_done_total": 16,
                            "tensor_collective_bytes_sent_total": 1024,
                            "tensor_collective_bytes_recv_total": 1024,
                        }
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            out = self._run(p)
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m11] PASS", out.stdout)

    def test_fail_ops_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.json"
            p.write_text(
                json.dumps(
                    _make_summary(
                        tensor={
                            "tensor_program_iters_total": 16,
                            "tensor_program_ops_total": 31,
                            "tensor_mac_ops_total": 123,
                            "tensor_collective_epoch_done_total": 16,
                            "tensor_collective_bytes_sent_total": 1024,
                            "tensor_collective_bytes_recv_total": 1024,
                        }
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            out = self._run(p)
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("program_ops_total", out.stdout)


if __name__ == "__main__":
    unittest.main()

