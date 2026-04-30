#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m44_frontend_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m44_frontend_contract.py"


class ValidateTensorM44FrontendContractTest(unittest.TestCase):
    def _summary(self) -> dict:
        return {
            "schema_version": 1,
            "run_dir": "/tmp/run",
            "sim_time_ns": 1000,
            "tensor": {
                "tensor_compute_cycles_total": 10,
            },
            "npu_tpu_readiness": {
                "capability_profile": "baseline_npu_like_v1",
                "scheduler_model": "legacy",
                "memory_hierarchy_profile": "balanced",
                "calibration_tag": "m44_tag",
                "capability_score_total": 66.0,
                "capability_score_breakdown": {
                    "scheduler": 70.0,
                    "dataflow": 61.0,
                    "memory": 72.0,
                    "parallelism": 58.0,
                    "scalability": 54.0,
                },
                "distance_to_target": 19.0,
                "target_score": 85.0,
                "gap_rank_topk": [
                    {"dimension": "scalability", "target": 85.0, "actual": 54.0, "gap": 31.0}
                ],
                "calibration_confidence": "medium",
                "regression_drift_flags": ["x"],
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "summary.json"
            p.write_text(json.dumps(self._summary()), encoding="utf-8")
            out = subprocess.run(["python3", str(SCRIPT), "--summary", str(p), "--label", "x"], text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m44:x]", out.stdout)

    def test_fail_missing_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = self._summary()
            payload.pop("npu_tpu_readiness", None)
            p = Path(td) / "summary.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            out = subprocess.run(["python3", str(SCRIPT), "--summary", str(p)], text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("missing npu_tpu_readiness", out.stderr)


if __name__ == "__main__":
    unittest.main()
