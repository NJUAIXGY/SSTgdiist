#!/usr/bin/env python3
"""Unit tests for validate_tensor_m2_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m2_trends.py"


def _make_summary(
    *,
    overlap_cycles: int,
    pending_cycles: int,
    noc_budget_stall: int,
    collective_stall: int,
    collective_issue_cycles: int = 20,
    collective_bytes_sent: int = 1024,
    pkt_bytes_sent: int = 2048,
) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 5000,
        "tensor": {
            "tensor_compute_cycles_total": 1000,
            "tensor_compute_math_cycles_total": 900,
            "tensor_compute_pipeline_cycles_total": 100,
            "tensor_mac_ops_total": 1024000,
            "tensor_collective_pending_cycles_total": pending_cycles,
            "tensor_collective_issue_cycles_total": collective_issue_cycles,
            "tensor_stall_noc_budget_cycles_total": noc_budget_stall,
            "tensor_overlap_compute_collective_cycles_total": overlap_cycles,
            "tensor_stall_collective_cycles_total": collective_stall,
            "tensor_collective_bytes_sent_total": collective_bytes_sent,
            "tensor_pkt_bytes_sent_total": pkt_bytes_sent,
        },
    }


class ValidateTensorM2TrendsTest(unittest.TestCase):
    def _write_summary(self, directory: Path, name: str, payload: Dict[str, object]) -> Path:
        path = directory / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _run(self, **kwargs: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(SCRIPT)]
        for key, value in kwargs.items():
            cmd.extend([f"--{key.replace('_', '-')}", value])
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_pass_with_valid_trends(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = {
                "baseline_compat": self._write_summary(
                    root,
                    "baseline_compat",
                    _make_summary(overlap_cycles=0, pending_cycles=0, noc_budget_stall=0, collective_stall=0),
                ),
                "noc_capped_overlap_on": self._write_summary(
                    root,
                    "noc_capped_overlap_on",
                    _make_summary(overlap_cycles=32, pending_cycles=64, noc_budget_stall=16, collective_stall=8),
                ),
                "noc_capped_overlap_off": self._write_summary(
                    root,
                    "noc_capped_overlap_off",
                    _make_summary(overlap_cycles=0, pending_cycles=64, noc_budget_stall=16, collective_stall=24),
                ),
                "noc_capped_heavy_collective": self._write_summary(
                    root,
                    "noc_capped_heavy_collective",
                    _make_summary(overlap_cycles=16, pending_cycles=128, noc_budget_stall=48, collective_stall=12),
                ),
                "noc_capped_payload_first": self._write_summary(
                    root,
                    "noc_capped_payload_first",
                    _make_summary(
                        overlap_cycles=0,
                        pending_cycles=256,
                        noc_budget_stall=64,
                        collective_stall=0,
                        collective_issue_cycles=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=4096,
                    ),
                ),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m2] PASS", out.stdout)

    def test_fail_when_overlap_off_has_overlap_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = {
                "baseline_compat": self._write_summary(
                    root,
                    "baseline_compat",
                    _make_summary(overlap_cycles=0, pending_cycles=0, noc_budget_stall=0, collective_stall=0),
                ),
                "noc_capped_overlap_on": self._write_summary(
                    root,
                    "noc_capped_overlap_on",
                    _make_summary(overlap_cycles=32, pending_cycles=64, noc_budget_stall=16, collective_stall=8),
                ),
                "noc_capped_overlap_off": self._write_summary(
                    root,
                    "noc_capped_overlap_off",
                    _make_summary(overlap_cycles=2, pending_cycles=64, noc_budget_stall=16, collective_stall=24),
                ),
                "noc_capped_heavy_collective": self._write_summary(
                    root,
                    "noc_capped_heavy_collective",
                    _make_summary(overlap_cycles=16, pending_cycles=128, noc_budget_stall=48, collective_stall=12),
                ),
                "noc_capped_payload_first": self._write_summary(
                    root,
                    "noc_capped_payload_first",
                    _make_summary(
                        overlap_cycles=0,
                        pending_cycles=256,
                        noc_budget_stall=64,
                        collective_stall=0,
                        collective_issue_cycles=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=4096,
                    ),
                ),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("overlap_off", out.stdout)


if __name__ == "__main__":
    unittest.main()
