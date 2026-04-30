#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for calibrate_tensor_memory_profile.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "calibrate_tensor_memory_profile.py"


class CalibrateTensorMemoryProfileTest(unittest.TestCase):
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
            out_p = root / "profile.json"
            base_p.write_text(json.dumps(self._mk_summary(100, 10, 100)), encoding="utf-8")
            targ_p.write_text(json.dumps(self._mk_summary(300, 10, 200)), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--baseline",
                str(base_p),
                "--target",
                str(targ_p),
                "--out",
                str(out_p),
                "--tag",
                "x",
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            payload = json.loads(out_p.read_text(encoding="utf-8"))
            self.assertEqual(payload["calibration_tag"], "x")
            self.assertAlmostEqual(float(payload["factors"]["read_latency_scale"]), 3.0, places=6)


if __name__ == "__main__":
    unittest.main()
