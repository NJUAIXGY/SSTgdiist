#!/usr/bin/env python3
"""Unit tests for validate_tensor_m4_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m4_trends.py"


def _make_summary(
    *,
    bank_conflict_stall: int,
    queue_occ_max: int,
    collective_pending: int,
    collective_issue: int,
    collective_bytes_sent: int,
    pkt_bytes_sent: int,
    credit_stall: int,
    backpressure_stall: int,
    inflight_max: int,
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
            "tensor_collective_pending_cycles_total": collective_pending,
            "tensor_collective_issue_cycles_total": collective_issue,
            "tensor_collective_bytes_sent_total": collective_bytes_sent,
            "tensor_pkt_bytes_sent_total": pkt_bytes_sent,
            "tensor_stall_onchip_bank_conflict_cycles_total": bank_conflict_stall,
            "tensor_collective_credit_stall_cycles_total": credit_stall,
            "tensor_collective_backpressure_stall_cycles_total": backpressure_stall,
            "tensor_collective_inflight_chunks_max": inflight_max,
            "tensor_bank_queue_occupancy_max": queue_occ_max,
        },
    }


class ValidateTensorM4TrendsTest(unittest.TestCase):
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
                    _make_summary(
                        bank_conflict_stall=0,
                        queue_occ_max=0,
                        collective_pending=0,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=0,
                        credit_stall=0,
                        backpressure_stall=0,
                        inflight_max=0,
                    ),
                ),
                "bank_conflict_heavy": self._write_summary(
                    root,
                    "bank_conflict_heavy",
                    _make_summary(
                        bank_conflict_stall=120,
                        queue_occ_max=1,
                        collective_pending=0,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=0,
                        credit_stall=0,
                        backpressure_stall=0,
                        inflight_max=0,
                    ),
                ),
                "bank_conflict_relaxed": self._write_summary(
                    root,
                    "bank_conflict_relaxed",
                    _make_summary(
                        bank_conflict_stall=12,
                        queue_occ_max=2,
                        collective_pending=0,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=0,
                        credit_stall=0,
                        backpressure_stall=0,
                        inflight_max=0,
                    ),
                ),
                "bank_conflict_queue_limited": self._write_summary(
                    root,
                    "bank_conflict_queue_limited",
                    _make_summary(
                        bank_conflict_stall=80,
                        queue_occ_max=5,
                        collective_pending=0,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=0,
                        credit_stall=0,
                        backpressure_stall=0,
                        inflight_max=0,
                    ),
                ),
                "collective_credit_off": self._write_summary(
                    root,
                    "collective_credit_off",
                    _make_summary(
                        bank_conflict_stall=0,
                        queue_occ_max=0,
                        collective_pending=120,
                        collective_issue=64,
                        collective_bytes_sent=8192,
                        pkt_bytes_sent=8192,
                        credit_stall=0,
                        backpressure_stall=0,
                        inflight_max=0,
                    ),
                ),
                "collective_credit_hard": self._write_summary(
                    root,
                    "collective_credit_hard",
                    _make_summary(
                        bank_conflict_stall=0,
                        queue_occ_max=0,
                        collective_pending=220,
                        collective_issue=48,
                        collective_bytes_sent=6144,
                        pkt_bytes_sent=6144,
                        credit_stall=64,
                        backpressure_stall=64,
                        inflight_max=4,
                    ),
                ),
                "collective_credit_soft": self._write_summary(
                    root,
                    "collective_credit_soft",
                    _make_summary(
                        bank_conflict_stall=0,
                        queue_occ_max=0,
                        collective_pending=180,
                        collective_issue=72,
                        collective_bytes_sent=9216,
                        pkt_bytes_sent=9216,
                        credit_stall=80,
                        backpressure_stall=40,
                        inflight_max=6,
                    ),
                ),
                "collective_credit_payload_first": self._write_summary(
                    root,
                    "collective_credit_payload_first",
                    _make_summary(
                        bank_conflict_stall=0,
                        queue_occ_max=0,
                        collective_pending=256,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=4096,
                        credit_stall=32,
                        backpressure_stall=32,
                        inflight_max=2,
                    ),
                ),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m4] PASS", out.stdout)

    def test_fail_when_hard_credit_stall_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            common = _make_summary(
                bank_conflict_stall=10,
                queue_occ_max=2,
                collective_pending=100,
                collective_issue=20,
                collective_bytes_sent=2048,
                pkt_bytes_sent=2048,
                credit_stall=10,
                backpressure_stall=10,
                inflight_max=2,
            )
            paths = {
                "baseline_compat": self._write_summary(root, "baseline_compat", _make_summary(
                    bank_conflict_stall=0,
                    queue_occ_max=0,
                    collective_pending=0,
                    collective_issue=0,
                    collective_bytes_sent=0,
                    pkt_bytes_sent=0,
                    credit_stall=0,
                    backpressure_stall=0,
                    inflight_max=0,
                )),
                "bank_conflict_heavy": self._write_summary(root, "bank_conflict_heavy", _make_summary(
                    bank_conflict_stall=100,
                    queue_occ_max=1,
                    collective_pending=0,
                    collective_issue=0,
                    collective_bytes_sent=0,
                    pkt_bytes_sent=0,
                    credit_stall=0,
                    backpressure_stall=0,
                    inflight_max=0,
                )),
                "bank_conflict_relaxed": self._write_summary(root, "bank_conflict_relaxed", _make_summary(
                    bank_conflict_stall=20,
                    queue_occ_max=1,
                    collective_pending=0,
                    collective_issue=0,
                    collective_bytes_sent=0,
                    pkt_bytes_sent=0,
                    credit_stall=0,
                    backpressure_stall=0,
                    inflight_max=0,
                )),
                "bank_conflict_queue_limited": self._write_summary(root, "bank_conflict_queue_limited", _make_summary(
                    bank_conflict_stall=60,
                    queue_occ_max=2,
                    collective_pending=0,
                    collective_issue=0,
                    collective_bytes_sent=0,
                    pkt_bytes_sent=0,
                    credit_stall=0,
                    backpressure_stall=0,
                    inflight_max=0,
                )),
                "collective_credit_off": self._write_summary(root, "collective_credit_off", _make_summary(
                    bank_conflict_stall=0,
                    queue_occ_max=0,
                    collective_pending=80,
                    collective_issue=20,
                    collective_bytes_sent=2048,
                    pkt_bytes_sent=2048,
                    credit_stall=0,
                    backpressure_stall=0,
                    inflight_max=0,
                )),
                "collective_credit_hard": self._write_summary(root, "collective_credit_hard", _make_summary(
                    bank_conflict_stall=0,
                    queue_occ_max=0,
                    collective_pending=120,
                    collective_issue=20,
                    collective_bytes_sent=2048,
                    pkt_bytes_sent=2048,
                    credit_stall=0,
                    backpressure_stall=0,
                    inflight_max=2,
                )),
                "collective_credit_soft": self._write_summary(root, "collective_credit_soft", common),
                "collective_credit_payload_first": self._write_summary(root, "collective_credit_payload_first", _make_summary(
                    bank_conflict_stall=0,
                    queue_occ_max=0,
                    collective_pending=120,
                    collective_issue=0,
                    collective_bytes_sent=0,
                    pkt_bytes_sent=1024,
                    credit_stall=10,
                    backpressure_stall=10,
                    inflight_max=1,
                )),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("credit stall", out.stdout)


if __name__ == "__main__":
    unittest.main()
