#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


class ComputeEssentialSummarySinglepeCLITest(unittest.TestCase):
    def _run_summary(self, run_dir: Path) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("compute_essential_summary_singlepe.py")
        return subprocess.run(
            ["python3", str(script), "--run-dir", str(run_dir)],
            text=True,
            capture_output=True,
        )

    def test_prefers_effective_config_and_surfaces_runtime_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_json(
                run_dir / "local_run_config.json",
                {
                    "sim_time": "5us",
                    "num_cores_per_pe": 1,
                    "neurons_per_core": 2,
                    "mem_backend": "simple",
                    "mc_mem_size": "64MiB",
                    "dataset_path": "datasets/raw.txt",
                },
            )
            _write_json(
                run_dir / "local_run_config.effective.json",
                {
                    "sim_time": "7us",
                    "num_cores_per_pe": 3,
                    "neurons_per_core": 4,
                    "mem_backend": "ramulator2",
                    "ramulator2_config_file": "/abs/ramulator.cfg",
                    "mc_mem_size": "383MiB",
                    "mc_mem_size_configured": "64MiB",
                    "mc_mem_size_configured_bytes": 64 * 1024 * 1024,
                    "mc_mem_size_effective": "383MiB",
                    "mc_mem_size_effective_bytes": 383 * 1024 * 1024,
                    "mc_mem_size_auto_expanded": 1,
                    "dataset_path": "/abs/resolved.txt",
                    "dataset_path_configured": "datasets/raw.txt",
                },
            )
            (run_dir / "last_run.time").write_text("real 1.23\nuser 1.00\nsys 0.20\n", encoding="utf-8")

            proc = self._run_summary(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["model"]["sim_time"], "7us")
            self.assertEqual(summary["model"]["cores_per_pe"], 3)
            self.assertEqual(summary["model"]["neurons_per_core"], 4)
            self.assertEqual(summary["runtime_config"]["mem_backend"], "ramulator2")
            self.assertEqual(summary["runtime_config"]["ramulator2_config_file"], "/abs/ramulator.cfg")
            self.assertEqual(summary["runtime_config"]["mc_mem_size"]["configured"], "64MiB")
            self.assertEqual(summary["runtime_config"]["mc_mem_size"]["effective"], "383MiB")
            self.assertEqual(summary["runtime_config"]["mc_mem_size"]["effective_bytes"], 383 * 1024 * 1024)
            self.assertTrue(summary["runtime_config"]["mc_mem_size"]["auto_expanded"])
            self.assertEqual(summary["runtime_config"]["dataset_path"]["configured"], "datasets/raw.txt")
            self.assertEqual(summary["runtime_config"]["dataset_path"]["effective"], "/abs/resolved.txt")
            self.assertEqual(summary["inputs"]["local_run_config"], "local_run_config.json")
            self.assertEqual(summary["inputs"]["local_run_config_effective"], "local_run_config.effective.json")

    def test_falls_back_to_raw_config_when_effective_snapshot_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_json(
                run_dir / "local_run_config.json",
                {
                    "sim_time": "9us",
                    "num_cores_per_pe": 2,
                    "neurons_per_core": 5,
                    "mem_backend": "simple",
                    "mc_mem_size": "128MiB",
                    "dataset_path": "datasets/raw_only.txt",
                },
            )

            proc = self._run_summary(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["model"]["sim_time"], "9us")
            self.assertEqual(summary["runtime_config"]["mem_backend"], "simple")
            self.assertEqual(summary["runtime_config"]["mc_mem_size"]["configured"], "128MiB")
            self.assertEqual(summary["runtime_config"]["mc_mem_size"]["effective"], "128MiB")
            self.assertFalse(summary["runtime_config"]["mc_mem_size"]["auto_expanded"])
            self.assertEqual(summary["runtime_config"]["dataset_path"]["configured"], "datasets/raw_only.txt")
            self.assertEqual(summary["runtime_config"]["dataset_path"]["effective"], "datasets/raw_only.txt")

    def test_keeps_dataset_configured_null_when_only_effective_path_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_json(
                run_dir / "local_run_config.json",
                {
                    "sim_time": "11us",
                    "num_cores_per_pe": 1,
                    "neurons_per_core": 1,
                },
            )
            _write_json(
                run_dir / "local_run_config.effective.json",
                {
                    "sim_time": "11us",
                    "num_cores_per_pe": 1,
                    "neurons_per_core": 1,
                    "dataset_path": "/abs/resolved_only.txt",
                    "dataset_path_configured": None,
                },
            )

            proc = self._run_summary(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary.json").read_text(encoding="utf-8"))
            self.assertIsNone(summary["runtime_config"]["dataset_path"]["configured"])
            self.assertEqual(summary["runtime_config"]["dataset_path"]["effective"], "/abs/resolved_only.txt")


if __name__ == "__main__":
    unittest.main()
