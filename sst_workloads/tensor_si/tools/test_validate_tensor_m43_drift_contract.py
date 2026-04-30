#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m43_drift_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m43_drift_contract.py"


class ValidateTensorM43DriftContractTest(unittest.TestCase):
    def _report(self, status: str) -> dict:
        return {
            "schema_version": 1,
            "baseline_id": "gold",
            "status": status,
            "severity": "none" if status == "pass" else "medium",
            "thresholds": {
                "score_total_delta_min": -3.0,
                "breakdown_delta_min": -5.0,
                "max_new_drift_flags": 2,
            },
            "deltas": {
                "capability_score_total_avg": -1.0,
                "distance_to_target_avg": 1.0,
                "capability_score_breakdown_avg": {"scheduler": -1.0},
                "new_regression_drift_flags": [],
            },
            "violations": [] if status == "pass" else [{"rule": "x"}],
        }

    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.json"
            p.write_text(json.dumps(self._report("pass")), encoding="utf-8")
            out = subprocess.run(["python3", str(SCRIPT), "--drift-report", str(p), "--label", "x"], text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m43:x]", out.stdout)

    def test_fail_when_expect_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.json"
            p.write_text(json.dumps(self._report("fail")), encoding="utf-8")
            out = subprocess.run(["python3", str(SCRIPT), "--drift-report", str(p)], text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected pass", out.stderr)


if __name__ == "__main__":
    unittest.main()
