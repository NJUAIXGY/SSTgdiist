#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_summary(run_dir: Path, *, req_total: float, line_groups_p95: float, older_wait_max_p95: float,
                   depth_avg_p99: float, depth_max_p95: float, global_steps_done: int = 2,
                   windows_incomplete: int = 0, materialization_ratio: float = 1.0,
                   retire_drain_ratio: float = 1.0) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    obj = {
        "gas": {
            "global_steps_done": global_steps_done,
            "windows_incomplete": windows_incomplete,
        },
        "memhierarchy": {
            "memctrl": {
                "req_total": req_total,
            }
        },
        "retire_hol_attribution_core": {
            "frontend_ordering": {
                "completion_state": {
                    "materialization_ratio": materialization_ratio,
                    "retire_drain_ratio": retire_drain_ratio,
                },
                "older_head_wait": {
                    "window_wait_cycles_max_p95": older_wait_max_p95,
                },
                "younger_ahead_depth": {
                    "window_depth_avg_p99": depth_avg_p99,
                    "window_depth_max_p95": depth_max_p95,
                },
                "queue_shape": {
                    "window_line_groups_per_prepare_p95": line_groups_p95,
                },
            }
        },
    }
    (run_dir / "essential_summary_mesh.json").write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class CompareEssentialSummaryMeshTest(unittest.TestCase):
    def _run_gate(self, base_run: Path, cand_run: Path) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("compare_essential_summary_mesh.py")
        return subprocess.run(
            [
                "python3",
                str(script),
                "--a",
                str(base_run),
                "--b",
                str(cand_run),
                "--gate-profile",
                "offline_antiburial_tail",
            ],
            text=True,
            capture_output=True,
        )

    def test_offline_antiburial_tail_gate_passes_for_improving_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            base_run = td_path / "baseline"
            cand_run = td_path / "candidate"
            _write_summary(
                base_run,
                req_total=397207.0,
                line_groups_p95=812.05,
                older_wait_max_p95=252911.35,
                depth_avg_p99=1055.66,
                depth_max_p95=2311.10,
            )
            _write_summary(
                cand_run,
                req_total=309905.0,
                line_groups_p95=533.0,
                older_wait_max_p95=229311.0,
                depth_avg_p99=1082.84,
                depth_max_p95=2300.0,
            )

            proc = self._run_gate(base_run, cand_run)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("PASS tail.depth_tail_or", proc.stdout)

    def test_offline_antiburial_tail_gate_fails_when_depth_tail_and_wait_regress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            base_run = td_path / "baseline"
            cand_run = td_path / "candidate"
            _write_summary(
                base_run,
                req_total=397207.0,
                line_groups_p95=812.05,
                older_wait_max_p95=252911.35,
                depth_avg_p99=1055.66,
                depth_max_p95=2311.10,
            )
            _write_summary(
                cand_run,
                req_total=309905.0,
                line_groups_p95=533.0,
                older_wait_max_p95=260000.0,
                depth_avg_p99=1082.84,
                depth_max_p95=2340.15,
            )

            proc = self._run_gate(base_run, cand_run)
            self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
            self.assertIn("FAIL tail.depth_tail_or", proc.stdout)
            self.assertIn("FAIL tail.older_wait_max_p95", proc.stdout)


if __name__ == "__main__":
    unittest.main()
