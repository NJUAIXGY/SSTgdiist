#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI tests for tools/run_tensor_m40_gate.sh."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
SCRIPT = REPO_ROOT / "tools" / "run_tensor_m40_gate.sh"


class RunTensorM40GateTest(unittest.TestCase):
    def test_help(self) -> None:
        out = subprocess.run(["bash", str(SCRIPT), "--help"], text=True, capture_output=True, cwd=str(REPO_ROOT))
        self.assertEqual(out.returncode, 0, msg=out.stderr)
        self.assertIn("run_tensor_m40_gate.sh", out.stdout)

    def test_unknown_arg(self) -> None:
        out = subprocess.run(["bash", str(SCRIPT), "--unknown"], text=True, capture_output=True, cwd=str(REPO_ROOT))
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("unknown arg", out.stderr)


if __name__ == "__main__":
    unittest.main()
