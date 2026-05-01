#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI tests for tools/snndl_spec_cli.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
CLI = REPO_ROOT / "tools" / "snndl_spec_cli.py"


class SnndlSpecCliTest(unittest.TestCase):
    def _write_spec(self, directory: Path, payload: dict) -> Path:
        path = directory / "spec.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(CLI), *args]
        return subprocess.run(cmd, text=True, capture_output=True, cwd=str(REPO_ROOT))

    def test_cli_validate_defaults_to_mesh(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(Path(td), {"schema_version": 1})
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("OK", out.stdout)

    def test_cli_validate_accepts_mesh_alias(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(Path(td), {"schema_version": 1, "model": "mesh_template"})
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("OK", out.stdout)

    def test_cli_rejects_invalid_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(Path(td), {"schema_version": 1, "model": "bad"})
            out = self._run_cli("validate", str(spec_path))
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("invalid model", out.stderr)

    def test_cli_validate_tensor_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(
                Path(td),
                {"schema_version": 1, "model": "tensor", "platform": {"mesh_size": 2, "stop": {"simulation_time": "5us"}}},
            )
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("OK", out.stdout)

    def test_cli_tensor_unknown_param_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(
                Path(td),
                {
                    "schema_version": 1,
                    "model": "tensor",
                    "workload": {"tensor": {"params": {"unknown_key": 1}}},
                },
            )
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 2)
            self.assertIn("unknown tensor params", out.stderr)

    def test_v3_requires_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(Path(td), {"schema_version": 3})
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 2)
            self.assertIn("model", out.stderr.lower())

    def test_cli_validate_v3_mesh_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(
                Path(td),
                {
                    "schema_version": 3,
                    "model": "mesh",
                    "platform": {"stop": {"mode": "step_limited", "max_steps": 1}},
                },
            )
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("OK", out.stdout)

    def test_cli_validate_v3_tensor_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(
                Path(td),
                {
                    "schema_version": 3,
                    "model": "tensor",
                    "platform": {"stop": {"mode": "time", "simulation_time": "5us"}},
                },
            )
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("OK", out.stdout)

    def test_repo_tensor_m0_specs_validate(self) -> None:
        spec_paths = [
            REPO_ROOT / "tools" / "specs" / "tensor_m0_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m0_collective_v3.json",
        ]
        for spec_path in spec_paths:
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=f"{spec_path}: {out.stderr}")
            self.assertIn("OK", out.stdout)

    def test_repo_tensor_m1_specs_validate(self) -> None:
        spec_paths = [
            REPO_ROOT / "tools" / "specs" / "tensor_m1_fp16_bulk_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m1_fp32_bulk_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m1_int8_bulk_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m1_fp16_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m1_fp32_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m1_int8_tile_v3.json",
        ]
        for spec_path in spec_paths:
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=f"{spec_path}: {out.stderr}")
            self.assertIn("OK", out.stdout)

    def test_repo_tensor_m2_specs_validate(self) -> None:
        spec_paths = [
            REPO_ROOT / "tools" / "specs" / "tensor_m2_baseline_compat_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m2_noc_capped_overlap_on_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m2_noc_capped_overlap_off_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m2_noc_capped_heavy_collective_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m2_noc_capped_payload_first_tile_v3.json",
        ]
        for spec_path in spec_paths:
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=f"{spec_path}: {out.stderr}")
            self.assertIn("OK", out.stdout)

    def test_repo_tensor_m3_specs_validate(self) -> None:
        spec_paths = [
            REPO_ROOT / "tools" / "specs" / "tensor_m3_baseline_compat_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m3_onchip_capacity_nospill_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m3_onchip_capacity_spill_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m3_ring_chunked_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m3_ring_chunked_reduce_wait_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m3_ring_chunked_payload_first_tile_v3.json",
        ]
        for spec_path in spec_paths:
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=f"{spec_path}: {out.stderr}")
            self.assertIn("OK", out.stdout)

    def test_repo_tensor_m4_specs_validate(self) -> None:
        spec_paths = [
            REPO_ROOT / "tools" / "specs" / "tensor_m4_baseline_compat_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m4_bank_conflict_heavy_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m4_bank_conflict_relaxed_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m4_bank_conflict_queue_limited_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m4_collective_credit_off_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m4_collective_credit_hard_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m4_collective_credit_soft_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m4_collective_credit_payload_first_tile_v3.json",
        ]
        for spec_path in spec_paths:
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=f"{spec_path}: {out.stderr}")
            self.assertIn("OK", out.stdout)

    def test_repo_tensor_m5_specs_validate(self) -> None:
        spec_paths = [
            REPO_ROOT / "tools" / "specs" / "tensor_m5_credit_return_legacy_tick_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m5_credit_return_event_hard_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m5_credit_return_event_soft_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m5_credit_return_event_payload_first_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m5_credit_return_event_uncapped_tile_v3.json",
            REPO_ROOT / "tools" / "specs" / "tensor_m5_credit_return_event_stress_tile_v3.json",
        ]
        for spec_path in spec_paths:
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=f"{spec_path}: {out.stderr}")
            self.assertIn("OK", out.stdout)


if __name__ == "__main__":
    unittest.main()
