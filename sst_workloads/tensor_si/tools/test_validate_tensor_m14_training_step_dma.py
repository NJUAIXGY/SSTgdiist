#!/usr/bin/env python3
"""Unit tests for validate_tensor_m14_training_step_dma.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m14_training_step_dma.py"


def _make_summary(
    *,
    iters: int,
    ops: int,
    dma_busy: int,
    mxu_busy: int,
    fence_count: int,
    macs: int,
    epochs_done: int,
    bytes_sent: int,
    bytes_recv: int,
) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 5000,
        "tensor": {
            "tensor_program_iters_total": iters,
            "tensor_program_ops_total": ops,
            "tensor_program_dma_busy_cycles_total": dma_busy,
            "tensor_program_mxu_busy_cycles_total": mxu_busy,
            "tensor_program_fence_count_total": fence_count,
            "tensor_mac_ops_total": macs,
            "tensor_collective_epoch_done_total": epochs_done,
            "tensor_collective_bytes_sent_total": bytes_sent,
            "tensor_collective_bytes_recv_total": bytes_recv,
        },
    }


class ValidateTensorM14TrainingStepDmaTest(unittest.TestCase):
    def _write_summary(self, directory: Path, name: str, payload: Dict[str, object]) -> Path:
        path = directory / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _run(self, *, summary: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(SCRIPT), "--summary", summary]
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = _make_summary(
                iters=16,
                ops=96,
                dma_busy=10,
                mxu_busy=20,
                fence_count=16,
                macs=1024,
                epochs_done=16,
                bytes_sent=1,
                bytes_recv=1,
            )
            path = self._write_summary(root, "ok", payload)
            out = self._run(summary=str(path))
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m14] PASS", out.stdout)

    def test_fail_when_ops_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = _make_summary(
                iters=16,
                ops=32,
                dma_busy=10,
                mxu_busy=20,
                fence_count=16,
                macs=1024,
                epochs_done=16,
                bytes_sent=1,
                bytes_recv=1,
            )
            path = self._write_summary(root, "bad", payload)
            out = self._run(summary=str(path))
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("program_ops_total", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()

