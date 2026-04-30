#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m46_multi_scenario_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m46_multi_scenario_contract.py"


class ValidateTensorM46MultiScenarioContractTest(unittest.TestCase):
    def _scenario(self, name: str, status: str = "pass") -> dict:
        return {
            "name": name,
            "status": status,
            "drift_status": "pass" if status == "pass" else "fail",
            "waived": status == "waived",
            "waiver_reason": "known" if status == "waived" else "",
            "waiver_expires_at": "2099-01-01" if status == "waived" else "",
            "candidate_report": f"/tmp/{name}_candidate.json",
            "drift_report": f"/tmp/{name}_drift.json",
            "patch_report": f"/tmp/{name}_patch.json",
            "candidate_score_total_avg": 63.0,
            "candidate_distance_to_target_avg": 22.0,
            "score_delta": 1.0,
            "distance_delta": -1.0,
            "new_drift_flags_count": 0,
            "drift_violations_count": 0,
            "drift_severity": "none",
        }

    def _report(self) -> dict:
        scenarios = [
            self._scenario("capability_baseline"),
            self._scenario("scheduler_aggressive"),
            self._scenario("mem_profile_server"),
            self._scenario("readiness_mix"),
        ]
        return {
            "schema_version": 1,
            "status": "pass",
            "scenario_count": 4,
            "pass_count": 4,
            "fail_count": 0,
            "waived_count": 0,
            "scenario_results": scenarios,
            "score_delta_summary": {"min": 0.5, "max": 1.5, "avg": 1.0},
            "distance_delta_summary": {"min": -1.5, "max": -0.5, "avg": -1.0},
            "new_drift_flags_total": 0,
            "failures": [],
            "waivers": [],
        }

    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "m46.json"
            report.write_text(json.dumps(self._report()), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--report",
                str(report),
                "--min-scenarios",
                "4",
                "--required-scenario",
                "capability_baseline",
                "--required-scenario",
                "scheduler_aggressive",
                "--required-scenario",
                "mem_profile_server",
                "--required-scenario",
                "readiness_mix",
                "--expect-pass",
                "1",
                "--label",
                "x",
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn("[m46:x]", proc.stdout)

    def test_fail_missing_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._report()
            payload["scenario_results"] = payload["scenario_results"][:-1]
            payload["scenario_count"] = 3
            payload["pass_count"] = 3
            report = root / "m46.json"
            report.write_text(json.dumps(payload), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--report",
                str(report),
                "--min-scenarios",
                "3",
                "--required-scenario",
                "readiness_mix",
                "--expect-pass",
                "0",
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("missing required scenario", proc.stderr)


if __name__ == "__main__":
    unittest.main()
