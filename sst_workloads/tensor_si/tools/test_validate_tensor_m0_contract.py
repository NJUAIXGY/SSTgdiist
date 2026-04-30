#!/usr/bin/env python3
"""Unit tests for validate_tensor_m0_contract.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m0_contract.py"


def _make_summary(run_dir: Path, *, collective_sent: int = 0) -> Dict[str, object]:
    tensor = {
        "tensor_mem_reads_issued_total": 1,
        "tensor_mem_bytes_read_total": 64,
        "tensor_compute_cycles_total": 1,
        "tensor_mac_ops_total": 1024,
        "tensor_dma_cycles_total": 0,
        "tensor_dma_stall_cycles_total": 0,
        "tensor_stall_dma_budget_cycles_total": 0,
        "tensor_stall_mem_outstanding_cycles_total": 0,
        "tensor_stall_wait_read_cycles_total": 0,
        "tensor_collective_bytes_sent_total": collective_sent,
        "tensor_pkt_bytes_sent_total": 0,
        "tensor_collective_bytes_recv_total": 0,
        "tensor_collective_pkts_sent_total": 0,
        "tensor_collective_pkts_recv_total": 0,
        "tensor_collective_cycles_total": 0,
    }
    return {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "artifacts": {"mesh_stats_csv": str(run_dir / "mesh_stats.csv")},
        "sim_time_ns": 1000,
        "tensor": tensor,
    }


class ValidateTensorM0ContractTest(unittest.TestCase):
    def _prepare_run_dir(self, td: str, *, tile: bool = False, collective: bool = False) -> Path:
        run_dir = Path(td) / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "mesh_stats.csv").write_text("ComponentName,StatisticName,Sum.u64\n", encoding="utf-8")
        (run_dir / "tensor_mesh_run.log").write_text("ok\n", encoding="utf-8")
        (run_dir / "time.txt").write_text("ok\n", encoding="utf-8")
        (run_dir / "validation.log").write_text("[tensor_mesh] PASS\n", encoding="utf-8")
        summary = _make_summary(run_dir, collective_sent=1024 if collective else 0)
        (run_dir / "essential_summary_tensor_mesh.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tensor_cfg = {
            "workload_impl": "tensor",
            "tensor_exec_mode": "tile" if tile else "bulk",
            "tensor_tile_m": 64 if tile else 0,
            "tensor_tile_n": 64 if tile else 0,
            "tensor_tile_k": 64 if tile else 0,
            "tensor_collective_type": "allreduce" if collective else "none",
        }
        (run_dir / "effective_config.json").write_text(
            json.dumps({"tensor_cfg": tensor_cfg}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return run_dir

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(SCRIPT), *args]
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_contract_pass_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = self._prepare_run_dir(td)
            out = self._run("--run-dir", str(run_dir), "--scenario", "s0")
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)

    def test_contract_requires_collective_activity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = self._prepare_run_dir(td, collective=False)
            out = self._run("--run-dir", str(run_dir), "--scenario", "s2", "--expect-collective")
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("collective", out.stdout)

    def test_contract_requires_tile_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = self._prepare_run_dir(td, tile=False)
            out = self._run("--run-dir", str(run_dir), "--scenario", "s1", "--expect-tile")
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("tile", out.stdout)

    def test_contract_fails_when_metric_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = self._prepare_run_dir(td)
            summary_path = run_dir / "essential_summary_tensor_mesh.json"
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            tensor = payload.get("tensor", {})
            if isinstance(tensor, dict):
                tensor.pop("tensor_dma_cycles_total", None)
            summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            out = self._run("--run-dir", str(run_dir), "--scenario", "s0")
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("missing tensor metric", out.stdout)

    def test_contract_allow_zero_mac_ops(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = self._prepare_run_dir(td, collective=True)
            summary_path = run_dir / "essential_summary_tensor_mesh.json"
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            tensor = payload.get("tensor", {})
            if isinstance(tensor, dict):
                tensor["tensor_mac_ops_total"] = 0
                tensor["tensor_compute_cycles_total"] = 0
            summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            out = self._run("--run-dir", str(run_dir), "--scenario", "s2", "--expect-collective")
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("tensor_mac_ops_total", out.stdout)

            out2 = self._run(
                "--run-dir",
                str(run_dir),
                "--scenario",
                "s2",
                "--expect-collective",
                "--allow-zero-mac",
            )
            self.assertEqual(out2.returncode, 0, msg=out2.stdout + out2.stderr)


if __name__ == "__main__":
    unittest.main()
