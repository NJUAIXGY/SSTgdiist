#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for apply_tensor_calibration_feedback.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "apply_tensor_calibration_feedback.py"


class ApplyTensorCalibrationFeedbackTest(unittest.TestCase):
    def _source_spec(self) -> dict:
        return {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "params": {
                    "tensor_memory_hierarchy_profile": "balanced",
                    "tensor_calibration_tag": "old_tag",
                    "tensor_dma_bandwidth_bytes_per_cycle": 200,
                    "tensor_dma_shared_bandwidth_bytes_per_cycle": 200,
                    "tensor_dma_hbm_channel_bandwidth_bytes_per_cycle": 50,
                }
            },
        }

    def _profile(self, confidence: str = "medium") -> dict:
        return {
            "schema_version": 1,
            "calibration_tag": "m41_calib_v1",
            "confidence": confidence,
            "suggested_profile": "server",
            "factors": {
                "suggested_mem_bandwidth_scale": 1.1,
            },
        }

    def _whitelist(self, confidence_min: str = "low") -> dict:
        return {
            "schema_version": 1,
            "confidence_min": confidence_min,
            "allowed_profiles": ["balanced", "server"],
            "allowed_paths": [
                "workload.params.tensor_memory_hierarchy_profile",
                "workload.params.tensor_calibration_tag",
                "workload.params.tensor_dma_bandwidth_bytes_per_cycle",
                "workload.params.tensor_dma_shared_bandwidth_bytes_per_cycle",
                "workload.params.tensor_dma_hbm_channel_bandwidth_bytes_per_cycle",
            ],
            "numeric_limits": {
                "workload.params.tensor_dma_bandwidth_bytes_per_cycle": {"min": 64, "max": 512, "max_ratio": 1.2},
                "workload.params.tensor_dma_shared_bandwidth_bytes_per_cycle": {"min": 64, "max": 512, "max_ratio": 1.2},
                "workload.params.tensor_dma_hbm_channel_bandwidth_bytes_per_cycle": {
                    "min": 32,
                    "max": 256,
                    "max_ratio": 1.2,
                },
            },
        }

    def test_apply_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.json"
            profile = root / "profile.json"
            whitelist = root / "whitelist.json"
            out = root / "patched.json"
            report = root / "patch_report.json"

            source.write_text(json.dumps(self._source_spec()), encoding="utf-8")
            profile.write_text(json.dumps(self._profile("medium")), encoding="utf-8")
            whitelist.write_text(json.dumps(self._whitelist("low")), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--source-spec",
                str(source),
                "--profile",
                str(profile),
                "--whitelist",
                str(whitelist),
                "--out",
                str(out),
                "--patch-report",
                str(report),
                "--label",
                "x",
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)

            patched = json.loads(out.read_text(encoding="utf-8"))
            params = patched["workload"]["params"]
            self.assertEqual(params["tensor_memory_hierarchy_profile"], "server")
            self.assertEqual(params["tensor_calibration_tag"], "m41_calib_v1")

            rep = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(rep["status"], "pass")
            self.assertGreaterEqual(rep["applied_change_count"], 2)
            self.assertIn("[m45:x]", proc.stdout)

    def test_fail_when_confidence_too_low(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.json"
            profile = root / "profile.json"
            whitelist = root / "whitelist.json"
            out = root / "patched.json"
            report = root / "patch_report.json"

            source.write_text(json.dumps(self._source_spec()), encoding="utf-8")
            profile.write_text(json.dumps(self._profile("low")), encoding="utf-8")
            whitelist.write_text(json.dumps(self._whitelist("high")), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--source-spec",
                str(source),
                "--profile",
                str(profile),
                "--whitelist",
                str(whitelist),
                "--out",
                str(out),
                "--patch-report",
                str(report),
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(proc.returncode, 0)
            rep = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(rep["status"], "fail")
            self.assertGreater(len(rep.get("violations", [])), 0)


if __name__ == "__main__":
    unittest.main()
