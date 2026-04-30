#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m26_ram2_memctrl_channels_trends.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m26_ram2_memctrl_channels_trends.py"


class ValidateTensorM26Ram2MemctrlChannelsTrendsTest(unittest.TestCase):
    def _write_run(self, root: Path, name: str, dma_busy: int) -> Path:
        run_dir = root / name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "effective_config.json").write_text(
            json.dumps({"mesh_cfg": {"mem_backend": "ramulator2", "mem_backend_params": {"configFile": "x.cfg"}}}),
            encoding="utf-8",
        )
        p = run_dir / "essential_summary_tensor_mesh.json"
        p.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "tensor": {
                        "tensor_program_iters_total": 1,
                        "tensor_mem_bytes_read_total": 8192,
                        "tensor_program_dma_busy_cycles_total": dma_busy,
                    },
                }
            ),
            encoding="utf-8",
        )
        return p

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ch1 = self._write_run(root, "ch1", 900)
            ch4 = self._write_run(root, "ch4", 300)
            hot = self._write_run(root, "hot", 850)
            spread = self._write_run(root, "spread", 320)

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
            self.assertIn("[m26:x]", out.stdout)

    def test_fails_when_channels_not_faster(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ch1 = self._write_run(root, "ch1", 500)
            ch4 = self._write_run(root, "ch4", 700)
            hot = self._write_run(root, "hot", 800)
            spread = self._write_run(root, "spread", 600)

            cmd = ["python3", str(SCRIPT), "--ch1", str(ch1), "--ch4", str(ch4), "--hot", str(hot), "--spread", str(spread)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("dma_busy(4ch) < 1ch", out.stderr)


if __name__ == "__main__":
    unittest.main()

