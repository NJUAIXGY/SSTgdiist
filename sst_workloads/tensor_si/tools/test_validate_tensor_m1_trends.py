#!/usr/bin/env python3
"""Unit tests for validate_tensor_m1_trends.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m1_trends.py"


def _make_summary(precision: str, eff: float) -> Dict[str, object]:
    math_cycles = 100
    mac_ops = int(round(eff * math_cycles))
    precision_ids = {"fp16": 0, "fp32": 2, "int8": 4}
    return {
        "schema_version": 1,
        "run_dir": "/tmp/fake",
        "artifacts": {"mesh_stats_csv": "/tmp/fake/mesh_stats.csv"},
        "sim_time_ns": 5000,
        "tensor": {
            "tensor_compute_cycles_total": 110,
            "tensor_compute_math_cycles_total": math_cycles,
            "tensor_compute_pipeline_cycles_total": 10,
            "tensor_mac_ops_total": mac_ops,
            "tensor_precision_profile_name": precision,
            "tensor_precision_profile_id": precision_ids[precision],
            "tensor_effective_mac_per_cycle_math": float(mac_ops) / float(math_cycles),
        },
    }


class ValidateTensorM1TrendsTest(unittest.TestCase):
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
                "bulk_fp16": self._write_summary(root, "bulk_fp16", _make_summary("fp16", 100.0)),
                "bulk_fp32": self._write_summary(root, "bulk_fp32", _make_summary("fp32", 50.0)),
                "bulk_int8": self._write_summary(root, "bulk_int8", _make_summary("int8", 200.0)),
                "tile_fp16": self._write_summary(root, "tile_fp16", _make_summary("fp16", 100.0)),
                "tile_fp32": self._write_summary(root, "tile_fp32", _make_summary("fp32", 50.0)),
                "tile_int8": self._write_summary(root, "tile_int8", _make_summary("int8", 200.0)),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertIn("[m1] PASS", out.stdout)

    def test_fail_when_trend_broken(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = {
                "bulk_fp16": self._write_summary(root, "bulk_fp16", _make_summary("fp16", 100.0)),
                "bulk_fp32": self._write_summary(root, "bulk_fp32", _make_summary("fp32", 120.0)),
                "bulk_int8": self._write_summary(root, "bulk_int8", _make_summary("int8", 200.0)),
                "tile_fp16": self._write_summary(root, "tile_fp16", _make_summary("fp16", 100.0)),
                "tile_fp32": self._write_summary(root, "tile_fp32", _make_summary("fp32", 50.0)),
                "tile_int8": self._write_summary(root, "tile_int8", _make_summary("int8", 200.0)),
            }
            out = self._run(**{k: str(v) for k, v in paths.items()})
            self.assertEqual(out.returncode, 13, msg=out.stdout + out.stderr)
            self.assertIn("trend mismatch", out.stdout)


if __name__ == "__main__":
    unittest.main()
