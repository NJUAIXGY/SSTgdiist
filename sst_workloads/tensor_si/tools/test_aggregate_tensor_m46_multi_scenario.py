#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for aggregate_tensor_m46_multi_scenario.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "aggregate_tensor_m46_multi_scenario.py"


class AggregateTensorM46MultiScenarioTest(unittest.TestCase):
    def _candidate(self, score: float, dist: float) -> dict:
        return {
            "schema_version": 1,
            "scenario_count": 1,
            "capability_score_total_avg": score,
            "distance_to_target_avg": dist,
            "capability_score_breakdown_avg": {
                "scheduler": score,
                "dataflow": score,
                "memory": score,
                "parallelism": score,
                "scalability": score,
            },
            "regression_drift_flags_union": [],
        }

    def _drift(self, *, status: str, score_delta: float, violations: int = 0) -> dict:
        return {
            "schema_version": 1,
            "baseline_id": "tensor_m42_golden_v1",
            "status": status,
            "severity": "none" if status == "pass" else "medium",
            "thresholds": {
                "score_total_delta_min": -2.0,
                "breakdown_delta_min": -4.0,
                "max_new_drift_flags": 1,
                "enforce_dimensions": ["scheduler", "dataflow", "memory", "parallelism", "scalability"],
            },
            "baseline_metrics": {
                "capability_score_total_avg": 62.264,
                "distance_to_target_avg": 22.736,
                "capability_score_breakdown_avg": {
                    "scheduler": 66.0,
                    "dataflow": 52.5,
                    "memory": 84.75,
                    "parallelism": 51.25,
                    "scalability": 42.594,
                },
                "regression_drift_flags_union": ["single_node_bandwidth_limited_proxy"],
            },
            "candidate_metrics": {
                "capability_score_total_avg": 62.264 + score_delta,
                "distance_to_target_avg": 22.736 - score_delta,
                "capability_score_breakdown_avg": {
                    "scheduler": 66.0,
                    "dataflow": 52.5,
                    "memory": 84.75,
                    "parallelism": 51.25,
                    "scalability": 42.594,
                },
                "regression_drift_flags_union": ["single_node_bandwidth_limited_proxy"],
            },
            "deltas": {
                "capability_score_total_avg": score_delta,
                "distance_to_target_avg": -score_delta,
                "capability_score_breakdown_avg": {
                    "scheduler": 0.0,
                    "dataflow": 0.0,
                    "memory": 0.0,
                    "parallelism": 0.0,
                    "scalability": 0.0,
                },
                "new_regression_drift_flags": [],
            },
            "violations": ([{"rule": "x"}] if violations > 0 else []),
        }

    def _patch(self, status: str = "pass") -> dict:
        return {
            "schema_version": 1,
            "status": status,
            "profile_confidence": "medium",
            "confidence_min": "low",
            "applied_change_count": 3,
            "applied_changes": [],
            "skipped_changes": [],
            "violations": [],
        }

    def test_pass_with_valid_waiver(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_report = root / "m46.json"
            results = root / "results.tsv"
            exceptions = root / "exceptions.json"

            a_c = root / "a_candidate.json"
            a_d = root / "a_drift.json"
            a_p = root / "a_patch.json"
            b_c = root / "b_candidate.json"
            b_d = root / "b_drift.json"
            b_p = root / "b_patch.json"

            a_c.write_text(json.dumps(self._candidate(65.0, 20.0)), encoding="utf-8")
            a_d.write_text(json.dumps(self._drift(status="pass", score_delta=2.0)), encoding="utf-8")
            a_p.write_text(json.dumps(self._patch()), encoding="utf-8")

            b_c.write_text(json.dumps(self._candidate(58.0, 27.0)), encoding="utf-8")
            b_d.write_text(json.dumps(self._drift(status="fail", score_delta=-4.0, violations=1)), encoding="utf-8")
            b_p.write_text(json.dumps(self._patch()), encoding="utf-8")

            results.write_text(
                "capability_baseline\t{}\t{}\t{}\nreadiness_mix\t{}\t{}\t{}\n".format(
                    a_c, a_d, a_p, b_c, b_d, b_p
                ),
                encoding="utf-8",
            )
            exceptions.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "waived_scenarios": [
                            {
                                "name": "readiness_mix",
                                "reason": "known_issue",
                                "expires_at": "2099-01-01",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            cmd = [
                "python3",
                str(SCRIPT),
                "--results-file",
                str(results),
                "--exceptions",
                str(exceptions),
                "--out",
                str(out_report),
                "--label",
                "x",
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(out_report.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["pass_count"], 1)
            self.assertEqual(payload["waived_count"], 1)
            self.assertEqual(payload["fail_count"], 0)
            self.assertIn("[m46:x]", proc.stdout)

    def test_fail_without_waiver(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_report = root / "m46.json"
            results = root / "results.tsv"
            exceptions = root / "exceptions.json"

            c = root / "candidate.json"
            d = root / "drift.json"
            p = root / "patch.json"
            c.write_text(json.dumps(self._candidate(58.0, 27.0)), encoding="utf-8")
            d.write_text(json.dumps(self._drift(status="fail", score_delta=-4.0, violations=1)), encoding="utf-8")
            p.write_text(json.dumps(self._patch()), encoding="utf-8")

            results.write_text(f"readiness_mix\t{c}\t{d}\t{p}\n", encoding="utf-8")
            exceptions.write_text(json.dumps({"schema_version": 1, "waived_scenarios": []}), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--results-file",
                str(results),
                "--exceptions",
                str(exceptions),
                "--out",
                str(out_report),
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(out_report.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["fail_count"], 1)


if __name__ == "__main__":
    unittest.main()
