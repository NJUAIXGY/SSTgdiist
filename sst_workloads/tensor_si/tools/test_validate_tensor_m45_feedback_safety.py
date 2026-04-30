#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m45_feedback_safety.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m45_feedback_safety.py"


class ValidateTensorM45FeedbackSafetyTest(unittest.TestCase):
    def _whitelist(self) -> dict:
        return {
            "schema_version": 1,
            "confidence_min": "low",
            "allowed_paths": [
                "workload.params.tensor_calibration_tag",
                "workload.params.tensor_dma_bandwidth_bytes_per_cycle",
            ],
            "numeric_limits": {
                "workload.params.tensor_dma_bandwidth_bytes_per_cycle": {
                    "min": 64,
                    "max": 512,
                    "max_ratio": 1.2,
                }
            },
        }

    def _report(self) -> dict:
        return {
            "schema_version": 1,
            "status": "pass",
            "profile_confidence": "medium",
            "confidence_min": "low",
            "applied_changes": [
                {
                    "path": "workload.params.tensor_calibration_tag",
                    "old": "a",
                    "new": "b",
                    "reason": "calibration_tag",
                },
                {
                    "path": "workload.params.tensor_dma_bandwidth_bytes_per_cycle",
                    "old": 200,
                    "new": 220,
                    "reason": "mem_bandwidth_scale",
                },
            ],
            "violations": [],
        }

    def test_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whitelist = root / "whitelist.json"
            report = root / "report.json"
            whitelist.write_text(json.dumps(self._whitelist()), encoding="utf-8")
            report.write_text(json.dumps(self._report()), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--patch-report", str(report), "--whitelist", str(whitelist), "--label", "x"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m45:x]", out.stdout)

    def test_fail_when_path_not_whitelisted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            whitelist = root / "whitelist.json"
            report = root / "report.json"
            payload = self._report()
            payload["applied_changes"][0]["path"] = "workload.params.tensor_unknown"
            whitelist.write_text(json.dumps(self._whitelist()), encoding="utf-8")
            report.write_text(json.dumps(payload), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--patch-report", str(report), "--whitelist", str(whitelist)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("path not in whitelist", out.stderr)


if __name__ == "__main__":
    unittest.main()
