#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m63_regression_hardening.py."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m63_regression_hardening.py"


class ValidateTensorM63RegressionHardeningTest(unittest.TestCase):
    def _minimal(self) -> str:
        lines = []
        for gate in range(47, 111):
            fail_code = gate - 16
            lines.append(f'm{gate}_report_dir=""')
            lines.append(
                f'm{gate}_report_dir="$(run_realism_gate "m{gate}" "$REPO_ROOT/tools/run_tensor_m{gate}_gate.sh" {fail_code})"'
            )
            lines.append(f'echo "[gate] tensor_m{gate}_report_dir=\\"$m{gate}_report_dir\\""')
        return "\n".join(lines) + "\n"

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "gate.sh"
            p.write_text(self._minimal(), encoding="utf-8")
            out = subprocess.run(["python3", str(SCRIPT), "--script", str(p)], text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_missing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "gate.sh"
            txt = self._minimal().replace('m110_report_dir=""\n', '')
            p.write_text(txt, encoding="utf-8")
            out = subprocess.run(["python3", str(SCRIPT), "--script", str(p)], text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("m110_report_dir", out.stderr)

    def test_accepts_unescaped_echo_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "gate.sh"
            txt = self._minimal().replace('\\"$m47_report_dir\\"', '"$m47_report_dir"')
            p.write_text(txt, encoding="utf-8")
            out = subprocess.run(["python3", str(SCRIPT), "--script", str(p)], text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)


if __name__ == "__main__":
    unittest.main()
