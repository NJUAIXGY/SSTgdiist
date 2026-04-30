#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m37_capability_matrix.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m37_capability_matrix.py"


class ValidateTensorM37CapabilityMatrixTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = {
                "schema_version": 1,
                "tensor": {"tensor_capability_score_total": 72.5},
                "npu_tpu_readiness": {
                    "capability_score_total": 72.5,
                    "capability_score_breakdown": {
                        "scheduler": 70.0,
                        "dataflow": 68.0,
                        "memory": 75.0,
                        "parallelism": 74.0,
                        "scalability": 72.0,
                    },
                    "distance_to_target": 12.5,
                    "gap_rank_topk": [
                        {"dimension": "dataflow", "target": 85.0, "actual": 68.0, "gap": 17.0},
                        {"dimension": "scheduler", "target": 85.0, "actual": 70.0, "gap": 15.0},
                        {"dimension": "scalability", "target": 85.0, "actual": 72.0, "gap": 13.0},
                    ],
                    "calibration_confidence": "low",
                    "regression_drift_flags": ["single_node_bandwidth_limited_proxy"],
                },
            }
            matrix = {
                "schema_version": 1,
                "dimensions": [
                    {"name": "scheduler", "weight": 0.25, "target": 85.0},
                    {"name": "dataflow", "weight": 0.2, "target": 85.0},
                    {"name": "memory", "weight": 0.25, "target": 85.0},
                    {"name": "parallelism", "weight": 0.15, "target": 85.0},
                    {"name": "scalability", "weight": 0.15, "target": 85.0},
                ],
            }
            sp = root / "summary.json"
            mp = root / "matrix.json"
            sp.write_text(json.dumps(summary), encoding="utf-8")
            mp.write_text(json.dumps(matrix), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--summary", str(sp), "--matrix", str(mp), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m37:x]", out.stdout)

    def test_fail_when_missing_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = {
                "schema_version": 1,
                "tensor": {},
                "npu_tpu_readiness": {
                    "capability_score_total": 70,
                    "capability_score_breakdown": {
                        "scheduler": 70,
                        "dataflow": 70,
                        "memory": 70,
                        "parallelism": 70,
                        "scalability": 70,
                    },
                    "distance_to_target": 10,
                    "gap_rank_topk": [{"dimension": "memory", "gap": 15}],
                    "calibration_confidence": "low",
                    "regression_drift_flags": [],
                },
            }
            matrix = {"schema_version": 1, "dimensions": [{"name": "scheduler", "weight": 1.0, "target": 85.0}]}
            sp = root / "summary.json"
            mp = root / "matrix.json"
            sp.write_text(json.dumps(summary), encoding="utf-8")
            mp.write_text(json.dumps(matrix), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--summary", str(sp), "--matrix", str(mp)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected >=5 capability dimensions", out.stderr)


if __name__ == "__main__":
    unittest.main()
