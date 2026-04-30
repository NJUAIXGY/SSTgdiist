#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m23_hbm_channels_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m23_hbm_channels_trends.py"


class ValidateTensorM23HbmChannelsTrendsTest(unittest.TestCase):
    def _write_summary(self, root: Path, name: str, any_busy: int, dma_busy: int) -> Path:
        payload = {
            "schema_version": 1,
            "tensor": {
                "tensor_program_iters_total": 1,
                "tensor_mem_bytes_read_total": 65536,
                "tensor_program_any_busy_cycles_total": any_busy,
                "tensor_program_dma_busy_cycles_total": dma_busy,
            },
        }
        p = root / name
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ch1 = self._write_summary(root, "ch1.json", 300, 900)
            ch4 = self._write_summary(root, "ch4.json", 100, 900)
            hot = self._write_summary(root, "hot.json", 280, 900)
            spread = self._write_summary(root, "spread.json", 120, 900)

            cmd = [
                "python3",
                str(SCRIPT),
                "--ch1",
                str(ch1),
                "--ch4",
                str(ch4),
                "--hot",
                str(hot),
                "--spread",
                str(spread),
                "--label",
                "x",
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m23:x]", out.stdout)

    def test_fails_when_channels_not_faster(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ch1 = self._write_summary(root, "ch1.json", 200, 900)
            ch4 = self._write_summary(root, "ch4.json", 200, 900)
            hot = self._write_summary(root, "hot.json", 300, 900)
            spread = self._write_summary(root, "spread.json", 100, 900)

            cmd = [
                "python3",
                str(SCRIPT),
                "--ch1",
                str(ch1),
                "--ch4",
                str(ch4),
                "--hot",
                str(hot),
                "--spread",
                str(spread),
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("any_busy(4ch) < 1ch", out.stderr)


if __name__ == "__main__":
    unittest.main()
