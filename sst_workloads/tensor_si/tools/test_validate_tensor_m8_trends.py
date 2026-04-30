#!/usr/bin/env python3
"""Unit tests for validate_tensor_m8_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m8_trends.py"


def _make_summary(*, tensor: Dict[str, object]) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 50000,
        "tensor": dict(tensor),
    }


class ValidateTensorM8TrendsTest(unittest.TestCase):
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

            ring = self._write_summary(
                root,
                "ring",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 1,
                        "tensor_collective_ring_steps_total": 480,
                        "tensor_collective_chunk_groups_total": 16,
                        "tensor_collective_bytes_sent_total": 123456,
                        "tensor_collective_credit_stall_cycles_total": 100,
                        # 2D attribution should be zero in ring baseline.
                        "tensor_collective_2d_row_rs_steps_total": 0,
                        "tensor_collective_2d_col_rs_steps_total": 0,
                        "tensor_collective_2d_col_ag_steps_total": 0,
                        "tensor_collective_2d_row_ag_steps_total": 0,
                    }
                ),
            )

            torus_2d = self._write_summary(
                root,
                "torus_2d",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 2,
                        "tensor_collective_2d_dim_x": 2,
                        "tensor_collective_2d_dim_y": 8,
                        "tensor_collective_chunk_groups_total": 16,
                        "tensor_collective_ring_steps_total": 256,
                        "tensor_collective_bytes_sent_total": 16000,
                        "tensor_collective_2d_row_rs_steps_total": 16,
                        "tensor_collective_2d_col_rs_steps_total": 112,
                        "tensor_collective_2d_col_ag_steps_total": 112,
                        "tensor_collective_2d_row_ag_steps_total": 16,
                        "tensor_collective_2d_row_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_ag_bytes_sent_total": 4000,
                        "tensor_collective_2d_row_ag_bytes_sent_total": 4000,
                        "tensor_collective_credit_stall_cycles_total": 50,
                    }
                ),
            )

            chunk64k = self._write_summary(
                root,
                "chunk64k",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 2,
                        "tensor_collective_2d_dim_x": 2,
                        "tensor_collective_2d_dim_y": 8,
                        "tensor_collective_chunk_groups_total": 1,
                        "tensor_collective_ring_steps_total": 16,
                        "tensor_collective_bytes_sent_total": 16000,
                        "tensor_collective_2d_row_rs_steps_total": 1,
                        "tensor_collective_2d_col_rs_steps_total": 7,
                        "tensor_collective_2d_col_ag_steps_total": 7,
                        "tensor_collective_2d_row_ag_steps_total": 1,
                        "tensor_collective_2d_row_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_ag_bytes_sent_total": 4000,
                        "tensor_collective_2d_row_ag_bytes_sent_total": 4000,
                        "tensor_collective_credit_stall_cycles_total": 10,
                    }
                ),
            )

            inflight4 = self._write_summary(
                root,
                "inflight4",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 2,
                        "tensor_collective_2d_dim_x": 2,
                        "tensor_collective_2d_dim_y": 8,
                        "tensor_collective_chunk_groups_total": 16,
                        "tensor_collective_ring_steps_total": 256,
                        "tensor_collective_bytes_sent_total": 16000,
                        "tensor_collective_2d_row_rs_steps_total": 16,
                        "tensor_collective_2d_col_rs_steps_total": 112,
                        "tensor_collective_2d_col_ag_steps_total": 112,
                        "tensor_collective_2d_row_ag_steps_total": 16,
                        "tensor_collective_2d_row_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_ag_bytes_sent_total": 4000,
                        "tensor_collective_2d_row_ag_bytes_sent_total": 4000,
                        "tensor_collective_credit_stall_cycles_total": 30,
                    }
                ),
            )

            out = self._run(
                ring=str(ring),
                torus_2d=str(torus_2d),
                chunk64k=str(chunk64k),
                inflight4=str(inflight4),
            )
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m8] PASS", out.stdout)

    def test_fail_when_stage_steps_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            ring = self._write_summary(
                root,
                "ring",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 1,
                        "tensor_collective_ring_steps_total": 480,
                        "tensor_collective_chunk_groups_total": 16,
                        "tensor_collective_bytes_sent_total": 123456,
                        "tensor_collective_credit_stall_cycles_total": 100,
                        "tensor_collective_2d_row_rs_steps_total": 0,
                    }
                ),
            )

            torus_2d_bad = self._write_summary(
                root,
                "torus_2d_bad",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 2,
                        "tensor_collective_2d_dim_x": 2,
                        "tensor_collective_2d_dim_y": 8,
                        "tensor_collective_chunk_groups_total": 16,
                        "tensor_collective_ring_steps_total": 256,
                        "tensor_collective_bytes_sent_total": 16000,
                        # wrong: row_rs should be 16
                        "tensor_collective_2d_row_rs_steps_total": 15,
                        "tensor_collective_2d_col_rs_steps_total": 112,
                        "tensor_collective_2d_col_ag_steps_total": 112,
                        "tensor_collective_2d_row_ag_steps_total": 16,
                        "tensor_collective_2d_row_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_ag_bytes_sent_total": 4000,
                        "tensor_collective_2d_row_ag_bytes_sent_total": 4000,
                        "tensor_collective_credit_stall_cycles_total": 50,
                    }
                ),
            )

            chunk64k = self._write_summary(
                root,
                "chunk64k",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 2,
                        "tensor_collective_2d_dim_x": 2,
                        "tensor_collective_2d_dim_y": 8,
                        "tensor_collective_chunk_groups_total": 1,
                        "tensor_collective_ring_steps_total": 16,
                        "tensor_collective_bytes_sent_total": 16000,
                        "tensor_collective_2d_row_rs_steps_total": 1,
                        "tensor_collective_2d_col_rs_steps_total": 7,
                        "tensor_collective_2d_col_ag_steps_total": 7,
                        "tensor_collective_2d_row_ag_steps_total": 1,
                        "tensor_collective_2d_row_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_ag_bytes_sent_total": 4000,
                        "tensor_collective_2d_row_ag_bytes_sent_total": 4000,
                        "tensor_collective_credit_stall_cycles_total": 10,
                    }
                ),
            )

            inflight4 = self._write_summary(
                root,
                "inflight4",
                _make_summary(
                    tensor={
                        "tensor_collective_algo_id": 2,
                        "tensor_collective_2d_dim_x": 2,
                        "tensor_collective_2d_dim_y": 8,
                        "tensor_collective_chunk_groups_total": 16,
                        "tensor_collective_ring_steps_total": 256,
                        "tensor_collective_bytes_sent_total": 16000,
                        "tensor_collective_2d_row_rs_steps_total": 16,
                        "tensor_collective_2d_col_rs_steps_total": 112,
                        "tensor_collective_2d_col_ag_steps_total": 112,
                        "tensor_collective_2d_row_ag_steps_total": 16,
                        "tensor_collective_2d_row_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_rs_bytes_sent_total": 4000,
                        "tensor_collective_2d_col_ag_bytes_sent_total": 4000,
                        "tensor_collective_2d_row_ag_bytes_sent_total": 4000,
                        "tensor_collective_credit_stall_cycles_total": 30,
                    }
                ),
            )

            out = self._run(
                ring=str(ring),
                torus_2d=str(torus_2d_bad),
                chunk64k=str(chunk64k),
                inflight4=str(inflight4),
            )
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("row_rs_steps", out.stdout)


if __name__ == "__main__":
    unittest.main()

