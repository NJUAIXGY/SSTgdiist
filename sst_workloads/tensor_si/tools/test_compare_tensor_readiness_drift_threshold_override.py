#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for compare_tensor_readiness_drift.py threshold override behavior."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "compare_tensor_readiness_drift.py"


class CompareTensorReadinessDriftThresholdOverrideTest(unittest.TestCase):
    def _baseline_spec(self) -> dict:
        return {
            "schema_version": 1,
            "baseline_id": "gold",
            "baseline_report_snapshot": {
                "capability_score_total_avg": 60.0,
                "distance_to_target_avg": 25.0,
                "capability_score_breakdown_avg": {
                    "scheduler": 60.0,
                    "dataflow": 55.0,
                    "memory": 70.0,
                    "parallelism": 50.0,
                    "scalability": 45.0,
                },
                "regression_drift_flags_union": ["x"],
            },
            "thresholds": {
                "score_total_delta_min": -3.0,
                "breakdown_delta_min": -5.0,
                "max_new_drift_flags": 2,
            },
        }

    def _candidate(self, *, score: float, scheduler: float, dataflow: float) -> dict:
        return {
            "schema_version": 1,
            "scenario_count": 3,
            "capability_score_total_avg": score,
            "distance_to_target_avg": 25.0,
            "capability_score_breakdown_avg": {
                "scheduler": scheduler,
                "dataflow": dataflow,
                "memory": 70.0,
                "parallelism": 50.0,
                "scalability": 45.0,
            },
            "regression_drift_flags_union": ["x"],
        }

    def test_override_makes_case_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            threshold = root / "threshold.json"
            out_path = root / "drift.json"

            baseline.write_text(json.dumps(self._baseline_spec()), encoding="utf-8")
            candidate.write_text(json.dumps(self._candidate(score=58.0, scheduler=60.0, dataflow=51.0)), encoding="utf-8")
            threshold.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "thresholds": {
                            "score_total_delta_min": -3.0,
                            "breakdown_delta_min": -2.0,
                            "max_new_drift_flags": 2,
                            "enforce_dimensions": ["dataflow"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            cmd = [
                "python3",
                str(SCRIPT),
                "--baseline-spec",
                str(baseline),
                "--threshold-spec",
                str(threshold),
                "--candidate-report",
                str(candidate),
                "--out",
                str(out_path),
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["thresholds"]["breakdown_delta_min"], -2.0)
            self.assertEqual(report["thresholds"]["enforce_dimensions"], ["dataflow"])

    def test_enforce_dimensions_filters_breakdown_checks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            threshold = root / "threshold.json"
            out_path = root / "drift.json"

            baseline.write_text(json.dumps(self._baseline_spec()), encoding="utf-8")
            candidate.write_text(json.dumps(self._candidate(score=58.0, scheduler=60.0, dataflow=40.0)), encoding="utf-8")
            threshold.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "score_total_delta_min": -3.0,
                        "breakdown_delta_min": -2.0,
                        "max_new_drift_flags": 2,
                        "enforce_dimensions": ["scheduler"],
                    }
                ),
                encoding="utf-8",
            )

            cmd = [
                "python3",
                str(SCRIPT),
                "--baseline-spec",
                str(baseline),
                "--threshold-spec",
                str(threshold),
                "--candidate-report",
                str(candidate),
                "--out",
                str(out_path),
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["thresholds"]["enforce_dimensions"], ["scheduler"])


if __name__ == "__main__":
    unittest.main()
