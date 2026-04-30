#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for compare_tensor_readiness_drift.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "compare_tensor_readiness_drift.py"


class CompareTensorReadinessDriftTest(unittest.TestCase):
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

    def _candidate(self, score: float, dataflow: float, flags: list[str]) -> dict:
        return {
            "schema_version": 1,
            "scenario_count": 3,
            "capability_score_total_avg": score,
            "distance_to_target_avg": 25.0,
            "capability_score_breakdown_avg": {
                "scheduler": 60.0,
                "dataflow": dataflow,
                "memory": 70.0,
                "parallelism": 50.0,
                "scalability": 45.0,
            },
            "regression_drift_flags_union": flags,
        }

    def test_pass_case(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = root / "baseline.json"
            c = root / "candidate.json"
            o = root / "drift.json"
            b.write_text(json.dumps(self._baseline_spec()), encoding="utf-8")
            c.write_text(json.dumps(self._candidate(58.0, 51.0, ["x", "y"])), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--baseline-spec", str(b), "--candidate-report", str(c), "--out", str(o)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            report = json.loads(o.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "pass")

    def test_fail_case(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = root / "baseline.json"
            c = root / "candidate.json"
            o = root / "drift.json"
            b.write_text(json.dumps(self._baseline_spec()), encoding="utf-8")
            c.write_text(json.dumps(self._candidate(50.0, 40.0, ["x", "a", "b", "c"])), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--baseline-spec", str(b), "--candidate-report", str(c), "--out", str(o)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            report = json.loads(o.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "fail")
            self.assertGreater(len(report.get("violations", [])), 0)


if __name__ == "__main__":
    unittest.main()
