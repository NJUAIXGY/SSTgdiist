#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m17_mapping_contract.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m17_mapping_contract.py"


class ValidateTensorM17MappingContractTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mapping = {
                "platform": {"mesh_size": 2, "simulation_time": "1us"},
                "tensor_params": {"tensor_exec_mode": "program", "tensor_iterations": 1},
                "program": {"loop": False, "ops": [{"op_type": "gemm"}, {"op_type": "gemm"}]},
            }
            spec = {
                "schema_version": 3,
                "model": "tensor",
                "platform": {"mesh_size": 2, "stop": {"mode": "time", "simulation_time": "1us"}},
                "noc": {"type": "merlin_mesh", "params": {}},
                "memory": {"type": "shared", "backend": {"type": "simple"}, "params": {}},
                "pe": {"cores_per_pe": 4, "neurons_per_core": 4},
                "workload": {
                    "type": "tensor",
                    "stats_modules": "tensor",
                    "params": {"tensor_exec_mode": "program", "tensor_iterations": 1},
                    "program": {"loop": False, "ops": [{"op_type": "gemm"}, {"op_type": "gemm"}]},
                },
            }
            summary = {
                "schema_version": 1,
                "run_dir": str(root),
                "tensor": {"tensor_program_iters_total": 1, "tensor_program_ops_total": 2},
            }
            mp = root / "mapping.json"
            sp = root / "spec.json"
            su = root / "summary.json"
            mp.write_text(json.dumps(mapping), encoding="utf-8")
            sp.write_text(json.dumps(spec), encoding="utf-8")
            su.write_text(json.dumps(summary), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--mapping",
                str(mp),
                "--spec",
                str(sp),
                "--summary",
                str(su),
                "--label",
                "x",
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m17:x]", out.stdout)

    def test_fails_on_empty_ops(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mp = root / "mapping.json"
            sp = root / "spec.json"
            su = root / "summary.json"
            mp.write_text(json.dumps({"program": {"ops": []}}), encoding="utf-8")
            sp.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "model": "tensor",
                        "workload": {
                            "type": "tensor",
                            "params": {"tensor_exec_mode": "program"},
                            "program": {"ops": []},
                        },
                    }
                ),
                encoding="utf-8",
            )
            su.write_text(json.dumps({"tensor": {"tensor_program_iters_total": 1, "tensor_program_ops_total": 1}}), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--mapping", str(mp), "--spec", str(sp), "--summary", str(su)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("mapping.program.ops", out.stderr)


if __name__ == "__main__":
    unittest.main()

