#!/usr/bin/env python3
"""Unit tests for validate_tensor_m10_pkts_alias.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m10_pkts_alias.py"


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_summary(*, run_dir: str, tensor: Dict[str, object]) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "artifacts": {"mesh_stats_csv": str(Path(run_dir) / "mesh_stats.csv")},
        "sim_time_ns": 50000,
        "tensor": dict(tensor),
    }


class ValidateTensorM10PktsAliasTest(unittest.TestCase):
    def _run(self, **kwargs: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(SCRIPT)]
        for key, value in kwargs.items():
            cmd.extend([f"--{key.replace('_', '-')}", value])
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_pass_when_alias_folded_to_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_chunks = root / "run_chunks"
            run_pkts = root / "run_pkts"
            run_chunks.mkdir(parents=True)
            run_pkts.mkdir(parents=True)

            eff_cfg = {
                "node_limit": 4,
                "mesh_cfg": {"num_cores_per_pe": 4},
                "tensor_cfg": {
                    "tensor_collective_credit_enable": 1,
                    "tensor_collective_max_inflight_chunks": 8,
                    "tensor_collective_credit_window_chunks": 1,
                }
            }
            _write_json(run_chunks / "effective_config.json", eff_cfg)
            _write_json(run_pkts / "effective_config.json", eff_cfg)

            sum_chunks = root / "chunks.json"
            sum_pkts = root / "pkts.json"
            _write_json(
                sum_chunks,
                _make_summary(
                    run_dir=str(run_chunks),
                    tensor={"tensor_collective_inflight_chunks_max": 1, "tensor_collective_credit_stall_cycles_total": 0},
                ),
            )
            _write_json(
                sum_pkts,
                _make_summary(
                    run_dir=str(run_pkts),
                    tensor={"tensor_collective_inflight_chunks_max": 1, "tensor_collective_credit_stall_cycles_total": 1},
                ),
            )

            out = self._run(chunks=str(sum_chunks), pkts_alias=str(sum_pkts))
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m10] PASS", out.stdout)

    def test_fail_when_effective_config_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_chunks = root / "run_chunks"
            run_pkts = root / "run_pkts"
            run_chunks.mkdir(parents=True)
            run_pkts.mkdir(parents=True)
            # Only one has config.
            _write_json(
                run_chunks / "effective_config.json",
                {
                    "node_limit": 4,
                    "mesh_cfg": {"num_cores_per_pe": 4},
                    "tensor_cfg": {
                        "tensor_collective_credit_enable": 1,
                        "tensor_collective_max_inflight_chunks": 8,
                        "tensor_collective_credit_window_chunks": 1,
                    }
                },
            )

            sum_chunks = root / "chunks.json"
            sum_pkts = root / "pkts.json"
            _write_json(
                sum_chunks,
                _make_summary(
                    run_dir=str(run_chunks),
                    tensor={"tensor_collective_inflight_chunks_max": 1, "tensor_collective_credit_stall_cycles_total": 0},
                ),
            )
            _write_json(
                sum_pkts,
                _make_summary(
                    run_dir=str(run_pkts),
                    tensor={"tensor_collective_inflight_chunks_max": 1, "tensor_collective_credit_stall_cycles_total": 1},
                ),
            )

            out = self._run(chunks=str(sum_chunks), pkts_alias=str(sum_pkts))
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("effective_config.json", out.stdout)


if __name__ == "__main__":
    unittest.main()
