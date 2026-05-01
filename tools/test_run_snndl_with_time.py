#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI tests for tools/run_snndl_with_time.sh.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
SCRIPT = REPO_ROOT / "tools" / "run_snndl_with_time.sh"


class RunSnndlWithTimeTest(unittest.TestCase):
    def test_help(self) -> None:
        cmd = ["bash", str(SCRIPT), "--help"]
        out = subprocess.run(cmd, text=True, capture_output=True, cwd=str(REPO_ROOT))
        self.assertEqual(out.returncode, 0, msg=out.stderr)
        self.assertIn("run_snndl_with_time.sh", out.stdout)


if __name__ == "__main__":
    unittest.main()
