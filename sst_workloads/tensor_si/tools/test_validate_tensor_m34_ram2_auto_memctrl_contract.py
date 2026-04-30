#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m34_ram2_auto_memctrl_contract.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m34_ram2_auto_memctrl_contract.py"


class ValidateTensorM34Ram2AutoMemctrlContractTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            explicit = {
                "schema_version": 1,
                "tensor": {
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_program_dma_busy_cycles_total": 123,
                },
            }
            auto = {
                "schema_version": 1,
                "tensor": {
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_program_dma_busy_cycles_total": 123,
                },
            }
            exp_p = root / "explicit.json"
            auto_dir = root / "auto"
            auto_dir.mkdir(parents=True, exist_ok=True)
            auto_p = auto_dir / "auto.json"
            exp_p.write_text(json.dumps(explicit), encoding="utf-8")
            auto_p.write_text(json.dumps(auto), encoding="utf-8")
            (auto_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "tensor_cfg": {
                            "tensor_dma_hbm_channels": 4,
                            "tensor_dma_hbm_channel_interleave_bytes": 256,
                        }
                    }
                ),
                encoding="utf-8",
            )

            cmd = ["python3", str(SCRIPT), "--explicit", str(exp_p), "--auto", str(auto_p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m34:x]", out.stdout)

    def test_fails_when_dma_busy_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            explicit = {
                "schema_version": 1,
                "tensor": {
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_program_dma_busy_cycles_total": 10,
                },
            }
            auto = {
                "schema_version": 1,
                "tensor": {
                    "tensor_mem_bytes_read_total": 8192,
                    "tensor_program_dma_busy_cycles_total": 11,
                },
            }
            exp_p = root / "explicit.json"
            auto_dir = root / "auto"
            auto_dir.mkdir(parents=True, exist_ok=True)
            auto_p = auto_dir / "auto.json"
            exp_p.write_text(json.dumps(explicit), encoding="utf-8")
            auto_p.write_text(json.dumps(auto), encoding="utf-8")
            (auto_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "tensor_cfg": {
                            "tensor_dma_hbm_channels": 4,
                            "tensor_dma_hbm_channel_interleave_bytes": 256,
                        }
                    }
                ),
                encoding="utf-8",
            )

            cmd = ["python3", str(SCRIPT), "--explicit", str(exp_p), "--auto", str(auto_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected program_dma_busy_cycles_total match", out.stderr)


if __name__ == "__main__":
    unittest.main()

