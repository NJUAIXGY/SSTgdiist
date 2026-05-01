#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract tests for realism wiring in tools/run_snndl_regression_gate.sh."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
SCRIPT = REPO_ROOT / "tools" / "run_snndl_regression_gate.sh"


class RunSnndlRegressionGateRealismContractTest(unittest.TestCase):
    def test_realism_wiring_m47_to_m110(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8", errors="ignore")

        for gate in range(47, 111):
            code = gate - 16
            self.assertIn(f'm{gate}_report_dir=""', text)
            self.assertRegex(
                text,
                re.compile(
                    rf'm{gate}_report_dir="\$\(run_realism_gate "m{gate}" "\$REPO_ROOT/tools/run_tensor_m{gate}_gate\.sh" {code}\)"'
                ),
            )
            self.assertIn(f'echo "[gate] tensor_m{gate}_report_dir=\\\"$m{gate}_report_dir\\\""', text)


if __name__ == "__main__":
    unittest.main()
