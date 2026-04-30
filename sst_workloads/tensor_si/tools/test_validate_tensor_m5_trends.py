#!/usr/bin/env python3
"""Unit tests for validate_tensor_m5_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m5_trends.py"


def _make_summary(
    *,
    collective_pending: int,
    collective_issue: int,
    collective_bytes_sent: int,
    pkt_bytes_sent: int,
    credit_stall: int,
    backpressure_stall: int,
    inflight_max: int,
    return_sent: int,
    return_recv: int,
    return_orphan: int,
    return_dup: int,
    return_latency_total: int,
    return_latency_max: int,
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
            "tensor_collective_credit_stall_cycles_total": credit_stall,
            "tensor_collective_backpressure_stall_cycles_total": backpressure_stall,
            "tensor_collective_inflight_chunks_max": inflight_max,
            "tensor_collective_credit_return_pkts_sent_total": return_sent,
            "tensor_collective_credit_return_pkts_recv_total": return_recv,
            "tensor_collective_credit_return_orphan_total": return_orphan,
            "tensor_collective_credit_return_dup_total": return_dup,
            "tensor_collective_credit_return_latency_cycles_total": return_latency_total,
            "tensor_collective_credit_return_latency_cycles_max": return_latency_max,
        },
    }


class ValidateTensorM5TrendsTest(unittest.TestCase):
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
                "legacy_tick": self._write_summary(
                    root,
                    "legacy_tick",
                    _make_summary(
                        collective_pending=120,
                        collective_issue=80,
                        collective_bytes_sent=8192,
                        pkt_bytes_sent=8192,
                        credit_stall=32,
                        backpressure_stall=32,
                        inflight_max=4,
                        return_sent=0,
                        return_recv=0,
                        return_orphan=0,
                        return_dup=0,
                        return_latency_total=0,
                        return_latency_max=0,
                    ),
                ),
                "event_hard": self._write_summary(
                    root,
                    "event_hard",
                    _make_summary(
                        collective_pending=240,
                        collective_issue=64,
                        collective_bytes_sent=6144,
                        pkt_bytes_sent=6144,
                        credit_stall=96,
                        backpressure_stall=96,
                        inflight_max=4,
                        return_sent=256,
                        return_recv=256,
                        return_orphan=0,
                        return_dup=0,
                        return_latency_total=2048,
                        return_latency_max=16,
                    ),
                ),
                "event_soft": self._write_summary(
                    root,
                    "event_soft",
                    _make_summary(
                        collective_pending=200,
                        collective_issue=72,
                        collective_bytes_sent=9216,
                        pkt_bytes_sent=9216,
                        credit_stall=80,
                        backpressure_stall=40,
                        inflight_max=6,
                        return_sent=288,
                        return_recv=288,
                        return_orphan=0,
                        return_dup=0,
                        return_latency_total=2016,
                        return_latency_max=14,
                    ),
                ),
                "event_payload_first": self._write_summary(
                    root,
                    "event_payload_first",
                    _make_summary(
                        collective_pending=256,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=4096,
                        credit_stall=32,
                        backpressure_stall=32,
                        inflight_max=2,
                        return_sent=0,
                        return_recv=0,
                        return_orphan=0,
                        return_dup=0,
                        return_latency_total=0,
                        return_latency_max=0,
                    ),
                ),
                "event_uncapped": self._write_summary(
                    root,
                    "event_uncapped",
                    _make_summary(
                        collective_pending=140,
                        collective_issue=96,
                        collective_bytes_sent=12288,
                        pkt_bytes_sent=12288,
                        credit_stall=24,
                        backpressure_stall=24,
                        inflight_max=8,
                        return_sent=384,
                        return_recv=384,
                        return_orphan=0,
                        return_dup=0,
                        return_latency_total=1536,
                        return_latency_max=12,
                    ),
                ),
                "event_stress": self._write_summary(
                    root,
                    "event_stress",
                    _make_summary(
                        collective_pending=480,
                        collective_issue=120,
                        collective_bytes_sent=15360,
                        pkt_bytes_sent=15360,
                        credit_stall=160,
                        backpressure_stall=160,
                        inflight_max=8,
                        return_sent=640,
                        return_recv=640,
                        return_orphan=0,
                        return_dup=0,
                        return_latency_total=6400,
                        return_latency_max=20,
                    ),
                ),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m5] PASS", out.stdout)

    def test_fail_when_event_hard_has_no_credit_return(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            common = _make_summary(
                collective_pending=200,
                collective_issue=60,
                collective_bytes_sent=6144,
                pkt_bytes_sent=6144,
                credit_stall=64,
                backpressure_stall=64,
                inflight_max=4,
                return_sent=200,
                return_recv=200,
                return_orphan=0,
                return_dup=0,
                return_latency_total=2000,
                return_latency_max=20,
            )
            paths = {
                "legacy_tick": self._write_summary(root, "legacy_tick", _make_summary(
                    collective_pending=120,
                    collective_issue=80,
                    collective_bytes_sent=8192,
                    pkt_bytes_sent=8192,
                    credit_stall=32,
                    backpressure_stall=32,
                    inflight_max=4,
                    return_sent=0,
                    return_recv=0,
                    return_orphan=0,
                    return_dup=0,
                    return_latency_total=0,
                    return_latency_max=0,
                )),
                "event_hard": self._write_summary(root, "event_hard", _make_summary(
                    collective_pending=220,
                    collective_issue=64,
                    collective_bytes_sent=6144,
                    pkt_bytes_sent=6144,
                    credit_stall=80,
                    backpressure_stall=80,
                    inflight_max=4,
                    return_sent=0,
                    return_recv=0,
                    return_orphan=0,
                    return_dup=0,
                    return_latency_total=0,
                    return_latency_max=0,
                )),
                "event_soft": self._write_summary(root, "event_soft", common),
                "event_payload_first": self._write_summary(root, "event_payload_first", _make_summary(
                    collective_pending=256,
                    collective_issue=0,
                    collective_bytes_sent=0,
                    pkt_bytes_sent=4096,
                    credit_stall=32,
                    backpressure_stall=32,
                    inflight_max=2,
                    return_sent=0,
                    return_recv=0,
                    return_orphan=0,
                    return_dup=0,
                    return_latency_total=0,
                    return_latency_max=0,
                )),
                "event_uncapped": self._write_summary(root, "event_uncapped", common),
                "event_stress": self._write_summary(root, "event_stress", _make_summary(
                    collective_pending=320,
                    collective_issue=100,
                    collective_bytes_sent=12288,
                    pkt_bytes_sent=12288,
                    credit_stall=96,
                    backpressure_stall=96,
                    inflight_max=8,
                    return_sent=320,
                    return_recv=320,
                    return_orphan=0,
                    return_dup=0,
                    return_latency_total=3200,
                    return_latency_max=16,
                )),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("credit-return packet activity", out.stdout)


if __name__ == "__main__":
    unittest.main()
