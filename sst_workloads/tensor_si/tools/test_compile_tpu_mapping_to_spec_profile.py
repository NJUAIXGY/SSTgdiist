#!/usr/bin/env python3
"""Unit tests for compile_tpu_mapping_to_spec.py profile defaults."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "compile_tpu_mapping_to_spec.py"


class CompileTpuMappingToSpecProfileTest(unittest.TestCase):
    def _write_mapping(self, path: Path, mapping: dict) -> None:
        path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")

    def test_profile_tpuv3_applies_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            mapping_path = td_path / "mapping.json"
            out_path = td_path / "spec.json"

            # Minimal runnable mapping: program ops only.
            mapping = {
                "platform": {"mesh_size": 1, "simulation_time": "5us"},
                "program": {"loop": False, "ops": [{"op_type": "gemm"}]},
                "tensor_params": {},
            }
            self._write_mapping(mapping_path, mapping)

            cmd = [
                sys.executable,
                str(SCRIPT),
                "--profile",
                "tpuv3",
                "--mapping",
                str(mapping_path),
                "--out",
                str(out_path),
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)

            spec = json.loads(out_path.read_text(encoding="utf-8"))
            wl = spec.get("workload", {})
            self.assertIsInstance(wl, dict)
            params = wl.get("params", {})
            self.assertIsInstance(params, dict)
            self.assertEqual(int(params.get("tensor_array_m", 0)), 128)
            self.assertEqual(int(params.get("tensor_array_n", 0)), 128)
            self.assertEqual(str(params.get("tensor_compute_precision", "")), "bf16")
            self.assertEqual(int(params.get("tensor_ub_bytes", 0)), 256 * 1024)
            self.assertEqual(int(params.get("tensor_acc_bytes", 0)), 256 * 1024)
            self.assertEqual(int(params.get("tensor_onchip_model_enable", 0)), 1)

    def test_profile_tpuv3_respects_mapping_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            mapping_path = td_path / "mapping.json"
            out_path = td_path / "spec.json"

            mapping = {
                "profile": "tpuv3",
                "platform": {"mesh_size": 1, "simulation_time": "5us"},
                "program": {"loop": False, "ops": [{"op_type": "gemm"}]},
                "tensor_params": {"tensor_array_m": 64, "tensor_compute_precision": "int8"},
            }
            self._write_mapping(mapping_path, mapping)

            cmd = [sys.executable, str(SCRIPT), "--mapping", str(mapping_path), "--out", str(out_path)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)

            spec = json.loads(out_path.read_text(encoding="utf-8"))
            params = (spec.get("workload", {}) or {}).get("params", {})
            self.assertIsInstance(params, dict)
            self.assertEqual(int(params.get("tensor_array_m", 0)), 64)
            self.assertEqual(str(params.get("tensor_compute_precision", "")), "int8")


if __name__ == "__main__":
    unittest.main()

