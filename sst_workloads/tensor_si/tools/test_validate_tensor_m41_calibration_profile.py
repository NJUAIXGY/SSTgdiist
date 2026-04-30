#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m41_calibration_profile.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
CALIB = THIS_DIR / "calibrate_tensor_memory_profile.py"
VALIDATE = THIS_DIR / "validate_tensor_m41_calibration_profile.py"


class ValidateTensorM41CalibrationProfileTest(unittest.TestCase):
    def _mk_summary(self, lat_total: int, lat_samples: int, dma_busy: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_read_latency_cycles_total": lat_total,
                "tensor_mem_read_latency_samples_total": lat_samples,
                "tensor_program_dma_busy_cycles_total": dma_busy,
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_p = root / "base.json"
            targ_p = root / "targ.json"
            prof_p = root / "profile.json"
            base_p.write_text(json.dumps(self._mk_summary(100, 20, 100)), encoding="utf-8")
            targ_p.write_text(json.dumps(self._mk_summary(250, 20, 180)), encoding="utf-8")

            gen = [
                "python3",
                str(CALIB),
                "--baseline",
                str(base_p),
                "--target",
                str(targ_p),
                "--out",
                str(prof_p),
                "--tag",
                "x",
            ]
            gen_out = subprocess.run(gen, text=True, capture_output=True)
            self.assertEqual(gen_out.returncode, 0, msg=gen_out.stderr)

            cmd = [
                "python3",
                str(VALIDATE),
                "--profile",
                str(prof_p),
                "--baseline",
                str(base_p),
                "--target",
                str(targ_p),
                "--label",
                "x",
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m41:x]", out.stdout)


if __name__ == "__main__":
    unittest.main()
