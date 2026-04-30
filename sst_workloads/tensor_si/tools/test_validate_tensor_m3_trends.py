#!/usr/bin/env python3
"""Unit tests for validate_tensor_m3_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m3_trends.py"


def _make_summary(
    *,
    onchip_capacity_stall: int,
    onchip_port_stall: int,
    spill_budget_stall: int,
    spill_bytes: int,
    collective_pending: int,
    collective_issue: int,
    collective_bytes_sent: int,
    pkt_bytes_sent: int,
    collective_algo_id: int,
    ring_chunks: int,
    ring_steps: int,
    reduce_wait_cycles: int,
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
            "tensor_stall_onchip_capacity_cycles_total": onchip_capacity_stall,
            "tensor_stall_onchip_port_cycles_total": onchip_port_stall,
            "tensor_stall_spill_budget_cycles_total": spill_budget_stall,
            "tensor_spill_bytes_total": spill_bytes,
            "tensor_collective_chunk_groups_total": ring_chunks,
            "tensor_collective_ring_steps_total": ring_steps,
            "tensor_collective_reduce_wait_cycles_total": reduce_wait_cycles,
            "tensor_collective_algo_id": collective_algo_id,
            "tensor_collective_bytes_sent_total": collective_bytes_sent,
            "tensor_pkt_bytes_sent_total": pkt_bytes_sent,
        },
    }


class ValidateTensorM3TrendsTest(unittest.TestCase):
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
                        onchip_capacity_stall=0,
                        onchip_port_stall=0,
                        spill_budget_stall=0,
                        spill_bytes=0,
                        collective_pending=0,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=0,
                        collective_algo_id=0,
                        ring_chunks=0,
                        ring_steps=0,
                        reduce_wait_cycles=0,
                    ),
                ),
                "onchip_capacity_nospill": self._write_summary(
                    root,
                    "onchip_capacity_nospill",
                    _make_summary(
                        onchip_capacity_stall=120,
                        onchip_port_stall=4,
                        spill_budget_stall=0,
                        spill_bytes=0,
                        collective_pending=0,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=0,
                        collective_algo_id=0,
                        ring_chunks=0,
                        ring_steps=0,
                        reduce_wait_cycles=0,
                    ),
                ),
                "onchip_capacity_spill": self._write_summary(
                    root,
                    "onchip_capacity_spill",
                    _make_summary(
                        onchip_capacity_stall=12,
                        onchip_port_stall=8,
                        spill_budget_stall=0,
                        spill_bytes=16384,
                        collective_pending=0,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=0,
                        collective_algo_id=0,
                        ring_chunks=0,
                        ring_steps=0,
                        reduce_wait_cycles=0,
                    ),
                ),
                "ring_chunked": self._write_summary(
                    root,
                    "ring_chunked",
                    _make_summary(
                        onchip_capacity_stall=0,
                        onchip_port_stall=0,
                        spill_budget_stall=0,
                        spill_bytes=0,
                        collective_pending=128,
                        collective_issue=64,
                        collective_bytes_sent=8192,
                        pkt_bytes_sent=8192,
                        collective_algo_id=1,
                        ring_chunks=16,
                        ring_steps=96,
                        reduce_wait_cycles=0,
                    ),
                ),
                "ring_chunked_reduce_wait": self._write_summary(
                    root,
                    "ring_chunked_reduce_wait",
                    _make_summary(
                        onchip_capacity_stall=0,
                        onchip_port_stall=0,
                        spill_budget_stall=0,
                        spill_bytes=0,
                        collective_pending=156,
                        collective_issue=64,
                        collective_bytes_sent=8192,
                        pkt_bytes_sent=8192,
                        collective_algo_id=1,
                        ring_chunks=16,
                        ring_steps=96,
                        reduce_wait_cycles=32,
                    ),
                ),
                "ring_chunked_payload_first": self._write_summary(
                    root,
                    "ring_chunked_payload_first",
                    _make_summary(
                        onchip_capacity_stall=0,
                        onchip_port_stall=0,
                        spill_budget_stall=0,
                        spill_bytes=0,
                        collective_pending=256,
                        collective_issue=0,
                        collective_bytes_sent=0,
                        pkt_bytes_sent=4096,
                        collective_algo_id=1,
                        ring_chunks=16,
                        ring_steps=96,
                        reduce_wait_cycles=0,
                    ),
                ),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m3] PASS", out.stdout)

    def test_fail_when_ring_algo_id_is_wrong(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            common = {
                "onchip_capacity_stall": 10,
                "onchip_port_stall": 0,
                "spill_budget_stall": 0,
                "spill_bytes": 4096,
                "collective_pending": 10,
                "collective_issue": 1,
                "collective_bytes_sent": 1024,
                "pkt_bytes_sent": 1024,
                "collective_algo_id": 1,
                "ring_chunks": 2,
                "ring_steps": 4,
                "reduce_wait_cycles": 1,
            }
            paths = {
                "baseline_compat": self._write_summary(root, "baseline_compat", _make_summary(**common)),
                "onchip_capacity_nospill": self._write_summary(
                    root, "onchip_capacity_nospill", _make_summary(**{**common, "spill_bytes": 0, "onchip_capacity_stall": 100})
                ),
                "onchip_capacity_spill": self._write_summary(root, "onchip_capacity_spill", _make_summary(**common)),
                "ring_chunked": self._write_summary(
                    root, "ring_chunked", _make_summary(**{**common, "collective_algo_id": 0})
                ),
                "ring_chunked_reduce_wait": self._write_summary(root, "ring_chunked_reduce_wait", _make_summary(**common)),
                "ring_chunked_payload_first": self._write_summary(
                    root,
                    "ring_chunked_payload_first",
                    _make_summary(**{**common, "collective_issue": 0, "collective_bytes_sent": 0, "pkt_bytes_sent": 2048}),
                ),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("algo_id", out.stdout)


if __name__ == "__main__":
    unittest.main()
