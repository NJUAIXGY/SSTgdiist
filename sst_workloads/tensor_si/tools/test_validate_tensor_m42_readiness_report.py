#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m42_readiness_report.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m42_readiness_report.py"


class ValidateTensorM42ReadinessReportTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = {
                "schema_version": 1,
                "scenario_count": 3,
                "scenarios": [
                    {"summary": "a", "score_total": 60.0, "distance_to_target": 25.0, "calibration_confidence": "low"},
                    {"summary": "b", "score_total": 65.0, "distance_to_target": 20.0, "calibration_confidence": "medium"},
                    {"summary": "c", "score_total": 70.0, "distance_to_target": 15.0, "calibration_confidence": "high"},
                ],
                "capability_score_total_avg": 65.0,
                "distance_to_target_avg": 20.0,
                "capability_score_breakdown_avg": {
                    "scheduler": 65.0,
                    "dataflow": 64.0,
                    "memory": 66.0,
                    "parallelism": 65.0,
                    "scalability": 65.0,
                },
                "top_gaps": [{"dimension": "memory", "gap_avg": 18.0}],
                "regression_drift_flags_union": ["x"],
                "calibration_confidence": "high",
                "readiness_level": "L1",
            }
            p = root / "r.json"
            p.write_text(json.dumps(report), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--report", str(p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m42:x]", out.stdout)

    def test_fail_when_scenarios_too_few(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = {
                "schema_version": 1,
                "scenario_count": 1,
                "scenarios": [{"summary": "a", "score_total": 60.0, "distance_to_target": 25.0, "calibration_confidence": "low"}],
                "capability_score_total_avg": 60.0,
                "distance_to_target_avg": 25.0,
                "capability_score_breakdown_avg": {"scheduler": 60.0},
                "top_gaps": [{"dimension": "scheduler", "gap_avg": 25.0}],
                "regression_drift_flags_union": [],
                "calibration_confidence": "low",
                "readiness_level": "L1",
            }
            p = root / "r.json"
            p.write_text(json.dumps(report), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--report", str(p), "--min-scenarios", "3"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("scenario_count too small", out.stderr)


if __name__ == "__main__":
    unittest.main()
