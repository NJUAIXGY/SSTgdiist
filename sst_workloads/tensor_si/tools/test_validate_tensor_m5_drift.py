#!/usr/bin/env python3
"""Unit tests for validate_tensor_m5_drift.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m5_drift.py"


def _summary(*, sent: int, pending: int, credit_stall: int, inflight: int, ret_recv: int, ret_sent: int) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "tensor": {
            "tensor_collective_bytes_sent_total": sent,
            "tensor_collective_pending_cycles_total": pending,
            "tensor_collective_credit_stall_cycles_total": credit_stall,
            "tensor_collective_inflight_chunks_max": inflight,
            "tensor_collective_credit_return_pkts_recv_total": ret_recv,
            "tensor_collective_credit_return_pkts_sent_total": ret_sent,
        },
    }


class ValidateTensorM5DriftTest(unittest.TestCase):
    def _write_summary(self, directory: Path, name: str, payload: Dict[str, object]) -> Path:
        path = directory / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _run(self, *, current: Path, baseline: Path, threshold: float) -> subprocess.CompletedProcess[str]:
        cmd = [
            sys.executable,
            str(SCRIPT),
            "--current",
            str(current),
            "--baseline",
            str(baseline),
            "--threshold",
            str(threshold),
        ]
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_pass_within_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            baseline = self._write_summary(
                root,
                "baseline",
                _summary(sent=1000, pending=200, credit_stall=80, inflight=4, ret_recv=120, ret_sent=120),
            )
            current = self._write_summary(
                root,
                "current",
                _summary(sent=1060, pending=190, credit_stall=88, inflight=4, ret_recv=126, ret_sent=118),
            )
            out = self._run(current=current, baseline=baseline, threshold=0.10)
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m5][drift] PASS", out.stdout)

    def test_fail_when_threshold_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            baseline = self._write_summary(
                root,
                "baseline",
                _summary(sent=1000, pending=200, credit_stall=80, inflight=4, ret_recv=120, ret_sent=120),
            )
            current = self._write_summary(
                root,
                "current",
                _summary(sent=1600, pending=190, credit_stall=88, inflight=4, ret_recv=126, ret_sent=118),
            )
            out = self._run(current=current, baseline=baseline, threshold=0.10)
            self.assertEqual(out.returncode, 14, msg=out.stdout + out.stderr)
            self.assertIn("exceeded threshold", out.stdout)


if __name__ == "__main__":
    unittest.main()
