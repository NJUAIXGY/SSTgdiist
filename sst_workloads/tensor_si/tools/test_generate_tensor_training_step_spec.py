#!/usr/bin/env python3
"""Unit tests for generate_tensor_training_step_spec.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "generate_tensor_training_step_spec.py"


class GenerateTensorTrainingStepSpecTest(unittest.TestCase):
    def test_generates_valid_json_to_out_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "spec.json"
            cmd = [sys.executable, str(SCRIPT), "--out", str(out_path)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(int(payload.get("schema_version", 0)), 3)
            self.assertEqual(str(payload.get("model", "")), "tensor")

            wl = payload.get("workload", {})
            self.assertIsInstance(wl, dict)
            program = wl.get("program", {})
            self.assertIsInstance(program, dict)
            ops = program.get("ops", [])
            self.assertIsInstance(ops, list)
            self.assertEqual(len(ops), 2)
            self.assertEqual(str(ops[0].get("op_type")), "gemm")
            self.assertEqual(str(ops[1].get("op_type")), "allreduce")
            self.assertGreater(int(ops[1].get("bytes", 0)), 0)

            params = wl.get("params", {})
            self.assertIsInstance(params, dict)
            # Generator uses *_pkts aliases (folded during resolve_spec).
            self.assertIn("tensor_collective_max_inflight_pkts", params)
            self.assertIn("tensor_collective_credit_window_pkts", params)

    def test_explicit_dma_emits_m7_ops(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "spec.json"
            cmd = [sys.executable, str(SCRIPT), "--explicit-dma", "--out", str(out_path)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            wl = payload.get("workload", {})
            self.assertIsInstance(wl, dict)
            program = wl.get("program", {})
            self.assertIsInstance(program, dict)
            ops = program.get("ops", [])
            self.assertIsInstance(ops, list)
            self.assertEqual(len(ops), 6)
            self.assertEqual(str(ops[0].get("op_type")), "dma_read")
            self.assertEqual(str(ops[1].get("op_type")), "dma_read")
            self.assertEqual(str(ops[2].get("op_type")), "gemm_ub")
            self.assertGreater(int(ops[2].get("cycles", 0)), 0)
            self.assertIn("ub_read_bytes", ops[2])
            self.assertIn("ub_write_bytes", ops[2])
            self.assertEqual(str(ops[-1].get("op_type")), "allreduce")

    def test_profile_tpuv3_applies_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "spec.json"
            cmd = [sys.executable, str(SCRIPT), "--profile", "tpuv3", "--out", str(out_path)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            wl = payload.get("workload", {})
            self.assertIsInstance(wl, dict)
            params = wl.get("params", {})
            self.assertIsInstance(params, dict)

            self.assertEqual(int(params.get("tensor_array_m", 0)), 128)
            self.assertEqual(int(params.get("tensor_array_n", 0)), 128)
            self.assertEqual(str(params.get("tensor_compute_precision", "")), "bf16")
            self.assertEqual(int(params.get("tensor_ub_bytes", 0)), 256 * 1024)
            self.assertEqual(int(params.get("tensor_acc_bytes", 0)), 256 * 1024)
            self.assertEqual(int(params.get("tensor_onchip_model_enable", 0)), 1)
            self.assertEqual(int(params.get("tensor_mem_req_bytes", 0)), 256)
            self.assertEqual(int(params.get("tensor_mem_max_outstanding", 0)), 64)
            self.assertEqual(int(params.get("tensor_dma_bandwidth_bytes_per_cycle", 0)), 1024)

    def test_profile_tpuv3_respects_explicit_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "spec.json"
            cmd = [
                sys.executable,
                str(SCRIPT),
                "--profile",
                "tpuv3",
                "--array-m",
                "64",
                "--compute-precision",
                "int8",
                "--out",
                str(out_path),
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stdout + out.stderr)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            params = (payload.get("workload", {}) or {}).get("params", {})
            self.assertIsInstance(params, dict)
            self.assertEqual(int(params.get("tensor_array_m", 0)), 64)
            self.assertEqual(str(params.get("tensor_compute_precision", "")), "int8")


if __name__ == "__main__":
    unittest.main()
